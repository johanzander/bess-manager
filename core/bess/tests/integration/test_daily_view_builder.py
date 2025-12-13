"""Integration tests for DailyViewBuilder.

Tests behavior: merging actual + predicted data at different times of day.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from core.bess.daily_view_builder import DailyView, DailyViewBuilder
from core.bess.historical_data_store import HistoricalDataStore
from core.bess.models import (
    DecisionData,
    EconomicData,
    EnergyData,
    OptimizationResult,
    PeriodData,
)
from core.bess.schedule_store import ScheduleStore
from core.bess.settings import BatterySettings

TIMEZONE = ZoneInfo("Europe/Stockholm")


@pytest.fixture
def battery_settings():
    """Battery settings for tests."""
    return BatterySettings(
        total_capacity=30.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        min_soc=10.0,
        max_soc=100.0,
    )


@pytest.fixture
def historical_store(battery_settings):
    """Historical store with some actual data."""
    store = HistoricalDataStore(battery_capacity_kwh=battery_settings.total_capacity)
    return store


@pytest.fixture
def schedule_store():
    """Schedule store for predicted data."""
    return ScheduleStore()


@pytest.fixture
def view_builder(historical_store, schedule_store, battery_settings):
    """ViewBuilder instance."""
    return DailyViewBuilder(historical_store, schedule_store, battery_settings)


def create_period_data(
    period_index: int, data_source: str = "predicted", savings: float = 10.0
) -> PeriodData:
    """Helper to create PeriodData for testing."""
    return PeriodData(
        period=period_index,
        energy=EnergyData(
            solar_production=1.0,
            home_consumption=0.5,
            battery_charged=0.0,
            battery_discharged=0.0,
            grid_imported=0.0,
            grid_exported=0.5,
            battery_soe_start=15.0,
            battery_soe_end=15.0,
        ),
        timestamp=datetime.now(tz=TIMEZONE),
        data_source=data_source,
        economic=EconomicData(
            buy_price=1.0,
            sell_price=0.5,
            hourly_savings=savings,
        ),
        decision=DecisionData(),
    )


def test_early_morning_all_predicted(view_builder, schedule_store):
    """Early morning (period 0): all data should be predicted."""
    # Create optimization result with 96 periods
    periods = [create_period_data(i, "predicted", savings=10.0) for i in range(96)]
    opt_result = OptimizationResult(
        input_data={},
        period_data=periods,
        economic_summary=None,
    )

    # Store schedule
    schedule_store.store_schedule(opt_result, optimization_period=0)

    # Build view at period 0 (midnight)
    view = view_builder.build_daily_view(current_period=0)

    # Behavior: At midnight, all periods are in the future → all predicted
    assert isinstance(view, DailyView)
    assert len(view.periods) == 96
    assert view.actual_count == 0
    assert view.predicted_count == 96
    assert all(p.data_source == "predicted" for p in view.periods)
    assert view.total_savings == 96 * 10.0  # 96 periods X 10 SEK


def test_midday_mix_actual_and_predicted(
    view_builder, historical_store, schedule_store
):
    """Midday (period 56): past = actual, future = predicted."""
    # Add actual data for periods 0-55 (past)
    for i in range(56):
        historical_store.record_period(
            i, create_period_data(i, "actual", savings=5.0)
        )

    # Create predicted data for all 96 periods
    periods = [create_period_data(i, "predicted", savings=10.0) for i in range(96)]
    opt_result = OptimizationResult(
        input_data={},
        period_data=periods,
        economic_summary=None,
    )
    schedule_store.store_schedule(opt_result, optimization_period=14)

    # Build view at period 56 (14:00)
    view = view_builder.build_daily_view(current_period=56)

    # Behavior: Past uses actual, future uses predicted
    assert len(view.periods) == 96
    assert view.actual_count == 56
    assert view.predicted_count == 40

    # First 56 should be actual (5 SEK each)
    assert all(p.data_source == "actual" for p in view.periods[:56])
    assert all(p.economic.hourly_savings == 5.0 for p in view.periods[:56])

    # Remaining 40 should be predicted (10 SEK each)
    assert all(p.data_source == "predicted" for p in view.periods[56:])
    assert all(p.economic.hourly_savings == 10.0 for p in view.periods[56:])

    # Total: 56*5 + 40*10 = 280 + 400 = 680
    assert view.total_savings == 680.0


def test_end_of_day_mostly_actual(view_builder, historical_store, schedule_store):
    """Late evening (period 92): most data is actual."""
    # Add actual data for periods 0-91
    for i in range(92):
        historical_store.record_period(
            i, create_period_data(i, "actual", savings=7.0)
        )

    # Create predicted data
    periods = [create_period_data(i, "predicted", savings=10.0) for i in range(96)]
    opt_result = OptimizationResult(
        input_data={},
        period_data=periods,
        economic_summary=None,
    )
    schedule_store.store_schedule(opt_result, optimization_period=23)

    # Build view at period 92 (23:00)
    view = view_builder.build_daily_view(current_period=92)

    # Behavior: Only last 4 periods are predicted
    assert len(view.periods) == 96
    assert view.actual_count == 92
    assert view.predicted_count == 4

    # Total: 92*7 + 4*10 = 644 + 40 = 684
    assert view.total_savings == 684.0


def test_missing_historical_data_uses_predicted(
    view_builder, historical_store, schedule_store
):
    """Behavior: If historical data missing, use predicted instead."""
    # Only add actual data for some periods (gaps in history)
    historical_store.record_period(0, create_period_data(0, "actual", savings=5.0))
    historical_store.record_period(10, create_period_data(10, "actual", savings=5.0))
    # Periods 1-9, 11-29 missing

    # Create predicted data
    periods = [create_period_data(i, "predicted", savings=10.0) for i in range(96)]
    opt_result = OptimizationResult(
        input_data={},
        period_data=periods,
        economic_summary=None,
    )
    schedule_store.store_schedule(opt_result, optimization_period=0)

    # Build view at period 30
    view = view_builder.build_daily_view(current_period=30)

    # Behavior: Missing past data falls back to predicted
    assert len(view.periods) == 96

    # Period 0 should be actual
    assert view.periods[0].data_source == "actual"
    assert view.periods[0].economic.hourly_savings == 5.0

    # Periods 1-9 should be predicted (missing actual)
    assert all(p.data_source == "predicted" for p in view.periods[1:10])

    # Period 10 should be actual
    assert view.periods[10].data_source == "actual"

    # Periods 11-29 should be predicted (missing actual)
    assert all(p.data_source == "predicted" for p in view.periods[11:30])

    # Periods 30+ should be predicted (future)
    assert all(p.data_source == "predicted" for p in view.periods[30:])


def test_no_schedule_raises_error(view_builder):
    """Behavior: If no schedule available, should raise error."""
    # Don't store any schedule

    with pytest.raises(ValueError, match="No optimization schedule available"):
        view_builder.build_daily_view(current_period=56)


def test_different_periods_throughout_day(
    view_builder, historical_store, schedule_store
):
    """Test actual/predicted split at different times of day."""
    # Add actual data for all past periods
    for i in range(96):
        historical_store.record_period(
            i, create_period_data(i, "actual", savings=5.0)
        )

    # Create predicted data
    periods = [create_period_data(i, "predicted", savings=10.0) for i in range(96)]
    opt_result = OptimizationResult(
        input_data={},
        period_data=periods,
        economic_summary=None,
    )
    schedule_store.store_schedule(opt_result, optimization_period=0)

    # Test at different periods
    test_periods = [0, 20, 40, 60, 80, 95]

    for current_period in test_periods:
        view = view_builder.build_daily_view(current_period=current_period)

        # Behavior: actual_count should equal current_period
        assert view.actual_count == current_period
        assert view.predicted_count == 96 - current_period
        assert len(view.periods) == 96


def test_economic_data_preserved(view_builder, historical_store, schedule_store):
    """Test that economic data is correctly preserved from sources."""
    # Create actual data with specific economic values
    actual_data = create_period_data(0, "actual", savings=123.45)
    actual_data.economic.buy_price = 2.5
    actual_data.economic.sell_price = 1.5
    historical_store.record_period(0, actual_data)

    # Create predicted data with different economic values
    predicted_data = create_period_data(1, "predicted", savings=67.89)
    predicted_data.economic.buy_price = 3.0
    predicted_data.economic.sell_price = 2.0

    periods = [predicted_data] * 96
    opt_result = OptimizationResult(
        input_data={},
        period_data=periods,
        economic_summary=None,
    )
    schedule_store.store_schedule(opt_result, optimization_period=0)

    # Build view at period 1
    view = view_builder.build_daily_view(current_period=1)

    # Behavior: Economic data should be preserved exactly
    assert view.periods[0].economic.hourly_savings == 123.45
    assert view.periods[0].economic.buy_price == 2.5
    assert view.periods[0].economic.sell_price == 1.5

    assert view.periods[1].economic.hourly_savings == 67.89
    assert view.periods[1].economic.buy_price == 3.0
    assert view.periods[1].economic.sell_price == 2.0
