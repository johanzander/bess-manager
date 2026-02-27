"""
Octopus Energy Agile tariff price source.

Fetches import and export rates from Octopus Energy HA event entities.
Prices are VAT-inclusive in GBP/kWh at 30-minute resolution (48 periods/day).
"""

import logging
from datetime import date, datetime, timedelta

from .exceptions import PriceDataUnavailableError, SystemConfigurationError
from .price_manager import PriceSource

logger = logging.getLogger(__name__)

EXPECTED_PERIODS_PER_DAY = 48
MIN_PERIODS_PER_DAY = 46


class OctopusEnergySource(PriceSource):
    """Price source for Octopus Energy Agile tariff via Home Assistant event entities.

    Key differences from Nordpool:
    - 30-minute periods (48/day) instead of 15-minute (96/day)
    - Separate import and export rate entities
    - Prices are already VAT-inclusive final prices in GBP/kWh
    - Data comes from HA event entity attributes (rates list)
    """

    def __init__(
        self,
        ha_controller,
        import_today_entity: str,
        import_tomorrow_entity: str,
        export_today_entity: str,
        export_tomorrow_entity: str,
    ) -> None:
        """Initialize with Home Assistant controller and Octopus entity IDs.

        Args:
            ha_controller: Controller with access to Home Assistant API
            import_today_entity: Entity ID for today's import rates
            import_tomorrow_entity: Entity ID for tomorrow's import rates
            export_today_entity: Entity ID for today's export rates
            export_tomorrow_entity: Entity ID for tomorrow's export rates
        """
        self.ha_controller = ha_controller
        self.import_today_entity = import_today_entity
        self.import_tomorrow_entity = import_tomorrow_entity
        self.export_today_entity = export_today_entity
        self.export_tomorrow_entity = export_tomorrow_entity

    @property
    def period_duration_hours(self) -> float:
        """Octopus Energy uses 30-minute periods."""
        return 0.5

    def get_prices_for_date(self, target_date: date) -> list[float]:
        """Get import rates from Octopus Energy for the specified date.

        Args:
            target_date: The date to get import prices for

        Returns:
            List of 48 import rates in GBP/kWh (VAT-inclusive)

        Raises:
            PriceDataUnavailableError: If rates cannot be fetched
            SystemConfigurationError: If date is not today or tomorrow
        """
        current_date = datetime.now().date()
        tomorrow_date = current_date + timedelta(days=1)

        if target_date not in (current_date, tomorrow_date):
            raise SystemConfigurationError(
                message=f"Can only fetch today's or tomorrow's prices, not {target_date}"
            )

        if target_date == current_date:
            entity_id = self.import_today_entity
        else:
            entity_id = self.import_tomorrow_entity

        return self._fetch_rates(entity_id, target_date, "import")

    def get_sell_prices_for_date(self, target_date: date) -> list[float] | None:
        """Get export rates from Octopus Energy for the specified date.

        Args:
            target_date: The date to get export prices for

        Returns:
            List of 48 export rates in GBP/kWh, or None if no export entity configured
        """
        if not self.export_today_entity and not self.export_tomorrow_entity:
            return None

        current_date = datetime.now().date()
        tomorrow_date = current_date + timedelta(days=1)

        if target_date not in (current_date, tomorrow_date):
            return None

        if target_date == current_date:
            entity_id = self.export_today_entity
        else:
            entity_id = self.export_tomorrow_entity

        if not entity_id:
            return None

        try:
            return self._fetch_rates(entity_id, target_date, "export")
        except PriceDataUnavailableError:
            logger.warning(f"Export rates unavailable for {target_date}")
            return None

    def _fetch_rates(
        self, entity_id: str, target_date: date, rate_type: str
    ) -> list[float]:
        """Fetch rates from a Home Assistant event entity.

        Args:
            entity_id: HA entity ID to fetch from
            target_date: Date to filter rates for
            rate_type: "import" or "export" (for logging)

        Returns:
            List of 48 rate values (value_inc_vat) sorted chronologically

        Raises:
            PriceDataUnavailableError: If rates cannot be fetched or validated
        """
        try:
            response = self.ha_controller._api_request(
                "get", f"/api/states/{entity_id}"
            )
        except Exception as e:
            raise PriceDataUnavailableError(
                date=target_date,
                message=f"Failed to fetch {rate_type} rates from {entity_id}: {e}",
            ) from e

        if not response or "attributes" not in response:
            raise PriceDataUnavailableError(
                date=target_date,
                message=f"No attributes in response from {entity_id}",
            )

        attributes = response["attributes"]
        rates = attributes.get("rates")

        if not rates or not isinstance(rates, list):
            raise PriceDataUnavailableError(
                date=target_date,
                message=f"No rates list in attributes from {entity_id}",
            )

        # Filter rates for the target date and sort chronologically
        filtered_rates = self._filter_rates_for_date(rates, target_date)

        if len(filtered_rates) < MIN_PERIODS_PER_DAY:
            raise PriceDataUnavailableError(
                date=target_date,
                message=(
                    f"Expected at least {MIN_PERIODS_PER_DAY} {rate_type} rates for {target_date}, "
                    f"got {len(filtered_rates)} from {entity_id}"
                ),
            )
        if len(filtered_rates) > EXPECTED_PERIODS_PER_DAY:
            raise PriceDataUnavailableError(
                date=target_date,
                message=(
                    f"Too many {rate_type} rates for {target_date}: "
                    f"expected at most {EXPECTED_PERIODS_PER_DAY}, "
                    f"got {len(filtered_rates)} from {entity_id}"
                ),
            )

        # Extract value_inc_vat from each rate entry
        prices = [float(rate["value_inc_vat"]) for rate in filtered_rates]

        logger.info(
            f"Fetched {len(prices)} Octopus {rate_type} rates for {target_date}: "
            f"range {min(prices):.4f} - {max(prices):.4f} GBP/kWh"
        )

        return prices

    def _filter_rates_for_date(
        self, rates: list[dict], target_date: date
    ) -> list[dict]:
        """Filter and sort rates for a specific date.

        Args:
            rates: List of rate entries with 'start' timestamps
            target_date: Date to filter for

        Returns:
            Filtered and sorted list of rate entries for the target date
        """
        filtered = []
        for rate in rates:
            start_str = rate.get("start")
            if not start_str:
                continue

            try:
                start_dt = datetime.fromisoformat(start_str)
                if start_dt.date() == target_date:
                    filtered.append(rate)
            except (ValueError, TypeError):
                continue

        # Sort by start time
        filtered.sort(key=lambda r: r["start"])

        return filtered

    def perform_health_check(self) -> dict:
        """Perform health check on Octopus Energy source.

        Returns:
            dict: Health check result with status and checks
        """
        checks = []
        overall_status = "OK"
        today = datetime.now().date()

        # Test import rates
        import_check = {
            "component": "OctopusEnergySource (Import)",
            "status": "OK",
            "message": "",
        }
        try:
            import_prices = self.get_prices_for_date(today)
            import_check["message"] = (
                f"Successfully fetched {len(import_prices)} import rates for today"
            )
        except Exception as e:
            import_check["status"] = "ERROR"
            import_check["message"] = f"Failed to fetch import rates: {e}"
            overall_status = "ERROR"
        checks.append(import_check)

        # Test export rates
        export_check = {
            "component": "OctopusEnergySource (Export)",
            "status": "OK",
            "message": "",
        }
        try:
            export_prices = self.get_sell_prices_for_date(today)
            if export_prices is not None:
                export_check["message"] = (
                    f"Successfully fetched {len(export_prices)} export rates for today"
                )
            else:
                export_check["message"] = "No export entity configured"
        except Exception as e:
            export_check["status"] = "WARNING"
            export_check["message"] = f"Failed to fetch export rates: {e}"
            if overall_status == "OK":
                overall_status = "WARNING"
        checks.append(export_check)

        return {
            "status": overall_status,
            "checks": checks,
        }
