"""ScheduleStore persisted strategic intents (restart recovery).

Regression for issue #380 (a second instance found during code review, in
the same file as the timestamp-lookup fix). _save_to_disk built the
period->intent map with the same positional arithmetic
(optimization_period + i) that caused the original bug: the standalone
prepare_next_day schedule (optimization_period=0, period_data[i].period
also 0..95 -- only its timestamp carries tomorrow's date) collided with
today's real schedule at the same positional indices, so every 23:55-00:00
save clobbered today's persisted intents with tomorrow's.
"""

from datetime import timedelta

from core.bess.models import (
    DecisionData,
    EconomicData,
    EnergyData,
    OptimizationResult,
    PeriodData,
)
from core.bess.schedule_store import ScheduleStore
from core.bess.time_utils import period_index_to_timestamp


def _period_data(period: int, timestamp, intent: str) -> PeriodData:
    return PeriodData(
        period=period,
        energy=EnergyData(
            solar_production=0.0,
            home_consumption=0.0,
            battery_charged=0.0,
            battery_discharged=0.0,
            grid_imported=0.0,
            grid_exported=0.0,
            battery_soe_start=10.0,
            battery_soe_end=10.0,
        ),
        timestamp=timestamp,
        economic=EconomicData(),
        decision=DecisionData(strategic_intent=intent),
    )


def test_next_day_schedule_does_not_clobber_todays_persisted_intents(tmp_path):
    persist_path = tmp_path / "intents.json"
    store = ScheduleStore(persist_path=persist_path)

    # Today's real schedule, made moments earlier: period 92-95 planned as
    # LOAD_SUPPORT.
    today_periods = [
        _period_data(92 + i, period_index_to_timestamp(92 + i), "LOAD_SUPPORT")
        for i in range(4)
    ]
    store.store_schedule(
        OptimizationResult(input_data={}, period_data=today_periods),
        optimization_period=92,
    )

    # The prepare_next_day schedule stored at 23:55: optimization_period=0,
    # period_data[i].period is also 0..95 (only timestamp carries tomorrow's
    # date) -- must not overwrite today's persisted period 95.
    tomorrow_start = period_index_to_timestamp(96)
    tomorrow_periods = [
        _period_data(i, tomorrow_start + timedelta(minutes=15 * i), "GRID_CHARGE")
        for i in range(96)
    ]
    store.store_schedule(
        OptimizationResult(input_data={}, period_data=tomorrow_periods),
        optimization_period=0,
    )

    # Simulate a restart: a fresh ScheduleStore reloading from the same file.
    reloaded = ScheduleStore(persist_path=persist_path)

    assert reloaded.get_persisted_intent(95) == "LOAD_SUPPORT"
