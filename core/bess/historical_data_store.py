"""HistoricalDataStore - Stores actual sensor data at quarterly resolution.

Simplified storage using continuous period indices (0 = today 00:00).
Only stores today's data in memory. Persists to disk for restart recovery.
"""

import json
import logging
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path

from core.bess.models import DecisionData, EconomicData, EnergyData, PeriodData
from core.bess.settings import BatterySettings
from core.bess.time_utils import TIMEZONE, get_period_count

logger = logging.getLogger(__name__)

# /data is HA add-on persistent storage, always available without map config
PERSIST_PATH = Path("/data/bess_historical_data.json")


class HistoricalDataStore:
    """Stores actual sensor data at quarterly resolution.

    Uses simple integer indices: 0 = today 00:00, 95 = today 23:45.
    Only stores today's data in memory. Persists to disk for restart recovery.
    """

    def __init__(
        self, battery_settings: BatterySettings, persist_path: Path | None = None
    ):
        """Initialize the historical data store.

        Args:
            battery_settings: Battery settings reference (shared, always up-to-date)
            persist_path: Optional custom path for persistence file (for testing)
        """
        # Simple storage: period_index → PeriodData
        self._records: dict[int, PeriodData] = {}

        # Store battery settings reference for SOC calculations
        self.battery_settings = battery_settings

        self._persist_path = persist_path or PERSIST_PATH

        # Load persisted data on startup
        self._load_from_disk()

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

        self._save_to_disk()

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

        if self._persist_path.exists():
            try:
                self._persist_path.unlink()
                logger.debug(f"Deleted persistence file {self._persist_path}")
            except Exception as e:
                logger.warning(f"Failed to delete persistence file: {e}")

        logger.info("Cleared all historical data")

    def _save_to_disk(self) -> None:
        """Persist today's historical data to survive restart.

        Stores serialized PeriodData records with today's date for validation.
        """
        if not self._records:
            return

        # Serialize records using dataclasses.asdict()
        serialized_records: dict[str, dict] = {}
        for period_index, period_data in self._records.items():
            record_dict = asdict(period_data)
            # Convert datetime to ISO format for JSON serialization
            if record_dict["timestamp"] is not None:
                record_dict["timestamp"] = record_dict["timestamp"].isoformat()
            serialized_records[str(period_index)] = record_dict

        data = {
            "date": datetime.now(tz=TIMEZONE).date().isoformat(),
            "records": serialized_records,
        }

        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._persist_path, "w") as f:
                json.dump(data, f)
            logger.debug(
                f"Persisted {len(serialized_records)} historical records"
                f" to {self._persist_path}"
            )
        except Exception as e:
            logger.warning(f"Failed to persist historical data: {e}")

    def _load_from_disk(self) -> None:
        """Load persisted historical data on startup.

        Only loads if the persisted file is from today.
        Reconstructs PeriodData objects, filtering init=False fields
        so that __post_init__ recalculates derived values.
        """
        if not self._persist_path.exists():
            logger.debug("No persisted historical data file found")
            return

        try:
            with open(self._persist_path) as f:
                data = json.load(f)

            # Validate date - only use if from today
            stored_date = data.get("date")
            today = datetime.now(tz=TIMEZONE).date().isoformat()
            if stored_date != today:
                logger.info(
                    f"Persisted historical data from {stored_date}"
                    f" (not today {today}), discarding"
                )
                return

            # Identify init=True field names for filtered reconstruction
            energy_init_fields = {f.name for f in fields(EnergyData) if f.init}
            economic_init_fields = {f.name for f in fields(EconomicData) if f.init}

            records = data.get("records", {})
            for period_key, record_dict in records.items():
                period_index = int(period_key)

                # Reconstruct EnergyData (filter init=False fields)
                energy_dict = record_dict["energy"]
                energy_kwargs = {
                    k: v for k, v in energy_dict.items() if k in energy_init_fields
                }
                energy = EnergyData(**energy_kwargs)

                # Reconstruct EconomicData (filter init=False fields)
                economic_dict = record_dict.get("economic", {})
                economic_kwargs = {
                    k: v for k, v in economic_dict.items() if k in economic_init_fields
                }
                economic = EconomicData(**economic_kwargs)

                # Reconstruct DecisionData (all fields are init=True)
                decision_dict = record_dict.get("decision", {})
                decision = DecisionData(**decision_dict)

                # Parse timestamp
                timestamp = None
                if record_dict.get("timestamp") is not None:
                    timestamp = datetime.fromisoformat(record_dict["timestamp"])

                period_data = PeriodData(
                    period=record_dict["period"],
                    energy=energy,
                    timestamp=timestamp,
                    data_source=record_dict.get("data_source", "predicted"),
                    economic=economic,
                    decision=decision,
                )

                self._records[period_index] = period_data

            logger.info(
                f"Loaded {len(self._records)} persisted historical records" " from disk"
            )

        except Exception as e:
            logger.warning(f"Failed to load persisted historical data: {e}")

    def get_stored_count(self) -> int:
        """Get count of stored periods.

        Returns:
            Number of periods currently stored
        """
        return len(self._records)
