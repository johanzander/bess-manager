"""Behavioral tests for the Huawei LUNA2000 inverter controller."""

from unittest.mock import MagicMock

import pytest

from core.bess.exceptions import SystemConfigurationError
from core.bess.huawei_controller import HuaweiController
from core.bess.settings import BatterySettings


def make_intents(hourly: dict[int, str], default: str = "IDLE") -> list[str]:
    quarterly = [default] * 96
    for hour, intent in hourly.items():
        for p in range(hour * 4, (hour + 1) * 4):
            quarterly[p] = intent
    return quarterly


def make_schedule_mock(intents: list[str]) -> MagicMock:
    schedule = MagicMock()
    schedule.original_dp_results = {"strategic_intent": intents}
    schedule.actions = [0.0] * len(intents)
    return schedule


@pytest.fixture
def battery_settings() -> BatterySettings:
    return BatterySettings(
        total_capacity=10.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        min_soc=15.0,
        max_soc=95.0,
    )


@pytest.fixture
def controller(battery_settings: BatterySettings) -> HuaweiController:
    return HuaweiController(battery_settings=battery_settings)


class TestScheduleBuilding:
    def test_charge_period_produces_plus_flag(
        self, controller: HuaweiController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule_mock(intents))
        assert len(controller._periods) == 1
        assert controller._periods[0]["flag"] == "+"
        assert controller._periods[0]["start_time"] == "02:00"
        assert controller._periods[0]["end_time"] == "02:59"

    def test_discharge_period_produces_minus_flag(
        self, controller: HuaweiController
    ) -> None:
        intents = make_intents({18: "BATTERY_EXPORT"})
        controller.apply_intents(make_schedule_mock(intents))
        assert controller._periods[0]["flag"] == "-"

    def test_idle_periods_produce_no_entry(self, controller: HuaweiController) -> None:
        intents = make_intents({})  # all IDLE
        controller.apply_intents(make_schedule_mock(intents))
        assert controller._periods == []

    def test_period_limit_enforced_at_14(self, controller: HuaweiController) -> None:
        # 20 separated single-quarter charge blocks (non-adjacent so they
        # don't merge), exceeding MAX_TOU_PERIODS=14.
        intents = ["IDLE"] * 96
        # Create 20 charge blocks separated by IDLE to exceed MAX_TOU_PERIODS
        for i in range(20):
            if i * 4 < 96:
                intents[i * 4] = "GRID_CHARGING"
        controller.apply_intents(make_schedule_mock(intents))
        assert len(controller._periods) <= HuaweiController.MAX_TOU_PERIODS


