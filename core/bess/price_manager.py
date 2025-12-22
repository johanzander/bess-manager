"""
PriceManager for BESS.
A clean implementation with clear separation of concerns and dependency
inversion.
"""

import logging
from datetime import date, datetime, timedelta

from .exceptions import PriceDataUnavailableError, SystemConfigurationError

logger = logging.getLogger(__name__)


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

    def perform_health_check(self) -> dict:
        """Perform health check on the price source.

        Returns:
            dict: Health check result with status and checks

        Raises:
            NotImplementedError: If the source doesn't implement this method
        """
        raise NotImplementedError("Price sources must implement perform_health_check")


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

    def perform_health_check(self) -> dict:
        """Perform health check on mock source.

        Returns:
            dict: Always returns OK status for mock source
        """
        return {
            "status": "OK",
            "checks": [
                {
                    "component": "MockSource",
                    "status": "OK",
                    "message": f"Mock source with {len(self.test_prices)} test prices",
                }
            ],
        }


class HomeAssistantSource(PriceSource):
    """Home Assistant Nordpool sensor price source with robust timestamp-based parsing.

    This source handles Nordpool prices from Home Assistant, which include VAT.
    It removes VAT from prices before returning them, ensuring all price sources
    consistently return VAT-exclusive prices.
    """

    def __init__(self, ha_controller, vat_multiplier: float) -> None:
        """Initialize with Home Assistant controller.

        Args:
            ha_controller: Controller with access to Home Assistant
            vat_multiplier: VAT multiplier used to convert VAT-inclusive prices to VAT-exclusive
                            (must be provided from config.yaml)
        """
        self.ha_controller = ha_controller
        self.vat_multiplier = vat_multiplier

    def get_prices_for_date(self, target_date: date) -> list:
        """Get prices from Home Assistant for the specified date.

        Simple, fault-tolerant approach: fetch sensor data and parse with timestamp validation.
        """
        logger = logging.getLogger(__name__)

        current_date = datetime.now().date()
        tomorrow_date = current_date + timedelta(days=1)

        # Only support today and tomorrow
        if target_date not in (current_date, tomorrow_date):
            raise SystemConfigurationError(
                message=f"Can only fetch today's or tomorrow's prices, not {target_date}"
            )

        try:
            # Fetch sensor data from both sensors
            today_data = self._fetch_sensor_attributes("nordpool_kwh_today")
            tomorrow_data = self._fetch_sensor_attributes("nordpool_kwh_tomorrow")

            # Try both sensors - use whichever has valid data for our target date
            for sensor_data, sensor_name in [
                (today_data, "today"),
                (tomorrow_data, "tomorrow"),
            ]:
                if not sensor_data:
                    continue

                prices = self._extract_prices_for_date(
                    sensor_data, target_date, sensor_name
                )
                if prices:
                    logger.debug(f"Found {target_date} prices in {sensor_name} sensor")
                    return prices

            # No prices found
            raise PriceDataUnavailableError(date=target_date)

        except Exception as e:
            if isinstance(e, PriceDataUnavailableError | SystemConfigurationError):
                raise
            raise PriceDataUnavailableError(
                date=target_date,
                message=f"Failed to get price data for {target_date}: {e}",
            ) from e

    def _fetch_sensor_attributes(self, sensor_key):
        """Fetch attributes from the configured Nordpool sensor via HA controller's sensor mapping."""
        try:
            # Use HA controller's sensor mapping to get the actual entity ID
            entity_id = self.ha_controller.sensors.get(sensor_key)
            if not entity_id:
                return None

            # Fetch sensor state with attributes using the mapped entity ID
            response = self.ha_controller._api_request(
                "get", f"/api/states/{entity_id}"
            )
            if not response or "attributes" not in response:
                return None

            return response["attributes"]
        except Exception:
            return None

    def _extract_prices_for_date(self, sensor_attributes, target_date, sensor_name):
        """Extract prices for a specific date from sensor attributes."""
        if not sensor_attributes:
            return None

        try:
            # Try raw data first (with timestamp validation)
            for raw_key in ["raw_today", "raw_tomorrow"]:
                raw_data = sensor_attributes.get(raw_key)
                if raw_data:
                    prices = self._parse_raw_data_for_date(raw_data, target_date)
                    if prices:
                        return prices

            # Fallback to regular arrays (simple date matching)
            current_date = datetime.now().date()
            tomorrow_date = current_date + timedelta(days=1)

            if target_date == current_date:
                prices = sensor_attributes.get("today")
                if prices:
                    return self._handle_dst_transitions(prices)

            elif target_date == tomorrow_date:
                prices = sensor_attributes.get("tomorrow")
                if prices:
                    return self._handle_dst_transitions(prices)

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
        """Handle DST transitions for quarterly resolution (92-100 periods).

        Nordpool provides quarterly prices (15-minute intervals):
        - Normal day: 96 periods (24 hours × 4)
        - DST spring (23h): 92 periods
        - DST fall (25h): 100 periods

        Returns prices as-is since Nordpool already provides quarterly resolution.
        """
        if not prices:
            return []

        # Validate quarterly period count (92-100 for DST variations)
        if 92 <= len(prices) <= 100:
            return prices
        else:
            # Unexpected count - fail fast instead of guessing
            raise PriceDataUnavailableError(
                message=f"Unexpected price count: {len(prices)} periods. Expected 92-100 for quarterly resolution with DST."
            )

    def _get_sensor_diagnostic_info(self, sensor_data, sensor_name):
        """Get simple diagnostic information about sensor data availability."""
        if not sensor_data:
            return "no data"

        info = []
        if sensor_data.get("today"):
            info.append("today array")
        if sensor_data.get("tomorrow"):
            info.append("tomorrow array")
        if sensor_data.get("raw_today"):
            info.append("raw_today")
        if sensor_data.get("raw_tomorrow"):
            info.append("raw_tomorrow")

        return ", ".join(info) if info else "no price data"

    def perform_health_check(self) -> dict:
        """Perform health check on Home Assistant source.

        Returns:
            dict: Health check result with status and checks
        """
        try:
            # Test fetching today's prices (accepts any count - DST may give 23/24/25)
            today_prices = self.get_prices_for_date(date.today())
            if today_prices:
                return {
                    "status": "OK",
                    "checks": [
                        {
                            "component": "HomeAssistantSource",
                            "status": "OK",
                            "message": f"Successfully fetched {len(today_prices)} prices for today",
                        }
                    ],
                }
            else:
                return {
                    "status": "ERROR",
                    "checks": [
                        {
                            "component": "HomeAssistantSource",
                            "status": "ERROR",
                            "message": "No price data available for today",
                        }
                    ],
                }
        except Exception as e:
            return {
                "status": "ERROR",
                "checks": [
                    {
                        "component": "HomeAssistantSource",
                        "status": "ERROR",
                        "message": f"Failed to fetch prices: {e}",
                    }
                ],
            }


