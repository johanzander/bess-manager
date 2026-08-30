"""Tests for HA Statistics-based consumption forecast."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from core.bess.battery_system_manager import (
    BatterySystemManager,
    ha_statistics_quarterly_profile,
)
from core.bess.exceptions import HAStatisticsUnavailableError, ManagedLoadsError
from core.bess.runtime_failure_tracker import RuntimeFailureTracker
from core.bess.settings import BatterySettings, HomeSettings
from core.bess.tests.conftest import MockHomeAssistantController
from core.bess.time_utils import TIMEZONE


def _make_hourly_stats(hourly_kwh: list[float], days: int = 7) -> list[dict]:
    """Build mock HA statistics response with given hourly pattern repeated over days.

    Args:
        hourly_kwh: 24-element list of kWh values per hour-of-day.
        days: Number of days of history to generate.

    Returns:
        List of statistics entries as returned by recorder/statistics_during_period.
    """
    base_date = datetime(2026, 5, 5, 0, 0, tzinfo=TIMEZONE)
    entries = []
    for day in range(days):
        day_start = base_date + timedelta(days=day)
        for hour in range(24):
            start = day_start.replace(hour=hour)
            # Use millisecond epoch timestamps like real HA responses
            start_ms = int(start.timestamp() * 1000)
            end_ms = int(start.replace(minute=59, second=59).timestamp() * 1000)
            entries.append(
                {
                    "start": start_ms,
                    "end": end_ms,
                    "change": hourly_kwh[hour],
                }
            )
    return entries


def _create_manager_with_stats(
    controller: MockHomeAssistantController, stats_response: dict
) -> BatterySystemManager:
    """Create a BatterySystemManager wired to a mock controller with statistics data."""
    controller._statistics_response = stats_response
    controller.sensors = {
        "lifetime_load_consumption": "sensor.load_energy_total",
    }

    battery_settings = BatterySettings()
    home_settings = HomeSettings()
    home_settings.consumption_strategy = "ha_statistics"

    manager = BatterySystemManager.__new__(BatterySystemManager)
    manager._controller = controller
    manager.home_settings = home_settings
    manager.battery_settings = battery_settings
    manager._runtime_failure_tracker = RuntimeFailureTracker()

    return manager


class TestHAStatisticsForecastShape:
    """Verify the forecast captures intra-day consumption patterns."""

    def test_peak_hours_higher_than_overnight(self):
        """Evening peak should produce higher forecast values than overnight."""
        hourly_kwh = [0.5] * 24
        hourly_kwh[7] = 2.0  # morning peak
        hourly_kwh[8] = 2.5
        hourly_kwh[17] = 3.0  # evening peak
        hourly_kwh[18] = 4.0
        hourly_kwh[19] = 3.5

        stats = _make_hourly_stats(hourly_kwh)
        controller = MockHomeAssistantController()
        stat_id = "sensor.load_energy_total"
        manager = _create_manager_with_stats(controller, {stat_id: stats})

        with patch("core.bess.battery_system_manager.time_utils") as mock_tu:
            mock_tu.today.return_value = datetime(2026, 5, 12, tzinfo=TIMEZONE).date()
            mock_tu.TIMEZONE = TIMEZONE
            result = manager._get_ha_statistics_forecast()

        assert len(result) == 96

        # Period 72-75 = hour 18 (evening peak at 4.0 kWh/h)
        evening_quarter = result[72]
        # Period 8-11 = hour 2 (overnight at 0.5 kWh/h)
        overnight_quarter = result[8]
        assert evening_quarter > overnight_quarter * 3

    def test_total_daily_kwh_preserved(self):
        """Sum of 96 quarterly values should match expected daily total."""
        hourly_kwh = [1.0] * 24  # 24 kWh/day
        stats = _make_hourly_stats(hourly_kwh)
        controller = MockHomeAssistantController()
        stat_id = "sensor.load_energy_total"
        manager = _create_manager_with_stats(controller, {stat_id: stats})

        with patch("core.bess.battery_system_manager.time_utils") as mock_tu:
            mock_tu.today.return_value = datetime(2026, 5, 12, tzinfo=TIMEZONE).date()
            mock_tu.TIMEZONE = TIMEZONE
            result = manager._get_ha_statistics_forecast()

        assert abs(sum(result) - 24.0) < 0.01

    def test_quarter_hour_expansion_is_uniform_within_hour(self):
        """Each hour's kWh should be split evenly across its 4 quarter-hours."""
        hourly_kwh = [float(h) for h in range(24)]  # 0, 1, 2, ... 23
        stats = _make_hourly_stats(hourly_kwh)
        controller = MockHomeAssistantController()
        stat_id = "sensor.load_energy_total"
        manager = _create_manager_with_stats(controller, {stat_id: stats})

        with patch("core.bess.battery_system_manager.time_utils") as mock_tu:
            mock_tu.today.return_value = datetime(2026, 5, 12, tzinfo=TIMEZONE).date()
            mock_tu.TIMEZONE = TIMEZONE
            result = manager._get_ha_statistics_forecast()

        # Hour 10 (periods 40-43) should each be 10.0 / 4 = 2.5
        for period in range(40, 44):
            assert abs(result[period] - 2.5) < 0.001


