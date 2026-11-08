"""
Behavioral tests for the Solis (solis_modbus) inverter controller.

Tests verify WHAT the system does, not HOW it does it internally. Modeled on
test_sph_schedule.py since Solis shares Growatt SPH's SM-Period-lists
scheduling model (via the shared InverterController grouping helpers), but
Solis supports 6 charge + 6 discharge periods (not 3+3) and writes each
period directly to HA entities rather than via a cloud service call.
"""

import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any
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


def planned(
    soe_start: float = 1.5,
    soe_end: float | None = None,
    battery_discharged: float = 0.5,
    grid_imported: float = 0.5,
    verdict_open: bool = False,
) -> SimpleNamespace:
    """A plan row; the default sits at the fixture battery's 1.5 kWh floor."""
    return SimpleNamespace(
        energy=SimpleNamespace(
            battery_soe_start=soe_start,
            battery_soe_end=soe_start if soe_end is None else soe_end,
            battery_discharged=battery_discharged,
            grid_imported=grid_imported,
        ),
        decision=SimpleNamespace(intra_period_discharge_allowed=verdict_open),
    )


def make_schedule_mock(
    intents: list[str], period_data: list | None = None
) -> MagicMock:
    """Create a DPSchedule-like mock with the given intents."""
    schedule = MagicMock()
    schedule.original_dp_results = {"strategic_intent": intents}
    schedule.actions = [0.0] * len(intents)
    schedule.period_data = (
        [planned() for _ in intents] if period_data is None else period_data
    )
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
        manager.apply_intents(make_schedule_mock(intents))

        assert len(manager._charge_periods) == 1

    def test_charge_period_time_matches_grid_charging_hours(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING", 3: "GRID_CHARGING"})
        manager.apply_intents(make_schedule_mock(intents))

        period = manager._charge_periods[0]
        assert period["start_time"] == "02:00"
        assert period["end_time"] == "03:59"

    def test_grid_charging_writes_charge_slot_to_controller(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING"})
        manager.apply_intents(make_schedule_mock(intents))

        controller = MagicMock()
        manager.sync_to_hardware(controller, 0)

        # Slot 1 gets the real charge period, enabled=True
        controller.write_solis_period.assert_any_call(
            "charge", 1, "02:00", "02:59", True
        )

    def test_no_grid_charging_disables_all_charge_slots(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents({})  # All IDLE
        manager.apply_intents(make_schedule_mock(intents))

        controller = MagicMock()
        manager.sync_to_hardware(controller, 0)

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
        manager.apply_intents(make_schedule_mock(intents))

        assert len(manager._charge_periods) == 0

    def test_solar_storage_produces_no_discharge_periods(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents({10: "SOLAR_STORAGE"})
        manager.apply_intents(make_schedule_mock(intents))

        assert len(manager._discharge_periods) == 0


# ── BATTERY_EXPORT → discharge period; LOAD_SUPPORT is left to Self Use ──────


class TestDischargeIntentsProduceDischargePeriod:
    def test_load_support_opens_no_discharge_period(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents({18: "LOAD_SUPPORT", 19: "LOAD_SUPPORT"})
        manager.apply_intents(make_schedule_mock(intents))

        assert len(manager._discharge_periods) == 0

    def test_export_arbitrage_produces_discharge_period(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents({20: "BATTERY_EXPORT"})
        manager.apply_intents(make_schedule_mock(intents))

        assert len(manager._discharge_periods) == 1

    def test_load_support_next_to_export_stays_out_of_the_export_window(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents({18: "LOAD_SUPPORT", 19: "BATTERY_EXPORT"})
        manager.apply_intents(make_schedule_mock(intents))

        assert len(manager._discharge_periods) == 1
        assert manager._discharge_periods[0]["start_time"] == "19:00"
        assert manager._discharge_periods[0]["end_time"] == "19:59"

    def test_discharge_period_writes_discharge_slot_to_controller(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents({20: "BATTERY_EXPORT"})
        manager.apply_intents(make_schedule_mock(intents))

        controller = MagicMock()
        manager.sync_to_hardware(controller, 0)

        controller.write_solis_period.assert_any_call(
            "discharge", 1, "20:00", "20:59", True
        )


# ── IDLE-only day ─────────────────────────────────────────────────────────────


class TestIdleOnlyDay:
    def test_idle_day_has_no_charge_periods(
        self, manager: SolisModbusController
    ) -> None:
        intents = ["IDLE"] * 96
        manager.apply_intents(make_schedule_mock(intents))

        assert len(manager._charge_periods) == 0

    def test_idle_day_has_no_discharge_periods(
        self, manager: SolisModbusController
    ) -> None:
        intents = ["IDLE"] * 96
        manager.apply_intents(make_schedule_mock(intents))

        assert len(manager._discharge_periods) == 0

    def test_idle_day_writes_all_12_slots_disabled(
        self, manager: SolisModbusController
    ) -> None:
        intents = ["IDLE"] * 96
        manager.apply_intents(make_schedule_mock(intents))

        controller = MagicMock()
        writes, disables = manager.sync_to_hardware(controller, 0)

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
        manager.apply_intents(make_schedule_mock(intents))

        assert len(manager._charge_periods) <= 6

    def test_more_than_6_discharge_blocks_capped_to_6(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents(
            dict.fromkeys(range(1, 24, 2), "BATTERY_EXPORT")  # 12 non-consecutive
        )
        manager.apply_intents(make_schedule_mock(intents))

        assert len(manager._discharge_periods) <= 6


# ── evaluate_intents ─────────────────────────────────────────────────────────


class TestEvaluateIntentsSolis:
    def test_no_change_when_intents_identical(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING"})
        manager.apply_intents(make_schedule_mock(intents), current_period=0)

        differs, _ = manager.evaluate_intents(make_schedule_mock(intents))

        assert differs is False

    def test_detects_charge_period_change(self, manager: SolisModbusController) -> None:
        manager.apply_intents(
            make_schedule_mock(make_intents({2: "GRID_CHARGING"})), current_period=0
        )

        differs, reason = manager.evaluate_intents(
            make_schedule_mock(make_intents({5: "GRID_CHARGING"}))
        )

        assert differs is True
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
        controller.missing_solis_discharge_limit_sensors.return_value = []

        result = manager.check_health(controller)

        assert result[0]["status"] == "OK"

    def test_health_check_names_the_fix_when_limit_entities_are_missing(
        self, manager: SolisModbusController
    ) -> None:
        # An install upgraded from before #869 has none of these configured.
        controller = MagicMock()
        controller.read_solis_periods.return_value = []
        controller.missing_solis_discharge_limit_sensors.return_value = [
            "solis_discharge_cutoff_soc_1"
        ]

        result = manager.check_health(controller)

        assert result[0]["status"] == "ERROR"
        assert "discovery" in result[0]["checks"][0]["message"].lower()

    def test_health_check_error_when_read_fails(
        self, manager: SolisModbusController
    ) -> None:
        controller = MagicMock()
        controller.read_solis_periods.side_effect = RuntimeError("boom")

        result = manager.check_health(controller)

        assert result[0]["status"] == "ERROR"


# ── Per-period apply (#850) ──────────────────────────────────────────────────


class TestApplyPeriod:
    def test_apply_period_with_battery_system_manager_call_shape_succeeds(
        self, manager: SolisModbusController
    ) -> None:
        # Command-level check: Solis has no per-period execution model (the TOU
        # schedule is deployed by sync_to_hardware), so the outcome to assert is
        # that the shared apply_period path does not raise and reports success.
        # BatterySystemManager passes every argument positionally, including
        # block_passive_charging; the Solis override once rejected it (#850).
        success, error_msg = manager.apply_period(
            MagicMock(), False, 20, False, "LOAD_SUPPORT", False, 100, False
        )

        assert success is True
        assert error_msg == ""


# ── What the inverter actually does with the slots BESS writes (#869) ────────


class MeasuredSolisInverter:
    """A Solis discharge slot as measured on the #869 reporter's S5-EH1P.

    The inverter simulator models Growatt MIN only, so R == P cannot be run for
    Solis. This encodes the reporter's controlled readings instead, so these
    tests can assert the battery's behaviour rather than the commands written:

    * no slot active: Self Use, the battery follows the net load (2,530 W);
    * slot active, SOC at or below its cut-off: 0 W (cut-off 77% at SOC 67%);
    * slot active, SOC above its cut-off: the slot current regardless of load
      (50 A gave 2,510 W, 25 A gave 1,246 W; about 2,500 W at a 670 W load).

    Slots start as the reporter's did, with a stale 50% cut-off and 50 A.
    """

    VOLTS = 50.0

    def __init__(self) -> None:
        self.discharge: dict[int, dict[str, Any]] = {
            n: {"start": "00:00", "end": "00:00", "on": False, "cutoff": 50, "amps": 50}
            for n in range(1, 7)
        }

    def write_solis_period(
        self,
        direction: str,
        slot: int,
        start_time: str,
        end_time: str,
        enabled: bool,
    ) -> None:
        if direction == "discharge":
            self.discharge[slot].update(start=start_time, end=end_time, on=enabled)

    def set_solis_discharge_cutoff_soc(self, slot: int, soc: int) -> None:
        self.discharge[slot]["cutoff"] = soc

    def set_solis_discharge_current(self, slot: int, amps: float) -> None:
        self.discharge[slot]["amps"] = amps

    def get_battery_voltage(self) -> float:
        return self.VOLTS

    def battery_watts(self, clock: str, soc: float, net_load_w: float) -> float:
        active = [
            s
            for s in self.discharge.values()
            if s["on"] and s["start"] <= clock <= s["end"]
        ]
        if not active:
            return max(0.0, net_load_w)
        if soc <= active[0]["cutoff"]:
            return 0.0
        return float(active[0]["amps"]) * self.VOLTS


REPORTER_CAPACITY_KWH = 15.36
REPORTER_PLAN = json.loads(
    (Path(__file__).parent / "fixtures" / "solis_issue_869_plan.json").read_text()
)


def _clock(period: int) -> str:
    return f"{period // 4:02d}:{(period % 4) * 15:02d}"


def _synced(
    manager: SolisModbusController,
    intents: list[str],
    period_data: list,
    current_period: int = 0,
) -> MeasuredSolisInverter:
    inverter = MeasuredSolisInverter()
    manager.apply_intents(make_schedule_mock(intents, period_data), current_period)
    manager.sync_to_hardware(inverter, current_period)
    return inverter


class TestReporterPlanOutcome:
    """Drives the controller with the plan from the #869 debug bundle."""

    @pytest.fixture
    def reporter_manager(self) -> SolisModbusController:
        return SolisModbusController(
            BatterySettings(
                total_capacity=REPORTER_CAPACITY_KWH,
                max_charge_power_kw=3.0,
                max_discharge_power_kw=3.0,
                min_soc=15.0,
                max_soc=100.0,
            )
        )

    @pytest.fixture
    def plan(self) -> tuple[list[str], list]:
        intents = ["IDLE"] * 96
        period_data: list = [None] * 96
        for row in REPORTER_PLAN:
            intents[row["period"]] = row["intent"]
            period_data[row["period"]] = planned(
                row["soe_start"],
                row["soe_end"],
                row["battery_discharged"],
                row["grid_imported"],
                row["intra_period_discharge_allowed"],
            )
        return intents, period_data

    def test_load_support_covers_the_house_without_exporting(
        self, reporter_manager: SolisModbusController, plan: tuple[list[str], list]
    ) -> None:
        inverter = _synced(reporter_manager, *plan, current_period=59)

        rows = [r for r in REPORTER_PLAN if r["intent"] == "LOAD_SUPPORT"]
        assert rows
        for row in rows:
            net_load_w = (row["home_consumption"] - row["solar_production"]) * 4000
            soc = row["soe_start"] / REPORTER_CAPACITY_KWH * 100
            delivered = inverter.battery_watts(_clock(row["period"]), soc, net_load_w)
            assert delivered == pytest.approx(max(0.0, net_load_w)), row["period"]

    def test_load_support_still_works_below_the_old_cut_off(
        self, reporter_manager: SolisModbusController, plan: tuple[list[str], list]
    ) -> None:
        # The reported fault: 46% SOC, 2,732 W imported, battery at 0 W.
        inverter = _synced(reporter_manager, *plan, current_period=59)

        assert inverter.battery_watts("15:00", 46.0, 2732.0) == 2732.0

    def test_idle_at_the_floor_uses_no_slot(
        self, reporter_manager: SolisModbusController, plan: tuple[list[str], list]
    ) -> None:
        _synced(reporter_manager, *plan, current_period=59)

        assert reporter_manager._discharge_periods == []


class TestHoldOutcome:
    def _hold_day(self, **plan_kwargs: Any) -> tuple[list[str], list]:
        intents = make_intents({18: "IDLE"}, default="LOAD_SUPPORT")
        period_data = [planned(soe_start=6.0) for _ in intents]
        for p in range(18 * 4, 19 * 4):
            period_data[p] = planned(soe_start=6.0, **plan_kwargs)
        return intents, period_data

    def test_deliberate_idle_keeps_the_battery_at_zero_watts(
        self, manager: SolisModbusController
    ) -> None:
        inverter = _synced(manager, *self._hold_day())

        assert inverter.battery_watts("18:15", 60.0, 2397.0) == 0.0

    def test_load_support_around_the_hold_still_follows_the_load(
        self, manager: SolisModbusController
    ) -> None:
        inverter = _synced(manager, *self._hold_day())

        assert inverter.battery_watts("17:45", 60.0, 2397.0) == 2397.0

    def test_idle_the_plan_would_release_is_not_held(
        self, manager: SolisModbusController
    ) -> None:
        # Same rule the forced-power platforms use (#786): a fall-through IDLE.
        inverter = _synced(
            manager, *self._hold_day(verdict_open=True, grid_imported=0.0)
        )

        assert inverter.battery_watts("18:15", 60.0, 2397.0) == 2397.0

    def test_idle_within_one_soc_point_of_the_floor_is_not_held(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents({18: "IDLE"}, default="LOAD_SUPPORT")
        # Floor is 1.5 kWh; 1% of the 10 kWh pack is the inverter's resolution.
        period_data = [planned(soe_start=1.55) for _ in intents]

        _synced(manager, intents, period_data)

        assert manager._discharge_periods == []

    def test_a_hold_that_has_finished_does_not_take_a_slot(
        self, manager: SolisModbusController
    ) -> None:
        inverter = _synced(manager, *self._hold_day(), current_period=20 * 4)

        assert manager._discharge_periods == []
        assert inverter.battery_watts("18:15", 60.0, 2397.0) == 2397.0


class TestExportOutcome:
    def _export(
        self, manager: SolisModbusController, soe_end: float = 4.04
    ) -> MeasuredSolisInverter:
        intents = make_intents({20: "BATTERY_EXPORT"}, default="LOAD_SUPPORT")
        period_data = [planned(soe_start=8.0) for _ in intents]
        # 0.5 kWh per quarter hour is 2 kW.
        for p in range(20 * 4, 21 * 4):
            period_data[p] = planned(
                soe_start=6.0, soe_end=soe_end, battery_discharged=0.5
            )
        return _synced(manager, intents, period_data)

    def test_export_runs_at_the_planned_power_not_the_stale_slot_current(
        self, manager: SolisModbusController
    ) -> None:
        inverter = self._export(manager)

        assert inverter.battery_watts("20:15", 60.0, 300.0) == pytest.approx(2000.0)

    def test_export_stops_at_the_planned_end_soc(
        self, manager: SolisModbusController
    ) -> None:
        inverter = self._export(manager, soe_end=4.04)
        expected_cutoff = math.ceil(40.4)

        assert inverter.battery_watts("20:15", expected_cutoff, 300.0) == 0.0
        assert inverter.battery_watts(
            "20:15", expected_cutoff + 1, 300.0
        ) == pytest.approx(2000.0)

    def test_export_never_runs_below_min_soc(
        self, manager: SolisModbusController
    ) -> None:
        inverter = self._export(manager, soe_end=0.5)

        assert inverter.battery_watts("20:15", 15.0, 300.0) == 0.0


class TestDischargeSlotAllocation:
    def test_exports_keep_their_slots_when_holds_overflow(
        self, manager: SolisModbusController
    ) -> None:
        # 6 single-period exports plus longer holds: 12 candidates for 6 slots.
        intents = ["LOAD_SUPPORT"] * 96
        for h in range(0, 12, 2):
            intents[h * 4] = "BATTERY_EXPORT"
        for h in range(12, 24, 2):
            for p in range(h * 4, (h + 1) * 4):
                intents[p] = "IDLE"
        period_data = [planned(soe_start=6.0, soe_end=5.5) for _ in intents]

        manager.apply_intents(make_schedule_mock(intents, period_data))

        assert len(manager._discharge_periods) == 6
        assert all(p["discharge_power_kw"] for p in manager._discharge_periods)

    def test_hold_and_export_side_by_side_are_separate_slots(
        self, manager: SolisModbusController
    ) -> None:
        intents = make_intents({18: "IDLE", 19: "BATTERY_EXPORT"}, "LOAD_SUPPORT")
        period_data = [planned(soe_start=6.0, soe_end=5.5) for _ in intents]

        manager.apply_intents(make_schedule_mock(intents, period_data))

        assert len(manager._discharge_periods) == 2


class TestLimitChangesReachTheInverter:
    def test_same_window_changing_from_hold_to_export_is_a_difference(
        self, manager: SolisModbusController
    ) -> None:
        period_data = [planned(soe_start=6.0, soe_end=5.5) for _ in range(96)]
        hold = make_intents({18: "IDLE"}, "LOAD_SUPPORT")
        export = make_intents({18: "BATTERY_EXPORT"}, "LOAD_SUPPORT")
        manager.apply_intents(make_schedule_mock(hold, period_data))

        differs, reason = manager.evaluate_intents(
            make_schedule_mock(export, period_data)
        )

        assert differs is True
        assert "limit" in reason.lower()

    def test_unchanged_plan_is_not_a_difference(
        self, manager: SolisModbusController
    ) -> None:
        period_data = [planned(soe_start=6.0, soe_end=5.5) for _ in range(96)]
        intents = make_intents({18: "IDLE"}, "LOAD_SUPPORT")
        manager.apply_intents(make_schedule_mock(intents, period_data))

        differs, _ = manager.evaluate_intents(make_schedule_mock(intents, period_data))

        assert differs is False

    def test_limits_read_back_at_startup_are_treated_as_unknown(
        self, manager: SolisModbusController
    ) -> None:
        # Times and enable bits can be read back; the limits are not, so a slot
        # found enabled at startup must be rewritten before it can be trusted.
        controller = MagicMock()
        controller.read_solis_periods.side_effect = lambda direction: (
            [{"slot": 1, "start_time": "18:00", "end_time": "18:59", "enabled": True}]
            if direction == "discharge"
            else []
        )
        manager.read_and_initialize_from_hardware(controller, current_hour=10)
        period_data = [planned(soe_start=6.0, soe_end=5.5) for _ in range(96)]
        intents = make_intents({18: "IDLE"}, "LOAD_SUPPORT")

        differs, _ = manager.evaluate_intents(make_schedule_mock(intents, period_data))

        assert differs is True


class TestUpgradedInstallWithoutLimitEntities:
    def test_slot_is_closed_rather_than_opened_with_stale_limits(
        self, manager: SolisModbusController
    ) -> None:
        # Command-level on purpose: the outcome here is that a slot whose limits
        # could not be set is never enabled, and the slot write is that outcome.
        controller = MagicMock()
        controller.set_solis_discharge_cutoff_soc.side_effect = ValueError("missing")
        intents = make_intents({18: "IDLE"}, "LOAD_SUPPORT")
        period_data = [planned(soe_start=6.0, soe_end=5.5) for _ in intents]
        manager.apply_intents(make_schedule_mock(intents, period_data))

        manager.sync_to_hardware(controller, 0)

        controller.write_solis_period.assert_any_call(
            "discharge", 1, "00:00", "00:00", False
        )
