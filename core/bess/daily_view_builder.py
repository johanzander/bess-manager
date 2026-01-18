"""ViewBuilder - Creates daily views combining actual + predicted data.

SIMPLIFIED: Always operates on quarterly periods.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime

from .historical_data_store import HistoricalDataStore
from .models import DecisionData, EconomicData, EnergyData, PeriodData
from .schedule_store import ScheduleStore
from .settings import BatterySettings
from .time_utils import TIMEZONE, format_period, get_period_count

logger = logging.getLogger(__name__)


@dataclass
class DailyView:
    """Daily view with quarterly periods."""

    date: date
    periods: list[PeriodData]  # 92-100 periods depending on DST
    total_savings: float
    actual_count: int
    predicted_count: int
    missing_count: int = 0  # Periods with no sensor data (e.g., HA restart gap)


class DailyViewBuilder:
    """Builds daily views by merging actual + predicted data."""

    def __init__(
        self,
        historical_store: HistoricalDataStore,
        schedule_store: ScheduleStore,
        battery_settings: BatterySettings,
    ):
        self.historical_store = historical_store
        self.schedule_store = schedule_store
        self.battery_settings = battery_settings

    def _create_missing_period(self, period: int, today: date) -> PeriodData:
        """Create a placeholder for a period with no available data.

        This handles edge cases like HA restarts where sensor data is unavailable.
        Uses persisted strategic intent if available, otherwise defaults to IDLE.

        Args:
            period: Period index (0-95)
            today: Current date

        Returns:
            PeriodData with data_source="missing" and zero energy values
        """
        # Try to recover the planned intent from persistence
        persisted_intent = self.schedule_store.get_persisted_intent(period)
        intent = persisted_intent or "IDLE"

        # Create timestamp for this period
        hour = period // 4
        minute = (period % 4) * 15
        timestamp = datetime.combine(
            today, datetime.min.time().replace(hour=hour, minute=minute), tzinfo=TIMEZONE
        )

        return PeriodData(
            period=period,
            energy=EnergyData(
                solar_production=0.0,
                home_consumption=0.0,
                battery_charged=0.0,
                battery_discharged=0.0,
                grid_imported=0.0,
                grid_exported=0.0,
                battery_soe_start=0.0,
                battery_soe_end=0.0,
            ),
            timestamp=timestamp,
            data_source="missing",
            economic=EconomicData(),
            decision=DecisionData(strategic_intent=intent),
        )

    def build_daily_view(self, current_period: int) -> DailyView:
        """Build view for today.

        Merges:
        - Actual data (from sensors) for past periods
        - Predicted data (from optimization) for future periods

        Args:
            current_period: Current period index (0-95 for normal day)

        Returns:
            DailyView with quarterly periods (92-100 depending on DST)
        """
        today = datetime.now(tz=TIMEZONE).date()
        logger.info(
            f"Building view for {today} at period {current_period} ({format_period(current_period)})"
        )

        # 2. Get data sources
        historical_periods = self.historical_store.get_today_periods()
        predicted_schedule = self.schedule_store.get_latest_schedule()

        if not predicted_schedule:
            raise ValueError("No optimization schedule available")

        predicted_periods = predicted_schedule.optimization_result.period_data
        optimization_period = predicted_schedule.optimization_period

        # 3. Merge: past = actual, future = predicted
        periods = []
        num_periods = get_period_count(today)

        for i in range(num_periods):
            if i < current_period and historical_periods[i] is not None:
                # Past: use actual sensor data
                periods.append(historical_periods[i])
            else:
                # Future: use predicted optimization data
                # Period indices and timestamps are already correct from BatterySystemManager
                predicted_index = i - optimization_period
                if 0 <= predicted_index < len(predicted_periods):
                    periods.append(predicted_periods[predicted_index])
                else:
                    # No historical data AND no predicted data for this period
                    # This can happen when HA restarts and sensor data is unavailable
                    logger.warning(
                        f"No data available for period {i} ({format_period(i)}) - "
                        f"creating placeholder (HA sensor data unavailable)"
                    )
                    placeholder = self._create_missing_period(i, today)
                    periods.append(placeholder)

        # 4. Calculate summary
        total_savings = sum(
            p.economic.hourly_savings for p in periods if p.economic is not None
        )

        actual_count = sum(1 for p in periods if p.data_source == "actual")
        missing_count = sum(1 for p in periods if p.data_source == "missing")
        predicted_count = len(periods) - actual_count - missing_count

        if missing_count > 0:
            logger.warning(
                f"DailyView has {missing_count} missing period(s) - "
                f"sensor data was unavailable (e.g., HA restart)"
            )

        logger.info(
            f"Built view: {len(periods)} periods "
            f"({actual_count} actual, {predicted_count} predicted, {missing_count} missing), "
            f"total savings: {total_savings:.2f} SEK"
        )

        return DailyView(
            date=today,
            periods=periods,
            total_savings=total_savings,
            actual_count=actual_count,
            predicted_count=predicted_count,
            missing_count=missing_count,
        )
