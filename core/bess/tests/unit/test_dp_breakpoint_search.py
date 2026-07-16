"""Tests for #282 (Approach 1 of #276): replacing
`_best_action_at_continuous_state`'s per-period grid search with breakpoint
enumeration over the *hardware-achievable* action space, per
docs/superpowers/specs/2026-07-12-dp-continuous-action-reformulation-design.md.

These reproduce the exact (t, soe) cells the design doc's prototype measured
on `historical_2024_08_16_high_spread_no_solar`: at an off-grid SoE (not an
exact multiple of SOE_STEP_KWH -- what Step 2 actually encounters after real
state transitions), the coarse fixed-step POWER_STEP_KW grid search finds a
worse action than the best one really available. Postmortem (#282): the
first version of this fix searched the truly continuous action space and
found exact analytic breakpoints, which improved on the coarse grid but
broke plan-faithfulness (R == P) -- real hardware only executes discharge
at an integer percent of max_discharge_power_kw
(core/bess/simulation/inverter_simulator.py::_map_rates), so a genuinely
continuous "optimum" like -7.505 kW (out of 10 kW max) is not actually
achievable; execution silently rounds it to 75% (7.5 kW), diverging from
the plan. The fix enumerates the discrete hardware-percent grid directly,
which is both exact with respect to the *true* action space and always
executable exactly as planned.
"""

import pytest

from core.bess.dp_battery_algorithm import (
    _best_action_at_continuous_state,
    _charge_candidate,
    _discharge_candidates,
    _discretize_state_action_space,
    _interpolate_value,
    _run_dynamic_programming,
)
from core.bess.dp_constants import POWER_CLASSIFICATION_THRESHOLD_KW
from core.bess.tests.helpers import make_battery_settings
from core.bess.tests.unit.test_scenarios import build_scenario_inputs


def _prepare(scenario_name):
    scenario, battery_settings, buy_prices, sell_prices, dt = build_scenario_inputs(
        scenario_name
    )
    horizon = len(scenario["base_prices"])
    home_consumption = scenario["home_consumption"][:horizon]
    solar_production = scenario["solar_production"][:horizon]
    V = _run_dynamic_programming(
        horizon=horizon,
        buy_price=buy_prices,
        sell_price=sell_prices,
        home_consumption=home_consumption,
        battery_settings=battery_settings,
        dt=dt,
        solar_production=solar_production,
        initial_soe=battery_settings.min_soe_kwh + 5.0,
    )
    return (
        battery_settings,
        buy_prices,
        sell_prices,
        home_consumption,
        solar_production,
        V,
        dt,
    )


def _total_value(
    soe,
    t,
    V,
    battery_settings,
    dt,
    home_consumption,
    solar_production,
    buy_prices,
    sell_prices,
):
    _, power_levels = _discretize_state_action_space(battery_settings)
    _, best_next_soe, _, best_reward = _best_action_at_continuous_state(
        soe=soe,
        t=t,
        V_next=V[t + 1, :],
        power_levels=power_levels,
        home_consumption=home_consumption,
        battery_settings=battery_settings,
        dt=dt,
        solar_production=solar_production,
        buy_price=buy_prices,
        sell_price=sell_prices,
        cost_basis=0.0,
        max_charge_power_per_period=None,
    )
    return best_reward + _interpolate_value(
        V[t + 1, :], best_next_soe, battery_settings
    )


def test_off_grid_discharge_closes_interpolation_gap_case_1():
    """t=10, soe=13.083 kWh on the high-spread fixture: the design doc's
    dense scan found a true (unconstrained-continuous) optimum of
    -118.641847, but the production grid search (POWER_STEP_KW=0.2) only
    found -118.675085 -- a 0.033 SEK single-period gap from missing the
    true breakpoint between grid points. Here the hardware-percent grid
    (1% of max_discharge_power_kw=6.0, i.e. 0.06 kW steps) is fine enough
    to recover the dense-scan value almost exactly, unlike case_2 where the
    availability constraint caps the achievable rate below what a finer
    grid could otherwise reach."""
    (
        battery_settings,
        buy_prices,
        sell_prices,
        home_consumption,
        solar_production,
        V,
        dt,
    ) = _prepare("historical_2024_08_16_high_spread_no_solar")
    t = 10
    soe = battery_settings.min_soe_kwh + 10.083
    value = _total_value(
        soe,
        t,
        V,
        battery_settings,
        dt,
        home_consumption,
        solar_production,
        buy_prices,
        sell_prices,
    )
    assert value >= -118.65, (
        f"expected breakpoint search to recover the true optimum "
        f"(~-118.641847), got {value} -- still stuck near the old grid-search "
        f"value (-118.675085)"
    )


