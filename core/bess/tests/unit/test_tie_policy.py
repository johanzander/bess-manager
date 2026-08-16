"""The one ordered preference table (P2, `core/bess/tie_policy.py`).

Every case the two retired tie-break helpers were pinned against, ported
onto `apply_tie_policy` with the same candidates and the same expected
indices, plus the cases that only exist once the rows share one table:
the row 3 / row 4 asymmetry, and the epsilon == 0 semantics both helpers
used to refuse.
"""

import pytest

from core.bess.action_selector import Candidate
from core.bess.dp_battery_algorithm import PeriodFlows
from core.bess.tie_policy import TieContext, _eligible_indices, apply_tie_policy


def _candidate(value, power, next_soe, new_cost_basis, reward, grid_imported):
    """Build a `Candidate` from the positional layout these fixtures were
    written against, so the cases below stay literally what they were when
    the tie-breaks lived on 6-tuples.

    `grid_imported` now reaches the candidate inside its `PeriodFlows` record
    (Phase 3). The tie policy reads only that one flow, so the rest of the
    record is zeroed rather than invented -- these fixtures pin preference
    ordering, not physics."""
    return Candidate(
        power=power,
        next_soe=next_soe,
        reward=reward,
        new_cost_basis=new_cost_basis,
        flows=PeriodFlows(
            solar_to_battery=0.0,
            grid_to_battery=0.0,
            battery_charged=0.0,
            battery_discharged=0.0,
            grid_imported=grid_imported,
            grid_exported=0.0,
            clipped_solar=0.0,
            energy_stored=0.0,
        ),
        value=value,
    )


def _ctx(epsilon=0.01, home=0.25, solar=0.0, dt=0.25, floored=False):
    return TieContext(
        epsilon=epsilon,
        home_consumption=home,
        solar_production=solar,
        dt=dt,
        sell_price_floored=floored,
    )


# ---------------------------------------------------------------- row 3 (#466)

# Candidate fields: (value, power, next_soe, new_cost_basis, reward, grid_imported)
IDLE = _candidate(10.00, 0.0, 6.0, 0.0, 0.0, 0.25)
COVER = _candidate(9.995, -1.0, 5.74, 0.0, 0.25, 0.0)  # covers 1 kW net load
OVER = _candidate(9.999, -3.0, 5.21, 0.0, 0.30, 0.0)  # past load -> would export
CHARGE = _candidate(9.99, 2.0, 6.5, 0.0, -0.5, 0.75)


def _pick(candidates, argmax_index, **ctx_kwargs):
    return apply_tie_policy(candidates, argmax_index, _ctx(**ctx_kwargs))


def test_near_tied_idle_swaps_to_load_covering_discharge():
    candidates = [IDLE, COVER, OVER, CHARGE]
    # IDLE wins argmax; COVER is 0.005 behind, inside epsilon=0.01 -> swap.
    assert _pick(candidates, 0) == 1


def test_decisive_idle_margin_is_never_swapped():
    candidates = [IDLE, COVER, OVER, CHARGE]
    # COVER is 0.005 behind; with epsilon below that the hold is deliberate.
    assert _pick(candidates, 0, epsilon=0.004) == 0


def test_never_swaps_into_exporting_discharge():
    # Only the over-load discharge is within epsilon -> no eligible swap.
    candidates = [IDLE, _candidate(9.90, -1.0, 5.74, 0.0, 0.25, 0.0), OVER, CHARGE]
    assert _pick(candidates, 0) == 0


def test_only_exact_or_under_cover_is_eligible():
    # Eligibility ends exactly at the load-cover breakpoint (#497): any
    # overshooting candidate is either unexecutable (already excluded from
    # the action set before the table runs) or a genuine export -- never a
    # load-cover swap target, so there is no round-up allowance.
    # net load is 1.0 kW (home=0.25 kWh, dt=0.25h).
    idle = _candidate(10.00, 0.0, 6.0, 0.0, 0.0, 0.25)
    barely_over = _candidate(9.999, -1.001, 5.74, 0.0, 0.30, 0.0)
    exact_cover = _candidate(9.995, -1.0, 5.76, 0.0, 0.28, 0.0)

    assert _pick([idle, barely_over], 0) == 0, "any overshoot at all must not swap"
    assert _pick([idle, barely_over, exact_cover], 0) == 2, "exact cover may swap"


