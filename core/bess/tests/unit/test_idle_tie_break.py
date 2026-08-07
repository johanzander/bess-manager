"""Risk-aware IDLE tie-break (#466): when IDLE and a load-covering discharge
are within the DP's own value noise, prefer the discharge -- it fails safe
(tracks actual load) where IDLE fails unsafe (discharge hard-disabled)."""

from core.bess.dp_battery_algorithm import _prefer_load_covering_discharge

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
