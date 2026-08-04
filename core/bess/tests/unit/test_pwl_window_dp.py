import numpy as np
import pytest

from core.bess.pwl_window_dp import (
    _backward_discharge_levels,
    _end_soe_pin_tolerance,
    _pwl_best_action_at_continuous_state,
    _pwl_eval_array,
    _pwl_prune,
    _pwl_window_seed_points,
    pwl_window_is_feasible,
    resolve_pwl_window,
    run_pwl_window_backward_induction,
)
from core.bess.settings import BatterySettings


def _tiny_battery() -> BatterySettings:
    """10 kWh usable-range battery: min_soe 1.0 kWh, max_soe 10.0 kWh.

    `min_soe_kwh`/`max_soe_kwh` are derived (init=False) in BatterySettings,
    so they are set via total_capacity/min_soc/max_soc rather than directly.
    """
    return BatterySettings(
        total_capacity=10.0,
        min_soc=10.0,
        max_soc=100.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        efficiency_charge=0.95,
        efficiency_discharge=0.95,
        cycle_cost_per_kwh=0.0,
        inverter_max_ac_power_kw=0.0,  # 0 disables the AC cap
    )


def test_pwl_eval_array_interpolates_between_breakpoints():
    xs = np.array([0.0, 5.0, 10.0])
    vs = np.array([0.0, 10.0, 15.0])
    result = _pwl_eval_array((xs, vs), np.array([2.5, 7.5]))
    assert result[0] == pytest.approx(5.0)
    assert result[1] == pytest.approx(12.5)


def test_pwl_eval_array_extrapolates_below_first_breakpoint():
    xs = np.array([1.0, 2.0])
    vs = np.array([10.0, 20.0])
    result = _pwl_eval_array((xs, vs), np.array([0.0]))
    assert result[0] == pytest.approx(
        0.0
    )  # slope 10/unit, extrapolated down from (1, 10)


def test_pwl_prune_drops_collinear_interior_points():
    xs = np.array([0.0, 1.0, 2.0, 3.0])
    vs = np.array(
        [0.0, 1.0, 2.0, 3.0]
    )  # perfectly linear -- interior points are redundant
    pruned_xs, _pruned_vs = _pwl_prune(xs, vs, eps=1e-9)
    assert len(pruned_xs) == 2
    assert list(pruned_xs) == [0.0, 3.0]


def test_pwl_best_action_at_continuous_state_prefers_idle_when_flat_continuation():
    """With a continuation value function that's flat (indifferent to SOE)
    and zero prices, IDLE should be selected -- no incentive to move energy."""
    battery_settings = BatterySettings()
    xs = np.array([battery_settings.min_soe_kwh, battery_settings.max_soe_kwh])
    vs = np.array([0.0, 0.0])
    soe = (battery_settings.min_soe_kwh + battery_settings.max_soe_kwh) / 2

    action, next_soe, _new_cost_basis, _reward = _pwl_best_action_at_continuous_state(
        soe=soe,
        t=0,
        V_next=(xs, vs),
        power_levels=np.array([]),
        home_consumption=[0.0],
        battery_settings=battery_settings,
        dt=1.0,
        solar_production=[0.0],
        buy_price=[0.0],
        sell_price=[0.0],
        cost_basis=0.0,
        max_charge_power_per_period=None,
    )

    assert action == pytest.approx(0.0)
    assert next_soe == pytest.approx(soe)


def test_pinned_terminal_soe_penalizes_states_far_from_target():
    battery = _tiny_battery()
    V = run_pwl_window_backward_induction(
        window_horizon=3,
        buy_price=[1.0, 1.0, 1.0],
        sell_price=[0.5, 0.5, 0.5],
        home_consumption=[0.0, 0.0, 0.0],
        solar_production=[0.0, 0.0, 0.0],
        battery_settings=battery,
        dt=0.25,
        end_soe_target=5.0,
        end_soe_tolerance=1e-3,
    )
    terminal_row = V[3]
    near_target_value = _pwl_eval_array(terminal_row, np.array([5.0]))[0]
    far_from_target_value = _pwl_eval_array(terminal_row, np.array([1.5]))[0]
    assert near_target_value > far_from_target_value + 1e6, (
        "states far from the pinned target must be penalized far below "
        "states at the target, or backward induction won't preferentially "
        "route trajectories toward it"
    )