def test_charge_winner_is_untouched():
    candidates = [IDLE, COVER, OVER, CHARGE]
    assert _pick(candidates, 3) == 3


def test_no_net_load_means_no_swap():
    # Solar covers the house: net load <= 0, nothing to fail-safe.
    candidates = [IDLE, COVER, OVER, CHARGE]
    assert _pick(candidates, 0, home=0.10, solar=0.50) == 0


def test_picks_largest_eligible_coverage_among_ties():
    partial = _candidate(9.997, -0.5, 5.87, 0.0, 0.12, 0.12)  # covers half the load
    candidates = [IDLE, partial, COVER]
    # Both discharges are inside epsilon; the fuller cover (1.0 kW) wins.
    assert _pick(candidates, 0) == 2


def test_partial_cover_winner_is_improved_to_a_fuller_cover():
    # #512: which tied candidate the argmax returns is an enumeration-order
    # accident, so the table must fire on a partial-cover winner too, not
    # only on IDLE -- otherwise the swap is silently skipped and residual
    # import stays exposed.
    partial = _candidate(10.00, -0.5, 5.87, 0.0, 0.12, 0.12)
    full = _candidate(9.995, -1.0, 5.74, 0.0, 0.25, 0.0)
    assert _pick([partial, full], 0) == 1


def test_discharge_beyond_the_cover_is_left_alone():
    # A winner that already exports is a deliberate export, not a tie the
    # load-cover row is entitled to reinterpret.
    assert _pick([OVER, COVER, IDLE], 0) == 0


# ------------------------------------------------- row 4 (#510 curtailment)

HOLD = _candidate(10.0, 0.0, 12.0, 0.035, 0.0, 0.0)  # SOLAR_EXPORT bypass: SOE flat
ABSORB = _candidate(10.0, 0.0, 12.6, 0.035, 0.0, 0.0)  # IDLE: absorbs surplus
CHARGE_IMPORT = _candidate(9.999, 5.0, 13.25, 0.05, -0.1, 0.65)  # pulls grid
DISCHARGE = _candidate(9.99, -1.0, 11.7, 0.035, 0.2, 0.0)


def _pick_floored(candidates, argmax_index, epsilon=0.01):
    # home == solar: no net load, so row 3 stands down and row 4 is isolated.
    return apply_tie_policy(
        candidates,
        argmax_index,
        _ctx(epsilon=epsilon, home=0.0, solar=0.0, floored=True),
    )


def test_exact_tie_swaps_hold_to_highest_soe_absorb():
    candidates = [ABSORB, HOLD, CHARGE_IMPORT, DISCHARGE]
    # HOLD won the argmax on float noise; ABSORB is exactly tied -> swap.
    assert _pick_floored(candidates, 1) == 0


def test_never_swaps_into_grid_importing_charge():
    # CHARGE_IMPORT stores the most but pays the buy price for it -- the
    # morning failure mode (#269 comment: Meter 1 + charge 100% pulling
    # ~0.9 kW grid import during Storage). Row 1 makes it ineligible.
    assert _pick_floored([HOLD, CHARGE_IMPORT], 0) == 0


def test_decisive_hold_margin_is_never_swapped():
    low_absorb = _candidate(9.98, 0.0, 12.6, 0.035, 0.0, 0.0)
    # 0.02 behind with epsilon 0.01: the hold is deliberate arbitrage.
    assert _pick_floored([HOLD, low_absorb], 0) == 0


def test_discharge_winner_is_untouched():
    # A row 3 load-covering swap (or a genuine discharge argmax) must survive.
    assert _pick_floored([ABSORB, DISCHARGE], 1) == 1


def test_row_4_may_still_improve_a_charge_winner():
    # The row 3 / row 4 guard asymmetry, pinned: row 3 refuses to touch a
    # charge winner, row 4 may improve one to a larger absorb. Merging the
    # two guards into one shared "bail on any non-idle winner" would lose
    # this and re-open the hole #512 closed on the other side.
    small_charge = _candidate(10.0, 1.0, 12.2, 0.035, 0.0, 0.0)
    big_charge = _candidate(9.995, 2.0, 12.9, 0.035, 0.0, 0.0)
    assert _pick_floored([small_charge, big_charge], 0) == 1


def test_row_4_is_inert_when_the_sell_price_was_not_floored():
    candidates = [HOLD, ABSORB]
    assert apply_tie_policy(candidates, 0, _ctx(home=0.0, solar=0.0)) == 0


