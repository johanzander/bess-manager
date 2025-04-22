"""Battery Energy Storage System (BESS) management package."""

# Define public API - only include what users should directly access
__all__ = [
    "BatterySystemManager",  # Main facade
    "HomeAssistantAPIController",  # Used by pyscript integrations
    "BatterySettings",  # Public settings classes
    "HomeSettings",
    "ConsumptionSettings",
    "PriceSettings",
]

# Import settings used by other modules
from .settings import (  # noqa: I001
    BatterySettings,
    ConsumptionSettings,
    HomeSettings,
    PriceSettings,
)

# Import controller for Home Assistant integration
# from .ha_controller import HomeAssistantController
from .ha_api_controller import HomeAssistantAPIController

# Import main facade class (the primary entry point to the system)
from .battery_system import BatterySystemManager
