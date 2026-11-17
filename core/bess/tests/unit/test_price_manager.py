"""
Test the PriceManager implementation.
"""

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from core.bess import time_utils
from core.bess.calendar_windows import CalendarWindow
from core.bess.exceptions import PriceDataUnavailableError
from core.bess.price_manager import (
    HomeAssistantSource,
    MockSource,
    PriceManager,
    PriceSource,
)


def test_direct_price_initialization() -> None:
    """Test initialization with direct prices."""
    mock_source = MockSource([1.0, 2.0, 3.0, 4.0])
    pm = PriceManager(
        price_source=mock_source,
        markup_rate=0.1,
        vat_multiplier=1.25,
        additional_costs=0.5,
        tax_reduction=0.2,
        area="SE4",
    )

    # Check calculations with the updated formula:
    # - Base price is now VAT-exclusive
    # - Apply markup, then apply VAT, and add costs
    expected_buy_price = (1.0 + 0.1) * 1.25 + 0.5
    assert pm.buy_prices[0] == expected_buy_price

    # For sell price: add tax reduction to base price (VAT-exclusive)
    expected_sell_price = 1.0 + 0.2
    assert pm.sell_prices[0] == expected_sell_price

    # Check compatibility methods
    assert pm.get_buy_prices() == pm.buy_prices
    assert pm.get_sell_prices() == pm.sell_prices


def test_spot_multiplier_applied_to_buy_price() -> None:
    """Multiplicative spot adjustment must apply before markup/VAT (Luminus-style contracts)."""
    mock_source = MockSource([1.0])
    pm = PriceManager(
        price_source=mock_source,
        markup_rate=0.198,
        vat_multiplier=1.06,
        additional_costs=0.0,
        tax_reduction=-0.012685,
        area="EUR",
        spot_multiplier=1.0175,
        export_spot_multiplier=1.018,
    )

    expected_buy_price = (1.0 * 1.0175 + 0.198) * 1.06
    assert pm.buy_prices[0] == expected_buy_price

    expected_sell_price = 1.0 * 1.018 + (-0.012685)
    assert pm.sell_prices[0] == expected_sell_price


def test_spot_multiplier_defaults_to_no_adjustment() -> None:
    """Omitting spot_multiplier/export_spot_multiplier must reproduce the additive-only formula."""
    mock_source = MockSource([1.0])
    pm = PriceManager(
        price_source=mock_source,
        markup_rate=0.1,
        vat_multiplier=1.25,
        additional_costs=0.5,
        tax_reduction=0.2,
        area="SE4",
    )

    assert pm.buy_prices[0] == (1.0 + 0.1) * 1.25 + 0.5
    assert pm.sell_prices[0] == 1.0 + 0.2


def test_controller_price_fetching() -> None:
    """Test price fetching from controller."""
    mock_controller = MagicMock()

    today_date = time_utils.today()
    tomorrow_date = today_date + timedelta(days=1)

    # Create 96 quarterly periods of test data (Nordpool provides quarterly)
    raw_today_data = [
        {
            "start": f"{today_date.isoformat()}T{h:02d}:{m:02d}:00+01:00",
            "value": float(h + 1),  # Same price for all quarters in each hour
        }
        for h in range(24)
        for m in [0, 15, 30, 45]
    ]
    raw_tomorrow_data = [
        {
            "start": f"{tomorrow_date.isoformat()}T{h:02d}:{m:02d}:00+01:00",
            "value": float(h + 25),  # Same price for all quarters in each hour
        }
        for h in range(24)
        for m in [0, 15, 30, 45]
    ]

    def mock_api_request(method: str, path: str) -> dict | None:
        if "sensor.nordpool_kwh_se4_sek_2_10_025" in path:
            # Return both today and tomorrow data for the same entity
            return {
                "attributes": {
                    "raw_today": raw_today_data,
                    "raw_tomorrow": raw_tomorrow_data,
                }
            }
        return None

    mock_controller._api_request = mock_api_request

    ha_source = HomeAssistantSource(
        mock_controller,
        entity="sensor.nordpool_kwh_se4_sek_2_10_025",
    )
    pm = PriceManager(
        price_source=ha_source,
        markup_rate=0.1,
        vat_multiplier=1.25,
        additional_costs=0.5,
        tax_reduction=0.2,
        area="SE4",
    )

    # Get today's prices (quarterly - 96 periods)
    today_prices = pm.get_today_prices()
    assert len(today_prices) == 96
    # PriceManager strips VAT from the VAT-inclusive HomeAssistantSource prices
    assert today_prices[0]["price"] == 1.0 / 1.25

    # Check calculations with the updated formula:
    base_price = 1.0 / 1.25  # Price after VAT removal in PriceManager
    expected_buy_price = (base_price + 0.1) * 1.25 + 0.5
    assert today_prices[0]["buyPrice"] == expected_buy_price

    # For sell price: add tax reduction to base price (VAT-exclusive)
    expected_sell_price = base_price + 0.2
    assert today_prices[0]["sellPrice"] == expected_sell_price

    # Get tomorrow's prices (quarterly - 96 periods)
    tomorrow_prices = pm.get_tomorrow_prices()
    assert len(tomorrow_prices) == 96
    # PriceManager strips VAT from the VAT-inclusive HomeAssistantSource prices
    assert tomorrow_prices[0]["price"] == 25.0 / 1.25

    # Calculate buy price with the updated formula
    tomorrow_base_price = 25.0 / 1.25  # Price after VAT removal in PriceManager
    tomorrow_expected_buy_price = (tomorrow_base_price + 0.1) * 1.25 + 0.5
    assert tomorrow_prices[0]["buyPrice"] == tomorrow_expected_buy_price

    # For sell price: add tax reduction to base price (VAT-exclusive)
    tomorrow_expected_sell_price = tomorrow_base_price + 0.2
    assert tomorrow_prices[0]["sellPrice"] == tomorrow_expected_sell_price


