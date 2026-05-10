"""Growatt MIN inverter controller using solax_modbus entity-based TOU writes.

This controller supports Growatt MIN inverters connected via the solax_modbus
HACS integration (local Modbus) instead of the growatt_server cloud integration.

The scheduling algorithm (9 TOU slots, differential updates, corruption recovery)
is identical to GrowattMinController. Only the hardware I/O differs:

- growatt_server: single service call ``growatt_server.update_time_segment``
- solax_modbus: 4 entity writes (``select.select_option`` x4) + 1 button press per slot

Per-period control (``set_grid_charge``, ``set_discharging_power_rate``) already uses
generic HA service calls that resolve entity IDs from sensor config, so no override
is needed for those.
"""

import logging

from .growatt_min_controller import GrowattMinController
from .settings import BatterySettings

logger = logging.getLogger(__name__)


class GrowattSolaxModbusController(GrowattMinController):
    """Growatt MIN controller using solax_modbus entity-based TOU writes."""

    def __init__(self, battery_settings: BatterySettings) -> None:
        """Initialize the Growatt solax_modbus controller."""
        super().__init__(battery_settings)

    def _send_segment_to_hardware(self, controller, segment: dict) -> None:
        """Write a single TOU segment via solax_modbus entity writes.

        Instead of the growatt_server service call, this writes 4 select entities
        (enabled, begin, end, mode) and presses the update button for the slot.
        """
        controller.set_tou_segment_via_entities(
            segment_id=segment["segment_id"],
            batt_mode=segment["batt_mode"],
            start_time=segment["start_time"],
            end_time=segment["end_time"],
            enabled=segment["enabled"],
        )

    def _read_segments_from_hardware(self, controller) -> list[dict]:
        """Read current TOU segments from solax_modbus entity states.

        Reads the state of all 9 TOU slot entities and returns the same
        format as read_inverter_time_segments().
        """
        return controller.read_tou_segments_from_entities()
