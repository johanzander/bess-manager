"""
Test the EntsoeSource implementation.

Models the ENTSO-e Transparency Platform HA integration
(github.com/JaccoR/hass-entso-e). The integration's "Average electricity price"
sensor exposes ``prices_today`` / ``prices_tomorrow`` attributes, each a list of
``{"time": <iso>, "price": <float>}`` entries at hourly (24/day) or quarterly
(96/day) resolution.
"""

from datetime import UTC, date, datetime, timedelta
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

    def test_all_zero_prices_treated_as_not_yet_available(self):
        """A full-length array of literal 0.0 prices is a placeholder/stub
        snapshot from the upstream integration, not a real day-ahead
        clearing — treat it as not-yet-available rather than caching it.
        """
        tomorrow = time_utils.today() + timedelta(days=1)
        entries = [
            {**entry, "price": 0.0} for entry in _make_entries(tomorrow, count=96)
        ]
        source = EntsoeSource(_make_controller(tomorrow_entries=entries), ENTITY)
        with pytest.raises(PriceDataUnavailableError):
            source.get_prices_for_date(tomorrow)

    def test_partially_zero_prices_are_accepted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Real markets do have occasional zero-price periods — only an
        entirely flat all-zero array should be rejected.
        """
        # Pinned: the real "tomorrow" can be a 92/100-period DST day, where 96
        # quarterly entries are (rightly) rejected.
        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 6, 9))
        tomorrow = date(2026, 6, 10)
        entries = _make_entries(tomorrow, count=96)
        entries[0]["price"] = 0.0
        source = EntsoeSource(_make_controller(tomorrow_entries=entries), ENTITY)
        prices = source.get_prices_for_date(tomorrow)
        assert prices[0] == pytest.approx(0.0)


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


class TestEntsoeSourceDstDays:
    """DST days are 92 or 100 quarterly periods (issue #830).

    The hass-entso-e sensor collapses the repeated fall-back hour by wall-clock
    time, so it hands over 24 hourly entries for the 25-hour day.
    """

    FALL_BACK = date(2026, 10, 25)  # 25 hours, 100 periods
    SPRING_FORWARD = date(2026, 3, 29)  # 23 hours, 92 periods

    @staticmethod
    def _hourly(target_date: date, count: int, base: float = 0.10) -> list[dict]:
        """``count`` consecutive hourly entries from local midnight, true offsets."""
        start = datetime.combine(
            target_date, datetime.min.time(), tzinfo=time_utils.TIMEZONE
        )
        return [
            {
                "time": (start.astimezone(UTC) + timedelta(hours=h))
                .astimezone(time_utils.TIMEZONE)
                .isoformat(),
                "price": base + h,
            }
            for h in range(count)
        ]

    @staticmethod
    def _collapsed_wall_hourly(target_date: date, base: float = 0.10) -> list[dict]:
        """What the sensor sends on the fall-back day: wall hours 00..23, all +02:00."""
        return [
            {
                "time": f"{target_date.isoformat()} {h:02d}:00:00+02:00",
                "price": base + h,
            }
            for h in range(24)
        ]

    def _source_for_tomorrow(
        self,
        monkeypatch: pytest.MonkeyPatch,
        target_date: date,
        entries: list[dict],
    ) -> EntsoeSource:
        monkeypatch.setattr(
            time_utils, "today", lambda: target_date - timedelta(days=1)
        )
        return EntsoeSource(_make_controller(tomorrow_entries=entries), ENTITY)

    def test_fall_back_day_with_collapsed_hour_fills_repeated_hour(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        entries = self._collapsed_wall_hourly(self.FALL_BACK)
        source = self._source_for_tomorrow(monkeypatch, self.FALL_BACK, entries)

        prices = source.get_prices_for_date(self.FALL_BACK)

        assert len(prices) == 100
        hourly = list(prices[::4])
        # Wall-clock hours 00,01,02,02(repeat),03..23: the repeated hour keeps
        # the 02:00 price, everything after it stays on its own hour.
        assert hourly == pytest.approx([0.10 + h for h in (0, 1, 2, 2, *range(3, 24))])
        assert "repeated" in caplog.text

    def test_fall_back_day_full_hourly_needs_no_fill(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        entries = self._hourly(self.FALL_BACK, 25)
        source = self._source_for_tomorrow(monkeypatch, self.FALL_BACK, entries)

        prices = source.get_prices_for_date(self.FALL_BACK)

        assert len(prices) == 100
        assert prices[::4] == pytest.approx([0.10 + h for h in range(25)])
        assert "repeated" not in caplog.text

    def test_fall_back_day_quarterly_passthrough(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        start = datetime.combine(
            self.FALL_BACK, datetime.min.time(), tzinfo=time_utils.TIMEZONE
        ).astimezone(UTC)
        entries = [
            {
                "time": (start + timedelta(minutes=15 * i))
                .astimezone(time_utils.TIMEZONE)
                .isoformat(),
                "price": 0.1 + i,
            }
            for i in range(100)
        ]
        source = self._source_for_tomorrow(monkeypatch, self.FALL_BACK, entries)

        prices = source.get_prices_for_date(self.FALL_BACK)

        assert prices == pytest.approx([0.1 + i for i in range(100)])

    def test_spring_forward_day_hourly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        entries = self._hourly(self.SPRING_FORWARD, 23)
        source = self._source_for_tomorrow(monkeypatch, self.SPRING_FORWARD, entries)

        prices = source.get_prices_for_date(self.SPRING_FORWARD)

        assert len(prices) == 92
        assert prices[::4] == pytest.approx([0.10 + h for h in range(23)])

    def test_fall_back_day_other_miscount_still_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entries = self._hourly(self.FALL_BACK, 23)
        source = self._source_for_tomorrow(monkeypatch, self.FALL_BACK, entries)

        with pytest.raises(PriceDataUnavailableError):
            source.get_prices_for_date(self.FALL_BACK)

    def test_price_manager_serves_collapsed_fall_back_day(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End to end: the sensor payload that broke tomorrow's prices in #830."""
        from core.bess.price_manager import PriceManager

        entries = self._collapsed_wall_hourly(self.FALL_BACK)
        source = self._source_for_tomorrow(monkeypatch, self.FALL_BACK, entries)
        manager = PriceManager(
            price_source=source,
            markup_rate=0.0,
            vat_multiplier=1.25,
            additional_costs=0.0,
            tax_reduction=0.0,
            area="BE",
        )

        data = manager.get_price_data(self.FALL_BACK)

        assert len(data) == 100
