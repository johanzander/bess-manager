"""
Test the PriceManager implementation.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from core.bess.price_manager import HomeAssistantSource, MockSource, PriceManager


def test_direct_price_initialization():
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


def test_controller_price_fetching():
    """Test price fetching from controller."""
    mock_controller = MagicMock()
    mock_controller.sensors = {
        "nordpool_kwh_today": "sensor.nordpool_kwh_se4_sek_2_10_025",
        "nordpool_kwh_tomorrow": "sensor.nordpool_kwh_se4_sek_2_10_025",
    }

    today_date = datetime.now().date()
    tomorrow_date = today_date + timedelta(days=1)

    # Create 24 hours of test data
    raw_today_data = [
        {
            "start": f"{today_date.isoformat()}T{h:02d}:00:00+01:00",
            "value": float(h + 1),
        }
        for h in range(24)
    ]
    raw_tomorrow_data = [
        {
            "start": f"{tomorrow_date.isoformat()}T{h:02d}:00:00+01:00",
            "value": float(h + 25),
        }
        for h in range(24)
    ]

    def mock_api_request(method, path):
        if "sensor.nordpool_kwh_se4_sek_2_10_025" in path:
            # Return both today and tomorrow data for the same entity
            return {
                "attributes": {
                    "raw_today": raw_today_data,
                    "raw_tomorrow": raw_tomorrow_data,
                }
            }
        return None

    def mock_get_entity_for_service(sensor_key):
        return "sensor.nordpool_kwh_se4_sek_2_10_025"

    mock_controller._api_request = mock_api_request
    mock_controller._get_entity_for_service = mock_get_entity_for_service

    ha_source = HomeAssistantSource(mock_controller, vat_multiplier=1.25)
    pm = PriceManager(
        price_source=ha_source,
        markup_rate=0.1,
        vat_multiplier=1.25,
        additional_costs=0.5,
        tax_reduction=0.2,
        area="SE4",
    )

    # Get today's prices
    today_prices = pm.get_today_prices()
    assert len(today_prices) == 24
    # Note: HomeAssistantSource now removes VAT from prices before returning them
    assert today_prices[0]["price"] == 1.0 / 1.25

    # Check calculations with the updated formula:
    base_price = 1.0 / 1.25  # Price after VAT removal in HomeAssistantSource
    expected_buy_price = (base_price + 0.1) * 1.25 + 0.5
    assert today_prices[0]["buyPrice"] == expected_buy_price

    # For sell price: add tax reduction to base price (VAT-exclusive)
    expected_sell_price = base_price + 0.2
    assert today_prices[0]["sellPrice"] == expected_sell_price

    # Get tomorrow's prices
    tomorrow_prices = pm.get_tomorrow_prices()
    assert len(tomorrow_prices) == 24
    # Note: HomeAssistantSource now removes VAT from prices before returning them
    assert tomorrow_prices[0]["price"] == 25.0 / 1.25

    # Calculate buy price with the updated formula
    tomorrow_base_price = 25.0 / 1.25  # Price after VAT removal in HomeAssistantSource
    tomorrow_expected_buy_price = (tomorrow_base_price + 0.1) * 1.25 + 0.5
    assert tomorrow_prices[0]["buyPrice"] == tomorrow_expected_buy_price

    # For sell price: add tax reduction to base price (VAT-exclusive)
    tomorrow_expected_sell_price = tomorrow_base_price + 0.2
    assert tomorrow_prices[0]["sellPrice"] == tomorrow_expected_sell_price


def test_mock_source():
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


def test_home_assistant_source_vat_parameter():
    """Test that the VAT multiplier parameter in HomeAssistantSource works correctly."""
    mock_controller = MagicMock()
    mock_controller.sensors = {
        "nordpool_kwh_today": "sensor.nordpool_kwh_se4_sek_2_10_025",
    }

    today_date = datetime.now().date()

    # Create test data with 24 hours, all with price value of 2.0
    raw_today_data = []
    for hour in range(24):
        raw_today_data.append(
            {
                "start": f"{today_date.isoformat()}T{hour:02d}:00:00+01:00",
                "value": 2.0,  # VAT-inclusive price
            }
        )

    def mock_api_request(method, path):
        if "sensor.nordpool_kwh_se4_sek_2_10_025" in path:
            return {"attributes": {"raw_today": raw_today_data}}
        return None

    def mock_get_entity_for_service(sensor_key):
        return "sensor.nordpool_kwh_se4_sek_2_10_025"

    mock_controller._api_request = mock_api_request
    mock_controller._get_entity_for_service = mock_get_entity_for_service

    # Test with default VAT multiplier (1.25)
    ha_source_default = HomeAssistantSource(mock_controller, vat_multiplier=1.25)
    prices_default = ha_source_default.get_prices_for_date(today_date)
    assert prices_default[0] == 1.6  # 2.0 / 1.25 = 1.6

    # Test with custom VAT multiplier (1.20 for 20% VAT)
    ha_source_custom = HomeAssistantSource(mock_controller, vat_multiplier=1.20)
    prices_custom = ha_source_custom.get_prices_for_date(today_date)
    assert round(prices_custom[0], 4) == round(2.0 / 1.20, 4)  # ~1.6667
