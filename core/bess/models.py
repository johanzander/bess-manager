# core/bess/models.py
"""
Data models for the BESS system.

This module contains dataclasses representing various data structures used throughout
the BESS system, providing type safety and clear interfaces between components.

"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

# Use TYPE_CHECKING to avoid circular imports
if TYPE_CHECKING:
    from core.bess.settings import BatterySettings

logger = logging.getLogger(__name__)

__all__ = [
    "CostScenarios",
    "DecisionData",
    "EconomicData",
    "EnergyData",
    "HourlyData",
    "OptimizationResult"
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
    
    def calculate_detailed_flows(self, battery_settings=None, use_direct_method=False) -> None:
        """
        Calculate detailed energy flows for this EnergyData instance.
        
        This is an instance method that uses the existing core energy values to calculate 
        all detailed energy flows using the canonical calculation function. It updates 
        the instance in-place with the calculated detailed flows.
        
        Args:
            battery_settings: Optional battery settings to use. If None and use_direct_method=False,
                              will try to use the instance's _battery_settings attribute or create a default.
            use_direct_method: If True, uses direct calculation without SOE conversion or battery_settings.
                              Set this to True to avoid BatterySettings dependency.
                              
        Note:
            When use_direct_method=False, this requires battery capacity for SOE calculations.
            Set use_direct_method=True to avoid BatterySettings dependency completely.
        """
        # If using direct method, we don't need battery_settings at all
        if use_direct_method:
            # Use the direct method that doesn't require SOE conversion or battery capacity
            EnergyData.calculate_detailed_flows_direct(self)
            return
            
        # Otherwise proceed with the original SOE-based method
        from .settings import BatterySettings
        
        # Use provided settings, or fallback to instance attribute, or create default
        if battery_settings is None:
            battery_settings = getattr(self, '_battery_settings', None)
            
        if not battery_settings:
            battery_settings = BatterySettings()
            logger.warning(
                "No battery settings provided - using default which may be inaccurate. "
                "Consider using use_direct_method=True to avoid BatterySettings dependency."
            )
            # Store for future use
            self._battery_settings = battery_settings
        
        # Import the canonical function
        from core.bess.dp_battery_algorithm import calculate_energy_flows
        
        # Calculate net battery power for flow calculation
        battery_net_power = self.battery_charged - self.battery_discharged
        
        # Convert percent SOC to kWh for the canonical function
        soe_start = (self.battery_soc_start / 100.0) * battery_settings.total_capacity
        soe_end = (self.battery_soc_end / 100.0) * battery_settings.total_capacity
        
        # Use the canonical function directly with the actual battery values
        # This ensures we use the measured values rather than recalculating from power
        detailed_flows = calculate_energy_flows(
            power=battery_net_power,  # Still include power for compatibility
            home_consumption=self.home_consumed,
            solar_production=self.solar_generated,
            soe_start=soe_start,
            soe_end=soe_end,
            battery_settings=battery_settings,
            dt=1.0,
            battery_charged=self.battery_charged,
            battery_discharged=self.battery_discharged
        )
        
        # Update this instance's detailed flow fields
        self.solar_to_home = detailed_flows.solar_to_home
        self.solar_to_battery = detailed_flows.solar_to_battery
        self.solar_to_grid = detailed_flows.solar_to_grid
        self.grid_to_home = detailed_flows.grid_to_home
        self.grid_to_battery = detailed_flows.grid_to_battery
        self.battery_to_home = detailed_flows.battery_to_home
        self.battery_to_grid = detailed_flows.battery_to_grid
    
    @classmethod
    def create_with_detailed_flows(
        cls,
        solar_generated: float,
        home_consumed: float,
        battery_charged: float,
        battery_discharged: float,
        battery_soc_start: float,
        battery_soc_end: float,
        battery_settings: "BatterySettings",
        dt: float = 1.0
    ) -> "EnergyData":
        """
        Create a new EnergyData instance with detailed flows calculated.
        
        This class factory method creates a new EnergyData instance with all detailed 
        flows calculated using the canonical calculation function. It ensures consistent 
        detailed flows calculated from the same source of truth.
        
        Args:
            solar_generated: Total solar generation in kWh
            home_consumed: Total home consumption in kWh
            battery_charged: Total battery charging in kWh
            battery_discharged: Total battery discharging in kWh
            battery_soc_start: Battery state of charge at start (%)
            battery_soc_end: Battery state of charge at end (%)
            battery_settings: Battery settings for capacity calculations
            dt: Time delta in hours (default 1.0 for hourly data)
            
        Returns:
            EnergyData with all detailed flows calculated
            
        Example usage:
            # Create a new EnergyData with detailed flows
            energy_data = EnergyData.create_with_detailed_flows(
                solar_generated=10.5,
                home_consumed=8.2,
                battery_charged=3.0,
                battery_discharged=1.2,
                battery_soc_start=65.0,
                battery_soc_end=70.0,
                battery_settings=battery_settings,
                dt=1.0
            )
            
        Example usage:
            # Create EnergyData with detailed flows calculated from core flows
            energy_data = EnergyData.create_with_detailed_flows(
                solar_generated=10.5,
                home_consumed=8.2,
                battery_charged=3.0,
                battery_discharged=1.2,
                battery_soc_start=65.0,
                battery_soc_end=70.0,
                battery_settings=battery_settings,
                dt=1.0
            )
            
            # This ensures that all detailed flow fields like solar_to_home, solar_to_battery, etc.
            # are calculated consistently using the canonical function in dp_battery_algorithm.py
        """
        from core.bess.dp_battery_algorithm import calculate_energy_flows
        
        # Convert percent SOC to kWh for the canonical function
        soe_start = (battery_soc_start / 100.0) * battery_settings.total_capacity
        soe_end = (battery_soc_end / 100.0) * battery_settings.total_capacity
        
        # Calculate net battery power (charge is positive, discharge is negative)
        battery_net_power = (battery_charged - battery_discharged) / dt
        
        # Use canonical function to calculate detailed flows
        # Pass both power and actual battery charged/discharged values
        return calculate_energy_flows(
            power=battery_net_power,
            home_consumption=home_consumed,
            solar_production=solar_generated,
            soe_start=soe_start,
            soe_end=soe_end,
            battery_settings=battery_settings,
            dt=dt,
            battery_charged=battery_charged,
            battery_discharged=battery_discharged
        )

    @staticmethod
    def calculate_detailed_flows_direct(energy: "EnergyData") -> "EnergyData":
        """
        Calculate detailed energy flows directly from core flows without using BatterySettings.
        
        This method provides a simpler way to calculate detailed flows when you don't need
        the precision of the battery SOE-based calculations, or when BatterySettings is unavailable.
        
        Args:
            energy: The EnergyData object with core flows populated
            
        Returns:
            Updated EnergyData with detailed flows calculated
        """
        from core.bess.dp_battery_algorithm import calculate_energy_flows_direct
        
        # Use the canonical function that doesn't require SOE conversion or BatterySettings
        # This will properly calculate all detailed flows directly from core energy values
        result = calculate_energy_flows_direct(
            solar_production=energy.solar_generated,
            home_consumption=energy.home_consumed,
            battery_charged=energy.battery_charged,
            battery_discharged=energy.battery_discharged,
            battery_soc_start=energy.battery_soc_start,
            battery_soc_end=energy.battery_soc_end,
            grid_imported=energy.grid_imported,
            grid_exported=energy.grid_exported
        )
        
        # Copy the detailed flows back to the input energy object
        energy.solar_to_home = result.solar_to_home
        energy.solar_to_battery = result.solar_to_battery
        energy.solar_to_grid = result.solar_to_grid
        energy.grid_to_home = result.grid_to_home
        energy.grid_to_battery = result.grid_to_battery
        energy.battery_to_home = result.battery_to_home
        energy.battery_to_grid = result.battery_to_grid
                
        return energy

    def validate_energy_balance(self, tolerance: float = 0.2) -> tuple[bool, str]:
        """Validate energy balance - always warn and continue, never fail."""
        energy_in = self.solar_generated + self.grid_imported + self.battery_discharged
        energy_out = self.home_consumed + self.grid_exported + self.battery_charged
        balance_error = abs(energy_in - energy_out)

        if balance_error <= tolerance:
            return True, f"Energy balance OK: {balance_error:.3f} kWh error"
        else:
            # Always log warning and return True - never fail validation
            logger.warning(
                f"Energy balance warning: In={energy_in:.2f}, Out={energy_out:.2f}, Error={balance_error:.2f} kWh"
            )
            return True, f"Energy balance warning: {balance_error:.2f} kWh error (continuing)"
    
@dataclass
class CostScenarios:
    """All cost scenarios for one hour."""

    base_case_cost: float
    solar_only_cost: float
    battery_solar_cost: float
    solar_savings: float
    battery_savings: float
    total_savings: float
    battery_wear_cost: float

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
    solar_only_cost: float = 0.0  # SEK - cost with solar only (no battery)

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
        return self.decision.strategic_intent

    @property
    def battery_action(self) -> float | None:
        return self.decision.battery_action

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
        if not 0 <= self.energy.battery_soc_start <= 100:
            errors.append(f"Invalid start SOC: {self.energy.battery_soc_start}%")
        if not 0 <= self.energy.battery_soc_end <= 100:
            errors.append(f"Invalid end SOC: {self.energy.battery_soc_end}%")

        return errors


@dataclass
class OptimizationResult:
    """Result structure returned by optimize_battery_schedule."""

    input_data: dict
    hourly_data: list[HourlyData]
    economic_summary: EconomicSummary
