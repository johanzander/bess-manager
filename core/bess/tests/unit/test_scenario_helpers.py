"""Tests for core.bess.tests.helpers._scenario_inputs's price/battery
derivation -- covering the buy_price/sell_price direct-input path and
initial_cost_basis pass-through added for debug-log-derived regression
fixtures, and confirming spot_multiplier/export_spot_multiplier support
(previously only present in test_scenarios.py's separate, now-removed
duplicate of this logic) still works after unification. See
docs/superpowers/specs/2026-07-25-debug-log-regression-fixtures-design.md.
"""

import pytest

from core.bess.tests.helpers import _scenario_inputs


def _battery(**overrides):
    battery = {
        "max_soe_kwh": 15.0,
        "min_soe_kwh": 1.8,
        "max_charge_power_kw": 5.0,
        "max_discharge_power_kw": 5.0,
        "efficiency_charge": 0.97,
        "efficiency_discharge": 0.95,
        "cycle_cost_per_kwh": 0.035,
        "initial_soe": 1.65,
    }
    battery.update(overrides)
    return battery


def test_direct_buy_sell_price_used_verbatim_without_price_manager():
    """A scenario with buy_price/sell_price keys must use them exactly as
    given, bypassing PriceManager/base_prices entirely -- this is what lets
    a fixture carry the exact final prices an optimizer run actually saw."""
    scenario = {
        "buy_price": [0.5, 0.6],
        "sell_price": [-0.01, -0.02],
        "home_consumption": [0.2, 0.2],
        "solar_production": [0.5, 0.5],
        "battery": _battery(),
    }

    inputs = _scenario_inputs(scenario)

    assert inputs["buy_price"] == [0.5, 0.6]
    assert inputs["sell_price"] == [-0.01, -0.02]


def test_base_prices_path_unaffected_when_no_direct_prices_given():
    """Existing base_prices + PriceManager derivation must be unchanged for
    scenarios that don't set buy_price/sell_price."""
    scenario = {
        "base_prices": [0.3, 0.3],
        "home_consumption": [0.2, 0.2],
        "solar_production": [0.0, 0.0],
        "battery": _battery(),
    }

    inputs = _scenario_inputs(scenario)

    assert inputs["buy_price"][0] > scenario["base_prices"][0]  # markup applied
    assert len(inputs["buy_price"]) == 2


def test_initial_cost_basis_passed_through_when_present():
    scenario = {
        "buy_price": [0.5],
        "sell_price": [0.1],
        "home_consumption": [0.2],
        "solar_production": [0.0],
        "battery": _battery(initial_cost_basis=0.035),
    }

    inputs = _scenario_inputs(scenario)

    assert inputs["initial_cost_basis"] == 0.035


def test_initial_cost_basis_defaults_to_none_when_absent():
    scenario = {
        "buy_price": [0.5],
        "sell_price": [0.1],
        "home_consumption": [0.2],
        "solar_production": [0.0],
        "battery": _battery(),
    }

    inputs = _scenario_inputs(scenario)

    assert inputs["initial_cost_basis"] is None


def test_spot_multiplier_still_applied_via_base_prices_path():
    """Regression: before this change, helpers._scenario_inputs silently
    dropped price_data's spot_multiplier/export_spot_multiplier -- only
    test_scenarios.py's separate build_scenario_inputs applied them.
    core/bess/tests/unit/data/realworld_2026_07_13_155212.json relies on
    spot_multiplier. Task 2 makes test_scenarios.py delegate to this same
    function, so this must hold here too."""
    base_price_data = {
        "markup_rate": 0.0,
        "vat_multiplier": 1.0,
        "additional_costs": 0.0,
        "tax_reduction": 0.0,
    }
    scenario_without = {
        "base_prices": [1.0],
        "home_consumption": [0.2],
        "solar_production": [0.0],
        "battery": _battery(),
        "price_data": base_price_data,
    }
    scenario_with = {
        **scenario_without,
        "price_data": {**base_price_data, "spot_multiplier": 2.0},
    }

    buy_without = _scenario_inputs(scenario_without)["buy_price"][0]
    buy_with = _scenario_inputs(scenario_with)["buy_price"][0]

    assert buy_with == pytest.approx(buy_without * 2.0)
