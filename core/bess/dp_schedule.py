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

    def log_schedule_TO_BE_REMOVED(self):
        """Log the schedule with strategic intent information."""
        if not self.actions:
            logger.info("No schedule data to log")
            return

        lines = [
            "\n╔════════════════════════════════════════════════════════════════════════════╗",
            "║                         Battery Schedule with Strategic Intents            ║",
            "╠════╦═══════════════════╦═══════╦════════╦═══════════════════════════════════╣",
            "║ Hr ║ Strategic Intent  ║Action ║  SOE   ║           Description             ║",
            "╠════╬═══════════════════╬═══════╬════════╬═══════════════════════════════════╣",
        ]

        intent_descriptions = {
            "GRID_CHARGING": "Store cheap grid energy",
            "SOLAR_STORAGE": "Store excess solar energy",
            "LOAD_SUPPORT": "Support home consumption",
            "EXPORT_ARBITRAGE": "Export for profit",
            "SOLAR_EXPORT": "Natural solar export",
            "IDLE": "No significant activity",
        }

        for hour in range(len(self.actions)):
            action = self.actions[hour]
            soe = self.state_of_energy[hour] if hour < len(self.state_of_energy) else 0
            intent = (
                self.strategic_intents[hour]
                if hour < len(self.strategic_intents)
                else "IDLE"
            )
            description = intent_descriptions.get(intent, "Unknown")

            # Format action with direction indicator
            if action > 0.01:
                action_str = f"{action:5.1f}↑"  # Charging
            elif action < -0.01:
                action_str = f"{abs(action):5.1f}↓"  # Discharging
            else:
                action_str = "  0.0-"  # Idle

            row = f"║ {hour:02d} ║ {intent:17} ║ {action_str:5} ║ {soe:6.1f} ║ {description:33} ║"
            lines.append(row)

        lines.append(
            "╚════╩═══════════════════╩═══════╩════════╩═══════════════════════════════════╝"
        )

        logger.info("\n".join(lines))

    def get_total_energy_flows(self) -> dict[str, float]:
        """Get total energy flows for the day."""
        if not self.hourly_data:
            return {}

        flows = {}
        for key, values in self.hourly_data.items():
            if isinstance(values, list) and len(values) > 0:
                try:
                    flows[f"total_{key}"] = sum(
                        float(v) for v in values if v is not None
                    )
                except (ValueError, TypeError):
                    continue

        return flows

    def get_schedule_data(self) -> dict[str, Any]:
        """Get schedule data in the format expected by the API endpoints.

        This method provides compatibility with the existing API structure.
        """
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
                raise ValueError(
                    f"Hour {hour} is out of range for actions array (length: {len(self.actions)})"
                )
            action = self.actions[hour]

            if hour >= len(self.state_of_energy):
                raise ValueError(
                    f"Hour {hour} is out of range for state_of_energy array (length: {len(self.state_of_energy)})"
                )
            soe = self.state_of_energy[hour]

            if hour >= len(self.prices):
                raise ValueError(
                    f"Hour {hour} is out of range for prices array (length: {len(self.prices)})"
                )
            price = self.prices[hour]

            if hour >= len(self.hourly_consumption) or not self.hourly_consumption:
                raise ValueError(
                    f"Hour {hour} is out of range for hourly_consumption array (length: {len(self.hourly_consumption) if self.hourly_consumption else 0})"
                )
            consumption = self.hourly_consumption[hour]

            # Calculate SOC percentage - use actual battery capacity instead of hardcoded 15.0 kWh
            # Get capacity from battery_settings if available, otherwise default to 30.0 (standard value)
            battery_capacity = self.original_dp_results.get("battery_settings", {}).get(
                "total_capacity", 30.0
            )

            # Assert if battery capacity is invalid
            if battery_capacity <= 0:
                raise ValueError(
                    f"Invalid battery capacity: {battery_capacity}. Must be positive."
                )

            # Calculate SOC percentage - assert if SOE is negative
            if soe < 0:
                raise ValueError(
                    f"Invalid state of energy (SOE): {soe}. Cannot be negative."
                )
            soc_percent = soe / battery_capacity * 100

            # Get additional data from hourly_data
            # Don't provide defaults - if data isn't available, it shouldn't be used
            solar_production = 0.0
            grid_import = 0.0
            grid_export = 0.0

            if self.hourly_data:
                if "solar_production" in self.hourly_data and hour < len(
                    self.hourly_data["solar_production"]
                ):
                    solar_production = self.hourly_data["solar_production"][hour]
                if "grid_import" in self.hourly_data and hour < len(
                    self.hourly_data["grid_import"]
                ):
                    grid_import = self.hourly_data["grid_import"][hour]
                if "grid_export" in self.hourly_data and hour < len(
                    self.hourly_data["grid_export"]
                ):
                    grid_export = self.hourly_data["grid_export"][hour]

            # Calculate costs
            base_cost = consumption * price
            grid_cost = grid_import * price - grid_export * price * 0.6
            savings = base_cost - grid_cost

            hour_data = {
                "hour": str(hour),
                "price": price,
                "electricityPrice": price,
                "consumption": consumption,
                "homeConsumption": consumption,
                "batteryLevel": soc_percent,
                "batterySoc": soc_percent,
                "action": action,
                "batteryAction": action,
                "strategic_intent": intent,
                "strategicIntent": intent,
                # Cost fields
                "gridCost": grid_cost,
                "batteryCost": 0.0,
                "totalCost": grid_cost,
                "baseCost": base_cost,
                "savings": savings,
                "hourlyCost": grid_cost,
                "hourlySavings": savings,
                # Energy flows
                "solarProduction": solar_production,
                "gridImport": grid_import,
                "gridExported": grid_export,
                "gridImported": grid_import,
                "batteryCharge": max(0, action),
                "batteryDischarge": max(0, -action),
                # Additional fields for compatibility
                "data_source": "predicted",
                "dataSource": "predicted",
                "battery_soc_start": soc_percent,
                "solarCharged": min(max(0, action), solar_production),
                "effective_diff": 0.0,
                "opportunity_score": 0.0,
            }

            hourly_data.append(hour_data)

        # Calculate summary
        total_consumption = sum(h["homeConsumption"] for h in hourly_data)
        total_solar = sum(h["solarProduction"] for h in hourly_data)
        total_grid_import = sum(h["gridImport"] for h in hourly_data)
        total_grid_export = sum(h["gridExported"] for h in hourly_data)
        total_battery_charge = sum(h["batteryCharge"] for h in hourly_data)
        total_battery_discharge = sum(h["batteryDischarge"] for h in hourly_data)
        avg_price = (
            sum(h["price"] for h in hourly_data) / len(hourly_data)
            if hourly_data
            else 0.0
        )

        # Summary calculations
        total_base_cost = sum(h["baseCost"] for h in hourly_data)
        total_optimized_cost = sum(h["totalCost"] for h in hourly_data)
        total_savings = sum(h["savings"] for h in hourly_data)

        summary = {
            "baseCost": total_base_cost,
            "optimizedCost": total_optimized_cost,
            "gridCosts": total_grid_import * avg_price,
            "batteryCosts": 0,
            "savings": total_savings,
            "totalSolarProduction": total_solar,
            "totalBatteryCharge": total_battery_charge,
            "totalBatteryDischarge": total_battery_discharge,
            "totalGridImport": total_grid_import,
            "totalGridExport": total_grid_export,
            "cycleCount": total_battery_discharge
            / battery_capacity,  # Use actual battery capacity
            "avgBuyPrice": avg_price,
            "avgSellPrice": avg_price * 0.6,
            "totalConsumption": total_consumption,
            "estimatedBatteryCycles": total_battery_discharge / battery_capacity,
        }

        # Add strategic intent summary
        intent_summary = {}
        for hour_data in hourly_data:
            intent = hour_data["strategic_intent"]
            intent_summary[intent] = intent_summary.get(intent, 0) + 1

        return {
            "hourly_data": hourly_data,
            "hourlyData": hourly_data,  # Also provide camelCase version
            "summary": summary,
            "enhancedSummary": summary,
            "strategic_intent_summary": intent_summary,
            "strategicIntentSummary": intent_summary,
            "energyProfile": {
                "consumption": [h["consumption"] for h in hourly_data],
                "solar": [h["solarProduction"] for h in hourly_data],
                "battery_soc": [h["batteryLevel"] for h in hourly_data],
                "actualHours": 0,  # This would be set by the daily view builder
            },
        }