def test_pinned_terminal_penalty_survives_backward_propagation():
    """The pin must still be visible in V[0] after propagating back through
    `_pwl_candidate_values_at` interpolation *and* `_pwl_prune` -- the whole
    point of the pin is that it steers the window's first action.

    With dt=0.25 and max_charge_power 5 kW, one period adds at most
    5 * 0.25 * 0.95 = 1.1875 kWh, so over 3 periods a battery starting at
    min_soe (1.0) can reach at most 4.5625 kWh -- it can never hit the 5.0
    target. Starting at 8.0 it can (3.0 kWh of discharge is an exact
    multiple of the 0.0125/0.95 kWh discharge lattice step). So V[0] must
    separate the two by a penalty-scale margin, not a cents-scale one.
    """
    battery = _tiny_battery()
    V = run_pwl_window_backward_induction(
        window_horizon=3,
        buy_price=[1.0, 1.0, 1.0],
        sell_price=[0.5, 0.5, 0.5],
        home_consumption=[0.0, 0.0, 0.0],
        solar_production=[0.0, 0.0, 0.0],
        battery_settings=battery,
        dt=0.25,
        end_soe_target=5.0,
        end_soe_tolerance=1e-3,
    )
    reachable = _pwl_eval_array(V[0], np.array([8.0]))[0]
    unreachable = _pwl_eval_array(V[0], np.array([1.0]))[0]
    assert reachable > -1000.0, (
        f"a start SOE that can reach the target must keep ~economic-scale "
        f"value, got {reachable}"
    )
    assert unreachable < -1e5, (
        f"a start SOE that cannot reach the target must carry the terminal "
        f"penalty, got {unreachable}"
    )


def test_pinned_window_forward_replay_lands_on_target():
    """End-to-end proof the pin works: replaying the greedy Bellman policy
    against this V table from a known start SOE must land within tolerance
    of the pinned end SOE.

    Uses `_pwl_best_action_at_continuous_state` (already available from
    Task 4) directly rather than Task 6's `resolve_pwl_window` wrapper, so
    the numerical claim is verified here where the pin is implemented.
    """
    battery = _tiny_battery()
    horizon = 4
    dt = 0.25
    buy_price = [1.0, 3.0, 0.5, 2.0]
    sell_price = [0.5, 2.5, 0.2, 1.5]
    home_consumption = [0.5] * horizon
    solar_production = [0.0] * horizon
    start_soe = 8.0
    target = 6.0

    V = run_pwl_window_backward_induction(
        window_horizon=horizon,
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        battery_settings=battery,
        dt=dt,
        end_soe_target=target,
        end_soe_tolerance=1e-3,
    )

    soe = start_soe
    cost_basis = 0.0
    for t in range(horizon):
        _action, next_soe, cost_basis, _reward = _pwl_best_action_at_continuous_state(
            soe=soe,
            t=t,
            V_next=V[t + 1],
            power_levels=np.array([]),
            home_consumption=home_consumption,
            battery_settings=battery,
            dt=dt,
            solar_production=solar_production,
            buy_price=buy_price,
            sell_price=sell_price,
            cost_basis=cost_basis,
            max_charge_power_per_period=None,
        )
        soe = next_soe

    # The real invariant is the pin's own half-width, not a round number:
    # the discharge lattice guarantees a reachable state inside the band, so
    # anything outside it means the pin failed to steer.
    pin_half_width = _end_soe_pin_tolerance(
        1e-3, battery, dt, discharge_resolution_kw=None
    )
    assert soe == pytest.approx(target, abs=pin_half_width), (
        f"forward replay must land within the pin half-width "
        f"{pin_half_width} of the pinned end SOE {target}, got {soe}"
    )
    assert pwl_window_is_feasible(V, start_soe)


