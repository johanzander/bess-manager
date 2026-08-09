"""Tests for optimize_battery_schedule's optional tie_diagnostics hook
(#450 synthetic coverage validation suite)."""

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.tests.helpers import _scenario_inputs
from core.bess.tests.unit.test_scenarios import load_test_scenario


def test_tie_diagnostics_populated_when_dict_passed():
    # A fixture that still near-ties at #512's finer grid (the original
    # choice here, #450's reproduction case regression_2026_08_02_043728,
    # stopped tying when the finer grid halved the snap noise -- see
    # test_issue_450_hybrid_resolution.py). Window measured at (14, 19).
    scenario = load_test_scenario("synthetic_consumption_high_no_solar")
    inputs = _scenario_inputs(scenario)
    diagnostics: dict = {}

    result = optimize_battery_schedule(
        buy_price=inputs["buy_price"],
        sell_price=inputs["sell_price"],
        home_consumption=scenario["home_consumption"],
        solar_production=scenario["solar_production"],
        initial_soe=scenario["battery"]["initial_soe"],
        battery_settings=inputs["battery_settings"],
        period_duration_hours=inputs["period_duration_hours"],
        terminal_value_per_kwh=scenario.get("terminal_value_per_kwh", 0.0),
        tie_diagnostics=diagnostics,
    )

    horizon = len(inputs["buy_price"])
    assert len(diagnostics["tie_margins"]) == horizon
    assert len(diagnostics["value_slopes"]) == horizon
    assert len(diagnostics["soe_trajectory"]) == horizon + 1
    # Known to flag exactly one window at the current grid resolution.
    assert len(diagnostics["windows"]) == 1
    assert result.reward_objective_cost is not None


def test_tie_diagnostics_none_by_default_is_a_no_op():
    scenario = load_test_scenario("synthetic_consumption_efficient")
    inputs = _scenario_inputs(scenario)

    # Must not raise when tie_diagnostics is omitted -- this is the default,
    # unmodified call shape every existing production caller uses.
    result = optimize_battery_schedule(
        buy_price=inputs["buy_price"],
        sell_price=inputs["sell_price"],
        home_consumption=scenario["home_consumption"],
        solar_production=scenario["solar_production"],
        initial_soe=scenario["battery"]["initial_soe"],
        battery_settings=inputs["battery_settings"],
        period_duration_hours=inputs["period_duration_hours"],
        terminal_value_per_kwh=scenario.get("terminal_value_per_kwh", 0.0),
    )
    assert result.economic_summary is not None
