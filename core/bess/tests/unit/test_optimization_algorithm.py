"""
Test module for core battery optimization algorithm functions (DP-based, canonical for BESS).

This module contains the fundamental unit tests for the battery optimization algorithm,
using the unified optimize_battery_schedule API function. These tests verify that the
core functions produce outputs with the expected structure and reasonable values,
but don't test specific optimization results.
"""

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.models import EconomicSummary, PeriodData
from core.bess.settings import BatterySettings

# Create a BatterySettings instance for testing
battery_settings = BatterySettings()


def test_battery_simulation_results(
    sample_price_data, sample_consumption_data, sample_solar_data
):
    """
    Test that battery optimization produces the expected results structure with new APIs.
    """
    buy_price = sample_price_data["buy_price"]
    sell_price = sample_price_data["sell_price"]
    home_consumption = sample_consumption_data
    solar_production = sample_solar_data
    initial_soc = battery_settings.reserved_capacity

    results = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=initial_soc,
        battery_settings=battery_settings,
    )

    # Test new OptimizationResult structure
    assert hasattr(results, "period_data")
    assert hasattr(results, "economic_summary")
    assert hasattr(results, "input_data")

    hourly_data_list = results.period_data
    economic_summary = results.economic_summary

    # Test that we have the right structure
    assert isinstance(hourly_data_list, list)
    assert len(hourly_data_list) == 24  # Should have 24 hours
    assert isinstance(
        economic_summary, EconomicSummary
    )  # Should be EconomicSummary dataclass

    # Test that each hourly data object is PeriodData with proper structure
    for hour_data in hourly_data_list:
        assert isinstance(hour_data, PeriodData)

        # Test core properties (these use the property accessors)
        assert hasattr(hour_data, "period")
        assert 0 <= hour_data.period <= 23

        # Test energy data access - using single source of truth pattern
        assert hasattr(hour_data.energy, "solar_production")
        assert hasattr(hour_data.energy, "home_consumption")
        assert hasattr(hour_data.energy, "grid_imported")
        assert hasattr(hour_data.energy, "grid_exported")
        assert hasattr(hour_data.energy, "battery_charged")
        assert hasattr(hour_data.energy, "battery_discharged")
        assert hasattr(hour_data.energy, "battery_soe_start")
        assert hasattr(hour_data.energy, "battery_soe_end")

        # Test economic data access - using single source of truth pattern
        assert hasattr(hour_data.economic, "buy_price")
        assert hasattr(hour_data.economic, "sell_price")
        assert hasattr(hour_data.economic, "hourly_cost")
        assert hasattr(hour_data.economic, "hourly_savings")

        # Test strategy data access - using single source of truth pattern
        assert hasattr(hour_data.decision, "strategic_intent")
        assert hasattr(hour_data.decision, "battery_action")

        # Test that data source is set correctly
        assert hour_data.data_source == "predicted"

        # Test that all components are present
        assert hour_data.energy is not None
        assert hour_data.economic is not None
        assert hour_data.decision is not None

    # Test economic summary has expected fields (EconomicSummary dataclass)
    assert hasattr(economic_summary, "grid_only_cost")
    assert hasattr(economic_summary, "battery_solar_cost")
    assert hasattr(economic_summary, "grid_to_battery_solar_savings")
    assert hasattr(economic_summary, "grid_to_battery_solar_savings_pct")
    assert hasattr(economic_summary, "total_charged")
    assert hasattr(economic_summary, "total_discharged")

    # Test economic calculations with proper floating-point tolerance
    assert economic_summary.grid_only_cost >= 0

    # Use floating-point tolerance for accumulated vs calculated values
    expected_savings = (
        economic_summary.grid_only_cost - economic_summary.battery_solar_cost
    )
    actual_savings = economic_summary.grid_to_battery_solar_savings

    # Allow for small floating-point precision differences from 24 hours of calculations
    tolerance = 1e-10  # Very small tolerance for precision differences
    assert (
        abs(actual_savings - expected_savings) < tolerance
    ), f"Savings calculation mismatch: {actual_savings} vs {expected_savings} (diff: {abs(actual_savings - expected_savings)})"

    # Test that savings percentage is calculated correctly
    if economic_summary.grid_only_cost > 0:
        expected_pct = (
            economic_summary.grid_to_battery_solar_savings
            / economic_summary.grid_only_cost
        ) * 100
        assert (
            abs(economic_summary.grid_to_battery_solar_savings_pct - expected_pct)
            < 0.01
        )