def test_mock_source() -> None:
    """Test using a MockSource."""
    mock_source = MockSource([1.0, 2.0, 3.0, 4.0])

    pm = PriceManager(
        price_source=mock_source,
        markup_rate=0.1,
        vat_multiplier=1.25,
        additional_costs=0.5,
        tax_reduction=0.2,
        area="SE4",
    )

    # Get today's prices
    today_prices = pm.get_today_prices()
    assert len(today_prices) == 4
    assert today_prices[0]["price"] == 1.0

    # Check calculations with the updated formula:
    # MockSource prices are already VAT-exclusive, so no need to divide
    expected_buy_price = (1.0 + 0.1) * 1.25 + 0.5
    assert today_prices[0]["buyPrice"] == expected_buy_price

    # For sell price: add tax reduction to base price (VAT-exclusive)
    expected_sell_price = 1.0 + 0.2
    assert today_prices[0]["sellPrice"] == expected_sell_price


def test_home_assistant_source_vat_removed_by_price_manager() -> None:
    """HomeAssistantSource returns VAT-inclusive prices; PriceManager strips VAT.

    The source declares prices_include_vat and never divides itself, so the
    multiplier PriceManager holds -- the one settings updates keep current --
    is the only one applied (#903).
    """
    mock_controller = MagicMock()

    today_date = time_utils.today()

    # Create test data with 96 quarterly periods, all with price value of 2.0
    raw_today_data = []
    for hour in range(24):
        for minute in [0, 15, 30, 45]:
            raw_today_data.append(
                {
                    "start": f"{today_date.isoformat()}T{hour:02d}:{minute:02d}:00+01:00",
                    "value": 2.0,  # VAT-inclusive price
                }
            )

    def mock_api_request(method: str, path: str) -> dict | None:
        if "sensor.nordpool_kwh_se4_sek_2_10_025" in path:
            return {"attributes": {"raw_today": raw_today_data}}
        return None

    mock_controller._api_request = mock_api_request

    entity = "sensor.nordpool_kwh_se4_sek_2_10_025"

    ha_source = HomeAssistantSource(mock_controller, entity=entity)
    assert ha_source.prices_include_vat is True
    assert ha_source.get_prices_for_date(today_date)[0] == 2.0  # as published

    for vat in (1.25, 1.20):
        pm = PriceManager(
            price_source=ha_source,
            markup_rate=0.0,
            vat_multiplier=vat,
            additional_costs=0.0,
            tax_reduction=0.0,
            area="SE4",
        )
        assert pm.get_today_prices()[0]["price"] == 2.0 / vat


def _quarterly_array(value: float) -> list[float]:
    """96 identical quarterly values (a plain, timestamp-less Nordpool array)."""
    return [value] * 96


def test_home_assistant_source_rejects_premarket_tomorrow_mirror() -> None:
    """Issue #704: a plain ``tomorrow`` array mirroring today must not be used.

    Before Nordpool publishes next-day prices (~13:00 CET) the HACS sensor
    keeps ``tomorrow_valid`` false while its plain ``tomorrow`` attribute still
    holds today's VAT-inclusive values and there is no ``raw_tomorrow``. That
    array carries no timestamps, so without the ``tomorrow_valid`` guard it
    cannot be told apart from real next-day data. It must be rejected (caller
    raises PriceDataUnavailableError and retries later), not accepted and
    cached as tomorrow inflated by the VAT multiplier.
    """
    mock_controller = MagicMock()
    today_date = time_utils.today()
    tomorrow_date = today_date + timedelta(days=1)

    raw_today_data = [
        {
            "start": f"{today_date.isoformat()}T{hour:02d}:{minute:02d}:00+02:00",
            "value": 2.0,  # VAT-inclusive
        }
        for hour in range(24)
        for minute in (0, 15, 30, 45)
    ]

    def mock_api_request(method: str, path: str) -> dict | None:
        if "sensor.nordpool" in path:
            return {
                "attributes": {
                    "raw_today": raw_today_data,
                    # pre-market: no raw_tomorrow, tomorrow mirrors today,
                    # and the sensor itself says tomorrow is not valid yet
                    "tomorrow_valid": False,
                    "tomorrow": _quarterly_array(2.0),
                }
            }
        return None

    mock_controller._api_request = mock_api_request

    ha_source = HomeAssistantSource(mock_controller, entity="sensor.nordpool_x")

    # today still resolves from the validated raw path
    assert ha_source.get_prices_for_date(today_date)[0] == 2.0

    # tomorrow must be reported unavailable, not returned as today
    try:
        ha_source.get_prices_for_date(tomorrow_date)
    except PriceDataUnavailableError:
        pass
    else:
        raise AssertionError("expected PriceDataUnavailableError for tomorrow")


