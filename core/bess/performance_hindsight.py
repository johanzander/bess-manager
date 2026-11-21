"""Read-only retrospective analysis of persisted quarter-hour observations.

No controller or HA client is accepted here. The live DP and its flow/economic
models are reused unchanged; a terminal penalty targets the observed end energy.
Results are withheld if replay cannot meet that boundary or reproduce economics.
"""

import json
from dataclasses import asdict, fields, replace
from datetime import date, datetime, timedelta
from itertools import pairwise
from math import isfinite
from pathlib import Path
from time import perf_counter
from typing import Any

from . import time_utils
from .daily_view_store import DailyViewStore
from .dp_battery_algorithm import optimize_battery_schedule, period_import_caps_kwh
from .execution_model import DEFAULT_CAPABILITIES, PlatformCapabilities
from .huawei_controller import HuaweiController
from .models import EconomicData, PeriodData
from .price_manager import MockSource, PriceManager
from .savings_aggregator import _month_bounds, _week_bounds
from .settings import BatterySettings, HomeSettings
from .simulation.inverter_simulator import (
    derive_control_command,
    simulate,
    simulate_physical_plan,
)
from .terminal_value import TerminalValueCurve

HUAWEI_PLATFORM = "huawei_solar_luna2000"
ENERGY_TOLERANCE_KWH = 0.2  # Independent cumulative meters' existing tolerance.
TERMINAL_TOLERANCE_KWH = 1e-6
# Energy lattice of the production DP; a closing state can miss by up to one step.
DP_ENERGY_STEP_KWH = 0.1
# SOC sensors report whole percent, so two readings can disagree by one step
# of capacity without any energy having moved.
SOC_REPORTING_STEP = 0.01
# Published day-ahead prices have 0.01 EUR/MWh resolution; stored retail prices
# derived from them by the configured formula agree to well within this.
PRICE_REFERENCE_TOLERANCE = 1e-4
# Discharge per quarter above meter noise, so it counts as delivered energy.
BACKUP_DISCHARGE_KWH = 0.05
_ENERGY_KEYS = (
    "solar_production",
    "home_consumption",
    "battery_charged",
    "battery_discharged",
    "grid_imported",
    "grid_exported",
    "clipped_solar",
)


def _soe_tolerance(settings: BatterySettings) -> float:
    return ENERGY_TOLERANCE_KWH + settings.total_capacity * SOC_REPORTING_STEP


def historical_context(
    battery: BatterySettings,
    home: HomeSettings,
    capabilities: PlatformCapabilities,
    *,
    unsupported_constraints: bool = False,
    platform: str | None = None,
) -> dict[str, Any]:
    """Freeze the model used when an observation is collected, not when queried."""
    return {
        "platform": platform,
        "battery": {
            f.name: battery.__dict__[f.name] for f in fields(battery) if f.init
        },
        "home": asdict(home),
        "capabilities": {
            **capabilities.__dict__,
            "intent_to_mode": dict(capabilities.intent_to_mode),
        },
        "currency": home.currency,
        "timezone": str(time_utils.TIMEZONE),
        "unsupported_constraints": unsupported_constraints,
        "solar_basis": "delivered",
        "configuration_source": "recorded at observation collection",
    }


def _period_issues(
    p: PeriodData, previous: PeriodData | None, settings: BatterySettings
) -> set[str]:
    e = p.energy
    issues = set()
    if p.data_source != "actual":
        issues.add("Forecast or missing quarters are excluded.")
    if e.observation_verified is not True:
        issues.add(
            "Meter/SOC provenance is unverified (legacy, missing or estimated readings)."
        )
    if p.economic.prices_verified is not True:
        issues.add(
            "Historical import/export price coverage is unverified; zero is not assumed to be a price."
        )
    amounts = [
        e.solar_production,
        e.home_consumption,
        e.battery_charged,
        e.battery_discharged,
        e.grid_imported,
        e.grid_exported,
        e.clipped_solar,
        e.battery_soe_start,
        e.battery_soe_end,
    ]
    if any(
        not isinstance(v, (int, float)) or not isfinite(v) or v < 0 for v in amounts
    ) or any(
        not isinstance(v, (int, float)) or not isfinite(v)
        for v in (p.economic.buy_price, p.economic.sell_price)
    ):
        issues.add("Nonfinite prices or invalid energy measurements.")
        return issues
    balance = (
        e.solar_production
        - e.clipped_solar
        + e.grid_imported
        + e.battery_discharged
        - e.home_consumption
        - e.grid_exported
        - e.battery_charged
    )
    home_balance = (
        e.solar_to_home + e.battery_to_home + e.grid_to_home - e.home_consumption
    )
    export_balance = e.solar_to_grid + e.battery_to_grid - e.grid_exported
    if max(abs(balance), abs(home_balance), abs(export_balance)) > ENERGY_TOLERANCE_KWH:
        issues.add("Energy meters or detailed household/export flows do not reconcile.")
    if (
        previous
        and _soc_available(previous, settings.min_soe_kwh)
        and abs(previous.energy.battery_soe_end - e.battery_soe_start)
        > _soe_tolerance(settings)
    ):
        issues.add("Battery SOC has gaps between quarters or days.")
    if not (
        settings.min_soe_kwh - 1e-6
        <= e.battery_soe_start
        <= settings.max_soe_kwh + 1e-6
        and settings.min_soe_kwh - 1e-6
        <= e.battery_soe_end
        <= settings.max_soe_kwh + 1e-6
    ):
        issues.add("Observed battery energy is outside the historical model limits.")
    expected_delta = (
        e.battery_charged * settings.efficiency_charge
        - e.battery_discharged / settings.efficiency_discharge
    )
    if abs(e.soe_change_kwh - expected_delta) > _soe_tolerance(settings):
        issues.add(
            "Battery SOC changes do not reconcile with measured charge/discharge and efficiency."
        )
    return issues


PERIOD_BOUNDS = {"week": _week_bounds, "month": _month_bounds}


def available_periods(
    store: DailyViewStore,
    today: date | None = None,
    include_current: bool = False,
    period: str = "week",
) -> list[date]:
    """Weeks (or months) containing history, newest first; completed unless asked."""
    reference = today or time_utils.today()
    bounds = PERIOD_BOUNDS[period]
    return sorted(
        {
            bounds(date.fromisoformat(d))[0]
            for d in store.list_available_dates()
            if bounds(date.fromisoformat(d))[1] < reference
            or (include_current and bounds(date.fromisoformat(d))[0] <= reference)
        },
        reverse=True,
    )


def _summary(periods: list[PeriodData]) -> dict[str, Any]:
    grid = sum(p.economic.grid_cost for p in periods)
    wear = sum(p.economic.battery_cycle_cost for p in periods)
    solar = sum(p.energy.solar_production for p in periods)
    solar_export = sum(p.energy.solar_to_grid for p in periods)
    clipped = sum(p.energy.clipped_solar for p in periods)
    charged = sum(p.energy.battery_charged for p in periods)
    discharged = sum(p.energy.battery_discharged for p in periods)
    return {
        "grid_import_kwh": sum(p.energy.grid_imported for p in periods),
        "grid_export_kwh": sum(p.energy.grid_exported for p in periods),
        "import_cost": sum(p.economic.import_cost for p in periods),
        "export_revenue": sum(p.economic.export_revenue for p in periods),
        "net_grid_cost": grid,
        "wear_cost": wear,
        "total_economic_cost": grid + wear,
        "charged_kwh": charged,
        "discharged_kwh": discharged,
        "throughput_kwh": charged + discharged,
        "solar_export_kwh": solar_export,
        "solar_self_consumption_percent": (
            100 * (solar - clipped - solar_export) / (solar - clipped)
            if solar > clipped
            else None
        ),
    }


