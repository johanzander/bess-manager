"""Risk-aware IDLE tie-break (#466): when IDLE and a load-covering discharge
are within the DP's own value noise, prefer the discharge -- it fails safe
(tracks actual load) where IDLE fails unsafe (discharge hard-disabled)."""

import numpy as np
import pytest

from core.bess.dp_battery_algorithm import (
    SOE_STEP_KWH,
    _best_action_at_continuous_state,
    _discretize_state_action_space,
    optimize_battery_schedule,
)
from core.bess.pwl_window_dp import (
    _pwl_best_action_at_continuous_state,
    _pwl_local_value_slope,
)
from core.bess.settings import BatterySettings
from core.bess.tests.unit.test_scenarios import (
    build_scenario_optimizer_inputs,
)
from core.bess.tie_detection import TIE_NOISE_FACTOR

# The candidate-level cases for this tie-break now live in
# `test_tie_policy.py`, alongside the rest of the P2 preference table --
# they moved with the rule itself, unchanged. What stays here is the
# end-to-end evidence: the same preference observed through the real grid
# and PWL replays, and through #466's own regression fixture.


def _lossless_battery() -> BatterySettings:
    return BatterySettings(
        total_capacity=10.0,
        min_soc=10.0,
        max_soc=100.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        efficiency_charge=1.0,
        efficiency_discharge=1.0,
        cycle_cost_per_kwh=0.0,
        inverter_max_ac_power_kw=0.0,
    )


def _replay_choice(value_slope: float) -> float:
    """Run the one-step replay at soe=6.0 with 1 kW net load, no solar,
    buy=1.0, and a linear V[t+1] of the given slope; return chosen power.

    Discharging d kWh saves d*buy now but forfeits d*slope of continuation
    value (lossless battery), so idle-vs-cover margin = d*(slope - buy):
    slope == buy -> exact tie; slope >> buy -> decisive hold.

    max_charge_power_per_period is pinned to 0.0: at soe=6.0 the battery
    has 4 kWh of headroom, so an unconstrained charge candidate is itself
    profitable arbitrage whenever slope > buy (independent of the
    IDLE-vs-discharge comparison this test isolates) and would win the
    argmax outright at slope=2.0, masking the case under test. Disabling
    charge removes that confound without touching the IDLE/discharge
    candidates the tie-break in this test module targets.
    """
    settings = _lossless_battery()
    soe_levels = np.arange(
        settings.min_soe_kwh, settings.max_soe_kwh + SOE_STEP_KWH, SOE_STEP_KWH
    )
    V_next = value_slope * (soe_levels - settings.min_soe_kwh)
    _, power_levels = _discretize_state_action_space(settings)
    action, *_rest = _best_action_at_continuous_state(
        soe=6.0,
        t=0,
        V_next=V_next,
        power_levels=power_levels,
        home_consumption=[0.25],
        battery_settings=settings,
        dt=0.25,
        solar_production=[0.0],
        buy_price=[1.0],
        sell_price=[0.4],
        cost_basis=0.0,
        max_charge_power_per_period=[0.0],
    )
    return action


def test_replay_swaps_exact_tie_to_load_cover():
    # slope == buy: idle and cover are exactly tied -> fail-safe side wins.
    action = _replay_choice(value_slope=1.0)
    assert action < 0, f"expected load-covering discharge, got {action}"
    # Covers the 1 kW net load (within one percent-step of 5 kW / 100).
    assert -action == pytest.approx(1.0, abs=0.05)


def test_replay_tie_margin_is_non_negative_when_swap_fires():
    # #466 review: tie_margin must be measured at the PRE-swap value-argmax,
    # not the post-swap executed action -- otherwise a fired swap (this is
    # the exact-tie case from test_replay_swaps_exact_tie_to_load_cover)
    # reports a negative margin, which would wrongly flag this period as a
    # #450 tie window purely because #466 swapped the executed action.
    settings = _lossless_battery()
    soe_levels = np.arange(
        settings.min_soe_kwh, settings.max_soe_kwh + SOE_STEP_KWH, SOE_STEP_KWH
    )
    V_next = 1.0 * (soe_levels - settings.min_soe_kwh)  # slope == buy -> exact tie
    _, power_levels = _discretize_state_action_space(settings)
    action, _next_soe, _cost_basis, _reward, _flows, tie_margin, _value_slope = (
        _best_action_at_continuous_state(
            soe=6.0,
            t=0,
            V_next=V_next,
            power_levels=power_levels,
            home_consumption=[0.25],
            battery_settings=settings,
            dt=0.25,
            solar_production=[0.0],
            buy_price=[1.0],
            sell_price=[0.4],
            cost_basis=0.0,
            max_charge_power_per_period=[0.0],
        )
    )
    assert action < 0, f"expected the swap to fire, got action={action}"
    assert (
        tie_margin >= 0.0
    ), f"tie_margin must be non-negative even when #466 swaps, got {tie_margin}"


def test_replay_keeps_decisive_arbitrage_hold():
    # Stored energy worth far more later than covering load now.
    action = _replay_choice(value_slope=2.0)
    assert action == 0.0


