"""Read-only retrospective analysis of persisted quarter-hour observations.

No controller or HA client is accepted here. The live DP and its flow/economic
models are reused unchanged; a terminal penalty targets the observed end energy.

The result is one clearly labelled estimate: every quarter is modelled with the
battery, home and platform settings BESS runs with now, because settings
changed during the period are not recorded.
"""

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from itertools import pairwise
from math import isfinite
from time import perf_counter
from typing import Literal

from . import time_utils
from .daily_view_store import DailyViewStore
from .dp_battery_algorithm import optimize_battery_schedule, period_import_caps_kwh
from .execution_model import DEFAULT_CAPABILITIES, PlatformCapabilities
from .models import EconomicData, EnergyData, PeriodData
from .savings_aggregator import _month_bounds, _week_bounds
from .settings import BatterySettings, HomeSettings
from .simulation.inverter_simulator import (
    derive_control_command,
    simulate,
    simulate_physical_plan,
)
from .terminal_value import TerminalValueCurve

ENERGY_TOLERANCE_KWH = 0.2  # Independent cumulative meters' existing tolerance.
TERMINAL_TOLERANCE_KWH = 1e-6
# Energy lattice of the production DP; a closing state can miss by up to one step.
DP_ENERGY_STEP_KWH = 0.1
# SOC sensors report whole percent, so two readings can disagree by one step
# of capacity without any energy having moved.
SOC_REPORTING_STEP = 0.01
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

PeriodKind = Literal["week", "month"]
AnalysisStatus = Literal[
    "estimated", "estimated_partial", "insufficient_data", "unsupported_model"
]
ESTIMATE_LABEL = (
    "Estimate: every quarter is modelled with your current battery, home and "
    "inverter settings; changes made during the period are not reflected."
)


@dataclass(frozen=True)
class HindsightModel:
    """The settings every scenario of one analysis is modelled with."""

    battery: BatterySettings
    home: HomeSettings
    capabilities: PlatformCapabilities


@dataclass(frozen=True)
class ScenarioCost:
    net_grid_cost: float
    wear_cost: float
    total_economic_cost: float


@dataclass(frozen=True)
class OperationSummary:
    """One scenario's grid, wear and battery totals over the analyzed quarters."""

    grid_import_kwh: float
    grid_export_kwh: float
    import_cost: float
    export_revenue: float
    net_grid_cost: float
    wear_cost: float
    total_economic_cost: float
    charged_kwh: float
    discharged_kwh: float
    throughput_kwh: float
    solar_export_kwh: float
    solar_self_consumption_percent: float | None
    initial_soc: float
    final_soc: float
    # Missing closing energy the DP's 0.1 kWh lattice left, priced into
    # total_economic_cost at the window's dearest import price.
    terminal_shortfall_cost: float = 0.0


@dataclass(frozen=True)
class ExcludedInterval:
    date: str
    period: int
    timestamp: str
    reason: str


@dataclass(frozen=True)
class GapBoundary:
    after: str
    resumes: str
    measured_energy_change_kwh: float | None


@dataclass(frozen=True)
class Coverage:
    """Which quarters the comparison could use, and why the rest were left out."""

    expected_periods: int
    analyzed_periods: int
    coverage_percent: float
    actual_periods: int
    predicted_periods: int
    missing_periods: int
    invalid_records: int
    restart_placeholders: int
    soc_dropouts: int
    below_reserve_periods: int
    excluded_intervals: list[ExcludedInterval]
    gap_boundaries: list[GapBoundary]


@dataclass(frozen=True)
class EfficiencyCalibration:
    configured_charge: float
    configured_discharge: float
    charged_kwh: float
    discharged_kwh: float
    stored_change_kwh: float
    applied: bool
    charge: float | None = None
    discharge: float | None = None
    capped: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class CapacityCalibration:
    configured_capacity_kwh: float
    charging_runs: int
    discharging_runs: int
    applied: bool
    factor: float | None = None
    capacity_kwh: float | None = None
    charge: float | None = None
    discharge: float | None = None
    capped: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class BatteryModel:
    """The battery the scenarios were modelled with, and where it came from."""

    capacity_kwh: float
    min_soc: float
    max_soc: float
    max_charge_power_kw: float
    max_discharge_power_kw: float
    efficiency_charge: float
    efficiency_discharge: float
    cycle_cost_per_kwh: float
    history_source: str | None
    capacity_calibration: CapacityCalibration | None
    efficiency_calibration: EfficiencyCalibration | None


