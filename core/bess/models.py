# core/bess/models.py
"""
Data models for the BESS system.

This module contains dataclasses representing various data structures used throughout
the BESS system, providing type safety and clear interfaces between components.

"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

__all__ = [
    "DecisionData",
    "EconomicData",
    "EnergyData",
    "OptimizationResult",
    "PeriodData",
    "infer_intent_from_flows",
]


def infer_intent_from_flows(power: float, energy_data: "EnergyData") -> str:
    """
    Infer strategic intent from observed energy flows.

    NOTE: For OBSERVATIONAL purposes only (dashboard display of what happened).
    The authoritative intent comes from DP algorithm economics-based decision
    in decision_intelligence.create_decision_data().

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
        if energy_data.grid_to_battery > 0.1:  # ANY grid charging needs capability
            return "GRID_CHARGING"  # Enable grid charging capability
        elif energy_data.solar_to_battery > 0.1 or energy_data.solar_production > 0.1:
            return "SOLAR_STORAGE"  # Solar charging (check both flows and production)
        else:
            # Small amounts of charging from unclear source - default to grid
            return "GRID_CHARGING"
    elif power < -0.1:  # DISCHARGING
        if energy_data.battery_to_grid > 0.1:  # ANY export needs capability
            return "EXPORT_ARBITRAGE"  # Enable export capability
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
        remaining_consumption = self.home_consumption - solar_to_home

        # Solar priority: home first, then battery charging, then grid export
        solar_to_battery = min(remaining_solar, self.battery_charged)
        solar_to_grid = max(0, remaining_solar - solar_to_battery)

        # Step 2: Battery discharge allocation (home consumption priority)
        battery_to_home = min(self.battery_discharged, remaining_consumption)
        remaining_consumption -= battery_to_home

        # Remaining battery discharge goes to grid export
        battery_to_grid = self.battery_discharged - battery_to_home

        # Step 3: Grid flow allocation (uses actual measured totals)
        # Grid import covers remaining home consumption first, then battery charging
        grid_to_home = min(self.grid_imported, remaining_consumption)
        # Grid to battery is whatever battery charging wasn't covered by solar
        # Must be constrained by actual battery_charged to avoid impossible flows
        grid_to_battery = max(0, self.battery_charged - solar_to_battery)

        # Step 4: Export flow reconciliation (ensure exports match measured total)
        calculated_export = solar_to_grid + battery_to_grid
        if self.grid_exported != calculated_export:
            # Adjust battery_to_grid to match actual grid export total
            battery_to_grid = self.grid_exported - solar_to_grid

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
        energy_in = self.solar_production + self.grid_imported + self.battery_discharged
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

    buy_price: float = 0.0  # SEK/kWh - price to buy from grid
    sell_price: float = 0.0  # SEK/kWh - price to sell to grid
    grid_cost: float = 0.0  # SEK - cost of grid interactions (imports - exports)
    battery_cycle_cost: float = 0.0  # SEK - battery degradation cost
    hourly_cost: float = 0.0  # SEK - total optimized cost for this hour
    grid_only_cost: float = 0.0  # SEK - pure grid cost (home_consumption * buy_price)
    solar_only_cost: float = (
        0.0  # SEK - cost with solar only (no battery - algorithm baseline)
    )
    hourly_savings: float = 0.0  # SEK - savings vs baseline scenario
    solar_savings: float = field(
        default=0.0, init=False
    )  # SEK - calculated automatically

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
            buy_price: Price to buy from grid (SEK/kWh)
            sell_price: Price to sell to grid (SEK/kWh)
            battery_cycle_cost: Battery degradation cost (SEK) - should include actual wear cost

        Returns:
            EconomicData with all calculated fields
        """
        # Grid cost: what we paid/earned from grid
        grid_cost = (
            energy_data.grid_imported * buy_price
            - energy_data.grid_exported * sell_price
        )

        # Total cost: grid interactions + battery wear
        hourly_cost = grid_cost + battery_cycle_cost

        # Grid-only baseline: cost if we only used grid (no solar, no battery)
        grid_only_cost = energy_data.home_consumption * buy_price

        # Solar-only baseline: cost if we had solar but no battery
        # If solar > consumption, we export excess at sell_price
        # If solar < consumption, we import deficit at buy_price
        solar_only_cost = (
            max(0, energy_data.home_consumption - energy_data.solar_production)
            * buy_price
            - max(0, energy_data.solar_production - energy_data.home_consumption)
            * sell_price
        )

        # Savings: solar-only baseline minus actual cost
        hourly_savings = solar_only_cost - hourly_cost

        return cls(
            buy_price=buy_price,
            sell_price=sell_price,
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

    grid_only_cost: float  # SEK - cost using only grid electricity
    solar_only_cost: float
    battery_solar_cost: float
    grid_to_solar_savings: float  # SEK - savings from solar vs grid-only
    grid_to_battery_solar_savings: (
        float  # SEK - savings from battery+solar vs grid-only
    )
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
    cost_basis: float = 0.0  # SEK/kWh - cost basis of stored energy

    # Enhanced intelligence fields (optional)
    pattern_name: str = ""  # Name of detected pattern
    description: str = ""  # Human-readable description
    economic_chain: str = ""  # Economic reasoning chain
    immediate_value: float = 0.0  # Immediate economic value
    future_value: float = 0.0  # Future economic value
    net_strategy_value: float = 0.0  # Net strategic value

    # Simple enhanced fields that we can actually implement
    advanced_flow_pattern: str = (
        ""  # Detailed flow pattern (e.g., SOLAR_TO_HOME_AND_BATTERY)
    )
    detailed_flow_values: dict[str, float] = field(
        default_factory=dict
    )  # Value per flow (SEK)
    future_target_hours: list[int] = field(
        default_factory=list
    )  # When future opportunity occurs

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


@dataclass
class OptimizationResult:
    """Result structure returned by optimize_battery_schedule."""

    input_data: dict
    period_data: list[PeriodData]
    economic_summary: EconomicSummary | None = None