def test_home_assistant_source_tomorrow_plain_array_used_when_valid() -> None:
    """A plain ``tomorrow`` array IS used once ``tomorrow_valid`` is true.

    This is the shape used by the mock-HA scenarios and by HACS sensor
    configurations that expose ``today``/``tomorrow`` but not ``raw_*``.
    """
    mock_controller = MagicMock()
    today_date = time_utils.today()
    tomorrow_date = today_date + timedelta(days=1)

    def mock_api_request(method: str, path: str) -> dict | None:
        if "sensor.nordpool" in path:
            return {
                "attributes": {
                    "today": _quarterly_array(2.0),
                    "tomorrow_valid": True,
                    "tomorrow": _quarterly_array(1.5),
                }
            }
        return None

    mock_controller._api_request = mock_api_request

    ha_source = HomeAssistantSource(mock_controller, entity="sensor.nordpool_x")

    prices = ha_source.get_prices_for_date(tomorrow_date)
    assert len(prices) == 96
    assert prices[0] == 1.5


def test_home_assistant_source_tomorrow_from_valid_raw_data_still_works() -> None:
    """A timestamp-validated ``raw_tomorrow`` array is still accepted."""
    mock_controller = MagicMock()
    today_date = time_utils.today()
    tomorrow_date = today_date + timedelta(days=1)

    raw_tomorrow_data = [
        {
            "start": f"{tomorrow_date.isoformat()}T{hour:02d}:{minute:02d}:00+02:00",
            "value": 0.8,
        }
        for hour in range(24)
        for minute in (0, 15, 30, 45)
    ]

    def mock_api_request(method: str, path: str) -> dict | None:
        if "sensor.nordpool" in path:
            return {"attributes": {"raw_tomorrow": raw_tomorrow_data}}
        return None

    mock_controller._api_request = mock_api_request

    ha_source = HomeAssistantSource(mock_controller, entity="sensor.nordpool_x")

    prices = ha_source.get_prices_for_date(tomorrow_date)
    assert len(prices) == 96
    assert prices[0] == 0.8


def test_home_assistant_source_today_plain_array_fallback() -> None:
    """The plain ``today`` array fallback (no ``raw_today``) is used as published."""
    mock_controller = MagicMock()
    today_date = time_utils.today()

    def mock_api_request(method: str, path: str) -> dict | None:
        if "sensor.nordpool" in path:
            return {"attributes": {"today": _quarterly_array(2.0)}}
        return None

    mock_controller._api_request = mock_api_request

    ha_source = HomeAssistantSource(mock_controller, entity="sensor.nordpool_x")

    prices = ha_source.get_prices_for_date(today_date)
    assert len(prices) == 96
    assert prices[0] == 2.0


def test_get_available_prices_today_only() -> None:
    """Should return today's prices at quarterly resolution when tomorrow unavailable."""
    mock_source = MockSource(
        test_prices=[0.5] * 96
    )  # Nordpool provides 96 quarterly prices
    pm = PriceManager(
        price_source=mock_source,
        markup_rate=0.05,
        vat_multiplier=1.25,
        additional_costs=0.0,
        tax_reduction=0.0,
        area="SE3",
    )

    with patch.object(mock_source, "get_prices_for_date") as mock_get:
        # First call (today) succeeds with 96 quarterly prices, second (tomorrow) fails
        mock_get.side_effect = [[0.5] * 96, Exception("No data for tomorrow")]

        buy, sell = pm.get_available_prices()

        # Should have 96 quarterly periods
        assert len(buy) == 96
        assert len(sell) == 96

        # All prices should be identical in this test
        assert all(b == buy[0] for b in buy)


def test_get_available_prices_today_and_tomorrow() -> None:
    """Should return today + tomorrow at quarterly resolution when both available."""
    mock_source = MockSource(
        test_prices=[0.5] * 96
    )  # Nordpool provides 96 quarterly prices
    pm = PriceManager(
        price_source=mock_source,
        markup_rate=0.05,
        vat_multiplier=1.25,
        additional_costs=0.0,
        tax_reduction=0.0,
        area="SE3",
    )

    with patch.object(mock_source, "get_prices_for_date") as mock_get:
        # Price source is called:
        # 1. Once for today (cached for both buy and sell)
        # 2. Once for tomorrow via get_price_data (returns full price_data with buyPrice and sellPrice)
        mock_get.side_effect = [[0.5] * 96, [0.6] * 96]

        buy, sell = pm.get_available_prices()

        # Should have today + tomorrow (192 quarterly periods)
        assert len(buy) == 192
        assert len(sell) == 192

        # First 96 are today
        assert all(b == pm._calculate_buy_price(0.5, 0.0) for b in buy[:96])

        # Last 96 are tomorrow
        assert all(b == pm._calculate_buy_price(0.6, 0.0) for b in buy[96:])


def test_get_available_prices_returns_full_arrays_from_midnight() -> None:
    """Should return quarterly arrays starting from 00:00 (not current time)."""
    mock_source = MockSource(test_prices=[0.5] * 96)
    pm = PriceManager(
        price_source=mock_source,
        markup_rate=0.05,
        vat_multiplier=1.25,
        additional_costs=0.0,
        tax_reduction=0.0,
        area="SE3",
    )

    # Create different quarterly prices (96 periods)
    # For simplicity: price = period_index / 100.0
    today_quarterly = [i / 100.0 for i in range(96)]

    with patch.object(mock_source, "get_prices_for_date") as mock_get:
        mock_get.side_effect = [today_quarterly, Exception("No tomorrow")]

        buy, sell = pm.get_available_prices()

        # Index 0 should be first price (00:00 = period 0)
        assert buy[0] == pm._calculate_buy_price(0.0, 0.0)
        assert sell[0] == pm._calculate_sell_price(0.0)

        # Index 56 should be period 56 (14:00 = period 56)
        # Price for period 56 is 0.56
        period_56_price = 56 / 100.0
        assert buy[56] == pm._calculate_buy_price(period_56_price, 0.0)
        assert sell[56] == pm._calculate_sell_price(period_56_price)

        # Each quarter has its own price (no repetition)
        assert buy[56] != buy[57]  # Different quarters have different prices


