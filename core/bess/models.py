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
    "HourlyData",
    "OptimizationResult",
]


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
        Internal method: Calculate detailed energy flows using physical constraints.

        PHYSICAL CONSTRAINTS IMPLEMENTED:
        1. HOME LOAD PRIORITY - Electrical loads satisfied before grid export
        2. NO SIMULTANEOUS IMPORT/EXPORT - Physical system limitation
        3. BATTERY vs GRID PRIORITY - Typical residential inverter behavior
        """

        # Priority: Solar -> Home first, then remaining solar -> Battery/Grid
        solar_to_home = min(self.solar_production, self.home_consumption)
        remaining_solar = self.solar_production - solar_to_home
        remaining_consumption = self.home_consumption - solar_to_home

        # Solar allocation: battery charging takes priority over grid export
        solar_to_battery = min(remaining_solar, self.battery_charged)
        solar_to_grid = max(0, remaining_solar - solar_to_battery)

        # Battery discharge allocation: home consumption takes priority
        battery_to_home = min(self.battery_discharged, remaining_consumption)
        battery_to_grid = max(0, self.battery_discharged - battery_to_home)

        # Grid imports: fill remaining consumption and battery charging
        grid_to_home = max(0, remaining_consumption - battery_to_home)
        grid_to_battery = max(0, self.battery_charged - solar_to_battery)

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
        "IDLE"  # Strategic intent (GRID_CHARGING, SOLAR_STORAGE, etc.)
    )
    battery_action: float | None = (
        None  # kW - planned battery action (+ charge, - discharge)
    )
    cost_basis: float = 0.0  # SEK/kWh - cost basis of stored energy

    # Enhanced intelligence fields (optional)
    pattern_name: str = ""  # Name of detected pattern
    description: str = ""  # Human-readable description
    economic_chain: str = ""  # Economic reasoning chain
    immediate_value: float = 0.0  # Immediate economic value
    future_value: float = 0.0  # Future economic value
    net_strategy_value: float = 0.0  # Net strategic value


@dataclass
class HourlyData:
    """
    Complete hourly data with context - when/where this data applies.
    Composes pure energy data with economic analysis and strategic decisions.

    """

    # Required fields first (no defaults)
    hour: int  # TODO: Check if someone is actually using this
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
        hour: int,
        energy_data: EnergyData,
        data_source: str = "actual",
        timestamp: datetime | None = None,
    ) -> "HourlyData":
        """Create HourlyData from pure energy data (sensor input)."""
        return cls(
            hour=hour,
            energy=energy_data,
            timestamp=timestamp or datetime.now(),
            data_source=data_source,
        )

    @classmethod
    def from_optimization(
        cls,
        hour: int,
        energy_data: EnergyData,
        economic_data: EconomicData,
        decision_data: DecisionData,
        timestamp: datetime | None = None,
    ) -> "HourlyData":
        """Create complete HourlyData from optimization algorithm."""
        return cls(
            hour=hour,
            energy=energy_data,
            timestamp=timestamp or datetime.now(),
            data_source="predicted",
            economic=economic_data,
            decision=decision_data,
        )

    def validate_data(self) -> list[str]:
        """Validate all data components and return any errors."""
        errors = []

        # Validate hour
        if not 0 <= self.hour <= 23:
            errors.append(f"Invalid hour: {self.hour}, must be 0-23")

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
    hourly_data: list[HourlyData]
    economic_summary: EconomicSummary
