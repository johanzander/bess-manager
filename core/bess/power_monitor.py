"""Monitors home power usage and adapts battery charging power to prevent overloading of fuses.

It does this by:

1. Power Monitoring:
   - Continuously monitors current draw on all three phases
   - Calculates total power consumption per phase
   - Considers house fuse limits (e.g., 25A per phase)
   - Maintains a safety margin to prevent tripping fuses

2. Battery Charge Management:
   - Adjusts battery charging power based on available power
   - Ensures total power draw (including battery) stays within fuse limits
   - Makes gradual adjustments (e.g., 5% steps) to prevent sudden load changes
   - Respects maximum charging rate configuration
   - Only activates when grid charging is enabled

This module is designed to work with the Home Assistant controller and to be run periodically (e.g from pyscript)

"""

import logging

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
        step_size: int = 5,
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
        self.step_size = step_size

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
            "  Target charging rate: {}%\n"
            "  Step size: {}%"
        )
        logger.info(
            log_message.format(
                self.max_power_per_phase,
                self.max_charge_power_w,
                self.target_charging_power_pct,
                self.step_size,
            )
        )

    def check_health(self) -> list:
        """Check the health of the Power Monitor component."""
        # Define what controller methods this component uses
        power_methods = [
            "get_l1_current",
            "get_l2_current",
            "get_l3_current",
            "get_charging_power_rate",
        ]

        # For power monitoring, since the component itself is optional, all methods are optional
        # System can operate without power monitoring - it's an enhancement feature
        required_power_methods = []

        health_check = perform_health_check(
            component_name="Power Monitoring",
            description="Monitors home power consumption and adapts battery charging",
            is_required=False,
            controller=self.controller,
            all_methods=power_methods,
            required_methods=required_power_methods,
        )

        return [health_check]

    def get_current_phase_loads_w(self) -> tuple[float, float, float]:
        """Get current load on each phase in watts."""
        l1_current = self.controller.get_l1_current()
        l2_current = self.controller.get_l2_current()
        l3_current = self.controller.get_l3_current()

        return (
            l1_current * self.home_settings.voltage,
            l2_current * self.home_settings.voltage,
            l3_current * self.home_settings.voltage,
        )

    def calculate_available_charging_power(self) -> float:
        """Calculate safe battery charging power based on most loaded phase and target power."""
        # Get current loads in watts
        l1, l2, l3 = self.get_current_phase_loads_w()

        # Calculate current usage as percentage of max safe current (for logging)
        l1_pct = (l1 / self.max_power_per_phase) * 100
        l2_pct = (l2 / self.max_power_per_phase) * 100
        l3_pct = (l3 / self.max_power_per_phase) * 100

        # Find most loaded phase in watts
        max_load_w = max(l1, l2, l3)
        max_load_pct = (max_load_w / self.max_power_per_phase) * 100

        # Calculate available power on most loaded phase
        available_power_w = self.max_power_per_phase - max_load_w

        # Max battery power per phase (assuming equal distribution across 3 phases)
        max_battery_power_per_phase_w = self.max_charge_power_w / 3

        # Calculate available charging power as percentage of battery's max power
        # This is the correct calculation: available power relative to what the battery needs
        if max_battery_power_per_phase_w > 0:
            available_pct = (available_power_w / max_battery_power_per_phase_w) * 100
        else:
            available_pct = 0

        # Limit by target charging power
        charging_power_pct = min(available_pct, self.target_charging_power_pct)

        log_message = (
            "Phase loads: #1: %.0fW (%.1f%%), "
            "#2: %.0fW (%.1f%%), "
            "#3: %.0fW (%.1f%%)\n"
            "Most loaded phase: %.1f%%\n"
            "Available power: %.0fW (%.1f%% of battery max per phase)\n"
            "Target charging: %.1f%%\n"
            "Recommended charging: %.1f%%"
        )
        logger.info(
            log_message,
            l1,
            l1_pct,
            l2,
            l2_pct,
            l3,
            l3_pct,
            max_load_pct,
            available_power_w,
            available_pct,
            self.target_charging_power_pct,
            charging_power_pct,
        )

        return max(0, charging_power_pct)

    def adjust_battery_charging(self) -> None:
        """Adjust battery charging power based on available capacity."""
        if not self.controller.grid_charge_enabled():
            return

        target_power = self.calculate_available_charging_power()
        current_power = self.controller.get_charging_power_rate()

        if target_power > current_power:
            new_power = min(current_power + self.step_size, target_power)
        else:
            new_power = max(current_power - self.step_size, target_power)

        if abs(new_power - current_power) >= self.step_size:
            logger.info(
                f"Adjusting charging power from {current_power:.0f}% to {new_power:.0f}% (target: {target_power:.0f}%)"
            )
            self.controller.set_charging_power_rate(int(new_power))

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