def test_end_soe_pin_tolerance_is_floored_at_half_the_action_lattice():
    """A tolerance finer than the discharge action lattice is unsatisfiable,
    so it is raised to half a lattice step (see `_end_soe_pin_tolerance`)."""
    battery = _tiny_battery()
    dt = 0.25
    lattice_step = (battery.max_discharge_power_kw / 100) * dt / 0.95

    floored = _end_soe_pin_tolerance(1e-6, battery, dt, discharge_resolution_kw=None)
    assert floored == pytest.approx(lattice_step / 2)

    # A caller asking for a *wider* band keeps it.
    honoured = _end_soe_pin_tolerance(0.5, battery, dt, discharge_resolution_kw=None)
    assert honoured == pytest.approx(0.5)


def test_unreachable_target_leaves_the_terminal_penalty_in_v0():
    """An end SOE the window physically cannot reach must surface as a
    penalty-scale V[0], so the caller can decline to splice the window."""
    battery = _tiny_battery()
    horizon = 2
    # Two 15-minute periods discharge at most 2 * 5 * 0.25 / 0.95 = 2.63 kWh,
    # so 9.5 -> 1.5 (8.0 kWh) is out of reach.
    V = run_pwl_window_backward_induction(
        window_horizon=horizon,
        buy_price=[1.0, 1.0],
        sell_price=[0.5, 0.5],
        home_consumption=[0.0, 0.0],
        solar_production=[0.0, 0.0],
        battery_settings=battery,
        dt=0.25,
        end_soe_target=1.5,
    )
    assert _pwl_eval_array(V[0], np.array([9.5]))[0] < -1e6


def test_unreachable_target_fails_the_feasibility_predicate():
    """The infeasibility contract is a function callers invoke, not a magic
    number they re-derive -- Task 6 gates its splice on this."""
    battery = _tiny_battery()
    V = run_pwl_window_backward_induction(
        window_horizon=2,
        buy_price=[1.0, 1.0],
        sell_price=[0.5, 0.5],
        home_consumption=[0.0, 0.0],
        solar_production=[0.0, 0.0],
        battery_settings=battery,
        dt=0.25,
        end_soe_target=1.5,
    )
    # 9.5 -> 1.5 needs 8.0 kWh in two 15-minute periods; at most 2.63 is
    # available, so this window cannot reconnect.
    assert not pwl_window_is_feasible(V, 9.5)
    # 3.0 -> 1.5 is comfortably within one period's discharge.
    assert pwl_window_is_feasible(V, 3.0)


def test_out_of_range_end_soe_target_raises():
    """Clipping would produce a legitimate-looking zero-penalty pin at the
    wrong SOE, so an impossible target must fail loudly instead."""
    battery = _tiny_battery()
    kwargs = {
        "window_horizon": 1,
        "buy_price": [1.0],
        "sell_price": [0.5],
        "home_consumption": [0.0],
        "solar_production": [0.0],
        "battery_settings": battery,
        "dt": 0.25,
    }
    with pytest.raises(ValueError, match="outside the battery's usable range"):
        run_pwl_window_backward_induction(end_soe_target=12.0, **kwargs)
    with pytest.raises(ValueError, match="outside the battery's usable range"):
        run_pwl_window_backward_induction(end_soe_target=0.5, **kwargs)


