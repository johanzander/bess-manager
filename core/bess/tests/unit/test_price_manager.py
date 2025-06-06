"""
Test the PriceManager implementation.
"""

import unittest
from unittest.mock import MagicMock

from core.bess.price_manager import HomeAssistantSource, MockSource, PriceManager


class TestPriceManager(unittest.TestCase):
    def test_direct_price_initialization(self):
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
        self.assertEqual(pm.buy_prices[0], (1.0 + 0.1) * 1.25 + 0.5)
        self.assertEqual(pm.sell_prices[0], 1.0 + 0.2)

        # Check compatibility methods
        self.assertEqual(pm.get_buy_prices(), pm.buy_prices)
        self.assertEqual(pm.get_sell_prices(), pm.sell_prices)

    def test_controller_price_fetching(self):
        """Test price fetching from controller."""
        mock_controller = MagicMock()
        mock_controller.get_nordpool_prices_today.return_value = [1.0, 2.0, 3.0, 4.0]
        mock_controller.get_nordpool_prices_tomorrow.return_value = [5.0, 6.0, 7.0, 8.0]

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
        self.assertEqual(len(today_prices), 4)
        self.assertEqual(today_prices[0]["price"], 1.0)
        self.assertEqual(today_prices[0]["buyPrice"], (1.0 + 0.1) * 1.25 + 0.5)
        self.assertEqual(today_prices[0]["sellPrice"], 1.0 + 0.2)

        # Get tomorrow's prices
        tomorrow_prices = pm.get_tomorrow_prices()
        self.assertEqual(len(tomorrow_prices), 4)
        self.assertEqual(tomorrow_prices[0]["price"], 5.0)
        self.assertEqual(tomorrow_prices[0]["buyPrice"], (5.0 + 0.1) * 1.25 + 0.5)
        self.assertEqual(tomorrow_prices[0]["sellPrice"], 5.0 + 0.2)

    def test_mock_source(self):
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
        self.assertEqual(len(today_prices), 4)
        self.assertEqual(today_prices[0]["price"], 1.0)
        self.assertEqual(today_prices[0]["buyPrice"], (1.0 + 0.1) * 1.25 + 0.5)
        self.assertEqual(today_prices[0]["sellPrice"], 1.0 + 0.2)


if __name__ == "__main__":
    print("Running tests...")
    unittest.main()
