"""
Official Home Assistant Nordpool integration price source.

This source uses the official HA Nordpool integration's service actions
instead of sensor attributes, providing compatibility with the core integration.
"""

import logging
from datetime import date, datetime, timedelta

from .price_manager import PriceSource

logger = logging.getLogger(__name__)


class OfficialNordpoolSource(PriceSource):
    """Price source that uses the official Home Assistant Nordpool integration.

    Uses the nordpool.get_prices_for_date service action instead of sensor attributes.
    The official integration was added to HA Core and provides different API than custom components.
    """

    def __init__(
        self, ha_controller, config_entry_id: str, vat_multiplier: float = 1.25
    ) -> None:
        """Initialize with Home Assistant controller and config entry ID.

        Args:
            ha_controller: Controller with access to Home Assistant services
            config_entry_id: Configuration entry ID for the Nordpool integration
            vat_multiplier: VAT multiplier (prices from official integration are VAT-exclusive)
        """
        self.ha_controller = ha_controller
        self.config_entry_id = config_entry_id
        self.vat_multiplier = vat_multiplier

    def get_prices_for_date(self, target_date: date) -> list[float]:
        """Get prices from official Nordpool integration for the specified date.

        Uses the nordpool.get_prices_for_date service action.

        Args:
            target_date: The date to get prices for

        Returns:
            List of hourly prices in SEK/kWh (VAT-exclusive)

        Raises:
            ValueError: If prices cannot be fetched
        """
        logger.info(
            f"Fetching Nordpool prices for {target_date} using official integration"
        )

        # Only support today and tomorrow (official integration limitation)
        current_date = datetime.now().date()
        tomorrow_date = current_date + timedelta(days=1)

        if target_date not in (current_date, tomorrow_date):
            raise ValueError(
                f"Official Nordpool integration only supports today and tomorrow, not {target_date}"
            )

        try:
            # Call the nordpool.get_prices_for_date service
            date_str = target_date.strftime("%Y-%m-%d")

            service_data = {
                "config_entry": self.config_entry_id,
                "date": date_str,
            }

            # Make service call
            response = self.ha_controller._service_call_with_retry(
                "nordpool",
                "get_prices_for_date",
                **service_data,
                return_response=True,
            )

            if not response or "service_response" not in response:
                raise ValueError(
                    f"No response from nordpool.get_prices_for_date for {target_date}"
                )

            service_response = response["service_response"]

            # Extract price entries from service response
            # Official integration returns data under area code (e.g., "SE4")
            price_entries = []

            # Look for data under area codes (SE1, SE2, SE3, SE4, etc.)
            for key, value in service_response.items():
                if isinstance(value, list) and key.startswith("SE"):
                    price_entries = value
                    logger.debug(f"Found price data under area code: {key}")
                    break

            # Fallback: try "prices" key (in case response format changes)
            if not price_entries:
                price_entries = service_response.get("prices", [])

            if not price_entries:
                logger.error(f"Service response keys: {list(service_response.keys())}")
                raise ValueError(
                    f"No price entries returned for {target_date}. Available keys: {list(service_response.keys())}"
                )

            # Convert price entries to hourly list
            prices = []
            for entry in price_entries:
                # Official integration returns prices in [Currency]/MWh
                price_mwh = float(entry["price"])
                # Convert to SEK/kWh
                price_kwh = price_mwh / 1000.0
                prices.append(price_kwh)

            # Nordpool changed from hourly to quarter-hourly reporting (4 values per hour)
            # Convert 96 quarter-hourly prices to 24 hourly prices for backward compatibility
            if len(prices) == 96:
                logger.info(
                    f"Converting 96 quarter-hourly prices to 24 hourly prices by averaging"
                )
                hourly_prices = []
                for hour in range(24):
                    # Average the 4 quarter-hour values for this hour
                    quarter_start = hour * 4
                    quarter_end = quarter_start + 4
                    hour_quarters = prices[quarter_start:quarter_end]
                    hourly_avg = sum(hour_quarters) / len(hour_quarters)
                    hourly_prices.append(hourly_avg)
                prices = hourly_prices
                logger.info(f"Successfully converted to {len(prices)} hourly prices")

            if len(prices) != 24:
                logger.warning(
                    f"Expected 24 hourly prices, got {len(prices)} for {target_date}"
                )

            logger.info(
                f"Successfully fetched {len(prices)} prices from official Nordpool integration"
            )
            logger.debug(f"Price range: {min(prices):.3f} - {max(prices):.3f} SEK/kWh")

            return prices

        except Exception as e:
            if isinstance(e, ValueError):
                raise
            raise ValueError(
                f"Failed to get prices from official integration for {target_date}: {e}"
            ) from e

    def perform_health_check(self):
        """Perform health check for official Nordpool integration.

        Returns:
            dict: Health check results
        """
        health_check = {
            "component_name": "Official Nordpool Integration",
            "description": "Official Home Assistant Nordpool price source",
            "is_required": True,
            "status": "OK",
            "checks": [],
        }

        # Test the service call with today's date
        from datetime import datetime

        today = datetime.now().date()

        service_check = {
            "name": "Nordpool Service Call",
            "status": "OK",
            "error": None,
            "value": "Available",
        }

        try:
            # Try to get today's prices to verify the integration works
            prices = self.get_prices_for_date(today)
            service_check.update(
                {"status": "OK", "value": f"{len(prices)} hourly prices available"}
            )

        except Exception as e:
            service_check.update(
                {
                    "status": "ERROR",
                    "error": f"Service call failed: {e!s}",
                    "value": "N/A",
                }
            )
            health_check["status"] = "ERROR"

        # Add config entry check
        config_check = {
            "name": "Configuration Entry",
            "status": "OK",
            "error": None,
            "value": f"ID: {self.config_entry_id}",
        }

        if not self.config_entry_id:
            config_check.update(
                {
                    "status": "ERROR",
                    "error": "No config entry ID configured",
                    "value": "Missing",
                }
            )
            health_check["status"] = "ERROR"

        health_check["checks"] = [service_check, config_check]
        return health_check


class LegacyNordpoolSource(PriceSource):
    """Price source for legacy/custom Nordpool integrations using sensor attributes.

    This maintains compatibility with custom Nordpool components that provide
    'today', 'tomorrow', 'raw_today', 'raw_tomorrow' attributes.
    """

    def __init__(self, ha_controller, vat_multiplier: float = 1.25) -> None:
        """Initialize with Home Assistant controller.

        Args:
            ha_controller: Controller with access to Home Assistant
            vat_multiplier: VAT multiplier for price conversion
        """
        self.ha_controller = ha_controller
        self.vat_multiplier = vat_multiplier

    def get_prices_for_date(self, target_date: date) -> list[float]:
        """Get prices from legacy Nordpool sensor attributes.

        This is the existing logic that expects sensor attributes.
        """
        from .price_manager import HomeAssistantSource

        # Use the existing HomeAssistantSource logic
        legacy_source = HomeAssistantSource(self.ha_controller, self.vat_multiplier)
        return legacy_source.get_prices_for_date(target_date)
