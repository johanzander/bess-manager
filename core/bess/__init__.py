"""Battery Energy Storage System (BESS) management package."""

# Define public API - only include what users should directly access
__all__ = [
    "BatterySettings",  # Public settings classes
    "BatterySystemManager",  # Main facade
    "HistoricalDataStore",
    "HomeAssistantAPIController",
    "HomeSettings",
    "HourlyEvent",
    "PriceSettings",
]

# Import settings used by other modules
from .settings import (  # noqa: I001
    BatterySettings,
    HomeSettings,
    PriceSettings,
)

# Import controller for Home Assistant integration
# from .ha_controller import HomeAssistantController
from .ha_api_controller import HomeAssistantAPIController

# Import main facade class (the primary entry point to the system)
from .battery_system_manager import BatterySystemManager