def test_get_available_prices_returns_tuple() -> None:
    """Should return a tuple of (buy_prices, sell_prices)."""
    mock_source = MockSource(
        test_prices=[0.5] * 96
    )  # Nordpool provides 96 quarterly prices
    pm = PriceManager(
        price_source=mock_source,
        markup_rate=0.05,
        vat_multiplier=1.25,
        additional_costs=0.0,
        tax_reduction=0.0,
        area="SE3",
    )

    with patch.object(mock_source, "get_prices_for_date") as mock_get:
        mock_get.side_effect = [[0.5] * 96, Exception("No tomorrow")]

        result = pm.get_available_prices()

        assert isinstance(result, tuple)
        assert len(result) == 2
        buy, sell = result
        assert isinstance(buy, list)
        assert isinstance(sell, list)
        assert len(buy) == 96
        assert len(sell) == 96


class CountingSource(MockSource):
    """MockSource that records how often it is fetched and probed.

    Both counters are the health check's real cost: every probe is a live
    service call to Home Assistant (#662).
    """

    def __init__(self, test_prices: list, fetch_fails: bool = False) -> None:
        super().__init__(test_prices)
        self.fetch_count = 0
        self.probe_count = 0
        self.fetch_fails = fetch_fails

    def get_prices_for_date(self, target_date: date) -> list:
        self.fetch_count += 1
        if self.fetch_fails:
            raise PriceDataUnavailableError(
                date=target_date, message="Nordpool service call failed"
            )
        return self.test_prices

    def perform_health_check(self) -> dict:
        self.probe_count += 1
        if self.fetch_fails:
            return {
                "status": "ERROR",
                "checks": [
                    {
                        "name": "CountingSource",
                        "status": "ERROR",
                        "error": "Nordpool service call failed",
                    }
                ],
            }
        return super().perform_health_check()


def _counting_price_manager(source: CountingSource) -> PriceManager:
    return PriceManager(
        price_source=source,
        markup_rate=0.0,
        vat_multiplier=1.0,
        additional_costs=0.0,
        tax_reduction=0.0,
        area="SE4",
    )


def test_health_check_reports_from_cache_without_probing_the_source() -> None:
    """Holding today's prices leaves nothing for a live call to prove.

    The health check runs every 5 minutes and the source probe is a live Home
    Assistant service call, so re-proving data that changes once a day is what
    turned a transient upstream 500 into a daily error/recovery banner (#662).
    """
    source = CountingSource([1.0] * 96)
    pm = _counting_price_manager(source)

    pm.get_today_prices()
    fetches_after_warmup = source.fetch_count

    for _ in range(3):
        result = pm.check_health()

    assert result[0]["status"] == "OK"
    assert source.probe_count == 0
    assert source.fetch_count == fetches_after_warmup


def test_health_check_probes_the_source_when_today_is_not_cached() -> None:
    """A cold cache has nothing to report from, so the probe must still happen."""
    source = CountingSource([1.0] * 96)
    pm = _counting_price_manager(source)

    result = pm.check_health()

    assert result[0]["status"] == "OK"
    assert source.probe_count == 1


def test_health_check_reports_error_when_the_cold_probe_fails() -> None:
    """Without today's prices the system genuinely cannot optimize — still ERROR."""
    source = CountingSource([1.0] * 96, fetch_fails=True)
    pm = _counting_price_manager(source)

    result = pm.check_health()

    assert result[0]["status"] == "ERROR"
    assert source.probe_count == 1


# ── #709: price fetching moves off the optimizer's critical path ──────────────
#
# The optimizer (update_battery_schedule -> _get_price_data) used to call
# get_today_prices()/get_tomorrow_prices(), which fetch on a cache miss. Before
# tomorrow's prices publish (~13:00 CET) that meant a full 4-attempt retry loop
# every 15-minute cycle, synchronously on the scheduler thread, delaying or
# skipping the per-period hardware write whenever the HA Nordpool integration
# 500'd at the top of the hour. Fetching now happens only in a dedicated
# refresh job (PriceManager.refresh_cache) and a one-shot startup warm-up; the
# optimizer reads cache-only accessors that never fetch.


class _DateTrackingSource(MockSource):
    """MockSource that records the dates it was asked to fetch."""

    # A non-permissive publication time so the market-time gating in
    # refresh_cache() is actually exercised (base PriceSource is (0, 0, "UTC"),
    # i.e. always reached).
    TOMORROW_EARLIEST = (12, 0, "Europe/Oslo")

    def __init__(self, test_prices: list, unavailable_dates: set | None = None) -> None:
        super().__init__(test_prices)
        self.fetched_dates: list[date] = []
        self._unavailable = unavailable_dates or set()

    def get_prices_for_date(self, target_date: date) -> list:
        self.fetched_dates.append(target_date)
        if target_date in self._unavailable:
            raise PriceDataUnavailableError(
                date=target_date, message="not published yet"
            )
        return self.test_prices


def _tracking_price_manager(source: _DateTrackingSource) -> PriceManager:
    return PriceManager(
        price_source=source,
        markup_rate=0.0,
        vat_multiplier=1.0,
        additional_costs=0.0,
        tax_reduction=0.0,
        area="SE4",
    )


