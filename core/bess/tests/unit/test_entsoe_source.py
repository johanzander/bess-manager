"""
Test the EntsoeSource implementation.

Models the ENTSO-e Transparency Platform HA integration
(github.com/JaccoR/hass-entso-e). The integration's "Average electricity price"
sensor exposes ``prices_today`` / ``prices_tomorrow`` attributes, each a list of
``{"time": <iso>, "price": <float>}`` entries at hourly (24/day) or quarterly
(96/day) resolution.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from core.bess import time_utils
from core.bess.entsoe_source import EntsoeSource
from core.bess.exceptions import PriceDataUnavailableError, SystemConfigurationError

ENTITY = "sensor.belpex_h_average_electricity_price"


def _make_entries(target_date, count=24, base_value=0.08):
    """Build mock ENTSO-e {time, price} entries for a given date.

    Args:
        target_date: Date to create prices for
        count: Number of periods (24 = hourly, 96 = quarterly)
        base_value: Base price in EUR/kWh
    """
    interval_minutes = (24 * 60) // count
    entries = []
    for i in range(count):
        start = datetime.combine(target_date, datetime.min.time()) + timedelta(
            minutes=interval_minutes * i
        )
        entries.append({"time": start.isoformat(), "price": base_value + i * 0.001})
    return entries


def _make_controller(today_entries=None, tomorrow_entries=None):
    """Create a mock HA controller returning the given attribute lists."""
    controller = MagicMock()
    attributes = {}
    if today_entries is not None:
        attributes["prices_today"] = today_entries
    if tomorrow_entries is not None:
        attributes["prices_tomorrow"] = tomorrow_entries
    controller._api_request = MagicMock(return_value={"attributes": attributes})
    return controller


class TestEntsoeSourceProperties:
    def test_period_duration_is_quarterly(self):
        source = EntsoeSource(MagicMock(), ENTITY)
        assert source.period_duration_hours == 0.25

    def test_prices_are_not_final(self):
        """ENTSO-e returns VAT-exclusive spot prices — PriceManager adds markup/VAT."""
        source = EntsoeSource(MagicMock(), ENTITY)
        assert source.prices_are_final is False

    def test_no_separate_sell_prices(self):
        source = EntsoeSource(MagicMock(), ENTITY)
        assert source.get_sell_prices_for_date(time_utils.today()) is None


class TestEntsoeSourceExpansion:
    def test_hourly_expands_to_quarterly(self):
        today = time_utils.today()
        entries = _make_entries(today, count=24)
        source = EntsoeSource(_make_controller(today_entries=entries), ENTITY)

        prices = source.get_prices_for_date(today)

        assert len(prices) == time_utils.get_period_count(today)
        # Each hourly value duplicated 4x
        assert prices[0] == pytest.approx(entries[0]["price"])
        assert prices[1] == pytest.approx(entries[0]["price"])
        assert prices[3] == pytest.approx(entries[0]["price"])
        assert prices[4] == pytest.approx(entries[1]["price"])

    def test_quarterly_passthrough(self):
        today = time_utils.today()
        entries = _make_entries(today, count=96)
        source = EntsoeSource(_make_controller(today_entries=entries), ENTITY)

        prices = source.get_prices_for_date(today)

        assert len(prices) == 96
        assert prices[0] == pytest.approx(entries[0]["price"])
        assert prices[1] == pytest.approx(entries[1]["price"])

    def test_prices_returned_vat_exclusive_unchanged(self):
        """Raw prices pass through without VAT division (unlike Nordpool HACS)."""
        today = time_utils.today()
        entries = [
            {
                "time": datetime.combine(today, datetime.min.time()).isoformat(),
                "price": 0.12345,
            },
            *_make_entries(today, count=24)[1:],
        ]
        source = EntsoeSource(_make_controller(today_entries=entries), ENTITY)

        prices = source.get_prices_for_date(today)
        assert prices[0] == pytest.approx(0.12345)


class TestEntsoeSourceDateHandling:
    def test_tomorrow_uses_prices_tomorrow_attribute(self):
        today = time_utils.today()
        tomorrow = today + timedelta(days=1)
        controller = _make_controller(
            today_entries=_make_entries(today, base_value=0.05),
            tomorrow_entries=_make_entries(tomorrow, base_value=0.09),
        )
        source = EntsoeSource(controller, ENTITY)

        prices = source.get_prices_for_date(tomorrow)
        assert prices[0] == pytest.approx(0.09)

    def test_filters_entries_not_matching_target_date(self):
        """Stray entries for other dates are ignored."""
        today = time_utils.today()
        entries = _make_entries(today, count=24)
        # Append a bogus entry for yesterday — must be filtered out
        yesterday = today - timedelta(days=1)
        entries.append(
            {
                "time": datetime.combine(yesterday, datetime.min.time()).isoformat(),
                "price": 9.99,
            }
        )
        source = EntsoeSource(_make_controller(today_entries=entries), ENTITY)

        prices = source.get_prices_for_date(today)
        assert len(prices) == time_utils.get_period_count(today)
        assert 9.99 not in prices

    def test_rejects_dates_beyond_tomorrow(self):
        source = EntsoeSource(_make_controller(), ENTITY)
        with pytest.raises(SystemConfigurationError):
            source.get_prices_for_date(time_utils.today() + timedelta(days=3))


class TestEntsoeSourceFailures:
    def test_missing_entity_raises(self):
        source = EntsoeSource(_make_controller(), "")
        with pytest.raises(SystemConfigurationError):
            source.get_prices_for_date(time_utils.today())

    def test_missing_attribute_raises(self):
        # Controller returns attributes without prices_today
        source = EntsoeSource(_make_controller(today_entries=None), ENTITY)
        with pytest.raises(PriceDataUnavailableError):
            source.get_prices_for_date(time_utils.today())

    def test_empty_prices_for_date_raises(self):
        today = time_utils.today()
        # Only entries for tomorrow present under prices_today — none match today
        tomorrow = today + timedelta(days=1)
        source = EntsoeSource(
            _make_controller(today_entries=_make_entries(tomorrow)), ENTITY
        )
        with pytest.raises(PriceDataUnavailableError):
            source.get_prices_for_date(today)

    def test_non_divisible_count_raises(self):
        today = time_utils.today()
        # 23 entries does not divide evenly into 96 quarterly periods
        source = EntsoeSource(
            _make_controller(today_entries=_make_entries(today, count=24)[:23]), ENTITY
        )
        with pytest.raises(PriceDataUnavailableError):
            source.get_prices_for_date(today)

    def test_api_failure_raises(self):
        controller = MagicMock()
        controller._api_request = MagicMock(side_effect=RuntimeError("boom"))
        source = EntsoeSource(controller, ENTITY)
        with pytest.raises(PriceDataUnavailableError):
            source.get_prices_for_date(time_utils.today())


class TestEntsoeSourceHealthCheck:
    def test_health_ok(self):
        today = time_utils.today()
        source = EntsoeSource(
            _make_controller(today_entries=_make_entries(today)), ENTITY
        )
        result = source.perform_health_check()
        assert result["status"] == "OK"

    def test_health_error_on_missing_data(self):
        source = EntsoeSource(_make_controller(today_entries=None), ENTITY)
        result = source.perform_health_check()
        assert result["status"] == "ERROR"
