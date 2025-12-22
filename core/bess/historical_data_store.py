"""HistoricalDataStore - Stores actual sensor data at quarterly resolution.

Simplified storage using continuous period indices (0 = today 00:00).
Only stores today's data in memory.
"""

import logging
from datetime import datetime

from core.bess.models import PeriodData
from core.bess.time_utils import TIMEZONE, get_period_count

logger = logging.getLogger(__name__)


class HistoricalDataStore:
    """Stores actual sensor data at quarterly resolution.

    Uses simple integer indices: 0 = today 00:00, 95 = today 23:45.
    Only stores today's data in memory.
    """

    def __init__(self, battery_capacity_kwh: float):
        """Initialize the historical data store.

        Args:
            battery_capacity_kwh: Total battery capacity for SOC calculations
        """
        # Simple storage: period_index → PeriodData
        self._records: dict[int, PeriodData] = {}

        # Store battery capacity for SOC calculations
        self.total_capacity = battery_capacity_kwh

        logger.debug("Initialized HistoricalDataStore")

    def record_period(self, period_index: int, period_data: PeriodData) -> None:
        """Record actual sensor data for a period.

        Args:
            period_index: Continuous index from today 00:00 (0-95)
            period_data: Sensor data with data_source="actual"

        Raises:
            ValueError: If period_index is out of range for today
        """
        # Validate period is within today's range
        today = datetime.now(tz=TIMEZONE).date()
        today_periods = get_period_count(today)

        if not 0 <= period_index < today_periods:
            raise ValueError(
                f"Period index {period_index} out of range for today "
                f"(0-{today_periods-1})"
            )

        # Store
        self._records[period_index] = period_data

        logger.debug(
            "Recorded period %d: SOC %.1f → %.1f kWh",
            period_index,
            period_data.energy.battery_soe_start,
            period_data.energy.battery_soe_end,
        )

    def get_period(self, period_index: int) -> PeriodData | None:
        """Get data for a specific period.

        Args:
            period_index: Continuous index from today 00:00

        Returns:
            PeriodData if available, None if missing
        """
        return self._records.get(period_index)

    def get_today_periods(self) -> list[PeriodData | None]:
        """Get all periods for today (accounting for DST).

        Returns:
            List of 92-100 PeriodData (or None for missing periods)
            Length depends on DST (92 = spring, 96 = normal, 100 = fall)
        """
        today = datetime.now(tz=TIMEZONE).date()
        num_periods = get_period_count(today)

        # Return list with data if available, None otherwise
        return [self._records.get(i) for i in range(num_periods)]

    def clear(self) -> None:
        """Clear all stored data.

        Useful for testing or daily reset.
        """
        self._records.clear()
        logger.info("Cleared all historical data")

    def get_stored_count(self) -> int:
        """Get count of stored periods.

        Returns:
            Number of periods currently stored
        """
        return len(self._records)