def test_battery_constraints_respected():
    """
    Test that the battery simulation respects physical constraints using new APIs.
    """
    buy_price = [0.5] * 24
    sell_price = [0.3] * 24
    home_consumption = [2.0] * 24
    solar_production = [0.0] * 24
    initial_soc = battery_settings.reserved_capacity

    results = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=initial_soc,
        battery_settings=battery_settings,
    )

    # Test constraints using new PeriodData structure
    for hour_data in results.period_data:
        # SOE is already in kWh, no conversion needed
        soe_start_kwh = hour_data.energy.battery_soe_start
        soe_end_kwh = hour_data.energy.battery_soe_end

        assert (
            battery_settings.min_soe_kwh
            <= soe_start_kwh
            <= battery_settings.max_soe_kwh
        )
        assert (
            battery_settings.min_soe_kwh <= soe_end_kwh <= battery_settings.max_soe_kwh
        )

        # Battery action should respect power limits
        if hour_data.decision.battery_action:
            assert abs(hour_data.decision.battery_action) <= max(
                battery_settings.max_charge_power_kw,
                battery_settings.max_discharge_power_kw,
            )

        # Energy balance should be maintained (approximately)
        energy_in = hour_data.energy.solar_production + hour_data.energy.grid_imported
        energy_out = hour_data.energy.home_consumption + hour_data.energy.grid_exported
        battery_net = (
            hour_data.energy.battery_charged - hour_data.energy.battery_discharged
        )

        # Energy balance: energy_in = energy_out + battery_net (within tolerance for efficiency losses)
        balance_error = abs(energy_in - energy_out - battery_net)
        assert balance_error < 0.1, f"Energy balance error too large: {balance_error}"


def SKIP_test_strategic_intent_assignment():  # TODO: Improve test to validate correct strategic decisions, not just presence of intents
    """
    Test that strategic intents are assigned correctly using new APIs.
    """
    # Create scenario with high price spread to encourage battery usage
    buy_price = [
        0.3,
        0.3,
        0.3,
        0.3,
        0.3,
        0.3,  # Night - cheap
        0.8,
        0.8,
        0.8,
        0.8,
        0.8,
        0.8,  # Morning - expensive
        0.4,
        0.4,
        0.4,
        0.4,
        0.4,
        0.4,  # Afternoon - medium
        0.9,
        0.9,
        0.9,
        0.9,
        0.3,
        0.3,
    ]  # Evening peak then night

    sell_price = [p * 0.7 for p in buy_price]  # Sell price is 70% of buy price
    home_consumption = [1.5] * 24  # Constant consumption
    solar_production = (
        [0.0] * 6 + [1.0, 2.0, 3.0, 4.0, 3.0, 2.0] + [1.0] * 6 + [0.0] * 6
    )  # Solar during day

    results = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=battery_settings.min_soe_kwh,
        battery_settings=battery_settings,
    )

    # Check that strategic intents are assigned
    intents = [hour_data.decision.strategic_intent for hour_data in results.period_data]

    # Should have some strategic decisions (not all IDLE)
    assert len(set(intents)) > 1, "Should have multiple strategic intents"

    # Verify valid strategic intents only
    valid_intents = {
        "IDLE",
        "GRID_CHARGING",
        "SOLAR_STORAGE",
        "LOAD_SUPPORT",
        "EXPORT_ARBITRAGE",
    }
    for intent in intents:
        assert intent in valid_intents, f"Invalid strategic intent: {intent}"


def test_energy_data_structure():
    """
    Test that energy data structure is properly populated in PeriodData.
    """
    buy_price = [0.5] * 24
    sell_price = [0.3] * 24
    home_consumption = [2.0] * 24
    solar_production = [1.0] * 24
    initial_soc = battery_settings.reserved_capacity

    results = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=initial_soc,
        battery_settings=battery_settings,
    )

    for hour_data in results.period_data:
        # Test that energy component exists and has data
        assert hour_data.energy is not None
        assert hour_data.energy.solar_production >= 0
        assert hour_data.energy.home_consumption >= 0
        assert hour_data.energy.grid_imported >= 0
        assert hour_data.energy.grid_exported >= 0

        # Test detailed flows are calculated
        assert hour_data.energy.solar_to_home >= 0
        assert hour_data.energy.solar_to_battery >= 0
        assert hour_data.energy.solar_to_grid >= 0
        assert hour_data.energy.grid_to_home >= 0
        assert hour_data.energy.grid_to_battery >= 0
        assert hour_data.energy.battery_to_home >= 0
        assert hour_data.energy.battery_to_grid >= 0


def test_economic_data_structure():
    """
    Test that economic data structure is properly populated in PeriodData.
    """
    buy_price = [0.5] * 24
    sell_price = [0.3] * 24
    home_consumption = [2.0] * 24
    solar_production = [1.0] * 24
    initial_soc = battery_settings.reserved_capacity

    results = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=initial_soc,
        battery_settings=battery_settings,
    )

    for hour_data in results.period_data:
        # Test that economic component exists and has data
        assert hour_data.economic is not None
        assert hour_data.economic.buy_price >= 0
        assert hour_data.economic.sell_price >= 0
        assert hour_data.economic.grid_only_cost >= 0  # Grid-only baseline cost
        # Solar-only cost can be negative when exporting solar (earning money from export)
        # No assertion needed for solar_only_cost as it can be positive, negative, or zero
        assert hour_data.economic.battery_cycle_cost >= 0

        # Test that hourly savings is calculated correctly vs solar-only baseline
        expected_savings = (
            hour_data.economic.solar_only_cost - hour_data.economic.hourly_cost
        )
        assert abs(hour_data.economic.hourly_savings - expected_savings) < 0.01


