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
    )

    # Check calculations
    assert pm.buy_prices[0] == (1.0 + 0.1) * 1.25 + 0.5
    assert pm.sell_prices[0] == 1.0 + 0.2

    # Check compatibility methods
    assert pm.get_buy_prices() == pm.buy_prices
    assert pm.get_sell_prices() == pm.sell_prices


def test_controller_price_fetching():
    """Test price fetching from controller."""
    mock_controller = MagicMock()
    mock_controller.sensors = {
        'nordpool_kwh_today': 'sensor.nordpool_kwh_se3_today',
        'nordpool_kwh_tomorrow': 'sensor.nordpool_kwh_se3_tomorrow'
    }
    
    today_date = datetime.now().date()
    tomorrow_date = today_date + timedelta(days=1)
    
    # Create 24 hours of test data
    raw_today_data = [
        {'start': f'{today_date.isoformat()}T{h:02d}:00:00+01:00', 'value': float(h + 1)} 
        for h in range(24)
    ]
    raw_tomorrow_data = [
        {'start': f'{tomorrow_date.isoformat()}T{h:02d}:00:00+01:00', 'value': float(h + 25)} 
        for h in range(24)
    ]
    
    def mock_api_request(method, path):
        if 'nordpool_kwh_se3_today' in path:
            return {'attributes': {'raw_today': raw_today_data}}
        elif 'nordpool_kwh_se3_tomorrow' in path:
            return {'attributes': {'raw_tomorrow': raw_tomorrow_data}}
        return None
    
    mock_controller._api_request = mock_api_request

    ha_source = HomeAssistantSource(mock_controller)
    pm = PriceManager(
        price_source=ha_source,
        markup_rate=0.1,
        vat_multiplier=1.25,
        additional_costs=0.5,
        tax_reduction=0.2,
    )

    # Get today's prices
    today_prices = pm.get_today_prices()
    assert len(today_prices) == 24
    assert today_prices[0]["price"] == 1.0
    assert today_prices[0]["buyPrice"] == (1.0 + 0.1) * 1.25 + 0.5
    assert today_prices[0]["sellPrice"] == 1.0 + 0.2

    # Get tomorrow's prices
    tomorrow_prices = pm.get_tomorrow_prices()
    assert len(tomorrow_prices) == 24
    assert tomorrow_prices[0]["price"] == 25.0
    assert tomorrow_prices[0]["buyPrice"] == (25.0 + 0.1) * 1.25 + 0.5
    assert tomorrow_prices[0]["sellPrice"] == 25.0 + 0.2


def test_mock_source():
    """Test using a MockSource."""
    mock_source = MockSource([1.0, 2.0, 3.0, 4.0])

    pm = PriceManager(
        price_source=mock_source,
        markup_rate=0.1,
        vat_multiplier=1.25,
        additional_costs=0.5,
        tax_reduction=0.2,
    )

    # Get today's prices
    today_prices = pm.get_today_prices()
    assert len(today_prices) == 4
    assert today_prices[0]["price"] == 1.0
    assert today_prices[0]["buyPrice"] == (1.0 + 0.1) * 1.25 + 0.5
    assert today_prices[0]["sellPrice"] == 1.0 + 0.2