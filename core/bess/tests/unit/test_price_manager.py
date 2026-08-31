"""
Test the PriceManager implementation.
"""

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from core.bess import time_utils
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
        vat_multiplier=1.25,
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
    # Note: HomeAssistantSource now removes VAT from prices before returning them
    assert today_prices[0]["price"] == 1.0 / 1.25

    # Check calculations with the updated formula:
    base_price = 1.0 / 1.25  # Price after VAT removal in HomeAssistantSource
    expected_buy_price = (base_price + 0.1) * 1.25 + 0.5
    assert today_prices[0]["buyPrice"] == expected_buy_price

    # For sell price: add tax reduction to base price (VAT-exclusive)
    expected_sell_price = base_price + 0.2
    assert today_prices[0]["sellPrice"] == expected_sell_price

    # Get tomorrow's prices (quarterly - 96 periods)
    tomorrow_prices = pm.get_tomorrow_prices()
    assert len(tomorrow_prices) == 96
    # Note: HomeAssistantSource now removes VAT from prices before returning them
    assert tomorrow_prices[0]["price"] == 25.0 / 1.25

    # Calculate buy price with the updated formula
    tomorrow_base_price = 25.0 / 1.25  # Price after VAT removal in HomeAssistantSource
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


def test_home_assistant_source_vat_parameter() -> None:
    """Test that the VAT multiplier parameter in HomeAssistantSource works correctly."""
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

    # Test with default VAT multiplier (1.25)
    ha_source_default = HomeAssistantSource(
        mock_controller,
        vat_multiplier=1.25,
        entity=entity,
    )
    prices_default = ha_source_default.get_prices_for_date(today_date)
    assert prices_default[0] == 1.6  # 2.0 / 1.25 = 1.6

    # Test with custom VAT multiplier (1.20 for 20% VAT)
    ha_source_custom = HomeAssistantSource(
        mock_controller,
        vat_multiplier=1.20,
        entity=entity,
    )
    prices_custom = ha_source_custom.get_prices_for_date(today_date)
    assert round(prices_custom[0], 4) == round(2.0 / 1.20, 4)  # ~1.6667


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

    ha_source = HomeAssistantSource(
        mock_controller, vat_multiplier=1.25, entity="sensor.nordpool_x"
    )

    # today still resolves from the validated raw path
    assert ha_source.get_prices_for_date(today_date)[0] == 2.0 / 1.25

    # tomorrow must be reported unavailable, not returned as today * 1.25
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
    VAT must still be stripped.
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

    ha_source = HomeAssistantSource(
        mock_controller, vat_multiplier=1.25, entity="sensor.nordpool_x"
    )

    prices = ha_source.get_prices_for_date(tomorrow_date)
    assert len(prices) == 96
    assert prices[0] == 1.5 / 1.25


def test_home_assistant_source_tomorrow_from_valid_raw_data_still_works() -> None:
    """A timestamp-validated ``raw_tomorrow`` array is still accepted, VAT stripped."""
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

    ha_source = HomeAssistantSource(
        mock_controller, vat_multiplier=1.25, entity="sensor.nordpool_x"
    )

    prices = ha_source.get_prices_for_date(tomorrow_date)
    assert len(prices) == 96
    assert prices[0] == 0.8 / 1.25


def test_home_assistant_source_today_plain_array_fallback_strips_vat() -> None:
    """The plain ``today`` array fallback (no ``raw_today``) must strip VAT too."""
    mock_controller = MagicMock()
    today_date = time_utils.today()

    def mock_api_request(method: str, path: str) -> dict | None:
        if "sensor.nordpool" in path:
            return {"attributes": {"today": _quarterly_array(2.0)}}
        return None

    mock_controller._api_request = mock_api_request

    ha_source = HomeAssistantSource(
        mock_controller, vat_multiplier=1.25, entity="sensor.nordpool_x"
    )

    prices = ha_source.get_prices_for_date(today_date)
    assert len(prices) == 96
    assert prices[0] == 2.0 / 1.25


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
        assert all(b == pm._calculate_buy_price(0.5) for b in buy[:96])

        # Last 96 are tomorrow
        assert all(b == pm._calculate_buy_price(0.6) for b in buy[96:])


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
        assert buy[0] == pm._calculate_buy_price(0.0)
        assert sell[0] == pm._calculate_sell_price(0.0)

        # Index 56 should be period 56 (14:00 = period 56)
        # Price for period 56 is 0.56
        period_56_price = 56 / 100.0
        assert buy[56] == pm._calculate_buy_price(period_56_price)
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

    # A second refresh with today already cached does not re-fetch today.
    pm.refresh_cache()
    assert source.fetched_dates.count(today) == 1


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

    assert source.fetched_dates == [
        date(2026, 9, 1)
    ], "only Sep 1 should have been fetched; Aug 31 came from the promoted cache"


def test_official_nordpool_and_octopus_declare_publication_times() -> None:
    from core.bess.octopus_energy_source import OctopusEnergySource
    from core.bess.official_nordpool_source import OfficialNordpoolSource

    assert OfficialNordpoolSource.TOMORROW_EARLIEST == (12, 0, "Europe/Oslo")
    assert OctopusEnergySource.TOMORROW_EARLIEST == (15, 30, "Europe/London")
    # Base class stays permissive so an unknown source is never gated out.
    assert PriceSource.TOMORROW_EARLIEST == (0, 0, "UTC")
