"""Monitors home power usage and adapts battery charging power to prevent overloading of fuses.

It does this by:

1. Power Monitoring:
   - Continuously monitors current draw on electrical phases (single or three-phase)
   - Calculates total power consumption per phase
   - Considers house fuse limits (e.g., 25A per phase)
   - Maintains a safety margin to prevent tripping fuses

2. Battery Charge Management:
   - Adjusts battery charging power based on available power
   - Ensures total power draw (including battery) stays within fuse limits
   - Respects maximum charging rate configuration
   - Only activates when grid charging is enabled

This module is designed to work with the Home Assistant controller and to be run periodically

"""

import logging
from datetime import datetime

from .ha_api_controller import HomeAssistantAPIController
from .health_check import perform_health_check
from .settings import BatterySettings, HomeSettings

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class HomePowerMonitor:
    """Monitors home power consumption and manages battery charging."""

    def __init__(
        self,
        ha_controller: HomeAssistantAPIController,
        home_settings: HomeSettings | None = None,
        battery_settings: BatterySettings | None = None,
    ) -> None:
        """Initialize power monitor.

        Args:
            ha_controller: Home Assistant controller instance
            home_settings: Home electrical settings (optional)
            battery_settings: Battery settings (optional)
            step_size: Size of power adjustments in percent (default: 5%)

        """
        self.controller = ha_controller
        self.home_settings = home_settings or HomeSettings()
        self.battery_settings = battery_settings or BatterySettings()

        # Calculate max power per phase with safety margin
        self.max_power_per_phase = (
            self.home_settings.voltage
            * self.home_settings.max_fuse_current
            * self.home_settings.safety_margin
        )

        # Max charging power in watts (convert from kW)
        self.max_charge_power_w = self.battery_settings.max_charge_power_kw * 1000

        # Target charging power percentage - initialized from battery settings
        # This can be modified by external components like growatt_schedule
        # to reflect the actual charging power needed for strategic intents
        self.target_charging_power_pct = self.battery_settings.charging_power_rate

        log_message = (
            "Initialized HomePowerMonitor with:\n"
            "  Max power per phase: {}W\n"
            "  Max charging power: {}W\n"
            "  Target charging rate: {}%"
        )
        logger.info(
            log_message.format(
                self.max_power_per_phase,
                self.max_charge_power_w,
                self.target_charging_power_pct,
            )
        )

    def check_health(self) -> list:
        """Check the health of the Power Monitor component."""
        if not self.home_settings.power_monitoring_enabled:
            return [
                {
                    "name": "Power Monitoring",
                    "description": "Monitors home power consumption and adapts battery charging",
                    "required": False,
                    "status": "WARNING",
                    "checks": [
                        {
                            "component": "Power Monitoring",
                            "status": "WARNING",
                            "message": "Disabled — set power_monitoring_enabled: true in config to enable",
                        }
                    ],
                    "last_run": datetime.now().isoformat(),
                }
            ]

        if self.home_settings.phase_count == 1:
            all_methods = ["get_l1_current", "get_charging_power_rate"]
        else:
            all_methods = [
                "get_l1_current",
                "get_l2_current",
                "get_l3_current",
                "get_charging_power_rate",
            ]

        health_check = perform_health_check(
            component_name="Power Monitoring",
            description="Monitors home power consumption and adapts battery charging",
            is_required=False,
            controller=self.controller,
            all_methods=all_methods,
            required_methods=all_methods,
        )

        return [health_check]

    def get_current_phase_loads_w(self) -> tuple[float, ...]:
        """Get current load on each phase in watts.

        Returns a tuple with one element per phase (1 for single-phase, 3 for three-phase).
        """
        voltage = self.home_settings.voltage

        if self.home_settings.phase_count == 1:
            l1_current = self.controller.get_l1_current()
            return (l1_current * voltage,)

        l1_current = self.controller.get_l1_current()
        l2_current = self.controller.get_l2_current()
        l3_current = self.controller.get_l3_current()

        return (
            l1_current * voltage,
            l2_current * voltage,
            l3_current * voltage,
        )

    def calculate_available_charging_power(self) -> float:
        """Calculate safe battery charging power based on most loaded phase and target power."""
        phase_count = self.home_settings.phase_count

        # Get current loads in watts (variable-length tuple matching phase count)
        phase_loads = self.get_current_phase_loads_w()

        # Find most loaded phase in watts
        max_load_w = max(phase_loads)
        max_load_pct = (max_load_w / self.max_power_per_phase) * 100

        # Calculate available power on most loaded phase
        available_power_w = self.max_power_per_phase - max_load_w

        # Max battery power per phase (distributed across phases)
        max_battery_power_per_phase_w = self.max_charge_power_w / phase_count

        # Calculate available charging power as percentage of battery's max power
        # This is the correct calculation: available power relative to what the battery needs
        if max_battery_power_per_phase_w > 0:
            available_pct = (available_power_w / max_battery_power_per_phase_w) * 100
        else:
            available_pct = 0

        # Limit by target charging power
        charging_power_pct = min(available_pct, self.target_charging_power_pct)

        # Log phase loads
        if phase_count == 1:
            pct = (phase_loads[0] / self.max_power_per_phase) * 100
            phase_log = f"Phase load: {phase_loads[0]:.0f}W ({pct:.1f}%)"
        else:
            phase_parts = []
            for i, load in enumerate(phase_loads):
                pct = (load / self.max_power_per_phase) * 100
                phase_parts.append(f"#{i + 1}: {load:.0f}W ({pct:.1f}%)")
            phase_log = "Phase loads: " + ", ".join(phase_parts)

        log_message = (
            "%s\n"
            "Most loaded phase: %.1f%%\n"
            "Available power: %.0fW (%.1f%% of battery max per phase)\n"
            "Target charging: %.1f%%\n"
            "Recommended charging: %.1f%%"
        )
        logger.info(
            log_message,
            phase_log,
            max_load_pct,
            available_power_w,
            available_pct,
            self.target_charging_power_pct,
            charging_power_pct,
        )

        return max(0, charging_power_pct)

    def adjust_battery_charging(self) -> None:
        if not self.controller.grid_charge_enabled():
            return

        target_power = self.calculate_available_charging_power()
        current_power = self.controller.get_charging_power_rate()

        # Skip if no change needed (within 1% tolerance)
        if abs(target_power - current_power) < 1:
            return

        logger.info(
            f"Adjusting charging power from {current_power:.0f}% to {target_power:.0f}%"
        )
        self.controller.set_charging_power_rate(int(target_power))

    def update_target_charging_power(self, percentage: float) -> None:
        """Update the target charging power percentage.

        This method allows external components (like GrowattScheduleManager)
        to update the target charging power percentage based on strategic intents
        and optimization results.

        Args:
            percentage: Target charging power percentage (0-100)
        """
        if not 0 <= percentage <= 100:
            logger.warning(
                f"Invalid charging power percentage: {percentage}. Must be between 0-100."
            )
            percentage = min(100, max(0, percentage))

        # Only log when there's an actual change
        if (
            abs(self.target_charging_power_pct - percentage) > 0.01
        ):  # Use small tolerance for float comparison
            logger.info(
                f"Updating target charging power from {self.target_charging_power_pct:.1f}% to {percentage:.1f}%"
            )

        self.target_charging_power_pct = percentage