# ---------------------------------------------------- the two rows together


def test_row_3_swap_survives_row_4():
    # Row 3 turns an IDLE winner into a load cover; row 4 runs afterwards in
    # the same floored period and must leave that discharge alone. Under the
    # old chained helpers this held by guard-clause coincidence; here it is
    # row 4's stated guard.
    candidates = [IDLE, COVER, ABSORB]
    chosen = apply_tie_policy(
        candidates,
        0,
        _ctx(epsilon=0.01, home=0.25, solar=0.0, floored=True),
    )
    assert chosen == 1


def test_epsilon_band_is_measured_against_the_argmax_not_the_previous_row():
    """The band is anchored at the argmax: a candidate 1.5x epsilon behind
    it is ineligible even though it sits within epsilon of `near`.

    HONEST SCOPE (review finding): this pins the anchor, but it does NOT
    discriminate against the retired chained helpers -- they return the
    same index here, because with home == solar == 0 row 3 stands down and
    the chained anchor *is* the argmax.

    No end-to-end case can discriminate, and that is a property of the
    table rather than a gap in the fixture: row 3 returns either the argmax
    or a discharge, and row 4 returns immediately on a discharge winner, so
    the two anchors provably coincide whenever row 4 actually runs. (The
    Phase 2 measurement confirmed it empirically: 0 divergences across 2194
    selector calls.) Anchoring is therefore a structural guarantee that
    survives a future row being inserted, widened, or reordered -- none of
    which the chained arrangement would have survived -- not a behavior
    difference observable today.

    What IS discriminating is the direct assertion below: eligibility is
    computed from `argmax_index`, so re-pointing it at any other index
    fails here.
    """
    epsilon = 0.01
    winner = _candidate(10.0, 0.0, 12.0, 0.035, 0.0, 0.0)
    near = _candidate(10.0 - 0.9 * epsilon, 1.0, 12.4, 0.035, 0.0, 0.0)
    far = _candidate(10.0 - 1.5 * epsilon, 2.0, 12.9, 0.035, 0.0, 0.0)
    assert _pick_floored([winner, near, far], 0, epsilon=epsilon) == 1

    # Anchor pinned directly: measured from candidate 0 (the argmax), only
    # `winner` and `near` are within the band. Measured from `near` instead
    # -- the chained anchor -- `far` would also qualify.
    candidates = [winner, near, far]
    ctx = _ctx(epsilon=epsilon, home=0.0, solar=0.0, floored=True)
    assert _eligible_indices(candidates, 0, ctx) == [0, 1]


# ------------------------------------------------------- epsilon == 0 (P2)
#
# Both retired helpers returned early on `epsilon <= 0`, disabling tie
# resolution exactly where the value function is flattest -- the most
# degenerate tie there is. The table drops that early return. What replaces
# it is not a floor: at epsilon 0 the inclusive band admits *only* bit-exact
# ties, so a nonzero gap still ranks the candidates and the argmax stands.


def test_zero_epsilon_still_ranks_a_nonzero_gap():
    # COVER is 0.005 behind IDLE. That is a real ranking, not float noise,
    # and no epsilon floor exists to cross it.
    candidates = [IDLE, COVER, OVER, CHARGE]
    assert _pick(candidates, 0, epsilon=0.0) == 0


def test_zero_epsilon_resolves_a_bit_exact_tie_to_the_load_cover():
    # The DP's own objective declares these indistinguishable; the fail-safe
    # side wins for free (forfeiture exactly 0.0 SEK).
    tied_cover = _candidate(10.00, -1.0, 5.74, 0.0, 0.25, 0.0)
    assert _pick([IDLE, tied_cover], 0, epsilon=0.0) == 1


def test_zero_epsilon_resolves_a_bit_exact_curtailment_tie_to_charge_early():
    # Same for row 4: a floored sell price makes hold and absorb earn
    # literally the same reward, which is the exact-tie case #510 reported.
    assert _pick_floored([HOLD, ABSORB], 0, epsilon=0.0) == 1