def test_cached_accessors_return_empty_on_cold_cache_without_fetching() -> None:
    source = _DateTrackingSource([1.0] * 96)
    pm = _tracking_price_manager(source)

    assert pm.get_cached_today_prices() == []
    assert pm.get_cached_tomorrow_prices() == []
    assert source.fetched_dates == []


def test_refresh_cache_populates_today_then_serves_it_from_cache() -> None:
    source = _DateTrackingSource([1.0] * 96)
    pm = _tracking_price_manager(source)

    pm.refresh_cache()

    today = time_utils.today()
    assert source.fetched_dates.count(today) == 1
    assert len(pm.get_cached_today_prices()) == 96
    # Serving the cached day does not fetch.
    assert source.fetched_dates.count(today) == 1

    # Every refresh re-fetches today, so a source that replaces a complete
    # day reaches the cache (#902).
    pm.refresh_cache()
    assert source.fetched_dates.count(today) == 2


def test_refresh_cache_swallows_source_failure() -> None:
    today = time_utils.today()
    source = _DateTrackingSource([1.0] * 96, unavailable_dates={today})
    pm = _tracking_price_manager(source)

    pm.refresh_cache()  # must not raise

    assert today in source.fetched_dates
    assert pm.get_cached_today_prices() == []


def test_refresh_cache_skips_tomorrow_before_market_publication_time() -> None:
    source = _DateTrackingSource([1.0] * 96)
    pm = _tracking_price_manager(source)

    # 09:00 Stockholm == 09:00 Oslo, before the 12:00 threshold.
    before_noon = datetime(2026, 8, 31, 9, 0, tzinfo=ZoneInfo("Europe/Stockholm"))
    with patch("core.bess.price_manager.time_utils.now", return_value=before_noon):
        pm.refresh_cache()
        tomorrow = time_utils.today() + timedelta(days=1)

    assert tomorrow not in source.fetched_dates


def test_refresh_cache_fetches_tomorrow_after_market_publication_time() -> None:
    source = _DateTrackingSource([1.0] * 96)
    pm = _tracking_price_manager(source)

    after_noon = datetime(2026, 8, 31, 13, 30, tzinfo=ZoneInfo("Europe/Stockholm"))
    with patch("core.bess.price_manager.time_utils.now", return_value=after_noon):
        pm.refresh_cache()
        tomorrow = time_utils.today() + timedelta(days=1)

    assert tomorrow in source.fetched_dates


def test_cache_only_read_serves_today_in_the_0000_to_0005_gap() -> None:
    """The 00:00 quarterly cycle must not abort while waiting for the :05 job.

    Yesterday's "tomorrow" fetch IS today's data after midnight, but it sits
    in the _tomorrow_* slot. The optimizer reads cache-only accessors that
    never call get_price_data(), and the refresh job that would promote it
    fires at :05 — 5 min after the optimizer's :00 tick. So the read path
    itself (via _cached_today_prices) must do the promotion, with no
    refresh_cache() call in between.
    """
    source = _DateTrackingSource(
        [1.0] * 96
    )  # _DateTrackingSource pins 12:00 Europe/Oslo
    pm = _tracking_price_manager(source)

    day_n_afternoon = datetime(2026, 8, 30, 15, 0, tzinfo=ZoneInfo("Europe/Stockholm"))
    with patch("core.bess.price_manager.time_utils.now", return_value=day_n_afternoon):
        pm.refresh_cache()  # caches today=Aug30, tomorrow=Aug31
        assert pm._tomorrow_date == date(2026, 8, 31)

    source.fetched_dates.clear()
    # 00:00 Aug 31 — rollover has happened, the :05 refresh job has NOT run.
    midnight = datetime(2026, 8, 31, 0, 0, tzinfo=ZoneInfo("Europe/Stockholm"))
    with patch("core.bess.price_manager.time_utils.now", return_value=midnight):
        assert len(pm.get_cached_today_prices()) == 96
        assert pm.get_cached_tomorrow_prices() == []  # Sep 1 not fetched yet
        assert pm._today_date == date(2026, 8, 31)  # promotion persisted

    # ...and it survives the noon refresh that overwrites the _tomorrow_* slot.
    noon = datetime(2026, 8, 31, 13, 0, tzinfo=ZoneInfo("Europe/Stockholm"))
    with patch("core.bess.price_manager.time_utils.now", return_value=noon):
        pm.refresh_cache()  # fetches Sep 1 into _tomorrow_*
        assert pm._tomorrow_date == date(2026, 9, 1)
        assert len(pm.get_cached_today_prices()) == 96  # Aug 31 still there

    # The 00:00 read above fetched nothing; the noon refresh re-fetches both
    # days (#902).
    assert source.fetched_dates == [date(2026, 8, 31), date(2026, 9, 1)]


# ── #902: a complete cached day is still the source's current truth ───────────
#
# A source may publish a complete day and later replace it with different
# values: a forecast sensor that fills tomorrow before Nordpool publishes and
# swaps in the confirmed prices at ~13:00, or a market correction. The refresh
# job used to treat any complete cached day as final, so the optimizer kept
# planning on the forecast until the add-on restarted.

HELSINKI = ZoneInfo("Europe/Helsinki")


