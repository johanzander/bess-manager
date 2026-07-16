"""Tests for SolaxModbusGrowattController control_mode="vpp".

Verifies the VPP remote-power-control path (issue #118):
- No TOU segment writes — remote_control/power/time entities only
- VPP Status/AC-charging enabled once, not every period
- Intent -> power mapping mirrors SolaxController
- Fallback timer state survives controller re-instantiation via read-back
- health check gates on VPP entities, not TOU entities
"""

from datetime import datetime
from unittest.mock import patch

import pytest  # type: ignore

from core.bess.dp_schedule import DPSchedule
from core.bess.settings import BatterySettings
from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController
from core.bess.tests.conftest import MockHomeAssistantController


def hourly_to_quarterly(
    hourly_intents: dict[int, str], default: str = "IDLE"
) -> list[str]:
    quarterly = [default] * 96
    for hour, intent in hourly_intents.items():
        for period in range(hour * 4, (hour + 1) * 4):
            quarterly[period] = intent
    return quarterly


def make_schedule(intents: list[str]) -> DPSchedule:
    return DPSchedule(
        actions=[0.0] * len(intents),
        state_of_energy=[25.0] * (len(intents) + 1),
        prices=[0.1] * len(intents),
        original_dp_results={"strategic_intent": intents},
    )


@pytest.fixture
def battery_settings():
    return BatterySettings(
        total_capacity=50.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        min_soc=10.0,
        max_soc=95.0,
        cycle_cost_per_kwh=0.05,
    )


@pytest.fixture
def controller(battery_settings):
    return SolaxModbusGrowattController(battery_settings, control_mode="vpp")


@pytest.fixture
def mock_ha():
    return MockHomeAssistantController()


def _apply_at_period(controller, mock_ha, period, grid_charge, discharge_rate):
    hour = period // 4
    minute = (period % 4) * 15
    with patch("core.bess.solax_modbus_growatt_controller.time.sleep"):
        with patch("core.bess.solax_modbus_growatt_controller.time_utils") as mock_time:
            mock_time.now.return_value = datetime(2026, 5, 20, hour, minute, 0)
            controller.apply_period(mock_ha, grid_charge, discharge_rate)


class TestControlModeValidation:
    def test_rejects_unknown_control_mode(self, battery_settings):
        with pytest.raises(ValueError):
            SolaxModbusGrowattController(battery_settings, control_mode="bogus")

    def test_defaults_to_tou(self, battery_settings):
        controller = SolaxModbusGrowattController(battery_settings)
        assert controller.control_mode == "tou"


class TestIntentToVpp:
    def test_grid_charge_maps_to_full_charge_power(self, controller):
        power_pct, enabled = controller._intent_to_vpp(
            grid_charge=True, discharge_rate=0
        )
        assert power_pct == 100
        assert enabled is True

    def test_idle_disables_remote_control(self, controller):
        power_pct, enabled = controller._intent_to_vpp(
            grid_charge=False, discharge_rate=0
        )
        assert power_pct == 0
        assert enabled is False

    def test_discharge_rate_maps_to_negative_power(self, controller):
        power_pct, enabled = controller._intent_to_vpp(
            grid_charge=False, discharge_rate=60
        )
        assert power_pct == -60
        assert enabled is True