class TestHAStatisticsPartialData:
    """Verify behavior with incomplete data."""

    def test_partial_days_still_produces_forecast(self):
        """3 of 7 days having data should still work."""
        hourly_kwh = [2.0] * 24
        stats = _make_hourly_stats(hourly_kwh, days=3)
        controller = MockHomeAssistantController()
        stat_id = "sensor.load_energy_total"
        manager = _create_manager_with_stats(controller, {stat_id: stats})

        with patch("core.bess.battery_system_manager.time_utils") as mock_tu:
            mock_tu.today.return_value = datetime(2026, 5, 12, tzinfo=TIMEZONE).date()
            mock_tu.TIMEZONE = TIMEZONE
            result = manager._get_ha_statistics_forecast()

        assert len(result) == 96
        assert abs(sum(result) - 48.0) < 0.01  # 2.0 * 24 = 48 kWh/day

    def test_no_data_raises_error(self):
        """Empty statistics should raise HAStatisticsUnavailableError."""
        controller = MockHomeAssistantController()
        stat_id = "sensor.load_energy_total"
        manager = _create_manager_with_stats(controller, {stat_id: []})

        with patch("core.bess.battery_system_manager.time_utils") as mock_tu:
            mock_tu.today.return_value = datetime(2026, 5, 12, tzinfo=TIMEZONE).date()
            mock_tu.TIMEZONE = TIMEZONE
            with pytest.raises(HAStatisticsUnavailableError):
                manager._get_ha_statistics_forecast()

    def test_empty_response_raises_error(self):
        """No matching statistic_id in response should raise."""
        controller = MockHomeAssistantController()
        manager = _create_manager_with_stats(controller, {})

        with patch("core.bess.battery_system_manager.time_utils") as mock_tu:
            mock_tu.today.return_value = datetime(2026, 5, 12, tzinfo=TIMEZONE).date()
            mock_tu.TIMEZONE = TIMEZONE
            with pytest.raises(HAStatisticsUnavailableError):
                manager._get_ha_statistics_forecast()

    def test_too_few_hours_raises_error(self):
        """Fewer than 12 hours with data should raise."""
        # Only provide data for hours 0-10 (11 hours)
        stats = []
        base_date = datetime(2026, 5, 5, 0, 0, tzinfo=TIMEZONE)
        for day in range(7):
            for hour in range(11):
                start = (base_date + timedelta(days=day)).replace(hour=hour)
                start_ms = int(start.timestamp() * 1000)
                stats.append(
                    {
                        "start": start_ms,
                        "end": start_ms,
                        "change": 1.0,
                    }
                )

        controller = MockHomeAssistantController()
        stat_id = "sensor.load_energy_total"
        manager = _create_manager_with_stats(controller, {stat_id: stats})

        with patch("core.bess.battery_system_manager.time_utils") as mock_tu:
            mock_tu.today.return_value = datetime(2026, 5, 12, tzinfo=TIMEZONE).date()
            mock_tu.TIMEZONE = TIMEZONE
            with pytest.raises(HAStatisticsUnavailableError, match="11/24 hours"):
                manager._get_ha_statistics_forecast()