def economic_comparison(
    solar_cost: float,
    actual_cost: float,
    optimal_cost: float,
) -> tuple[float, float | None]:
    """Comparable total costs; out-of-range capture is evidence, not clipped UI."""
    achievable = solar_cost - optimal_cost
    captured = (
        100 * (solar_cost - actual_cost) / achievable if achievable > 1e-9 else None
    )
    return actual_cost - optimal_cost, captured


def solve_hindsight(
    periods: list[PeriodData],
    context: dict[str, Any],
    terminal_energy_kwh: float | None = None,
) -> tuple[list[PeriodData], dict[str, float]]:
    """One continuous horizon, with simulator verification and no hardware access.

    A terminal lower bound prevents funding savings by emptying the battery.
    The finite-grid model may leave extra energy, which receives no financial
    credit. The lower bound is checked after replay. No daily resets are used.
    """
    battery = BatterySettings(**context["battery"])
    # The production DP prices stored kWh; retrospective comparisons price
    # input-side charge throughput, as historical EconomicData does. This copy
    # converts the coefficient without changing the production optimizer.
    objective_battery = replace(
        battery,
        cycle_cost_per_kwh=battery.cycle_cost_per_kwh / battery.efficiency_charge,
    )
    home = HomeSettings(**context["home"])
    capabilities = PlatformCapabilities(**context["capabilities"])
    buy = [p.economic.buy_price for p in periods]
    sell = [p.economic.sell_price for p in periods]
    demand = [p.energy.home_consumption for p in periods]
    solar = [p.energy.solar_production for p in periods]
    initial = periods[0].energy.battery_soe_start
    target = (
        periods[-1].energy.battery_soe_end
        if terminal_energy_kwh is None
        else terminal_energy_kwh
    )
    penalty = (
        1
        + sum(
            abs(b) + abs(s) + battery.cycle_cost_per_kwh
            for b, s in zip(buy, sell, strict=True)
        )
    ) / min(battery.efficiency_charge, battery.efficiency_discharge)
    curve = TerminalValueCurve(penalty, target - battery.min_soe_kwh, 0.0)
    started = perf_counter()
    plan = optimize_battery_schedule(
        buy,
        sell,
        demand,
        objective_battery,
        solar_production=solar,
        initial_soe=initial,
        terminal_curve=curve,
        currency=context["currency"],
        capabilities=capabilities,
        home_settings=home,
    )
    elapsed = perf_counter() - started
    # The current simulator models Growatt MIN TOU semantics only. Other platforms
    # must not acquire a hardware-faithfulness claim from this replay.
    simulator_capabilities = replace(
        DEFAULT_CAPABILITIES,
        discharge_resolution_kw=capabilities.discharge_resolution_kw,
    )
    import_caps = period_import_caps_kwh(home, None, len(periods), 0.25)
    if capabilities != simulator_capabilities or capabilities.discharge_rate_step_kw(
        battery
    ) != DEFAULT_CAPABILITIES.discharge_rate_step_kw(battery):
        replay = simulate_physical_plan(
            plan.period_data,
            solar,
            demand,
            buy,
            sell,
            initial,
            battery,
            0.25,
            context["currency"],
            import_caps,
        )
        return replay.period_data, {
            "solve_seconds": elapsed,
            "simulation_cost_difference": float("nan"),
            "physics_replay_cost_difference": replay.realized_cost
            - sum(p.economic.hourly_cost for p in plan.period_data),
            "plan_soe_drift_kwh": max(
                abs(a.energy.battery_soe_end - b.energy.battery_soe_end)
                for a, b in zip(plan.period_data, replay.period_data, strict=True)
            ),
            "import_constraint_violation_kwh": (
                max(
                    (
                        max(0, p.energy.grid_imported - cap) if cap is not None else 0
                        for p, cap in zip(replay.period_data, import_caps, strict=True)
                    ),
                    default=0,
                )
                if import_caps is not None
                else 0
            ),
        }
    commands = []
    for p in plan.period_data:
        action = p.decision.battery_action
        assert action is not None
        commands.append(
            derive_control_command(
                p.decision.strategic_intent,
                action / 0.25,
                battery,
                intra_period_discharge_allowed=p.decision.intra_period_discharge_allowed,
                planned_grid_imported_kwh=p.energy.grid_imported,
            )
        )
    replay = simulate(
        commands,
        solar,
        demand,
        buy,
        sell,
        initial,
        objective_battery,
        0.25,
        currency=context["currency"],
        import_cap_kwh=import_caps,
    )
    delta = replay.realized_cost - sum(p.economic.hourly_cost for p in plan.period_data)
    trajectory_error = max(
        abs(a.energy.battery_soe_end - b.energy.battery_soe_end)
        for a, b in zip(replay.period_data, plan.period_data, strict=True)
    )
    import_violation = (
        max(
            max(0, p.energy.grid_imported - cap) if cap is not None else 0
            for p, cap in zip(replay.period_data, import_caps, strict=True)
        )
        if import_caps is not None
        else 0.0
    )
    return replay.period_data, {
        "solve_seconds": elapsed,
        "simulation_cost_difference": delta,
        "simulation_trajectory_error_kwh": trajectory_error,
        "import_constraint_violation_kwh": import_violation,
    }


def retrospective_context(
    settings: dict[str, Any], source: str, timezone: str
) -> dict[str, Any]:
    """Build an explicitly approved assumption profile, never current settings."""
    required = {
        "total_capacity",
        "min_soc",
        "max_soc",
        "max_charge_power_kw",
        "max_discharge_power_kw",
        "efficiency_charge",
        "efficiency_discharge",
        "cycle_cost_per_kwh",
    }
    if not required <= settings["battery"].keys():
        raise ValueError("The assumption backup lacks required battery parameters")
    if (
        "currency" not in settings["home"]
        or "power_monitoring_enabled" not in settings["home"]
    ):
        raise ValueError(
            "The assumption backup lacks currency or import-constraint configuration"
        )
    battery = BatterySettings(
        **{
            f.name: settings["battery"][f.name]
            for f in fields(BatterySettings)
            if f.init and f.name in settings["battery"]
        }
    )
    home = HomeSettings(
        **{
            f.name: settings["home"][f.name]
            for f in fields(HomeSettings)
            if f.init and f.name in settings["home"]
        }
    )
    if settings["inverter"]["platform"] != "huawei_solar_luna2000":
        raise ValueError(
            "This retrospective backup profile supports Huawei LUNA2000 declarations only"
        )
    # Construction reads declarations only; no HA client is passed or contacted.
    capabilities = PlatformCapabilities.from_controller(
        HuaweiController(battery), battery
    )
    context = historical_context(
        battery,
        home,
        capabilities,
        platform=settings["inverter"]["platform"],
        unsupported_constraints=bool(
            battery.export_curtailment_enabled
            or settings["battery"].get("temperature_derating", {}).get("enabled", False)
        ),
    )
    context.update(
        timezone=timezone,
        assumption_source=source,
        configuration_source="user-approved backup assumption",
    )
    return context


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
    )


def _energy_available(p: PeriodData) -> bool:
    return all(
        _finite(p.energy.__dict__[key]) and p.energy.__dict__[key] >= 0
        for key in _ENERGY_KEYS
    )


