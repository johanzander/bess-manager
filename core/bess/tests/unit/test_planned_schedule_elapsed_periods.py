"""The Planned Schedule display must survive periods that have already elapsed (#847).

`BatterySystemManager._create_updated_schedule` builds `DPSchedule.period_data`
as a full-day list in which every period before the current optimization
period is a `None` placeholder (nothing was planned for it by this run).
`InverterController.get_period_settings` is called for every hour of the day by
`GET /api/inverter/schedule`, so on a mid-day run it reaches those placeholders
and `_planned_discharge_authorized` dereferenced `None`: the endpoint logged
`'NoneType' object has no attribute 'decision'` once per elapsed hour and
substituted fabricated IDLE rows.

**The schedule is built by the real `_create_updated_schedule`**, not by hand:
a hand-built list would not be `None`-padded the way production's is, and the
bug is exactly that padding. What is asserted is that the display answer is
produced at all and is the unchanged-behaviour answer (no discharge
authorisation) for a period the plan holds no decision for.
"""

from datetime import date
from unittest.mock import patch

from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.dp_schedule import DPSchedule
from core.bess.inverter_controller import InverterController
from core.bess.price_manager import MockSource
from core.bess.tests.conftest import MockHomeAssistantController, MockSensorCollector
from core.bess.time_utils import get_period_count

MID_DAY_PERIOD = 40  # 10:00 -- on every day length, incl. the DST ones


class _DSTAwareMockSource(MockSource):
    def get_prices_for_date(self, target_date: date) -> list:
        return self.test_prices[: get_period_count(target_date)]


@patch("core.bess.battery_system_manager.SensorCollector", MockSensorCollector)
def _mid_day_system_and_schedule() -> tuple[BatterySystemManager, DPSchedule]:
    """Run the real optimizer from mid-day and build the schedule the
    controller is handed in production."""
    controller = MockHomeAssistantController()
    controller.settings["battery_soc"] = 50
    system = BatterySystemManager(
        controller=controller,
        price_source=_DSTAwareMockSource([0.8] * 68 + [0.2] * 32),
        addon_options={"inverter": {"platform": "growatt_server_min"}},
    )
    system._price_manager.refresh_cache()

    prices, price_entries = system._get_price_data(prepare_next_day=False)
    assert prices is not None and price_entries is not None
    gathered = system._gather_optimization_data(
        period=MID_DAY_PERIOD,
        current_soc=50.0,
        prepare_next_day=False,
        period_count=len(prices),
    )
    assert gathered is not None
    optimization_period, optimization_data = gathered
    assert optimization_period == MID_DAY_PERIOD

    result = system._run_optimization(
        optimization_period, optimization_data, prices, price_entries, False
    )
    assert result is not None
    schedule = system._create_updated_schedule(
        optimization_period, result, prices, optimization_data, True, False
    )
    assert schedule is not None
    return system, schedule


def test_elapsed_periods_have_no_plan_decision_and_display_does_not_raise() -> None:
    system, schedule = _mid_day_system_and_schedule()
    inverter_controller = system._inverter_controller
    assert isinstance(inverter_controller, InverterController)
    inverter_controller.current_schedule = schedule
    inverter_controller.strategic_intents = schedule.strategic_intents

    # Precondition the bug depends on: the real schedule is None-padded for
    # every period before the run's optimization period.
    assert len(schedule.period_data) == get_period_count(time_utils.today())
    assert all(schedule.period_data[p] is None for p in range(MID_DAY_PERIOD))
    assert schedule.period_data[MID_DAY_PERIOD] is not None

    # The endpoint renders every hour of the day, elapsed or not.
    for period in range(len(schedule.period_data)):
        settings = inverter_controller.get_period_settings(period)
        assert settings["strategic_intent"] is not None

    # No plan decision -> no economic basis for releasing a hold (#526).
    for period in range(MID_DAY_PERIOD):
        assert inverter_controller._planned_discharge_authorized(period) is False
