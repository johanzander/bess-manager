# core/bess/models.py
"""
Data models for the BESS system.

This module contains dataclasses representing various data structures used throughout
the BESS system, providing type safety and clear interfaces between components.

"""

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime

logger = logging.getLogger(__name__)

# Energy resolution floor for grid flows (kWh). Home Assistant's lifetime
# energy counters report at 0.1 kWh resolution, so a measured grid flow below
# this cannot be told apart from counter noise between two independent sensors.
#
# Single source of truth on purpose (#497). This value answers exactly one
# question -- "is this export real, or is it below the resolution at which we
# can know anything?" -- and it used to be answered in two places that drifted
# apart: this module's noise fold hardcoded 0.1 while the DP's self-throttle
# threshold used 0.01, leaving a band where the optimizer booked export revenue
# for energy the flow calculator had already decided never left the property.
# Same failure shape as the #275 postmortem (see dp_constants.py): one physical
# boundary, two independent constants, no enforcement that they agree.
#
# Homed here, in the measurement/model layer, because it describes the sensors,
# not the optimizer -- the DP's `_discharge_is_unexecutable` imports it.
GRID_FLOW_RESOLUTION_KWH = 0.1

__all__ = [
    "DecisionData",
    "EconomicData",
    "EnergyData",
    "OptimizationResult",
    "PeriodData",
    "apply_export_curtailment_to_period_data",
    "infer_intent_from_flows",
]


def infer_intent_from_flows(power: float, energy_data: "EnergyData") -> str:
    """
    Infer strategic intent from observed energy flows.

    NOTE: For OBSERVATIONAL purposes only (dashboard display of what happened).
    The authoritative intent comes from DP algorithm economics-based decision
    in strategic_intent.create_decision_data().

    This function looks at actual energy flows to determine what the battery
    appeared to be doing. It cannot determine economic intent (e.g., whether
    discharge was profitable export vs load support) - that requires price data.

    Args:
        power: Battery power in kW (+ charging, - discharging)
        energy_data: Complete energy flow data

    Returns:
        Inferred strategic intent string based on observed flows
    """
    if power > 0.1:  # CHARGING
        if energy_data.grid_to_battery > 0.01:
            return (
                "GRID_CHARGING"  # Grid must participate → battery_first, grid_charge=ON
            )
        else:
            return "SOLAR_STORAGE"  # Solar surplus covers it → load_first
    elif power < -0.1:  # DISCHARGING
        if energy_data.battery_to_grid > 0.01:  # ANY export needs capability
            return "BATTERY_EXPORT"  # Enable export capability
        else:
            return "LOAD_SUPPORT"  # Pure home support
    else:
        return "IDLE"