@dataclass(frozen=True)
class PhysicsCheck:
    max_energy_balance_error_kwh: float
    max_soe_accounting_error_kwh: float
    energy_balance_mismatches: int
    soe_accounting_mismatches: int
    operational_soc_violations: int
    charge_power_violations: int
    discharge_power_violations: int
    minimum_energy_kwh: float
    maximum_energy_kwh: float


@dataclass(frozen=True)
class SolverReport:
    solve_seconds: float
    # None where the platform's commands have no execution model, so the
    # schedule was only replayed through the physical battery model.
    simulation_cost_difference: float | None
    simulation_trajectory_error_kwh: float
    plan_soe_drift_kwh: float
    import_constraint_violation_kwh: float


@dataclass(frozen=True)
class Comparison:
    """Actual operation against the perfect-foresight schedule, same quarters."""

    actual: OperationSummary
    optimal: OperationSummary
    solar_only: ScenarioCost
    grid_only: ScenarioCost
    missed_savings: float
    captured_percent: float | None
    comparison_start: str
    comparison_end: str
    initial_energy_kwh: float
    terminal_energy_kwh: float
    terminal_timestamp: str
    terminal_evidence: str
    model_terminal_energy_kwh: float
    terminal_difference_kwh: float
    execution_replayed: bool
    solver: SolverReport
    actual_validation: PhysicsCheck
    model_validation: PhysicsCheck


@dataclass(frozen=True)
class DailyComparison:
    date: str
    observed_periods: int
    actual_grid_cost: float
    optimal_grid_cost: float
    grid_only_cost: float
    solar_only_cost: float
    actual_wear_cost: float
    optimal_wear_cost: float


@dataclass(frozen=True)
class PeriodComparison:
    timestamp: str
    date: str
    buy_price: float
    sell_price: float
    actual_soc: float | None
    optimal_soc: float
    actual_soc_end: float | None
    optimal_soc_end: float
    actual_energy: EnergyData
    optimal_energy: EnergyData


@dataclass(frozen=True)
class SocTimelinePoint:
    timestamp: str
    buy_price: float | None
    sell_price: float | None
    actual_soc: float | None
    optimal_soc: float | None
    energy_unknown: bool


@dataclass(frozen=True)
class PerformanceAnalysis:
    """How close BESS came to perfect hindsight over one week or month."""

    start_date: str
    end_date: str
    period: PeriodKind
    in_progress: bool
    timezone: str
    currency: str
    status: AnalysisStatus
    issues: list[str]
    warnings: list[str]
    available_periods: list[str]
    coverage: Coverage
    battery_model: BatteryModel | None = None
    comparison: Comparison | None = None
    daily: list[DailyComparison] = field(default_factory=list)
    periods: list[PeriodComparison] = field(default_factory=list)
    soc_timeline: list[SocTimelinePoint] = field(default_factory=list)


def _soe_tolerance(settings: BatterySettings) -> float:
    return ENERGY_TOLERANCE_KWH + settings.total_capacity * SOC_REPORTING_STEP


def _period_issues(
    p: PeriodData, previous: PeriodData | None, settings: BatterySettings
) -> set[str]:
    e = p.energy
    issues = set()
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
        issues.add("Observed battery energy is outside the model's battery limits.")
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


