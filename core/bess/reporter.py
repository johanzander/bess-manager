"""Battery system reporting module for comprehensive analysis and visualization.

This module provides tools to generate comparative reports between different
energy scenarios (grid-only, solar-only, and battery-optimized) to highlight
the economic benefits of each approach.
"""

import logging

logger = logging.getLogger(__name__)


class BatterySystemReporter:
    """Generates comprehensive reports comparing different energy scenarios."""

    def __init__(self, energy_manager, schedule_getter, price_manager) -> None:
        """Initialize with required dependencies.

        Args:
            energy_manager: Energy manager instance with solar and consumption data
            schedule_getter: Function that returns the current schedule
            price_manager: Price manager for buy/sell price
        """
        self.energy_manager = energy_manager
        self.schedule_getter = schedule_getter
        self.price_manager = price_manager

    def generate_comparison_report(self) -> dict:
        """Generate a comprehensive comparison of grid-only, solar-only, and battery scenarios.

        Returns:
            dict: Complete report data with hourly breakdown and summary metrics
        """
        # Get the current schedule using the getter
        current_schedule = self.schedule_getter()
        if not current_schedule:
            logger.error("No current schedule available for reporting")
            return {}

        # Get optimization results from schedule
        schedule_data = current_schedule.get_schedule_data()
        hourly_data = schedule_data["hourlyData"]
        summary = schedule_data[
            "summary"
        ].copy()  # Create a copy to avoid modifying original

        # Get prices from schedule - needed for calculations
        prices = self._extract_prices(hourly_data)

        # Get solar and consumption data from energy manager
        energy_profile = self.energy_manager.get_full_day_energy_profile()
        solar_production = energy_profile["solar"]
        consumption = energy_profile["consumption"]

        # Calculate solar-only scenario
        solar_only_data = self._calculate_solar_only_scenario(
            solar_production=solar_production, consumption=consumption, prices=prices
        )

        # Enhance hourly data with solar-only scenario
        for hour, hour_data in enumerate(hourly_data):
            if hour < len(solar_only_data["hourly"]):
                solar_hour_data = solar_only_data["hourly"][hour]

                # Grid-only case - use consumption * price
                grid_only_cost = (
                    solar_hour_data["consumption"] * solar_hour_data["price"]
                )
                hour_data["baseCost"] = grid_only_cost

                # Add solar-only scenario values
                hour_data["solarProduction"] = solar_hour_data["solar_production"]
                hour_data["directSolarUsed"] = solar_hour_data["direct_solar_used"]
                hour_data["excessSolar"] = solar_hour_data["excess_solar"]
                hour_data["solarOnlyGridImport"] = solar_hour_data["grid_import"]
                hour_data["solarSellRevenue"] = solar_hour_data["sell_revenue"]
                hour_data["solarOnlyCost"] = solar_hour_data["net_cost"]
                hour_data["solarOnlySavings"] = solar_hour_data["savings"]

        # Update summary with enhanced metrics
        summary["baseCost"] = solar_only_data["summary"]["grid_only_total_cost"]
        summary["gridOnlyCost"] = solar_only_data["summary"]["grid_only_total_cost"]
        summary["solarOnlyCost"] = solar_only_data["summary"]["solar_only_total_cost"]
        summary["solarOnlySavings"] = solar_only_data["summary"]["solar_only_savings"]

        # Calculate total battery charge, discharge and cycles
        total_battery_charge = 0.0
        total_battery_discharge = 0.0

        for hour_data in hourly_data:
            action = hour_data.get("action", 0.0)
            if action > 0:
                total_battery_charge += action
            elif action < 0:
                total_battery_discharge += abs(action)

        # Add metrics to summary
        summary["totalBatteryCharge"] = total_battery_charge
        summary["totalBatteryDischarge"] = total_battery_discharge

        # Estimate battery cycles (full cycle = charge capacity / total capacity)
        # Access capacity from the current schedule if available
        battery_capacity = 30.0  # Default capacity in kWh
        if hasattr(current_schedule, "total_capacity"):
            battery_capacity = current_schedule.total_capacity

        estimated_cycles = (total_battery_charge + total_battery_discharge) / (
            2 * battery_capacity
        )
        summary["cycleCount"] = estimated_cycles

        # Battery-only savings is the additional savings beyond solar-only
        total_savings = summary["baseCost"] - summary["optimizedCost"]
        battery_only_savings = total_savings - summary["solarOnlySavings"]

        summary["batterySavings"] = battery_only_savings
        summary["totalSavings"] = total_savings
        summary["totalSolarProduction"] = solar_only_data["summary"][
            "total_solar_production"
        ]
        summary["totalDirectSolar"] = solar_only_data["summary"]["total_direct_solar"]
        summary["totalExcessSolar"] = solar_only_data["summary"]["total_excess_solar"]
        summary["totalGridImport"] = solar_only_data["summary"]["total_grid_import"]
        summary["totalSellRevenue"] = solar_only_data["summary"]["total_sell_revenue"]

        return {"hourlyData": hourly_data, "summary": summary}

    def generate_daily_savings_report(self) -> dict:
        """Generate a daily savings report focused on economic metrics.

        This is a more focused report than the full comparison report,
        emphasizing financial savings and key metrics for the daily dashboard.

        Returns:
            dict: Daily savings report data
        """
        # Currently just an alias for generate_comparison_report
        # You can extend this with more specific daily savings information
        return self.generate_comparison_report()

    def _extract_prices(self, hourly_data) -> list:
        """Extract hourly prices from schedule data.

        Args:
            hourly_data: Hourly data from schedule

        Returns:
            list: Hourly prices
        """
        prices = []
        for hour_data in hourly_data:
            prices.append(hour_data.get("price", 0))
        return prices

    def _calculate_solar_only_scenario(
        self, solar_production, consumption, prices
    ) -> dict:
        """Calculate hypothetical scenario with solar but no battery.

        Args:
            solar_production: Hourly solar production values
            consumption: Hourly consumption values
            prices: Hourly electricity prices

        Returns:
            dict: Solar-only scenario data
        """
        # Initialize tracking variables
        solar_only_total_cost = 0.0
        grid_only_total_cost = 0.0
        total_solar_production = sum(solar_production)
        total_direct_solar = 0.0
        total_excess_solar = 0.0
        total_grid_import = 0.0
        total_sell_revenue = 0.0
        hourly_results = []

        # Process each hour
        for hour in range(min(len(solar_production), len(consumption), len(prices))):
            price = prices[hour]
            hourly_consumption = consumption[hour]
            hourly_solar = solar_production[hour]

            # GRID-ONLY CASE - consumption from grid
            grid_only_cost = price * hourly_consumption
            grid_only_total_cost += grid_only_cost

            # SOLAR-ONLY CASE
            # 1. Use solar directly when available
            direct_solar_used = min(hourly_consumption, hourly_solar)
            total_direct_solar += direct_solar_used

            # 2. If extra consumption needed, import from grid
            grid_import = max(0, hourly_consumption - direct_solar_used)
            total_grid_import += grid_import

            # 3. If excess solar, export to grid
            excess_solar = max(0, hourly_solar - direct_solar_used)
            total_excess_solar += excess_solar

            # Calculate costs based on these flows
            grid_buy_cost = price * grid_import

            # Get sell price from price manager
            price_data = self.price_manager.calculate_prices(price)
            sell_price = price_data.get("sellPrice")

            sell_revenue = sell_price * excess_solar
            total_sell_revenue += sell_revenue

            # Net cost calculation
            net_cost = grid_buy_cost - sell_revenue
            solar_only_total_cost += net_cost

            # Calculate savings compared to grid-only base case
            savings = grid_only_cost - net_cost

            # Store hourly results
            hourly_results.append(
                {
                    "hour": hour,
                    "price": price,
                    "consumption": hourly_consumption,
                    "solar_production": hourly_solar,
                    "direct_solar_used": direct_solar_used,
                    "grid_import": grid_import,
                    "excess_solar": excess_solar,
                    "grid_buy_cost": grid_buy_cost,
                    "sell_revenue": sell_revenue,
                    "net_cost": net_cost,
                    "savings": savings,
                }
            )

        # Calculate solar-only savings
        solar_only_savings = grid_only_total_cost - solar_only_total_cost

        return {
            "hourly": hourly_results,
            "summary": {
                "grid_only_total_cost": grid_only_total_cost,
                "solar_only_total_cost": solar_only_total_cost,
                "solar_only_savings": solar_only_savings,
                "total_solar_production": total_solar_production,
                "total_direct_solar": total_direct_solar,
                "total_excess_solar": total_excess_solar,
                "total_grid_import": total_grid_import,
                "total_sell_revenue": total_sell_revenue,
            },
        }

    def log_comparison_report(self) -> None:
        """Generate and log a battery schedule report with grid-only and solar-only comparisons."""
        try:
            report_data = self.generate_comparison_report()
            if not report_data:
                logger.error("Failed to generate comparison report")
                return

            hourly_data = report_data["hourlyData"]
            summary = report_data["summary"]

            # Format the report as a table
            self._log_formatted_table(hourly_data, summary)

        except Exception as e:
            logger.error(f"Error generating comparison report: {e}")

    def _log_formatted_table(self, hourly_data, summary) -> None:
        """Format and log the report as a table.

        Args:
            hourly_data: Hourly data from the report
            summary: Summary metrics from the report
        """
        # Table headers with three scenarios
        lines = [
            "\nBattery Schedule:",
            "╔═══════╦══════════════════════════╦══════════════════════════════════════════════════════╦═════════════════════════════════════════════╗",
            "║       ║     Grid-Only Case       ║                  Solar-Only Case                     ║             Solar+Battery Case              ║",
            "╠═══════╬════════╦════════╦════════╬════════╦════════╦════════╦════════╦════════╦═════════╬════════╦════════╦════════╦════════╦═════════╣",
            "║ Hour  ║ Price  ║ Cons.  ║  Cost  ║ Solar  ║ Direct ║ Export ║ Import ║  Cost  ║ Savings ║  SOE   ║ Action ║  Grid  ║  Cost  ║ Savings ║",
            "╠═══════╬════════╬════════╬════════╬════════╬════════╬════════╬════════╬════════╬═════════╬════════╬════════╬════════╬════════╬═════════╣",
        ]

        # Format hourly data
        total_charged = 0
        total_discharged = 0
        total_solar = 0
        total_direct_solar = 0
        total_excess_solar = 0
        total_solar_only_grid_import = 0
        total_batt_grid = 0

        for hour_data in hourly_data:
            action = hour_data.get("action", 0.0)
            solar = hour_data.get("solarProduction", 0.0)
            direct_solar = hour_data.get("directSolarUsed", 0.0)
            excess_solar = hour_data.get("excessSolar", 0.0)
            solar_only_grid_import = hour_data.get("solarOnlyGridImport", 0.0)
            solar_only_cost = hour_data.get("solarOnlyCost", 0.0)
            solar_only_savings = hour_data.get("solarOnlySavings", 0.0)
            consumption = hour_data.get("consumption", 0.0)
            base_cost = hour_data.get("baseCost", 0.0)
            price = hour_data.get("price", 0.0)
            battery_savings = hour_data.get("savings", 0.0)

            if action > 0:
                total_charged += action
            elif action < 0:
                total_discharged -= action

            total_solar += solar
            total_direct_solar += direct_solar
            total_excess_solar += excess_solar
            total_solar_only_grid_import += solar_only_grid_import

            # For grid in battery case, calculate from gridCost if available
            if "gridCost" in hour_data and price > 0:
                grid_used = hour_data["gridCost"] / price
            else:
                grid_used = hour_data.get("gridUsed", 0.0)

            total_batt_grid += grid_used

            # Format the row
            row = (
                f"║ {hour_data['hour']} ║"
                f" {price:>6.2f} ║"
                f" {consumption:>6.1f} ║"
                f" {base_cost:>6.2f} ║"
                f" {solar:>6.1f} ║"
                f" {direct_solar:>6.1f} ║"
                f" {excess_solar:>6.1f} ║"
                f" {solar_only_grid_import:>6.1f} ║"
                f" {solar_only_cost:>6.2f} ║"
                f" {solar_only_savings:>7.2f} ║"
                f" {hour_data.get('batteryLevel', 0):>6.1f} ║"
                f" {action:>6.1f} ║"
                f" {grid_used:>6.1f} ║"
                f" {hour_data.get('totalCost', 0):>6.2f} ║"
                f" {battery_savings:>7.2f} ║"
            )
            lines.append(row)

        # Format totals
        total_consumption = sum(
            hour_data.get("consumption", 0.0) for hour_data in hourly_data
        )
        solar_only_cost = summary.get("solarOnlyCost", 0.0)
        solar_only_savings = summary.get("solarOnlySavings", 0.0)
        battery_savings = summary.get("batterySavings", 0.0)

        lines.extend(
            [
                "╠═══════╬════════╬════════╬════════╬════════╬════════╬════════╬════════╬════════╬═════════╬════════╬════════╬════════╬════════╬═════════╣",
                f"║ TOTAL ║        ║{total_consumption:>7.1f} ║{summary.get('baseCost', 0):>7.2f} ║"
                f"{total_solar:>7.1f} ║{total_direct_solar:>7.1f} ║{total_excess_solar:>7.1f} ║{total_solar_only_grid_import:>7.1f} ║"
                f"{solar_only_cost:>7.2f} ║{solar_only_savings:>8.2f} ║        ║"
                f" C:{total_charged:>4.1f} ║{total_batt_grid:>7.1f} ║"
                f"{summary.get('optimizedCost', 0):>7.2f} ║{battery_savings:>8.2f} ║",
                "╚═══════╩════════╩════════╩════════╩════════╩════════╩════════╩════════╩════════╩═════════╩════════╩════════╩════════╩════════╩═════════╝",
            ]
        )

        # Format enhanced summary
        solar_savings_pct = (
            (summary.get("solarOnlySavings", 0) / summary.get("baseCost", 1) * 100)
            if summary.get("baseCost", 0) > 0
            else 0
        )
        battery_savings_pct = (
            (summary.get("batterySavings", 0) / summary.get("baseCost", 1) * 100)
            if summary.get("baseCost", 0) > 0
            else 0
        )
        total_savings_pct = (
            (summary.get("savings", 0) / summary.get("baseCost", 1) * 100)
            if summary.get("baseCost", 0) > 0
            else 0
        )

        lines.extend(
            [
                "\nEnhanced Savings Summary:",
                f"Grid-Only Cost:                 {summary.get('baseCost', 0):>8.2f} SEK",
                f"Solar-Only Cost:                {solar_only_cost:>8.2f} SEK",
                f"Solar+Battery Cost:             {summary.get('optimizedCost', 0):>8.2f} SEK",
                "",
                f"Solar Savings:                  {solar_only_savings:>8.2f} SEK ({solar_savings_pct:>5.1f}%)",
                f"Additional Battery Savings:     {battery_savings:>8.2f} SEK ({battery_savings_pct:>5.1f}%)",
                f"Total Combined Savings:         {summary.get('savings', 0):>8.2f} SEK ({total_savings_pct:>5.1f}%)",
                "",
                f"Total Solar Production:         {summary.get('totalSolarProduction', 0):>8.1f} kWh",
                f"- Direct Solar Use:             {summary.get('totalDirectSolar', 0):>8.1f} kWh",
                f"- Excess Solar Sold:            {summary.get('totalExcessSolar', 0):>8.1f} kWh",
                f"Total Energy Charged:           {summary.get('totalBatteryCharge', 0):>8.1f} kWh",
                f"Total Energy Discharged:        {summary.get('totalBatteryDischarge', 0):>8.1f} kWh",
                f"Estimated Battery Cycles:       {summary.get('cycleCount', 0):>8.1f}\n",
            ]
        )

        # Log the formatted report
        logger.info("\n".join(lines))