class TestHAStatisticsTrimmedMean:
    """Verify outlier-robust trimmed mean averaging."""

    def test_ev_spike_filtered_out(self):
        """A single-day EV charging spike should be trimmed from the average."""
        # 7 days: 6 normal days at 1.0 kWh/h, 1 day with 10.0 kWh spike at hour 22
        base_date = datetime(2026, 5, 5, 0, 0, tzinfo=TIMEZONE)
        entries = []
        for day in range(7):
            day_start = base_date + timedelta(days=day)
            for hour in range(24):
                start = day_start.replace(hour=hour)
                start_ms = int(start.timestamp() * 1000)
                end_ms = int(start.replace(minute=59, second=59).timestamp() * 1000)
                # Spike on day 3, hour 22
                kwh = 10.0 if (day == 3 and hour == 22) else 1.0
                entries.append({"start": start_ms, "end": end_ms, "change": kwh})

        controller = MockHomeAssistantController()
        stat_id = "sensor.load_energy_total"
        manager = _create_manager_with_stats(controller, {stat_id: entries})

        with patch("core.bess.battery_system_manager.time_utils") as mock_tu:
            mock_tu.today.return_value = datetime(2026, 5, 12, tzinfo=TIMEZONE).date()
            mock_tu.TIMEZONE = TIMEZONE
            result = manager._get_ha_statistics_forecast()

        # Hour 22 = periods 88-91.  Without trimming: (6*1.0 + 10.0)/7 = 2.28
        # With trimming (drop min+max from 7 values): mean of [1,1,1,1,1] = 1.0
        hour_22_quarter = result[88]
        assert abs(hour_22_quarter - 0.25) < 0.01  # 1.0 kWh/h / 4 = 0.25 kWh/qh

    def test_uniform_data_unaffected_by_trimming(self):
        """Trimming identical values should produce the same result as plain mean."""
        hourly_kwh = [2.0] * 24
        stats = _make_hourly_stats(hourly_kwh)
        controller = MockHomeAssistantController()
        stat_id = "sensor.load_energy_total"
        manager = _create_manager_with_stats(controller, {stat_id: stats})

        with patch("core.bess.battery_system_manager.time_utils") as mock_tu:
            mock_tu.today.return_value = datetime(2026, 5, 12, tzinfo=TIMEZONE).date()
            mock_tu.TIMEZONE = TIMEZONE
            result = manager._get_ha_statistics_forecast()

        assert abs(sum(result) - 48.0) < 0.01  # 2.0 * 24 = 48 kWh/day