def period_days(anchor: date, period: PeriodKind) -> list[date]:
    """Every local day of the week or month containing the anchor."""
    start, end = PERIOD_BOUNDS[period](anchor)
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def available_periods(
    store: DailyViewStore,
    today: date | None = None,
    include_current: bool = False,
    period: PeriodKind = "week",
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


def _summary(
    periods: list[PeriodData], battery: BatterySettings, final_energy_kwh: float
) -> OperationSummary:
    grid = sum(p.economic.grid_cost for p in periods)
    wear = sum(p.economic.battery_cycle_cost for p in periods)
    solar = sum(p.energy.solar_production for p in periods)
    solar_export = sum(p.energy.solar_to_grid for p in periods)
    clipped = sum(p.energy.clipped_solar for p in periods)
    charged = sum(p.energy.battery_charged for p in periods)
    discharged = sum(p.energy.battery_discharged for p in periods)
    return OperationSummary(
        grid_import_kwh=sum(p.energy.grid_imported for p in periods),
        grid_export_kwh=sum(p.energy.grid_exported for p in periods),
        import_cost=sum(p.economic.import_cost for p in periods),
        export_revenue=sum(p.economic.export_revenue for p in periods),
        net_grid_cost=grid,
        wear_cost=wear,
        total_economic_cost=grid + wear,
        charged_kwh=charged,
        discharged_kwh=discharged,
        throughput_kwh=charged + discharged,
        solar_export_kwh=solar_export,
        solar_self_consumption_percent=(
            100 * (solar - clipped - solar_export) / (solar - clipped)
            if solar > clipped
            else None
        ),
        initial_soc=periods[0].energy.battery_soe_start / battery.total_capacity * 100,
        final_soc=final_energy_kwh / battery.total_capacity * 100,
    )


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
    model: HindsightModel,
    terminal_energy_kwh: float | None = None,
) -> tuple[list[PeriodData], SolverReport]:
    """One continuous horizon, with simulator verification and no hardware access.

    A terminal lower bound prevents funding savings by emptying the battery.
    The finite-grid model may leave extra energy, which receives no financial
    credit. The lower bound is checked after replay. No daily resets are used.
    """
    battery = model.battery
    # The production DP prices stored kWh; retrospective comparisons price
    # input-side charge throughput, as historical EconomicData does. This copy
    # converts the coefficient without changing the production optimizer.
    objective_battery = replace(
        battery,
        cycle_cost_per_kwh=battery.cycle_cost_per_kwh / battery.efficiency_charge,
    )
    currency = model.home.currency
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
        currency=currency,
        capabilities=model.capabilities,
        home_settings=model.home,
    )
    elapsed = perf_counter() - started
    import_caps = period_import_caps_kwh(model.home, None, len(periods), 0.25)

    def import_violation(rows: list[PeriodData]) -> float:
        if import_caps is None:
            return 0.0
        return max(
            (
                max(0.0, p.energy.grid_imported - cap) if cap is not None else 0.0
                for p, cap in zip(rows, import_caps, strict=True)
            ),
            default=0.0,
        )

    # The current simulator models Growatt MIN TOU semantics only. Other platforms
    # must not acquire a hardware-faithfulness claim from this replay.
    simulator_capabilities = replace(
        DEFAULT_CAPABILITIES,
        discharge_resolution_kw=model.capabilities.discharge_resolution_kw,
    )
    if model.capabilities != simulator_capabilities or (
        model.capabilities.discharge_rate_step_kw(battery)
        != DEFAULT_CAPABILITIES.discharge_rate_step_kw(battery)
    ):
        physical = simulate_physical_plan(
            plan.period_data,
            solar,
            demand,
            buy,
            sell,
            initial,
            battery,
            0.25,
            currency,
            import_caps,
        )
        return physical.period_data, SolverReport(
            solve_seconds=elapsed,
            simulation_cost_difference=None,
            simulation_trajectory_error_kwh=0.0,
            plan_soe_drift_kwh=max(
                abs(a.energy.battery_soe_end - b.energy.battery_soe_end)
                for a, b in zip(plan.period_data, physical.period_data, strict=True)
            ),
            import_constraint_violation_kwh=import_violation(physical.period_data),
        )
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
        currency=currency,
        import_cap_kwh=import_caps,
    )
    return replay.period_data, SolverReport(
        solve_seconds=elapsed,
        simulation_cost_difference=replay.realized_cost
        - sum(p.economic.hourly_cost for p in plan.period_data),
        simulation_trajectory_error_kwh=max(
            abs(a.energy.battery_soe_end - b.energy.battery_soe_end)
            for a, b in zip(replay.period_data, plan.period_data, strict=True)
        ),
        plan_soe_drift_kwh=0.0,
        import_constraint_violation_kwh=import_violation(replay.period_data),
    )


def _finite(value: object) -> bool:
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
    # Collection stored an 'unavailable' SOC sensor as exactly 0 % (logged at a
    # restart, with no matching discharge). A battery with a non-zero reserve
    # cannot read 0, so that value is unknown, not empty.
    return reserve_kwh <= 0 or 0.0 not in values


def _restart_placeholder(p: PeriodData, day: date, index: int) -> bool:
    """A row the restart recovery wrote as zero energy long afterwards.

    Such a row is not an observation: no meter was read for that quarter.
    """
    return (
        p.timestamp is not None
        and p.timestamp.tzinfo is not None
        and p.timestamp >= time_utils.period_start(day, index + 2)
        and all(p.energy.__dict__[key] == 0 for key in _ENERGY_KEYS)
    )


