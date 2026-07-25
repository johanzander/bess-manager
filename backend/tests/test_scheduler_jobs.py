"""New scheduler job: sample live power sensors every minute (#387).

Feeds PowerSampleBuffer so collect_energy_data's runtime branch can gap-fill
zero-delta cumulative-counter periods without an InfluxDB dependency.
"""

from unittest.mock import MagicMock, patch

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
