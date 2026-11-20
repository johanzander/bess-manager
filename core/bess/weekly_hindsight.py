"""Read-only retrospective analysis of persisted quarter-hour observations.

No controller or HA client is accepted here. The live DP and its flow/economic
models are reused unchanged; a terminal penalty targets the observed end energy.
Results are withheld if replay cannot meet that boundary or reproduce economics.
"""

from dataclasses import asdict, fields, replace
from datetime import date, datetime, timedelta
from math import isfinite
from time import perf_counter
from typing import Any

from . import time_utils
from .daily_view_store import DailyViewStore
from .dp_battery_algorithm import optimize_battery_schedule, period_import_caps_kwh
from .execution_model import DEFAULT_CAPABILITIES, PlatformCapabilities
from .huawei_controller import HuaweiController
from .models import EconomicData, PeriodData
from .savings_aggregator import _week_bounds
from .settings import BatterySettings, HomeSettings
from .simulation.inverter_simulator import (
    derive_control_command,
    simulate,
    simulate_physical_plan,
)
from .terminal_value import TerminalValueCurve

ENERGY_TOLERANCE_KWH = 0.2  # Independent cumulative meters' existing tolerance.
TERMINAL_TOLERANCE_KWH = 1e-6


def historical_context(
    battery: BatterySettings,
    home: HomeSettings,
    capabilities: PlatformCapabilities,
    *,
    unsupported_constraints: bool = False,
) -> dict[str, Any]:
    """Freeze the model used when an observation is collected, not when queried."""
    return {
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
        and abs(previous.energy.battery_soe_end - e.battery_soe_start)
        > ENERGY_TOLERANCE_KWH
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
    if abs(e.soe_change_kwh - expected_delta) > ENERGY_TOLERANCE_KWH:
        issues.add(
            "Battery SOC changes do not reconcile with measured charge/discharge and efficiency."
        )
    return issues


def available_weeks(store: DailyViewStore, today: date | None = None) -> list[date]:
    """Completed ISO weeks containing history, newest first."""
    reference = today or time_utils.today()
    return sorted(
        {
            _week_bounds(date.fromisoformat(d))[0]
            for d in store.list_available_dates()
            if _week_bounds(date.fromisoformat(d))[1] < reference
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
        for key in (
            "solar_production",
            "home_consumption",
            "battery_charged",
            "battery_discharged",
            "grid_imported",
            "grid_exported",
            "clipped_solar",
        )
    )


def _soc_available(p: PeriodData) -> bool:
    return all(
        _finite(value) and value >= 0
        for value in (p.energy.battery_soe_start, p.energy.battery_soe_end)
    )


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
        "soe_accounting_mismatches": sum(v > ENERGY_TOLERANCE_KWH for v in soe),
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


def analyze_week(
    store: DailyViewStore,
    anchor: date,
    *,
    today: date | None = None,
    mode: str = "verified",
    assumed_context: dict[str, Any] | None = None,
    allow_partial: bool = False,
) -> dict[str, Any]:
    """Validate independently; estimated observations never become verified data.

    Partial analysis excludes unknown energy quarters completely. Across each
    excluded interval the model holds its battery energy unchanged. Its external
    energy/cost is unknown, not zero, and no complete-week score is published.
    """
    if mode not in ("verified", "estimated"):
        raise ValueError("Unknown historical analysis mode")
    if mode == "estimated" and assumed_context is None:
        raise ValueError(
            "Estimated mode requires an explicitly approved assumption context"
        )
    start, end = _week_bounds(anchor)
    days = [start + timedelta(days=i) for i in range(7)]
    expected = sum(time_utils.get_period_count(day) for day in days)
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
        ),
        0,
    )
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
        "optimal": None,
        "captured_percent": None,
        "missed_savings": None,
        "model_cost_difference": None,
        "daily": [],
        "periods": [],
        "excluded_intervals": [],
        "available_weeks": [d.isoformat() for d in available_weeks(store, today)],
    }
    issues: set[str] = set()
    warnings: set[str] = set()
    if end >= (today or time_utils.today()):
        issues.add("Only completed local calendar weeks can be analyzed.")
    periods: list[PeriodData] = []
    price_rows: list[dict[str, Any]] = []
    contexts = []
    structural_issues: set[str] = set()
    for day in days:
        count = time_utils.get_period_count(day)
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
                else:
                    counts["actual_periods"] += 1
                    energy_ok = _energy_available(p)
                    soc_ok = _soc_available(p)
                    counts["energy_available"] += energy_ok
                    counts["energy_verified"] += (
                        energy_ok and p.energy.observation_verified is True
                    )
                    counts["soc_available"] += soc_ok
                    counts["soc_verified"] += (
                        soc_ok and p.energy.observation_verified is True
                    )
                    counts["invalid_records"] += not (energy_ok and prices_ok)
                    if energy_ok and prices_ok:
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
    if not periods:
        issues.add("No usable actual energy/price observations are available.")
    if context is None or issues:
        response["issues"] = sorted(issues)
        return response
    battery = BatterySettings(**context["battery"])
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
            if _soc_available(p)
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
    if not (_soc_available(periods[0]) and _soc_available(periods[-1])):
        response["issues"] = [
            "Measured opening and closing battery energy are required."
        ]
        return response
    if not (
        battery.min_soe_kwh
        <= periods[0].energy.battery_soe_start
        <= battery.max_soe_kwh
        and battery.min_soe_kwh
        <= periods[-1].energy.battery_soe_end
        <= battery.max_soe_kwh
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
        for p in periods
    ]
    actual_physics = _physics_diagnostics(
        [p for p in actual if _soc_available(p)], battery
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
                if p.period == 0 and p.data_source == "actual" and _soc_available(p)
            ),
            None,
        )
        if opening is not None:
            terminal_energy = opening.energy.battery_soe_start
            terminal_timestamp = time_utils.period_start(end + timedelta(days=1), 0)
            terminal_evidence = (
                f"{following.date.isoformat()} actual period 0 opening battery energy"
            )
    if not battery.min_soe_kwh <= terminal_energy <= battery.max_soe_kwh:
        response["issues"] = [
            "Observed terminal boundary energy is outside the approved battery model."
        ]
        return response
    optimal, solver = solve_hindsight(actual, context, terminal_energy)
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
        terminal_delta >= -TERMINAL_TOLERANCE_KWH
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
            "Huawei execution is not independently verified: period-list behavior and load support are unmodelled. These are planned physical-model costs, not certified realizable Huawei savings."
        )
    if solver.get("plan_soe_drift_kwh", 0) > 1e-6:
        warnings.add(
            "The raw DP trajectory contained a state discontinuity. Reported model flows and continuous SOC were recomputed by physical replay; exact global optimality is not established."
        )
    if context["capabilities"]["control_model"] == "period_list":
        controller = HuaweiController(battery)
        block_counts = {}
        for day in days:
            intents = {
                p.period: o.decision.strategic_intent
                for p, o in zip(actual, optimal, strict=True)
                if p.timestamp is not None and p.timestamp.date() == day
            }
            blocks = controller._group_huawei_periods(
                [
                    intents.get(index, "UNKNOWN")
                    for index in range(time_utils.get_period_count(day))
                ]
            )
            block_counts[day.isoformat()] = len(blocks)
        response["huawei_tou_blocks"] = block_counts
        if any(v > HuaweiController.MAX_TOU_PERIODS for v in block_counts.values()):
            warnings.add(
                "The hypothetical schedule exceeds Huawei's daily TOU period-list limit; it is a relaxed model benchmark, not an executable schedule."
            )
    actual_summary = _summary(actual)
    optimal_summary = _summary(optimal)
    actual_summary.update(
        initial_soc=actual[0].energy.battery_soe_start / battery.total_capacity * 100,
        final_soc=terminal_energy / battery.total_capacity * 100,
    )
    optimal_summary.update(
        initial_soc=optimal[0].energy.battery_soe_start / battery.total_capacity * 100,
        final_soc=optimal[-1].energy.battery_soe_end / battery.total_capacity * 100,
    )
    solar_cost = sum(p.economic.solar_only_cost for p in actual)
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
        model_cost_difference=missed,
    )
    if not gaps and replay_ok:
        response.update(missed_savings=missed, captured_percent=captured)
    if captured is not None and not 0 <= captured <= 100:
        warnings.add(
            "The conditional modeled capture is outside 0-100%; it is not clamped. Measurement/model inconsistencies may dominate the comparison."
        )
    response["warnings"] = sorted(warnings)
    for p, o in zip(actual, optimal, strict=True):
        assert p.timestamp is not None
        response["periods"].append(
            {
                "timestamp": p.timestamp.isoformat(),
                "date": p.timestamp.date().isoformat(),
                "buy_price": p.economic.buy_price,
                "sell_price": p.economic.sell_price,
                "actual_soc": (
                    p.energy.battery_soe_start / battery.total_capacity * 100
                    if _soc_available(p)
                    else None
                ),
                "optimal_soc": o.energy.battery_soe_start
                / battery.total_capacity
                * 100,
                "actual_soc_end": (
                    p.energy.battery_soe_end / battery.total_capacity * 100
                    if _soc_available(p)
                    else None
                ),
                "optimal_soc_end": o.energy.battery_soe_end
                / battery.total_capacity
                * 100,
                "actual_energy": asdict(p.energy),
                "optimal_energy": asdict(o.energy),
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