def test_confirmed_prices_replace_a_cached_complete_forecast() -> None:
    source = _DateTrackingSource([1.0] * 96)
    pm = _tracking_price_manager(source)

    # 13:05 Helsinki (12:05 Oslo): the sensor still holds the forecast.
    with patch(
        "core.bess.price_manager.time_utils.now",
        return_value=datetime(2026, 11, 17, 13, 5, tzinfo=HELSINKI),
    ):
        pm.refresh_cache()
        assert [e["buyPrice"] for e in pm.get_cached_tomorrow_prices()] == [1.0] * 96

    # 14:05: the sensor now holds a complete, different, confirmed day.
    source.test_prices = [2.0] * 96
    with patch(
        "core.bess.price_manager.time_utils.now",
        return_value=datetime(2026, 11, 17, 14, 5, tzinfo=HELSINKI),
    ):
        pm.refresh_cache()
        # The optimizer's cache-only reads must see the confirmed prices.
        assert [e["buyPrice"] for e in pm.get_cached_tomorrow_prices()] == [2.0] * 96
        assert [e["buyPrice"] for e in pm.get_cached_today_prices()] == [2.0] * 96


def test_failed_refetch_keeps_the_previously_cached_day() -> None:
    source = _DateTrackingSource([1.0] * 96)
    pm = _tracking_price_manager(source)
    pm.refresh_cache()

    source._unavailable = {time_utils.today()}
    pm.refresh_cache()  # must not raise

    assert [e["buyPrice"] for e in pm.get_cached_today_prices()] == [1.0] * 96


def test_tomorrow_publication_is_not_reached_just_after_midnight_east_of_oslo() -> None:
    """00:05 Helsinki is 23:05 the previous day in Oslo — 13 h before publication.

    Comparing only the time of day read (23, 5) >= (12, 0) as published.
    """
    source = _DateTrackingSource([1.0] * 96)
    pm = _tracking_price_manager(source)

    with patch(
        "core.bess.price_manager.time_utils.now",
        return_value=datetime(2026, 11, 17, 0, 5, tzinfo=HELSINKI),
    ):
        pm.refresh_cache()
        tomorrow = time_utils.today() + timedelta(days=1)

    assert tomorrow not in source.fetched_dates


def test_official_nordpool_and_octopus_declare_publication_times() -> None:
    from core.bess.octopus_energy_source import OctopusEnergySource
    from core.bess.official_nordpool_source import OfficialNordpoolSource

    assert OfficialNordpoolSource.TOMORROW_EARLIEST == (12, 0, "Europe/Oslo")
    assert OctopusEnergySource.TOMORROW_EARLIEST == (15, 30, "Europe/London")
    # Base class stays permissive so an unknown source is never gated out.
    assert PriceSource.TOMORROW_EARLIEST == (0, 0, "Pacific/Kiritimati")


def test_base_source_tomorrow_is_never_gated_after_local_midnight() -> None:
    """The permissive base default must stay open from the user's own midnight."""
    # Plain MockSource: inherits the base PriceSource.TOMORROW_EARLIEST.
    pm = PriceManager(
        price_source=MockSource([1.0] * 96),
        markup_rate=0.0,
        vat_multiplier=1.0,
        additional_costs=0.0,
        tax_reduction=0.0,
        area="SE4",
    )
    for tz in ("Pacific/Auckland", "Europe/Helsinki", "America/Los_Angeles"):
        with patch(
            "core.bess.price_manager.time_utils.now",
            return_value=datetime(2026, 11, 17, 0, 0, tzinfo=ZoneInfo(tz)),
        ):
            assert pm._tomorrow_publication_reached(), tz


# ── Octoplus free-import windows composed at read time ────────────────────────
#
# Octopus leaves the Agile rate unchanged for a Power Up / Happy Hour window, so
# PriceManager overlays the window onto cached entries whenever they are read.
# Bookings change during the day while rates do not, so the window list is
# re-fetched on every refresh_cache() even when the day's prices are cached.


class _WindowSource:
    """Stands in for BatterySystemManager._fetch_free_import_windows."""

    def __init__(self) -> None:
        self.windows: list = []
        self.error: Exception | None = None
        self.calls: list[tuple[datetime, datetime]] = []

    def __call__(self, start: datetime, end: datetime) -> list:
        self.calls.append((start, end))
        if self.error is not None:
            raise self.error
        return list(self.windows)


def _free_import_price_manager(
    source: CountingSource, windows: _WindowSource, free_import_price: float = 0.0
) -> PriceManager:
    return PriceManager(
        price_source=source,
        markup_rate=0.0,
        vat_multiplier=1.0,
        additional_costs=0.0,
        tax_reduction=0.0,
        area="SE4",
        free_import_price=free_import_price,
        free_import_window_source=windows,
    )


def _window_on(day: date, start_hour: int, end_hour: int) -> CalendarWindow:
    tz = time_utils.TIMEZONE
    return CalendarWindow(
        start=datetime.combine(day, datetime.min.time(), tzinfo=tz)
        + timedelta(hours=start_hour),
        end=datetime.combine(day, datetime.min.time(), tzinfo=tz)
        + timedelta(hours=end_hour),
    )


def test_window_booked_after_prices_are_cached_reaches_the_optimizer_read() -> None:
    source = CountingSource([0.30] * 96)
    windows = _WindowSource()
    pm = _free_import_price_manager(source, windows)
    today = time_utils.today()

    pm.refresh_cache()
    assert all(e["buyPrice"] == 0.30 for e in pm.get_cached_today_prices())

    windows.windows = [_window_on(today, 11, 12)]
    pm.refresh_cache()

    entries = pm.get_cached_today_prices()
    assert [i for i, e in enumerate(entries) if e["buyPrice"] == 0.0] == [
        44,
        45,
        46,
        47,
    ]
    assert all(e["sellPrice"] == entries[0]["sellPrice"] for e in entries)


