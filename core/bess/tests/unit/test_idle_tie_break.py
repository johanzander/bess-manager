"""Risk-aware IDLE tie-break (#466): when IDLE and a load-covering discharge
are within the DP's own value noise, prefer the discharge -- it fails safe
(tracks actual load) where IDLE fails unsafe (discharge hard-disabled)."""

import numpy as np
import pytest

from core.bess.dp_battery_algorithm import (
    SOE_STEP_KWH,
    _best_action_at_continuous_state,
    _discretize_state_action_space,
    _prefer_load_covering_discharge,
)
from core.bess.pwl_window_dp import _pwl_best_action_at_continuous_state
from core.bess.settings import BatterySettings

# Candidate tuple: (value, power, next_soe, new_cost_basis, reward, grid_imported)
IDLE = (10.00, 0.0, 6.0, 0.0, 0.0, 0.25)
COVER = (9.995, -1.0, 5.74, 0.0, 0.25, 0.0)  # discharges 1 kW, covers 1 kW net load
OVER = (9.999, -3.0, 5.21, 0.0, 0.30, 0.0)  # discharges past load -> would export
CHARGE = (9.99, 2.0, 6.5, 0.0, -0.5, 0.75)


def _pick(candidates, best_index, epsilon=0.01, home=0.25, solar=0.0):
    return _prefer_load_covering_discharge(
        candidates,
        best_index,
        epsilon=epsilon,
        home_consumption=home,
        solar_production=solar,
        dt=0.25,
        rate_step=0.05,  # 5 kW battery / 100
    )


def test_near_tied_idle_swaps_to_load_covering_discharge():
    candidates = [IDLE, COVER, OVER, CHARGE]
    # IDLE wins argmax; COVER is 0.005 behind, inside epsilon=0.01 -> swap.
    assert _pick(candidates, best_index=0) == 1


def test_decisive_idle_margin_is_never_swapped():
    candidates = [IDLE, COVER, OVER, CHARGE]
    # COVER is 0.005 behind; with epsilon below that the hold is deliberate.
    assert _pick(candidates, best_index=0, epsilon=0.004) == 0


def test_never_swaps_into_exporting_discharge():
    # Only the over-load discharge is within epsilon -> no eligible swap.
    candidates = [IDLE, (9.90, -1.0, 5.74, 0.0, 0.25, 0.0), OVER, CHARGE]
    assert _pick(candidates, best_index=0) == 0


def test_export_cap_bounded_by_export_threshold():
    # rate_step=0.1 makes the old half-step admission (0.05 kW) exceed
    # BATTERY_EXPORT_THRESHOLD_KWH/dt (0.04 kW at dt=0.25) -- with the
    # tightened cap, eligibility is governed by the export threshold, not
    # the rate-step half-step. balance_zero_p is 1.0 kW (home=0.25 kWh,
    # dt=0.25h), so the cap admits discharge up to 1.04 kW.
    home, solar, dt, rate_step = 0.25, 0.0, 0.25, 0.1
    idle = (10.00, 0.0, 6.0, 0.0, 0.0, 0.25)
    # Overshoot = (1.045 - 1.0) * 0.25h = 0.01125 kWh > 0.01 threshold ->
    # real export -> must NOT be selected.
    just_over = (9.999, -1.045, 5.74, 0.0, 0.30, 0.0)
    # Overshoot = (1.03 - 1.0) * 0.25h = 0.0075 kWh < 0.01 threshold -> may
    # be selected.
    just_under = (9.995, -1.03, 5.76, 0.0, 0.28, 0.0)

    only_over = _prefer_load_covering_discharge(
        [idle, just_over],
        best_index=0,
        epsilon=0.01,
        home_consumption=home,
        solar_production=solar,
        dt=dt,
        rate_step=rate_step,
    )
    assert only_over == 0, "overshoot past the export threshold must not swap"

    with_under = _prefer_load_covering_discharge(
        [idle, just_over, just_under],
        best_index=0,
        epsilon=0.01,
        home_consumption=home,
        solar_production=solar,
        dt=dt,
        rate_step=rate_step,
    )
    assert with_under == 2, "overshoot within the export threshold may swap"


def test_non_idle_winner_is_untouched():
    candidates = [IDLE, COVER, OVER, CHARGE]
    assert _pick(candidates, best_index=3) == 3


def test_no_net_load_means_no_swap():
    # Solar covers the house: balance_zero_p <= 0, nothing to fail-safe.
    candidates = [IDLE, COVER, OVER, CHARGE]
    assert _pick(candidates, best_index=0, home=0.10, solar=0.50) == 0


def test_zero_epsilon_is_a_no_op():
    # Flat value function (dV/dSoE == 0) -> epsilon 0 -> tie-break disabled,
    # mirroring tie_detection's documented blind spot.
    candidates = [IDLE, COVER, OVER, CHARGE]
    assert _pick(candidates, best_index=0, epsilon=0.0) == 0


def test_picks_largest_eligible_coverage_among_ties():
    partial = (9.997, -0.5, 5.87, 0.0, 0.12, 0.12)  # covers half the load
    candidates = [IDLE, partial, COVER]
    # Both discharges are inside epsilon; the fuller cover (1.0 kW) wins.
    assert _pick(candidates, best_index=0) == 2


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
    # review finding). At slope=1.02 (just above buy=1.0) that halving is
    # enough to shrink epsilon below the tie margin and only swap a partial
    # discharge; the correctly one-sided slope keeps epsilon large enough to
    # swap the full load-covering discharge.
    settings = _lossless_battery()
    action = _pwl_replay_choice(value_slope=1.02, soe=settings.max_soe_kwh)
    assert action < 0, f"expected load-covering discharge, got {action}"
    assert -action == pytest.approx(1.0, abs=0.05)
