"""
Octopus Energy Agile tariff price source.

Fetches import and export rates from Octopus Energy HA event entities.
Prices are VAT-inclusive in GBP/kWh. Raw data arrives at 30-minute resolution
(48 periods/day) and is expanded to 15-minute quarterly resolution (96 periods/day)
to match the system-wide period model.
"""

import logging
from datetime import date, datetime, timedelta

from . import time_utils
from .exceptions import PriceDataUnavailableError, SystemConfigurationError
from .price_manager import PriceSource

logger = logging.getLogger(__name__)

# Tolerance below the expected half-hourly count for a given day.
# Accounts for incremental publishing and DST boundary timestamp edge cases
# where rates at the settlement boundary may have the previous day's date.
_RAW_PERIOD_TOLERANCE = 2


class OctopusEnergySource(PriceSource):
    """Price source for Octopus Energy Agile tariff via Home Assistant event entities.

    Raw data arrives at 30-minute resolution (48 half-hourly slots per day) and is
    expanded to 96 quarterly (15-minute) periods to match the system-wide period model.

    Key differences from Nordpool:
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

    def get_prices_for_date(self, target_date: date) -> list[float]:
        """Get import rates from Octopus Energy for the specified date.

        Args:
            target_date: The date to get import prices for

        Returns:
            List of 96 quarterly import rates in GBP/kWh (VAT-inclusive),
            expanded from 48 half-hourly raw rates

        Raises:
            PriceDataUnavailableError: If rates cannot be fetched
            SystemConfigurationError: If date is not today or tomorrow
        """
        current_date = time_utils.today()
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
            List of 96 quarterly export rates in GBP/kWh (expanded from 48 raw),
            or None if no export entity configured
        """
        if not self.export_today_entity and not self.export_tomorrow_entity:
            return None

        current_date = time_utils.today()
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

        Octopus provides half-hourly rates (normally 48 per day, fewer on DST
        spring-forward, more on DST fall-back). Each rate is duplicated to
        produce quarterly (15-minute) periods matching the system-wide resolution.

        Args:
            entity_id: HA entity ID to fetch from
            target_date: Date to filter rates for
            rate_type: "import" or "export" (for logging)

        Returns:
            List of quarterly rate values (value_inc_vat) sorted chronologically

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

        # Compute expected half-hourly count from the actual day length
        # (DST-aware via time_utils). Allow a tolerance for settlement-boundary
        # timestamps that may carry the previous day's date.
        quarterly_period_count = time_utils.get_period_count(target_date)
        expected_raw = quarterly_period_count // 2
        min_raw = expected_raw - _RAW_PERIOD_TOLERANCE

        if len(filtered_rates) < min_raw:
            raise PriceDataUnavailableError(
                date=target_date,
                message=(
                    f"Expected at least {min_raw} {rate_type} rates for {target_date}, "
                    f"got {len(filtered_rates)} from {entity_id}"
                ),
            )
        if len(filtered_rates) > expected_raw:
            raise PriceDataUnavailableError(
                date=target_date,
                message=(
                    f"Too many {rate_type} rates for {target_date}: "
                    f"expected at most {expected_raw}, "
                    f"got {len(filtered_rates)} from {entity_id}"
                ),
            )

        # Extract value_inc_vat from each half-hourly rate entry
        half_hourly_prices = [float(rate["value_inc_vat"]) for rate in filtered_rates]

        # Expand half-hourly prices → quarterly prices (duplicate each)
        quarterly_prices = [p for p in half_hourly_prices for _ in range(2)]

        logger.info(
            f"Fetched {len(half_hourly_prices)} Octopus {rate_type} rates for {target_date} "
            f"(expanded to {len(quarterly_prices)} quarterly periods): "
            f"range {min(half_hourly_prices):.4f} - {max(half_hourly_prices):.4f} GBP/kWh"
        )

        return quarterly_prices

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
        today = time_utils.today()

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
