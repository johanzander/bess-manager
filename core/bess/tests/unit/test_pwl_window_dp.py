import numpy as np
import pytest

from core.bess import pwl_window_dp
from core.bess.action_selector import _discharge_candidates
from core.bess.dp_constants import POWER_STEP_KW
from core.bess.exceptions import PWLWindowUnderRefinedError
from core.bess.execution_model import DEFAULT_CAPABILITIES
from core.bess.pwl_window_dp import (
    _backward_discharge_levels,
    _end_soe_pin_tolerance,
    _pinned_terminal_row,
    _pwl_best_action_at_continuous_state,
    _pwl_candidate_values_at,
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

    action, next_soe, _new_cost_basis, _reward, _flows = (
        _pwl_best_action_at_continuous_state(
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
        _action, next_soe, cost_basis, _reward, _flows = (
            _pwl_best_action_at_continuous_state(
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
        )
        soe = next_soe

    # The real invariant is the pin's own half-width, not a round number:
    # the discharge lattice guarantees a reachable state inside the band, so
    # anything outside it means the pin failed to steer.
    pin_half_width = _end_soe_pin_tolerance(1e-3, battery, dt, DEFAULT_CAPABILITIES)
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

    floored = _end_soe_pin_tolerance(1e-6, battery, dt, DEFAULT_CAPABILITIES)
    assert floored == pytest.approx(lattice_step / 2)

    # A caller asking for a *wider* band keeps it.
    honoured = _end_soe_pin_tolerance(0.5, battery, dt, DEFAULT_CAPABILITIES)
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
        1e-3, battery, dt=0.25, capabilities=DEFAULT_CAPABILITIES
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
        _backward_discharge_levels(battery, DEFAULT_CAPABILITIES)
        * dt
        / battery.efficiency_discharge
    )
    # A row far larger than the old 30000 / 98 ~ 306 cut-off.
    xs_next = np.linspace(battery.min_soe_kwh, battery.max_soe_kwh, 2000)

    X = _pwl_window_seed_points(
        0, xs_next, battery, dt, [0.0], [0.0], capabilities=DEFAULT_CAPABILITIES
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


def _solve_tiny_window(battery: BatterySettings):
    """A small but non-trivial window (varying prices, non-zero load) whose
    rows genuinely need adaptive refinement -- used by the guard tests below,
    which shrink one budget at a time and require a loud failure."""
    return run_pwl_window_backward_induction(
        window_horizon=3,
        buy_price=[1.0, 2.0, 0.5],
        sell_price=[0.5, 1.5, 0.2],
        home_consumption=[0.5, 0.5, 0.5],
        solar_production=[0.0, 0.0, 0.0],
        battery_settings=battery,
        dt=0.25,
        end_soe_target=5.0,
    )


def test_breakpoint_ceiling_raises_instead_of_returning_an_approximation(monkeypatch):
    """Hitting `PWL_MAX_BREAKPOINTS` means the row is an under-refined
    approximation. Returning it anyway would let the caller splice it into
    the schedule as if it were exact -- a silent degradation of the one path
    where the solver knows its own answer is untrustworthy."""
    monkeypatch.setattr(pwl_window_dp, "PWL_MAX_BREAKPOINTS", 5)
    with pytest.raises(PWLWindowUnderRefinedError, match="breakpoint ceiling"):
        _solve_tiny_window(_tiny_battery())


def test_refinement_non_convergence_raises(monkeypatch):
    """Exhausting `PWL_MAX_REFINE_ITERS` without the probe error dropping
    below tolerance means the row still carries representation error above
    `PWL_EPS_REFINE` -- not something a caller may treat as exact."""
    monkeypatch.setattr(pwl_window_dp, "PWL_MAX_REFINE_ITERS", 1)
    with pytest.raises(PWLWindowUnderRefinedError, match="did not converge"):
        _solve_tiny_window(_tiny_battery())


def test_skipped_preimage_seeding_raises(monkeypatch):
    """Skipping exact discharge-preimage seeding can misplace the terminal
    pin's reachable-set boundary by ~1e6 SEK/kWh of fictitious value, which
    is enough to invert the window's decision."""
    monkeypatch.setattr(pwl_window_dp, "PWL_MAX_PREIMAGE_SEED_POINTS", 1)
    with pytest.raises(PWLWindowUnderRefinedError, match="discharge-preimage"):
        _solve_tiny_window(_tiny_battery())


def test_pwl_replay_respects_the_grid_import_cap():
    """The windowed PWL replay must obey the same fuse-derived grid-import
    cap (#429) the surrounding grid DP enforces.

    The window is re-solved precisely where charging-vs-not is closest
    (#450), so an unthreaded cap here would let the exact solver splice back
    a grid-charge action the house's fuse cannot carry -- silently weakening
    the constraint exactly where it is most likely to bind.
    """
    battery = _tiny_battery()
    # Continuation value rising steeply with SOE, so charging is strongly
    # preferred and only the cap can hold it back.
    v_next = (
        np.array([battery.min_soe_kwh, battery.max_soe_kwh]),
        np.array([0.0, 10.0 * (battery.max_soe_kwh - battery.min_soe_kwh)]),
    )
    home = 1.0  # kWh per period of household load
    cap = 1.2  # leaves only 0.2 kWh of headroom for grid charging

    _, uncapped_next_soe, _, _, _ = _pwl_best_action_at_continuous_state(
        soe=2.0,
        t=0,
        V_next=v_next,
        power_levels=np.array([]),
        home_consumption=[home],
        battery_settings=battery,
        dt=1.0,
        solar_production=[0.0],
        buy_price=[0.1],
        sell_price=[0.0],
        cost_basis=0.0,
        max_charge_power_per_period=None,
    )
    _, capped_next_soe, _, _, _ = _pwl_best_action_at_continuous_state(
        soe=2.0,
        t=0,
        V_next=v_next,
        power_levels=np.array([]),
        home_consumption=[home],
        battery_settings=battery,
        dt=1.0,
        solar_production=[0.0],
        buy_price=[0.1],
        sell_price=[0.0],
        cost_basis=0.0,
        max_charge_power_per_period=None,
        import_cap_kwh=cap,
    )

    # Uncapped, STORE charges at the full 5 kW rate (4.75 kWh stored after
    # charge efficiency) and would import 6.0 kWh -- five times the cap.
    assert uncapped_next_soe == pytest.approx(2.0 + 5.0 * battery.efficiency_charge)
    # Capped, only the 0.2 kWh the load leaves may go to the battery.
    assert capped_next_soe == pytest.approx(2.0 + 0.2 * battery.efficiency_charge)


def _planned_import_kwh(
    soe: float, next_soe: float, home_consumption: float, battery: BatterySettings
) -> float:
    """Grid import a no-solar period's plan actually requires, derived from the
    SOE the solver committed to.

    Deliberately NOT `_compute_reward`'s returned `grid_imported`: that function
    self-throttles grid charging against the very cap under test, so it reports
    a within-cap number for a plan that charges far beyond the cap. Asking it
    would make the assertion true by construction (this is exactly how the
    first version of these tests passed with the cap threading stripped out).
    The achieved SOE delta cannot lie -- storing it took
    `delta / efficiency_charge` kWh off the meter, on top of the house load.
    """
    return home_consumption + max(0.0, (next_soe - soe) / battery.efficiency_charge)


def test_pwl_window_backward_induction_respects_the_grid_import_cap():
    """End to end over a whole window: every replayed period's planned grid
    import stays within the cap (#429), and the window still charges (so the
    assertion is not vacuously satisfied by an idle plan).

    Verified by reversion: stripping the cap from
    `_pwl_best_action_at_continuous_state` makes this fail with a planned
    import of 6.0 kWh against the 1.2 kWh cap. It does NOT catch a cap
    stripped from the backward pass alone -- the pin still steers the replay
    to the same trajectory here -- so `_pwl_candidate_values_at` is covered
    separately by
    `test_pwl_backward_induction_values_reflect_the_grid_import_cap`.
    """
    battery = _tiny_battery()
    home = 1.0
    cap = 1.2
    start_soe = 2.0
    per_period_gain = 0.2 * battery.efficiency_charge
    end_soe_target = start_soe + 2 * per_period_gain

    kwargs = {
        "window_horizon": 2,
        "buy_price": [0.1, 0.1],
        "sell_price": [0.0, 0.0],
        "home_consumption": [home, home],
        "solar_production": [0.0, 0.0],
        "battery_settings": battery,
        "dt": 1.0,
        "import_cap_kwh": cap,
    }
    V = run_pwl_window_backward_induction(end_soe_target=end_soe_target, **kwargs)
    actions = resolve_pwl_window(V, start_soe=start_soe, cost_basis=0.0, **kwargs)

    soe = start_soe
    for t, (_power, next_soe, _flows) in enumerate(actions):
        planned_import = _planned_import_kwh(soe, next_soe, home, battery)
        assert planned_import <= cap + 1e-9, (
            f"period {t} plans {planned_import} kWh of grid import, above the "
            f"fuse cap of {cap} kWh"
        )
        soe = next_soe

    assert soe > start_soe, "window should still charge -- otherwise vacuous"


def test_pwl_backward_induction_values_reflect_the_grid_import_cap():
    """Direct coverage of the backward pass (`_pwl_candidate_values_at`).

    The V-table itself must be built under the cap, not just the forward
    replay: the table is what the replay's one-step Bellman recompute reads as
    its continuation value, so an uncapped table prices reachability the fuse
    does not permit. With a pin the capped solver cannot reach, an uncapped
    solve reaches it comfortably -- so the two tables must disagree at the
    start SOE, and only the capped one may report the window infeasible.
    """
    battery = _tiny_battery()
    home = 1.0
    cap = 1.2
    start_soe = 2.0
    # Reachable only by charging faster than the cap allows: the uncapped
    # STORE action stores 4.75 kWh in one period, the capped one 0.19 kWh.
    end_soe_target = start_soe + 2.0

    kwargs = {
        "window_horizon": 2,
        "buy_price": [0.1, 0.1],
        "sell_price": [0.0, 0.0],
        "home_consumption": [home, home],
        "solar_production": [0.0, 0.0],
        "battery_settings": battery,
        "dt": 1.0,
        "end_soe_target": end_soe_target,
    }
    V_capped = run_pwl_window_backward_induction(import_cap_kwh=cap, **kwargs)
    V_uncapped = run_pwl_window_backward_induction(import_cap_kwh=None, **kwargs)

    assert pwl_window_is_feasible(
        V_uncapped, start_soe
    ), "without a cap the window can charge its way to the pinned end SOE"
    assert not pwl_window_is_feasible(V_capped, start_soe), (
        "the capped backward pass must not price the pinned end SOE as "
        "reachable -- getting there needs more grid import than the fuse "
        "allows, so V[0] has to carry the terminal penalty"
    )


def test_backward_pass_admits_the_discharge_levels_the_replay_admits():
    """The two passes must agree on which discharge levels a state affords.

    `_backward_discharge_levels`' docstring states the module's core
    invariant: both passes enumerate the same hardware-true integer-percent
    action set, which is "what makes the replayed schedule achieve exactly the
    value the backward pass promised". The replay reaches that set through
    `_discharge_candidates`, which percent-floors its rate ceiling with an
    explicit `+ 1e-9` slack, so a state a floating-point hair below the onset
    of level L still affords L. The backward pass's own feasibility mask had
    no such slack, so at exactly that state it silently dropped L.

    That is not a hypothetical: the solver's breakpoint abscissae are built by
    adding lattice energies to the *previous* row's breakpoints, so they carry
    ULP-level noise and land on both sides of an onset. Here the two passes
    are handed the identical continuation row and the identical state one ULP
    below level L's onset; disagreeing means the table promises a value the
    replay cannot deliver, or (as measured on
    `historical_2024_08_16_high_spread_no_solar`) refuses a level the replay
    would have taken and prices the state 26 000 SEK below its true value.
    """
    battery = _tiny_battery()
    dt = 1.0
    level = 2.5  # an exact member of this battery's 0.05 kW percent lattice
    assert np.isclose(
        _backward_discharge_levels(battery, DEFAULT_CAPABILITIES), level
    ).any()

    # One ULP below the SOE at which `level` becomes affordable.
    onset = battery.min_soe_kwh + level * dt / battery.efficiency_discharge
    soe = float(np.nextafter(onset, 0.0))

    buy_price, sell_price, home, solar = [1.0], [0.5], [0.5], [0.0]
    continuation = _pinned_terminal_row(
        battery.min_soe_kwh,
        _end_soe_pin_tolerance(1e-6, battery, dt, DEFAULT_CAPABILITIES),
        battery,
    )

    # The replay's action set affords `level` at this state...
    replay_levels = _discharge_candidates(
        soe,
        battery,
        dt,
        home[0],
        solar[0],
        ac_cap_kwh=None,
    )
    assert np.isclose(replay_levels, level).any(), (
        "precondition: the replay must afford this level here, otherwise the "
        "test is not measuring a backward/forward disagreement"
    )

    # ...so the replay's one-step Bellman value is the value to match.
    _action, next_soe, _basis, reward, _flows = _pwl_best_action_at_continuous_state(
        soe=soe,
        t=0,
        V_next=continuation,
        power_levels=np.array([]),
        home_consumption=home,
        battery_settings=battery,
        dt=dt,
        solar_production=solar,
        buy_price=buy_price,
        sell_price=sell_price,
        cost_basis=0.0,
        max_charge_power_per_period=None,
        import_cap_kwh=None,
    )
    replay_value = reward + float(_pwl_eval_array(continuation, np.asarray(next_soe)))

    power_row = np.concatenate(
        (
            [0.0],
            _backward_discharge_levels(battery, DEFAULT_CAPABILITIES) * -1,
            [POWER_STEP_KW],
        )
    )
    backward_value = _pwl_candidate_values_at(
        np.array([soe]),
        0,
        continuation,
        power_row,
        (buy_price, sell_price, home, solar),
        battery,
        dt,
        None,
        None,
    )[0]

    assert backward_value == pytest.approx(replay_value, abs=1e-9), (
        f"backward pass priced this state at {backward_value} SEK while the "
        f"replay achieves {replay_value} SEK from the same continuation row"
    )
