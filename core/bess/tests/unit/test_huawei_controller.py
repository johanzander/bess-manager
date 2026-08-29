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
        controller.sync_to_hardware(ha, 0)
        ha.set_huawei_working_mode.assert_called_once_with("time_of_use_luna2000")

    def test_emma_time_of_use_mode_allows_schedule_write(
        self, controller: HuaweiController
    ) -> None:
        """Huawei EMMA exposes a localized 'Time Of Use' option instead of the
        stock 'time_of_use_luna2000' — it must be recognized as equivalent and
        written back verbatim."""
        intents = make_intents({18: "LOAD_SUPPORT"})
        controller.apply_intents(make_schedule_mock(intents))
        ha = MagicMock()
        ha.get_huawei_working_mode_options.return_value = [
            "Reserved 1",
            "Maximum Self Consumption",
            "Reserved 3",
            "Fully Fed To Grid",
            "Time Of Use",
            "Third Party Dispatch",
        ]
        ha.get_huawei_working_mode.return_value = "Maximum Self Consumption"

        controller.sync_to_hardware(ha, 0)

        ha.set_huawei_working_mode.assert_called_once_with("Time Of Use")
        ha.write_huawei_tou_periods.assert_called_once()

    def test_write_schedule_skips_mode_write_when_already_set(
        self, controller: HuaweiController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule_mock(intents))
        ha = MagicMock()
        ha.get_huawei_working_mode_options.return_value = []
        ha.get_huawei_working_mode.return_value = "time_of_use_luna2000"
        controller.sync_to_hardware(ha, 0)
        ha.set_huawei_working_mode.assert_not_called()

    def test_write_schedule_calls_write_tou_periods_with_joined_text(
        self, controller: HuaweiController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING", 18: "LOAD_SUPPORT"})
        controller.apply_intents(make_schedule_mock(intents))
        ha = MagicMock()
        ha.get_huawei_working_mode_options.return_value = []
        ha.get_huawei_working_mode.return_value = "time_of_use_luna2000"
        controller.sync_to_hardware(ha, 0)
        ha.write_huawei_tou_periods.assert_called_once()
        text = ha.write_huawei_tou_periods.call_args[0][0]
        assert "02:00-02:59/1234567/+" in text
        assert "18:00-18:59/1234567/-" in text

    def test_write_schedule_no_periods_clears_the_battery(
        self, controller: HuaweiController
    ) -> None:
        """An idle plan must clear periods the battery still holds.

        Skipping the write when the plan is empty would leave the old periods
        running — the empty string is how BESS says "no periods".
        """
        intents = make_intents({})
        controller.apply_intents(make_schedule_mock(intents))
        ha = MagicMock()
        ha.get_huawei_working_mode_options.return_value = []
        ha.get_huawei_working_mode.return_value = "time_of_use_luna2000"
        ha.read_huawei_tou_periods.return_value = ["02:00-02:59/1234567/+"]
        controller.sync_to_hardware(ha, 0)
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
            controller.sync_to_hardware(ha, 0)
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
        controller.sync_to_hardware(ha, 0)
        ha.write_huawei_tou_periods.assert_called_once()

    def test_write_schedule_enables_grid_charge_when_charge_period_present(
        self, controller: HuaweiController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule_mock(intents))
        ha = MagicMock()
        ha.get_huawei_working_mode_options.return_value = []
        ha.get_huawei_working_mode.return_value = "time_of_use_luna2000"
        controller.sync_to_hardware(ha, 0)
        ha.set_grid_charge.assert_called_once_with(True)

    def test_write_schedule_disables_grid_charge_when_no_charge_period(
        self, controller: HuaweiController
    ) -> None:
        intents = make_intents({18: "LOAD_SUPPORT"})
        controller.apply_intents(make_schedule_mock(intents))
        ha = MagicMock()
        ha.get_huawei_working_mode_options.return_value = []
        ha.get_huawei_working_mode.return_value = "time_of_use_luna2000"
        controller.sync_to_hardware(ha, 0)
        ha.set_grid_charge.assert_called_once_with(False)


class TestWorkingModeGateIsConditional:
    """Installs behind an energy manager (e.g. Huawei EMMA, PR #412) expose no
    LUNA2000 working-mode select. The gate must be skipped when the entity
    isn't mapped, rather than raising out of sync_to_hardware — but skipping
    it also skips the LG-RESU family check, so it is logged, not silent."""

    def test_write_proceeds_when_working_mode_entity_unmapped(
        self, controller: HuaweiController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule_mock(intents))
        ha = MagicMock()
        ha.is_sensor_configured.return_value = False
        controller.sync_to_hardware(ha, 0)
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
            controller.sync_to_hardware(ha, 0)
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
        controller.sync_to_hardware(ha, 0)
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


class FakeHuaweiInverter:
    """Execution model of a LUNA2000's TOU period list.

    Holds whatever BESS last wrote and reports it back in the huawei_solar
    sensor's attribute text format, so a restart can be replayed end to end:
    write → read back → decide whether to write again. Without this the tests
    could only pin the text BESS emits, which says nothing about whether a
    restart leaves the hardware alone.
    """

    def __init__(self, periods_text: str = "", tou_sensor_mapped: bool = True) -> None:
        self.periods_text = periods_text
        self.tou_sensor_mapped = tou_sensor_mapped
        self.write_count = 0

    def is_sensor_configured(self, sensor_key: str) -> bool:
        if sensor_key == "huawei_tou_periods":
            return self.tou_sensor_mapped
        return True

    def read_huawei_tou_periods(self) -> list[str]:
        if not self.tou_sensor_mapped:
            raise AssertionError("read attempted while the sensor is unmapped")
        return self.periods_text.splitlines() if self.periods_text else []

    def write_huawei_tou_periods(self, periods_text: str) -> None:
        self.periods_text = periods_text
        self.write_count += 1

    def get_huawei_working_mode(self) -> str:
        return "time_of_use_luna2000"

    def get_huawei_working_mode_options(self) -> list[str]:
        return ["maximise_self_consumption", "time_of_use_luna2000"]

    def set_huawei_working_mode(self, option: str) -> None:
        pass

    def set_grid_charge(self, enabled: bool) -> None:
        pass


def restart_against(
    inverter: FakeHuaweiInverter, battery_settings: BatterySettings
) -> HuaweiController:
    """A freshly constructed controller initialized from that inverter."""
    restarted = HuaweiController(battery_settings=battery_settings)
    restarted.read_and_initialize_from_hardware(inverter, current_hour=10)
    return restarted


def run_cycle(
    controller: HuaweiController, inverter: FakeHuaweiInverter, schedule: MagicMock
) -> bool:
    """One BESS decision cycle, as battery_system_manager drives it.

    evaluate_intents gates the write (_evaluate_schedule_application →
    _apply_schedule, battery_system_manager.py:2537/2585): no difference
    means the inverter is never touched. Returns whether it was written.
    """
    differs, _ = controller.evaluate_intents(schedule)
    if differs:
        controller.apply_intents(schedule)
        controller.sync_to_hardware(inverter, 0)
    return differs


class TestTouReadback:
    """Startup readback of the periods already programmed on the battery."""

    def test_restart_leaves_matching_hardware_untouched(
        self, controller: HuaweiController, battery_settings: BatterySettings
    ) -> None:
        """The point of the readback: no redundant rewrite after a restart.

        Every write is a flash-wear event on the battery, and until now BESS
        started blind and always rewrote the schedule it had just written.
        """
        intents = make_intents({2: "GRID_CHARGING", 18: "LOAD_SUPPORT"})
        inverter = FakeHuaweiInverter()
        controller.apply_intents(make_schedule_mock(intents))
        controller.sync_to_hardware(inverter, 0)
        assert inverter.write_count == 1

        restarted = restart_against(inverter, battery_settings)
        wrote = run_cycle(restarted, inverter, make_schedule_mock(intents))

        assert wrote is False
        assert inverter.write_count == 1

    def test_restart_rewrites_when_the_plan_has_moved_on(
        self, battery_settings: BatterySettings
    ) -> None:
        inverter = FakeHuaweiInverter("02:00-02:59/1234567/+")
        restarted = restart_against(inverter, battery_settings)

        new_plan = make_intents({18: "BATTERY_EXPORT"})
        wrote = run_cycle(restarted, inverter, make_schedule_mock(new_plan))

        assert wrote is True
        assert inverter.periods_text == "18:00-18:59/1234567/-"

    def test_period_limited_to_some_weekdays_is_not_a_match(
        self, battery_settings: BatterySettings
    ) -> None:
        """BESS only ever writes all-days periods.

        A period programmed elsewhere for Mon-Fri covers the same clock times
        but not the same days, so BESS's own all-days period is still missing
        from the battery — treating it as a match would suppress a write that
        is genuinely needed.
        """
        inverter = FakeHuaweiInverter("02:00-02:59/12345/+")
        restarted = restart_against(inverter, battery_settings)

        wrote = run_cycle(
            restarted, inverter, make_schedule_mock(make_intents({2: "GRID_CHARGING"}))
        )

        assert wrote is True
        assert inverter.periods_text == "02:00-02:59/1234567/+"

    def test_unmapped_sensor_keeps_the_previous_blind_start(
        self, battery_settings: BatterySettings
    ) -> None:
        """Readback is opt-in by configuration, never probed for.

        Installs whose integration exposes no TOU period entity (EMMA behind
        its own bridge) keep the documented pre-#431 behaviour: start with an
        empty schedule and let the first cycle converge.
        """
        inverter = FakeHuaweiInverter("02:00-02:59/1234567/+", tou_sensor_mapped=False)
        restarted = restart_against(inverter, battery_settings)

        assert restarted._periods == []
        wrote = run_cycle(
            restarted, inverter, make_schedule_mock(make_intents({2: "GRID_CHARGING"}))
        )
        assert wrote is True

    def test_readback_survives_a_second_restart(
        self, battery_settings: BatterySettings
    ) -> None:
        """Periods parsed from hardware must round-trip back out unchanged.

        A parse that dropped or reshaped a field would only show up when the
        read-back state is written out again.
        """
        inverter = FakeHuaweiInverter()
        first = HuaweiController(battery_settings=battery_settings)
        intents = make_intents({2: "GRID_CHARGING", 18: "LOAD_SUPPORT"})
        first.apply_intents(make_schedule_mock(intents))
        first.sync_to_hardware(inverter, 0)
        text_after_first = inverter.periods_text

        second = restart_against(inverter, battery_settings)
        second.sync_to_hardware(inverter, 0)

        assert inverter.periods_text == text_after_first

    def test_unparseable_period_text_raises(
        self, battery_settings: BatterySettings
    ) -> None:
        """No silent skip: a period BESS can't read is not a period it may
        pretend isn't there — that would suppress a needed write."""
        inverter = FakeHuaweiInverter("02:00-02:59/1234567")
        with pytest.raises(ValueError):
            restart_against(inverter, battery_settings)

    def test_write_is_skipped_when_the_battery_already_holds_the_plan(
        self, battery_settings: BatterySettings
    ) -> None:
        """The read-compare-write guard, same shape as Growatt MIN (#551/#552).

        Not every write goes through the evaluate_intents gate — a retry of a
        failed write, the corruption flag and the 23:55 next-day preparation
        all call sync_to_hardware directly. Each one is a flash-wear event on
        a battery that may already hold exactly these periods.
        """
        inverter = FakeHuaweiInverter()
        controller = HuaweiController(battery_settings=battery_settings)
        schedule = make_schedule_mock(make_intents({2: "GRID_CHARGING"}))

        controller.apply_intents(schedule)
        controller.sync_to_hardware(inverter, 0)
        assert inverter.write_count == 1

        controller.apply_intents(schedule)
        controller.sync_to_hardware(inverter, 0)

        assert inverter.write_count == 1

    def test_periods_changed_behind_bess_are_rewritten(
        self, battery_settings: BatterySettings
    ) -> None:
        """Skipping is decided against hardware, never against the model."""
        inverter = FakeHuaweiInverter()
        controller = HuaweiController(battery_settings=battery_settings)
        schedule = make_schedule_mock(make_intents({2: "GRID_CHARGING"}))

        controller.apply_intents(schedule)
        controller.sync_to_hardware(inverter, 0)
        inverter.periods_text = "07:00-07:59/1234567/-"

        controller.sync_to_hardware(inverter, 0)

        assert inverter.write_count == 2
        assert inverter.periods_text == "02:00-02:59/1234567/+"

    def test_unmapped_sensor_still_writes_every_cycle(
        self, battery_settings: BatterySettings
    ) -> None:
        """No readback, no comparison — the blind rewrite is all BESS has."""
        inverter = FakeHuaweiInverter(tou_sensor_mapped=False)
        controller = HuaweiController(battery_settings=battery_settings)
        schedule = make_schedule_mock(make_intents({2: "GRID_CHARGING"}))

        controller.apply_intents(schedule)
        controller.sync_to_hardware(inverter, 0)
        controller.sync_to_hardware(inverter, 0)

        assert inverter.write_count == 2

    def test_failed_read_leaves_the_battery_untouched(
        self, battery_settings: BatterySettings
    ) -> None:
        """An unreadable sensor aborts the cycle before anything is written.

        The read raises rather than reporting "no periods programmed", so the
        only question is what it leaves behind. Reading after set_grid_charge
        would arm grid charging against the period list from the previous
        plan and leave it that way until the next cycle's retry.
        """

        class UnreadableInverter(FakeHuaweiInverter):
            def __init__(self) -> None:
                super().__init__()
                self.grid_charge_calls: list[bool] = []

            def read_huawei_tou_periods(self) -> list[str]:
                raise SystemConfigurationError("TOU period entity unavailable")

            def set_grid_charge(self, enabled: bool) -> None:
                self.grid_charge_calls.append(enabled)

        inverter = UnreadableInverter()
        controller = HuaweiController(battery_settings=battery_settings)
        controller.apply_intents(make_schedule_mock(make_intents({2: "GRID_CHARGING"})))

        with pytest.raises(SystemConfigurationError):
            controller.sync_to_hardware(inverter, 0)

        assert inverter.grid_charge_calls == []
        assert inverter.write_count == 0

    def test_read_periods_are_shown_as_the_existing_schedule(
        self, battery_settings: BatterySettings
    ) -> None:
        """Read-back periods carry no intent — BESS didn't plan them."""
        inverter = FakeHuaweiInverter("02:00-02:59/1234567/+")
        restarted = restart_against(inverter, battery_settings)
        intervals = restarted.get_daily_TOU_settings()
        assert len(intervals) == 1
        assert intervals[0]["start_time"] == "02:00"
        assert intervals[0]["strategic_intent"] == "existing_schedule"


class TestWorkingModeAbsenceSeverity:
    """An unmapped working-mode entity means two different things.

    On an install driving a compatible integration under its own service
    domain (EMMA behind huawei_emma_management), the energy manager owns the
    mode and its absence is the expected shape. On a stock huawei_solar
    install it is a misconfiguration: BESS would write TOU periods the
    battery never acts on, because nothing puts it into time_of_use_luna2000.

    The configured service domain is what separates the two — declared
    configuration, not a probe of the hardware.
    """

    def test_stock_huawei_solar_install_reports_error(
        self, controller: HuaweiController
    ) -> None:
        ha = MagicMock()
        ha.is_sensor_configured.return_value = False
        ha.service_domain = "huawei_solar"
        result = controller.check_health(ha)
        assert result[0]["status"] == "ERROR"

    def test_custom_service_domain_install_reports_warning(
        self, controller: HuaweiController
    ) -> None:
        ha = MagicMock()
        ha.is_sensor_configured.return_value = False
        ha.service_domain = "huawei_emma_management"
        result = controller.check_health(ha)
        assert result[0]["status"] == "WARNING"