def _soc_available(p: PeriodData, reserve_kwh: float) -> bool:
    values = (p.energy.battery_soe_start, p.energy.battery_soe_end)
    if not all(_finite(value) and value >= 0 for value in values):
        return False
    # Legacy collection stored an 'unavailable' SOC sensor as exactly 0 %
    # (logged at a restart, with no matching discharge). A battery with a
    # non-zero reserve cannot read 0, so that value is unknown, not empty.
    # Verified readings come from the recorder and are trusted as recorded.
    return (
        p.energy.observation_verified is True or reserve_kwh <= 0 or 0.0 not in values
    )


def _restart_placeholder(p: PeriodData, day: date, index: int) -> bool:
    """A legacy row the restart recovery wrote as zero energy long afterwards.

    Such a row is not an observation: no meter was read for that quarter.
    """
    return (
        p.energy.observation_verified is not True
        and p.timestamp is not None
        and p.timestamp.tzinfo is not None
        and p.timestamp >= time_utils.period_start(day, index + 2)
        and all(p.energy.__dict__[key] == 0 for key in _ENERGY_KEYS)
    )


def published_price_reference(
    directory: Path,
    electricity_price: dict[str, Any],
    days: list[date],
) -> dict[str, Any]:
    """Retail prices rebuilt from Nord Pool data-portal day-ahead files.

    The configured price formula is applied by the production PriceManager, so
    only the spot input differs from what the live system would have stored.
    Files are ``<area>-<CET delivery date>.json`` responses of the public
    DayAheadPrices endpoint; each local day spans two CET delivery dates.
    """
    area = electricity_price["area"]
    spot: dict[float, float] = {}
    files = []
    for path in sorted(directory.glob(f"{area}-*.json")):
        files.append(path.name)
        for entry in json.loads(path.read_text(encoding="utf-8"))["multiAreaEntries"]:
            start = datetime.fromisoformat(
                entry["deliveryStart"].replace("Z", "+00:00")
            )
            spot[start.timestamp()] = entry["entryPerArea"][area] / 1000
    prices: dict[str, tuple[float, float]] = {}
    for day in days:
        starts = [
            time_utils.period_start(day, index)
            for index in range(time_utils.get_period_count(day))
        ]
        if not all(start.timestamp() in spot for start in starts):
            continue
        manager = PriceManager(
            MockSource([spot[start.timestamp()] for start in starts]),
            markup_rate=electricity_price["markup_rate"],
            vat_multiplier=electricity_price["vat_multiplier"],
            additional_costs=electricity_price["additional_costs"],
            tax_reduction=electricity_price["tax_reduction"],
            area=area,
            spot_multiplier=electricity_price["spot_multiplier"],
            export_spot_multiplier=electricity_price["export_spot_multiplier"],
            grid_tariff_hourly=electricity_price["grid_tariff_hourly"],
            grid_tariff_summer_hourly=electricity_price["grid_tariff_summer_hourly"],
        )
        for start, row in zip(starts, manager.get_price_data(day), strict=True):
            prices[start.isoformat()] = (row["buyPrice"], row["sellPrice"])
    return {
        "source": f"Nord Pool day-ahead {area} ({', '.join(files)}) with the assumption profile's price formula",
        "prices": prices,
    }


def huawei_tou_replay(
    optimal: list[PeriodData],
    actual: list[PeriodData],
    context: dict[str, Any],
) -> tuple[list[PeriodData], dict[str, int]]:
    """Execute the relaxed schedule's intents the way a Huawei period list would.

    Observed LUNA2000 behaviour and the controller's semantics: a charge period
    grid-charges at full power until the SOC limit, a discharge period covers
    household load without exporting, and outside both the battery only absorbs
    PV surplus. Blocks beyond the period-list limit are dropped exactly as the
    controller drops them. The result is a feasible schedule, not an optimum.
    """
    battery = BatterySettings(**context["battery"])
    controller = HuaweiController(battery)
    blocks_per_day: dict[str, int] = {}
    modes: dict[tuple[date, int], str] = {}
    days = sorted({p.timestamp.date() for p in actual if p.timestamp is not None})
    for day in days:
        intents = {
            p.period: o.decision.strategic_intent
            for p, o in zip(actual, optimal, strict=True)
            if p.timestamp is not None and p.timestamp.date() == day
        }
        block_count, kept = controller.period_list_for_intents(
            [
                intents.get(index, "UNKNOWN")
                for index in range(time_utils.get_period_count(day))
            ]
        )
        blocks_per_day[day.isoformat()] = block_count
        for block in kept:
            for index in range(block["start_period"], block["end_period"] + 1):
                modes[(day, index)] = block["flag"]
    actions = []
    for p in actual:
        assert p.timestamp is not None
        mode = modes.get((p.timestamp.date(), p.period))
        net_load = max(0.0, p.energy.home_consumption - p.energy.solar_production)
        if mode == "+":
            actions.append(battery.max_charge_power_kw * 0.25)
        elif mode == "-":
            actions.append(-min(net_load, battery.max_discharge_power_kw * 0.25))
        else:
            actions.append(0.0)
    planned = [
        replace(
            o,
            decision=replace(
                o.decision,
                battery_action=action,
                strategic_intent=(
                    "IDLE" if action == 0 else o.decision.strategic_intent
                ),
            ),
        )
        for o, action in zip(optimal, actions, strict=True)
    ]
    replay = simulate_physical_plan(
        planned,
        [p.energy.solar_production for p in actual],
        [p.energy.home_consumption for p in actual],
        [p.economic.buy_price for p in actual],
        [p.economic.sell_price for p in actual],
        actual[0].energy.battery_soe_start,
        battery,
        0.25,
        context["currency"],
        period_import_caps_kwh(
            HomeSettings(**context["home"]), None, len(actual), 0.25
        ),
    )
    return replay.period_data, blocks_per_day


def calibrate_efficiency(
    periods: list[PeriodData], battery: BatterySettings
) -> dict[str, Any]:
    """Charge/discharge efficiencies implied by the measured battery history.

    Over each run of consecutive observed quarters, stored energy changes by
    eta_c * charged - discharged / eta_d. Summing the runs gives one equation;
    the configured ratio eta_c / eta_d is kept and both are scaled by one
    factor, capped at 1. SOC is read in whole percent, so only a throughput of
    at least two full capacities is precise enough to use.
    """
    charged = discharged = stored = 0.0
    run: list[PeriodData] = []

    def close(run: list[PeriodData]) -> None:
        nonlocal charged, discharged, stored
        if run and all(
            _soc_available(p, battery.min_soe_kwh) for p in (run[0], run[-1])
        ):
            charged += sum(p.energy.battery_charged for p in run)
            discharged += sum(p.energy.battery_discharged for p in run)
            stored += run[-1].energy.battery_soe_end - run[0].energy.battery_soe_start

    previous: datetime | None = None
    for p in periods:
        assert p.timestamp is not None
        if previous is not None and p.timestamp - previous != timedelta(
            minutes=time_utils.INTERVAL_MINUTES
        ):
            close(run)
            run = []
        previous = p.timestamp
        run.append(p)
    close(run)
    result: dict[str, Any] = {
        "configured_charge": battery.efficiency_charge,
        "configured_discharge": battery.efficiency_discharge,
        "charged_kwh": charged,
        "discharged_kwh": discharged,
        "stored_change_kwh": stored,
        "applied": False,
    }
    if charged + discharged < 2 * battery.total_capacity or charged <= 0:
        result["reason"] = "too little battery throughput to calibrate"
        return result
    a, b = battery.efficiency_charge, battery.efficiency_discharge
    # a*C*k^2 - S*k - D/b = 0, positive root.
    k = (stored + (stored**2 + 4 * a * charged * discharged / b) ** 0.5) / (
        2 * a * charged
    )
    result.update(
        charge=min(1.0, a * k),
        discharge=min(1.0, b * k),
        capped=a * k > 1 or b * k > 1,
        applied=True,
    )
    return result


