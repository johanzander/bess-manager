"""
Data models for the BESS system.

This module contains dataclasses representing various data structures used throughout
the BESS system, providing type safety and clear interfaces between components.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class EnergyFlow:
    """
    Raw energy flow data collected from sensors with BOTH start and end SOC.
    All fields are required - no optional fields, no defaults.
    """
    # Core required fields
    hour: int
    timestamp: datetime
    
    # Energy flows (kWh) - all required from sensors
    battery_charged: float
    battery_discharged: float
    system_production: float
    load_consumption: float
    export_to_grid: float
    import_from_grid: float
    grid_to_battery: float
    solar_to_battery: float
    self_consumption: float
    
    # Battery SOC data - BOTH readings required from sensors
    battery_soc_start: float  # % (0-100) - START SOC from previous hour sensor
    battery_soc_end: float    # % (0-100) - END SOC from current hour sensor
    battery_soe_start: float  # kWh - calculated from SOC start
    battery_soe_end: float    # kWh - calculated from SOC end
    
    # Strategic intent
    strategic_intent: str
    
    # Backward compatibility properties
    @property
    def battery_soc(self) -> float:
        """Backward compatibility - returns end SOC."""
        return self.battery_soc_end
    
    @property
    def battery_soe(self) -> float:
        """Backward compatibility - returns end SOE."""
        return self.battery_soe_end
    
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
            hour=data.get("hour"),
            timestamp=data.get("timestamp"),
            battery_charged=data.get("battery_charged", 0.0),
            battery_discharged=data.get("battery_discharged", 0.0),
            system_production=data.get("system_production", 0.0),
            load_consumption=data.get("load_consumption", 0.0),
            export_to_grid=data.get("export_to_grid", 0.0),
            import_from_grid=data.get("import_from_grid", 0.0),
            grid_to_battery=data.get("grid_to_battery", 0.0),
            solar_to_battery=data.get("solar_to_battery", 0.0),
            self_consumption=data.get("self_consumption", 0.0),
            battery_soc_start=data.get("battery_soc_start", 0.0),
            battery_soc_end=data.get("battery_soc_end", 0.0),
            battery_soe_start=data.get("battery_soe_start", 0.0),
            battery_soe_end=data.get("battery_soe_end", 0.0),
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
