"""
Data models for the BESS system.

This module contains dataclasses representing various data structures used throughout
the BESS system, providing type safety and clear interfaces between components.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Import our other data models
from .dp_battery_algorithm import HourlyData


@dataclass
class EnergyFlow:
    """
    Raw energy flow data collected from sensors.
    
    This is a focused dataclass containing only the core energy flow measurements
    without additional metadata, strategic intents, or economic calculations.
    It represents the raw data collected from sensors and is used by components
    like SensorCollector and EnergyFlowCalculator.
    """
    # Core energy flows (kWh)
    battery_charged: float = 0.0
    battery_discharged: float = 0.0
    system_production: float = 0.0  # Solar production
    load_consumption: float = 0.0   # Home consumption
    export_to_grid: float = 0.0
    import_from_grid: float = 0.0
    
    # Additional energy flow details
    grid_to_battery: float = 0.0
    solar_to_battery: float = 0.0
    self_consumption: float = 0.0
    
    # Other energy-related data points 
    battery_soc: float = 0.0  # % (0-100)
    battery_soe: float = 0.0  # kWh
    
    # Optional metadata - only used at collection time
    # Using Optional for Python 3.8/3.9 compatibility
    hour: int | None = None
    timestamp: datetime | None = None
    strategic_intent: str = "IDLE"  # Strategic intent determined from flows
    
    @property
    def solar_generated(self) -> float:
        """Alias for system_production for compatibility with HourlyData."""
        return self.system_production
    
    @property
    def home_consumed(self) -> float:
        """Alias for load_consumption for compatibility with HourlyData."""
        return self.load_consumption
    
    @property
    def grid_imported(self) -> float:
        """Alias for import_from_grid for compatibility with HourlyData."""
        return self.import_from_grid
    
    @property
    def grid_exported(self) -> float:
        """Alias for export_to_grid for compatibility with HourlyData."""
        return self.export_to_grid
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnergyFlow":
        """Create an EnergyFlow instance from a dictionary."""
        return cls(
            battery_charged=data.get("battery_charged", 0.0),
            battery_discharged=data.get("battery_discharged", 0.0),
            system_production=data.get("system_production", 0.0),
            load_consumption=data.get("load_consumption", 0.0),
            export_to_grid=data.get("export_to_grid", 0.0),
            import_from_grid=data.get("import_from_grid", 0.0),
            grid_to_battery=data.get("grid_to_battery", 0.0),
            solar_to_battery=data.get("solar_to_battery", 0.0),
            self_consumption=data.get("self_consumption", 0.0),
            battery_soc=data.get("battery_soc", 0.0),
            battery_soe=data.get("battery_soe", 0.0),
            hour=data.get("hour"),
            timestamp=data.get("timestamp"),
            strategic_intent=data.get("strategic_intent", "IDLE"),
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for compatibility with legacy code."""
        return {
            "battery_charged": self.battery_charged,
            "battery_discharged": self.battery_discharged,
            "system_production": self.system_production,
            "load_consumption": self.load_consumption,
            "export_to_grid": self.export_to_grid,
            "import_from_grid": self.import_from_grid,
            "grid_to_battery": self.grid_to_battery,
            "solar_to_battery": self.solar_to_battery,
            "self_consumption": self.self_consumption,
            "battery_soc": self.battery_soc,
            "battery_soe": self.battery_soe,
            "strategic_intent": self.strategic_intent,
        }


# HourlyData and OptimizationResult are already imported at top of file


def create_hourly_data_from_energy_flow(
    flow: EnergyFlow,
    battery_soc_start: float,
    buy_price: float = 1.0,
    sell_price: float = 0.6,
) -> HourlyData:
    """
    Convert an EnergyFlow to a complete HourlyData object.
    
    Args:
        flow: The energy flow data
        battery_soc_start: Starting battery SOC percentage
        buy_price: Price for buying from grid
        sell_price: Price for selling to grid
        
    Returns:
        HourlyData object with all relevant fields populated
    """
    return HourlyData(
        hour=flow.hour if flow.hour is not None else 0,
        data_source="actual",
        timestamp=flow.timestamp or datetime.now(),
        solar_generated=flow.system_production,
        home_consumed=flow.load_consumption,
        grid_imported=flow.import_from_grid,
        grid_exported=flow.export_to_grid,
        battery_charged=flow.battery_charged,
        battery_discharged=flow.battery_discharged,
        battery_soc_start=battery_soc_start,
        battery_soc_end=flow.battery_soc,
        buy_price=buy_price,
        sell_price=sell_price,
        strategic_intent=flow.strategic_intent,
        # Add derived flows if available
        solar_to_home=getattr(flow, "solar_to_home", min(flow.system_production, flow.load_consumption)),
        solar_to_battery=flow.solar_to_battery,
        solar_to_grid=getattr(flow, "solar_to_grid", max(0, flow.system_production - flow.self_consumption - flow.solar_to_battery)),
        grid_to_home=getattr(flow, "grid_to_home", max(0, flow.load_consumption - min(flow.system_production, flow.load_consumption) - flow.battery_discharged)),
        grid_to_battery=flow.grid_to_battery,
        battery_to_home=getattr(flow, "battery_to_home", min(flow.battery_discharged, max(0, flow.load_consumption - min(flow.system_production, flow.load_consumption)))),
        battery_to_grid=getattr(flow, "battery_to_grid", max(0, flow.battery_discharged - min(flow.battery_discharged, max(0, flow.load_consumption - min(flow.system_production, flow.load_consumption))))),
    )