def test_window_is_fetched_for_today_and_tomorrow() -> None:
    windows = _WindowSource()
    pm = _free_import_price_manager(CountingSource([0.30] * 96), windows)
    today = time_utils.today()

    pm.refresh_cache()

    start, end = windows.calls[-1]
    tz = time_utils.TIMEZONE
    assert start == datetime.combine(today, datetime.min.time(), tzinfo=tz)
    assert end == datetime.combine(
        today + timedelta(days=2), datetime.min.time(), tzinfo=tz
    )


def test_every_cached_read_path_sees_the_same_free_window() -> None:
    """Plan, dashboard and realized cost must all price the window identically."""
    source = CountingSource([0.30] * 96)
    windows = _WindowSource()
    pm = _free_import_price_manager(source, windows, free_import_price=0.02)
    today = time_utils.today()
    tomorrow = today + timedelta(days=1)
    windows.windows = [_window_on(today, 11, 12), _window_on(tomorrow, 1, 2)]

    pm.refresh_cache()
    pm.get_price_data(tomorrow)

    buy, _sell = pm.get_available_prices()
    assert buy[44:48] == [0.02] * 4
    assert buy[96 + 4 : 96 + 8] == [0.02] * 4
    assert [e["buyPrice"] for e in pm.get_price_data(today)][44:48] == [0.02] * 4
    assert [e["buyPrice"] for e in pm.get_cached_tomorrow_prices()][4:8] == [0.02] * 4
    assert [e["isFreeImport"] for e in pm.get_price_data(tomorrow)][4:8] == [True] * 4


def test_freshly_fetched_prices_carry_the_overlay() -> None:
    """The cache-miss path of get_price_data returns overlaid entries too."""
    windows = _WindowSource()
    pm = _free_import_price_manager(CountingSource([0.30] * 96), windows)
    today = time_utils.today()
    windows.windows = [_window_on(today, 11, 12)]
    pm.refresh_cache()
    pm.clear_cache()

    assert [e["buyPrice"] for e in pm.get_price_data(today)][44:48] == [0.0] * 4


def test_failed_window_fetch_keeps_previous_windows_and_does_not_raise() -> None:
    windows = _WindowSource()
    pm = _free_import_price_manager(CountingSource([0.30] * 96), windows)
    today = time_utils.today()
    windows.windows = [_window_on(today, 11, 12)]
    pm.refresh_cache()

    windows.windows = []
    windows.error = RuntimeError("calendar unavailable")
    pm.refresh_cache()  # must not raise

    assert [e["buyPrice"] for e in pm.get_cached_today_prices()][44:48] == [0.0] * 4


def _free_import_health(pm: PriceManager) -> dict | None:
    components: list[dict] = pm.check_health()
    for component in components:
        if component["name"] == "Octoplus Free Import Windows":
            return component
    return None


def test_healthy_window_fetch_adds_no_health_component() -> None:
    windows = _WindowSource()
    pm = _free_import_price_manager(CountingSource([0.30] * 96), windows)
    pm.refresh_cache()

    assert _free_import_health(pm) is None


def test_failed_window_fetch_warns_then_errors_once_it_persists() -> None:
    windows = _WindowSource()
    pm = _free_import_price_manager(CountingSource([0.30] * 96), windows)
    windows.error = RuntimeError("calendar unavailable")
    tz = ZoneInfo("Europe/Stockholm")
    first_failure = datetime(2026, 9, 13, 9, 5, tzinfo=tz)

    with patch("core.bess.price_manager.time_utils.now", return_value=first_failure):
        pm.refresh_cache()
        component = _free_import_health(pm)
    assert component is not None
    assert component["status"] == "WARNING"
    assert component["required"] is False
    assert "calendar unavailable" in component["checks"][0]["error"]

    # A second failure does not reset how long the problem has persisted.
    with patch(
        "core.bess.price_manager.time_utils.now",
        return_value=first_failure + timedelta(minutes=15),
    ):
        pm.refresh_cache()
    with patch(
        "core.bess.price_manager.time_utils.now",
        return_value=first_failure + timedelta(minutes=31),
    ):
        component = _free_import_health(pm)
    assert component is not None
    assert component["status"] == "ERROR"

    windows.error = None
    pm.refresh_cache()
    assert _free_import_health(pm) is None


# ---------------------------------------------------------------------------
# Time-of-day grid tariff (#861). A Danish DSO (e.g. Radius Elnet) charges a
# grid transport fee that varies by hour and by season; it is added to the
# buy price per period on top of the flat additional_costs.
# ---------------------------------------------------------------------------

# Radius-style bands: low 00-06, high 06-17, peak 17-21, high 21-24.
_WINTER_TARIFF = [0.15] * 6 + [0.45] * 11 + [1.35] * 4 + [0.45] * 3
_SUMMER_TARIFF = [0.15] * 6 + [0.23] * 11 + [0.60] * 4 + [0.23] * 3


def _tariff_price_manager(
    source: PriceSource,
    grid_tariff_hourly: list[float],
    grid_tariff_summer_hourly: list[float] | None = None,
) -> PriceManager:
    return PriceManager(
        price_source=source,
        markup_rate=0.05,
        vat_multiplier=1.25,
        additional_costs=0.9,
        tax_reduction=0.1,
        area="DK2",
        grid_tariff_hourly=grid_tariff_hourly,
        grid_tariff_summer_hourly=grid_tariff_summer_hourly or [],
    )


