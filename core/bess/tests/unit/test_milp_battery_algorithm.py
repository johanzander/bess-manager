"""Core-model acceptance test for the #450 MILP pivot (build-phase slice 1).

Validates the generalized MILP core (modes, SOE recursion, self-throttle,
wear, terminal value) against the same #450 fixture the feasibility spike
used (docs/superpowers/specs/2026-08-03-milp-spike-450.py), which is itself
pinned against the exact-PWL reference implementation
(core/bess/dp_battery_algorithm.py) on this branch.

Scope so far: modes/SOE/self-throttle/wear/terminal-value core (slice 1),
negative-sell-price export-credit fix (slice 2), two-stage integer-rate
re-integerization (slice 3), below-floor tolerance (slice 4, #233). Still
missing: LP-dual shadow prices, AC-cap clipping, per-period charge caps --
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
    rate resolution.

    Stage 2 must only fix the four hardware-mode binaries, not the
    auxiliary piecewise-linear branch-select binaries (store_active,
    s2b_active, idle_active, throttled) -- fixing those too was measured
    to cost ~3.8 ore/day extra on this fixture versus a full joint-integer
    solve (confirmed by running the joint solve directly: -5.998460244,
    matching the pivot spec's cited table value), because they must be
    free to re-adapt once rates are forced onto the integer lattice."""
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
    # continuous relaxation's, and should be close to the joint-integer
    # optimum (-5.998460244, verified by running the joint solve directly)
    # -- not just "not wildly worse" (that looser bound previously masked
    # a ~3.8 ore/day regression from over-fixing stage-2 binaries).
    assert integer.cost >= continuous.cost - 1e-6
    assert integer.cost == pytest.approx(-5.998460244, abs=1e-3)

    # Same window: the SOE trajectory shouldn't shift to a different mode
    # sequence just because rates were re-integerized.
    assert integer.soe[35] == pytest.approx(continuous.soe[35], abs=1e-2)
    assert integer.soe[38] == pytest.approx(continuous.soe[38], abs=1e-2)


def test_integer_rates_matches_pwl_reference_within_known_tolerance():
    """Cross-checks the MILP core's hardware-executable optimum against
    the exact-PWL DP reference implementation's own pinned cost for this
    fixture (core/bess/dp_battery_algorithm.py via
    optimize_battery_schedule, same fixture's expected_results.
    battery_solar_cost -- the value core/bess/tests/unit/test_scenarios.py
    validates the current production DP against). A small residual gap is
    expected and was flagged by the pivot spec as needing reconciling
    (point 6, "likely a small feasibility-rule mismatch, e.g. charge-
    candidate classification floor") -- this test pins that gap at its
    currently measured size so a regression (the gap silently widening)
    gets caught, without claiming the gap is fully explained yet."""
    sc = _load_fixture()
    result = solve_milp_schedule(
        buy_price=sc["buy_price"],
        sell_price=sc["sell_price"],
        home_consumption=sc["home_consumption"],
        solar_production=sc["solar_production"],
        battery=sc["battery"],
        dt=sc["period_duration_hours"],
        integer_rates=True,
    )

    pwl_reference_cost = sc["expected_results"]["battery_solar_cost"]
    assert result.cost == pytest.approx(pwl_reference_cost, abs=2e-4)


def test_below_floor_start_recovers_gradually_without_fabricated_jump():
    """initial_soe below min_soe_kwh is common after a restart or deep
    discharge (#233). The model must not require an instant jump to the
    floor -- it must recover as fast as physically reachable and stay
    feasible in the meantime. A charge rate too slow to reach the floor
    within the horizon must still solve (reaching as far as reachable),
    not report infeasible."""
    battery = {
        "initial_soe": 1.0,  # below min_soe_kwh
        "min_soe_kwh": 2.0,
        "max_soe_kwh": 20.0,
        "efficiency_charge": 0.97,
        "efficiency_discharge": 0.95,
        "cycle_cost_per_kwh": 0.4,
        "max_charge_power_kw": 1.0,  # slow: can't reach the floor in 4 periods
        "max_discharge_power_kw": 10,
        "inverter_max_ac_power_kw": 11,
        "inverter_ac_power_margin": 0,
    }
    result = solve_milp_schedule(
        buy_price=[0.5] * 4,
        sell_price=[0.2] * 4,
        home_consumption=[0.0] * 4,
        solar_production=[0.0] * 4,
        battery=battery,
        dt=0.25,
    )

    assert result.status == "optimal"
    store_rate_kwh = 1.0 * 0.25 * 0.97  # max_charge_power_kw * dt * eta_c
    expected_soe = 1.0 + store_rate_kwh * np.arange(5)
    assert result.soe == pytest.approx(expected_soe, abs=1e-6)
    assert result.soe[-1] < 2.0  # never fabricated a jump to the floor
