"""Standing pins between the vectorized backward induction and the selector.

P1 (`docs/agents/optimizer-architecture.md`) lets the grid DP's backward
pass keep its own numpy evaluator for speed -- routing it through
`select_action` measured 256x slower (0.11 s -> ~29 s per solve on
`regression_2026_08_08_143843`) and would additionally change behavior,
since that pass deliberately estimates V over a coarser power lattice than
the replay chooses actions on. The price of that exemption is this file: a
vectorized evaluator that drifts from the selector's is #236 reproduced,
and drift is silent -- V is never compared against anything downstream.

Two things are pinned here, matching the two ways the passes can diverge:

1. The evaluators must agree bit-for-bit on the physics
   (`_state_transition_grid`/`_compute_reward_grid` vs the scalar
   `_state_transition`/`_compute_reward` the selector evaluates candidates
   with).
2. The backward pass must value every *candidate type* the selector can
   choose. The lattice itself legitimately differs; a candidate the
   selector can pick but V has never heard of does not -- that is exactly
   how a plan ends up ranked by a value function that does not know the
   plan exists.
"""

import numpy as np
import pytest

from core.bess.action_selector import _residual_cover_p
from core.bess.dp_battery_algorithm import (
    _compute_reward,
    _compute_reward_grid,
    _effective_ac_cap_kwh,
    _run_dynamic_programming,
    _state_transition,
    _state_transition_grid,
)
from core.bess.dp_constants import SOE_STEP_KWH
from core.bess.execution_model import DEFAULT_CAPABILITIES
from core.bess.tests.helpers import make_battery_settings

DT = 0.25


@pytest.mark.parametrize("solar", [0.0, 0.4, 2.5])
@pytest.mark.parametrize("home", [0.05, 0.5])
@pytest.mark.parametrize("import_cap_kwh", [None, 0.6])
def test_vectorized_evaluator_matches_the_selectors_scalar_physics(
    solar, home, import_cap_kwh
):
    """Both passes must compute the same next_soe, reward and grid import for
    the same action -- exactly, not approximately.

    The scalar functions are what `select_action` prices candidates with;
    the `_grid` twins are what the backward pass estimates V with. Any gap
    means the DP optimizes one plan and the replay executes another.
    """
    settings = make_battery_settings(inverter_max_ac_power_kw=5.0)
    soes = np.arange(settings.min_soe_kwh, settings.max_soe_kwh, 1.3)
    powers = np.array([-10.0, -3.0, -0.2, 0.0, 0.1, 4.0, 10.0])

    grid_next_soe = _state_transition_grid(
        soes.reshape(-1, 1),
        powers.reshape(1, -1),
        settings,
        DT,
        solar_production=solar,
        home_consumption=home,
        ac_cap_kwh=_effective_ac_cap_kwh(settings, DT),
        import_cap_kwh=import_cap_kwh,
    )
    grid_reward, grid_imported = _compute_reward_grid(
        powers.reshape(1, -1),
        soes.reshape(-1, 1),
        grid_next_soe,
        home_consumption=home,
        battery_settings=settings,
        dt=DT,
        current_buy_price=1.5,
        current_sell_price=0.4,
        solar_production=solar,
        import_cap_kwh=import_cap_kwh,
    )

    for i, soe in enumerate(soes):
        for j, power in enumerate(powers):
            scalar_next_soe = _state_transition(
                float(soe),
                float(power),
                settings,
                DT,
                solar_production=solar,
                home_consumption=home,
                ac_cap_kwh=_effective_ac_cap_kwh(settings, DT),
                import_cap_kwh=import_cap_kwh,
            )
            assert grid_next_soe[i, j] == scalar_next_soe, (
                f"next_soe drift at soe={soe}, power={power}: "
                f"{grid_next_soe[i, j]} != {scalar_next_soe}"
            )
            scalar_reward, _basis, scalar_flows = _compute_reward(
                power=float(power),
                soe=float(soe),
                next_soe=scalar_next_soe,
                period=0,
                home_consumption=home,
                battery_settings=settings,
                dt=DT,
                solar_production=solar,
                buy_price=[1.5],
                sell_price=[0.4],
                cost_basis=0.4,
                import_cap_kwh=import_cap_kwh,
            )
            assert grid_reward[i, j] == scalar_reward, (
                f"reward drift at soe={soe}, power={power}: "
                f"{grid_reward[i, j]} != {scalar_reward}"
            )
            assert grid_imported[i, j] == scalar_flows.grid_imported


