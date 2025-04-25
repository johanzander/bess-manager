# battery_monitor.py

"""Simple monitoring of battery system states."""

import logging

from .growatt_schedule import GrowattScheduleManager
from .ha_api_controller import HomeAssistantAPIController
from .settings import BatterySettings, HomeSettings

logger = logging.getLogger(__name__)


class BatteryMonitor:
    """Monitors battery system state consistency."""

    def __init__(
        self,
        ha_controller: HomeAssistantAPIController,
        schedule_manager: GrowattScheduleManager,
        home_settings: HomeSettings | None = None,
        battery_settings: BatterySettings | None = None,
    ) -> None:
        """Initialize the monitor.

        Args:
            ha_controller: Home Assistant controller instance
            schedule_manager: Schedule manager instance
            home_settings: Optional home electrical settings
            battery_settings: Optional battery settings

        """
        self.controller = ha_controller
        self.schedule_manager = schedule_manager
        self.home_settings = home_settings or HomeSettings()
        self.battery_settings = battery_settings or BatterySettings()

        # Configuration
        self.MIN_CHARGING_POWER = 500  # Watts, minimum to consider actually charging
        self.MAX_SOC = self.battery_settings.max_soc

    def check_system_state(self, current_hour: int) -> None:
        """Check if system states are consistent and correct any issues."""

        # Get current settings
        hourly_settings = self.schedule_manager.get_hourly_settings(current_hour)
        grid_charge_enabled = hourly_settings["grid_charge"]

        # Get current states
        soc = self.controller.get_battery_soc()
        charge_power = self.controller.get_battery_charge_power()
        discharge_power = self.controller.get_battery_discharge_power()
        grid_charge_state = self.controller.grid_charge_enabled()

        # Log current state for monitoring
        logger.info(
            "\nBattery State:\n"
            "  SOC:                 %d%%\n"
            "  Charge Power:        %.1f W\n"
            "  Discharge Power:     %.1f W\n"
            "  Grid Charge Enabled: %s\n"
            "  Grid Charge State:   %s\n",
            soc,
            charge_power,
            discharge_power,
            grid_charge_enabled,
            grid_charge_state,
        )

        # Check if settings match states and correct if needed
        if grid_charge_enabled != grid_charge_state:
            logger.warning(
                "Grid charge state mismatch - Setting: %s, Actual State: %s",
                grid_charge_enabled,
                grid_charge_state,
            )
            # Correct the mismatch by setting the inverter to match the expected state
            self.controller.set_grid_charge(grid_charge_enabled)
            logger.info("Corrected grid charge state to: %s", grid_charge_enabled)

        # Check charging behavior
        should_be_charging = grid_charge_enabled and soc < self.MAX_SOC

        if should_be_charging and charge_power < self.MIN_CHARGING_POWER:
            logger.warning(
                "Battery not charging when it should be - "
                "Grid Charge: %s, SOC: %d%%, Charge Power: %.1f W",
                grid_charge_enabled,
                soc,
                charge_power,
            )