def calibrate_capacity(
    periods: list[PeriodData], battery: BatterySettings
) -> dict[str, Any]:
    """Usable capacity and efficiency implied by one-way battery movements.

    Recorded battery energy is SOC % times the configured capacity, so a
    wrong capacity scales every stored-energy change by one factor f. Each
    run of quarters that only charges (or only discharges) gives
    f * recorded_change = eta_c * charged - discharged / eta_d; with both
    kinds present, f and a common efficiency scale k are identifiable and are
    fitted by least squares (configured eta_c / eta_d ratio kept, each capped
    at 1). Runs under 1 kWh of throughput are too coarse for whole-percent SOC.
    """
    segments: list[tuple[float, float, float]] = []
    run: list[PeriodData] = []
    direction = 0

    def close() -> None:
        if run and all(
            _soc_available(q, battery.min_soe_kwh) for q in (run[0], run[-1])
        ):
            charged = sum(q.energy.battery_charged for q in run)
            discharged = sum(q.energy.battery_discharged for q in run)
            if charged + discharged >= 1.0:
                segments.append(
                    (
                        run[-1].energy.battery_soe_end
                        - run[0].energy.battery_soe_start,
                        charged,
                        discharged,
                    )
                )

    previous: datetime | None = None
    for p in periods:
        assert p.timestamp is not None
        net = p.energy.battery_charged - p.energy.battery_discharged
        sign = 1 if net > 0.01 else -1 if net < -0.01 else 0
        contiguous = previous is not None and p.timestamp - previous == timedelta(
            minutes=time_utils.INTERVAL_MINUTES
        )
        if not contiguous or sign != direction:
            close()
            run = []
        direction = sign
        previous = p.timestamp
        if sign != 0:
            run.append(p)
    close()
    charging = [seg for seg in segments if seg[0] > 0]
    discharging = [seg for seg in segments if seg[0] < 0]
    result: dict[str, Any] = {
        "configured_capacity_kwh": battery.total_capacity,
        "charging_runs": len(charging),
        "discharging_runs": len(discharging),
        "applied": False,
    }
    if len(charging) < 3 or len(discharging) < 3:
        result["reason"] = "too few one-way charge and discharge runs"
        return result
    a, b = battery.efficiency_charge, battery.efficiency_discharge
    best: tuple[float, float, float] | None = None
    k = 0.8
    while k <= 1 / max(a, b) + 1e-9:
        targets = [a * k * c - d / (b * k) for _, c, d in segments]
        recorded = [seg[0] for seg in segments]
        f = sum(r * t for r, t in zip(recorded, targets, strict=True)) / sum(
            r * r for r in recorded
        )
        residual = sum((f * r - t) ** 2 for r, t in zip(recorded, targets, strict=True))
        if best is None or residual < best[0]:
            best = (residual, f, k)
        k += 0.0005
    assert best is not None
    _, f, k = best
    if not 0.8 <= f <= 1.25:
        result.update(reason=f"fitted capacity factor {f:.2f} is implausible", factor=f)
        return result
    result.update(
        factor=f,
        capacity_kwh=battery.total_capacity * f,
        charge=min(1.0, a * k),
        discharge=min(1.0, b * k),
        capped=k >= 1 / max(a, b) - 0.001,
        applied=True,
    )
    return result


def _physics_diagnostics(
    periods: list[PeriodData], battery: BatterySettings
) -> dict[str, Any]:
    balance = [
        abs(
            p.energy.solar_production
            - p.energy.clipped_solar
            + p.energy.grid_imported
            + p.energy.battery_discharged
            - p.energy.home_consumption
            - p.energy.grid_exported
            - p.energy.battery_charged
        )
        for p in periods
    ]
    soe = [
        abs(
            p.energy.soe_change_kwh
            - p.energy.battery_charged * battery.efficiency_charge
            + p.energy.battery_discharged / battery.efficiency_discharge
        )
        for p in periods
    ]
    return {
        "max_energy_balance_error_kwh": max(balance),
        "max_soe_accounting_error_kwh": max(soe),
        "energy_balance_mismatches": sum(v > ENERGY_TOLERANCE_KWH for v in balance),
        "soe_accounting_mismatches": sum(v > _soe_tolerance(battery) for v in soe),
        "operational_soc_violations": sum(
            not (
                battery.min_soe_kwh - 1e-6
                <= p.energy.battery_soe_start
                <= battery.max_soe_kwh + 1e-6
                and battery.min_soe_kwh - 1e-6
                <= p.energy.battery_soe_end
                <= battery.max_soe_kwh + 1e-6
            )
            for p in periods
        ),
        "charge_power_violations": sum(
            p.energy.battery_charged > battery.max_charge_power_kw * 0.25 + 1e-6
            for p in periods
        ),
        "discharge_power_violations": sum(
            p.energy.battery_discharged > battery.max_discharge_power_kw * 0.25 + 1e-6
            for p in periods
        ),
        "minimum_energy_kwh": min(p.energy.battery_soe_end for p in periods),
        "maximum_energy_kwh": max(p.energy.battery_soe_end for p in periods),
    }