def _flat_buy(spot: float) -> float:
    """Buy price for the _tariff_price_manager config with no tariff."""
    return (spot + 0.05) * 1.25 + 0.9


def test_grid_tariff_adds_the_local_hour_rate_to_each_buy_price() -> None:
    pm = _tariff_price_manager(MockSource([0.5] * 96), _WINTER_TARIFF)

    entries = pm.get_price_data(date(2026, 1, 14))

    assert len(entries) == 96
    for period, entry in enumerate(entries):
        hour = period // 4
        assert entry["buyPrice"] == _flat_buy(0.5) + _WINTER_TARIFF[hour], period
    # The tariff is a buy-side fee only -- the sell price is untouched.
    assert all(entry["sellPrice"] == 0.5 + 0.1 for entry in entries)


def test_grid_tariff_moves_the_cheapest_buy_period_away_from_the_spot_minimum() -> None:
    """The outcome that matters to the optimizer: the price signal changes.

    Spot is cheapest at 18:00, but the peak tariff (17-21) makes 18:00 one of
    the most expensive hours to import -- the cheapest buy is now the night.
    """
    spot = [0.6] * 96
    spot[18 * 4] = 0.2
    pm = _tariff_price_manager(MockSource(spot), _WINTER_TARIFF)

    buy = [entry["buyPrice"] for entry in pm.get_price_data(date(2026, 1, 14))]

    assert spot.index(min(spot)) == 18 * 4
    assert buy.index(min(buy)) < 6 * 4
    assert buy[18 * 4] > buy[0]


def test_summer_profile_applies_april_to_september_only() -> None:
    pm = _tariff_price_manager(MockSource([0.5] * 96), _WINTER_TARIFF, _SUMMER_TARIFF)
    peak = 18 * 4

    for day, profile in (
        (date(2026, 3, 31), _WINTER_TARIFF),
        (date(2026, 4, 1), _SUMMER_TARIFF),
        (date(2026, 9, 30), _SUMMER_TARIFF),
        (date(2026, 10, 1), _WINTER_TARIFF),
    ):
        buy = pm.get_price_data(day)[peak]["buyPrice"]
        assert buy == _flat_buy(0.5) + profile[18], day


def test_year_round_profile_applies_in_summer_without_a_summer_profile() -> None:
    pm = _tariff_price_manager(MockSource([0.5] * 96), _WINTER_TARIFF)

    buy = pm.get_price_data(date(2026, 7, 1))[18 * 4]["buyPrice"]

    assert buy == _flat_buy(0.5) + _WINTER_TARIFF[18]


def test_grid_tariff_follows_wall_clock_hours_on_the_fall_back_day() -> None:
    """2026-10-25 has 100 periods; 17:00 local is period 72, not 68."""
    pm = _tariff_price_manager(MockSource([0.5] * 100), _WINTER_TARIFF)

    entries = pm.get_price_data(date(2026, 10, 25))

    assert len(entries) == 100
    assert entries[72]["buyPrice"] == _flat_buy(0.5) + _WINTER_TARIFF[17]
    assert entries[68]["buyPrice"] == _flat_buy(0.5) + _WINTER_TARIFF[16]
    # The repeated 02:00 hour carries the 02:00 rate both times.
    assert entries[8]["buyPrice"] == entries[12]["buyPrice"]


def test_grid_tariff_follows_wall_clock_hours_on_the_spring_forward_day() -> None:
    """2026-03-29 has 92 periods; 17:00 local is period 64."""
    pm = _tariff_price_manager(MockSource([0.5] * 92), _WINTER_TARIFF)

    entries = pm.get_price_data(date(2026, 3, 29))

    assert len(entries) == 92
    assert entries[64]["buyPrice"] == _flat_buy(0.5) + _WINTER_TARIFF[17]


def test_empty_grid_tariff_leaves_buy_prices_unchanged() -> None:
    pm = _tariff_price_manager(MockSource([0.5] * 96), [])

    entries = pm.get_price_data(date(2026, 1, 14))

    assert all(entry["buyPrice"] == _flat_buy(0.5) for entry in entries)


def test_grid_tariff_is_not_added_to_final_source_prices() -> None:
    """A source with prices_are_final (Octopus) already includes all fees."""

    class _FinalSource(MockSource):
        @property
        def prices_are_final(self) -> bool:
            return True

    pm = _tariff_price_manager(_FinalSource([0.5] * 96), _WINTER_TARIFF)

    entries = pm.get_price_data(date(2026, 1, 14))

    assert all(entry["buyPrice"] == 0.5 for entry in entries)


def test_raw_price_buy_path_refuses_a_configured_grid_tariff() -> None:
    """raw_prices carry no date, so the tariff hour cannot be placed."""
    pm = _tariff_price_manager(MockSource([0.5] * 96), _WINTER_TARIFF)

    try:
        pm.get_buy_prices(raw_prices=[0.5] * 96)
    except ValueError as e:
        assert "grid tariff" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_grid_tariff_tolerates_a_source_returning_more_than_a_day() -> None:
    """Extended-horizon sources can return past midnight; the tariff must not
    assume the list is exactly one day long."""
    pm = _tariff_price_manager(MockSource([0.5] * 150), _WINTER_TARIFF)

    entries = pm.get_price_data(date(2026, 1, 14))

    assert len(entries) == 150
    # Period 96 + 8*4 is 08:00 the next day -- the high-band fee.
    assert entries[96 + 8 * 4]["buyPrice"] == _flat_buy(0.5) + _WINTER_TARIFF[8]