def calibrate_efficiency(
    periods: list[PeriodData], battery: BatterySettings
) -> EfficiencyCalibration:
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
    measured = EfficiencyCalibration(
        configured_charge=battery.efficiency_charge,
        configured_discharge=battery.efficiency_discharge,
        charged_kwh=charged,
        discharged_kwh=discharged,
        stored_change_kwh=stored,
        applied=False,
    )
    if charged + discharged < 2 * battery.total_capacity or charged <= 0:
        return replace(measured, reason="too little battery throughput to calibrate")
    a, b = battery.efficiency_charge, battery.efficiency_discharge
    # a*C*k^2 - S*k - D/b = 0, positive root.
    k = (stored + (stored**2 + 4 * a * charged * discharged / b) ** 0.5) / (
        2 * a * charged
    )
    return replace(
        measured,
        charge=min(1.0, a * k),
        discharge=min(1.0, b * k),
        capped=a * k > 1 or b * k > 1,
        applied=True,
    )


def calibrate_capacity(
    periods: list[PeriodData], battery: BatterySettings
) -> CapacityCalibration:
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
    measured = CapacityCalibration(
        configured_capacity_kwh=battery.total_capacity,
        charging_runs=len(charging),
        discharging_runs=len(discharging),
        applied=False,
    )
    if len(charging) < 3 or len(discharging) < 3:
        return replace(measured, reason="too few one-way charge and discharge runs")
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
        return replace(
            measured, reason=f"fitted capacity factor {f:.2f} is implausible", factor=f
        )
    return replace(
        measured,
        factor=f,
        capacity_kwh=battery.total_capacity * f,
        charge=min(1.0, a * k),
        discharge=min(1.0, b * k),
        capped=k >= 1 / max(a, b) - 0.001,
        applied=True,
    )


