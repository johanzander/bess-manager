"""Experimental read-only Huawei Solar inverter controller."""

from __future__ import annotations

import logging

from .dp_schedule import DPSchedule
from .health_check import perform_health_check
from .inverter_controller import InverterController
from .settings import BatterySettings

logger = logging.getLogger(__name__)


class HuaweiSolarController(InverterController):
    """Read-only Huawei Solar controller.

    This controller intentionally never writes to Home Assistant entities or
    calls Huawei services. It only accepts schedules/intents so the runtime can
    continue to monitor an experimental Huawei installation safely.
    """

    def __init__(self, battery_settings: BatterySettings) -> None:
        super().__init__(battery_settings)
        self._active_tou_intervals: list[dict] = []

    @property
    def active_tou_intervals(self) -> list[dict]:
        return list(self._active_tou_intervals)

    def create_schedule(
        self,
        schedule: DPSchedule,
        current_period: int = 0,
        previous_tou_intervals: list[dict] | None = None,
    ) -> None:
        self.current_schedule = schedule
        self.strategic_intents = list(getattr(schedule, "strategic_intents", []) or [])
        self.tou_intervals = []
        self._active_tou_intervals = []
        logger.info("Huawei Solar: accepted schedule intents in read-only mode")

    def write_schedule_to_hardware(
        self,
        controller,
        effective_period: int,
        current_tou: list,
    ) -> tuple[int, int]:
        logger.info("Huawei Solar: write_schedule_to_hardware is a read-only no-op")
        return 0, 0

    def _write_period_to_hardware(
        self, controller, grid_charge: bool, discharge_rate: int
    ) -> tuple[bool, str]:
        logger.info("Huawei Solar: per-period hardware write is a read-only no-op")
        return True, ""

    def sync_soc_limits(self, controller) -> None:
        logger.info("Huawei Solar: SOC limit synchronization is disabled (read-only)")

    def read_and_initialize_from_hardware(self, controller, current_hour: int) -> None:
        logger.warning(
            "Huawei Solar support is experimental and read-only; no schedules, "
            "SOC limits, or entities will be written."
        )

    def compare_schedules(
        self, other_schedule: InverterController, from_period: int = 0
    ) -> tuple[bool, str]:
        other_intents = getattr(other_schedule, "strategic_intents", [])
        if self.strategic_intents[from_period:] != other_intents[from_period:]:
            return True, "strategic intents differ"
        return False, "read-only schedules equivalent"

    def get_all_tou_segments(self) -> list[dict]:
        return []

    def get_daily_TOU_settings(self) -> list[dict]:
        return []

    def log_current_TOU_schedule(self, header: str = "") -> None:
        logger.info("%sHuawei Solar read-only mode: no TOU schedule", header)

    def log_detailed_schedule(self, header: str = "") -> None:
        logger.info(
            "%sHuawei Solar read-only mode: no detailed hardware schedule", header
        )

    def check_health(self, controller) -> list:
        checks = [
            perform_health_check(
                component_name="Huawei Solar Monitoring",
                description="Experimental read-only Huawei Solar monitoring sensors",
                is_required=True,
                controller=controller,
                all_methods=[
                    "get_battery_soc",
                    "get_battery_charge_power",
                    "get_battery_discharge_power",
                    "get_import_power",
                    "get_export_power",
                    "get_pv_power",
                    "get_local_load_power",
                ],
            )
        ]
        checks.append(
            {
                "name": "Huawei Solar Battery Control",
                "description": "Active battery control is not implemented for Huawei Solar",
                "required": False,
                "status": "WARNING",
                "checks": [
                    {
                        "name": "Read-only controller",
                        "key": None,
                        "method_name": None,
                        "entity_id": None,
                        "status": "SKIPPED",
                        "rawValue": None,
                        "displayValue": "Disabled",
                        "error": "Huawei Solar is monitoring-only; no HA writes are performed.",
                    }
                ],
            }
        )
        return checks