def test_defers_charging_to_cheaper_overnight_window():
    """
    Regression test for 2026-03-24 bug: optimizer charged at 1.20 SEK tonight
    instead of deferring to 1.13 SEK tomorrow overnight.

    Root cause: V[t, max_soe_state] in the backward pass was not propagating
    future value when no valid action was found (discharge unprofitable at low
    overnight sell prices, charge impossible when battery is full). This caused
    the export profit at tomorrow evening to be invisible from tonight's charging
    decision, making "charge now at 1.20" look equivalent to "charge later at 1.13".

    The optimizer should always prefer the cheapest available charging window when
    the battery can reach full capacity before the discharge opportunity regardless
    of when the charging happens.
    """
    # Battery settings matching the 2026-03-24 debug log
    settings = BatterySettings(
        total_capacity=30.0,
        min_soc=15.0,  # 4.5 kWh min — gives state 240 = 28.5 kWh = max
        max_soc=95.0,  # 28.5 kWh max
        max_charge_power_kw=14.7,
        max_discharge_power_kw=14.7,
        efficiency_charge=0.97,
        efficiency_discharge=0.95,
        cycle_cost_per_kwh=0.40,
    )

    # 104-period horizon (15-min periods) starting at 22:00 tonight
    # Periods 0-7   (22:00-23:45 tonight):      buy=1.20 — more expensive
    # Periods 8-27  (00:00-04:45 tomorrow):      buy=1.13 — cheaper overnight window
    # Periods 28-76 (05:00-17:00 tomorrow):      buy=1.20 — normal daytime
    # Periods 77-83 (17:15-18:45 tomorrow):      buy=2.10 — expensive; discharge avoids this cost
    # Periods 84-103 (19:00-23:45 tomorrow):     buy=1.20 — normal evening
    buy_price = (
        [1.20] * 8  # tonight
        + [1.13] * 20  # cheap overnight
        + [1.20] * 49  # daytime
        + [2.10] * 7  # discharge window
        + [1.20] * 20  # evening
    )
    sell_price = [0.71] * 8 + [0.65] * 20 + [0.71] * 49 + [1.44] * 7 + [0.71] * 20
    home_consumption = [0.8] * 104  # 3.2 kWh/hour, no solar
    solar_production = [0.0] * 104

    results = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=10.8,  # 36% SOC at 22:00 (from debug log)
        initial_cost_basis=1.644,  # from debug log
        battery_settings=settings,
        period_duration_hours=0.25,
    )

    # Before the fix the optimizer filled the battery to max SOE during the
    # expensive tonight window (1.20 SEK) because V[t, max_soe_state] did not
    # propagate future export value — making "charge now" look equivalent to
    # "charge later cheaper" plus extra idle costs.  After the fix the export
    # profit is correctly visible and the optimizer does NOT over-charge during
    # the expensive window.
    max_soe_during_tonight = max(
        p.energy.battery_soe_end for p in results.period_data[:8]
    )
    assert max_soe_during_tonight < battery_settings.max_soe_kwh, (
        f"Battery reached max SOE ({max_soe_during_tonight:.1f} kWh) during expensive "
        f"tonight window (buy=1.20 SEK). Optimizer should not over-charge when a cheaper "
        f"overnight window (1.13 SEK) is available — bug: V[t, max_soe_state] was not "
        f"propagating future export value in the backward pass."
    )

    # Export arbitrage must still be executed at the high-price window
    export_intents = [p.decision.strategic_intent for p in results.period_data[77:84]]
    assert any(i == "EXPORT_ARBITRAGE" for i in export_intents), (
        f"Expected EXPORT_ARBITRAGE at periods 77-83 (buy=2.10 SEK). "
        f"Got: {export_intents}"
    )


def test_strategy_data_structure():
    """
    Test that strategy data structure is properly populated in PeriodData.
    """
    buy_price = [0.5] * 24
    sell_price = [0.3] * 24
    home_consumption = [2.0] * 24
    solar_production = [1.0] * 24
    initial_soc = battery_settings.reserved_capacity

    results = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=initial_soc,
        battery_settings=battery_settings,
    )

    for hour_data in results.period_data:
        # Test that strategy component exists and has data
        assert hour_data.decision is not None
        assert hour_data.decision.strategic_intent is not None
        assert hour_data.decision.battery_action is not None
        assert hour_data.decision.cost_basis >= 0
