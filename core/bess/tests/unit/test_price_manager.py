from datetime import date, datetime, timedelta

from bess.price_manager import (
    ElectricityPriceManager,
    Guru56APISource,
    HANordpoolSource,
    MockSource,
    NordpoolAPISource,
)
import pytest


@pytest.fixture
def test_prices():
    """Provide test price data."""
    return [1.0] * 24


@pytest.fixture
def price_manager(test_prices):
    """Provide a configured price manager instance."""
    source = MockSource(test_prices)
    return ElectricityPriceManager(source)


class TestPriceCalculations:
    """Test price calculation logic."""

    def test_basic_calculation(self, price_manager):
        """Test basic price calculations."""
        base_price = 1.0
        result = price_manager.calculate_prices(base_price)

        # Raw Nordpool price
        assert abs(result["price"] - base_price) < 1e-6

        # Full retail price
        expected_buy = (
            (base_price + price_manager.settings.markup_rate)
            * price_manager.settings.vat_multiplier
            + price_manager.settings.additional_costs
        )
        assert abs(result["buyPrice"] - expected_buy) < 1e-6

        # Sell price
        expected_sell = base_price + price_manager.settings.tax_reduction
        assert abs(result["sellPrice"] - expected_sell) < 1e-6

    def test_actual_price_calculation(self, price_manager):
        """Test price calculation with use_actual_price=True."""
        price_manager.settings.use_actual_price = True
        base_price = 1.0
        result = price_manager.calculate_prices(base_price)

        # Should still keep both prices
        assert abs(result["price"] - base_price) < 1e-6
        expected_buy = (
            (base_price + price_manager.settings.markup_rate)
            * price_manager.settings.vat_multiplier
            + price_manager.settings.additional_costs
        )
        assert abs(result["buyPrice"] - expected_buy) < 1e-6


class TestPriceRetrieval:
    """Test price retrieval functionality."""

    def test_get_today_prices(self, price_manager):
        """Test retrieving today's prices."""
        prices = price_manager.get_today_prices()

        assert len(prices) == 24
        assert all(isinstance(p, dict) for p in prices)
        assert all("timestamp" in p for p in prices)

        # Verify timestamps are for today
        today = datetime.now().date()
        assert all(
            datetime.strptime(p["timestamp"], "%Y-%m-%d %H:%M").date() == today
            for p in prices
        )

    def test_get_tomorrow_prices(self, price_manager):
        """Test retrieving tomorrow's prices."""
        prices = price_manager.get_tomorrow_prices()

        assert len(prices) == 24
        tomorrow = datetime.now().date() + timedelta(days=1)
        assert all(
            datetime.strptime(p["timestamp"], "%Y-%m-%d %H:%M").date() == tomorrow
            for p in prices
        )

    def test_get_specific_date(self, price_manager):
        """Test retrieving prices for specific date."""
        test_date = date(2025, 1, 15)
        prices = price_manager.get_prices(test_date)

        assert len(prices) == 24
        assert all(
            datetime.strptime(p["timestamp"], "%Y-%m-%d %H:%M").date() == test_date
            for p in prices
        )


class TestSettingsManagement:
    """Test settings management."""

    def test_default_settings(self, price_manager):
        """Test default settings values."""
        settings = price_manager.get_settings()

        assert isinstance(settings, dict)
        assert "area" in settings
        assert "markupRate" in settings
        assert "vatMultiplier" in settings
        assert "additionalCosts" in settings
        assert "taxReduction" in settings
        assert "useActualPrice" in settings
        assert settings["useActualPrice"] is False

    def test_update_settings(self, price_manager):
        """Test updating settings."""
        new_markup = 0.15
        price_manager.update_settings(markup_rate=new_markup)

        settings = price_manager.get_settings()
        assert settings["markupRate"] == new_markup


class TestPriceSources:
    """Test different price sources."""

    def test_mock_source(self, test_prices):
        """Test mock source functionality."""
        source = MockSource(test_prices)
        manager = ElectricityPriceManager(source)

        prices = manager.get_today_prices()
        assert len(prices) == 24
        assert all(p["price"] == 1.0 for p in prices)

    def test_ha_source(self, mock_controller):
        """Test Home Assistant source."""
        # Use the mock_controller fixture instead of ha_controller
        source = HANordpoolSource(mock_controller)
        manager = ElectricityPriceManager(source)

        # Configure the mock_controller to return nordpool prices
        mock_controller.get_nordpool_prices_today = lambda: [1.0] * 24

        prices = manager.get_today_prices()
        assert len(prices) == 24
        # Verify we get prices
        assert all(isinstance(p["price"], float) for p in prices)

    def test_nordpool_api_source(self):
        """Test Nordpool API source with invalid date."""
        source = NordpoolAPISource()
        manager = ElectricityPriceManager(source)

        # Using a far future date should raise an error
        with pytest.raises(ValueError):
            future_date = date(2050, 1, 1)
            manager.get_prices(future_date)

    def test_guru_api_source(self):
        """Test Guru API source with invalid date."""
        source = Guru56APISource()
        manager = ElectricityPriceManager(source)

        # Using a far future date should raise an error
        with pytest.raises(ValueError):
            future_date = date(2050, 1, 1)
            manager.get_prices(future_date)
