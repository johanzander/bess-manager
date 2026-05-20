"""Behavioral tests for the SolaX inverter controller.

Tests verify WHAT the system does, not HOW it does it internally.
"""

from unittest.mock import MagicMock

import pytest

from core.bess.settings import BatterySettings
from core.bess.solax_controller import SolaxController


def make_intents(hourly: dict[int, str], default: str = "IDLE") -> list[str]:
    """Convert hourly intent map to 96 quarterly intents."""
    quarterly = [default] * 96
    for hour, intent in hourly.items():
        for p in range(hour * 4, (hour + 1) * 4):
            quarterly[p] = intent
    return quarterly


def make_schedule_mock(intents: list[str]) -> MagicMock:
    """Create a DPSchedule-like mock with the given intents."""
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
def controller(battery_settings: BatterySettings) -> SolaxController:
    return SolaxController(battery_settings=battery_settings)


# ── Active TOU intervals ──────────────────────────────────────────────────────


class TestActiveTouIntervals:
    def test_active_tou_intervals_is_always_empty(
        self, controller: SolaxController
    ) -> None:
        assert controller.active_tou_intervals == []

    def test_active_tou_intervals_empty_after_schedule_loaded(
        self, controller: SolaxController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING", 20: "LOAD_SUPPORT"})
        controller.create_schedule(make_schedule_mock(intents))

        assert controller.active_tou_intervals == []


# ── create_schedule ───────────────────────────────────────────────────────────


class TestCreateSchedule:
    def test_strategic_intents_stored_after_create_schedule(
        self, controller: SolaxController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING"})
        controller.create_schedule(make_schedule_mock(intents))

        assert controller.strategic_intents == intents

    def test_hourly_settings_populated_after_create_schedule(
        self, controller: SolaxController
    ) -> None:
        intents = ["IDLE"] * 96
        controller.create_schedule(make_schedule_mock(intents))

        assert len(controller.hourly_settings) == 24

    def test_current_schedule_stored_after_create_schedule(
        self, controller: SolaxController
    ) -> None:
        schedule = make_schedule_mock(["IDLE"] * 96)
        controller.create_schedule(schedule)

        assert controller.current_schedule is schedule


# ── write_schedule_to_hardware ────────────────────────────────────────────────


class TestWriteScheduleToHardware:
    def test_returns_zero_writes_zero_disables(
        self, controller: SolaxController
    ) -> None:
        mock_hw = MagicMock()
        writes, disables = controller.write_schedule_to_hardware(mock_hw, 0, [])

        assert writes == 0
        assert disables == 0

    def test_does_not_call_any_hardware_method(
        self, controller: SolaxController
    ) -> None:
        mock_hw = MagicMock()
        controller.write_schedule_to_hardware(mock_hw, 0, [])

        mock_hw.assert_not_called()


# ── _write_period_to_hardware: IDLE / SOLAR_STORAGE ──────────────────────────


class TestWritePeriodToHardwareDisablesVppForIdle:
    def test_idle_intent_disables_vpp(self, controller: SolaxController) -> None:
        mock_hw = MagicMock()
        controller._write_period_to_hardware(
            mock_hw, grid_charge=False, discharge_rate=0
        )

        mock_hw.set_solax_vpp_disabled.assert_called_once()
        mock_hw.set_solax_active_power_control.assert_not_called()

    def test_solar_storage_also_disables_vpp(self, controller: SolaxController) -> None:
        # SOLAR_STORAGE maps to grid_charge=False, discharge_rate=0
        mock_hw = MagicMock()
        controller._write_period_to_hardware(
            mock_hw, grid_charge=False, discharge_rate=0
        )

        mock_hw.set_solax_vpp_disabled.assert_called_once()


# ── _write_period_to_hardware: GRID_CHARGING ─────────────────────────────────


class TestWritePeriodToHardwareGridCharging:
    def test_grid_charging_calls_active_power_control(
        self, controller: SolaxController
    ) -> None:
        mock_hw = MagicMock()
        controller._write_period_to_hardware(
            mock_hw, grid_charge=True, discharge_rate=0
        )

        mock_hw.set_solax_active_power_control.assert_called_once()
        mock_hw.set_solax_vpp_disabled.assert_not_called()

    def test_grid_charging_power_is_positive_watts(
        self, controller: SolaxController
    ) -> None:
        mock_hw = MagicMock()
        controller._write_period_to_hardware(
            mock_hw, grid_charge=True, discharge_rate=0
        )

        watts = mock_hw.set_solax_active_power_control.call_args.args[0]
        assert watts > 0

    def test_grid_charging_power_matches_max_charge_setting(
        self, controller: SolaxController, battery_settings: BatterySettings
    ) -> None:
        mock_hw = MagicMock()
        controller._write_period_to_hardware(
            mock_hw, grid_charge=True, discharge_rate=0
        )

        expected_watts = int(battery_settings.max_charge_power_kw * 1000)
        watts = mock_hw.set_solax_active_power_control.call_args.args[0]
        assert watts == expected_watts


# ── _write_period_to_hardware: LOAD_SUPPORT / EXPORT_ARBITRAGE ───────────────


class TestWritePeriodToHardwareDischarge:
    def test_full_discharge_rate_calls_active_power_control(
        self, controller: SolaxController
    ) -> None:
        mock_hw = MagicMock()
        controller._write_period_to_hardware(
            mock_hw, grid_charge=False, discharge_rate=100
        )

        mock_hw.set_solax_active_power_control.assert_called_once()
        mock_hw.set_solax_vpp_disabled.assert_not_called()

    def test_full_discharge_rate_produces_negative_watts(
        self, controller: SolaxController
    ) -> None:
        mock_hw = MagicMock()
        controller._write_period_to_hardware(
            mock_hw, grid_charge=False, discharge_rate=100
        )

        watts = mock_hw.set_solax_active_power_control.call_args.args[0]
        assert watts < 0

    def test_full_discharge_equals_max_discharge_power(
        self, controller: SolaxController, battery_settings: BatterySettings
    ) -> None:
        mock_hw = MagicMock()
        controller._write_period_to_hardware(
            mock_hw, grid_charge=False, discharge_rate=100
        )

        expected_watts = -int(battery_settings.max_discharge_power_kw * 1000)
        watts = mock_hw.set_solax_active_power_control.call_args.args[0]
        assert watts == expected_watts

    def test_partial_discharge_rate_scales_proportionally(
        self, controller: SolaxController, battery_settings: BatterySettings
    ) -> None:
        mock_hw = MagicMock()
        controller._write_period_to_hardware(
            mock_hw, grid_charge=False, discharge_rate=50
        )

        expected_watts = -int(battery_settings.max_discharge_power_kw * 0.50 * 1000)
        watts = mock_hw.set_solax_active_power_control.call_args.args[0]
        assert watts == expected_watts

    def test_zero_discharge_rate_disables_vpp(
        self, controller: SolaxController
    ) -> None:
        mock_hw = MagicMock()
        controller._write_period_to_hardware(
            mock_hw, grid_charge=False, discharge_rate=0
        )

        mock_hw.set_solax_vpp_disabled.assert_called_once()
        mock_hw.set_solax_active_power_control.assert_not_called()


# ── compare_schedules ─────────────────────────────────────────────────────────


class TestCompareSchedules:
    def test_empty_schedules_do_not_differ(
        self, controller: SolaxController, battery_settings: BatterySettings
    ) -> None:
        other = SolaxController(battery_settings=battery_settings)
        differ, _ = controller.compare_schedules(other)
        assert not differ

    def test_identical_schedules_do_not_differ(
        self, controller: SolaxController, battery_settings: BatterySettings
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING", 20: "LOAD_SUPPORT"})
        schedule = make_schedule_mock(intents)
        controller.create_schedule(schedule)

        other = SolaxController(battery_settings=battery_settings)
        other.create_schedule(schedule)

        differ, _ = controller.compare_schedules(other)
        assert not differ

    def test_different_intents_are_detected(
        self, controller: SolaxController, battery_settings: BatterySettings
    ) -> None:
        controller.create_schedule(
            make_schedule_mock(make_intents({2: "GRID_CHARGING"}))
        )

        other = SolaxController(battery_settings=battery_settings)
        other.create_schedule(make_schedule_mock(make_intents({4: "GRID_CHARGING"})))

        differ, reason = controller.compare_schedules(other)
        assert differ
        assert reason

    def test_from_period_skips_earlier_differences(
        self, controller: SolaxController, battery_settings: BatterySettings
    ) -> None:
        # Period 0-3 differs, but compare_schedules starts at period 8 → no diff
        intents_a = ["GRID_CHARGING"] * 4 + ["IDLE"] * 92
        intents_b = ["IDLE"] * 96

        controller.strategic_intents = intents_a

        other = SolaxController(battery_settings=battery_settings)
        other.strategic_intents = intents_b

        differ, _ = controller.compare_schedules(other, from_period=8)
        assert not differ

    def test_different_length_intents_report_difference(
        self, controller: SolaxController, battery_settings: BatterySettings
    ) -> None:
        controller.strategic_intents = ["IDLE"] * 96
        other = SolaxController(battery_settings=battery_settings)
        other.strategic_intents = ["IDLE"] * 48

        differ, _ = controller.compare_schedules(other)
        assert differ


# ── sync_soc_limits ───────────────────────────────────────────────────────────


class TestSyncSocLimits:
    def test_sync_soc_limits_calls_set_solax_min_soc(
        self, controller: SolaxController, battery_settings: BatterySettings
    ) -> None:
        mock_hw = MagicMock()
        mock_hw.get_solax_power_control_mode.return_value = "Self Use Mode"
        controller.sync_soc_limits(mock_hw)

        mock_hw.set_solax_min_soc.assert_called_once_with(int(battery_settings.min_soc))

    def test_sync_soc_limits_uses_battery_settings_min_soc(
        self, battery_settings: BatterySettings
    ) -> None:
        battery_settings.min_soc = 20.0
        ctrl = SolaxController(battery_settings=battery_settings)
        mock_hw = MagicMock()
        mock_hw.get_solax_power_control_mode.return_value = "Self Use Mode"
        ctrl.sync_soc_limits(mock_hw)

        mock_hw.set_solax_min_soc.assert_called_once_with(20)


# ── check_health ──────────────────────────────────────────────────────────────


class TestCheckHealth:
    def test_returns_list(self, controller: SolaxController) -> None:
        mock_hw = MagicMock()
        mock_hw.get_solax_power_control_mode.return_value = "Self Use Mode"
        result = controller.check_health(mock_hw)
        assert isinstance(result, list)

    def test_ok_when_power_control_mode_readable(
        self, controller: SolaxController
    ) -> None:
        mock_hw = MagicMock()
        mock_hw.get_solax_power_control_mode.return_value = "Self Use Mode"
        result = controller.check_health(mock_hw)

        assert any(item["status"] == "OK" for item in result)

    def test_error_when_power_control_mode_returns_none(
        self, controller: SolaxController
    ) -> None:
        mock_hw = MagicMock()
        mock_hw.get_solax_power_control_mode.return_value = None
        result = controller.check_health(mock_hw)

        assert any(item["status"] == "ERROR" for item in result)

    def test_error_when_power_control_mode_raises(
        self, controller: SolaxController
    ) -> None:
        mock_hw = MagicMock()
        mock_hw.get_solax_power_control_mode.side_effect = ValueError(
            "entity not configured"
        )
        result = controller.check_health(mock_hw)

        assert any(item["status"] == "ERROR" for item in result)


# ── get_all_tou_segments ──────────────────────────────────────────────────────


class TestGetAllTouSegments:
    def test_returns_default_segment_when_no_schedule(
        self, controller: SolaxController
    ) -> None:
        segments = controller.get_all_tou_segments()

        assert len(segments) == 1
        assert segments[0]["is_default"] is True

    def test_returns_segments_from_loaded_schedule(
        self, controller: SolaxController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING", 20: "LOAD_SUPPORT"})
        controller.create_schedule(make_schedule_mock(intents))

        segments = controller.get_all_tou_segments()

        # Should have multiple segments, not the default placeholder
        assert len(segments) > 1
        assert all("is_default" not in seg for seg in segments)

    def test_all_segments_have_required_fields(
        self, controller: SolaxController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING"})
        controller.create_schedule(make_schedule_mock(intents))

        segments = controller.get_all_tou_segments()
        required_fields = {
            "segment_id",
            "start_time",
            "end_time",
            "batt_mode",
            "enabled",
        }

        for segment in segments:
            assert required_fields.issubset(segment.keys())
