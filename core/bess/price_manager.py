"""
PriceManager for BESS.
A clean implementation with clear separation of concerns and dependency
inversion.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Optional


class PriceSource:
    """Abstract base class for price sources.

    This defines the interface that all price sources must implement.
    """

    def get_prices_for_date(self, target_date: date) -> list:
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

    def get_prices_for_date(self, target_date: date) -> list:
        """Get prices for the specified date.

        Args:
            target_date: The date to get prices for

        Returns:
            The test prices provided at initialization
        """
        return self.test_prices


class HomeAssistantSource(PriceSource):
    """Home Assistant Nordpool sensor price source with robust timestamp-based parsing.
    
    This source handles Nordpool prices from Home Assistant, which include VAT.
    It removes VAT from prices before returning them, ensuring all price sources
    consistently return VAT-exclusive prices.
    """

    def __init__(self, ha_controller, vat_multiplier: float = 1.25) -> None:
        """Initialize with Home Assistant controller.

        Args:
            ha_controller: Controller with access to Home Assistant
            vat_multiplier: VAT multiplier used to convert VAT-inclusive prices to VAT-exclusive
                            (default: 1.25 for 25% Swedish VAT)
        """
        self.ha_controller = ha_controller
        self.vat_multiplier = vat_multiplier

    def get_prices_for_date(self, target_date: date) -> list:
        """Get prices from Home Assistant for the specified date using timestamp validation.

        This method fetches both today and tomorrow sensors, parses their actual timestamps,
        and returns the correct data for the target_date. If timestamp parsing fails,
        it fails fast rather than guessing.

        Args:
            target_date: The date to get prices for

        Returns:
            List of hourly prices for the specified date

        Raises:
            ValueError: If prices are not available for the date
        """
        logger = logging.getLogger(__name__)

        try:
            # Fetch both today and tomorrow sensor data to get all available price data
            today_data = self._fetch_sensor_attributes("nordpool_kwh_today")
            tomorrow_data = self._fetch_sensor_attributes("nordpool_kwh_tomorrow")

            # Try to find target_date in either sensor using timestamp parsing
            target_prices = None
            found_in_sensor = None

            # Check today sensor for our target date
            if today_data:
                prices = self._extract_prices_for_date(
                    today_data, target_date, "today sensor"
                )
                if prices:
                    target_prices = prices
                    found_in_sensor = "today sensor"
                    logger.debug(f"Found {target_date} prices in today sensor")

            # Check tomorrow sensor for our target date (might override if both have same date)
            if tomorrow_data:
                prices = self._extract_prices_for_date(
                    tomorrow_data, target_date, "tomorrow sensor"
                )
                if prices:
                    target_prices = prices
                    found_in_sensor = "tomorrow sensor"
                    logger.debug(f"Found {target_date} prices in tomorrow sensor")

            if target_prices:
                logger.info(
                    f"Successfully extracted {len(target_prices)} prices for {target_date} from {found_in_sensor}"
                )
                return target_prices

            # No fallbacks - fail with diagnostic information
            logger.error(f"Failed to find price data for {target_date} in any sensor")

            # Provide diagnostic info for debugging
            today_available = self._get_sensor_diagnostic_info(
                today_data, "today sensor"
            )
            tomorrow_available = self._get_sensor_diagnostic_info(
                tomorrow_data, "tomorrow sensor"
            )

            error_msg = (
                f"No price data found for {target_date}. "
                f"Today sensor: {today_available}. "
                f"Tomorrow sensor: {tomorrow_available}."
            )

            raise ValueError(error_msg)

        except Exception as e:
            logger.error(f"Error fetching prices for {target_date}: {e}")
            if isinstance(e, ValueError):
                raise  # Re-raise ValueError with original message
            raise ValueError(f"Failed to get price data for {target_date}: {e}") from e

    def _fetch_sensor_attributes(self, sensor_key):
        """Fetch attributes from a specific HA sensor."""
        try:
            entity_id = self.ha_controller.sensors.get(sensor_key)
            if not entity_id:
                return None

            response = self.ha_controller._api_request(
                "get", f"/api/states/{entity_id}"
            )
            if not response or "attributes" not in response:
                return None

            return response["attributes"]

        except Exception:
            return None

    def _extract_prices_for_date(self, sensor_attributes, target_date, sensor_name):
        """Extract prices for a specific date from sensor attributes using timestamp validation."""
        try:
            # First try raw_today with timestamp parsing
            raw_today = sensor_attributes.get("raw_today")
            if raw_today:
                prices = self._parse_raw_data_for_date(raw_today, target_date)
                if prices:
                    return prices

            # Then try raw_tomorrow with timestamp parsing
            raw_tomorrow = sensor_attributes.get("raw_tomorrow")
            if raw_tomorrow:
                prices = self._parse_raw_data_for_date(raw_tomorrow, target_date)
                if prices:
                    return prices

            # Fallback to regular arrays (educated guess based on current date)
            today_array = sensor_attributes.get("today")
            tomorrow_array = sensor_attributes.get("tomorrow")

            current_date = datetime.now().date()
            tomorrow_date = current_date + timedelta(days=1)

            # Try to match target_date with available arrays
            if target_date == current_date and today_array:
                return self._handle_dst_transitions(today_array)
            elif target_date == tomorrow_date and tomorrow_array:
                return self._handle_dst_transitions(tomorrow_array)

            return None

        except Exception:
            return None

    def _parse_raw_data_for_date(self, raw_data, target_date):
        """Parse raw data and return prices if it matches target_date."""
        if not raw_data or not isinstance(raw_data, list) or not raw_data:
            return None

        try:
            # Parse first timestamp to determine the actual date
            first_entry = raw_data[0]
            start_time_str = first_entry.get("start")
            if not start_time_str:
                return None

            # Parse timestamp - handle timezone
            try:
                if start_time_str.endswith(("+02:00", "+01:00")):
                    start_time_str = start_time_str[:-6]
                start_time = datetime.fromisoformat(start_time_str)
            except ValueError:
                return None

            actual_date = start_time.date()

            # Only return prices if this raw data is for our target date
            if actual_date != target_date:
                return None

            # Extract prices
            prices = [float(entry["value"]) for entry in raw_data if "value" in entry]
            
            # Nordpool prices from Home Assistant include VAT - remove it
            # to standardize all price sources to return VAT-exclusive prices
            prices = [price / self.vat_multiplier for price in prices]

            # Handle DST transitions
            return self._handle_dst_transitions(prices)

        except Exception:
            return None

    def _handle_dst_transitions(self, prices):
        """Handle DST transitions to ensure we always have 24 hours."""
        if not prices:
            return []

        if len(prices) == 24:
            return prices
        elif len(prices) == 23:
            # Spring forward - duplicate middle hour
            middle_idx = len(prices) // 2
            prices.insert(middle_idx, prices[middle_idx])
            return prices
        elif len(prices) == 25:
            # Fall back - remove middle hour
            middle_idx = len(prices) // 2
            prices.pop(middle_idx)
            return prices
        else:
            # Unexpected count - fail fast instead of guessing
            raise ValueError(
                f"Unexpected price count: {len(prices)} hours. Expected 23, 24, or 25 for DST transitions."
            )

    def _get_sensor_diagnostic_info(self, sensor_data, sensor_name):
        """Get diagnostic information about what data is available in a sensor."""
        if not sensor_data:
            return "no data"

        info = []

        # Check for raw data with timestamps
        if sensor_data.get("raw_today"):
            try:
                first_entry = sensor_data["raw_today"][0]
                start_time = first_entry.get("start", "unknown")
                info.append(f"raw_today({start_time[:10]})")
            except (IndexError, KeyError, TypeError, AttributeError) as e:
                info.append(f"raw_today(invalid: {type(e).__name__})")

        if sensor_data.get("raw_tomorrow"):
            try:
                first_entry = sensor_data["raw_tomorrow"][0]
                start_time = first_entry.get("start", "unknown")
                info.append(f"raw_tomorrow({start_time[:10]})")
            except (IndexError, KeyError, TypeError, AttributeError) as e:
                info.append(f"raw_tomorrow(invalid: {type(e).__name__})")

        # Check for regular arrays
        if sensor_data.get("today"):
            info.append("today array")
        if sensor_data.get("tomorrow"):
            info.append("tomorrow array")

        return ", ".join(info) if info else "no price data"


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
            base_price: Raw Nordpool price (VAT-exclusive)

        Returns:
            Calculated retail price
        """
        result = (base_price + self.markup_rate) * self.vat_multiplier
        return result + self.additional_costs

    def _calculate_sell_price(self, base_price: float) -> float:
        """Calculate sell-back price from Nordpool base price.

        Args:
            base_price: Raw Nordpool price (VAT-exclusive)

        Returns:
            Calculated sell-back price
        """
        return base_price + self.tax_reduction

    def get_price_data(
        self, target_date: Optional[date] = None  # noqa: UP007
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
        self, target_date: Optional[date] = None  # noqa: UP007
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
        target_date: Optional[date] = None,  # noqa: UP007
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
        target_date: Optional[date] = None,  # noqa: UP007
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