class PriceManager:
    """Price manager for calculating buy/sell prices based on Nordpool prices.

    This class is responsible for calculating retail and sell-back prices
    based on raw Nordpool prices and pricing parameters.
    """

    def __init__(
        self,
        price_source: PriceSource,
        markup_rate: float,
        vat_multiplier: float,
        additional_costs: float,
        tax_reduction: float,
        area: str,
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

        # Cache for tomorrow's prices
        self._tomorrow_prices = None
        self._tomorrow_date = None

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

    def get_price_data(self, target_date: date | None = None) -> list:
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

        # Use cached values for tomorrow if available
        if self._tomorrow_date == target_date and self._tomorrow_prices is not None:
            return self._tomorrow_prices

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
            today = datetime.now().date()
            tomorrow = today + timedelta(days=1)

            if target_date == today:
                self._today_prices = price_data
                self._today_date = target_date
            elif target_date == tomorrow:
                self._tomorrow_prices = price_data
                self._tomorrow_date = target_date

            return price_data

        except Exception as e:
            if isinstance(e, PriceDataUnavailableError | SystemConfigurationError):
                raise  # Re-raise specific exceptions as-is
            raise PriceDataUnavailableError(
                message=f"Failed to get price data: {e}"
            ) from e

    def get_today_prices(self) -> list:
        """Get prices for the current day.

        Returns:
            List of price entries for today
        """
        return self.get_price_data(datetime.now().date())

    def get_tomorrow_prices(self) -> list:
        """Get prices for the next day.

        Returns:
            List of price entries for tomorrow, or empty list if not yet available
        """
        tomorrow = datetime.now().date() + timedelta(days=1)
        try:
            return self.get_price_data(tomorrow)
        except ValueError:
            return []  # Return empty list instead of raising error

    def get_prices(self, target_date: date | None = None) -> list:
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
        target_date: date | None = None,
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
        target_date: date | None = None,
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


    def get_available_prices(self) -> tuple[list[float], list[float]]:
        """Get all available prices at quarterly resolution starting at today 00:00.

        Nordpool provides quarterly prices (96 periods/day) directly.
        Automatically tries tomorrow, falls back to today only.

        Returns:
            (buy_prices, sell_prices) tuple where:
            - Index 0 = today 00:00
            - Index 96 = tomorrow 00:00 (if available)
            - Length: 96 (today only) or 192 (today + tomorrow)

        Example at 14:00:
            buy, sell = get_available_prices()
            # buy[0] = today 00:00
            # buy[56] = today 14:00 (current period)
            # Caller slices: buy[56:] for optimization from now
        """
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)

        # Get today's quarterly prices (already quarterly resolution from Nordpool)
        buy_prices = self.get_buy_prices(target_date=today)
        sell_prices = self.get_sell_prices(target_date=today)

        # Try tomorrow (full day from 00:00)
        # Fetch price data once and extract both buy and sell to avoid duplicate API calls
        try:
            tomorrow_price_data = self.get_price_data(target_date=tomorrow)
            tomorrow_buy = [entry["buyPrice"] for entry in tomorrow_price_data]
            tomorrow_sell = [entry["sellPrice"] for entry in tomorrow_price_data]

            # Concatenate if tomorrow available
            buy_prices = buy_prices + tomorrow_buy
            sell_prices = sell_prices + tomorrow_sell

            logger.info(
                "Got prices for today + tomorrow (%d + %d periods)",
                len(buy_prices) - len(tomorrow_buy),
                len(tomorrow_buy),
            )
        except Exception as e:
            # Tomorrow not available - just use today
            logger.info(
                "Tomorrow prices not available (%s), using today only (%d periods)",
                str(e),
                len(buy_prices),
            )

        return (buy_prices, sell_prices)

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

    def check_health(self) -> list:
        """Check price management capabilities."""

        price_check = {
            "name": "Electricity Price Data",
            "description": "Retrieves electricity prices for optimization",
            "required": True,
            "status": "UNKNOWN",
            "checks": [],
            "last_run": datetime.now().isoformat(),
        }

        # Get health check from price source
        try:
            source_health = self.price_source.perform_health_check()
            price_check.update(
                {
                    "status": source_health["status"],
                    "checks": source_health["checks"],
                }
            )
            return [price_check]
        except Exception as e:
            price_check.update(
                {
                    "status": "ERROR",
                    "checks": [
                        {
                            "name": "Price Source Health Check",
                            "status": "ERROR",
                            "error": f"Health check failed: {e}",
                            "value": "N/A",
                        }
                    ],
                }
            )
            return [price_check]
