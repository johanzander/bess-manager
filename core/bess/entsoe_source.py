"""
ENTSO-e Transparency Platform price source.

Fetches day-ahead spot prices from the ENTSO-e Transparency Platform Home
Assistant integration (github.com/JaccoR/hass-entso-e, domain ``entsoe``).
Commonly used for Belgian Belpex prices and other European day-ahead markets.

The integration exposes a single "Average electricity price" sensor whose
attributes carry the full price arrays:

    sensor.<name>_average_electricity_price
        attributes:
            prices_today    -> [{"time": "<iso>", "price": <float>}, ...]
            prices_tomorrow -> [{"time": "<iso>", "price": <float>}, ...]

Prices are wholesale spot prices in EUR/kWh and are VAT-exclusive by default
(the integration's default modifyer is the raw ``{{current_price}}``), so this
source returns them unchanged and lets PriceManager apply markup/VAT/additional
costs — exactly like Nordpool.

Raw data arrives at hourly (24/day, PT60M) or quarterly (96/day, PT15M)
resolution depending on the integration's ``period`` option. Either way it is
expanded to the system-wide 96 quarterly (15-minute) period model.
"""

import logging
from datetime import date, datetime, timedelta

from . import time_utils
from .exceptions import PriceDataUnavailableError, SystemConfigurationError
from .price_manager import PriceSource

logger = logging.getLogger(__name__)


class EntsoeSource(PriceSource):
    """Price source for the ENTSO-e Transparency Platform HA integration.

    Reads the ``prices_today`` / ``prices_tomorrow`` attributes from the
    integration's "Average electricity price" sensor and expands them to 96
    quarterly periods. Prices are VAT-exclusive spot prices, so ``prices_are_final``
    stays False and PriceManager applies the buy-price calculation.
    """

    def __init__(self, ha_controller, entity: str) -> None:
        """Initialize with Home Assistant controller and the ENTSO-e sensor entity.

        Args:
            ha_controller: Controller with access to the Home Assistant API
            entity: Entity ID of the ENTSO-e average-price sensor that carries the
                    ``prices_today`` / ``prices_tomorrow`` attributes
                    (e.g. ``sensor.belpex_h_average_electricity_price``)
        """
        self.ha_controller = ha_controller
        self.entity = entity

    def get_prices_for_date(self, target_date: date) -> list[float]:
        """Get prices from the ENTSO-e sensor for the specified date.

        Args:
            target_date: The date to get prices for (today or tomorrow only)

        Returns:
            List of quarterly prices in EUR/kWh (VAT-exclusive), expanded from the
            raw hourly/quarterly arrays

        Raises:
            PriceDataUnavailableError: If prices cannot be fetched or validated
            SystemConfigurationError: If the date is not today or tomorrow
        """
        if not self.entity:
            raise SystemConfigurationError(
                message="ENTSO-e integration not configured: entity is missing. "
                "Run the setup wizard to configure the ENTSO-e price sensor."
            )

        current_date = time_utils.today()
        tomorrow_date = current_date + timedelta(days=1)

        if target_date not in (current_date, tomorrow_date):
            raise SystemConfigurationError(
                message=f"Can only fetch today's or tomorrow's prices, not {target_date}"
            )

        attribute = "prices_today" if target_date == current_date else "prices_tomorrow"

        try:
            response = self.ha_controller._api_request(
                "get", f"/api/states/{self.entity}"
            )
        except Exception as e:
            raise PriceDataUnavailableError(
                date=target_date,
                message=f"Failed to fetch ENTSO-e prices from {self.entity}: {e}",
            ) from e

        if not response or "attributes" not in response:
            raise PriceDataUnavailableError(
                date=target_date,
                message=f"No attributes in response from {self.entity}",
            )

        raw_entries = response["attributes"].get(attribute)
        if not raw_entries or not isinstance(raw_entries, list):
            raise PriceDataUnavailableError(
                date=target_date,
                message=f"No '{attribute}' list in attributes from {self.entity}",
            )

        hourly_or_quarterly = self._parse_entries_for_date(raw_entries, target_date)
        if not hourly_or_quarterly:
            raise PriceDataUnavailableError(
                date=target_date,
                message=(
                    f"No ENTSO-e prices for {target_date} in '{attribute}' "
                    f"from {self.entity}"
                ),
            )

        quarterly_prices = self._expand_to_quarterly(hourly_or_quarterly, target_date)

        logger.info(
            "Fetched %d ENTSO-e prices for %s (expanded to %d quarterly periods): "
            "range %.4f - %.4f EUR/kWh",
            len(hourly_or_quarterly),
            target_date,
            len(quarterly_prices),
            min(hourly_or_quarterly),
            max(hourly_or_quarterly),
        )

        return quarterly_prices

    def _parse_entries_for_date(
        self, raw_entries: list, target_date: date
    ) -> list[float]:
        """Filter raw {time, price} entries to target_date and return prices.

        Entries are sorted chronologically by their ``time`` timestamp. Timestamps
        are parsed with ``datetime.fromisoformat`` which handles both space and
        ``T`` separators and timezone offsets.
        """
        filtered: list[tuple[datetime, float]] = []
        for entry in raw_entries:
            if not isinstance(entry, dict):
                continue
            time_str = entry.get("time")
            price = entry.get("price")
            if time_str is None or price is None:
                continue
            try:
                entry_dt = datetime.fromisoformat(str(time_str))
            except ValueError:
                continue
            if entry_dt.date() == target_date:
                filtered.append((entry_dt, float(price)))

        filtered.sort(key=lambda item: item[0])
        return [price for _, price in filtered]

    def _expand_to_quarterly(
        self, prices: list[float], target_date: date
    ) -> list[float]:
        """Expand hourly/quarterly prices to the system-wide quarterly resolution.

        The expansion factor is derived from the DST-aware quarterly period count
        for the day, so hourly (factor 4) and already-quarterly (factor 1) inputs
        are both handled, including 23h/25h DST days.

        Raises:
            PriceDataUnavailableError: If the raw count does not divide evenly into
                the expected quarterly count.
        """
        quarterly_count = time_utils.get_period_count(target_date)

        if len(prices) == 0 or quarterly_count % len(prices) != 0:
            raise PriceDataUnavailableError(
                date=target_date,
                message=(
                    f"Unexpected ENTSO-e price count {len(prices)} for {target_date}: "
                    f"does not divide evenly into {quarterly_count} quarterly periods"
                ),
            )

        factor = quarterly_count // len(prices)
        return [price for price in prices for _ in range(factor)]

    def perform_health_check(self) -> dict:
        """Perform health check on the ENTSO-e source.

        Returns:
            dict: Health check result with status and checks
        """
        try:
            today_prices = self.get_prices_for_date(time_utils.today())
            return {
                "status": "OK",
                "checks": [
                    {
                        "name": "EntsoeSource",
                        "status": "OK",
                        "error": None,
                        "value": (
                            f"Successfully fetched {len(today_prices)} prices for today"
                        ),
                    }
                ],
            }
        except Exception as e:
            return {
                "status": "ERROR",
                "checks": [
                    {
                        "name": "EntsoeSource",
                        "status": "ERROR",
                        "error": f"Failed to fetch prices: {e}",
                    }
                ],
            }
