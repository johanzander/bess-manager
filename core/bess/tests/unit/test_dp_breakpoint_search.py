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

import numpy as np
import pytest

from core.bess.action_selector import (
    TIE_DEDUP_SOE_KWH,
    Candidate,
    _charge_candidate,
    _discharge_candidates,
    _residual_cover_p,
    _tie_margin,
)
from core.bess.dp_battery_algorithm import (
    PeriodFlows,
    _best_action_at_continuous_state,
    _discretize_state_action_space,
    _interpolate_value,
    _run_dynamic_programming,
)
from core.bess.dp_constants import POWER_CLASSIFICATION_THRESHOLD_KW
from core.bess.execution_model import DEFAULT_CAPABILITIES, PlatformCapabilities
from core.bess.models import GRID_FLOW_RESOLUTION_KWH
from core.bess.tests.helpers import make_battery_settings
from core.bess.tests.unit.test_scenarios import build_scenario_inputs


def _candidate(value: float, power: float, next_soe: float) -> Candidate:
    """A `Candidate` carrying only the three fields `_tie_margin` reads.

    The flow record is zeroed rather than derived: `_tie_margin` compares
    values and next_soe only, so inventing physics here would suggest these
    fixtures pin something they do not."""
    return Candidate(
        power=power,
        next_soe=next_soe,
        reward=0.0,
        new_cost_basis=0.0,
        flows=PeriodFlows(
            solar_to_battery=0.0,
            grid_to_battery=0.0,
            battery_charged=0.0,
            battery_discharged=0.0,
            grid_imported=0.0,
            grid_exported=0.0,
            clipped_solar=0.0,
            energy_stored=0.0,
        ),
        value=value,
    )


