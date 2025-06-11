"""
Enhanced DPSchedule class that includes strategic intent information.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class DPSchedule:
    """Enhanced battery schedule with strategic intent support."""

    def __init__(
        self,
        actions: list[float],
        state_of_energy: list[float],
        prices: list[float],
        cycle_cost: float = 0.0,
        hourly_consumption: list[float] | None = None,
        hourly_data: dict[str, list] | None = None,
        summary: dict[str, Any] | None = None,
        solar_charged: list[float] | None = None,
        original_dp_results: dict[str, Any] | None = None,
    ):
        """
        Initialize schedule with strategic intent support.

        Args:
            actions: Battery actions for each hour (kW)
            state_of_energy: Battery state for each hour (kWh)
            prices: Electricity prices for each hour
            cycle_cost: Cost per kWh for battery cycles
            hourly_consumption: Home consumption for each hour
            hourly_data: Detailed hourly data from DP algorithm
            summary: Economic summary data
            solar_charged: Solar energy charged to battery each hour
            original_dp_results: Complete results from DP algorithm including intents
        """
        self.actions = actions
        self.state_of_energy = state_of_energy
        self.prices = prices
        self.cycle_cost = cycle_cost
        self.hourly_consumption = hourly_consumption or []
        self.hourly_data = hourly_data or {}
        self.summary = summary or {}
        self.solar_charged = solar_charged or []
        self.original_dp_results = original_dp_results or {}

        # Extract strategic intents if available
        self.strategic_intents = self.original_dp_results.get("strategic_intent", [])

        logger.debug(
            "Created DPSchedule with %d hours, %d strategic intents",
            len(actions),
            len(self.strategic_intents),
        )

    def get_hour_settings(self, hour: int) -> dict[str, Any]:
        """Get settings for a specific hour including strategic intent."""
        if not 0 <= hour < len(self.actions):
            return {"state": "idle", "grid_charge": False, "strategic_intent": "IDLE"}

        action = self.actions[hour]
        intent = (
            self.strategic_intents[hour]
            if hour < len(self.strategic_intents)
            else "IDLE"
        )

        # Determine state based on strategic intent (primary) and action (secondary)
        if intent == "GRID_CHARGING":
            state = "charging"
            grid_charge = True  # Enable AC charging for grid arbitrage
        elif intent == "SOLAR_STORAGE":
            state = "charging" if action > 0.01 else "idle"
            grid_charge = False  # Solar charging only
        elif intent == "LOAD_SUPPORT":
            state = "discharging"
            grid_charge = False
        elif intent == "EXPORT_ARBITRAGE":
            state = "grid-first"  # Priority to grid export
            grid_charge = False
        else:  # IDLE
            state = "idle"
            grid_charge = False

        return {
            "state": state,
            "grid_charge": grid_charge,
            "battery_action": action,
            "strategic_intent": intent,
        }

    def get_daily_intervals(self) -> list[dict[str, Any]]:
        """Get daily intervals for TOU programming with strategic intents."""
        intervals = []

        for hour in range(len(self.actions)):
            settings = self.get_hour_settings(hour)

            intervals.append(
                {
                    "start_time": f"{hour:02d}:00",
                    "end_time": f"{hour:02d}:59",
                    "state": settings["state"],
                    "grid_charge": settings["grid_charge"],
                    "battery_action": settings["battery_action"],
                    "strategic_intent": settings["strategic_intent"],
                }
            )

        return intervals

    def get_strategic_intent_periods(self) -> list[dict[str, Any]]:
        """Get consolidated periods based on strategic intents."""
        if not self.strategic_intents:
            return []

        periods = []
        current_intent = self.strategic_intents[0]
        current_start = 0

        for hour in range(1, len(self.strategic_intents)):
            if self.strategic_intents[hour] != current_intent:
                # End current period
                periods.append(
                    {
                        "start_hour": current_start,
                        "end_hour": hour - 1,
                        "strategic_intent": current_intent,
                        "hours_count": hour - current_start,
                    }
                )

                # Start new period
                current_intent = self.strategic_intents[hour]
                current_start = hour

        # Add final period
        periods.append(
            {
                "start_hour": current_start,
                "end_hour": len(self.strategic_intents) - 1,
                "strategic_intent": current_intent,
                "hours_count": len(self.strategic_intents) - current_start,
            }
        )

        return periods
