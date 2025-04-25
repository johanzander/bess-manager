"""Generic battery schedule representation with hourly granularity."""

import logging

from .savings_calculator import HourlyResult, SavingsCalculator

logger = logging.getLogger(__name__)


def create_interval(
    start_time: str,
    end_time: str,
    state: str,
    action: float,
    state_of_energy: float,
    solar_charged: float,
) -> dict:
    """Create an interval dictionary with all required fields."""
    return {
        "start_time": start_time,
        "end_time": end_time,
        "state": state,
        "action": float(action),
        "state_of_energy": float(state_of_energy),
        "solar_charged": float(solar_charged),
    }


class Schedule:
    """Generic battery schedule representation with hourly granularity."""

    def __init__(self) -> None:
        """Initialize schedule state."""
        self.actions: list[float] = []
        self.state_of_energy: list[float] = []
        self.intervals: list[dict] = []
        self.hourly_results: list[HourlyResult] = []
        self.calc: SavingsCalculator | None = None
        self.hourly_settings: list[dict] = []
        self.optimization_results = None
        self.solar_charged: list[float] = []

    def set_optimization_results(
        self,
        actions: list[float],
        state_of_energy: list[float],
        prices: list[float],
        cycle_cost: float,
        hourly_consumption: list[float],
        solar_charged: list[float] | None = None,
    ) -> None:
        """Set optimization results and calculate costs.

        Args:
            actions: List of charge/discharge actions
            state_of_energy: List of battery energy states for each hour
            prices: List of electricity prices
            cycle_cost: Battery cycle cost
            hourly_consumption: List of consumption values
            solar_charged: List of hourly solar charged energy values

        """
        # Store all data directly as provided by the algorithm
        self.actions = list(actions)  # Make a copy to avoid reference issues
        self.state_of_energy = list(state_of_energy)  # Make a copy
        self.solar_charged = (
            list(solar_charged) if solar_charged else [0.0] * len(actions)
        )

        # Log solar charging for debugging
        total_solar = sum(self.solar_charged)
        if total_solar > 0:
            solar_hours = []
            for hour, solar in enumerate(self.solar_charged):
                if solar > 0:
                    solar_hours.append(f"Hour {hour}: {solar:.1f} kWh")

            logger.debug(
                "Schedule includes solar charging: %.1f kWh at %s",
                total_solar,
                ", ".join(solar_hours),
            )

        # Calculate hourly results for display
        self.calc = SavingsCalculator(cycle_cost, hourly_consumption)
        self.hourly_results = self.calc.calculate_hourly_results(
            prices=prices,
            actions=self.actions,
            state_of_energy=self.state_of_energy,
            solar_charged_kwh=self.solar_charged,
        )

        # Format data for display
        schedule_data = self.calc.format_schedule_data(self.hourly_results)

        # Store the original optimization results for reference
        hourly_costs = []
        for r in self.hourly_results:
            cost_dict = {
                "base_cost": r.base_cost,
                "grid_cost": r.grid_cost,
                "battery_cost": r.battery_cost,
                "total_cost": r.total_cost,
                "savings": r.savings,
            }
            hourly_costs.append(cost_dict)

        self.optimization_results = {
            "actions": self.actions,
            "state_of_energy": self.state_of_energy,
            "solar_charged": self.solar_charged,  # Make sure this is included
            "base_cost": schedule_data["summary"]["baseCost"],
            "optimized_cost": schedule_data["summary"]["optimizedCost"],
            "cost_savings": schedule_data["summary"]["savings"],
            "hourly_costs": hourly_costs,
        }

        self._create_hourly_intervals()

    def _create_hourly_intervals(self) -> None:
        """Create one interval per hour."""
        self.intervals = []
        hour = 0
        while hour < len(self.actions):
            # Determine state based on action
            if self.actions[hour] > 0:
                state = "charging"
            elif self.actions[hour] < 0:
                state = "discharging"
            else:
                state = "standby"

            # Create and append interval
            interval = create_interval(
                start_time=f"{hour:02d}:00",
                end_time=f"{hour:02d}:59",
                state=state,
                action=self.actions[hour],
                state_of_energy=self.state_of_energy[hour],
                solar_charged=self.solar_charged[hour],
            )
            self.intervals.append(interval)
            hour += 1

    def get_hour_settings(self, hour: int) -> dict:
        """Get settings for a specific hour."""
        if hour < 0 or hour >= len(self.intervals):
            return {
                "state": "standby",
                "action": 0.0,
                "state_of_energy": float(
                    self.state_of_energy[0] if self.state_of_energy else 0.0
                ),
            }
        return {
            "state": self.intervals[hour]["state"],
            "action": self.intervals[hour]["action"],
            "state_of_energy": self.intervals[hour]["state_of_energy"],
        }

    def get_daily_intervals(self) -> list[dict]:
        """Get all hourly intervals for the day."""
        return self.intervals

    def get_schedule_data(self) -> dict:
        """Get complete schedule data."""
        if not self.calc or not self.hourly_results:
            raise ValueError(
                "Schedule not fully initialized - missing cost calculations"
            )
        return self.calc.format_schedule_data(self.hourly_results)

    def log_schedule(self) -> None:
        """Print the current schedule data in formatted table."""
        schedule_data = self.get_schedule_data()
        hourly_data = schedule_data["hourlyData"]
        summary = schedule_data["summary"]

        # Table headers with solar column
        lines = [
            "\nBattery Schedule:",
            "╔════════╦═════════════════════════════╦╦══════════════════════════════════════════════════════════════════════╗",
            "║        ║        Base Case            ║║                            Optimized Case                            ║",
            "║  Hour  ╠═════════╦═══════╦═══════════╬╬══════╦═══════╦════════╦═════════╦═══════════╦════════════╦═══════════╣",
            "║        ║  Price  ║ Cons. ║   Cost    ║║  SOE ║ Solar ║ Action ║ G.Cost  ║  B.Cost   ║ Tot. Cost  ║  Savings  ║",
            "╠════════╬═════════╬═══════╬═══════════╬╬══════╬═══════╬════════╬═════════╬═══════════╬════════════╬═══════════╣",
        ]

        # Format hourly data
        total_charged = 0
        total_discharged = 0
        total_solar = 0

        for hour_data in hourly_data:
            action = hour_data["action"]
            solar = hour_data.get("solarCharged", 0.0)
            if action > 0:
                total_charged += action
            elif action < 0:
                total_discharged -= action
            total_solar += solar

            row = (
                f"║ {hour_data['hour']}  ║"
                f" {hour_data['price']:>7.3f} ║"
                f" {hour_data['consumption']:>5.1f} ║"
                f" {hour_data['baseCost']:>9.2f} ║║"
                f" {hour_data['batteryLevel']:>4.1f} ║"
                f" {solar:>5.1f} ║"
                f" {action:>6.1f} ║"
                f" {hour_data['gridCost']:>7.2f} ║"
                f" {hour_data['batteryCost']:>9.2f} ║"
                f" {hour_data['totalCost']:>10.2f} ║"
                f" {hour_data['savings']:>9.2f} ║"
            )
            lines.append(row)

        # Format totals
        total_consumption = 0
        for hour_data in hourly_data:
            total_consumption += hour_data["consumption"]

        lines.extend(
            [
                "╠════════╬═════════╬═══════╬═══════════╬╬══════╬═══════╬════════╬═════════╬═══════════╬════════════╬═══════════╣",
                f"║ TOTAL  ║         ║{total_consumption:>7.1f}║{summary['baseCost']:>10.2f} ║║      ║"
                f"S:{total_solar:>4.1f} ║"
                f"C:{total_charged:>5.1f} ║"
                f"{summary['gridCosts']:>8.2f} ║{summary['batteryCosts']:>10.2f} ║"
                f"{summary['optimizedCost']:>11.2f} ║{summary['savings']:>10.2f} ║",
                f"║        ║         ║       ║           ║║      ║       ║D:{total_discharged:>5.1f} ║         ║           ║            ║           ║",
                "╚════════╩═════════╩═══════╩═══════════╩╩══════╩═══════╩════════╩═════════╩═══════════╩════════════╩═══════════╝",
            ]
        )

        # Format summary
        lines.extend(
            [
                "\nSummary:",
                f"Base case cost:               {summary['baseCost']:>8.2f} SEK",
                f"Optimized cost:               {summary['optimizedCost']:>8.2f} SEK",
                f"Total savings:                {summary['savings']:>8.2f} SEK",
                f"Savings percentage:           {(summary['savings']/summary['baseCost']*100):>8.1f} %",
                f"Total energy charged:         {total_charged:>8.1f} kWh",
                f"Total solar charging:         {total_solar:>8.1f} kWh",
                f"Total energy discharged:      {total_discharged:>8.1f} kWh\n",
            ]
        )

        logger.info("\n".join(lines))
