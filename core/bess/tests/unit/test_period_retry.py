"""Tests for period-level hardware write retry logic."""

from unittest.mock import MagicMock

from core.bess.battery_system_manager import BatterySystemManager


def _make_bsm_with_mocks():
    """Create a minimal BSM with mocked dependencies for retry testing."""
    bsm = BatterySystemManager.__new__(BatterySystemManager)
    bsm._inverter_controller = MagicMock()
    bsm._controller = MagicMock()
    bsm._runtime_failure_tracker = MagicMock()
    bsm._scheduler = MagicMock()
    bsm._last_applied_discharge_rate = 0
    return bsm


class TestSchedulePeriodRetry:
    """Test _schedule_period_retry scheduling and callback behaviour."""

    def test_schedules_job_on_first_attempt(self):
        bsm = _make_bsm_with_mocks()
        bsm._schedule_period_retry(68, True, 50)

        bsm._scheduler.add_job.assert_called_once()
        _args, kwargs = bsm._scheduler.add_job.call_args
        assert kwargs["misfire_grace_time"] == 60

    def test_skipped_when_no_scheduler(self):
        bsm = _make_bsm_with_mocks()
        bsm._scheduler = None
        # Should not raise
        bsm._schedule_period_retry(68, True, 50)

    def test_retry_callback_success_dismisses_banner(self):
        bsm = _make_bsm_with_mocks()
        bsm._inverter_controller.apply_period.return_value = (True, "")

        bsm._schedule_period_retry(68, True, 50)
        # Extract and call the retry callback
        callback = bsm._scheduler.add_job.call_args[0][0]
        callback()

        bsm._runtime_failure_tracker.dismiss_by_category.assert_called_with(
            "period_apply"
        )
        # No new failure recorded on success
        bsm._runtime_failure_tracker.record_failure.assert_not_called()
        assert bsm._last_applied_discharge_rate == 50

    def test_retry_callback_failure_schedules_second_retry(self):
        bsm = _make_bsm_with_mocks()
        bsm._inverter_controller.apply_period.return_value = (
            False,
            "timeout",
        )

        bsm._schedule_period_retry(68, True, 50, attempt=1)
        # First retry callback
        callback_1 = bsm._scheduler.add_job.call_args_list[0][0][0]
        callback_1()

        # Should have scheduled a second job (attempt=2)
        assert bsm._scheduler.add_job.call_count == 2
        # Banner should mention retry
        failure_call = bsm._runtime_failure_tracker.record_failure.call_args
        assert "Retry 1 failed" in failure_call[1]["operation"]

    def test_final_retry_failure_records_permanent_banner(self):
        bsm = _make_bsm_with_mocks()
        bsm._inverter_controller.apply_period.return_value = (
            False,
            "timeout",
        )

        bsm._schedule_period_retry(68, True, 50, attempt=2)
        callback = bsm._scheduler.add_job.call_args[0][0]
        callback()

        # No further retry scheduled
        assert bsm._scheduler.add_job.call_count == 1
        failure_call = bsm._runtime_failure_tracker.record_failure.call_args
        assert "after 3 attempts" in failure_call[1]["operation"]

    def test_does_not_set_discharge_rate_on_failure(self):
        bsm = _make_bsm_with_mocks()
        bsm._inverter_controller.apply_period.return_value = (
            False,
            "timeout",
        )
        bsm._last_applied_discharge_rate = 0

        bsm._schedule_period_retry(68, True, 50, attempt=2)
        callback = bsm._scheduler.add_job.call_args[0][0]
        callback()

        assert bsm._last_applied_discharge_rate == 0

    def test_attempt_beyond_max_is_noop(self):
        bsm = _make_bsm_with_mocks()
        bsm._schedule_period_retry(68, True, 50, attempt=3)
        bsm._scheduler.add_job.assert_not_called()


class TestApplyPeriodScheduleRetry:
    """Test _apply_period_schedule failure → retry integration."""

    def test_failure_triggers_retry_and_banner(self):
        bsm = _make_bsm_with_mocks()
        bsm._inverter_controller.apply_period.return_value = (
            False,
            "HA supervisor timeout",
        )
        bsm._inverter_controller.strategic_intents = ["DISCHARGE"] * 96
        bsm._inverter_controller.current_schedule = None
        bsm._inverter_controller.compute_rates_for_period.return_value = (
            False,
            80,
        )
        bsm._desired_discharge_rate = 0
        bsm.adjust_charging_power = MagicMock()
        bsm._controller.get_discharge_inhibit_active.return_value = False

        bsm._apply_period_schedule(68)

        # Banner was posted
        bsm._runtime_failure_tracker.record_failure.assert_called_once()
        rec_call = bsm._runtime_failure_tracker.record_failure.call_args
        assert "HA supervisor timeout" in str(rec_call[1]["error"])
        assert "retrying in 3 min" in rec_call[1]["operation"]

        # Retry job scheduled
        bsm._scheduler.add_job.assert_called_once()

        # Discharge rate NOT updated on failure
        assert bsm._last_applied_discharge_rate == 0

    def test_success_sets_discharge_rate(self):
        bsm = _make_bsm_with_mocks()
        bsm._inverter_controller.apply_period.return_value = (True, "")
        bsm._inverter_controller.strategic_intents = ["DISCHARGE"] * 96
        bsm._inverter_controller.current_schedule = None
        bsm._inverter_controller.compute_rates_for_period.return_value = (
            False,
            80,
        )
        bsm._desired_discharge_rate = 0
        bsm.adjust_charging_power = MagicMock()
        bsm._controller.get_discharge_inhibit_active.return_value = False

        bsm._apply_period_schedule(68)

        assert bsm._last_applied_discharge_rate == 80
        bsm._scheduler.add_job.assert_not_called()
