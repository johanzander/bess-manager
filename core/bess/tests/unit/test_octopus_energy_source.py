"""
Test the OctopusEnergySource implementation.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from core.bess.exceptions import PriceDataUnavailableError, SystemConfigurationError
from core.bess.octopus_energy_source import OctopusEnergySource
from core.bess.price_manager import MockSource, PriceManager


def _make_rates(target_date, count=48, base_value=0.20, export=False):
    """Create mock Octopus rate entries for a given date.

    Args:
        target_date: Date to create rates for
        count: Number of 30-minute periods
        base_value: Base price value
        export: If True, use lower values typical of export rates

    Returns:
        List of rate dicts with start, end, and value_inc_vat
    """
    rates = []
    for i in range(count):
        start = datetime.combine(target_date, datetime.min.time()) + timedelta(
            minutes=30 * i
        )
        end = start + timedelta(minutes=30)
        value = (
            (base_value + i * 0.01) if not export else (base_value * 0.3 + i * 0.005)
        )
        rates.append(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "value_inc_vat": value,
            }
        )
    return rates


def _make_ha_controller(import_rates, export_rates=None):
    """Create a mock HA controller that returns rates for given entity IDs.

    Args:
        import_rates: Rates to return for import entities
        export_rates: Rates to return for export entities (optional)
    """
    controller = MagicMock()

    def api_request(method, path):
        if "import_today" in path or "import_tomorrow" in path:
            return {"attributes": {"rates": import_rates}}
        if "export_today" in path or "export_tomorrow" in path:
            if export_rates is not None:
                return {"attributes": {"rates": export_rates}}
            return {"attributes": {}}
        return {}

    controller._api_request = MagicMock(side_effect=api_request)
    return controller


def _make_source(controller):
    """Create an OctopusEnergySource with standard test entity IDs."""
    return OctopusEnergySource(
        ha_controller=controller,
        import_today_entity="event.octopus_import_today",
        import_tomorrow_entity="event.octopus_import_tomorrow",
        export_today_entity="event.octopus_export_today",
        export_tomorrow_entity="event.octopus_export_tomorrow",
    )


class TestOctopusEnergySourceProperties:
    """Test basic properties of OctopusEnergySource."""

    def test_period_duration_hours_is_half_hour(self):
        controller = MagicMock()
        source = _make_source(controller)
        assert source.period_duration_hours == 0.5

    def test_default_price_source_period_duration_is_quarter(self):
        """Verify the base PriceSource default is 0.25 (Nordpool)."""
        mock = MockSource([1.0])
        assert mock.period_duration_hours == 0.25


class TestImportRateFetching:
    """Test fetching import rates from Octopus Energy entities."""

    def test_fetch_today_import_rates(self):
        today = datetime.now().date()
        rates = _make_rates(today)
        controller = _make_ha_controller(rates)
        source = _make_source(controller)

        prices = source.get_prices_for_date(today)

        assert len(prices) == 48
        assert prices[0] == rates[0]["value_inc_vat"]
        assert prices[47] == rates[47]["value_inc_vat"]

    def test_fetch_tomorrow_import_rates(self):
        tomorrow = datetime.now().date() + timedelta(days=1)
        rates = _make_rates(tomorrow)
        controller = _make_ha_controller(rates)
        source = _make_source(controller)

        prices = source.get_prices_for_date(tomorrow)

        assert len(prices) == 48

    def test_rejects_date_beyond_tomorrow(self):
        day_after = datetime.now().date() + timedelta(days=2)
        controller = MagicMock()
        source = _make_source(controller)

        with pytest.raises(SystemConfigurationError):
            source.get_prices_for_date(day_after)

    def test_too_few_rates_raises_error(self):
        """Rates below minimum threshold should fail validation."""
        today = datetime.now().date()
        rates = _make_rates(today, count=20)  # Well below minimum of 46
        controller = _make_ha_controller(rates)
        source = _make_source(controller)

        with pytest.raises(PriceDataUnavailableError):
            source.get_prices_for_date(today)

    def test_partial_rates_accepted(self):
        """46-47 rates should be accepted (Octopus publishes incrementally)."""
        today = datetime.now().date()
        for count in (46, 47):
            rates = _make_rates(today, count=count)
            controller = _make_ha_controller(rates)
            source = _make_source(controller)

            prices = source.get_prices_for_date(today)
            assert len(prices) == count

    def test_too_many_rates_raises_error(self):
        """More than 48 rates for a single date should fail validation."""
        today = datetime.now().date()
        rates = _make_rates(today, count=48)
        # Add duplicate rates that also fall on today to exceed 48
        extra = _make_rates(today, count=2, base_value=0.50)
        # Adjust extra start times to be within the same day but unique
        for i, rate in enumerate(extra):
            start = datetime.combine(today, datetime.min.time()) + timedelta(
                minutes=15 * i
            )
            rate["start"] = start.isoformat()
            rate["end"] = (start + timedelta(minutes=15)).isoformat()
        all_rates = rates + extra
        controller = _make_ha_controller(all_rates)
        source = _make_source(controller)

        with pytest.raises(PriceDataUnavailableError):
            source.get_prices_for_date(today)

    def test_no_rates_attribute_raises_error(self):
        today = datetime.now().date()
        controller = MagicMock()
        controller._api_request = MagicMock(
            return_value={"attributes": {"no_rates_key": []}}
        )
        source = _make_source(controller)

        with pytest.raises(PriceDataUnavailableError):
            source.get_prices_for_date(today)

    def test_api_failure_raises_error(self):
        today = datetime.now().date()
        controller = MagicMock()
        controller._api_request = MagicMock(side_effect=ConnectionError("timeout"))
        source = _make_source(controller)

        with pytest.raises(PriceDataUnavailableError):
            source.get_prices_for_date(today)


class TestExportRateFetching:
    """Test fetching export/sell rates from Octopus Energy entities."""

    def test_fetch_export_rates(self):
        today = datetime.now().date()
        import_rates = _make_rates(today)
        export_rates = _make_rates(today, export=True)
        controller = _make_ha_controller(import_rates, export_rates)
        source = _make_source(controller)

        sell_prices = source.get_sell_prices_for_date(today)

        assert sell_prices is not None
        assert len(sell_prices) == 48
        assert sell_prices[0] == export_rates[0]["value_inc_vat"]

    def test_no_export_entity_returns_none(self):
        today = datetime.now().date()
        controller = MagicMock()
        source = OctopusEnergySource(
            ha_controller=controller,
            import_today_entity="event.import_today",
            import_tomorrow_entity="event.import_tomorrow",
            export_today_entity="",
            export_tomorrow_entity="",
        )

        assert source.get_sell_prices_for_date(today) is None

    def test_export_failure_returns_none(self):
        """Export rate failure should return None, not raise."""
        today = datetime.now().date()
        controller = MagicMock()
        controller._api_request = MagicMock(side_effect=ConnectionError("timeout"))
        source = _make_source(controller)

        assert source.get_sell_prices_for_date(today) is None

    def test_default_get_sell_prices_for_date_returns_none(self):
        """Base PriceSource returns None for sell prices."""
        mock = MockSource([1.0])
        assert mock.get_sell_prices_for_date(datetime.now().date()) is None


class TestDateFilteringAndSorting:
    """Test rate filtering by date and chronological sorting."""

    def test_filters_rates_by_date(self):
        """Only rates matching the target date should be included."""
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)

        # Mix rates from today and tomorrow
        today_rates = _make_rates(today)
        tomorrow_rates = _make_rates(tomorrow, count=10)
        mixed_rates = today_rates + tomorrow_rates

        controller = _make_ha_controller(mixed_rates)
        source = _make_source(controller)

        prices = source.get_prices_for_date(today)
        assert len(prices) == 48

    def test_sorts_rates_chronologically(self):
        """Rates should be sorted by start time regardless of input order."""
        today = datetime.now().date()
        rates = _make_rates(today)
        # Reverse the order
        rates.reverse()

        controller = _make_ha_controller(rates)
        source = _make_source(controller)

        prices = source.get_prices_for_date(today)
        assert len(prices) == 48
        # First price should be the midnight rate (lowest index)
        assert prices[0] == 0.20  # base_value for index 0


class TestHealthCheck:
    """Test health check functionality."""

    def test_healthy_source(self):
        today = datetime.now().date()
        import_rates = _make_rates(today)
        export_rates = _make_rates(today, export=True)
        controller = _make_ha_controller(import_rates, export_rates)
        source = _make_source(controller)

        result = source.perform_health_check()

        assert result["status"] == "OK"
        assert len(result["checks"]) == 2
        assert result["checks"][0]["status"] == "OK"
        assert result["checks"][1]["status"] == "OK"

    def test_unhealthy_import(self):
        controller = MagicMock()
        controller._api_request = MagicMock(side_effect=ConnectionError("down"))
        source = _make_source(controller)

        result = source.perform_health_check()

        assert result["status"] == "ERROR"
        assert result["checks"][0]["status"] == "ERROR"


class TestPriceManagerIntegration:
    """Test OctopusEnergySource integration with PriceManager."""

    def test_price_manager_uses_direct_sell_prices(self):
        """When source provides sell prices, PriceManager should use them directly."""
        today = datetime.now().date()
        import_rates = _make_rates(today)
        export_rates = _make_rates(today, export=True)
        controller = _make_ha_controller(import_rates, export_rates)
        source = _make_source(controller)

        pm = PriceManager(
            price_source=source,
            markup_rate=0.0,
            vat_multiplier=1.0,
            additional_costs=0.0,
            tax_reduction=0.0,
            area="UK",
        )

        price_data = pm.get_price_data(today)

        assert len(price_data) == 48
        # Sell price should come directly from export rates, not calculated
        assert price_data[0]["sellPrice"] == export_rates[0]["value_inc_vat"]
        # Buy price should still be calculated from import rates
        assert price_data[0]["buyPrice"] == import_rates[0]["value_inc_vat"]

    def test_price_manager_timestamps_use_half_hour_spacing(self):
        """Timestamps should be 30 minutes apart for Octopus."""
        today = datetime.now().date()
        rates = _make_rates(today)
        controller = _make_ha_controller(rates)
        source = _make_source(controller)

        pm = PriceManager(
            price_source=source,
            markup_rate=0.0,
            vat_multiplier=1.0,
            additional_costs=0.0,
            tax_reduction=0.0,
            area="UK",
        )

        price_data = pm.get_price_data(today)

        # First entry at 00:00, second at 00:30
        assert price_data[0]["timestamp"].endswith("00:00")
        assert price_data[1]["timestamp"].endswith("00:30")
        assert price_data[2]["timestamp"].endswith("01:00")

    def test_price_manager_fallback_sell_without_export(self):
        """Without export entity, sell price should use calculated formula."""
        today = datetime.now().date()
        rates = _make_rates(today)
        controller = _make_ha_controller(rates)

        source = OctopusEnergySource(
            ha_controller=controller,
            import_today_entity="event.octopus_import_today",
            import_tomorrow_entity="event.octopus_import_tomorrow",
            export_today_entity="",
            export_tomorrow_entity="",
        )

        tax_reduction = 0.05
        pm = PriceManager(
            price_source=source,
            markup_rate=0.0,
            vat_multiplier=1.0,
            additional_costs=0.0,
            tax_reduction=tax_reduction,
            area="UK",
        )

        price_data = pm.get_price_data(today)

        # Sell price should be calculated: base_price + tax_reduction
        expected_sell = rates[0]["value_inc_vat"] + tax_reduction
        assert abs(price_data[0]["sellPrice"] - expected_sell) < 1e-6
