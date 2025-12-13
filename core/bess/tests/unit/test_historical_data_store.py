"""Tests for HistoricalDataStore."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from core.bess.historical_data_store import HistoricalDataStore
from core.bess.models import DecisionData, EnergyData, PeriodData

TIMEZONE = ZoneInfo("Europe/Stockholm")


@pytest.fixture
def store():
    """Create a fresh HistoricalDataStore for testing."""
    return HistoricalDataStore(battery_capacity_kwh=30.0)


@pytest.fixture
def sample_period_data():
    """Create sample PeriodData for testing."""
    return PeriodData(
        period=0,  # Backward compat field
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
        data_source="actual",
        decision=DecisionData(),
    )


def test_store_and_retrieve_period(store, sample_period_data):
    """Should store and retrieve period data."""
    # Store period 0 (today 00:00)
    store.record_period(0, sample_period_data)

    # Retrieve it
    retrieved = store.get_period(0)

    assert retrieved is not None
    assert retrieved.energy.solar_production == 1.0
    assert retrieved.data_source == "actual"


def test_get_missing_period_returns_none(store):
    """Should return None for missing periods."""
    assert store.get_period(50) is None


def test_get_today_periods_all_none_when_empty(store):
    """Should return list of None when no data stored."""
    periods = store.get_today_periods()

    assert len(periods) == 96  # Normal day
    assert all(p is None for p in periods)


def test_get_today_periods_with_partial_data(store, sample_period_data):
    """Should return mixed list with some data, some None."""
    # Store data for periods 0, 50, 95
    store.record_period(0, sample_period_data)
    store.record_period(50, sample_period_data)
    store.record_period(95, sample_period_data)

    periods = store.get_today_periods()

    assert len(periods) == 96
    assert periods[0] is not None
    assert periods[1] is None  # Not stored
    assert periods[50] is not None
    assert periods[95] is not None


def test_record_period_validates_range(store, sample_period_data):
    """Should reject period indices outside today's range."""
    # Period 96 is tomorrow, not allowed
    with pytest.raises(ValueError, match="out of range"):
        store.record_period(96, sample_period_data)

    # Negative period not allowed
    with pytest.raises(ValueError, match="out of range"):
        store.record_period(-1, sample_period_data)


def test_clear_removes_all_data(store, sample_period_data):
    """Should clear all stored data."""
    # Store some data
    store.record_period(0, sample_period_data)
    store.record_period(50, sample_period_data)

    assert store.get_stored_count() == 2

    # Clear
    store.clear()

    assert store.get_stored_count() == 0
    assert store.get_period(0) is None
    assert store.get_period(50) is None


def test_get_stored_count(store, sample_period_data):
    """Should return correct count of stored periods."""
    assert store.get_stored_count() == 0

    store.record_period(0, sample_period_data)
    assert store.get_stored_count() == 1

    store.record_period(50, sample_period_data)
    assert store.get_stored_count() == 2

    # Overwriting same period doesn't increase count
    store.record_period(0, sample_period_data)
    assert store.get_stored_count() == 2


def test_total_capacity_stored(store):
    """Should store battery capacity."""
    assert store.total_capacity == 30.0


def test_custom_battery_capacity():
    """Should accept custom battery capacity."""
    store = HistoricalDataStore(battery_capacity_kwh=50.0)
    assert store.total_capacity == 50.0
