"""Electricity price management with configurable sources."""

from datetime import date, datetime, timedelta
import logging
from typing import Any
from zoneinfo import ZoneInfo

import requests

from .settings import PriceSettings

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class PriceSource:
    """Base class for price sources."""

    def get_prices(
        self, target_date: date, area: str, calculator: callable
    ) -> list[dict[str, Any]]:
        """Get prices for the specified date and area."""
        raise NotImplementedError

    def _create_price_list(
        self, prices: list[float], base_date: date, calculator: callable
    ) -> list[dict[str, Any]]:
        """Create standardized price list from raw prices."""
        result = []
        base_timestamp = datetime.combine(base_date, datetime.min.time())

        for hour, price in enumerate(prices):
            timestamp = base_timestamp + timedelta(hours=hour)
            price_entry = {"timestamp": timestamp.strftime("%Y-%m-%d %H:%M")}
            price_entry.update(calculator(price))
            result.append(price_entry)

        return result


class MockSource(PriceSource):
    """Mock price source for testing."""

    def __init__(self, test_prices: list[float]) -> None:
        """Initialize with test data."""
        self.test_prices = test_prices

    def get_prices(
        self, target_date: date, area: str, calculator: callable
    ) -> list[dict[str, Any]]:
        """Return test prices."""
        return self._create_price_list(self.test_prices, target_date, calculator)


class HANordpoolSource(PriceSource):
    """Home Assistant Nordpool sensor price source."""

    def __init__(self, ha_controller) -> None:
        """Initialize with HA controller."""
        self.ha_controller = ha_controller

    def get_prices(
        self, target_date: date | None, area: str, calculator: callable
    ) -> list[dict[str, Any]]:
        """Get prices from HA Nordpool sensor."""
        today = datetime.now().date()

        if target_date is None or target_date == today:
            prices = self.ha_controller.get_nordpool_prices_today()
        elif target_date == today + timedelta(days=1):
            prices = self.ha_controller.get_nordpool_prices_tomorrow()
        else:
            raise ValueError("Can only fetch today's or tomorrow's prices")

        if not prices:
            raise ValueError(f"No prices available for {target_date or today}")

        # Remove VAT from HA prices (they include 25% VAT)
        prices_no_vat = []
        for price in prices:
            prices_no_vat.append(float(price) / 1.25)  # noqa: PERF401

        return self._create_price_list(prices_no_vat, target_date or today, calculator)


class NordpoolAPISource(PriceSource):
    """Nord Pool Group API price source."""

    def __init__(self) -> None:
        """Initialize source."""
        self.base_url = "https://dataportal-api.nordpoolgroup.com/api/DayAheadPrices"

    def get_prices(
        self, target_date: date, area: str, calculator: callable
    ) -> list[dict[str, Any]]:
        """Get prices from Nord Pool API."""
        params = {
            "market": "DayAhead",
            "deliveryArea": area,
            "currency": "SEK",
            "date": target_date.strftime("%Y-%m-%d"),
        }

        try:
            response = requests.get(
                self.base_url,
                params=params,
                headers={
                    "Accept": "application/json",
                    "Origin": "https://data.nordpoolgroup.com",
                    "Referer": "https://data.nordpoolgroup.com/",
                    "User-Agent": "Mozilla/5.0",
                },
                timeout=10,
            )

            if response.status_code == 204:
                raise ValueError(f"No prices found for date {target_date}")

            if response.status_code != 200:
                raise RuntimeError(
                    f"API request failed with status {response.status_code}"
                )

            data = response.json()
            prices = []
            for entry in data.get("multiAreaEntries", []):
                if (
                    entry.get("deliveryStart")
                    and entry.get("entryPerArea", {}).get(area) is not None
                ):
                    price = float(entry["entryPerArea"][area]) / 1000
                    prices.append(price)
                    logger.debug("Processed entry: %s with price %f", entry, price)
                else:
                    logger.warning("Skipping invalid entry: %s", entry)

            if len(prices) != 24:
                raise ValueError(
                    f"Expected 24 prices but got {len(prices)} for date {target_date}"
                )

            return self._create_price_list(prices, target_date, calculator)

        except requests.RequestException as e:
            raise RuntimeError(f"Failed to fetch prices: {e!s}") from e


