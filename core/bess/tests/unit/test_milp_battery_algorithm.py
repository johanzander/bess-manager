"""Core-model acceptance test for the #450 MILP pivot (build-phase slice 1).

Validates the generalized MILP core (modes, SOE recursion, self-throttle,
wear, terminal value) against the same #450 fixture the feasibility spike
used (docs/superpowers/specs/2026-08-03-milp-spike-450.py), which is itself
pinned against the exact-PWL reference implementation
(core/bess/dp_battery_algorithm.py) on this branch.

Scope so far: modes/SOE/self-throttle/wear/terminal-value core (slice 1),
negative-sell-price export-credit fix (slice 2), two-stage integer-rate
re-integerization (slice 3). Still missing: LP-dual shadow prices,
below-floor tolerance (#233), AC-cap clipping, per-period charge caps --
see docs/superpowers/specs/2026-08-03-milp-optimizer-pivot-450.md for the
full remaining build list.
"""

import json
import os

import numpy as np
import pytest

from core.bess.milp_battery_algorithm import solve_milp_schedule

_FIXTURE = os.path.join(
    os.path.dirname(__file__), "data", "regression_2026_08_02_043728.json"
)


def _load_fixture():
    with open(_FIXTURE) as f:
        return json.load(f)


def test_matches_spike_continuous_rate_optimum():
    """Continuous-rate MILP core must reproduce the feasibility spike's
    validated optimum (-6.0309207) and the #450 window (BYPASS then three
    charges, SOE 2.0 -> 3.222 -> 4.444 -> 5.666), not just solve to
    *a* feasible optimum."""
    sc = _load_fixture()

    result = solve_milp_schedule(
        buy_price=sc["buy_price"],
        sell_price=sc["sell_price"],
        home_consumption=sc["home_consumption"],
        solar_production=sc["solar_production"],
        battery=sc["battery"],
        dt=sc["period_duration_hours"],
    )

    assert result.status == "optimal"
    assert result.cost == pytest.approx(-6.0309207, abs=1e-4)

    # #450 window: index 35 (13:15) is IDLE (passive solar charge), not
    # STORE -- the cheaper window the DP must pick per the regression test.
    assert result.soe[35] == pytest.approx(2.0, abs=1e-3)
    assert result.soe[36] == pytest.approx(3.222, abs=1e-2)
    assert result.soe[37] == pytest.approx(4.444, abs=1e-2)
    assert result.soe[38] == pytest.approx(5.666, abs=1e-2)


def test_terminal_value_reduces_reported_cost():
    """A positive terminal_value_per_kwh must credit the final SOE above
    the floor -- sanity check on sign/direction before this term is relied
    on by later slices (shadow prices, production wiring)."""
    sc = _load_fixture()
    kwargs = {
        "buy_price": sc["buy_price"],
        "sell_price": sc["sell_price"],
        "home_consumption": sc["home_consumption"],
        "solar_production": sc["solar_production"],
        "battery": sc["battery"],
        "dt": sc["period_duration_hours"],
    }

    baseline = solve_milp_schedule(**kwargs)
    credited = solve_milp_schedule(**kwargs, terminal_value_per_kwh=1.0)

    assert credited.cost < baseline.cost


def test_negative_sell_price_export_is_not_free():
    """A period with forced solar-surplus export (battery at fixed zero
    capacity, so only BYPASS is feasible) at a NEGATIVE sell price must
    still cost sell_price * exported_kwh -- the self-throttle export-credit
    mechanism (#240) is a DISCHARGE-mode-only hardware quirk and must not
    let the model zero out the cost of export it cannot avoid in any other
    mode. Reproduces the pivot spec's point 3 (spike's buy>sell>0 shortcut
    is unsafe to reuse as-is)."""
    battery = {
        "initial_soe": 5.0,
        "min_soe_kwh": 5.0,
        "max_soe_kwh": 5.0,  # zero usable capacity: only BYPASS is feasible
        "efficiency_charge": 0.97,
        "efficiency_discharge": 0.95,
        "cycle_cost_per_kwh": 0.4,
        "max_charge_power_kw": 10,
        "max_discharge_power_kw": 10,
        "inverter_max_ac_power_kw": 11,
        "inverter_ac_power_margin": 0,
    }
    result = solve_milp_schedule(
        buy_price=[0.5, 0.5],
        sell_price=[-0.2, -0.2],
        home_consumption=[0.0, 0.0],
        solar_production=[2.0, 2.0],
        battery=battery,
        dt=0.25,
    )

    assert result.status == "optimal"
    assert (result.exp > 1.0).all()  # solar surplus forced out as export
    # credited_exp must track raw export exactly outside DISCHARGE mode --
    # no free credited_exp=0 loophole to dodge the negative-price cost.
    assert result.credited_exp == pytest.approx(result.exp, abs=1e-6)
    expected_cost = sum(
        -sell * exp for sell, exp in zip([-0.2, -0.2], result.exp, strict=True)
    )
    assert result.cost == pytest.approx(expected_cost, abs=1e-6)


def test_integer_rates_reintegerizes_to_hardware_executable_percents():
    """Continuous discharge rates aren't hardware-executable (#282: percent
    registers). integer_rates=True must fix the continuous solve's mode
    choice and re-solve with discharge_pct restricted to integers, without
    changing which window/mode sequence was chosen -- only the discharge
    rate resolution."""
    sc = _load_fixture()
    kwargs = {
        "buy_price": sc["buy_price"],
        "sell_price": sc["sell_price"],
        "home_consumption": sc["home_consumption"],
        "solar_production": sc["solar_production"],
        "battery": sc["battery"],
        "dt": sc["period_duration_hours"],
    }

    continuous = solve_milp_schedule(**kwargs)
    integer = solve_milp_schedule(**kwargs, integer_rates=True)

    assert integer.status == "optimal"
    non_integer_pct = integer.discharge_pct % 1
    assert np.all(
        np.minimum(non_integer_pct, 1 - non_integer_pct) < 1e-6
    ), integer.discharge_pct

    # Hardware-executable rates can only be worse (higher cost) than the
    # continuous relaxation's, per the pivot spec's feasibility-spike table
    # (~3 ore/day for this fixture) -- never better, and not wildly worse.
    assert integer.cost >= continuous.cost - 1e-6
    assert integer.cost < continuous.cost + 0.5

    # Same window: the SOE trajectory shouldn't shift to a different mode
    # sequence just because rates were re-integerized.
    assert integer.soe[35] == pytest.approx(continuous.soe[35], abs=1e-2)
    assert integer.soe[38] == pytest.approx(continuous.soe[38], abs=1e-2)
