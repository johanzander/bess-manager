"""
PriceManager for BESS.
A clean implementation with clear separation of concerns and dependency
inversion.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional


class PriceSource:
    """Abstract base class for price sources.

    This defines the interface that all price sources must implement.
    """

    def get_prices_for_date(self, target_date: datetime.date) -> list:
        """Get prices for a specific date.

        Args:
            target_date: The date to get prices for

        Returns:
            List of hourly prices for the specified date

        Raises:
            NotImplementedError: If the source doesn't implement this method
        """
        raise NotImplementedError("Price sources must implement get_prices_for_date")


class MockSource(PriceSource):
    """Mock price source for testing."""

    def __init__(self, test_prices: list) -> None:
        """Initialize with test data.

        Args:
            test_prices: List of test prices to return
        """
        self.test_prices = test_prices

    def get_prices_for_date(self, target_date: datetime.date) -> list:
        """Get prices for the specified date.

        Args:
            target_date: The date to get prices for

        Returns:
            The test prices provided at initialization
        """
        return self.test_prices


class HomeAssistantSource(PriceSource):
    """Home Assistant Nordpool sensor price source."""

    def __init__(self, ha_controller) -> None:
        """Initialize with Home Assistant controller.

        Args:
            ha_controller: Controller with access to Home Assistant
        """
        self.ha_controller = ha_controller

    def get_prices_for_date(self, target_date: datetime.date) -> list:
        """Get prices from Home Assistant for the specified date.

        Args:
            target_date: The date to get prices for

        Returns:
            List of hourly prices for the specified date

        Raises:
            ValueError: If prices are not available for the date
        """
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)

        # Choose method based on date
        if target_date == today:
            prices = self.ha_controller.get_nordpool_prices_today()
        elif target_date == tomorrow:
            prices = self.ha_controller.get_nordpool_prices_tomorrow()
        else:
            raise ValueError(
                f"Can only fetch today's or tomorrow's prices, not {target_date}"
            )

        if not prices:
            no_prices_msg = f"No prices available for {target_date}"
            raise ValueError(no_prices_msg)

        return prices


class PriceManager:
    """Price manager for calculating buy/sell prices based on Nordpool prices.

    This class is responsible for calculating retail and sell-back prices
    based on raw Nordpool prices and pricing parameters.
    """

    def __init__(
        self,
        price_source: PriceSource,
        markup_rate: float = 0.1,
        vat_multiplier: float = 1.25,
        additional_costs: float = 0.5,
        tax_reduction: float = 0.2,
        area: str = "SE3",
    ) -> None:
        """Initialize the price manager.

        Args:
            price_source: Source of raw Nordpool prices
            markup_rate: Markup rate applied to buy prices
            vat_multiplier: VAT multiplier applied to buy prices
            additional_costs: Additional fixed costs added to buy prices
            tax_reduction: Tax reduction applied to sell prices
            area: Price area code (default: "SE3")
        """
        self.price_source = price_source
        self.markup_rate = markup_rate
        self.vat_multiplier = vat_multiplier
        self.additional_costs = additional_costs
        self.tax_reduction = tax_reduction
        self.area = area
        self._logger = logging.getLogger(__name__)

        # Cache for today's prices
        self._today_prices = None
        self._today_date = None

    def _calculate_buy_price(self, base_price: float) -> float:
        """Calculate retail buy price from Nordpool base price.

        Args:
            base_price: Raw Nordpool price

        Returns:
            Calculated retail price
        """
        result = (base_price + self.markup_rate) * self.vat_multiplier
        return result + self.additional_costs

    def _calculate_sell_price(self, base_price: float) -> float:
        """Calculate sell-back price from Nordpool base price.

        Args:
            base_price: Raw Nordpool price

        Returns:
            Calculated sell-back price
        """
        return base_price + self.tax_reduction

    def get_price_data(
        self, target_date: Optional[datetime.date] = None  # noqa: UP007
    ) -> list:
        """Get formatted price data for the specified date.

        Args:
            target_date: Date to get prices for (default: today)

        Returns:
            List of dictionaries with timestamp, price, buyPrice, and sellPrice

        Raises:
            ValueError: If prices are not available
        """
        if target_date is None:
            target_date = datetime.now().date()

        # Use cached values for today if available
        if self._today_date == target_date and self._today_prices is not None:
            return self._today_prices

        try:
            # Get raw prices from the source
            raw_prices = self.price_source.get_prices_for_date(target_date)

            # Format prices with timestamp and calculations
            price_data = []
            base_timestamp = datetime.combine(target_date, datetime.min.time())

            for hour, price in enumerate(raw_prices):
                timestamp = base_timestamp + timedelta(hours=hour)
                price_entry = {
                    "timestamp": timestamp.strftime("%Y-%m-%d %H:%M"),
                    "price": price,
                    "buyPrice": self._calculate_buy_price(price),
                    "sellPrice": self._calculate_sell_price(price),
                }
                price_data.append(price_entry)

            # Cache today's prices
            if target_date == datetime.now().date():
                self._today_prices = price_data
                self._today_date = target_date

            return price_data

        except Exception as e:
            self._logger.error(f"Error getting prices for {target_date}: {e}")
            raise ValueError(f"Failed to get price data: {e}") from e

    def get_today_prices(self) -> list:
        """Get prices for the current day.

        Returns:
            List of price entries for today
        """
        return self.get_price_data(datetime.now().date())

    def get_tomorrow_prices(self) -> list:
        """Get prices for the next day.

        Returns:
            List of price entries for tomorrow
        """
        tomorrow = datetime.now().date() + timedelta(days=1)
        return self.get_price_data(tomorrow)

    def get_prices(
        self, target_date: Optional[datetime.date] = None  # noqa: UP007
    ) -> list:
        """Get raw price data for a specified date.

        This is a compatibility method for existing code.

        Args:
            target_date: Date to get prices for (default: today)

        Returns:
            List of price entries
        """
        return self.get_price_data(target_date)

    def get_buy_prices(
        self,
        target_date: Optional[datetime.date] = None,  # noqa: UP007
        raw_prices: list | None = None,
    ) -> list:
        """Get buy prices for the specified date or from raw prices.

        Args:
            target_date: Date to get prices for (default: today)
            raw_prices: Optional list of raw prices to calculate buy prices from

        Returns:
            List of buy prices
        """
        if raw_prices is not None:
            # Calculate buy prices directly from the provided raw prices
            return [self._calculate_buy_price(price) for price in raw_prices]
        else:
            # Get buy prices from the price data for the specified date
            price_data = self.get_price_data(target_date)
            return [entry["buyPrice"] for entry in price_data]

    def get_sell_prices(
        self,
        target_date: Optional[datetime.date] = None,  # noqa: UP007
        raw_prices: list | None = None,
    ) -> list:
        """Get sell prices for the specified date or from raw prices.

        Args:
            target_date: Date to get prices for (default: today)
            raw_prices: Optional list of raw prices to calculate sell prices from

        Returns:
            List of sell prices
        """
        if raw_prices is not None:
            # Calculate sell prices directly from the provided raw prices
            return [self._calculate_sell_price(price) for price in raw_prices]
        else:
            # Get sell prices from the price data for the specified date
            price_data = self.get_price_data(target_date)
            return [entry["sellPrice"] for entry in price_data]

    @property
    def buy_prices(self) -> list:
        """Buy prices for today."""
        return self.get_buy_prices()

    @property
    def sell_prices(self) -> list:
        """Sell prices for today."""
        return self.get_sell_prices()

    def log_price_information(self, title: str | None = None) -> None:
        """Log a formatted table of current price information.

        Args:
            title: Optional title for the price table
        """
        try:
            prices = self.get_price_data()
            if not prices:
                self._logger.warning("No prices available to log")
                return

            # Set default title if none provided
            if title is None:
                title = "Today's Electricity Prices"

            price_data = f"\n{title}:\n"
            price_data += "-" * 50 + "\n"
            price_data += "Hour   | Nordpool Price | Retail Price  | Sell Price\n"
            price_data += "-" * 50 + "\n"

            for entry in prices:
                hour = entry["timestamp"].split()[1][:5]
                price_str = f"{hour}  | {entry['price']:.4f} SEK    | "
                buy_str = f"{entry['buyPrice']:.4f} SEK  | "
                sell_str = f"{entry['sellPrice']:.4f} SEK\n"
                price_data += price_str + buy_str + sell_str

            self._logger.info(price_data)
        except Exception as e:
            self._logger.warning(f"Failed to log price information: {e}")
