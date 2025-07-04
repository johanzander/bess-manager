# core/bess/models.py
"""
Data models for the BESS system.

This module contains dataclasses representing various data structures used throughout
the BESS system, providing type safety and clear interfaces between components.

"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

__all__ = [
    "EconomicData",
    "EnergyData",
    "NewHourlyData",
    "StrategyData",
]


@dataclass
class EnergyData:
    """
    Pure energy flow data - just the physics, no context about when/where.
    This represents the actual energy flows measured by sensors or calculated by algorithms.
    """

    # Core energy flows (kWh) - directly from sensors
    solar_generated: float
    home_consumed: float
    grid_imported: float
    grid_exported: float
    battery_charged: float
    battery_discharged: float

    # Battery state (%) - directly from sensors
    battery_soc_start: float  # % (0-100) - SOC at start of hour
    battery_soc_end: float  # % (0-100) - SOC at end of hour

    # Detailed energy flows (calculated from core flows)
    solar_to_home: float = 0.0
    solar_to_battery: float = 0.0
    solar_to_grid: float = 0.0
    grid_to_home: float = 0.0
    grid_to_battery: float = 0.0
    battery_to_home: float = 0.0
    battery_to_grid: float = 0.0

    @property
    def battery_net_change(self) -> float:
        """Net battery energy change (positive = charged, negative = discharged)."""
        return self.battery_charged - self.battery_discharged

    @property
    def soc_change_percent(self) -> float:
        """SOC change during this period in percentage points."""
        return self.battery_soc_end - self.battery_soc_start

    def calculate_detailed_flows(self) -> None:
        """Calculate detailed energy flows from core flows using physics."""
        # Step 1: Solar first supplies home load (highest priority)
        self.solar_to_home = min(self.solar_generated, self.home_consumed)
        solar_excess = max(0, self.solar_generated - self.solar_to_home)
        remaining_home_consumption = max(0, self.home_consumed - self.solar_to_home)

        # Step 2: Determine battery flows based on net battery change
        if self.battery_charged > 0:  # Charging occurred
            # Solar goes to battery first, then grid if needed
            self.solar_to_battery = min(solar_excess, self.battery_charged)
            self.grid_to_battery = max(0, self.battery_charged - self.solar_to_battery)
            # Remaining solar goes to grid
            self.solar_to_grid = max(0, solar_excess - self.solar_to_battery)
            # Grid supplies remaining home consumption
            self.grid_to_home = remaining_home_consumption

        elif self.battery_discharged > 0:  # Discharging occurred
            # Battery supplies home first, then grid if excess
            self.battery_to_home = min(
                self.battery_discharged, remaining_home_consumption
            )
            self.battery_to_grid = max(
                0, self.battery_discharged - self.battery_to_home
            )
            # Grid supplies any remaining home consumption
            self.grid_to_home = max(
                0, remaining_home_consumption - self.battery_to_home
            )
            # All solar excess goes to grid
            self.solar_to_grid = solar_excess

        else:  # No battery action (idle)
            self.grid_to_home = remaining_home_consumption
            self.solar_to_grid = solar_excess

    def validate_energy_balance(self, tolerance: float = 0.1) -> tuple[bool, str]:
        """Validate energy balance - energy in should equal energy out."""
        energy_in = self.solar_generated + self.grid_imported + self.battery_discharged

        energy_out = self.home_consumed + self.grid_exported + self.battery_charged

        balance_error = abs(energy_in - energy_out)

        if balance_error <= tolerance:
            return True, f"Energy balance OK: {balance_error:.3f} kWh error"
        else:
            return (
                False,
                f"Energy balance error: In={energy_in:.2f}, Out={energy_out:.2f}, Error={balance_error:.2f} kWh",
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnergyData":
        """Create EnergyData from dictionary with validation."""
        # Validate required fields
        solar_generated = data.get("solar_generated")
        if solar_generated is None:
            raise ValueError("solar_generated is required")
        if not isinstance(solar_generated, int | float):
            raise ValueError("solar_generated must be numeric")

        home_consumed = data.get("home_consumed")
        if home_consumed is None:
            raise ValueError("home_consumed is required")
        if not isinstance(home_consumed, int | float):
            raise ValueError("home_consumed must be numeric")

        grid_imported = data.get("grid_imported")
        if grid_imported is None:
            raise ValueError("grid_imported is required")
        if not isinstance(grid_imported, int | float):
            raise ValueError("grid_imported must be numeric")

        grid_exported = data.get("grid_exported")
        if grid_exported is None:
            raise ValueError("grid_exported is required")
        if not isinstance(grid_exported, int | float):
            raise ValueError("grid_exported must be numeric")

        battery_charged = data.get("battery_charged")
        if battery_charged is None:
            raise ValueError("battery_charged is required")
        if not isinstance(battery_charged, int | float):
            raise ValueError("battery_charged must be numeric")

        battery_discharged = data.get("battery_discharged")
        if battery_discharged is None:
            raise ValueError("battery_discharged is required")
        if not isinstance(battery_discharged, int | float):
            raise ValueError("battery_discharged must be numeric")

        battery_soc_start = data.get("battery_soc_start")
        if battery_soc_start is None:
            raise ValueError("battery_soc_start is required")
        if not isinstance(battery_soc_start, int | float):
            raise ValueError("battery_soc_start must be numeric")

        battery_soc_end = data.get("battery_soc_end")
        if battery_soc_end is None:
            raise ValueError("battery_soc_end is required")
        if not isinstance(battery_soc_end, int | float):
            raise ValueError("battery_soc_end must be numeric")

        return cls(
            solar_generated=solar_generated,
            home_consumed=home_consumed,
            grid_imported=grid_imported,
            grid_exported=grid_exported,
            battery_charged=battery_charged,
            battery_discharged=battery_discharged,
            battery_soc_start=battery_soc_start,
            battery_soc_end=battery_soc_end,
            # Detailed flows can be provided or calculated later
            solar_to_home=data.get("solar_to_home", 0.0),
            solar_to_battery=data.get("solar_to_battery", 0.0),
            solar_to_grid=data.get("solar_to_grid", 0.0),
            grid_to_home=data.get("grid_to_home", 0.0),
            grid_to_battery=data.get("grid_to_battery", 0.0),
            battery_to_home=data.get("battery_to_home", 0.0),
            battery_to_grid=data.get("battery_to_grid", 0.0),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert EnergyData to dictionary."""
        return {
            "solar_generated": self.solar_generated,
            "home_consumed": self.home_consumed,
            "grid_imported": self.grid_imported,
            "grid_exported": self.grid_exported,
            "battery_charged": self.battery_charged,
            "battery_discharged": self.battery_discharged,
            "battery_soc_start": self.battery_soc_start,
            "battery_soc_end": self.battery_soc_end,
            "battery_net_change": self.battery_net_change,
            "soc_change_percent": self.soc_change_percent,
            "solar_to_home": self.solar_to_home,
            "solar_to_battery": self.solar_to_battery,
            "solar_to_grid": self.solar_to_grid,
            "grid_to_home": self.grid_to_home,
            "grid_to_battery": self.grid_to_battery,
            "battery_to_home": self.battery_to_home,
            "battery_to_grid": self.battery_to_grid,
        }