def _prepare(scenario_name):
    scenario, battery_settings, buy_prices, sell_prices, dt = build_scenario_inputs(
        scenario_name
    )
    horizon = len(buy_prices)
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
    _, best_next_soe, _, best_reward, _, _, _ = _best_action_at_continuous_state(
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


def _exhaustive_candidate_value(
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
    """Best total value over the production candidate set, evaluated directly.

    Enumerates IDLE, the charge candidate, and every discharge candidate via
    the same public enumeration the search uses, then computes each one's
    reward + interpolated continuation with the same V -- an independent
    maximum the search must match at any grid resolution.
    """
    from core.bess.dp_battery_algorithm import _compute_reward, _state_transition

    candidates = [0.0]
    charge = _charge_candidate(
        soe=soe, battery_settings=battery_settings, dt=dt, period_max_charge=None
    )
    if charge is not None:
        candidates.append(charge)
    candidates.extend(
        -p
        for p in _discharge_candidates(
            soe,
            battery_settings,
            dt,
            home_consumption[t],
            solar_production[t],
        )
    )
    best = None
    for power in candidates:
        next_soe = _state_transition(
            soe, power, battery_settings, dt, solar_production[t], home_consumption[t]
        )
        reward, _, _ = _compute_reward(
            power,
            soe,
            next_soe,
            t,
            home_consumption[t],
            battery_settings,
            dt,
            buy_prices,
            sell_prices,
            solar_production[t],
            0.0,
        )
        total = reward + _interpolate_value(V[t + 1, :], next_soe, battery_settings)
        best = total if best is None else max(best, total)
    return best


def test_off_grid_discharge_closes_interpolation_gap_case_1():
    """t=10, soe=13.083 kWh on the high-spread fixture: the cell where the
    old fixed POWER_STEP_KW grid search missed the best available action at
    an off-grid SoE (0.033 SEK single-period gap in the design doc's
    measurement). The breakpoint search must find the true maximum over its
    own executable candidate set -- asserted against a reference computed
    here by exhaustively evaluating every candidate with the same V, so the
    test survives grid-resolution changes (#512) instead of pinning the
    resolution-specific values the doc measured (-118.641847 vs
    -118.675085 under the 0.2 kW / 0.05 kWh grid)."""
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
    reference = _exhaustive_candidate_value(
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
    assert value == pytest.approx(reference, abs=1e-9), (
        f"breakpoint search returned {value}, but exhaustively evaluating its "
        f"own candidate set reaches {reference} -- the search is missing the "
        f"best available action at an off-grid SoE"
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
    must therefore be executable exactly as planned.

    Since Phase 4b that is "on the lattice **or** an exact-cover delivery",
    not "on the lattice" alone: the cover candidate is deliberately
    off-lattice because it plans the *delivery* of a ceiling command
    (`min(ceiling, actual load)`), and it is executable precisely when a
    covering ceiling exists on the platform -- which is what
    `covering_ceiling_kw` decides and what is asserted here. The 1.234 kW
    deficit below now produces one; before 4b the cover candidate was
    offered only below the smallest lattice step, so this scenario never
    reached it and the blanket lattice assertion happened to hold."""
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
    cover_p = _residual_cover_p(1.234, 0.0, 1.0, DEFAULT_CAPABILITIES, settings)
    assert cover_p is not None, (
        "this scenario is supposed to exercise the exact-cover candidate; "
        "if it no longer does, the exemption below is untested"
    )
    for p in candidates:
        if p == pytest.approx(cover_p, abs=1e-9):
            assert DEFAULT_CAPABILITIES.covering_ceiling_kw(p, settings) is not None, (
                f"exact-cover candidate {p} kW has no commandable covering "
                f"ceiling -- it cannot be delivered as planned"
            )
            continue
        pct = p / step
        assert pct == pytest.approx(round(pct), abs=1e-6), (
            f"candidate {p} kW is not an exact multiple of the hardware's "
            f"{step} kW (1%) rate step -- not executable as planned"
        )


def test_discharge_candidates_exceed_classification_threshold():
    """Second #282 postmortem: strategic_intent.classify_strategic_intent
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
    the classification threshold, not just above zero.

    One deliberate exception exists since the #466 sunrise-crossover
    follow-up: the residual load-cover candidate may sit at or below the
    threshold, because it is gated to classify LOAD_SUPPORT (via the
    battery_discharged > 0.01 kWh fallthrough) and to round to a nonzero
    percent -- see _residual_cover_p and
    test_discharge_candidates_include_sub_lattice_residual_cover. This
    scenario's residual (1.234 kW) is far above the lattice minimum, so no
    cover candidate appears here and the blanket assertion still holds."""
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


def test_discharge_candidates_include_sub_lattice_residual_cover():
    """#466 follow-up (sunrise crossover): when the forecast net load sits
    below the smallest percent-lattice candidate, the exact residual is a
    candidate -- discharging it covers the load with zero grid flows, and
    load-first hardware delivers min(actual load, ceiling) so the plan is
    executable despite being off the percent grid. Uses the real inputs
    from #466's second debug bundle: home 0.1675 kWh, solar 0.1461 kWh,
    dt=0.25h -> residual 85.7 W, vs a 0.2 kW smallest lattice candidate
    (10 kW battery, 1% steps, POWER_CLASSIFICATION_THRESHOLD_KW guard)."""
    settings = make_battery_settings(max_discharge_power_kw=10.0)
    home, solar, dt = 0.1675, 0.1461, 0.25
    residual_p = (home - solar) / dt

    candidates = _discharge_candidates(
        soe=4.34,
        battery_settings=settings,
        dt=dt,
        home_consumption=home,
        solar_production=solar,
    )
    assert any(
        c == pytest.approx(residual_p, abs=1e-9) for c in candidates
    ), f"expected residual-cover candidate {residual_p:.4f} kW in {candidates}"

    # Floors (see _residual_cover_p): below the classifier's 0.01 kWh
    # battery_discharged fallthrough the action would classify IDLE and
    # execute nothing -- no candidate may exist there.
    tiny = _discharge_candidates(
        soe=4.34,
        battery_settings=settings,
        dt=dt,
        home_consumption=0.010,  # residual 0.008 kWh = 0.032 kW
        solar_production=0.002,
    )
    assert all(
        c > POWER_CLASSIFICATION_THRESHOLD_KW for c in tiny
    ), f"sub-classifier residual must not produce a cover candidate: {tiny}"

    # Below half a percent step the rate register rounds to 0% and executes
    # nothing (dt=1h so the 0.01 kWh energy floor alone would pass).
    sub_step = _discharge_candidates(
        soe=4.34,
        battery_settings=settings,
        dt=1.0,
        home_consumption=0.030,  # residual 0.030 kW < 0.05 = half a step
        solar_production=0.0,
    )
    assert all(
        c > POWER_CLASSIFICATION_THRESHOLD_KW for c in sub_step
    ), f"sub-half-step residual must not produce a cover candidate: {sub_step}"

    # Round-DOWN band (review finding): a residual in (k*rate_step,
    # (k+0.5)*rate_step) for k >= 1 rounds to a percent ceiling BELOW the
    # residual -- e.g. 0.12 kW -> 1% of 10 kW = 0.10 kW -- so load-first
    # delivery (min(load, ceiling)) would under-deliver the plan by the
    # difference and break exact R == P. No cover candidate may exist there.
    round_down = _discharge_candidates(
        soe=4.34,
        battery_settings=settings,
        dt=dt,
        home_consumption=0.130,  # residual 0.03 kWh = 0.12 kW, ceiling 0.10
        solar_production=0.100,
    )
    assert all(
        c > POWER_CLASSIFICATION_THRESHOLD_KW for c in round_down
    ), f"round-down-band residual must not produce a cover candidate: {round_down}"


def test_charge_candidate_none_when_below_classification_threshold():
    """Same #282 threshold issue as discharge, on the charge side: when only
    a sliver of room remains near a full battery, `max_charge_power` can
    fall at or below POWER_CLASSIFICATION_THRESHOLD_KW (0.1 kW) -- picking
    it as the STORE candidate anyway would misclassify a genuine (if tiny)
    charge as noise at execution time. `_charge_candidate` must return
    `None` in that case (treat as no charge available) instead of a
    candidate the classifier can't recognize."""
    settings = make_battery_settings(max_charge_power_kw=10.0, efficiency_charge=1.0)
    # available_capacity = max_soe_kwh - soe -> max_charge_power equals that
    # room at dt=1.0; pick the room at half the live classification threshold
    # so the test tracks the grid resolution instead of hardcoding 0.05 kWh.
    from core.bess.dp_constants import POWER_CLASSIFICATION_THRESHOLD_KW

    soe = settings.max_soe_kwh - POWER_CLASSIFICATION_THRESHOLD_KW / 2
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


def test_discharge_candidates_exclude_unexecutable_overshoots():
    """#497: no candidate overshoots the home deficit by less than
    GRID_FLOW_RESOLUTION_KWH.

    This replaced #320's parameterized self-throttle threshold. That approach
    let the DP propose such a discharge and then zeroed the export *credit* in
    `_compute_reward`, which left `battery_discharged` and `next_soe` carrying
    energy the hardware never moved -- the flows did not add up and the plan
    was not executable. Excluding the action outright is strictly stronger:
    there is no longer a threshold anywhere downstream to keep in sync, and no
    platform needs to configure one.
    """
    settings = make_battery_settings(max_discharge_power_kw=5.0)
    deficit_kw = 1.0  # dt=1.0h, so also the deficit in kWh
    candidates = _discharge_candidates(
        soe=15.0,
        battery_settings=settings,
        dt=1.0,
        home_consumption=deficit_kw,
        solar_production=0.0,
    )

    unexecutable = [
        p for p in candidates if 0 < p - deficit_kw < GRID_FLOW_RESOLUTION_KWH
    ]
    assert not unexecutable, (
        f"candidates overshoot the deficit by less than the export resolution "
        f"and cannot be executed as commanded: {unexecutable}"
    )

    # Exact load cover survives (it is on the 1%-of-max grid here), so the
    # exclusion never costs the DP the ability to serve the home...
    assert deficit_kw in candidates
    # ...and a genuine, measurable export is still reachable.
    assert any(p - deficit_kw >= GRID_FLOW_RESOLUTION_KWH for p in candidates)


def test_discharge_candidates_use_injected_resolution():
    """#320: a platform with finer resolution than Growatt's 1%-of-max grid
    (e.g. a hypothetical 0.5%-of-max step) must produce twice as many
    candidates over the same feasible range, not the hardcoded /100 step."""
    settings = make_battery_settings(max_discharge_power_kw=10.0)
    default_candidates = _discharge_candidates(
        soe=15.0,
        battery_settings=settings,
        dt=1.0,
        home_consumption=1.234,
        solar_production=0.0,
    )
    finer_candidates = _discharge_candidates(
        soe=15.0,
        battery_settings=settings,
        dt=1.0,
        home_consumption=1.234,
        solar_production=0.0,
        capabilities=PlatformCapabilities(
            discharge_resolution_kw=settings.max_discharge_power_kw / 200
        ),
    )
    assert len(finer_candidates) > len(default_candidates)
    # every finer-grid candidate must still be an exact multiple of the
    # *injected* step, not the hardcoded 1% step -- except the exact-cover
    # candidate, which is off-lattice by construction on every step size
    # (it plans the delivery of a ceiling; see _residual_cover_p).
    finer_caps = PlatformCapabilities(
        discharge_resolution_kw=settings.max_discharge_power_kw / 200
    )
    step = settings.max_discharge_power_kw / 200
    cover_p = _residual_cover_p(1.234, 0.0, 1.0, finer_caps, settings)
    for p in finer_candidates:
        if cover_p is not None and p == pytest.approx(cover_p, abs=1e-9):
            continue
        pct = p / step
        assert pct == pytest.approx(round(pct), abs=1e-6)


def test_best_action_returns_tie_margin():
    """_best_action_at_continuous_state must report the gap between its
    chosen action's value and the runner-up's, so the hybrid tie detector
    (#450) can find near-tied periods without re-deriving this comparison."""
    (
        battery_settings,
        buy_prices,
        sell_prices,
        home_consumption,
        solar_production,
        V,
        dt,
    ) = _prepare("regression_2026_08_02_043728")
    t = 0
    soe = 2.0  # matches the fixture's documented initial_soe
    result = _best_action_at_continuous_state(
        soe,
        t,
        V[t + 1],
        power_levels=np.array(
            []
        ),  # unused by current implementation; keep call-compatible
        home_consumption=home_consumption,
        battery_settings=battery_settings,
        dt=dt,
        solar_production=solar_production,
        buy_price=buy_prices,
        sell_price=sell_prices,
        cost_basis=0.0,
        max_charge_power_per_period=None,
    )
    assert len(result) == 7, (
        "expected (action, next_soe, cost_basis, reward, flows, tie_margin, "
        "value_slope)"
    )
    _, _, _, _, _, tie_margin, _ = result
    assert (
        tie_margin >= 0.0
    ), "margin must be non-negative (best >= second-best by construction)"


def test_tie_margin_ignores_candidates_landing_at_the_same_soe():
    """The margin must measure ambiguity between behaviourally distinct
    actions, not the raw top-2 gap (#450).

    Several candidates _best_action_at_continuous_state evaluates are the
    same decision expressed twice -- most notably IDLE and the
    SOLAR_EXPORT-below-max candidate whenever there is no solar surplus to
    route differently. Ranking those against each other reported margin 0.0
    on 50-100% of periods of every fixture, which is not ambiguity at all.
    Candidates within TIE_DEDUP_SOE_KWH of the chosen next_soe are excluded
    from the runner-up search.
    """
    chosen = _candidate(value=10.0, power=0.0, next_soe=5.0)
    duplicate = _candidate(value=10.0, power=0.0, next_soe=5.0)  # same outcome
    distinct = _candidate(value=9.0, power=-2.0, next_soe=5.0 + TIE_DEDUP_SOE_KWH + 0.1)

    assert _tie_margin([chosen, duplicate], best_index=0) == float("inf")
    assert _tie_margin([chosen, duplicate, distinct], best_index=0) == pytest.approx(
        1.0
    )


def test_tie_margin_is_infinite_without_a_distinct_alternative():
    """ "No distinct alternative was feasible" must read as "not tied", not
    as a zero margin that the detector would flag (#450)."""
    only = _candidate(value=3.0, power=0.0, next_soe=5.0)
    assert _tie_margin([only], best_index=0) == float("inf")


def test_interpolate_value_extrapolates_below_min_soe():
    """#336: a below-floor SOE (a live sensor reading under min_soe_kwh,
    tolerated per #233's _soe_floor) must not be flattened to V_row[0].

    Real bundle evidence (bess-debug-2026-07-18-104523.md): with
    initial_soe=3.75kWh < min_soe_kwh=4.05kWh, every candidate whose
    next_soe stayed below the floor was clamped to the same degenerate
    V_row[0] value, so "charge a little" and "don't charge" looked equally
    worthless and the DP exported free solar at negative prices for 24
    straight periods instead of storing it. The value function must
    extrapolate the local gradient below the floor instead of clamping,
    so states below the floor are still distinguishable by how close they
    are to it.
    """
    settings = make_battery_settings(
        total_capacity=20.0, min_soc=11.0
    )  # min_soe_kwh = 2.2
    from core.bess.dp_constants import SOE_STEP_KWH

    step = SOE_STEP_KWH
    # V_row has a gradient of 1.0 value/kWh between the first two grid points
    V_row = np.array([2.0, 2.0 + step, 4.0, 6.0])

    soe_one_step_below_floor = settings.min_soe_kwh - step
    value = _interpolate_value(V_row, soe_one_step_below_floor, settings)

    # Extrapolating the V_row[0]->V_row[1] gradient (1.0 value/kWh) one step
    # below the floor should yield V_row[0] - step, not the clamped-flat 2.0.
    assert value == pytest.approx(2.0 - step, abs=1e-9)
    assert value != pytest.approx(V_row[0], abs=1e-9)


# --- #497 review follow-ups: the unexecutable-discharge exclusion must agree
# --- with models.py's noise fold at both boundaries.


def test_unexecutable_band_applies_down_to_zero_deficit():
    """models.py's noise fold applies whenever battery_to_home > 0 -- any
    positive deficit at all. The exclusion must use the same boundary: a
    deficit inside (0, POWER_TOLERANCE_KW] must not stand the predicate
    down, or the DP can still plan the exact #497 incoherent period there
    (0.2 kW against a 0.0008 kW deficit -> 0.0498 kWh phantom export)."""
    from core.bess.action_selector import _discharge_is_unexecutable

    assert _discharge_is_unexecutable(
        0.2, home_consumption=0.0002, solar_production=0.0, dt=0.25
    )


def test_exact_resolution_overshoot_stays_excluded():
    """An overshoot of exactly GRID_FLOW_RESOLUTION_KWH is excluded even
    though models.py's fold bound is strict (`< GRID_FLOW_RESOLUTION_KWH`)
    -- the inclusive upper bound is float safety margin, not drift. At the
    exact boundary the DP (subtracting powers) and the fold (subtracting
    energies) can land on opposite sides of the resolution, re-opening the
    #497 incoherence: verified on synthetic_seasonal_summer period 16,
    where admitting the boundary produced a planned 0.1 kWh export the
    fold erased and a 0.16 SEK plan-vs-execution gap. See the predicate's
    docstring."""
    from core.bess.action_selector import _discharge_is_unexecutable

    assert _discharge_is_unexecutable(
        1.1, home_consumption=1.0, solar_production=0.0, dt=1.0
    )


def test_tiny_deficit_plan_has_coherent_flows():
    """End-to-end regression for the residual (0, POWER_TOLERANCE_KW]
    deficit band: every discharge this small battery can command overshoots
    the 0.0008 kW deficit by less than GRID_FLOW_RESOLUTION_KWH, so the DP
    must propose none of them -- proposing one yields a period whose
    planned export the models.py fold erases (flows that do not add up)."""
    from core.bess.dp_battery_algorithm import optimize_battery_schedule
    from core.bess.tests.helpers import assert_flow_coherence

    settings = make_battery_settings(max_discharge_power_kw=0.2)
    horizon = 4
    result = optimize_battery_schedule(
        buy_price=[1.0] * horizon,
        sell_price=[0.5] * horizon,
        home_consumption=[0.0002] * horizon,
        solar_production=[0.0] * horizon,
        initial_soe=10.0,
        battery_settings=settings,
        period_duration_hours=0.25,
    )
    for pd in result.period_data:
        assert_flow_coherence(pd)
