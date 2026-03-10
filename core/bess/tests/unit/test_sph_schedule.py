"""
Behavioral tests for SPH inverter schedule management.

Tests verify WHAT the system does, not HOW it does it internally.
"""

from unittest.mock import MagicMock

import pytest  # type: ignore

from core.bess.settings import BatterySettings
from core.bess.sph_schedule import SphScheduleManager


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
def manager(battery_settings: BatterySettings) -> SphScheduleManager:
    return SphScheduleManager(battery_settings=battery_settings)


# ── GRID_CHARGING → charge period ────────────────────────────────────────────


class TestGridChargingProducesChargePeriod:
    def test_grid_charging_hour_produces_one_charge_period(
        self, manager: SphScheduleManager
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING", 3: "GRID_CHARGING"})
        manager.create_schedule(make_schedule_mock(intents))

        assert len(manager._charge_periods) == 1

    def test_charge_period_time_matches_grid_charging_hours(
        self, manager: SphScheduleManager
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING", 3: "GRID_CHARGING"})
        manager.create_schedule(make_schedule_mock(intents))

        period = manager._charge_periods[0]
        assert period["start_time"] == "02:00"
        assert period["end_time"] == "03:59"

    def test_grid_charging_writes_charge_call_to_controller(
        self, manager: SphScheduleManager
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING"})
        manager.create_schedule(make_schedule_mock(intents))

        controller = MagicMock()
        manager.write_schedule_to_hardware(controller, 0, [])

        controller.write_ac_charge_times.assert_called_once()
        call_kwargs = controller.write_ac_charge_times.call_args.kwargs
        assert call_kwargs["mains_enabled"] is True

    def test_no_grid_charging_sets_mains_disabled(
        self, manager: SphScheduleManager
    ) -> None:
        intents = make_intents({})  # All IDLE
        manager.create_schedule(make_schedule_mock(intents))

        controller = MagicMock()
        manager.write_schedule_to_hardware(controller, 0, [])

        call_kwargs = controller.write_ac_charge_times.call_args.kwargs
        assert call_kwargs["mains_enabled"] is False


# ── SOLAR_STORAGE → no charge period ─────────────────────────────────────────


class TestSolarStorageIsIdle:
    def test_solar_storage_produces_no_charge_periods(
        self, manager: SphScheduleManager
    ) -> None:
        intents = make_intents({10: "SOLAR_STORAGE", 11: "SOLAR_STORAGE"})
        manager.create_schedule(make_schedule_mock(intents))

        assert len(manager._charge_periods) == 0

    def test_solar_storage_produces_no_discharge_periods(
        self, manager: SphScheduleManager
    ) -> None:
        intents = make_intents({10: "SOLAR_STORAGE"})
        manager.create_schedule(make_schedule_mock(intents))

        assert len(manager._discharge_periods) == 0


# ── LOAD_SUPPORT / EXPORT_ARBITRAGE → discharge period ───────────────────────


class TestDischargeIntentsProduceDischargeperiod:
    def test_load_support_produces_discharge_period(
        self, manager: SphScheduleManager
    ) -> None:
        intents = make_intents({18: "LOAD_SUPPORT", 19: "LOAD_SUPPORT"})
        manager.create_schedule(make_schedule_mock(intents))

        assert len(manager._discharge_periods) == 1

    def test_export_arbitrage_produces_discharge_period(
        self, manager: SphScheduleManager
    ) -> None:
        intents = make_intents({20: "EXPORT_ARBITRAGE"})
        manager.create_schedule(make_schedule_mock(intents))

        assert len(manager._discharge_periods) == 1

    def test_consecutive_mixed_discharge_intents_merge_into_one_period(
        self, manager: SphScheduleManager
    ) -> None:
        # LOAD_SUPPORT followed immediately by EXPORT_ARBITRAGE → both are in
        # DISCHARGE_INTENTS, so they merge into a single continuous discharge period.
        intents = make_intents({18: "LOAD_SUPPORT", 19: "EXPORT_ARBITRAGE"})
        manager.create_schedule(make_schedule_mock(intents))

        assert len(manager._discharge_periods) == 1
        assert manager._discharge_periods[0]["start_time"] == "18:00"
        assert manager._discharge_periods[0]["end_time"] == "19:59"

    def test_discharge_period_writes_discharge_call_to_controller(
        self, manager: SphScheduleManager
    ) -> None:
        intents = make_intents({20: "EXPORT_ARBITRAGE"})
        manager.create_schedule(make_schedule_mock(intents))

        controller = MagicMock()
        manager.write_schedule_to_hardware(controller, 0, [])

        controller.write_ac_discharge_times.assert_called_once()


# ── IDLE-only day ─────────────────────────────────────────────────────────────


class TestIdleOnlyDay:
    def test_idle_day_has_no_charge_periods(self, manager: SphScheduleManager) -> None:
        intents = ["IDLE"] * 96
        manager.create_schedule(make_schedule_mock(intents))

        assert len(manager._charge_periods) == 0

    def test_idle_day_has_no_discharge_periods(
        self, manager: SphScheduleManager
    ) -> None:
        intents = ["IDLE"] * 96
        manager.create_schedule(make_schedule_mock(intents))

        assert len(manager._discharge_periods) == 0

    def test_idle_day_always_writes_both_calls(
        self, manager: SphScheduleManager
    ) -> None:
        intents = ["IDLE"] * 96
        manager.create_schedule(make_schedule_mock(intents))

        controller = MagicMock()
        writes, disables = manager.write_schedule_to_hardware(controller, 0, [])

        assert writes == 2
        assert disables == 0
        controller.write_ac_charge_times.assert_called_once()
        controller.write_ac_discharge_times.assert_called_once()


# ── 3-period limit enforcement ────────────────────────────────────────────────


class TestPeriodLimitEnforcement:
    def test_more_than_3_charge_blocks_capped_to_3(
        self, manager: SphScheduleManager
    ) -> None:
        # 4 non-consecutive GRID_CHARGING blocks
        intents = make_intents(
            {
                0: "GRID_CHARGING",
                2: "GRID_CHARGING",
                4: "GRID_CHARGING",
                6: "GRID_CHARGING",
            }
        )
        manager.create_schedule(make_schedule_mock(intents))

        assert len(manager._charge_periods) <= 3

    def test_more_than_3_discharge_blocks_capped_to_3(
        self, manager: SphScheduleManager
    ) -> None:
        intents = make_intents(
            {
                10: "LOAD_SUPPORT",
                12: "LOAD_SUPPORT",
                14: "LOAD_SUPPORT",
                16: "LOAD_SUPPORT",
            }
        )
        manager.create_schedule(make_schedule_mock(intents))

        assert len(manager._discharge_periods) <= 3

    def test_period_limit_keeps_longest_blocks(
        self, manager: SphScheduleManager
    ) -> None:
        # 4 blocks of different durations: 4h, 1h, 1h, 1h → keep the 4h + 2 of the 1h blocks
        intents = ["IDLE"] * 96
        # Block 1: 4 hours (hours 0-3)
        for h in range(0, 4):
            for p in range(h * 4, (h + 1) * 4):
                intents[p] = "GRID_CHARGING"
        # Block 2: 1 hour (hour 6)
        for p in range(6 * 4, 7 * 4):
            intents[p] = "GRID_CHARGING"
        # Block 3: 1 hour (hour 8)
        for p in range(8 * 4, 9 * 4):
            intents[p] = "GRID_CHARGING"
        # Block 4: 1 hour (hour 10)
        for p in range(10 * 4, 11 * 4):
            intents[p] = "GRID_CHARGING"

        manager.create_schedule(make_schedule_mock(intents))

        assert len(manager._charge_periods) == 3
        # The 4-hour block should be kept
        durations = [
            _time_to_minutes(p["end_time"]) - _time_to_minutes(p["start_time"]) + 1
            for p in manager._charge_periods
        ]
        assert max(durations) >= 4 * 60 - 1  # ~4 hours


# ── compare_schedules ─────────────────────────────────────────────────────────


class TestCompareSchedules:
    def test_identical_schedules_do_not_differ(
        self, manager: SphScheduleManager, battery_settings: BatterySettings
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING", 20: "LOAD_SUPPORT"})
        schedule = make_schedule_mock(intents)
        manager.create_schedule(schedule)

        other = SphScheduleManager(battery_settings=battery_settings)
        other.create_schedule(schedule)

        differ, _ = manager.compare_schedules(other)
        assert not differ

    def test_different_charge_periods_report_difference(
        self, manager: SphScheduleManager, battery_settings: BatterySettings
    ) -> None:
        intents_a = make_intents({2: "GRID_CHARGING"})
        intents_b = make_intents({4: "GRID_CHARGING"})

        manager.create_schedule(make_schedule_mock(intents_a))

        other = SphScheduleManager(battery_settings=battery_settings)
        other.create_schedule(make_schedule_mock(intents_b))

        differ, reason = manager.compare_schedules(other)
        assert differ
        assert reason

    def test_different_discharge_periods_report_difference(
        self, manager: SphScheduleManager, battery_settings: BatterySettings
    ) -> None:
        intents_a = make_intents({20: "LOAD_SUPPORT"})
        intents_b = make_intents({22: "LOAD_SUPPORT"})

        manager.create_schedule(make_schedule_mock(intents_a))

        other = SphScheduleManager(battery_settings=battery_settings)
        other.create_schedule(make_schedule_mock(intents_b))

        differ, reason = manager.compare_schedules(other)
        assert differ
        assert reason

    def test_empty_vs_nonempty_differs(
        self, manager: SphScheduleManager, battery_settings: BatterySettings
    ) -> None:
        manager.create_schedule(make_schedule_mock(["IDLE"] * 96))

        other = SphScheduleManager(battery_settings=battery_settings)
        other.create_schedule(make_schedule_mock(make_intents({2: "GRID_CHARGING"})))

        differ, _ = manager.compare_schedules(other)
        assert differ


# ── write_schedule_to_hardware ────────────────────────────────────────────────


class TestWriteScheduleToHardware:
    def test_always_returns_2_writes_0_disables(
        self, manager: SphScheduleManager
    ) -> None:
        manager.create_schedule(make_schedule_mock(make_intents({2: "GRID_CHARGING"})))

        controller = MagicMock()
        writes, disables = manager.write_schedule_to_hardware(controller, 0, [])

        assert writes == 2
        assert disables == 0

    def test_calls_both_charge_and_discharge_methods(
        self, manager: SphScheduleManager
    ) -> None:
        manager.create_schedule(
            make_schedule_mock(make_intents({2: "GRID_CHARGING", 20: "LOAD_SUPPORT"}))
        )

        controller = MagicMock()
        manager.write_schedule_to_hardware(controller, 0, [])

        controller.write_ac_charge_times.assert_called_once()
        controller.write_ac_discharge_times.assert_called_once()

    def test_charge_stop_soc_comes_from_battery_settings(
        self, manager: SphScheduleManager, battery_settings: BatterySettings
    ) -> None:
        manager.create_schedule(make_schedule_mock(["IDLE"] * 96))

        controller = MagicMock()
        manager.write_schedule_to_hardware(controller, 0, [])

        call_kwargs = controller.write_ac_charge_times.call_args.kwargs
        assert call_kwargs["charge_stop_soc"] == int(battery_settings.max_soc)

    def test_discharge_stop_soc_comes_from_battery_settings(
        self, manager: SphScheduleManager, battery_settings: BatterySettings
    ) -> None:
        manager.create_schedule(make_schedule_mock(["IDLE"] * 96))

        controller = MagicMock()
        manager.write_schedule_to_hardware(controller, 0, [])

        call_kwargs = controller.write_ac_discharge_times.call_args.kwargs
        assert call_kwargs["discharge_stop_soc"] == int(battery_settings.min_soc)

    def test_unused_charge_periods_are_disabled(
        self, manager: SphScheduleManager
    ) -> None:
        # 1 charge period → period_2 and period_3 must be disabled
        intents = make_intents({2: "GRID_CHARGING"})
        manager.create_schedule(make_schedule_mock(intents))

        controller = MagicMock()
        manager.write_schedule_to_hardware(controller, 0, [])

        call_kwargs = controller.write_ac_charge_times.call_args.kwargs
        assert call_kwargs.get("period_1_enabled") is True
        assert call_kwargs.get("period_2_enabled") is False
        assert call_kwargs.get("period_3_enabled") is False


# ── Helper ────────────────────────────────────────────────────────────────────


def _time_to_minutes(time_str: str) -> int:
    h, m = map(int, time_str.split(":"))
    return h * 60 + m