@dataclass
class EnergyData:
    """Energy data with automatic detailed flow calculation using physical constraints."""

    # Core energy flows (kWh) - all provided by caller
    solar_production: float
    home_consumption: float
    battery_charged: float
    battery_discharged: float
    grid_imported: float
    grid_exported: float

    # Battery state (kWh) - State of Energy for consistent units
    battery_soe_start: float  # kWh (changed from battery_soc_start)
    battery_soe_end: float  # kWh (changed from battery_soc_end)

    # Solar production never delivered as AC-side export/consumption (kWh).
    # Two causes: the inverter AC output cap (DC production the inverter
    # could neither convert to AC nor store in a full/rate-limited battery,
    # zero unless inverter_max_ac_power_kw is enabled), or the solar-sourced
    # share of a period's export curtailed to zero at runtime by PV
    # export-limit curtailment (#502, zero unless export_curtailment_enabled
    # -- see apply_export_curtailment_to_period_data).
    clipped_solar: float = 0.0

    # Detailed flows (calculated automatically in __post_init__)
    solar_to_home: float = field(default=0.0, init=False)
    solar_to_battery: float = field(default=0.0, init=False)
    solar_to_grid: float = field(default=0.0, init=False)
    grid_to_home: float = field(default=0.0, init=False)
    grid_to_battery: float = field(default=0.0, init=False)
    battery_to_home: float = field(default=0.0, init=False)
    battery_to_grid: float = field(default=0.0, init=False)

    def __post_init__(self):
        """Automatically calculate detailed flows when EnergyData is created."""
        self._calculate_detailed_flows()

    def _calculate_detailed_flows(self) -> None:
        """
        Calculate detailed energy flows using energy accounting for hourly aggregated data.

        CORRECTED APPROACH FOR HOURLY DATA:
        - Removes invalid "no simultaneous import/export" constraint
        - Uses actual grid_imported/grid_exported totals from sensor data
        - Distributes flows based on energy priorities and accounting principles
        - Ensures detailed flows always sum to measured totals
        """

        # Step 1: Solar allocation (home has highest priority)
        solar_to_home = min(self.solar_production, self.home_consumption)
        remaining_solar = self.solar_production - solar_to_home

        # Solar priority: home first, then battery charging, then grid export.
        solar_to_battery = min(remaining_solar, self.battery_charged)

        # Battery charging is DC-coupled, so only what is left after it must
        # pass the inverter's AC stage - and clipped solar never made it
        # through. Both solar_to_home and solar_to_grid are therefore limited
        # by that AC throughput, not by raw DC production.
        ac_solar = max(
            0.0, self.solar_production - solar_to_battery - self.clipped_solar
        )
        solar_to_home = min(solar_to_home, ac_solar)
        solar_to_grid = ac_solar - solar_to_home

        remaining_consumption = self.home_consumption - solar_to_home

        # Step 2: Battery discharge allocation (home consumption priority)
        battery_to_home = min(self.battery_discharged, remaining_consumption)
        remaining_consumption -= battery_to_home

        # Remaining battery discharge goes to grid export
        battery_to_grid = self.battery_discharged - battery_to_home

        # Step 3: Grid flow allocation (uses actual measured totals)
        # Grid to battery is whatever battery charging wasn't covered by solar
        grid_to_battery = min(
            max(0, self.battery_charged - solar_to_battery), self.grid_imported
        )
        # Grid to home is capped by what home still needs after solar+battery.
        # Any leftover grid_imported beyond that is cross-sensor noise between
        # independent lifetime counters (see validate_energy_balance's
        # tolerance) - it must not be invented as a flow to an entity that
        # consumed nothing.
        grid_to_home = min(
            remaining_consumption, max(0, self.grid_imported - grid_to_battery)
        )

        # Step 4: Export flow reconciliation, capped by what the battery
        # actually discharged - never invented to force-match grid_exported,
        # for the same cross-sensor-noise reason as grid_to_home above.
        battery_to_grid = min(
            max(0, self.grid_exported - solar_to_grid),
            self.battery_discharged - battery_to_home,
        )

        # A battery_to_grid below the lifetime counter's own resolution
        # (GRID_FLOW_RESOLUTION_KWH) can't be told apart from counter noise
        # between battery_discharged and home_consumption - and unlike a real
        # export, it doesn't require the inverter to have been in an
        # export-capable mode. Fold it back into battery_to_home rather than
        # let it flip the observed intent to BATTERY_EXPORT (see issue #350).
        #
        # The DP's self-throttle threshold is derived from this same constant
        # (#497), so a planned discharge can no longer land in a band where the
        # optimizer credits an export that this fold then erases.
        #
        # Only when battery_to_home > 0: the battery was already covering a
        # genuine home deficit, so a sub-resolution overshoot plausibly means
        # home_consumption's own meter under-read by that amount. When
        # battery_to_home == 0 (home's need was already fully met by solar),
        # there's no deficit to fold into - any nonzero export, however small,
        # has nowhere else to have gone and must stay a real export.
        if battery_to_home > 0 and 0 < battery_to_grid < GRID_FLOW_RESOLUTION_KWH:
            battery_to_home += battery_to_grid
            battery_to_grid = 0.0

        # Assign calculated flows
        self.solar_to_home = solar_to_home
        self.solar_to_battery = solar_to_battery
        self.solar_to_grid = solar_to_grid
        self.grid_to_home = grid_to_home
        self.grid_to_battery = grid_to_battery
        self.battery_to_home = battery_to_home
        self.battery_to_grid = battery_to_grid

    @property
    def battery_net_change(self) -> float:
        """Net battery energy change (positive = charged, negative = discharged)."""
        return self.battery_charged - self.battery_discharged

    @property
    def soe_change_kwh(self) -> float:
        """SOE change during this period in kWh."""
        return self.battery_soe_end - self.battery_soe_start

    def validate_energy_balance(self, tolerance: float = 0.2) -> tuple[bool, str]:
        """Validate energy balance - always warn and continue, never fail."""
        energy_in = (
            self.solar_production
            - self.clipped_solar
            + self.grid_imported
            + self.battery_discharged
        )
        energy_out = self.home_consumption + self.grid_exported + self.battery_charged
        balance_error = abs(energy_in - energy_out)

        if balance_error <= tolerance:
            return True, f"Energy balance OK: {balance_error:.3f} kWh error"
        else:
            logger.warning(
                f"Energy balance warning: In={energy_in:.2f}, Out={energy_out:.2f}, "
                f"Error={balance_error:.2f} kWh"
            )
            return (
                True,
                f"Energy balance warning: {balance_error:.2f} kWh error (continuing)",
            )


