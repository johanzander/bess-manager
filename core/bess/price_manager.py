"""
PriceManager for BESS.
A clean implementation with clear separation of concerns and dependency
inversion.
"""

import logging
from datetime import date, datetime, timedelta

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
        """Get prices from Home Assistant for the specified date.
        
        Simple, fault-tolerant approach: fetch sensor data and parse with timestamp validation.
        """
        logger = logging.getLogger(__name__)
        
        current_date = datetime.now().date()
        tomorrow_date = current_date + timedelta(days=1)
        
        # Only support today and tomorrow
        if target_date not in (current_date, tomorrow_date):
            raise ValueError(f"Can only fetch today's or tomorrow's prices, not {target_date}")
        
        try:
            # Fetch sensor data from both sensors
            today_data = self._fetch_sensor_attributes("nordpool_kwh_today")
            tomorrow_data = self._fetch_sensor_attributes("nordpool_kwh_tomorrow")
            
            # Try both sensors - use whichever has valid data for our target date
            for sensor_data, sensor_name in [(today_data, "today"), (tomorrow_data, "tomorrow")]:
                if not sensor_data:
                    continue
                    
                prices = self._extract_prices_for_date(sensor_data, target_date, sensor_name)
                if prices:
                    logger.debug(f"Found {target_date} prices in {sensor_name} sensor")
                    return prices
            
            # No prices found
            raise ValueError(f"No price data available for {target_date}")
            
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            raise ValueError(f"Failed to get price data for {target_date}: {e}") from e

    def _fetch_sensor_attributes(self, sensor_key):
        """Fetch attributes from the configured Nordpool sensor via HA controller's sensor mapping."""
        try:
            # Use HA controller's sensor mapping to get the actual entity ID
            entity_id = self.ha_controller.sensors.get(sensor_key)
            if not entity_id:
                return None
                
            # Fetch sensor state with attributes using the mapped entity ID
            response = self.ha_controller._api_request("get", f"/api/states/{entity_id}")
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
            if isinstance(e, ValueError):
                raise  # Re-raise ValueError as-is
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

        # Define what controller methods this component uses - following the established pattern
        price_methods = [
            "get_nordpool_prices_today",
            "get_nordpool_prices_tomorrow"
        ]

        # Get sensor diagnostics for all methods - this will include the centralized names
        sensor_diagnostics = self.price_source.ha_controller.validate_methods_sensors(price_methods)  # type: ignore

        working_methods = 0
        
        for method_info in sensor_diagnostics:
            # Use the centralized name from the method info
            display_name = method_info.get("name", method_info.get("method_name", "Unknown"))
            
            check_result = {
                "name": display_name,
                "key": method_info.get("sensor_key", method_info.get("method_name")),
                "entity_id": method_info.get("entity_id", "Not mapped"),
                "status": "UNKNOWN",
                "value": None,
                "error": None,
            }

            # Map HA controller method to price manager method
            ha_method = method_info["method_name"]
            price_method = "get_today_prices" if "today" in ha_method else "get_tomorrow_prices"
            is_required = "today" in ha_method

            try:
                method = getattr(self, price_method)
                prices = method()

                if prices and len(prices) >= 24:
                    check_result.update({
                        "status": "OK", 
                        "value": f"{len(prices)} prices available"
                    })
                    working_methods += 1
                elif prices and len(prices) > 0:
                    check_result.update({
                        "status": "WARNING",
                        "value": f"{len(prices)} prices available",
                        "error": "Incomplete price data",
                    })
                else:
                    # For tomorrow prices, missing data is WARNING not ERROR
                    if is_required:
                        check_result.update({
                            "status": "ERROR", 
                            "error": "No price data available", 
                            "value": "N/A"
                        })
                    else:
                        check_result.update({
                            "status": "WARNING", 
                            "value": "Not yet available"
                        })

            except Exception as e:
                # For tomorrow prices, failures are WARNING not ERROR 
                if is_required:
                    check_result.update({
                        "status": "ERROR", 
                        "error": f"Method failed: {e!s}", 
                        "value": "N/A"
                    })
                else:
                    check_result.update({
                        "status": "WARNING", 
                        "value": "Not yet available"
                    })

            price_check["checks"].append(check_result)

        # Determine overall status - only ERROR if today's prices fail
        has_critical_error = any(
            c["status"] == "ERROR" and "Today" in c["name"] for c in price_check["checks"]
        )
        
        if has_critical_error:
            price_check["status"] = "ERROR"
        elif working_methods >= 1:
            price_check["status"] = "OK"
        else:
            price_check["status"] = "WARNING"

        return [price_check]