def _single_period_value(
    settings, home, solar, buy, sell, initial_soe, soe_of_interest
):
    """V[0] from a one-period backward induction, at one grid state.

    With `terminal_value_per_kwh = 0` the terminal row is all zeros, so
    V[0][i] is exactly `max(reward)` over the candidates the pass considers
    -- no continuation term, no grid snapping of the lookup. That makes the
    comparison against a scalar `_compute_reward` exact rather than
    tolerance-bounded.
    """
    V = _run_dynamic_programming(
        horizon=1,
        buy_price=[buy],
        sell_price=[sell],
        home_consumption=[home],
        battery_settings=settings,
        dt=DT,
        solar_production=[solar],
        initial_soe=initial_soe,
    )
    index = round((soe_of_interest - settings.min_soe_kwh) / SOE_STEP_KWH)
    return V[0, index]


def test_backward_pass_values_the_residual_cover_candidate():
    """#466's off-lattice residual-cover action must be priced by V too.

    The scenario is built so that covering the residual is the *uniquely*
    best action: net load (0.02 kWh over 15 min = 0.08 kW) sits below the
    smallest lattice discharge, and the sell price is negative, so every
    coarse-lattice discharge that overshoots it pays to export the
    overshoot. If the backward pass ever stops carrying the cover column,
    V collapses to IDLE's value -- importing the residual -- and this fails.
    """
    settings = make_battery_settings(cycle_cost_per_kwh=0.0)
    home, solar, buy, sell = 0.02, 0.0, 1.5, -0.5
    soe = settings.min_soe_kwh + 4 * SOE_STEP_KWH

    cover_p = _residual_cover_p(home, solar, DT, DEFAULT_CAPABILITIES, settings)
    assert cover_p is not None, "fixture no longer exercises the cover candidate"

    next_soe = _state_transition(
        soe,
        -cover_p,
        settings,
        DT,
        solar_production=solar,
        home_consumption=home,
    )
    cover_reward, _basis, _imported = _compute_reward(
        power=-cover_p,
        soe=soe,
        next_soe=next_soe,
        period=0,
        home_consumption=home,
        battery_settings=settings,
        dt=DT,
        solar_production=solar,
        buy_price=[buy],
        sell_price=[sell],
        cost_basis=0.0,
    )
    idle_reward, _basis, _imported = _compute_reward(
        power=0.0,
        soe=soe,
        next_soe=soe,
        period=0,
        home_consumption=home,
        battery_settings=settings,
        dt=DT,
        solar_production=solar,
        buy_price=[buy],
        sell_price=[sell],
        cost_basis=0.0,
    )
    assert cover_reward > idle_reward, "fixture no longer discriminates"

    assert (
        _single_period_value(settings, home, solar, buy, sell, soe, soe) == cover_reward
    )


def test_backward_pass_values_the_solar_export_bypass_candidate():
    """#313's SOE-held-flat bypass must be priced by V too.

    At min_soe no discharge is feasible, so the only way to beat IDLE's
    forced passive charge (which pays cycle cost and forgoes the export) is
    the bypass column. Dropping it leaves V at IDLE's value and this fails.
    """
    settings = make_battery_settings(cycle_cost_per_kwh=0.40)
    home, solar, buy, sell = 0.1, 1.5, 1.5, 0.9
    soe = settings.min_soe_kwh

    bypass_reward, _basis, _imported = _compute_reward(
        power=0.0,
        soe=soe,
        next_soe=soe,
        period=0,
        home_consumption=home,
        battery_settings=settings,
        dt=DT,
        solar_production=solar,
        buy_price=[buy],
        sell_price=[sell],
        cost_basis=0.0,
    )
    idle_next_soe = _state_transition(
        soe,
        0.0,
        settings,
        DT,
        solar_production=solar,
        home_consumption=home,
    )
    idle_reward, _basis, _imported = _compute_reward(
        power=0.0,
        soe=soe,
        next_soe=idle_next_soe,
        period=0,
        home_consumption=home,
        battery_settings=settings,
        dt=DT,
        solar_production=solar,
        buy_price=[buy],
        sell_price=[sell],
        cost_basis=0.0,
    )
    assert bypass_reward > idle_reward, "fixture no longer discriminates"

    assert (
        _single_period_value(settings, home, solar, buy, sell, soe, soe)
        == bypass_reward
    )