@dataclass
class EconomicData:
    """Economic analysis data for one time period."""

    buy_price: float = 0.0  # per kWh - price to buy from grid
    sell_price: float = 0.0  # per kWh - price to sell to grid
    import_cost: float = 0.0  # cost of grid imports (grid_imported * buy_price)
    export_revenue: float = (
        0.0  # revenue from grid exports (grid_exported * sell_price)
    )
    grid_cost: float = 0.0  # cost of grid interactions (imports - exports)
    battery_cycle_cost: float = 0.0  # battery degradation cost
    hourly_cost: float = 0.0  # total optimized cost for this hour
    grid_only_cost: float = 0.0  # pure grid cost (home_consumption * buy_price)
    solar_only_cost: float = (
        0.0  # cost with solar only (no battery - algorithm baseline)
    )
    hourly_savings: float = 0.0  # savings vs baseline scenario
    solar_savings: float = field(default=0.0, init=False)  # calculated automatically

    def __post_init__(self):
        """Calculate derived economic fields."""
        # Calculate solar savings: Grid-Only → Solar-Only savings
        self.solar_savings = self.grid_only_cost - self.solar_only_cost

    def calculate_net_value(self) -> float:
        """Calculate net economic value (savings minus costs)."""
        return self.hourly_savings - self.battery_cycle_cost

    @classmethod
    def from_energy_data(
        cls,
        energy_data: EnergyData,
        buy_price: float,
        sell_price: float,
        battery_cycle_cost: float = 0.0,
    ) -> "EconomicData":
        """
        Create EconomicData from EnergyData and prices using standard calculations.

        This method encapsulates the economic calculation logic used throughout the system,
        ensuring consistency between optimization and historical data analysis.

        Args:
            energy_data: Energy flows for the period
            buy_price: Price to buy from grid (per kWh)
            sell_price: Price to sell to grid (per kWh)
            battery_cycle_cost: Battery degradation cost - should include actual wear cost

        Returns:
            EconomicData with all calculated fields
        """
        # Grid cost: what we paid/earned from grid
        import_cost = energy_data.grid_imported * buy_price
        export_revenue = energy_data.grid_exported * sell_price
        grid_cost = import_cost - export_revenue

        # Total cost: grid interactions + battery wear
        hourly_cost = grid_cost + battery_cycle_cost

        # Grid-only baseline: cost if we only used grid (no solar, no battery)
        grid_only_cost = energy_data.home_consumption * buy_price

        # Solar-only baseline: cost if we had solar but no battery.
        # A battery-less system faces the same inverter AC cap, so only the
        # AC-deliverable share of production counts. Clipping means the AC
        # stage was saturated, so its throughput that period - production less
        # what went DC-side to the battery, less what was clipped - is the cap.
        usable_solar = energy_data.solar_production
        if energy_data.clipped_solar > 0:
            usable_solar = max(
                0.0,
                energy_data.solar_production
                - energy_data.solar_to_battery
                - energy_data.clipped_solar,
            )

        # If solar > consumption, we export excess at sell_price
        # If solar < consumption, we import deficit at buy_price
        solar_only_cost = (
            max(0, energy_data.home_consumption - usable_solar) * buy_price
            - max(0, usable_solar - energy_data.home_consumption) * sell_price
        )

        # Savings: solar-only baseline minus actual cost
        hourly_savings = solar_only_cost - hourly_cost

        return cls(
            buy_price=buy_price,
            sell_price=sell_price,
            import_cost=import_cost,
            export_revenue=export_revenue,
            grid_cost=grid_cost,
            battery_cycle_cost=battery_cycle_cost,
            hourly_cost=hourly_cost,
            grid_only_cost=grid_only_cost,
            solar_only_cost=solar_only_cost,
            hourly_savings=hourly_savings,
        )