@dataclass
class EconomicData:
    """Economic analysis data for one time period."""

    buy_price: float = 0.0  # SEK/kWh - price to buy from grid
    sell_price: float = 0.0  # SEK/kWh - price to sell to grid
    grid_cost: float = 0.0  # SEK - cost of grid interactions (imports - exports)
    battery_cycle_cost: float = 0.0  # SEK - battery degradation cost
    hourly_cost: float = 0.0  # SEK - total optimized cost for this hour
    base_case_cost: float = 0.0  # SEK - cost without optimization (baseline)
    hourly_savings: float = 0.0  # SEK - savings vs baseline scenario

    def calculate_net_value(self) -> float:
        """Calculate net economic value (savings minus costs)."""
        return self.hourly_savings - self.battery_cycle_cost


@dataclass
class EconomicSummary:
    """Economic summary for optimization results."""

    base_cost: float
    solar_only_cost: float
    battery_solar_cost: float
    base_to_solar_savings: float
    base_to_battery_solar_savings: float
    solar_to_battery_solar_savings: float
    base_to_battery_solar_savings_pct: float
    total_charged: float
    total_discharged: float


@dataclass
class StrategyData:
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
    risk_factors: list[str] = field(
        default_factory=list
    )  # Risk factors for this decision


@dataclass
class NewHourlyData:
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
    strategy: StrategyData = field(default_factory=StrategyData)

    # Convenience properties for backward compatibility
    @property
    def solar_generated(self) -> float:
        return self.energy.solar_generated

    @property
    def home_consumed(self) -> float:
        return self.energy.home_consumed

    @property
    def grid_imported(self) -> float:
        return self.energy.grid_imported

    @property
    def grid_exported(self) -> float:
        return self.energy.grid_exported

    @property
    def battery_charged(self) -> float:
        return self.energy.battery_charged

    @property
    def battery_discharged(self) -> float:
        return self.energy.battery_discharged

    @property
    def battery_soc_start(self) -> float:
        return self.energy.battery_soc_start

    @property
    def battery_soc_end(self) -> float:
        return self.energy.battery_soc_end

    @property
    def battery_net_change(self) -> float:
        return self.energy.battery_net_change

    @property
    def strategic_intent(self) -> str:
        return self.strategy.strategic_intent

    @property
    def battery_action(self) -> float | None:
        return self.strategy.battery_action

    @property
    def buy_price(self) -> float:
        return self.economic.buy_price

    @property
    def sell_price(self) -> float:
        return self.economic.sell_price

    @property
    def hourly_cost(self) -> float:
        return self.economic.hourly_cost

    @property
    def hourly_savings(self) -> float:
        return self.economic.hourly_savings

    @property
    def battery_cycle_cost(self) -> float:
        return self.economic.battery_cycle_cost

    # Factory methods for creating instances
    @classmethod
    def from_energy_data(
        cls,
        hour: int,
        energy_data: EnergyData,
        data_source: str = "actual",
        timestamp: datetime | None = None,
    ) -> "NewHourlyData":
        """Create NewHourlyData from pure energy data (sensor input)."""
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
        strategy_data: StrategyData,
        timestamp: datetime | None = None,
    ) -> "NewHourlyData":
        """Create complete NewHourlyData from optimization algorithm."""
        return cls(
            hour=hour,
            energy=energy_data,
            timestamp=timestamp or datetime.now(),
            data_source="predicted",
            economic=economic_data,
            strategy=strategy_data,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert NewHourlyData to dictionary for API compatibility."""
        return {
            "hour": self.hour,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "data_source": self.data_source,
            # Energy fields
            "solar_generated": self.energy.solar_generated,
            "home_consumed": self.energy.home_consumed,
            "grid_imported": self.energy.grid_imported,
            "grid_exported": self.energy.grid_exported,
            "battery_charged": self.energy.battery_charged,
            "battery_discharged": self.energy.battery_discharged,
            "battery_soc_start": self.energy.battery_soc_start,
            "battery_soc_end": self.energy.battery_soc_end,
            "battery_net_change": self.energy.battery_net_change,
            # Detailed flows
            "solar_to_home": self.energy.solar_to_home,
            "solar_to_battery": self.energy.solar_to_battery,
            "solar_to_grid": self.energy.solar_to_grid,
            "grid_to_home": self.energy.grid_to_home,
            "grid_to_battery": self.energy.grid_to_battery,
            "battery_to_home": self.energy.battery_to_home,
            "battery_to_grid": self.energy.battery_to_grid,
            # Economic fields
            "buy_price": self.economic.buy_price,
            "sell_price": self.economic.sell_price,
            "hourly_cost": self.economic.hourly_cost,
            "hourly_savings": self.economic.hourly_savings,
            "battery_cycle_cost": self.economic.battery_cycle_cost,
            # Strategy fields
            "strategic_intent": self.strategy.strategic_intent,
            "battery_action": self.strategy.battery_action,
            "cost_basis": self.strategy.cost_basis,
            "pattern_name": self.strategy.pattern_name,
            "description": self.strategy.description,
        }

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
        if not 0 <= self.energy.battery_soc_start <= 100:
            errors.append(f"Invalid start SOC: {self.energy.battery_soc_start}%")
        if not 0 <= self.energy.battery_soc_end <= 100:
            errors.append(f"Invalid end SOC: {self.energy.battery_soc_end}%")

        return errors


@dataclass
class OptimizationResult:
    """Result structure returned by optimize_battery_schedule."""

    input_data: dict
    hourly_data: list[NewHourlyData]
    economic_summary: EconomicSummary
