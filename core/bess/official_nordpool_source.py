"""
Official Home Assistant Nordpool integration price source.

This source uses the official HA Nordpool integration's service actions
instead of sensor attributes, providing compatibility with the core integration.
"""

import logging
from datetime import date, timedelta

from . import time_utils
from .price_manager import PriceSource

logger = logging.getLogger(__name__)


class OfficialNordpoolSource(PriceSource):
    """Price source that uses the official Home Assistant Nordpool integration.

    Uses the nordpool.get_prices_for_date service action instead of sensor attributes.
    The official integration was added to HA Core and provides different API than custom components.
    """

    def __init__(
        self, ha_controller, config_entry_id: str, vat_multiplier: float, area: str = ""
    ) -> None:
        """Initialize with Home Assistant controller and config entry ID.

        Args:
            ha_controller: Controller with access to Home Assistant services
            config_entry_id: Configuration entry ID for the Nordpool integration
            vat_multiplier: VAT multiplier (prices from official integration are VAT-exclusive)
            area: Market area code (e.g. "SE4", "NO1"). When provided it is passed
                  to the service call and used as the response key for an exact lookup.
                  When empty the first list in the response is used as a fallback.
        """
        self.ha_controller = ha_controller
        self.config_entry_id = config_entry_id
        self.vat_multiplier = vat_multiplier
        self.area = area

    def get_prices_for_date(self, target_date: date) -> list[float]:
        """Get prices from official Nordpool integration for the specified date.

        Uses the nordpool.get_prices_for_date service action.

        Args:
            target_date: The date to get prices for

        Returns:
            List of hourly prices per kWh (VAT-exclusive)

        Raises:
            ValueError: If prices cannot be fetched
        """
        if not self.config_entry_id:
            raise ValueError(
                "Nordpool integration not configured: config_entry_id is missing. "
                "Run the setup wizard to configure the Nordpool integration."
            )

        logger.info(
            f"Fetching Nordpool prices for {target_date} using official integration"
        )

        # Only support today and tomorrow (official integration limitation)
        from . import time_utils

        current_date = time_utils.today()
        tomorrow_date = current_date + timedelta(days=1)

        if target_date not in (current_date, tomorrow_date):
            raise ValueError(
                f"Official Nordpool integration only supports today and tomorrow, not {target_date}"
            )

        try:
            # Call the nordpool.get_prices_for_date service
            date_str = target_date.strftime("%Y-%m-%d")

            service_data: dict = {
                "config_entry": self.config_entry_id,
                "date": date_str,
            }
            if self.area:
                service_data["areas"] = self.area

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

            # Response is keyed by area code (e.g. {"SE4": [...]}).
            # Use the configured area for an exact lookup; fall back to the first
            # list in the response for installs where area is not yet configured.
            price_entries: list = []
            if self.area:
                price_entries = service_response.get(self.area, [])
                if not price_entries:
                    # Area codes are always uppercase in the response
                    price_entries = service_response.get(self.area.upper(), [])
                if price_entries:
                    logger.debug(f"Found price data under area key: {self.area}")
            if not price_entries:
                for key, value in service_response.items():
                    if isinstance(value, list) and value:
                        price_entries = value
                        logger.debug(f"Found price data under key: {key} (fallback)")
                        break

            if not price_entries:
                raise ValueError(
                    f"No price entries returned for {target_date}. Available keys: {list(service_response.keys())}"
                )

            # Convert price entries to hourly list
            prices = []
            for entry in price_entries:
                # Official integration returns prices in [Currency]/MWh
                price_mwh = float(entry["price"])
                # Convert from per MWh to per kWh
                price_kwh = price_mwh / 1000.0
                prices.append(price_kwh)

            logger.info(
                f"Successfully fetched {len(prices)} prices from official Nordpool integration"
            )
            logger.debug(f"Price range: {min(prices):.3f} - {max(prices):.3f} per kWh")

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

        # Check config entry ID first — no point calling the API without it
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
            health_check["checks"] = [config_check]
            return health_check

        # Test the service call with today's date
        today = time_utils.today()

        service_check = {
            "name": "Nordpool Service Call",
            "status": "OK",
            "error": None,
            "value": "Available",
        }

        try:
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

        health_check["checks"] = [service_check, config_check]
        return health_check
