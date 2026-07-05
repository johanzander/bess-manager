"""
Behavioral tests for the Solis (solis_modbus) inverter controller.

Tests verify WHAT the system does, not HOW it does it internally. Modeled on
test_sph_schedule.py since Solis shares Growatt SPH's SM-Period-lists
scheduling model (via the shared InverterController grouping helpers), but
Solis supports 6 charge + 6 discharge periods (not 3+3) and writes each
period directly to HA entities rather than via a cloud service call.
"""

from unittest.mock import MagicMock

import pytest  # type: ignore

from core.bess.settings import BatterySettings
from core.bess.solis_modbus_controller import SolisModbusController


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
def manager(battery_settings: BatterySettings) -> SolisModbusController:
    return SolisModbusController(battery_settings=battery_settings)


# ── GRID_CHARGING → charge period ────────────────────────────────────────────


class TestGridChargingProducesChargePeriod:
    def test_grid_charging_hour_produces_one_charge_period(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING", 3: "GRID_CHARGING"})
        manager.create_schedule(make_schedule_mock(intents))

        assert len(manager._charge_periods) == 1

    def test_charge_period_time_matches_grid_charging_hours(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING", 3: "GRID_CHARGING"})
        manager.create_schedule(make_schedule_mock(intents))

        period = manager._charge_periods[0]
        assert period["start_time"] == "02:00"
        assert period["end_time"] == "03:59"

    def test_grid_charging_writes_charge_slot_to_controller(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING"})
        manager.create_schedule(make_schedule_mock(intents))

        controller = MagicMock()
        manager.write_schedule_to_hardware(controller, 0, [])

        # Slot 1 gets the real charge period, enabled=True
        controller.write_solis_period.assert_any_call(
            "charge", 1, "02:00", "02:59", True
        )

    def test_no_grid_charging_disables_all_charge_slots(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents({})  # All IDLE
        manager.create_schedule(make_schedule_mock(intents))

        controller = MagicMock()
        manager.write_schedule_to_hardware(controller, 0, [])

        for slot in range(1, manager.MAX_CHARGE_PERIODS + 1):
            controller.write_solis_period.assert_any_call(
                "charge", slot, "00:00", "00:00", False
            )


# ── SOLAR_STORAGE → no charge period ─────────────────────────────────────────


class TestSolarStorageIsIdle:
    def test_solar_storage_produces_no_charge_periods(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents({10: "SOLAR_STORAGE", 11: "SOLAR_STORAGE"})
        manager.create_schedule(make_schedule_mock(intents))

        assert len(manager._charge_periods) == 0

    def test_solar_storage_produces_no_discharge_periods(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents({10: "SOLAR_STORAGE"})
        manager.create_schedule(make_schedule_mock(intents))

        assert len(manager._discharge_periods) == 0


# ── LOAD_SUPPORT / BATTERY_EXPORT → discharge period ─────────────────────────


class TestDischargeIntentsProduceDischargePeriod:
    def test_load_support_produces_discharge_period(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents({18: "LOAD_SUPPORT", 19: "LOAD_SUPPORT"})
        manager.create_schedule(make_schedule_mock(intents))

        assert len(manager._discharge_periods) == 1

    def test_export_arbitrage_produces_discharge_period(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents({20: "BATTERY_EXPORT"})
        manager.create_schedule(make_schedule_mock(intents))

        assert len(manager._discharge_periods) == 1

    def test_consecutive_mixed_discharge_intents_merge_into_one_period(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents({18: "LOAD_SUPPORT", 19: "BATTERY_EXPORT"})
        manager.create_schedule(make_schedule_mock(intents))

        assert len(manager._discharge_periods) == 1
        assert manager._discharge_periods[0]["start_time"] == "18:00"
        assert manager._discharge_periods[0]["end_time"] == "19:59"

    def test_discharge_period_writes_discharge_slot_to_controller(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents({20: "BATTERY_EXPORT"})
        manager.create_schedule(make_schedule_mock(intents))

        controller = MagicMock()
        manager.write_schedule_to_hardware(controller, 0, [])

        controller.write_solis_period.assert_any_call(
            "discharge", 1, "20:00", "20:59", True
        )


# ── IDLE-only day ─────────────────────────────────────────────────────────────


class TestIdleOnlyDay:
    def test_idle_day_has_no_charge_periods(
        self, manager: SolisModbusController
    ) -> None:
        intents = ["IDLE"] * 96
        manager.create_schedule(make_schedule_mock(intents))

        assert len(manager._charge_periods) == 0

    def test_idle_day_has_no_discharge_periods(
        self, manager: SolisModbusController
    ) -> None:
        intents = ["IDLE"] * 96
        manager.create_schedule(make_schedule_mock(intents))

        assert len(manager._discharge_periods) == 0

    def test_idle_day_writes_all_12_slots_disabled(
        self, manager: SolisModbusController
    ) -> None:
        intents = ["IDLE"] * 96
        manager.create_schedule(make_schedule_mock(intents))

        controller = MagicMock()
        writes, disables = manager.write_schedule_to_hardware(controller, 0, [])

        assert writes == 12
        assert disables == 12


# ── 6-period limit enforcement (Solis supports 6 slots, not SPH's 3) ────────


class TestPeriodLimitEnforcement:
    def test_more_than_6_charge_blocks_capped_to_6(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents(
            dict.fromkeys(range(0, 24, 2), "GRID_CHARGING")  # 12 non-consecutive blocks
        )
        manager.create_schedule(make_schedule_mock(intents))

        assert len(manager._charge_periods) <= 6

    def test_more_than_6_discharge_blocks_capped_to_6(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents(
            dict.fromkeys(range(1, 24, 2), "LOAD_SUPPORT")  # 12 non-consecutive blocks
        )
        manager.create_schedule(make_schedule_mock(intents))

        assert len(manager._discharge_periods) <= 6


# ── Schedule comparison ──────────────────────────────────────────────────────


class TestCompareSchedules:
    def test_identical_schedules_do_not_differ(
        self, manager: SolisModbusController, battery_settings: BatterySettings
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING"})
        manager.create_schedule(make_schedule_mock(intents))

        other = SolisModbusController(battery_settings=battery_settings)
        other.create_schedule(make_schedule_mock(intents))

        differ, _ = manager.compare_schedules(other)
        assert differ is False

    def test_different_charge_periods_are_detected(
        self, manager: SolisModbusController, battery_settings: BatterySettings
    ) -> None:
        manager.create_schedule(make_schedule_mock(make_intents({2: "GRID_CHARGING"})))

        other = SolisModbusController(battery_settings=battery_settings)
        other.create_schedule(make_schedule_mock(make_intents({5: "GRID_CHARGING"})))

        differ, reason = manager.compare_schedules(other)
        assert differ is True
        assert "charge" in reason.lower()


# ── Read-back from hardware ──────────────────────────────────────────────────


class TestReadAndInitializeFromHardware:
    def test_reads_enabled_periods_into_charge_and_discharge_lists(
        self, manager: SolisModbusController
    ) -> None:
        controller = MagicMock()
        controller.read_solis_periods.side_effect = lambda direction: (
            [{"slot": 1, "start_time": "02:00", "end_time": "03:59", "enabled": True}]
            if direction == "charge"
            else []
        )

        manager.read_and_initialize_from_hardware(controller, current_hour=10)

        assert len(manager._charge_periods) == 1
        assert manager._charge_periods[0]["start_time"] == "02:00"
        assert len(manager._discharge_periods) == 0

    def test_disabled_periods_are_not_included(
        self, manager: SolisModbusController
    ) -> None:
        controller = MagicMock()
        controller.read_solis_periods.return_value = [
            {"slot": 1, "start_time": "00:00", "end_time": "00:00", "enabled": False}
        ]

        manager.read_and_initialize_from_hardware(controller, current_hour=10)

        assert len(manager._charge_periods) == 0
        assert len(manager._discharge_periods) == 0


# ── SOC sync is an explicit no-op (no verified write path) ──────────────────


class TestSocLimitsNotImplemented:
    def test_sync_soc_limits_does_not_call_controller(
        self, manager: SolisModbusController
    ) -> None:
        controller = MagicMock()
        manager.sync_soc_limits(controller)

        controller.assert_not_called()
        assert controller.method_calls == []


# ── Health check ──────────────────────────────────────────────────────────


class TestHealthCheck:
    def test_health_check_ok_when_periods_readable(
        self, manager: SolisModbusController
    ) -> None:
        controller = MagicMock()
        controller.read_solis_periods.return_value = []

        result = manager.check_health(controller)

        assert result[0]["status"] == "OK"

    def test_health_check_error_when_read_fails(
        self, manager: SolisModbusController
    ) -> None:
        controller = MagicMock()
        controller.read_solis_periods.side_effect = RuntimeError("boom")

        result = manager.check_health(controller)

        assert result[0]["status"] == "ERROR"
