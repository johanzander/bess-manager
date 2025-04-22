"""Module for battery schedule savings calculations."""

# Add this function to savings_calculator.py


def calculate_trade_profitability(
    charge_price: float,
    discharge_price: float,
    charge_amount: float,
    cycle_cost: float,
    solar_amount: float = 0.0,
) -> tuple[bool, float]:
    """Calculate if a charge/discharge trade is profitable.

    Args:
        charge_price: Price when charging (SEK/kWh)
        discharge_price: Price when discharging (SEK/kWh)
        charge_amount: Amount of energy to charge (kWh)
        cycle_cost: Battery wear cost per kWh (SEK/kWh)
        solar_amount: Amount of solar energy used (kWh)

    Returns:
        Tuple of (is_profitable, profit_amount)

    """
    # Calculate grid charging cost (only apply to grid portion)
    grid_charge_amount = max(0, charge_amount - solar_amount)
    charging_cost = grid_charge_amount * charge_price

    # Calculate cycle cost (applies to all charging)
    battery_cost = charge_amount * cycle_cost

    # Calculate discharge savings
    discharge_savings = charge_amount * discharge_price

    # Calculate net profit
    profit = discharge_savings - charging_cost - battery_cost

    return profit > 0, profit


class HourlyResult:
    """Results for a single hour."""

    def __init__(
        self,
        hour: int,
        price: float,
        consumption_kwh: float,
        battery_action_kwh: float,
        battery_soe_kwh: float,
        solar_charged_kwh: float,
        base_cost: float,
        grid_cost: float,
        battery_cost: float,
        total_cost: float,
        savings: float,
    ) -> None:
        """Init function."""
        self.hour = hour
        self.price = price
        self.consumption_kwh = consumption_kwh
        self.battery_soe_kwh = battery_soe_kwh
        self.battery_action_kwh = battery_action_kwh
        self.solar_charged_kwh = solar_charged_kwh
        self.base_cost = base_cost
        self.grid_cost = grid_cost
        self.battery_cost = battery_cost
        self.total_cost = total_cost
        self.savings = savings

    def to_dict(self) -> dict:
        """Convert to dict."""
        return {
            "hour": f"{self.hour:02d}:00",
            "price": self.price,
            "consumption": self.consumption_kwh,
            "batteryLevel": self.battery_soe_kwh,
            "action": self.battery_action_kwh,
            "solarCharged": self.solar_charged_kwh,
            "gridCost": self.grid_cost,
            "batteryCost": self.battery_cost,
            "totalCost": self.total_cost,
            "baseCost": self.base_cost,
            "savings": self.savings,
        }


class SavingsCalculator:
    """Calculates costs and savings for battery schedule."""

    def __init__(self, cycle_cost: float, hourly_consumption: list[float]) -> None:
        """Init function."""
        self.cycle_cost = cycle_cost
        self.hourly_consumption = hourly_consumption

    def calculate_hourly_results(
        self,
        prices: list[float],
        actions: list[float],
        state_of_energy: list[float],
        solar_charged_kwh: list[float] | None = None,
    ) -> list[HourlyResult]:
        """Calculate detailed results for each hour."""
        if solar_charged_kwh is None:
            solar_charged_kwh = [0.0] * len(actions)

        results = []
        for hour, (price, action, solar, battery_soe, consumption) in enumerate(
            zip(
                prices,
                actions,
                solar_charged_kwh,
                state_of_energy,
                self.hourly_consumption,
                strict=False,
            )
        ):
            # Calculate base case (no battery, but including solar benefit)
            # Solar directly offsets consumption, only pay for remaining from grid
            grid_consumption_base = max(0, consumption - solar)
            base_cost = grid_consumption_base * price

            # Calculate optimized case with battery
            if action >= 0:  # Charging or standby
                # Grid cost = consumption not covered by solar + charging from grid
                grid_consumption = max(0, consumption - solar) + action
                grid_cost = grid_consumption * price

                # Battery costs apply to all charging (both solar and grid)
                battery_cost = action * self.cycle_cost
            else:  # Discharging
                # Discharge reduces grid consumption (after solar is applied)
                grid_consumption = max(
                    0, consumption + action - solar
                )  # action is negative
                grid_cost = grid_consumption * price if grid_consumption > 0 else 0

                # No cycle cost for discharging
                battery_cost = 0

            # Calculate total cost and savings
            total_cost = grid_cost + battery_cost
            savings = base_cost - total_cost

            results.append(
                HourlyResult(
                    hour=hour,
                    price=price,
                    consumption_kwh=consumption,
                    battery_action_kwh=action,
                    battery_soe_kwh=battery_soe,
                    solar_charged_kwh=solar,
                    base_cost=base_cost,
                    grid_cost=grid_cost,
                    battery_cost=battery_cost,
                    total_cost=total_cost,
                    savings=savings,
                )
            )

        return results

    def calculate_summary(self, hourly_results: list[HourlyResult]) -> dict:
        """Calculate summary metrics from hourly results."""
        total_base_cost = 0
        total_grid_cost = 0
        total_battery_cost = 0
        total_savings = 0
        total_charged = 0
        total_discharged = 0

        for r in hourly_results:
            total_base_cost += r.base_cost
            total_grid_cost += r.grid_cost
            total_battery_cost += r.battery_cost
            total_savings += r.savings
            if r.battery_action_kwh > 0:
                total_charged += r.battery_action_kwh
            elif r.battery_action_kwh < 0:
                total_discharged += -r.battery_action_kwh

        total_optimized_cost = total_grid_cost + total_battery_cost

        return {
            "baseCost": total_base_cost,
            "optimizedCost": total_optimized_cost,
            "gridCosts": total_grid_cost,
            "batteryCosts": total_battery_cost,
            "savings": total_savings,
        }

    def format_schedule_data(self, hourly_results: list[HourlyResult]) -> dict:
        """Format complete schedule data for API response."""
        hourly_data = []
        for r in hourly_results:
            hourly_data.append(r.to_dict())  # noqa: PERF401
        return {
            "hourlyData": hourly_data,
            "summary": self.calculate_summary(hourly_results),
        }

    def is_trade_profitable(
        self,
        charge_hour: int,
        discharge_hour: int,
        charge_price: float,
        discharge_price: float,
        charge_amount: float,
        solar_charged: float = 0.0,
    ) -> tuple[bool, float]:
        """Check if a charge/discharge trade is profitable."""
        # Use the shared function for consistent calculations
        return calculate_trade_profitability(
            charge_price=charge_price,
            discharge_price=discharge_price,
            charge_amount=charge_amount,
            cycle_cost=self.cycle_cost,
            solar_amount=solar_charged,
        )
