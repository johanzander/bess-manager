import copy

import pytest

from core.bess.tests.synthetic.perturb_scenario import (
    PerturbationParams,
    perturb_scenario,
)
from core.bess.tests.unit.test_scenarios import load_test_scenario


def _base():
    return load_test_scenario("regression_2026_07_25_090230")


def test_same_seed_produces_identical_output():
    base = _base()
    params = PerturbationParams(
        price_level_multiplier=1.5, volatility_jitter=0.1, solar_scale=0.5
    )
    a = perturb_scenario(base, seed=42, params=params)
    b = perturb_scenario(base, seed=42, params=params)
    assert a == b


def test_different_seed_produces_different_jitter():
    base = _base()
    params = PerturbationParams(volatility_jitter=0.2)
    a = perturb_scenario(base, seed=1, params=params)
    b = perturb_scenario(base, seed=2, params=params)
    assert a["buy_price"] != b["buy_price"]


def test_price_level_multiplier_scales_only_prices():
    base = _base()
    params = PerturbationParams(price_level_multiplier=2.0)
    result = perturb_scenario(base, seed=0, params=params)
    for orig, scaled in zip(base["buy_price"], result["buy_price"], strict=False):
        assert scaled == pytest.approx(orig * 2.0)
    for orig, scaled in zip(base["sell_price"], result["sell_price"], strict=False):
        assert scaled == pytest.approx(orig * 2.0)
    assert result["home_consumption"] == base["home_consumption"]
    assert result["solar_production"] == base["solar_production"]


def test_solar_scale_scales_only_solar():
    base = _base()
    params = PerturbationParams(solar_scale=0.0)
    result = perturb_scenario(base, seed=0, params=params)
    assert all(v == 0.0 for v in result["solar_production"])
    assert result["buy_price"] == base["buy_price"]
    assert result["home_consumption"] == base["home_consumption"]


def test_battery_override_replaces_capacity_and_clamps_initial_soe():
    base = _base()
    # base fixture's initial_soe is within its own capacity; overriding to a
    # much smaller battery must not leave initial_soe above the new max.
    params = PerturbationParams(battery_capacity_override_kwh=1.0)
    result = perturb_scenario(base, seed=0, params=params)
    assert result["battery"]["max_soe_kwh"] == pytest.approx(1.0)
    assert result["battery"]["initial_soe"] <= result["battery"]["max_soe_kwh"]


def test_invalid_battery_override_raises():
    base = _base()
    params = PerturbationParams(battery_capacity_override_kwh=-1.0)
    with pytest.raises(ValueError, match="battery_capacity_override_kwh"):
        perturb_scenario(base, seed=0, params=params)


def test_does_not_mutate_input():
    base = _base()
    original = copy.deepcopy(base)
    perturb_scenario(
        base, seed=0, params=PerturbationParams(price_level_multiplier=3.0)
    )
    assert base == original
