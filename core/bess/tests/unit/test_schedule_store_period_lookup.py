"""ScheduleStore.get_period_data_at: timestamp-based period lookup.

Positional arithmetic (period_index - optimization_period) silently breaks
whenever a stored schedule's period_data isn't anchored the way the caller
assumes -- e.g. the prepare_next_day schedule has optimization_period=0 but
period_data[0] is tomorrow 00:00, not today's. Every PeriodData already
carries its real timestamp, so resolving by timestamp instead removes the
anchor-assumption entirely. See issue #380.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core.bess.models import (
    DecisionData,
    EconomicData,
    EnergyData,
    OptimizationResult,
    PeriodData,
)
from core.bess.schedule_store import ScheduleStore

TIMEZONE = ZoneInfo("Europe/Stockholm")


def _period_data(period: int, timestamp: datetime, savings: float) -> PeriodData:
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
        economic=EconomicData(hourly_savings=savings),
        decision=DecisionData(),
    )


def test_returns_matching_period_by_timestamp():
    store = ScheduleStore()
    today = datetime.now(tz=TIMEZONE).date()
    ts = datetime.combine(today, datetime.min.time(), tzinfo=TIMEZONE) + timedelta(
        hours=14
    )
    periods = [_period_data(56, ts, savings=42.0)]
    store.store_schedule(
        OptimizationResult(input_data={}, period_data=periods), optimization_period=56
    )

    result = store.get_period_data_at(ts)

    assert result is not None
    assert result.economic.hourly_savings == 42.0


def test_returns_none_when_no_schedule_covers_timestamp():
    store = ScheduleStore()
    today = datetime.now(tz=TIMEZONE).date()
    ts = datetime.combine(today, datetime.min.time(), tzinfo=TIMEZONE)

    assert store.get_period_data_at(ts) is None


def test_next_day_only_schedule_does_not_shadow_todays_period():
    """Regression for issue #380.

    A standalone next-day-only schedule (optimization_period=0,
    period_data[0] timestamped tomorrow 00:00) must not be mistaken for
    today's period 95 just because positional index 95 exists in both.
    """
    store = ScheduleStore()
    today = datetime.now(tz=TIMEZONE).date()
    tomorrow = today + timedelta(days=1)

    today_2345 = datetime.combine(
        today, datetime.min.time(), tzinfo=TIMEZONE
    ) + timedelta(hours=23, minutes=45)
    tomorrow_2345 = datetime.combine(
        tomorrow, datetime.min.time(), tzinfo=TIMEZONE
    ) + timedelta(hours=23, minutes=45)

    # Normal schedule made earlier today, covering today's periods 92-95.
    today_periods = [
        _period_data(92 + i, today_2345 - timedelta(minutes=15 * (3 - i)), savings=10.0)
        for i in range(4)
    ]
    store.store_schedule(
        OptimizationResult(input_data={}, period_data=today_periods),
        optimization_period=92,
    )

    # Standalone next-day-only schedule made at 23:55, period_data[0] is
    # tomorrow 00:00 despite optimization_period=0.
    tomorrow_periods = [
        _period_data(95, tomorrow_2345, savings=999.0),
    ]
    store.store_schedule(
        OptimizationResult(input_data={}, period_data=tomorrow_periods),
        optimization_period=0,
    )

    result = store.get_period_data_at(today_2345)

    assert result is not None
    assert result.economic.hourly_savings == 10.0
