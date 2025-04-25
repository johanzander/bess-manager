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
from .settings import (
    BATTERY_MAX_CHARGE_DISCHARGE_POWER_KW,
    BatterySettings,
    HomeSettings,
)

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
        self.max_charge_power_kw = BATTERY_MAX_CHARGE_DISCHARGE_POWER_KW * 1000

        log_message = (
            "Initialized HomePowerMonitor with:\n"
            "  Max power per phase: {}W\n"
            "  Max charging power: {}W\n"
            "  Max battery charging rate: {}%\n"
            "  Step size: {}%"
        )
        logger.info(
            log_message.format(
                self.max_power_per_phase,
                self.max_charge_power_kw,
                self.battery_settings.charging_power_rate,
                self.step_size,
            )
        )

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
        """Calculate safe battery charging power based on most loaded phase."""
        # Get current loads in watts
        l1, l2, l3 = self.get_current_phase_loads_w()

        # Calculate current usage as percentage of max safe current
        l1_pct = (l1 / self.max_power_per_phase) * 100
        l2_pct = (l2 / self.max_power_per_phase) * 100
        l3_pct = (l3 / self.max_power_per_phase) * 100

        # Find most loaded phase
        max_load_pct = max(l1_pct, l2_pct, l3_pct)

        # Available capacity is what's left from 100%
        available_pct = 100 - max_load_pct

        # Convert to charging power percentage (limit by configured max)
        charging_power_pct = min(
            available_pct, float(self.battery_settings.charging_power_rate)
        )

        log_message = (
            "Phase loads: #1: %.0fW (%.1f%%), "
            "#2: %.0fW (%.1f%%), "
            "#3: %.0fW (%.1f%%)\n"
            "Most loaded phase: %.1f%%\n"
            "Available capacity: %.1f%%\n"
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
            available_pct,
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
                "Adjusting charging power from {}% to {:.0f}% (target: {:.0f}%)".join(
                    map(str, (current_power, new_power, target_power))
                )
            )
            self.controller.set_charging_power_rate(int(new_power))