def analyze_period(
    store: DailyViewStore,
    anchor: date,
    *,
    today: date | None = None,
    mode: str = "verified",
    assumed_context: dict[str, Any] | None = None,
    allow_partial: bool = False,
    price_reference: dict[str, Any] | None = None,
    efficiency_source: str | None = None,
    period: str = "week",
) -> dict[str, Any]:
    """Validate independently; estimated observations never become verified data.

    Partial analysis excludes unknown energy quarters completely. Across each
    excluded interval the model holds its battery energy unchanged, which only
    restricts it (it can never fund savings from a gap); the measured battery
    energy on both sides of every gap is reported so a biased comparison is
    visible. External energy/cost there is unknown, not zero, and no
    complete-week score is published.

    A published ``price_reference`` independently confirms each stored price it
    matches. In estimated mode the analysis is priced from the reference, so a
    stored forecast never becomes the historical bill; in verified mode any
    mismatch blocks the comparison.
    """
    if mode not in ("verified", "estimated"):
        raise ValueError("Unknown historical analysis mode")
    if mode == "estimated" and assumed_context is None:
        raise ValueError(
            "Estimated mode requires an explicitly approved assumption context"
        )
    reference = price_reference["prices"] if price_reference is not None else None
    start, end = PERIOD_BOUNDS[period](anchor)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    # A week still in progress is analyzed up to its last ended quarter; later
    # quarters have not happened yet, so they are neither expected nor gaps.
    cutoff = time_utils.now() if today is None else time_utils.period_start(today, 0)
    in_progress = time_utils.period_start(end + timedelta(days=1), 0) > cutoff
    elapsed = {
        day: sum(
            time_utils.period_start(day, index + 1) <= cutoff
            for index in range(time_utils.get_period_count(day))
        )
        for day in days
    }
    expected = sum(elapsed.values())
    counts: dict[str, Any] = dict.fromkeys(
        (
            "actual_periods",
            "predicted_periods",
            "missing_periods",
            "invalid_records",
            "energy_available",
            "energy_verified",
            "prices_available",
            "prices_verified",
            "soc_available",
            "soc_verified",
            "configuration_recorded",
            "capabilities_recorded",
            "constraints_recorded",
            "timezone_mismatches",
            "configuration_assumed",
            "capabilities_assumed",
            "restart_placeholders",
            "soc_dropouts",
            "below_reserve_periods",
            "prices_reference_confirmed",
            "prices_reference_mismatched",
            "prices_reference_missing",
        ),
        0,
    )
    counts["price_reference_max_difference"] = None
    counts["optimizer_feasible"] = None
    response: dict[str, Any] = {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "timezone": str(time_utils.TIMEZONE),
        "currency": None,
        "mode": mode,
        "expected_periods": expected,
        "verified_periods": 0,
        "coverage_percent": 0,
        "status": "insufficient_data",
        "scope": "full_week",
        "diagnostics": counts,
        "issues": [],
        "warnings": [],
        "assumptions": None,
        "actual": None,
        "solar_only": None,
        "grid_only": None,
        "optimal": None,
        "captured_percent": None,
        "conditional_captured_percent": None,
        "missed_savings": None,
        "model_cost_difference": None,
        "daily": [],
        "periods": [],
        "excluded_intervals": [],
        "gap_boundaries": [],
        "price_reference_source": (
            price_reference["source"] if price_reference is not None else None
        ),
        "available_periods": [
            d.isoformat()
            for d in available_periods(
                store, today, include_current=True, period=period
            )
        ],
        "period": period,
        "in_progress": in_progress,
    }
    issues: set[str] = set()
    warnings: set[str] = set()
    if expected == 0:
        issues.add("This week has no completed quarters yet.")
    if in_progress:
        warnings.add(
            "Week in progress: only quarters that have ended are analyzed; the comparison ends at the last of them, and figures will change as the week completes."
        )
    periods: list[PeriodData] = []
    price_rows: list[dict[str, Any]] = []
    contexts = []
    structural_issues: set[str] = set()
    assumed_battery = (
        BatterySettings(**assumed_context["battery"])
        if mode == "estimated" and assumed_context is not None
        else None
    )
    for day in days:
        count = elapsed[day]
        view = store.load_day(day)
        by_index: dict[int, list[PeriodData]] = {}
        if view is not None:
            if view.date != day:
                structural_issues.add(
                    "Stored calendar date does not match its historical file."
                )
            for p in view.periods:
                by_index.setdefault(p.period, []).append(p)
        for index in range(count):
            group = by_index.get(index, [])
            reason = "missing"
            if len(group) != 1:
                counts["missing_periods"] += not group
                counts["invalid_records"] += len(group) if group else 0
                if group:
                    structural_issues.add("Duplicate historical quarter indices.")
            else:
                p = group[0]
                prices_ok = all(
                    _finite(v) for v in (p.economic.buy_price, p.economic.sell_price)
                )
                confirmed = False
                if reference is not None:
                    published = reference.get(
                        time_utils.period_start(day, index).isoformat()
                    )
                    if published is None:
                        # Outside the reference's coverage the recorded
                        # price stays as recorded, unconfirmed and counted.
                        counts["prices_reference_missing"] += 1
                    else:
                        if prices_ok:
                            difference = max(
                                abs(p.economic.buy_price - published[0]),
                                abs(p.economic.sell_price - published[1]),
                            )
                            counts["price_reference_max_difference"] = max(
                                difference,
                                counts["price_reference_max_difference"] or 0.0,
                            )
                            confirmed = difference <= PRICE_REFERENCE_TOLERANCE
                        counts["prices_reference_confirmed"] += confirmed
                        counts["prices_reference_mismatched"] += not confirmed
                        if mode == "estimated" or confirmed:
                            p = replace(
                                p,
                                economic=replace(
                                    p.economic,
                                    buy_price=published[0],
                                    sell_price=published[1],
                                    prices_verified=(
                                        True
                                        if confirmed
                                        else p.economic.prices_verified
                                    ),
                                ),
                            )
                            prices_ok = True
                counts["prices_available"] += prices_ok
                if prices_ok:
                    price_rows.append(
                        {
                            "timestamp": time_utils.period_start(
                                day, index
                            ).isoformat(),
                            "buy_price": p.economic.buy_price,
                            "sell_price": p.economic.sell_price,
                        }
                    )
                counts["prices_verified"] += (
                    prices_ok and p.economic.prices_verified is True
                )
                if p.historical_inputs is not None:
                    counts["configuration_recorded"] += 1
                    counts["capabilities_recorded"] += (
                        "capabilities" in p.historical_inputs
                    )
                    counts["constraints_recorded"] += (
                        p.historical_inputs.get("unsupported_constraints") is False
                    )
                if p.data_source == "predicted":
                    counts["predicted_periods"] += 1
                    reason = "predicted energy excluded"
                elif p.data_source != "actual":
                    counts["missing_periods"] += 1
                elif _restart_placeholder(p, day, index):
                    counts["restart_placeholders"] += 1
                    reason = "zero-filled restart placeholder, not an observation"
                else:
                    counts["actual_periods"] += 1
                    energy_ok = _energy_available(p)
                    recorded_battery = (
                        BatterySettings(**p.historical_inputs["battery"])
                        if p.historical_inputs is not None
                        else None
                    )
                    reference_battery = assumed_battery or recorded_battery
                    soc_ok = _soc_available(
                        p,
                        (
                            reference_battery.min_soe_kwh
                            if reference_battery is not None
                            else 0.0
                        ),
                    )
                    counts["energy_available"] += energy_ok
                    counts["energy_verified"] += (
                        energy_ok and p.energy.observation_verified is True
                    )
                    counts["soc_available"] += soc_ok
                    counts["soc_dropouts"] += energy_ok and not soc_ok
                    counts["soc_verified"] += (
                        soc_ok and p.energy.observation_verified is True
                    )
                    counts["invalid_records"] += not (energy_ok and prices_ok)
                    # Below the configured reserve the battery was serving
                    # backup (an outage) or a lower inverter cutoff. Hindsight
                    # may never use that energy, so such quarters are left out
                    # of both sides rather than counted for or against BESS.
                    # Only energy actually delivered from inside the reserve
                    # is backup use; idle readings a few percent under it are
                    # standby drift and whole-percent rounding.
                    below_reserve = (
                        soc_ok
                        and reference_battery is not None
                        and p.energy.battery_discharged > BACKUP_DISCHARGE_KWH
                        and p.energy.battery_soe_end
                        < reference_battery.min_soe_kwh
                        - reference_battery.total_capacity * SOC_REPORTING_STEP
                        - 1e-6
                    )
                    counts["below_reserve_periods"] += below_reserve
                    if below_reserve:
                        reason = "battery below the configured reserve (backup use)"
                    elif energy_ok and prices_ok:
                        if p.timestamp is None or p.timestamp.tzinfo is None:
                            warnings.add(
                                "Some collection timestamps are unverified; day/quarter indices supply the historical boundaries."
                            )
                        elif p.timestamp.utcoffset() not in (
                            time_utils.period_start(day, index).utcoffset(),
                            time_utils.period_start(day, index + 1).utcoffset(),
                        ):
                            counts["timezone_mismatches"] += 1
                        periods.append(
                            replace(p, timestamp=time_utils.period_start(day, index))
                        )
                        contexts.append(p.historical_inputs)
                        continue
                    else:
                        reason = "invalid energy or prices"
            response["excluded_intervals"].append(
                {
                    "date": day.isoformat(),
                    "period": index,
                    "timestamp": time_utils.period_start(day, index).isoformat(),
                    "reason": reason,
                }
            )
    context = (
        assumed_context
        if mode == "estimated"
        else next((c for c in contexts if c is not None), None)
    )
    response["coverage_percent"] = 100 * counts["energy_available"] / expected
    if counts["timezone_mismatches"]:
        issues.add(
            "Historical timestamp offsets disagree with the configured local timezone."
        )
    if context is None:
        issues.add(
            "Historical battery configuration/capabilities were not recorded; current settings are not substituted."
        )
    else:
        response["currency"] = context["currency"]
        if mode == "estimated":
            counts["configuration_assumed"] = len(periods)
            counts["capabilities_assumed"] = len(periods)
            response["assumptions"] = {
                "source": context["assumption_source"],
                "battery": context["battery"],
                "capabilities": context["capabilities"],
                "timezone": context["timezone"],
            }
        if context["timezone"] != str(time_utils.TIMEZONE):
            issues.add(
                "The model timezone differs from the configured historical timezone."
            )
        if context["unsupported_constraints"]:
            issues.add(
                "Historical derating, peak/session constraints or curtailment are not reconstructible."
            )
    if structural_issues:
        issues.update(structural_issues)
    gaps = len(response["excluded_intervals"])
    if gaps and not (mode == "estimated" and allow_partial):
        issues.add(
            f"{gaps} quarters lack actual energy or valid prices. Predictions are not observations."
        )
    if counts["prices_reference_mismatched"] and mode == "verified":
        issues.add(
            f"{counts['prices_reference_mismatched']} recorded prices differ from the published reference; recorded prices cannot be confirmed."
        )
    if not periods:
        issues.add("No usable actual energy/price observations are available.")
    if context is None or issues:
        response["issues"] = sorted(issues)
        return response
    battery = BatterySettings(**context["battery"])
    if mode == "estimated" and efficiency_source is not None:
        capacity = calibrate_capacity(periods, battery)
        capacity["source"] = efficiency_source
        response["capacity_calibration"] = capacity
        if capacity["applied"]:
            factor = capacity["factor"]
            # Every recorded energy is SOC % times the configured capacity.
            periods = [
                replace(
                    p,
                    energy=replace(
                        p.energy,
                        battery_soe_start=p.energy.battery_soe_start * factor,
                        battery_soe_end=p.energy.battery_soe_end * factor,
                    ),
                )
                for p in periods
            ]
            context = {
                **context,
                "battery": {
                    **context["battery"],
                    "total_capacity": capacity["capacity_kwh"],
                },
            }
            battery = BatterySettings(**context["battery"])
            warnings.add(
                f"Usable capacity calibrated from {efficiency_source}: {capacity['capacity_kwh']:.1f} kWh (configured {capacity['configured_capacity_kwh']:g} kWh), from {capacity['charging_runs']} charging and {capacity['discharging_runs']} discharging runs."
            )
        calibration = calibrate_efficiency(periods, battery)
        calibration["source"] = efficiency_source
        response["efficiency_calibration"] = calibration
        if calibration["applied"]:
            context = {
                **context,
                "battery": {
                    **context["battery"],
                    "efficiency_charge": calibration["charge"],
                    "efficiency_discharge": calibration["discharge"],
                },
            }
            battery = BatterySettings(**context["battery"])
            warnings.add(
                f"Battery efficiency calibrated from {efficiency_source}: {calibration['charge'] * 100:.1f} % charge / {calibration['discharge'] * 100:.1f} % discharge (configured {calibration['configured_charge'] * 100:.1f} % / {calibration['configured_discharge'] * 100:.1f} %)."
                + (
                    " The measured history implies more than 100 %; capped at 100 %, so meter or SOC readings disagree."
                    if calibration["capped"]
                    else ""
                )
            )
    if not (
        0 < battery.efficiency_charge <= 1 and 0 < battery.efficiency_discharge <= 1
    ):
        response["issues"] = ["Invalid battery efficiency in the historical model."]
        return response
    if context["battery"]["inverter_max_ac_power_kw"] > 0 or any(
        p.energy.clipped_solar > 0 for p in periods
    ):
        response["issues"] = [
            "Available solar under clipping/curtailment cannot be reconstructed from delivered PV."
        ]
        return response
    previous = None
    for p, recorded in zip(periods, contexts, strict=True):
        found = (
            _period_issues(p, previous, battery)
            if _soc_available(p, battery.min_soe_kwh)
            else {"Battery SOC is unavailable in some observed quarters."}
        )
        if recorded is None:
            found.add("Historical configuration provenance is unavailable.")
        elif mode == "verified" and recorded != context:
            found.add("Historical configuration changed during the comparison period.")
        if not found:
            response["verified_periods"] += 1
        if mode == "verified":
            issues.update(found)
        else:
            warnings.update(found)
        previous = p
    if mode == "verified" and issues:
        response["issues"] = sorted(issues)
        return response
    if not (
        _soc_available(periods[0], battery.min_soe_kwh)
        and _soc_available(periods[-1], battery.min_soe_kwh)
    ):
        response["issues"] = [
            "Measured opening and closing battery energy are required."
        ]
        return response
    # SOC is read in whole percent, so a reading one step under the reserve is
    # the reserve within resolution, not a violation.
    # Boundary readings under the reserve are idle drift (backup use is
    # excluded above); the model itself always starts and ends at or above it.
    if not (
        periods[0].energy.battery_soe_start <= battery.max_soe_kwh
        and periods[-1].energy.battery_soe_end <= battery.max_soe_kwh
    ):
        response["issues"] = [
            "Opening or closing measured energy is outside the approved battery model; no clamping is permitted."
        ]
        return response
    if mode == "estimated":
        counts["configuration_assumed"] = len(periods)
        counts["capabilities_assumed"] = len(periods)
        response["assumptions"] = {
            "source": context["assumption_source"],
            "battery": context["battery"],
            "capabilities": context["capabilities"],
            "timezone": context["timezone"],
        }
        warnings.add(
            "Estimated Historical: approved backup settings and declared capabilities are assumptions, not verified historical configuration."
        )
    for before, after in pairwise(periods):
        assert before.timestamp is not None and after.timestamp is not None
        if after.timestamp - before.timestamp == timedelta(
            minutes=time_utils.INTERVAL_MINUTES
        ):
            continue
        change = (
            after.energy.battery_soe_start - before.energy.battery_soe_end
            if _soc_available(before, battery.min_soe_kwh)
            and _soc_available(after, battery.min_soe_kwh)
            else None
        )
        response["gap_boundaries"].append(
            {
                "after": before.timestamp.isoformat(),
                "resumes": after.timestamp.isoformat(),
                "measured_energy_change_kwh": change,
            }
        )
        if change is None or abs(change) > battery.total_capacity * SOC_REPORTING_STEP:
            warnings.add(
                "Measured battery energy changed, or is unknown, across an excluded interval; the observed-interval comparison omits that energy movement."
            )
    if reference is not None and mode == "estimated":
        warnings.add(
            f"Prices: {counts['prices_reference_confirmed']} recorded quarters match the published day-ahead reference; {counts['prices_reference_mismatched']} differ and are repriced from it; {counts['prices_reference_missing']} have no reference and keep their unconfirmed recorded price. Tariff components come from the assumption profile."
        )
    if counts["restart_placeholders"]:
        warnings.add(
            f"{counts['restart_placeholders']} zero-filled restart placeholder quarters are excluded as unknown."
        )
    if counts["below_reserve_periods"]:
        warnings.add(
            f"{counts['below_reserve_periods']} quarters with the battery below the configured reserve (backup use during an outage, or a lower inverter cutoff) are left out of both sides; hindsight never uses the reserve."
        )
    if counts["soc_dropouts"]:
        warnings.add(
            f"{counts['soc_dropouts']} quarters recorded an unavailable SOC sensor as 0 %; their SOC is shown as unknown."
        )
    warnings.update(
        {
            "Delivered solar is fixed input; unmeasured available PV under clipping or curtailment cannot be reconstructed.",
            "The existing DP uses a 0.1 kWh energy grid and hardware candidates; it is not a certified continuous physical optimum.",
            "Detailed measured source flows use EnergyData allocation priorities, not separate source meters.",
        }
    )
    if gaps:
        response["scope"] = "observed_intervals"
        warnings.add(
            f"Observed intervals only: {len(periods)}/{expected}. Unknown quarters are excluded, not zero-filled. The hypothetical battery holds energy through gaps; gap household energy/cost is unknown. Full-week savings and capture are withheld."
        )
    # Every scenario is driven by the household demand the grid, battery and PV
    # meters imply, so replaying the actual battery operation reproduces the
    # measured bill. A separate consumption meter that disagrees (inverter
    # losses, unmetered loads) would otherwise be billed to hindsight only.
    balanced = [
        replace(
            p,
            energy=replace(
                p.energy,
                home_consumption=max(
                    0.0,
                    p.energy.grid_imported
                    - p.energy.grid_exported
                    + p.energy.solar_production
                    - p.energy.clipped_solar
                    + p.energy.battery_discharged
                    - p.energy.battery_charged,
                ),
            ),
        )
        for p in periods
    ]
    meter_gap = sum(p.energy.home_consumption for p in periods) - sum(
        p.energy.home_consumption for p in balanced
    )
    if abs(meter_gap) > ENERGY_TOLERANCE_KWH:
        warnings.add(
            f"Household demand is taken from the grid, battery and PV meters; the separate consumption meter differs by {meter_gap:+.1f} kWh over the analyzed quarters."
        )
    actual = [
        replace(
            p,
            economic=replace(
                EconomicData.from_energy_data(
                    p.energy,
                    p.economic.buy_price,
                    p.economic.sell_price,
                    p.energy.battery_charged * battery.cycle_cost_per_kwh,
                ),
                prices_verified=p.economic.prices_verified,
            ),
        )
        for p in balanced
    ]
    actual_physics = _physics_diagnostics(
        [p for p in actual if _soc_available(p, battery.min_soe_kwh)], battery
    )
    response["actual_validation"] = actual_physics
    if actual_physics["operational_soc_violations"]:
        warnings.add(
            f'{actual_physics["operational_soc_violations"]} actual SOC intervals violate the approved model limits; historical limits may differ or SOC observations may be unreliable.'
        )
    terminal_energy = actual[-1].energy.battery_soe_end
    assert actual[-1].timestamp is not None
    terminal_timestamp = time_utils.period_start(
        actual[-1].timestamp.date(), actual[-1].period + 1
    )
    terminal_evidence = "last observed quarter closing battery energy"
    following = store.load_day(end + timedelta(days=1)) if gaps else None
    if following is not None:
        opening = next(
            (
                p
                for p in following.periods
                if p.period == 0
                and p.data_source == "actual"
                and _soc_available(p, battery.min_soe_kwh)
            ),
            None,
        )
        if opening is not None:
            terminal_energy = opening.energy.battery_soe_start
            terminal_timestamp = time_utils.period_start(end + timedelta(days=1), 0)
            terminal_evidence = (
                f"{following.date.isoformat()} actual period 0 opening battery energy"
            )
    if terminal_energy < battery.min_soe_kwh:
        warnings.add(
            "The closing reading is under the reserve; hindsight must end at the reserve, which slightly favours actual."
        )
        terminal_energy = battery.min_soe_kwh
    if not battery.min_soe_kwh <= terminal_energy <= battery.max_soe_kwh:
        response["issues"] = [
            "Observed terminal boundary energy is outside the approved battery model."
        ]
        return response
    model_input = actual
    if actual[0].energy.battery_soe_start < battery.min_soe_kwh:
        # A whole-percent reading just under the reserve: the model starts at
        # the reserve itself, never inside it.
        model_input = [
            replace(
                actual[0],
                energy=replace(actual[0].energy, battery_soe_start=battery.min_soe_kwh),
            ),
            *actual[1:],
        ]
        warnings.add(
            f"The opening reading is {battery.min_soe_kwh - actual[0].energy.battery_soe_start:.2f} kWh under the reserve; hindsight starts at the reserve."
        )
    optimal, solver = solve_hindsight(model_input, context, terminal_energy)
    response.update(solver)
    replay_ok = (
        isfinite(solver["simulation_cost_difference"])
        and abs(solver["simulation_cost_difference"]) <= 0.01
        and solver.get("simulation_trajectory_error_kwh", 0) <= TERMINAL_TOLERANCE_KWH
    )
    if not isfinite(solver["simulation_cost_difference"]):
        response["simulation_cost_difference"] = None
    terminal_delta = optimal[-1].energy.battery_soe_end - terminal_energy
    model_physics = _physics_diagnostics(optimal, battery)
    model_ok = (
        terminal_delta >= -DP_ENERGY_STEP_KWH
        and model_physics["max_energy_balance_error_kwh"] < 1e-6
        and model_physics["max_soe_accounting_error_kwh"] < 1e-6
        and not model_physics["operational_soc_violations"]
        and not model_physics["charge_power_violations"]
        and not model_physics["discharge_power_violations"]
        and solver.get("import_constraint_violation_kwh", 0) <= 1e-6
    )
    counts["optimizer_feasible"] = model_ok
    response.update(
        model_validation=model_physics,
        execution_verified=replay_ok,
        terminal_difference_kwh=terminal_delta,
        initial_energy_kwh=actual[0].energy.battery_soe_start,
        terminal_energy_kwh=terminal_energy,
        terminal_timestamp=terminal_timestamp.isoformat(),
        terminal_evidence=terminal_evidence,
        model_terminal_energy_kwh=optimal[-1].energy.battery_soe_end,
        terminal_policy="at least measured closing energy; excess stored energy receives no cost credit",
    )
    first_timestamp = actual[0].timestamp
    last_timestamp = actual[-1].timestamp
    assert first_timestamp is not None and last_timestamp is not None
    response.update(
        comparison_start=first_timestamp.isoformat(),
        comparison_end=(last_timestamp + timedelta(minutes=15)).isoformat(),
    )
    if not model_ok or (mode == "verified" and not replay_ok):
        response["status"] = "unsupported_model"
        response["issues"] = [
            "The model violates physical/terminal constraints or lacks a verified inverter execution replay. Savings comparison withheld."
        ]
        return response
    if not replay_ok:
        warnings.add(
            "Inverter execution of the hindsight schedule is not independently verified: period-list behavior and load support are unmodelled. These are planned physical-model costs, not certified realizable savings."
        )
    if solver.get("plan_soe_drift_kwh", 0) > 1e-6:
        warnings.add(
            "The raw DP trajectory contained a state discontinuity. Reported model flows and continuous SOC were recomputed by physical replay; exact global optimality is not established."
        )
    huawei: list[PeriodData] | None = None
    # Only Huawei's period-list semantics are modelled (observed on LUNA2000);
    # other period-list platforms keep the relaxed bound alone.
    if "platform" in context and context["platform"] == HUAWEI_PLATFORM:
        huawei, block_counts = huawei_tou_replay(optimal, model_input, context)
        response["huawei_tou_blocks"] = block_counts
        if any(v > HuaweiController.MAX_TOU_PERIODS for v in block_counts.values()):
            warnings.add(
                "The relaxed schedule exceeds Huawei's daily TOU period-list limit; the Huawei replay drops the shortest blocks as the controller would."
            )
        huawei_summary = _summary(huawei)
        huawei_terminal = huawei[-1].energy.battery_soe_end
        huawei_summary.update(
            initial_soc=huawei[0].energy.battery_soe_start
            / battery.total_capacity
            * 100,
            final_soc=huawei_terminal / battery.total_capacity * 100,
            terminal_shortfall_kwh=max(0.0, terminal_energy - huawei_terminal),
            comparable=huawei_terminal >= terminal_energy - TERMINAL_TOLERANCE_KWH,
        )
        # Missing closing energy is charged at the window's dearest import
        # price plus wear, per stored kWh: no schedule could restore it for
        # less, so the adjusted figure never flatters the Huawei replay.
        huawei_summary["terminal_adjusted_total_cost"] = (
            huawei_summary["total_economic_cost"]
            + huawei_summary["terminal_shortfall_kwh"]
            * (max(p.economic.buy_price for p in actual) + battery.cycle_cost_per_kwh)
            / battery.efficiency_charge
        )
        response["huawei_feasible"] = huawei_summary
        if not huawei_summary["comparable"]:
            warnings.add(
                "The Huawei-semantics replay ends below the measured closing battery energy; its terminal-adjusted cost prices the shortfall at the window's highest import price."
            )
    actual_summary = _summary(actual)
    optimal_summary = _summary(optimal)
    if terminal_delta < 0:
        # The DP's 0.1 kWh lattice can land just under the closing energy; the
        # missing energy is charged to hindsight at the dearest import price.
        shortfall_cost = (
            -terminal_delta
            * (max(p.economic.buy_price for p in actual) + battery.cycle_cost_per_kwh)
            / battery.efficiency_charge
        )
        optimal_summary["total_economic_cost"] += shortfall_cost
        optimal_summary["terminal_shortfall_cost"] = shortfall_cost
    actual_summary.update(
        initial_soc=actual[0].energy.battery_soe_start / battery.total_capacity * 100,
        final_soc=terminal_energy / battery.total_capacity * 100,
    )
    optimal_summary.update(
        initial_soc=optimal[0].energy.battery_soe_start / battery.total_capacity * 100,
        final_soc=optimal[-1].energy.battery_soe_end / battery.total_capacity * 100,
    )
    solar_cost = sum(p.economic.solar_only_cost for p in actual)
    grid_only_cost = sum(p.economic.grid_only_cost for p in actual)
    missed, captured = economic_comparison(
        solar_cost,
        actual_summary["total_economic_cost"],
        optimal_summary["total_economic_cost"],
    )
    response.update(
        status=(
            "estimated_partial"
            if gaps
            else ("estimated" if mode == "estimated" else "complete")
        ),
        actual=actual_summary,
        optimal=optimal_summary,
        solar_only={
            "net_grid_cost": solar_cost,
            "wear_cost": 0,
            "total_economic_cost": solar_cost,
        },
        # Every household kWh bought at the same import prices: neither solar
        # nor battery contributes, so it shows what both together saved.
        grid_only={
            "net_grid_cost": grid_only_cost,
            "wear_cost": 0,
            "total_economic_cost": grid_only_cost,
        },
        model_cost_difference=missed,
        # Same formula as the headline capture, on the observed quarters only;
        # shown as an estimate where the verified figure is withheld.
        conditional_captured_percent=captured,
        relaxed_bound_label="relaxed physical lower-cost bound (not proven executable)",
    )
    if not gaps and replay_ok and not in_progress:
        response.update(missed_savings=missed, captured_percent=captured)
    if captured is not None and not 0 <= captured <= 100:
        warnings.add(
            "The conditional modeled capture is outside 0-100%; it is not clamped. Measurement/model inconsistencies may dominate the comparison."
        )
    response["warnings"] = sorted(warnings)
    for i, (p, o) in enumerate(zip(actual, optimal, strict=True)):
        assert p.timestamp is not None
        response["periods"].append(
            {
                "timestamp": p.timestamp.isoformat(),
                "date": p.timestamp.date().isoformat(),
                "buy_price": p.economic.buy_price,
                "sell_price": p.economic.sell_price,
                "actual_soc": (
                    p.energy.battery_soe_start / battery.total_capacity * 100
                    if _soc_available(p, battery.min_soe_kwh)
                    else None
                ),
                "optimal_soc": o.energy.battery_soe_start
                / battery.total_capacity
                * 100,
                "actual_soc_end": (
                    p.energy.battery_soe_end / battery.total_capacity * 100
                    if _soc_available(p, battery.min_soe_kwh)
                    else None
                ),
                "optimal_soc_end": o.energy.battery_soe_end
                / battery.total_capacity
                * 100,
                "actual_energy": asdict(p.energy),
                "optimal_energy": asdict(o.energy),
                "huawei_soc_end": (
                    huawei[i].energy.battery_soe_end / battery.total_capacity * 100
                    if huawei is not None
                    else None
                ),
            }
        )
    for day in days:
        indices = [
            i
            for i, p in enumerate(actual)
            if p.timestamp is not None and p.timestamp.date() == day
        ]
        response["daily"].append(
            {
                "date": day.isoformat(),
                "observed_periods": len(indices),
                "actual_grid_cost": sum(actual[i].economic.grid_cost for i in indices),
                "optimal_grid_cost": sum(
                    optimal[i].economic.grid_cost for i in indices
                ),
                "grid_only_cost": sum(
                    actual[i].economic.grid_only_cost for i in indices
                ),
                "solar_only_cost": sum(
                    actual[i].economic.solar_only_cost for i in indices
                ),
                "actual_wear_cost": sum(
                    actual[i].economic.battery_cycle_cost for i in indices
                ),
                "optimal_wear_cost": sum(
                    optimal[i].economic.battery_cycle_cost for i in indices
                ),
                "huawei_grid_cost": (
                    sum(huawei[i].economic.grid_cost for i in indices)
                    if huawei is not None
                    else None
                ),
            }
        )
    starts = {row["timestamp"]: row for row in response["periods"]}
    ends = {
        time_utils.period_start(p.timestamp.date(), p.period + 1).isoformat(): row
        for p, row in zip(actual, response["periods"], strict=True)
        if p.timestamp is not None
    }
    timeline = []
    for price in price_rows:
        row = starts.get(price["timestamp"])
        prior = ends.get(price["timestamp"])
        timeline.append(
            {
                **price,
                "actual_soc": (
                    row["actual_soc"]
                    if row is not None
                    else (prior["actual_soc_end"] if prior is not None else None)
                ),
                "optimal_soc": (
                    row["optimal_soc"]
                    if row is not None
                    else (prior["optimal_soc_end"] if prior is not None else None)
                ),
                "energy_unknown": row is None,
            }
        )
    if (
        not timeline
        or terminal_timestamp.timestamp()
        > datetime.fromisoformat(timeline[-1]["timestamp"]).timestamp()
    ):
        timeline.append(
            {
                "timestamp": terminal_timestamp.isoformat(),
                "buy_price": None,
                "sell_price": None,
                "actual_soc": terminal_energy / battery.total_capacity * 100,
                "optimal_soc": optimal[-1].energy.battery_soe_end
                / battery.total_capacity
                * 100,
                "energy_unknown": bool(gaps),
            }
        )
    response["soc_timeline"] = timeline
    return response