def test_resolve_pwl_window_reaches_pinned_end_soe_exactly():
    """End-to-end: `resolve_pwl_window` forward-replays V into an action
    sequence that lands within the pin's tolerance of the target, matching
    the manual replay loop already proven in
    `test_pinned_window_forward_replay_lands_on_target`."""
    battery = _tiny_battery()
    V = run_pwl_window_backward_induction(
        window_horizon=3,
        buy_price=[1.0, 1.0, 1.0],
        sell_price=[0.5, 0.5, 0.5],
        home_consumption=[0.0, 0.0, 0.0],
        solar_production=[0.0, 0.0, 0.0],
        battery_settings=battery,
        dt=0.25,
        end_soe_target=5.0,
        end_soe_tolerance=1e-3,
    )
    actions = resolve_pwl_window(
        V,
        start_soe=8.0,
        window_horizon=3,
        buy_price=[1.0, 1.0, 1.0],
        sell_price=[0.5, 0.5, 0.5],
        home_consumption=[0.0, 0.0, 0.0],
        solar_production=[0.0, 0.0, 0.0],
        battery_settings=battery,
        dt=0.25,
        cost_basis=0.0,
    )
    assert len(actions) == 3
    pin_half_width = _end_soe_pin_tolerance(
        1e-3, battery, dt=0.25, discharge_resolution_kw=None
    )
    final_soe = actions[-1][1]
    assert final_soe == pytest.approx(5.0, abs=pin_half_width)


def test_resolve_pwl_window_raises_on_infeasible_start_soe():
    """A window whose target is physically unreachable from `start_soe` must
    raise, not silently forward-replay through the terminal-penalty region
    and hand back actions that never reconnect."""
    battery = _tiny_battery()
    horizon = 2
    # Two 15-minute periods discharge at most 2 * 5 * 0.25 / 0.95 = 2.63 kWh,
    # so 9.5 -> 1.5 (8.0 kWh) is out of reach (mirrors
    # test_unreachable_target_fails_the_feasibility_predicate).
    V = run_pwl_window_backward_induction(
        window_horizon=horizon,
        buy_price=[1.0, 1.0],
        sell_price=[0.5, 0.5],
        home_consumption=[0.0, 0.0],
        solar_production=[0.0, 0.0],
        battery_settings=battery,
        dt=0.25,
        end_soe_target=1.5,
    )
    with pytest.raises(RuntimeError, match="infeasible"):
        resolve_pwl_window(
            V,
            start_soe=9.5,
            window_horizon=horizon,
            buy_price=[1.0, 1.0],
            sell_price=[0.5, 0.5],
            home_consumption=[0.0, 0.0],
            solar_production=[0.0, 0.0],
            battery_settings=battery,
            dt=0.25,
            cost_basis=0.0,
        )


def test_exact_discharge_preimages_are_seeded_on_every_row():
    """Regression: the preimage budget used to be shared with the per-row
    breakpoint ceiling, which silently switched this mechanism off on every
    row after the first backward step (|xs_next| > ~303 was enough). The
    seeded set must contain `b + e` for V[t+1]'s breakpoints `b` and every
    discharge energy step `e`, at realistic row sizes.
    """
    battery = _tiny_battery()
    dt = 0.25
    discharge_energy = (
        _backward_discharge_levels(battery, None) * dt / battery.efficiency_discharge
    )
    # A row far larger than the old 30000 / 98 ~ 306 cut-off.
    xs_next = np.linspace(battery.min_soe_kwh, battery.max_soe_kwh, 2000)

    X = _pwl_window_seed_points(
        0, xs_next, battery, dt, [0.0], [0.0], discharge_resolution_kw=None
    )

    expected = np.add.outer(xs_next, discharge_energy).ravel()
    expected = expected[
        (expected >= battery.min_soe_kwh) & (expected <= battery.max_soe_kwh)
    ]
    # Distance from each expected preimage to the nearest seeded point
    # (checking both neighbours, since dedup may have merged one away).
    idx = np.searchsorted(X, expected)
    left = X[np.clip(idx - 1, 0, len(X) - 1)]
    right = X[np.clip(idx, 0, len(X) - 1)]
    nearest = np.minimum(np.abs(left - expected), np.abs(right - expected))
    missing = expected[nearest > 1e-9]
    assert missing.size == 0, f"{missing.size} discharge preimages were not seeded"
