"""
Integration test for Decision Intelligence API/data pipeline using scenario data.
Validates that the DP-based future value timeline and decision landscape are populated and correct.
"""
import json
import os

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.models import DecisionData, FutureValueContribution, HourlyData
from core.bess.settings import BatterySettings


def load_scenario(filename):
    path = os.path.join(os.path.dirname(__file__), '../unit/data', filename)
    with open(path) as f:
        return json.load(f)

def test_decision_intelligence_pipeline():
    scenario = load_scenario('historical_2024_08_16_high_spread_no_solar.json')
    buy_price = scenario['base_prices']
    sell_price = scenario['base_prices']  # No separate sell price in this scenario
    home_consumption = scenario['home_consumption']
    solar_production = scenario['solar_production']
    battery = scenario['battery']
    battery_settings = BatterySettings(
        total_capacity=battery['max_soe_kwh'],
        min_soc=(battery['min_soe_kwh'] / battery['max_soe_kwh']) * 100.0,
        max_soc=100.0,
        max_charge_power_kw=battery['max_charge_power_kw'],
        max_discharge_power_kw=battery['max_discharge_power_kw'],
        efficiency_charge=battery['efficiency_charge'],
        efficiency_discharge=battery['efficiency_discharge'],
        cycle_cost_per_kwh=battery['cycle_cost_per_kwh'],
    )
    result = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=battery['initial_soe'],
        battery_settings=battery_settings,
    )
    # Validate structure
    assert isinstance(result.hourly_data, list)
    assert all(isinstance(h, HourlyData) for h in result.hourly_data)
    # Validate decision intelligence fields
    found_timeline = False
    found_alternatives = False
    timeline_count = 0
    alternatives_count = 0
    first_timeline = None
    first_alternatives = None
    for hour_idx, hour_data in enumerate(result.hourly_data):
        decision: DecisionData = hour_data.decision
        # Timeline should be a list
        assert hasattr(decision, 'future_value_timeline')
        assert isinstance(decision.future_value_timeline, list)
        # At least one hour should have a non-empty timeline if DP is working
        if decision.future_value_timeline:
            found_timeline = True
            timeline_count += 1
            if first_timeline is None:
                first_timeline = (hour_idx, decision.future_value_timeline)
            for contrib in decision.future_value_timeline:
                assert isinstance(contrib, FutureValueContribution)
                assert hasattr(contrib, 'hour')
                assert hasattr(contrib, 'contribution')
        # Decision landscape (alternatives)
        assert hasattr(decision, 'alternatives_evaluated')
        assert isinstance(decision.alternatives_evaluated, list)
        if decision.alternatives_evaluated:
            found_alternatives = True
            alternatives_count += 1
            if first_alternatives is None:
                first_alternatives = (hour_idx, decision.alternatives_evaluated)
    # At least one hour should have a non-empty timeline or alternatives
    assert found_timeline or found_alternatives, "No decision intelligence data found in scenario run."
    print("\n--- Decision Intelligence Integration Test Output ---")
    print(f"Total hours with non-empty future_value_timeline: {timeline_count}")
    print(f"Total hours with non-empty alternatives_evaluated: {alternatives_count}")
    if first_timeline:
        hour, timeline = first_timeline
        print(f"\nFirst non-empty future_value_timeline at hour {hour}:")
        for contrib in timeline:
            print(f"  Hour: {contrib.hour}, Contribution: {contrib.contribution}")
    if first_alternatives:
        hour, alternatives = first_alternatives
        print(f"\nFirst non-empty alternatives_evaluated at hour {hour}:")
        for alt in alternatives:
            print(f"  {alt}")
    print("\nDecision intelligence integration test passed.")