@pytest.mark.parametrize("epsilon", [0.0, 0.01])
def test_a_decisive_winner_is_alone_in_the_eligible_set(epsilon):
    # ridax67's principle (#466), stated as a property: IDLE is emitted only
    # on a decisive margin. Anything more than epsilon behind cannot be
    # chosen by any row, at any epsilon.
    decisive_idle = _candidate(10.0, 0.0, 6.0, 0.0, 0.0, 0.25)
    behind = _candidate(10.0 - epsilon - 1e-6, -1.0, 5.74, 0.0, 0.25, 0.0)
    assert _pick([decisive_idle, behind], 0, epsilon=epsilon) == 0


# ---------------------------------------------------------------- row 5 (#606)

# Row 5 resolves what the objective cannot: candidates whose values are within
# VALUE_INDISTINGUISHABLE_SEK. Its discharge direction is covered end-to-end by
# test_tie_determinism.py against a real DP solve; the charge and idle
# directions and the class guard are NOT reachable from any corpus fixture (all
# 38 are byte-identical under the opposite charge ordering), so they are pinned
# here directly. Without these, an edit to the sort key or the class filter
# would change charge/idle tie-breaking with nothing to catch it.


def test_row5_prefers_the_largest_discharge_among_indistinguishable():
    big = _candidate(10.0, -3.0, 5.21, 0.0, 0.30, 0.0)
    small = _candidate(10.0 - 1e-13, -2.0, 5.50, 0.0, 0.30, 0.0)
    # No net load, so row 3 stands down and row 5 is what decides.
    assert _pick([small, big], 0, home=0.0, solar=0.0) == 1


def test_row5_prefers_the_largest_charge_among_indistinguishable():
    # The charge direction follows row 4's argument (absorb earliest at equal
    # model reward), not the discharge sign. Unreachable from the corpus.
    small = _candidate(10.0, 1.0, 6.25, 0.0, -0.25, 0.375)
    big = _candidate(10.0 - 1e-13, 3.0, 6.75, 0.0, -0.75, 0.375)
    assert _pick([small, big], 0, home=0.0, solar=0.0) == 1


def test_row5_never_changes_the_action_class():
    # The guard that makes this a tie-break rather than a re-decision. An
    # unrestricted "largest magnitude" would turn an IDLE winner into a full
    # discharge on a flat value function, and flip charge winners to
    # discharges -- both observed failing before the class filter existed.
    idle = _candidate(10.0, 0.0, 6.0, 0.0, 0.0, 0.25)
    tied_discharge = _candidate(10.0, -3.0, 5.21, 0.0, 0.30, 0.0)
    tied_charge = _candidate(10.0, 3.0, 6.75, 0.0, -0.75, 0.375)
    # Bit-exact ties in all three classes, no net load so row 3 stands down.
    assert _pick([idle, tied_discharge, tied_charge], 0, home=0.0, solar=0.0) == 0
    assert _pick([idle, tied_discharge, tied_charge], 1, home=0.0, solar=0.0) == 1
    assert _pick([idle, tied_discharge, tied_charge], 2, home=0.0, solar=0.0) == 2


def test_row5_breaks_an_equal_power_tie_by_index():
    # Totality: two candidates at the same power must not reopen the float gap.
    first = _candidate(10.0, -2.0, 5.50, 0.0, 0.30, 0.0)
    second = _candidate(10.0 - 1e-14, -2.0, 5.50, 0.0, 0.30, 0.0)
    assert _pick([first, second], 0, home=0.0, solar=0.0) == 0
    assert _pick([first, second], 1, home=0.0, solar=0.0) == 0


def test_row5_stands_down_outside_the_indistinguishable_band():
    # A gap the objective CAN see is a real ranking, not a tie. 1e-9 is far
    # inside epsilon, so the candidate stays eligible -- only row 5's own
    # 1e-12 band excludes it, which is the distinction being pinned.
    winner = _candidate(10.0, -2.0, 5.50, 0.0, 0.30, 0.0)
    bigger_but_worse = _candidate(10.0 - 1e-9, -3.0, 5.21, 0.0, 0.30, 0.0)
    assert _pick([winner, bigger_but_worse], 0, home=0.0, solar=0.0) == 0


def test_row5_does_not_overrule_an_earlier_rows_pick():
    # Row 3 swaps IDLE -> COVER; row 5 must not then pull it to the larger
    # OVER discharge, which row 3 deliberately refused as a genuine export.
    tied_over = _candidate(10.00, -3.0, 5.21, 0.0, 0.30, 0.0)
    assert _pick([IDLE, COVER, tied_over], 0) == 1
