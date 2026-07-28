"""Huawei EMMA/SUN2000 controller using the integration's native TOU service."""

from datetime import datetime
from typing import ClassVar

from .ha_api_controller import HomeAssistantAPIController
from .huawei_controller import HuaweiController
from .settings import BatterySettings


class HuaweiEmmaController(HuaweiController):
    """Control SUN2000 through Huawei EMMA Management's native period list."""

    supports_charge_rate_control: ClassVar[bool] = False

    def __init__(self, battery_settings: BatterySettings) -> None:
        super().__init__(battery_settings)

    def write_to_hardware(
        self,
        controller: HomeAssistantAPIController,
        effective_period: int,
        current_tou: list,
    ) -> tuple[int, int]:
        periods = [
            {
                "start_time": period["start_time"],
                "end_time": period["end_time"],
                "action": "charge" if period["flag"] == "+" else "discharge",
                "days": [True] * 7,
            }
            for period in self._periods
        ]
        controller.set_grid_charge(any(p["action"] == "charge" for p in periods))
        controller.write_huawei_emma_tou_periods(periods)
        return 2, 0

    def read_and_initialize_from_hardware(
        self, controller: HomeAssistantAPIController, current_hour: int
    ) -> None:
        periods = controller.read_huawei_emma_tou_periods()
        self._periods = [
            {
                "start_time": period["start_time"],
                "end_time": period["end_time"],
                "flag": "+" if period["action"] == "charge" else "-",
            }
            for period in periods
        ]
        self.tou_intervals = [
            {
                "start_time": period["start_time"],
                "end_time": period["end_time"],
                "batt_mode": (
                    "battery_first" if period["action"] == "charge" else "grid_first"
                ),
                "enabled": True,
                "is_default": False,
                "segment_id": index,
            }
            for index, period in enumerate(periods, 1)
        ]

    def sync_soc_limits(self, controller: HomeAssistantAPIController) -> None:
        configured_max_soc = int(self.battery_settings.max_soc)
        configured_min_soc = int(self.battery_settings.min_soc)

        if controller.get_charge_stop_soc() != configured_max_soc:
            controller.set_charge_stop_soc(configured_max_soc)
        if controller.get_discharge_stop_soc() != configured_min_soc:
            controller.set_discharge_stop_soc(configured_min_soc)

    def initialize_hardware(self, controller: HomeAssistantAPIController) -> None:
        self.sync_soc_limits(controller)
        controller.set_huawei_maximum_charging_power(
            round(self.battery_settings.max_charge_power_kw * 1000)
        )
        controller.set_huawei_maximum_discharging_power(
            round(self.battery_settings.max_discharge_power_kw * 1000)
        )

    def check_health(self, controller: HomeAssistantAPIController) -> list[dict]:
        try:
            controller.read_huawei_emma_tou_periods()
            status = "OK"
            message = "Native EMMA TOU schedule is readable"
        except Exception as error:
            status = "ERROR"
            message = f"Native EMMA TOU read failed: {error}"
        return [
            {
                "name": "Battery Control (Huawei EMMA / SUN2000)",
                "description": (
                    "Controls the native Huawei EMMA time-of-use period list"
                ),
                "required": True,
                "status": status,
                "checks": [
                    {
                        "component": "Huawei EMMA native TOU",
                        "status": status,
                        "message": message,
                    }
                ],
                "last_run": datetime.now().isoformat(),
            }
        ]