class Guru56APISource(PriceSource):
    """Spot56k.guru API price source."""

    def __init__(self) -> None:
        """Initialize source."""
        self.base_url = "https://spot.56k.guru/api/v2/hass"

    def get_prices(
        self, target_date: date, area: str, calculator: callable
    ) -> list[dict[str, Any]]:
        """Get prices from Guru API."""
        today = datetime.now().date()
        if target_date not in (today, today + timedelta(days=1)):
            raise ValueError("Can only fetch today or tomorrow's prices")

        params = {"currency": "SEK", "area": area, "multiplier": 1, "decimals": 4}

        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            raise RuntimeError(f"Failed to fetch prices: {e!s}") from e

        result = []
        for item in data["data"]:
            timestamp = datetime.fromisoformat(item["st"]).astimezone(
                ZoneInfo("Europe/Stockholm")
            )

            if timestamp.date() == target_date:
                base_price = float(item["p"])
                price_entry = {"timestamp": timestamp.strftime("%Y-%m-%d %H:%M")}
                price_entry.update(calculator(base_price))
                result.append(price_entry)

        if not result:
            raise ValueError(f"No prices available for {target_date}")

        return result


class ElectricityPriceManager:
    """Main interface for electricity price management."""

    def __init__(self, source: PriceSource) -> None:
        """Initialize manager with price source."""
        self.settings = PriceSettings()
        self.source = source

    def calculate_prices(self, base_price: float) -> dict[str, float]:
        """Calculate buy and sell prices from base price.

        Args:
            base_price: Base Nordpool spot price

        Returns:
            Dictionary with:
            - price: Always the raw Nordpool price
            - buyPrice: Full retail price with markup/VAT/costs
            - sellPrice: Price including tax reduction

        """
        # Always store raw Nordpool price in price field
        price = base_price

        # Calculate full retail price with markup, VAT and costs
        buy_price = (
            base_price + self.settings.markup_rate
        ) * self.settings.vat_multiplier + self.settings.additional_costs

        # Calculate sell price with tax reduction
        sell_price = base_price + self.settings.tax_reduction

        return {
            "price": price,  # Raw Nordpool price
            "buyPrice": buy_price,  # Full retail price
            "sellPrice": sell_price,  # Price with tax reduction
        }

    def get_today_prices(self) -> list[dict[str, Any]]:
        """Get today's prices."""
        return self.source.get_prices(
            target_date=datetime.now().date(),
            area=self.settings.area,
            calculator=self.calculate_prices,
        )

    def get_tomorrow_prices(self) -> list[dict[str, Any]]:
        """Get tomorrow's prices."""
        return self.source.get_prices(
            target_date=datetime.now().date() + timedelta(days=1),
            area=self.settings.area,
            calculator=self.calculate_prices,
        )

    def get_prices(self, target_date: date) -> list[dict[str, Any]]:
        """Get prices for specific date."""
        return self.source.get_prices(
            target_date=target_date,
            area=self.settings.area,
            calculator=self.calculate_prices,
        )

    def get_settings(self) -> dict:
        """Get current settings as dictionary."""
        return self.settings.asdict()

    def update_settings(self, **kwargs) -> None:
        """Update settings from dictionary."""
        self.settings.update(**kwargs)

    def log_price_information(self, title=None):
        """Log a formatted table of current price information.

        Args:
            title: Optional title for the price table

        """
        try:
            prices = self.get_today_prices()
            if not prices:
                logger.warning("No prices available to log")
                return

            # Set default title if none provided
            if title is None:
                title = "Today's Electricity Prices"

            price_data = f"\n{title}:\n"
            price_data += "-" * 50 + "\n"
            price_data += "Hour   | Nordpool Price | Retail Price  | Sell Price\n"
            price_data += "-" * 50 + "\n"

            for entry in prices:
                hour = entry.get("timestamp", "").split()[1][:5]  # Extract HH:MM
                price_data += f"{hour}  | {entry.get('price', 0):.4f} SEK    | {entry.get('buyPrice', 0):.4f} SEK  | {entry.get('sellPrice', 0):.4f} SEK\n"

            logger.info(price_data)
        except (KeyError, ValueError, AttributeError) as e:
            logger.warning("Failed to log price information: %s", str(e))