class TestHAStatisticsDispatch:
    """Verify the consumption strategy dispatch works."""

    def test_ha_statistics_strategy_dispatches_correctly(self):
        """consumption_strategy='ha_statistics' should use the HA statistics path."""
        hourly_kwh = [1.5] * 24
        stats = _make_hourly_stats(hourly_kwh)
        controller = MockHomeAssistantController()
        stat_id = "sensor.load_energy_total"
        manager = _create_manager_with_stats(controller, {stat_id: stats})

        with patch("core.bess.battery_system_manager.time_utils") as mock_tu:
            mock_tu.today.return_value = datetime(2026, 5, 12, tzinfo=TIMEZONE).date()
            mock_tu.TIMEZONE = TIMEZONE
            result = manager._get_consumption_forecast()

        assert len(result) == 96
        assert abs(sum(result) - 36.0) < 0.01  # 1.5 * 24 = 36 kWh/day

    def test_missing_sensor_config_raises(self):
        """Missing lifetime_load_consumption sensor should raise."""
        controller = MockHomeAssistantController()
        manager = _create_manager_with_stats(controller, {})
        controller.sensors = {}  # Clear sensor mappings

        with patch("core.bess.battery_system_manager.time_utils") as mock_tu:
            mock_tu.today.return_value = datetime(2026, 5, 12, tzinfo=TIMEZONE).date()
            mock_tu.TIMEZONE = TIMEZONE
            with pytest.raises(HAStatisticsUnavailableError):
                manager._get_ha_statistics_forecast()

    def test_missing_sensor_falls_back_from_dispatch(self):
        """Dispatch should fall back to fixed when sensor is not configured."""
        controller = MockHomeAssistantController()
        manager = _create_manager_with_stats(controller, {})
        controller.sensors = {}
        manager.home_settings.default_hourly = 3.0

        # Override mock to raise like the real controller does for missing sensors
        def strict_resolve(sensor_key):
            raise ValueError(f"No entity ID configured for sensor '{sensor_key}'")

        controller._resolve_entity_id = strict_resolve

        result = manager._get_consumption_forecast()
        assert len(result) == 96
        assert all(v == 3.0 / 4.0 for v in result)

    def test_fallback_to_fixed_on_insufficient_data(self):
        """Dispatch should fall back to fixed profile when data is insufficient."""
        # Only 11 hours of data — below the 12-hour minimum
        stats = []
        base_date = datetime(2026, 5, 5, 0, 0, tzinfo=TIMEZONE)
        for day in range(7):
            for hour in range(11):
                start = (base_date + timedelta(days=day)).replace(hour=hour)
                start_ms = int(start.timestamp() * 1000)
                stats.append({"start": start_ms, "end": start_ms, "change": 1.0})

        controller = MockHomeAssistantController()
        stat_id = "sensor.load_energy_total"
        manager = _create_manager_with_stats(controller, {stat_id: stats})
        manager.home_settings.default_hourly = 4.0

        with patch("core.bess.battery_system_manager.time_utils") as mock_tu:
            mock_tu.today.return_value = datetime(2026, 5, 12, tzinfo=TIMEZONE).date()
            mock_tu.TIMEZONE = TIMEZONE
            result = manager._get_consumption_forecast()

        assert len(result) == 96
        assert all(v == 4.0 / 4.0 for v in result)


class TestManagedLoadsSubtraction:
    """Issue #706: managed_load_sensors excludes a load from the baseline."""

    def test_forecast_reflects_residual_after_subtracting_managed_load(self) -> None:
        """A flat managed load subtracted from a flat base halves the forecast."""
        hourly_kwh = [2.0] * 24
        ev_hourly_kwh = [1.0] * 24

        base_stats = _make_hourly_stats(hourly_kwh)
        ev_stats = _make_hourly_stats(ev_hourly_kwh)

        controller = MockHomeAssistantController()
        stat_id = "sensor.load_energy_total"
        ev_stat_id = "sensor.ev_charger_energy_total"
        manager = _create_manager_with_stats(
            controller, {stat_id: base_stats, ev_stat_id: ev_stats}
        )
        manager.home_settings.managed_load_sensors = [ev_stat_id]

        with patch("core.bess.battery_system_manager.time_utils") as mock_tu:
            mock_tu.today.return_value = datetime(2026, 5, 12, tzinfo=TIMEZONE).date()
            mock_tu.TIMEZONE = TIMEZONE
            result = manager._get_ha_statistics_forecast()

        # 2.0 kWh/h base - 1.0 kWh/h EV = 1.0 kWh/h residual = 0.25 kWh/quarter
        assert len(result) == 96
        assert all(v == pytest.approx(0.25) for v in result)

    def test_no_managed_loads_leaves_forecast_unchanged(self) -> None:
        """Baseline behaviour is unaffected when managed_load_sensors is empty."""
        hourly_kwh = [2.0] * 24
        stats = _make_hourly_stats(hourly_kwh)
        controller = MockHomeAssistantController()
        stat_id = "sensor.load_energy_total"
        manager = _create_manager_with_stats(controller, {stat_id: stats})
        assert manager.home_settings.managed_load_sensors == []

        with patch("core.bess.battery_system_manager.time_utils") as mock_tu:
            mock_tu.today.return_value = datetime(2026, 5, 12, tzinfo=TIMEZONE).date()
            mock_tu.TIMEZONE = TIMEZONE
            result = manager._get_ha_statistics_forecast()

        assert all(v == pytest.approx(0.5) for v in result)

    def test_missing_managed_load_statistics_raises(self) -> None:
        """A configured managed-load sensor with no statistics data is a hard error,
        not a silent skip -- the residual would otherwise silently overstate load."""
        hourly_kwh = [2.0] * 24
        base_stats = _make_hourly_stats(hourly_kwh)

        controller = MockHomeAssistantController()
        stat_id = "sensor.load_energy_total"
        # No entry for the EV sensor's statistic_id in the mock response.
        manager = _create_manager_with_stats(controller, {stat_id: base_stats})
        manager.home_settings.managed_load_sensors = ["sensor.ev_charger_energy_total"]

        with patch("core.bess.battery_system_manager.time_utils") as mock_tu:
            mock_tu.today.return_value = datetime(2026, 5, 12, tzinfo=TIMEZONE).date()
            mock_tu.TIMEZONE = TIMEZONE
            with pytest.raises(ManagedLoadsError):
                manager._get_ha_statistics_forecast()