class TestWriteSchedule:
    def test_write_schedule_sets_working_mode_when_drifted(
        self, controller: HuaweiController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule_mock(intents))
        ha = MagicMock()
        ha.get_huawei_working_mode_options.return_value = [
            "maximise_self_consumption",
            "time_of_use_luna2000",
        ]
        ha.get_huawei_working_mode.return_value = "maximise_self_consumption"
        controller.write_to_hardware(ha, 0, [])
        ha.set_huawei_working_mode.assert_called_once_with("time_of_use_luna2000")

    def test_write_schedule_skips_mode_write_when_already_set(
        self, controller: HuaweiController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule_mock(intents))
        ha = MagicMock()
        ha.get_huawei_working_mode_options.return_value = []
        ha.get_huawei_working_mode.return_value = "time_of_use_luna2000"
        controller.write_to_hardware(ha, 0, [])
        ha.set_huawei_working_mode.assert_not_called()

    def test_write_schedule_calls_write_tou_periods_with_joined_text(
        self, controller: HuaweiController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING", 18: "LOAD_SUPPORT"})
        controller.apply_intents(make_schedule_mock(intents))
        ha = MagicMock()
        ha.get_huawei_working_mode_options.return_value = []
        ha.get_huawei_working_mode.return_value = "time_of_use_luna2000"
        controller.write_to_hardware(ha, 0, [])
        ha.write_huawei_tou_periods.assert_called_once()
        text = ha.write_huawei_tou_periods.call_args[0][0]
        assert "02:00-02:59/1234567/+" in text
        assert "18:00-18:59/1234567/-" in text

    def test_write_schedule_no_periods_writes_empty_string(
        self, controller: HuaweiController
    ) -> None:
        intents = make_intents({})
        controller.apply_intents(make_schedule_mock(intents))
        ha = MagicMock()
        ha.get_huawei_working_mode_options.return_value = []
        ha.get_huawei_working_mode.return_value = "time_of_use_luna2000"
        controller.write_to_hardware(ha, 0, [])
        ha.write_huawei_tou_periods.assert_called_once_with("")

    def test_write_schedule_raises_for_lg_resu_battery(
        self, controller: HuaweiController
    ) -> None:
        """LG RESU installs never expose 'time_of_use_luna2000' as an option
        (select.py removes it in StorageModeSelectEntity.__init__) —
        writing LUNA2000-format periods against one would be silently wrong."""
        intents = make_intents({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule_mock(intents))
        ha = MagicMock()
        ha.get_huawei_working_mode_options.return_value = [
            "adaptive",
            "fixed_charge_discharge",
            "maximise_self_consumption",
            "time_of_use_lg",
            "fully_fed_to_grid",
        ]
        with pytest.raises(SystemConfigurationError):
            controller.write_to_hardware(ha, 0, [])
        ha.write_huawei_tou_periods.assert_not_called()

    def test_write_schedule_proceeds_when_options_unavailable(
        self, controller: HuaweiController
    ) -> None:
        """An empty options list (entity unreadable) doesn't block the
        write — only a confirmed non-LUNA2000 option list does."""
        intents = make_intents({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule_mock(intents))
        ha = MagicMock()
        ha.get_huawei_working_mode_options.return_value = []
        ha.get_huawei_working_mode.return_value = "time_of_use_luna2000"
        controller.write_to_hardware(ha, 0, [])
        ha.write_huawei_tou_periods.assert_called_once()

    def test_write_schedule_enables_grid_charge_when_charge_period_present(
        self, controller: HuaweiController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule_mock(intents))
        ha = MagicMock()
        ha.get_huawei_working_mode_options.return_value = []
        ha.get_huawei_working_mode.return_value = "time_of_use_luna2000"
        controller.write_to_hardware(ha, 0, [])
        ha.set_grid_charge.assert_called_once_with(True)

    def test_write_schedule_disables_grid_charge_when_no_charge_period(
        self, controller: HuaweiController
    ) -> None:
        intents = make_intents({18: "LOAD_SUPPORT"})
        controller.apply_intents(make_schedule_mock(intents))
        ha = MagicMock()
        ha.get_huawei_working_mode_options.return_value = []
        ha.get_huawei_working_mode.return_value = "time_of_use_luna2000"
        controller.write_to_hardware(ha, 0, [])
        ha.set_grid_charge.assert_called_once_with(False)


class TestWorkingModeGateIsConditional:
    """Installs behind an energy manager (e.g. Huawei EMMA, PR #412) expose no
    LUNA2000 working-mode select. The gate must be skipped when the entity
    isn't mapped, rather than raising out of write_to_hardware — but skipping
    it also skips the LG-RESU family check, so it is logged, not silent."""

    def test_write_proceeds_when_working_mode_entity_unmapped(
        self, controller: HuaweiController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule_mock(intents))
        ha = MagicMock()
        ha.is_sensor_configured.return_value = False
        controller.write_to_hardware(ha, 0, [])
        ha.get_huawei_working_mode_options.assert_not_called()
        ha.get_huawei_working_mode.assert_not_called()
        ha.set_huawei_working_mode.assert_not_called()
        ha.write_huawei_tou_periods.assert_called_once()

    def test_family_check_skip_is_logged(
        self, controller: HuaweiController, caplog: pytest.LogCaptureFixture
    ) -> None:
        controller.apply_intents(make_schedule_mock(make_intents({2: "GRID_CHARGING"})))
        ha = MagicMock()
        ha.is_sensor_configured.return_value = False
        with caplog.at_level("INFO", logger="core.bess.huawei_controller"):
            controller.write_to_hardware(ha, 0, [])
        assert any(
            "working mode" in r.message.lower() for r in caplog.records
        ), "skipping the working-mode gate must be logged, not silent"

    def test_gate_still_runs_when_working_mode_entity_mapped(
        self, controller: HuaweiController
    ) -> None:
        controller.apply_intents(make_schedule_mock(make_intents({2: "GRID_CHARGING"})))
        ha = MagicMock()
        ha.is_sensor_configured.return_value = True
        ha.get_huawei_working_mode_options.return_value = [
            "maximise_self_consumption",
            "time_of_use_luna2000",
        ]
        ha.get_huawei_working_mode.return_value = "maximise_self_consumption"
        controller.write_to_hardware(ha, 0, [])
        ha.set_huawei_working_mode.assert_called_once_with("time_of_use_luna2000")


class TestCheckHealthWithoutWorkingMode:
    def test_unmapped_working_mode_reports_warning_not_error(
        self, controller: HuaweiController
    ) -> None:
        """An EMMA-managed install has no working-mode select to read; that is
        a configuration state, not a hardware fault."""
        ha = MagicMock()
        ha.is_sensor_configured.return_value = False
        result = controller.check_health(ha)
        assert result[0]["status"] == "WARNING"
        assert result[0]["checks"][0]["status"] == "WARNING"
        ha.get_huawei_working_mode.assert_not_called()

    def test_mapped_working_mode_still_reports_ok(
        self, controller: HuaweiController
    ) -> None:
        ha = MagicMock()
        ha.is_sensor_configured.return_value = True
        ha.get_huawei_working_mode.return_value = "time_of_use_luna2000"
        result = controller.check_health(ha)
        assert result[0]["status"] == "OK"


class TestSyncSocLimits:
    def test_no_write_when_hardware_already_matches_config(
        self, controller: HuaweiController
    ) -> None:
        ha = MagicMock()
        ha.get_charge_stop_soc.return_value = 95
        ha.get_discharge_stop_soc.return_value = 15
        controller.sync_soc_limits(ha)
        ha.set_charge_stop_soc.assert_not_called()
        ha.set_discharge_stop_soc.assert_not_called()

    def test_writes_only_mismatched_register(
        self, controller: HuaweiController
    ) -> None:
        ha = MagicMock()
        ha.get_charge_stop_soc.return_value = 90
        ha.get_discharge_stop_soc.return_value = 15
        controller.sync_soc_limits(ha)
        ha.set_charge_stop_soc.assert_called_once_with(95)
        ha.set_discharge_stop_soc.assert_not_called()


class TestActiveTouIntervals:
    def test_active_tou_intervals_returns_all(
        self, controller: HuaweiController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule_mock(intents))
        assert controller.active_tou_intervals == controller.tou_intervals


class TestEvaluateIntentsHuawei:
    def test_identical_periods_do_not_differ(
        self, controller: HuaweiController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule_mock(intents))
        differ, _ = controller.evaluate_intents(make_schedule_mock(intents))
        assert differ is False

    def test_different_periods_differ(self, controller: HuaweiController) -> None:
        controller.apply_intents(make_schedule_mock(make_intents({2: "GRID_CHARGING"})))
        differ, _ = controller.evaluate_intents(
            make_schedule_mock(make_intents({18: "BATTERY_EXPORT"}))
        )
        assert differ is True