def test_off_grid_discharge_matches_hardware_constrained_optimum_case_2():
    """t=21, soe=6.029 kWh: the design doc's original dense scan found a
    continuous "optimum" of -37.762309 at power=-3.0287 kW, but that value
    is not actually achievable -- it needs a 50.478% discharge rate, and
    real hardware only accepts integer percent (#282 postmortem). Given the
    true action space (integer percent of max_discharge_power_kw=6.0,
    capped by the 3.029 kWh available at this off-grid SoE), the best
    reachable rate is exactly 50% (3.0 kW), which is what the old coarse
    POWER_STEP_KW=0.2 grid already happened to find here too -- so this
    specific cell has no headroom to improve on, and the breakpoint search
    must not regress it while fixing other cells (see case_1) that do."""
    (
        battery_settings,
        buy_prices,
        sell_prices,
        home_consumption,
        solar_production,
        V,
        dt,
    ) = _prepare("historical_2024_08_16_high_spread_no_solar")
    t = 21
    soe = battery_settings.min_soe_kwh + 3.029
    value = _total_value(
        soe,
        t,
        V,
        battery_settings,
        dt,
        home_consumption,
        solar_production,
        buy_prices,
        sell_prices,
    )
    assert value == pytest.approx(-37.863850, abs=1e-6), (
        f"expected the hardware-constrained optimum (-37.863850, the best "
        f"achievable integer-percent rate), got {value}"
    )


def test_discharge_candidates_are_hardware_representable():
    """Real hardware executes discharge as an integer percent (0-100) of
    max_discharge_power_kw (core/bess/simulation/inverter_simulator.py's
    _map_rates) -- it cannot apply an arbitrary continuous kW value.
    Postmortem (#282): the first breakpoint-enumeration implementation
    returned exact analytic breakpoints like -7.504999999999998 kW (out of
    a 10 kW max), which _map_rates rounds to 75% -> 7.5 kW -- a planned
    action the hardware silently can't reproduce, breaking R == P on
    several real-world scenarios. Every candidate this function returns
    must therefore already be an exact multiple of max_discharge_power_kw
    / 100, so planning and execution can never diverge on this account."""
    settings = make_battery_settings(max_discharge_power_kw=10.0)
    # soe/home_consumption/solar chosen so an unconstrained analytic
    # breakpoint (V-grid crossing) would fall strictly between two
    # percent-of-max-rate steps.
    candidates = _discharge_candidates(
        soe=15.0,
        battery_settings=settings,
        dt=1.0,
        home_consumption=1.234,
        solar_production=0.0,
    )
    assert candidates, "expected at least one discharge candidate"
    step = settings.max_discharge_power_kw / 100
    for p in candidates:
        pct = p / step
        assert pct == pytest.approx(round(pct), abs=1e-6), (
            f"candidate {p} kW is not an exact multiple of the hardware's "
            f"{step} kW (1%) rate step -- not executable as planned"
        )


