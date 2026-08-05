"""New scheduler job: sample live power sensors every minute (#387).

Feeds PowerSampleBuffer so collect_energy_data's runtime branch can gap-fill
zero-delta cumulative-counter periods without an InfluxDB dependency.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

from apscheduler.events import EVENT_JOB_MISSED, JobExecutionEvent
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# Importing backend.app (as a dotted package path, distinct from the bare
# "app" module conftest.py stubs for api.py's benefit) runs its module-level
# `bess_controller = BESSController()` and `start_in_background()` calls.
# Those need a writable /data directory and a reachable HA Supervisor
# endpoint, neither of which exist in the test sandbox. Neutralize both for
# the duration of the import only, so the real BESSController class
# definition — including the real `_init_scheduler_jobs`, which is what
# these tests exercise — is unaffected.
with (
    patch("core.bess.settings_store.SettingsStore._write"),
    patch(
        "core.bess.ha_api_controller.HomeAssistantAPIController.get_ha_config",
        side_effect=RuntimeError("no HA connection in tests"),
    ),
):
    from backend.app import BESSController


def _make_controller_for_scheduler_test():
    controller = BESSController.__new__(BESSController)
    controller.system = MagicMock()
    controller.scheduler = BackgroundScheduler()
    return controller


class TestSchedulerJobs:
    def test_registers_a_per_minute_power_sampling_job(self):
        controller = _make_controller_for_scheduler_test()

        controller._init_scheduler_jobs()

        power_sampling_jobs = [
            job
            for job in controller.scheduler.get_jobs()
            if job.func == controller.system.sensor_collector.sample_live_power
        ]
        assert len(power_sampling_jobs) == 1
        trigger = power_sampling_jobs[0].trigger
        assert isinstance(trigger, CronTrigger)
        minute_field = next(f for f in trigger.fields if f.name == "minute")
        assert str(minute_field) == "*"

        controller.scheduler.shutdown(wait=False)


class TestQuarterlyMisfireVisibility:
    """Issue #403: a coalesced misfire of update_schedule_quarterly was
    silently dropped with no log line, permanently losing a period's
    actuals with no trace it ever happened."""

    def test_quarterly_job_has_a_stable_id(self):
        controller = _make_controller_for_scheduler_test()

        controller._init_scheduler_jobs()

        quarterly_jobs = [
            job
            for job in controller.scheduler.get_jobs()
            if job.id == "update_schedule_quarterly"
        ]
        assert len(quarterly_jobs) == 1

        controller.scheduler.shutdown(wait=False)

    def test_missed_quarterly_tick_is_recorded_and_logged(self):
        controller = _make_controller_for_scheduler_test()
        controller._init_scheduler_jobs()

        scheduled_run_time = datetime(2026, 7, 27, 0, 30)
        event = JobExecutionEvent(
            code=EVENT_JOB_MISSED,
            job_id="update_schedule_quarterly",
            jobstore="default",
            scheduled_run_time=scheduled_run_time,
        )

        with patch("backend.app.logger") as mock_logger:
            controller.scheduler._dispatch_event(event)
            mock_logger.warning.assert_called_once()

        controller.system.record_scheduler_misfire.assert_called_once_with(
            job_id="update_schedule_quarterly",
            scheduled_run_time=scheduled_run_time,
        )

        controller.scheduler.shutdown(wait=False)

    def test_missed_tick_of_a_different_job_is_ignored(self):
        controller = _make_controller_for_scheduler_test()
        controller._init_scheduler_jobs()

        event = JobExecutionEvent(
            code=EVENT_JOB_MISSED,
            job_id="prepare_next_day",
            jobstore="default",
            scheduled_run_time=datetime(2026, 7, 27, 23, 55),
        )

        controller.scheduler._dispatch_event(event)

        controller.system.record_scheduler_misfire.assert_not_called()

        controller.scheduler.shutdown(wait=False)
