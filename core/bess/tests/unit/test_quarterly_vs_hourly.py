"""
Test that quarterly resolution optimization (96 periods, dt=0.25) produces
equal or better results than hourly resolution (24 periods, dt=1.0).

This test uses real Nordpool prices and standard battery/home settings
to verify that the higher resolution optimization is at least as good as
the lower resolution version.
"""

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.settings import BatterySettings


def average_to_hourly(quarterly_prices: list[float]) -> list[float]:
    """Average 96 quarterly prices into 24 hourly prices."""
    assert len(quarterly_prices) == 96, "Must have exactly 96 quarterly prices"

    hourly_prices = []
    for hour in range(24):
        # Get 4 quarters for this hour
        start_idx = hour * 4
        quarters = quarterly_prices[start_idx : start_idx + 4]
        # Average them
        hourly_prices.append(sum(quarters) / 4.0)

    return hourly_prices


def test_quarterly_vs_hourly_optimization():
    """
    Test that quarterly resolution produces equal or better optimization results.

    Uses real Nordpool prices from 2025-11-23 to verify that:
    1. Quarterly optimization (96 periods, dt=0.25) respects physical constraints
    2. Quarterly optimization produces savings >= hourly optimization
    3. Energy per period is correctly limited by power * time duration
    """

    # Real Nordpool prices for 2025-11-23 (96 quarterly periods)
    # These are base spot prices - we'll add markup for buy/sell
    quarterly_spot_prices = [
        0.564,
        0.262,
        0.362,
        0.216,
        0.295,
        0.193,
        0.19,
        0.192,
        0.253,
        0.248,
        0.211,
        0.216,
        0.329,
        0.216,
        0.274,
        0.232,
        0.26,
        0.281,
        0.324,
        0.346,
        0.269,
        0.293,
        0.342,
        0.424,
        0.288,
        0.346,
        0.46,
        0.554,
        0.395,
        0.554,
        0.738,
        0.795,
        0.765,
        0.79,
        0.798,
        0.773,
        0.914,
        0.858,
        0.853,
        0.831,
        0.927,
        0.927,
        0.869,
        0.872,
        0.884,
        0.917,
        0.923,
        0.938,
        0.921,
        0.927,
        0.942,
        0.944,
        0.934,
        0.907,
        0.899,
        0.903,
        0.917,
        0.936,
        0.961,
        1.006,
        0.98,
        1.023,
        1.102,
        1.144,
        1.105,
        1.064,
        1.038,
        1.074,
        1.084,
        1.129,
        1.112,
        1.118,
        1.132,
        1.114,
        1.107,
        1.184,
        1.201,
        1.182,
        1.128,
        1.092,
        1.129,
        1.087,
        1.055,
        1.009,
        1.064,
        1.02,
        0.997,
        0.979,
        1.032,
        1.022,
        1.001,
        0.971,
        0.966,
        0.957,
        0.955,
        0.932,
    ]

    assert len(quarterly_spot_prices) == 96, "Should have 96 quarterly spot prices"

    # Apply realistic markup to create buy/sell prices
    # Buy price: spot + 15% markup (realistic grid purchase markup)
    # Sell price: spot - 10% (realistic grid export discount)
    quarterly_buy_prices = [price * 1.15 for price in quarterly_spot_prices]
    quarterly_sell_prices = [price * 0.90 for price in quarterly_spot_prices]

    # Create hourly prices by averaging
    hourly_buy_prices = average_to_hourly(quarterly_buy_prices)
    hourly_sell_prices = average_to_hourly(quarterly_sell_prices)
    assert len(hourly_buy_prices) == 24, "Should have 24 hourly buy prices"
    assert len(hourly_sell_prices) == 24, "Should have 24 hourly sell prices"

    # Standard battery settings
    battery_settings = BatterySettings(
        total_capacity=30.0,  # kWh
        min_soc=10.0,  # %
        max_soc=100.0,  # %
        max_charge_power_kw=15.0,  # kW
        max_discharge_power_kw=15.0,  # kW
        efficiency_charge=0.97,
        efficiency_discharge=0.95,
        cycle_cost_per_kwh=0.40,
    )

    # Standard home consumption (quarterly: per 15-min, hourly: per hour)
    # For quarterly: 4.6 kWh/hour ÷ 4 = 1.15 kWh per 15-min period
    quarterly_consumption = [1.15] * 96
    hourly_consumption = [4.6] * 24

    # No solar production for simplicity
    quarterly_solar = [0.0] * 96
    hourly_solar = [0.0] * 24

    # Initial battery state
    initial_soe = battery_settings.min_soe_kwh

    # Run quarterly optimization (dt=0.25)
    quarterly_result = optimize_battery_schedule(
        buy_price=quarterly_buy_prices,
        sell_price=quarterly_sell_prices,
        home_consumption=quarterly_consumption,
        solar_production=quarterly_solar,
        initial_soe=initial_soe,
        battery_settings=battery_settings,
        period_duration_hours=0.25,  # 15-minute periods
    )

    # Run hourly optimization (dt=1.0)
    hourly_result = optimize_battery_schedule(
        buy_price=hourly_buy_prices,
        sell_price=hourly_sell_prices,
        home_consumption=hourly_consumption,
        solar_production=hourly_solar,
        initial_soe=initial_soe,
        battery_settings=battery_settings,
        period_duration_hours=1.0,  # 1-hour periods
    )

    # Verify physical constraints for quarterly optimization
    max_energy_per_quarter = (
        battery_settings.max_charge_power_kw * 0.25
    )  # 15 kW * 0.25h = 3.75 kWh

    for i, period_data in enumerate(quarterly_result.period_data):
        battery_charged = period_data.energy.battery_charged
        battery_discharged = period_data.energy.battery_discharged

        # Check charge constraint
        assert battery_charged <= max_energy_per_quarter + 0.01, (
            f"Period {i}: Charged {battery_charged:.2f} kWh exceeds "
            f"max {max_energy_per_quarter:.2f} kWh for 15-min period"
        )

        # Check discharge constraint
        assert battery_discharged <= max_energy_per_quarter + 0.01, (
            f"Period {i}: Discharged {battery_discharged:.2f} kWh exceeds "
            f"max {max_energy_per_quarter:.2f} kWh for 15-min period"
        )

    # Verify hourly optimization constraints
    max_energy_per_hour = (
        battery_settings.max_charge_power_kw * 1.0
    )  # 15 kW * 1h = 15 kWh

    for i, period_data in enumerate(hourly_result.period_data):
        battery_charged = period_data.energy.battery_charged
        battery_discharged = period_data.energy.battery_discharged

        assert battery_charged <= max_energy_per_hour + 0.01, (
            f"Hour {i}: Charged {battery_charged:.2f} kWh exceeds "
            f"max {max_energy_per_hour:.2f} kWh for 1-hour period"
        )

        assert battery_discharged <= max_energy_per_hour + 0.01, (
            f"Hour {i}: Discharged {battery_discharged:.2f} kWh exceeds "
            f"max {max_energy_per_hour:.2f} kWh for 1-hour period"
        )

    # Extract savings
    quarterly_savings = quarterly_result.economic_summary.grid_to_battery_solar_savings
    hourly_savings = hourly_result.economic_summary.grid_to_battery_solar_savings

    # Verify quarterly optimization is at least as good as hourly
    # Allow small numerical tolerance (0.1 SEK = 10 öre)
    assert quarterly_savings >= hourly_savings - 0.1, (
        f"Quarterly optimization ({quarterly_savings:.2f} SEK) should be "
        f"equal or better than hourly ({hourly_savings:.2f} SEK). "
        f"Quarterly has more flexibility and should never be worse."
    )

    # Calculate improvement
    improvement = quarterly_savings - hourly_savings
    improvement_pct = (improvement / max(hourly_savings, 0.01)) * 100.0

    print(f"\n{'='*70}")
    print("Quarterly vs Hourly Optimization Comparison")
    print(f"{'='*70}")
    print("Hourly optimization (24 periods, dt=1.0):")
    print(
        f"  Grid-only cost:    {hourly_result.economic_summary.grid_only_cost:.2f} SEK"
    )
    print(
        f"  Optimized cost:    {hourly_result.economic_summary.battery_solar_cost:.2f} SEK"
    )
    print(f"  Savings:           {hourly_savings:.2f} SEK")
    print("")
    print("Quarterly optimization (96 periods, dt=0.25):")
    print(
        f"  Grid-only cost:    {quarterly_result.economic_summary.grid_only_cost:.2f} SEK"
    )
    print(
        f"  Optimized cost:    {quarterly_result.economic_summary.battery_solar_cost:.2f} SEK"
    )
    print(f"  Savings:           {quarterly_savings:.2f} SEK")
    print("")
    print("Improvement:")
    print(f"  Additional savings: {improvement:.2f} SEK ({improvement_pct:+.1f}%)")
    print(f"{'='*70}\n")

    # Verify energy balance for both
    for i, period_data in enumerate(quarterly_result.period_data):
        is_valid, message = period_data.energy.validate_energy_balance(tolerance=0.2)
        assert is_valid, f"Quarterly period {i} energy balance failed: {message}"

    for i, period_data in enumerate(hourly_result.period_data):
        is_valid, message = period_data.energy.validate_energy_balance(tolerance=0.2)
        assert is_valid, f"Hourly hour {i} energy balance failed: {message}"

    # Success - quarterly is equal or better
    assert True, "Quarterly optimization validated successfully"


if __name__ == "__main__":
    # Run the test directly
    test_quarterly_vs_hourly_optimization()