class TestApplyPeriodVpp:
    def test_no_tou_segments_written(self, controller, mock_ha):
        intents = hourly_to_quarterly({2: "GRID_CHARGING"})
        controller.create_schedule(make_schedule(intents), current_period=0)

        _apply_at_period(controller, mock_ha, 8, grid_charge=True, discharge_rate=0)

        assert mock_ha.calls["tou_segments"] == []
        assert mock_ha.calls["grid_charge"] == []
        assert mock_ha.calls["discharge_rate"] == []

    def test_vpp_status_enabled_once(self, controller, mock_ha):
        """VPP Status/AC-charging are written once, not on every period."""
        intents = hourly_to_quarterly({2: "GRID_CHARGING", 4: "GRID_CHARGING"})
        controller.create_schedule(make_schedule(intents), current_period=0)

        _apply_at_period(controller, mock_ha, 8, grid_charge=True, discharge_rate=0)
        _apply_at_period(controller, mock_ha, 9, grid_charge=True, discharge_rate=0)

        assert len(mock_ha.calls["growatt_vpp_status"]) == 1
        assert len(mock_ha.calls["growatt_vpp_allow_ac_charging"]) == 1

    def test_charge_period_writes_positive_power(self, controller, mock_ha):
        intents = hourly_to_quarterly({2: "GRID_CHARGING"})
        controller.create_schedule(make_schedule(intents), current_period=0)

        _apply_at_period(controller, mock_ha, 8, grid_charge=True, discharge_rate=0)

        period = mock_ha.calls["growatt_vpp_periods"][-1]
        assert period["remote_control_enabled"] is True
        assert period["power_pct"] == 100
        assert period["fallback_minutes"] == 20

    def test_discharge_period_writes_negative_power(self, controller, mock_ha):
        intents = hourly_to_quarterly({10: "BATTERY_EXPORT"})
        controller.create_schedule(make_schedule(intents), current_period=0)

        _apply_at_period(controller, mock_ha, 40, grid_charge=False, discharge_rate=70)

        period = mock_ha.calls["growatt_vpp_periods"][-1]
        assert period["remote_control_enabled"] is True
        assert period["power_pct"] == -70

    def test_idle_disables_remote_control_on_hardware(self, controller, mock_ha):
        intents = hourly_to_quarterly({0: "IDLE"})
        controller.create_schedule(make_schedule(intents), current_period=0)
        controller._last_written_vpp_remote_control = True  # force a change

        _apply_at_period(controller, mock_ha, 0, grid_charge=False, discharge_rate=0)

        period = mock_ha.calls["growatt_vpp_periods"][-1]
        assert period["remote_control_enabled"] is False

    def test_unchanged_command_skips_write(self, controller, mock_ha):
        intents = hourly_to_quarterly({2: "GRID_CHARGING"})
        controller.create_schedule(make_schedule(intents), current_period=0)

        _apply_at_period(controller, mock_ha, 8, grid_charge=True, discharge_rate=0)
        writes_after_first = len(mock_ha.calls["growatt_vpp_periods"])

        # Same command again — should not write again
        _apply_at_period(controller, mock_ha, 9, grid_charge=True, discharge_rate=0)
        assert len(mock_ha.calls["growatt_vpp_periods"]) == writes_after_first

    def test_power_change_within_active_control_triggers_write(
        self, controller, mock_ha
    ):
        intents = hourly_to_quarterly({0: "BATTERY_EXPORT"})
        controller.create_schedule(make_schedule(intents), current_period=0)

        _apply_at_period(controller, mock_ha, 0, grid_charge=False, discharge_rate=50)
        _apply_at_period(controller, mock_ha, 1, grid_charge=False, discharge_rate=80)

        assert len(mock_ha.calls["growatt_vpp_periods"]) == 2
        assert mock_ha.calls["growatt_vpp_periods"][-1]["power_pct"] == -80


class TestWriteScheduleToHardwareVpp:
    def test_writes_initial_command_only(self, controller, mock_ha):
        intents = hourly_to_quarterly({2: "GRID_CHARGING"})
        controller.create_schedule(make_schedule(intents), current_period=0)

        writes, disables = controller.write_schedule_to_hardware(
            mock_ha, effective_period=8, current_tou=[]
        )

        assert writes == 1
        assert disables == 0
        assert mock_ha.calls["tou_segments"] == []
        assert len(mock_ha.calls["growatt_vpp_periods"]) == 1


class TestReadAndInitializeVpp:
    def test_seeds_state_from_hardware(self, controller, mock_ha):
        mock_ha._growatt_vpp_status_state = "Enabled"
        mock_ha._growatt_vpp_remote_control_state = "Enabled"

        controller.read_and_initialize_from_hardware(mock_ha, current_hour=10)

        assert controller._vpp_status_confirmed is True
        assert controller._last_written_vpp_remote_control is True

    def test_seeds_disabled_state(self, controller, mock_ha):
        mock_ha._growatt_vpp_status_state = "Disabled"
        mock_ha._growatt_vpp_remote_control_state = "Disabled"

        controller.read_and_initialize_from_hardware(mock_ha, current_hour=10)

        assert controller._vpp_status_confirmed is False
        assert controller._last_written_vpp_remote_control is False

    def test_no_hardware_writes_on_read(self, controller, mock_ha):
        controller.read_and_initialize_from_hardware(mock_ha, current_hour=10)

        assert mock_ha.calls["growatt_vpp_status"] == []
        assert mock_ha.calls["growatt_vpp_periods"] == []


class TestCheckHealthVpp:
    def test_checks_vpp_entities_not_tou_entities(self, controller, mock_ha):
        mock_ha.sensors.update(
            {
                "growatt_vpp_status": "select.growatt_vpp_status",
                "growatt_vpp_remote_control": "select.growatt_vpp_remote_control",
                "growatt_vpp_allow_ac_charging": "select.growatt_vpp_allow_ac_charging",
                "growatt_vpp_time": "number.growatt_vpp_time",
                "growatt_vpp_power": "number.growatt_vpp_power",
            }
        )

        [health] = controller.check_health(mock_ha)

        checked_keys = {c["key"] for c in health["checks"]}
        assert "growatt_vpp_status" in checked_keys
        assert "growatt_vpp_power" in checked_keys
        assert "tou_time_1_enabled" not in checked_keys

    def test_missing_vpp_entity_is_error(self, controller, mock_ha):
        [health] = controller.check_health(mock_ha)
        assert health["status"] == "ERROR"


class TestVppInitDoesNotTouchTou:
    def test_initialize_hardware_writes_no_tou_segments(self, controller, mock_ha):
        """VPP mode must never read or write TOU entities (#309, #302)."""
        mock_ha.read_tou_segments_from_entities = lambda: [
            {
                "segment_id": 1,
                "batt_mode": "battery_first",
                "start_time": "00:00",
                "end_time": "23:59",
                "enabled": True,
            }
        ]

        controller.initialize_hardware(mock_ha)

        assert mock_ha.calls["tou_segments"] == []