class TestQuarterlyProfileExtraction:
    """The pure statistics -> profile transform, shared with scripts/knee_oracle.py.

    It is module-level precisely so the oracle harness scores the forecast
    production really held rather than a second implementation of the trimming
    rule (#602/#687/#381). These pin the contract that harness depends on.
    """

    def test_returns_96_periods_and_counts_hours_with_data(self) -> None:
        stats = _make_hourly_stats([0.4] * 24)

        profile, hours_with_data = ha_statistics_quarterly_profile(stats, TIMEZONE)

        assert len(profile) == 96
        assert hours_with_data == 24
        assert profile == pytest.approx([0.1] * 96)

    def test_hours_without_samples_are_zero_and_uncounted(self) -> None:
        """A gap must be visible to the caller, not smoothed into a real value.

        The caller raises on too few hours; a zero that silently counted as
        data would let a mostly-empty window through as a valid profile.
        """
        all_stats = _make_hourly_stats([0.4] * 24)
        stats = [
            entry
            for entry in all_stats
            if datetime.fromtimestamp(entry["start"] / 1000, tz=TIMEZONE).hour < 10
        ]

        profile, hours_with_data = ha_statistics_quarterly_profile(stats, TIMEZONE)

        assert hours_with_data == 10
        assert profile[40:] == pytest.approx([0.0] * 56)

    def test_trimmed_mean_drops_min_and_max_at_seven_samples(self) -> None:
        """The behaviour that makes this a central estimate, not a reserve.

        Seven identical nights plus one spike: the spike is discarded. Correct
        for forecasting a day's cost, and the reason the terminal knee
        under-sizes an overnight reserve on a boiler night (#381).
        """
        stats = _make_hourly_stats([0.2] * 24, days=6)
        spike = _make_hourly_stats([0.9] * 24, days=1)
        for entry in spike:
            entry["start"] += 7 * 24 * 3600 * 1000

        profile, _ = ha_statistics_quarterly_profile(stats + spike, TIMEZONE)

        # mean of the middle five 0.2 samples -- the 0.9 never lands
        assert profile[0] == pytest.approx(0.05)

    def test_production_forecast_agrees_with_the_shared_transform(self) -> None:
        """The extraction must not have changed what production computes."""
        stats = _make_hourly_stats([0.1 * h for h in range(24)])
        expected, _ = ha_statistics_quarterly_profile(stats, TIMEZONE)

        controller = MockHomeAssistantController()
        stat_id = "sensor.load_energy_total"
        manager = _create_manager_with_stats(controller, {stat_id: stats})

        assert manager._get_ha_statistics_forecast() == pytest.approx(expected)