def _physics_check(periods: list[PeriodData], battery: BatterySettings) -> PhysicsCheck:
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
    return PhysicsCheck(
        max_energy_balance_error_kwh=max(balance, default=0.0),
        max_soe_accounting_error_kwh=max(soe, default=0.0),
        energy_balance_mismatches=sum(v > ENERGY_TOLERANCE_KWH for v in balance),
        soe_accounting_mismatches=sum(v > _soe_tolerance(battery) for v in soe),
        operational_soc_violations=sum(
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
        charge_power_violations=sum(
            p.energy.battery_charged > battery.max_charge_power_kw * 0.25 + 1e-6
            for p in periods
        ),
        discharge_power_violations=sum(
            p.energy.battery_discharged > battery.max_discharge_power_kw * 0.25 + 1e-6
            for p in periods
        ),
        minimum_energy_kwh=min((p.energy.battery_soe_end for p in periods), default=0),
        maximum_energy_kwh=max((p.energy.battery_soe_end for p in periods), default=0),
    )


@dataclass
class _Observations:
    """The quarters a period offers the comparison, and what was left out."""

    periods: list[PeriodData]
    price_rows: list[tuple[str, float, float]]
    excluded: list[ExcludedInterval]
    issues: set[str]
    warnings: set[str]
    actual_periods: int = 0
    predicted_periods: int = 0
    missing_periods: int = 0
    invalid_records: int = 0
    restart_placeholders: int = 0
    soc_dropouts: int = 0
    below_reserve_periods: int = 0
    energy_available: int = 0
    timezone_mismatches: int = 0


def _collect_observations(
    store: DailyViewStore,
    days: list[date],
    elapsed: dict[date, int],
    battery: BatterySettings,
) -> _Observations:
    found = _Observations([], [], [], set(), set())
    for day in days:
        view = store.load_day(day)
        by_index: dict[int, list[PeriodData]] = {}
        if view is not None:
            if view.date != day:
                found.issues.add(
                    "Stored calendar date does not match its historical file."
                )
            for p in view.periods:
                by_index.setdefault(p.period, []).append(p)
        for index in range(elapsed[day]):
            group = by_index.get(index, [])
            reason = "missing"
            if len(group) != 1:
                found.missing_periods += not group
                found.invalid_records += len(group)
                if group:
                    found.issues.add("Duplicate historical quarter indices.")
            else:
                p = group[0]
                prices_ok = all(
                    _finite(v) for v in (p.economic.buy_price, p.economic.sell_price)
                )
                start = time_utils.period_start(day, index)
                if prices_ok:
                    found.price_rows.append(
                        (start.isoformat(), p.economic.buy_price, p.economic.sell_price)
                    )
                if p.data_source == "predicted":
                    found.predicted_periods += 1
                    reason = "predicted energy excluded"
                elif p.data_source != "actual":
                    found.missing_periods += 1
                elif _restart_placeholder(p, day, index):
                    found.restart_placeholders += 1
                    reason = "zero-filled restart placeholder, not an observation"
                else:
                    found.actual_periods += 1
                    energy_ok = _energy_available(p)
                    soc_ok = _soc_available(p, battery.min_soe_kwh)
                    found.energy_available += energy_ok
                    found.soc_dropouts += energy_ok and not soc_ok
                    found.invalid_records += not (energy_ok and prices_ok)
                    # Below the configured reserve the battery was serving
                    # backup (an outage) or a lower inverter cutoff. Hindsight
                    # may never use that energy, so such quarters are left out
                    # of both sides rather than counted for or against BESS.
                    # Only energy actually delivered from inside the reserve
                    # is backup use; idle readings a few percent under it are
                    # standby drift and whole-percent rounding.
                    below_reserve = (
                        soc_ok
                        and p.energy.battery_discharged > BACKUP_DISCHARGE_KWH
                        and p.energy.battery_soe_end
                        < battery.min_soe_kwh
                        - battery.total_capacity * SOC_REPORTING_STEP
                        - 1e-6
                    )
                    found.below_reserve_periods += below_reserve
                    if below_reserve:
                        reason = "battery below the configured reserve (backup use)"
                    elif energy_ok and prices_ok:
                        if p.timestamp is None or p.timestamp.tzinfo is None:
                            found.warnings.add(
                                "Some collection timestamps are unverified; day/quarter indices supply the historical boundaries."
                            )
                        elif p.timestamp.utcoffset() not in (
                            start.utcoffset(),
                            time_utils.period_start(day, index + 1).utcoffset(),
                        ):
                            found.timezone_mismatches += 1
                        found.periods.append(replace(p, timestamp=start))
                        continue
                    else:
                        reason = "invalid energy or prices"
            found.excluded.append(
                ExcludedInterval(
                    date=day.isoformat(),
                    period=index,
                    timestamp=time_utils.period_start(day, index).isoformat(),
                    reason=reason,
                )
            )
    return found


def _calibrated(
    periods: list[PeriodData],
    battery: BatterySettings,
    source: str,
    warnings: set[str],
) -> tuple[
    list[PeriodData],
    BatterySettings,
    CapacityCalibration,
    EfficiencyCalibration,
]:
    capacity = calibrate_capacity(periods, battery)
    if capacity.applied:
        assert capacity.factor is not None and capacity.capacity_kwh is not None
        factor = capacity.factor
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
        battery = replace(battery, total_capacity=capacity.capacity_kwh)
        warnings.add(
            f"Usable capacity calibrated from {source}: {capacity.capacity_kwh:.1f} kWh (configured {capacity.configured_capacity_kwh:g} kWh), from {capacity.charging_runs} charging and {capacity.discharging_runs} discharging runs."
        )
    efficiency = calibrate_efficiency(periods, battery)
    if efficiency.applied:
        assert efficiency.charge is not None and efficiency.discharge is not None
        battery = replace(
            battery,
            efficiency_charge=efficiency.charge,
            efficiency_discharge=efficiency.discharge,
        )
        warnings.add(
            f"Battery efficiency calibrated from {source}: {efficiency.charge * 100:.1f} % charge / {efficiency.discharge * 100:.1f} % discharge (configured {efficiency.configured_charge * 100:.1f} % / {efficiency.configured_discharge * 100:.1f} %)."
            + (
                " The measured history implies more than 100 %; capped at 100 %, so meter or SOC readings disagree."
                if efficiency.capped
                else ""
            )
        )
    return periods, battery, capacity, efficiency


def analyze_period(
    store: DailyViewStore,
    anchor: date,
    model: HindsightModel,
    *,
    today: date | None = None,
    period: PeriodKind = "week",
    battery_history_source: str | None = None,
) -> PerformanceAnalysis:
    """Compare actual operation with perfect hindsight over one week or month.

    Unknown energy quarters are excluded completely. Across each excluded
    interval the model holds its battery energy unchanged, which only
    restricts it (it can never fund savings from a gap); the measured battery
    energy on both sides of every gap is reported so a biased comparison is
    visible. External energy/cost there is unknown, not zero.

    With ``battery_history_source`` the battery's capacity and efficiency are
    calibrated from the measured history it names before modelling.
    """
    days = period_days(anchor, period)
    start, end = days[0], days[-1]
    # A period still in progress is analyzed up to its last ended quarter;
    # later quarters have not happened yet, so they are neither expected nor gaps.
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
    battery = model.battery
    found = _collect_observations(store, days, elapsed, battery)
    issues, warnings = found.issues, found.warnings
    warnings.add(ESTIMATE_LABEL)
    gap_boundaries: list[GapBoundary] = []

    def result(
        status: AnalysisStatus,
        battery_model: BatteryModel | None = None,
        comparison: Comparison | None = None,
        daily: list[DailyComparison] | None = None,
        periods: list[PeriodComparison] | None = None,
        soc_timeline: list[SocTimelinePoint] | None = None,
    ) -> PerformanceAnalysis:
        return PerformanceAnalysis(
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            period=period,
            in_progress=in_progress,
            timezone=str(time_utils.TIMEZONE),
            currency=model.home.currency,
            status=status,
            issues=sorted(issues),
            warnings=sorted(warnings),
            available_periods=[
                d.isoformat()
                for d in available_periods(
                    store, today, include_current=True, period=period
                )
            ],
            coverage=Coverage(
                expected_periods=expected,
                analyzed_periods=len(found.periods),
                coverage_percent=(
                    100 * found.energy_available / expected if expected else 0.0
                ),
                actual_periods=found.actual_periods,
                predicted_periods=found.predicted_periods,
                missing_periods=found.missing_periods,
                invalid_records=found.invalid_records,
                restart_placeholders=found.restart_placeholders,
                soc_dropouts=found.soc_dropouts,
                below_reserve_periods=found.below_reserve_periods,
                excluded_intervals=found.excluded,
                gap_boundaries=gap_boundaries,
            ),
            battery_model=battery_model,
            comparison=comparison,
            daily=daily or [],
            periods=periods or [],
            soc_timeline=soc_timeline or [],
        )

    if expected == 0:
        issues.add("This period has no completed quarters yet.")
    if in_progress:
        warnings.add(
            "Period in progress: only quarters that have ended are analyzed; the comparison ends at the last of them, and figures will change as the period completes."
        )
    if found.timezone_mismatches:
        issues.add(
            "Historical timestamp offsets disagree with the configured local timezone."
        )
    periods = found.periods
    if not periods:
        issues.add("No usable actual energy/price observations are available.")
    if issues:
        return result("insufficient_data")
    capacity_calibration = efficiency_calibration = None
    if battery_history_source is not None:
        periods, battery, capacity_calibration, efficiency_calibration = _calibrated(
            periods, battery, battery_history_source, warnings
        )
    battery_model = BatteryModel(
        capacity_kwh=battery.total_capacity,
        min_soc=battery.min_soc,
        max_soc=battery.max_soc,
        max_charge_power_kw=battery.max_charge_power_kw,
        max_discharge_power_kw=battery.max_discharge_power_kw,
        efficiency_charge=battery.efficiency_charge,
        efficiency_discharge=battery.efficiency_discharge,
        cycle_cost_per_kwh=battery.cycle_cost_per_kwh,
        history_source=battery_history_source,
        capacity_calibration=capacity_calibration,
        efficiency_calibration=efficiency_calibration,
    )

    def withheld(reason: str) -> PerformanceAnalysis:
        issues.add(reason)
        return result("insufficient_data", battery_model=battery_model)

    if not (
        0 < battery.efficiency_charge <= 1 and 0 < battery.efficiency_discharge <= 1
    ):
        return withheld("Invalid battery efficiency in the battery model.")
    if battery.inverter_max_ac_power_kw > 0 or any(
        p.energy.clipped_solar > 0 for p in periods
    ):
        return withheld(
            "Available solar under clipping/curtailment cannot be reconstructed from delivered PV."
        )
    previous = None
    for p in periods:
        warnings.update(
            _period_issues(p, previous, battery)
            if _soc_available(p, battery.min_soe_kwh)
            else {"Battery SOC is unavailable in some observed quarters."}
        )
        previous = p
    if not (
        _soc_available(periods[0], battery.min_soe_kwh)
        and _soc_available(periods[-1], battery.min_soe_kwh)
    ):
        return withheld("Measured opening and closing battery energy are required.")
    # Boundary readings under the reserve are idle drift (backup use is
    # excluded above); the model itself always starts and ends at or above it.
    if not (
        periods[0].energy.battery_soe_start <= battery.max_soe_kwh
        and periods[-1].energy.battery_soe_end <= battery.max_soe_kwh
    ):
        return withheld(
            "Opening or closing measured energy is outside the battery model; no clamping is permitted."
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
        gap_boundaries.append(
            GapBoundary(
                after=before.timestamp.isoformat(),
                resumes=after.timestamp.isoformat(),
                measured_energy_change_kwh=change,
            )
        )
        if change is None or abs(change) > battery.total_capacity * SOC_REPORTING_STEP:
            warnings.add(
                "Measured battery energy changed, or is unknown, across an excluded interval; the observed-interval comparison omits that energy movement."
            )
    if found.restart_placeholders:
        warnings.add(
            f"{found.restart_placeholders} zero-filled restart placeholder quarters are excluded as unknown."
        )
    if found.below_reserve_periods:
        warnings.add(
            f"{found.below_reserve_periods} quarters with the battery below the configured reserve (backup use during an outage, or a lower inverter cutoff) are left out of both sides; hindsight never uses the reserve."
        )
    if found.soc_dropouts:
        warnings.add(
            f"{found.soc_dropouts} quarters recorded an unavailable SOC sensor as 0 %; their SOC is shown as unknown."
        )
    warnings.update(
        {
            "Delivered solar is fixed input; unmeasured available PV under clipping or curtailment cannot be reconstructed.",
            "The existing DP uses a 0.1 kWh energy grid and hardware candidates; it is not a certified continuous physical optimum.",
            "Detailed measured source flows use EnergyData allocation priorities, not separate source meters.",
        }
    )
    gaps = len(found.excluded)
    if gaps:
        warnings.add(
            f"Observed intervals only: {len(periods)}/{expected}. Unknown quarters are excluded, not zero-filled. The hypothetical battery holds energy through gaps; gap household energy/cost is unknown."
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
            economic=EconomicData.from_energy_data(
                p.energy,
                p.economic.buy_price,
                p.economic.sell_price,
                p.energy.battery_charged * battery.cycle_cost_per_kwh,
            ),
        )
        for p in balanced
    ]
    actual_physics = _physics_check(
        [p for p in actual if _soc_available(p, battery.min_soe_kwh)], battery
    )
    if actual_physics.operational_soc_violations:
        warnings.add(
            f"{actual_physics.operational_soc_violations} actual SOC intervals violate the model's battery limits; historical limits may differ or SOC observations may be unreliable."
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
        return withheld(
            "Observed terminal boundary energy is outside the battery model."
        )
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
    optimal, solver = solve_hindsight(
        model_input, replace(model, battery=battery), terminal_energy
    )
    replay_ok = (
        solver.simulation_cost_difference is not None
        and abs(solver.simulation_cost_difference) <= 0.01
        and solver.simulation_trajectory_error_kwh <= TERMINAL_TOLERANCE_KWH
    )
    terminal_delta = optimal[-1].energy.battery_soe_end - terminal_energy
    model_physics = _physics_check(optimal, battery)
    model_ok = (
        terminal_delta >= -DP_ENERGY_STEP_KWH
        and model_physics.max_energy_balance_error_kwh < 1e-6
        and model_physics.max_soe_accounting_error_kwh < 1e-6
        and not model_physics.operational_soc_violations
        and not model_physics.charge_power_violations
        and not model_physics.discharge_power_violations
        and solver.import_constraint_violation_kwh <= 1e-6
    )
    if not model_ok:
        issues.add(
            "The hindsight model violates physical or terminal constraints. Savings comparison withheld."
        )
        return result("unsupported_model", battery_model=battery_model)
    if not replay_ok:
        warnings.add(
            "Inverter execution of the hindsight schedule is not modelled for this platform: period-list behavior and load support are unmodelled. These are planned physical-model costs, not certified realizable savings."
        )
    if solver.plan_soe_drift_kwh > 1e-6:
        warnings.add(
            "The raw DP trajectory contained a state discontinuity. Reported model flows and continuous SOC were recomputed by physical replay; exact global optimality is not established."
        )
    actual_summary = _summary(actual, battery, terminal_energy)
    optimal_summary = _summary(optimal, battery, optimal[-1].energy.battery_soe_end)
    if terminal_delta < 0:
        # The DP's 0.1 kWh lattice can land just under the closing energy; the
        # missing energy is charged to hindsight at the dearest import price.
        shortfall_cost = (
            -terminal_delta
            * (max(p.economic.buy_price for p in actual) + battery.cycle_cost_per_kwh)
            / battery.efficiency_charge
        )
        optimal_summary = replace(
            optimal_summary,
            total_economic_cost=optimal_summary.total_economic_cost + shortfall_cost,
            terminal_shortfall_cost=shortfall_cost,
        )
    solar_cost = sum(p.economic.solar_only_cost for p in actual)
    grid_only_cost = sum(p.economic.grid_only_cost for p in actual)
    missed, captured = economic_comparison(
        solar_cost,
        actual_summary.total_economic_cost,
        optimal_summary.total_economic_cost,
    )
    if captured is not None and not 0 <= captured <= 100:
        warnings.add(
            "The modelled capture is outside 0-100%; it is not clamped. Measurement/model inconsistencies may dominate the comparison."
        )
    first_timestamp, last_timestamp = actual[0].timestamp, actual[-1].timestamp
    assert first_timestamp is not None and last_timestamp is not None
    comparison = Comparison(
        actual=actual_summary,
        optimal=optimal_summary,
        solar_only=ScenarioCost(solar_cost, 0.0, solar_cost),
        # Every household kWh bought at the same import prices: neither solar
        # nor battery contributes, so it shows what both together saved.
        grid_only=ScenarioCost(grid_only_cost, 0.0, grid_only_cost),
        missed_savings=missed,
        captured_percent=captured,
        comparison_start=first_timestamp.isoformat(),
        comparison_end=(last_timestamp + timedelta(minutes=15)).isoformat(),
        initial_energy_kwh=actual[0].energy.battery_soe_start,
        terminal_energy_kwh=terminal_energy,
        terminal_timestamp=terminal_timestamp.isoformat(),
        terminal_evidence=terminal_evidence,
        model_terminal_energy_kwh=optimal[-1].energy.battery_soe_end,
        terminal_difference_kwh=terminal_delta,
        execution_replayed=replay_ok,
        solver=solver,
        actual_validation=actual_physics,
        model_validation=model_physics,
    )

    def soc(energy_kwh: float) -> float:
        return energy_kwh / battery.total_capacity * 100

    rows = []
    for p, o in zip(actual, optimal, strict=True):
        assert p.timestamp is not None
        known = _soc_available(p, battery.min_soe_kwh)
        rows.append(
            PeriodComparison(
                timestamp=p.timestamp.isoformat(),
                date=p.timestamp.date().isoformat(),
                buy_price=p.economic.buy_price,
                sell_price=p.economic.sell_price,
                actual_soc=soc(p.energy.battery_soe_start) if known else None,
                optimal_soc=soc(o.energy.battery_soe_start),
                actual_soc_end=soc(p.energy.battery_soe_end) if known else None,
                optimal_soc_end=soc(o.energy.battery_soe_end),
                actual_energy=p.energy,
                optimal_energy=o.energy,
            )
        )
    daily = []
    for day in days:
        indices = [
            i
            for i, p in enumerate(actual)
            if p.timestamp is not None and p.timestamp.date() == day
        ]
        daily.append(
            DailyComparison(
                date=day.isoformat(),
                observed_periods=len(indices),
                actual_grid_cost=sum(actual[i].economic.grid_cost for i in indices),
                optimal_grid_cost=sum(optimal[i].economic.grid_cost for i in indices),
                grid_only_cost=sum(actual[i].economic.grid_only_cost for i in indices),
                solar_only_cost=sum(
                    actual[i].economic.solar_only_cost for i in indices
                ),
                actual_wear_cost=sum(
                    actual[i].economic.battery_cycle_cost for i in indices
                ),
                optimal_wear_cost=sum(
                    optimal[i].economic.battery_cycle_cost for i in indices
                ),
            )
        )
    starts = {row.timestamp: row for row in rows}
    ends = {
        time_utils.period_start(p.timestamp.date(), p.period + 1).isoformat(): row
        for p, row in zip(actual, rows, strict=True)
        if p.timestamp is not None
    }
    timeline = []
    for timestamp, buy, sell in found.price_rows:
        row = starts.get(timestamp)
        prior = ends.get(timestamp)
        timeline.append(
            SocTimelinePoint(
                timestamp=timestamp,
                buy_price=buy,
                sell_price=sell,
                actual_soc=(
                    row.actual_soc
                    if row is not None
                    else (prior.actual_soc_end if prior is not None else None)
                ),
                optimal_soc=(
                    row.optimal_soc
                    if row is not None
                    else (prior.optimal_soc_end if prior is not None else None)
                ),
                energy_unknown=row is None,
            )
        )
    if (
        not timeline
        or terminal_timestamp.timestamp()
        > datetime.fromisoformat(timeline[-1].timestamp).timestamp()
    ):
        timeline.append(
            SocTimelinePoint(
                timestamp=terminal_timestamp.isoformat(),
                buy_price=None,
                sell_price=None,
                actual_soc=soc(terminal_energy),
                optimal_soc=soc(optimal[-1].energy.battery_soe_end),
                energy_unknown=bool(gaps),
            )
        )
    return result(
        "estimated_partial" if gaps else "estimated",
        battery_model=battery_model,
        comparison=comparison,
        daily=daily,
        periods=rows,
        soc_timeline=timeline,
    )