def test_discharge_candidates_exceed_classification_threshold():
    """Second #282 postmortem: decision_intelligence.classify_strategic_intent
    treats any discharge magnitude at or below POWER_CLASSIFICATION_THRESHOLD_KW
    (0.1 kW, derived from POWER_STEP_KW) as noise and falls through to a
    different classification branch -- previously safe by construction, since
    the old fixed POWER_STEP_KW=0.2 grid's smallest nonzero action (0.2) always
    exceeded that threshold. The hardware-percent grid is battery-adaptive,
    though: for any max_discharge_power_kw <= 10 kW, 1% of it is <= 0.1 kW,
    landing at or below the threshold. A DP-chosen discharge there gets
    misclassified at execution time (falls through to LOAD_SUPPORT, which
    self-throttles to the real home deficit -- 0 during solar surplus),
    causing real hardware to discharge nothing when the plan assumed export
    revenue: a confirmed R != P divergence on several real-world scenarios
    with 6 kW batteries. Every non-zero candidate must stay strictly above
    the classification threshold, not just above zero."""
    settings = make_battery_settings(max_discharge_power_kw=6.0)
    candidates = _discharge_candidates(
        soe=15.0,
        battery_settings=settings,
        dt=1.0,
        home_consumption=1.234,
        solar_production=0.0,
    )
    assert candidates, "expected at least one discharge candidate"
    assert all(c > POWER_CLASSIFICATION_THRESHOLD_KW for c in candidates), (
        f"candidates {candidates} include a magnitude at or below the "
        f"{POWER_CLASSIFICATION_THRESHOLD_KW} kW classification threshold -- "
        f"would be misclassified (not real discharge) at execution time"
    )


def test_charge_candidate_none_when_below_classification_threshold():
    """Same #282 threshold issue as discharge, on the charge side: when only
    a sliver of room remains near a full battery, `max_charge_power` can
    fall at or below POWER_CLASSIFICATION_THRESHOLD_KW (0.1 kW) -- picking
    it as the STORE candidate anyway would misclassify a genuine (if tiny)
    charge as noise at execution time. `_charge_candidate` must return
    `None` in that case (treat as no charge available) instead of a
    candidate the classifier can't recognize."""
    settings = make_battery_settings(max_charge_power_kw=10.0, efficiency_charge=1.0)
    # available_capacity = max_soe_kwh - soe = 0.05 kWh -> max_charge_power
    # = 0.05 kW at dt=1.0, below the 0.1 kW threshold.
    soe = settings.max_soe_kwh - 0.05
    candidate = _charge_candidate(
        soe=soe, battery_settings=settings, dt=1.0, period_max_charge=None
    )
    assert (
        candidate is None
    ), f"expected None (room below classification threshold), got {candidate}"


def test_charge_candidate_present_when_above_classification_threshold():
    """Sanity check for the fix above: charge candidates aren't broken --
    plenty of room still returns a valid candidate."""
    settings = make_battery_settings(max_charge_power_kw=10.0, efficiency_charge=1.0)
    candidate = _charge_candidate(
        soe=settings.min_soe_kwh,
        battery_settings=settings,
        dt=1.0,
        period_max_charge=None,
    )
    assert candidate is not None
    assert candidate > 0.0


def test_compute_reward_self_throttle_threshold_is_parameterized():
    """#320: a platform with no self-throttle (self_throttle_export_threshold_kwh=0)
    must credit export revenue for the smallest overshoot; the default (0.01)
    must not."""
    from core.bess.dp_battery_algorithm import _compute_reward

    settings = make_battery_settings(max_discharge_power_kw=5.0)
    # power chosen so grid_exported lands strictly between 0 and 0.01 kWh
    # at dt=1.0h: home_consumption=1.0, discharge=1.005 kW -> export=0.005 kWh
    reward_default, _ = _compute_reward(
        power=-1.005,
        soe=15.0,
        next_soe=15.0 - 1.005 * 1.0 / settings.efficiency_discharge,
        period=0,
        home_consumption=1.0,
        battery_settings=settings,
        dt=1.0,
        buy_price=[0.30],
        sell_price=[0.10],
        solar_production=0.0,
        cost_basis=0.0,
    )
    reward_no_throttle, _ = _compute_reward(
        power=-1.005,
        soe=15.0,
        next_soe=15.0 - 1.005 * 1.0 / settings.efficiency_discharge,
        period=0,
        home_consumption=1.0,
        battery_settings=settings,
        dt=1.0,
        buy_price=[0.30],
        sell_price=[0.10],
        solar_production=0.0,
        cost_basis=0.0,
        self_throttle_export_threshold_kwh=0.0,
    )
    # no_throttle credits the 0.005 kWh export at sell_price=0.10; default
    # zeroes it out (self-throttled), so no_throttle's reward is higher.
    assert reward_no_throttle > reward_default
    assert reward_no_throttle == pytest.approx(reward_default + 0.005 * 0.10, abs=1e-9)