@dataclass
class EconomicSummary:
    """Economic summary for optimization results."""

    grid_only_cost: float  # cost using only grid electricity
    solar_only_cost: float
    battery_solar_cost: float
    grid_to_solar_savings: float  # savings from solar vs grid-only
    grid_to_battery_solar_savings: float  # savings from battery+solar vs grid-only
    solar_to_battery_solar_savings: float
    grid_to_battery_solar_savings_pct: float  # % - percentage savings vs grid-only
    total_charged: float
    total_discharged: float


@dataclass
class DecisionData:
    """Strategic analysis and decision data."""

    strategic_intent: str = (
        "IDLE"  # DP-planned intent (authoritative) - set at optimization time
    )
    observed_intent: str | None = (
        None  # What actually happened (for dashboard) - inferred from flows
    )
    battery_action: float | None = (
        None  # kWh per period - planned battery energy action (+ charge, - discharge)
    )
    cost_basis: float = 0.0  # per kWh - cost basis of stored energy
    shadow_price: float = (
        0.0  # SEK per kWh DELIVERED - marginal opportunity value of stored
        # energy, priced per kWh out of the battery rather than per kWh of SoE
        # (#683; the two differ by the discharge efficiency, delivered =
        # dV/dSoE / eta). REPORTING ONLY (#526): it is a
        # reading of the interpolant the policy walks (#571,
        # `_value_of_delivering_below`), so it does not exist at or below the
        # reserve floor, where there is no cell underneath to price,
        # and 0.0 is indistinguishable between "computed as worthless" and
        # "never computed". No consumer may re-derive a decision from it --
        # read intra_period_discharge_allowed instead.
    )
    intra_period_discharge_allowed: bool = (
        False  # DP's decision (#526): may the sub-period discharge ceiling be
        # opened for this period? Decided where the value function is owned,
        # using dV/dSoE when it exists. False where no shadow price is
        # computable: at the bottom grid level there is no removable kWh below
        # this state, so there is nothing to authorize. Absence is never
        # permission -- a decision this DP did not make stays False.
    )
    future_value: float = (
        0.0  # DP value-to-go (continuation_value) from the resulting battery
        # level onward -- the best achievable outcome from here forward.
    )
    curtailed: bool = (
        False  # Planned PV curtailment (#501): grid_exported > 0 and
        # sell_price below export_curtailment_price_floor while curtailment
        # is active. Mirrors BSM's execution-time gate
        # (_apply_period_schedule's should_curtail) so the plan can report
        # what actuation will do, distinct from a genuinely profitable
        # SOLAR_EXPORT.
    )

    @classmethod
    def from_observed_flows(cls, energy_data: EnergyData) -> "DecisionData":
        """Create DecisionData from actual sensor data with observed intent.

        This sets observed_intent (what actually happened) based on energy flows.
        Use this for historical periods where we have sensor data but may not
        have the original DP-planned intent.

        Args:
            energy_data: Actual energy data from sensors

        Returns:
            DecisionData with observed_intent set (strategic_intent remains IDLE)
        """
        # Use battery net change as power approximation (kWh ≈ kW for quarter-hourly data)
        battery_power = energy_data.battery_net_change
        observed = infer_intent_from_flows(battery_power, energy_data)

        return cls(observed_intent=observed)


@dataclass
class PeriodData:
    """
    Period data with energy, economic, and decision information.

    Represents a single period which can be:
    - Hourly resolution: 1-hour period (60 minutes), period index 0-23
    - Quarterly resolution: 15-minute period, period index 0-95

    Composes pure energy data with economic analysis and strategic decisions.
    """

    # Required fields first (no defaults)
    period: int  # Period index (0-23 for hourly, 0-95 for quarterly)
    energy: EnergyData

    # Optional fields with defaults
    timestamp: datetime | None = None
    data_source: str = "predicted"  # "actual" or "predicted"
    economic: EconomicData = field(default_factory=EconomicData)
    decision: DecisionData = field(default_factory=DecisionData)

    # Factory methods for creating instances
    @classmethod
    def from_energy_data(
        cls,
        period: int,
        energy_data: EnergyData,
        data_source: str = "actual",
        timestamp: datetime | None = None,
    ) -> "PeriodData":
        """Create PeriodData from pure energy data (sensor input)."""
        return cls(
            period=period,
            energy=energy_data,
            timestamp=timestamp or datetime.now(),
            data_source=data_source,
        )

    @classmethod
    def from_optimization(
        cls,
        period: int,
        energy_data: EnergyData,
        economic_data: EconomicData,
        decision_data: DecisionData,
        timestamp: datetime | None = None,
    ) -> "PeriodData":
        """Create complete PeriodData from optimization algorithm."""
        return cls(
            period=period,
            energy=energy_data,
            timestamp=timestamp or datetime.now(),
            data_source="predicted",
            economic=economic_data,
            decision=decision_data,
        )

    def validate_data(self) -> list[str]:
        """Validate all data components and return any errors."""
        errors = []

        # Validate period index (must be non-negative, no upper bound due to DST)
        if self.period < 0:
            errors.append(f"Invalid period: {self.period}, must be non-negative")

        # Validate energy balance
        is_valid, message = self.energy.validate_energy_balance()
        if not is_valid:
            errors.append(f"Energy balance error: {message}")

        # Validate SOC range
        if not 0 <= self.energy.battery_soe_start <= 100:
            errors.append(f"Invalid start SOE: {self.energy.battery_soe_start}%")
        if not 0 <= self.energy.battery_soe_end <= 100:
            errors.append(f"Invalid end SOE: {self.energy.battery_soe_end}%")

        return errors


