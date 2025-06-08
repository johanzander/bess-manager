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

    def get_schedule_data(self) -> dict[str, Any]:
            """Get schedule data - snake_case only."""
            
            # Build hourly data array
            hourly_data = []

            for hour in range(len(self.actions)):
                # Get strategic intent for this hour
                intent = (
                    self.strategic_intents[hour]
                    if hour < len(self.strategic_intents)
                    else "IDLE"
                )

                # Get data from arrays, ensure indices are valid
                if hour >= len(self.actions):
                    raise ValueError(f"Hour {hour} is out of range for actions array (length: {len(self.actions)})")
                action = self.actions[hour]

                if hour >= len(self.state_of_energy):
                    raise ValueError(f"Hour {hour} is out of range for state_of_energy array (length: {len(self.state_of_energy)})")
                soe = self.state_of_energy[hour]

                if hour >= len(self.prices):
                    raise ValueError(f"Hour {hour} is out of range for prices array (length: {len(self.prices)})")
                price = self.prices[hour]

                if hour >= len(self.hourly_consumption) or not self.hourly_consumption:
                    raise ValueError(f"Hour {hour} is out of range for hourly_consumption array (length: {len(self.hourly_consumption) if self.hourly_consumption else 0})")
                consumption = self.hourly_consumption[hour]

                # Calculate SOC percentage - use actual battery capacity
                battery_capacity = self.original_dp_results.get("battery_settings", {}).get("total_capacity", 30.0)

                if battery_capacity <= 0:
                    raise ValueError(f"Invalid battery capacity: {battery_capacity}. Must be positive.")

                if soe < 0:
                    raise ValueError(f"Invalid state of energy (SOE): {soe}. Cannot be negative.")
                soc_percent = soe / battery_capacity * 100

                # Get additional data from hourly_data
                solar_production = 0.0
                grid_import = 0.0
                grid_export = 0.0

                if self.hourly_data:
                    if "solar_production" in self.hourly_data and hour < len(self.hourly_data["solar_production"]):
                        solar_production = self.hourly_data["solar_production"][hour]
                    if "grid_import" in self.hourly_data and hour < len(self.hourly_data["grid_import"]):
                        grid_import = self.hourly_data["grid_import"][hour]
                    if "grid_export" in self.hourly_data and hour < len(self.hourly_data["grid_export"]):
                        grid_export = self.hourly_data["grid_export"][hour]

                # Calculate costs
                base_cost = consumption * price
                grid_cost = grid_import * price - grid_export * price * 0.6
                savings = base_cost - grid_cost

                hour_data = {
                    "hour": str(hour),
                    "price": price,
                    "consumption": consumption,
                    "battery_level": soc_percent,
                    "action": action,
                    "strategic_intent": intent,
                    "grid_cost": grid_cost,
                    "battery_cost": 0.0,
                    "total_cost": grid_cost,
                    "base_cost": base_cost,
                    "savings": savings,
                    "hourly_cost": grid_cost,
                    "hourly_savings": savings,
                    "solar_production": solar_production,
                    "grid_import": grid_import,
                    "grid_exported": grid_export,
                    "grid_imported": grid_import,
                    "battery_charge": max(0, action),
                    "battery_discharge": max(0, -action),
                    "data_source": "predicted",
                    "battery_soc_start": soc_percent,
                    "solar_charged": min(max(0, action), solar_production),
                    "effective_diff": 0.0,
                    "opportunity_score": 0.0,
                }

                hourly_data.append(hour_data)

            # Calculate summary
            total_consumption = sum(h["consumption"] for h in hourly_data)
            total_solar = sum(h["solar_production"] for h in hourly_data)
            total_grid_import = sum(h["grid_import"] for h in hourly_data)
            total_grid_export = sum(h["grid_exported"] for h in hourly_data)
            total_battery_charge = sum(h["battery_charge"] for h in hourly_data)
            total_battery_discharge = sum(h["battery_discharge"] for h in hourly_data)
            avg_price = sum(h["price"] for h in hourly_data) / len(hourly_data) if hourly_data else 0.0

            # Summary calculations
            total_base_cost = sum(h["base_cost"] for h in hourly_data)
            total_optimized_cost = sum(h["total_cost"] for h in hourly_data)
            total_savings = sum(h["savings"] for h in hourly_data)

            summary = {
                "base_cost": total_base_cost,
                "optimized_cost": total_optimized_cost,
                "grid_costs": total_grid_import * avg_price,
                "battery_costs": 0,
                "savings": total_savings,
                "total_solar_production": total_solar,
                "total_battery_charge": total_battery_charge,
                "total_battery_discharge": total_battery_discharge,
                "total_grid_import": total_grid_import,
                "total_grid_export": total_grid_export,
                "cycle_count": total_battery_discharge / battery_capacity,
                "avg_buy_price": avg_price,
                "avg_sell_price": avg_price * 0.6,
                "total_consumption": total_consumption,
                "estimated_battery_cycles": total_battery_discharge / battery_capacity,
            }

            # Add strategic intent summary
            intent_summary = {}
            for hour_data in hourly_data:
                intent = hour_data["strategic_intent"]
                intent_summary[intent] = intent_summary.get(intent, 0) + 1

            return {
                "hourly_data": hourly_data,
                "summary": summary,
                "enhanced_summary": summary,
                "strategic_intent_summary": intent_summary,
                "energy_profile": {
                    "consumption": [h["consumption"] for h in hourly_data],
                    "solar": [h["solar_production"] for h in hourly_data],
                    "battery_soc": [h["battery_level"] for h in hourly_data],
                    "actual_hours": 0,
                },
            }