def _pwl_replay_choice(value_slope: float, soe: float = 6.0) -> float:
    """Same construction as _replay_choice, against the PWL replay: linear
    continuation row as a two-breakpoint PWL, slope == buy -> exact tie.

    max_charge_power_per_period is pinned to 0.0 for the same reason
    documented on _replay_choice: an unconstrained charge candidate is
    itself profitable arbitrage at slope=2.0 and would win the argmax
    outright, masking the IDLE-vs-discharge case under test.
    """
    settings = _lossless_battery()
    xs = np.array([settings.min_soe_kwh, settings.max_soe_kwh])
    vs = value_slope * (xs - settings.min_soe_kwh)
    _, power_levels = _discretize_state_action_space(settings)
    action, *_rest = _pwl_best_action_at_continuous_state(
        soe=soe,
        t=0,
        V_next=(xs, vs),
        power_levels=power_levels,
        home_consumption=[0.25],
        battery_settings=settings,
        dt=0.25,
        solar_production=[0.0],
        buy_price=[1.0],
        sell_price=[0.4],
        cost_basis=0.0,
        max_charge_power_per_period=[0.0],
    )
    return action


def test_pwl_replay_swaps_exact_tie_to_load_cover():
    action = _pwl_replay_choice(value_slope=1.0)
    assert action < 0, f"expected load-covering discharge, got {action}"
    assert -action == pytest.approx(1.0, abs=0.05)


def test_pwl_replay_keeps_decisive_arbitrage_hold():
    assert _pwl_replay_choice(value_slope=2.0) == 0.0


def test_pwl_replay_full_swap_at_soe_ceiling():
    # Winner (IDLE) lands at next_soe == max_soe_kwh -- the domain's upper
    # breakpoint. _pwl_eval_array extrapolates the true slope below xs[0]
    # but np.interp clamps flat above xs[-1], so a naive central difference
    # straddling the ceiling averages in that flat segment and reports half
    # the true one-sided slope, understating epsilon exactly here (#466
    # review finding). The slope is chosen so the full cover's margin
    # (0.25 kWh x (slope-1) = 0.75x epsilon) swaps under the correct
    # one-sided slope but not under the halved flat-clamped estimate --
    # expressed via the live constants so the engineered margin tracks
    # grid-resolution changes (#512) instead of hardcoding the 0.05 kWh
    # era's slope=1.02.
    settings = _lossless_battery()
    slope = 1.0 + 3.0 * TIE_NOISE_FACTOR * SOE_STEP_KWH
    action = _pwl_replay_choice(value_slope=slope, soe=settings.max_soe_kwh)
    assert action < 0, f"expected load-covering discharge, got {action}"
    assert -action == pytest.approx(1.0, abs=0.05)


def test_pwl_local_value_slope_matches_line_slope_at_interior_point():
    xs = np.array([0.0, 10.0])
    vs = np.array([0.0, 20.0])  # slope 2.0
    assert _pwl_local_value_slope((xs, vs), soe=5.0) == pytest.approx(2.0)


def test_pwl_local_value_slope_is_one_sided_at_last_breakpoint():
    # soe == xs[-1]: a naive central difference straddling the ceiling would
    # average in the flat extrapolation above xs[-1] and report half the
    # true slope (the #466 review finding pinned by
    # test_pwl_replay_full_swap_at_soe_ceiling above). The clamped-span
    # divisor keeps this exact instead.
    xs = np.array([0.0, 10.0])
    vs = np.array([0.0, 20.0])  # slope 2.0
    assert _pwl_local_value_slope((xs, vs), soe=10.0) == pytest.approx(2.0)


def test_466_tie_break_does_not_trip_idle_guardrail():
    """The idle-schedule guardrail (dp_battery_algorithm.py, ~2320) silently
    returns the all-IDLE schedule if it ever costs strictly less than the
    DP's own plan -- a fail-safe against SoE-grid discretization residual.
    #466's tie-break trades up to epsilon/period to prefer a load-covering
    discharge over IDLE, which narrows (in theory) the margin the guardrail
    compares against. No known fixture trips it (#466 review: smallest
    observed margin 0.119 SEK vs worst forfeiture 0.032 SEK), but the
    fixture that exercises the tie-break most directly is #466's own
    regression scenario -- pin that it still doesn't trip here."""
    _, inputs = build_scenario_optimizer_inputs("regression_2026_08_06_466")
    result = optimize_battery_schedule(**inputs)

    actions = [pd.decision.battery_action for pd in result.period_data]
    assert any(
        abs(a) > 1e-9 for a in actions
    ), "guardrail appears to have fired -- schedule is all-IDLE"
    assert result.period_data[45].decision.strategic_intent == "LOAD_SUPPORT"

    # Period 32's intent tracks the grid resolution, correctly each time. It
    # was LOAD_SUPPORT until #497, then IDLE: its 0.0431 kWh deficit sat below
    # the smallest commandable discharge under the 0.2 kW grid (0.05 kWh =
    # 0.2 kW * 0.25 h, the first step above POWER_CLASSIFICATION_THRESHOLD_KW),
    # every candidate overshot by less than the export resolution, and #497's
    # rule rightly declined all of them. #512's finer grid halves the
    # classification threshold, so a smaller under-covering discharge is now
    # commandable and executable exactly as planned -- the period flips back
    # to LOAD_SUPPORT, covering part of the deficit instead of importing all
    # of it. Measured, not assumed: realized cost on this fixture improved by
    # 0.0181 SEK under the finer grid, and R == P still holds corpus-wide.
    assert result.period_data[32].decision.strategic_intent == "LOAD_SUPPORT"