def apply_export_curtailment_to_period_data(
    period_data: PeriodData,
    export_curtailment_active: bool,
    export_curtailment_price_floor: float,
) -> PeriodData:
    """Return a reporting-only view of period_data with export curtailment
    applied, for a period that will actually be curtailed to zero export at
    runtime (#502): exporting at a sell price below the floor, with
    export_curtailment_active True (the caller-computed, capability-aware
    flag -- never the raw settings field, so reporting can't disagree with
    what BSM's execution-time trigger will actually do on this platform).

    The curtailed energy is reported as unharvested production (folded into
    clipped_solar, mechanically identical to existing AC-cap clipping), not
    as harvested and discarded -- because the hardware mechanism this models
    only throttles PV/MPPT production (ha_api_controller.
    set_growatt_export_limit's own comment), never battery discharge. Only
    the solar-sourced share of grid_exported (energy.solar_to_grid) is
    curtailed here; any battery-sourced export (energy.battery_to_grid)
    still happens and is still reported at its real cost.

    Returns period_data unchanged if curtailment doesn't apply, or if the
    period's export was entirely battery-sourced (nothing PV-side to
    curtail). Never mutates the input -- callers must apply this only at
    reporting seams, never to the PeriodData BSM stores in schedule_store,
    which the execution-time curtailment trigger and the DP's guardrail
    comparison both require to stay at the honest, real price.
    """
    energy = period_data.energy
    economic = period_data.economic
    curtailed_solar_export = energy.solar_to_grid
    if (
        not export_curtailment_active
        or energy.grid_exported <= 0
        or economic.sell_price >= export_curtailment_price_floor
        or curtailed_solar_export <= 0
    ):
        return period_data

    adjusted_energy = EnergyData(
        solar_production=energy.solar_production,
        home_consumption=energy.home_consumption,
        battery_charged=energy.battery_charged,
        battery_discharged=energy.battery_discharged,
        grid_imported=energy.grid_imported,
        grid_exported=energy.grid_exported - curtailed_solar_export,
        battery_soe_start=energy.battery_soe_start,
        battery_soe_end=energy.battery_soe_end,
        clipped_solar=energy.clipped_solar + curtailed_solar_export,
    )
    adjusted_economic = EconomicData.from_energy_data(
        adjusted_energy,
        economic.buy_price,
        economic.sell_price,
        economic.battery_cycle_cost,
    )
    return replace(period_data, energy=adjusted_energy, economic=adjusted_economic)


@dataclass
class OptimizationResult:
    """Result structure returned by optimize_battery_schedule."""

    input_data: dict
    period_data: list[PeriodData]
    economic_summary: EconomicSummary | None = None
    # The DP's *own* objective value for this schedule: the negated sum of
    # each period's `_compute_reward` return, accumulated as the actions were
    # chosen (or recomputed by `_replay_accounting_pass` when the hybrid PWL
    # path re-solves a window). This is the quantity the optimizer actually
    # minimises, and the only one safe to compare across algorithms or pin in
    # a regression test -- `economic_summary.battery_solar_cost` is rebuilt
    # from reported PeriodData and can drift from it (see TODO.md's
    # `_build_period_data` reporting-drift entry).
    #
    # `None` means "not produced by an optimizer run": the all-IDLE safety-net
    # schedule and results constructed directly in tests carry no reward
    # accumulation. It is never a degraded stand-in for a real value.
    reward_objective_cost: float | None = None
