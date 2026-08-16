"""The single ordered preference table that resolves near-tied DP actions
(principle P2, `docs/agents/optimizer-architecture.md`).

Every near-tie the optimizer has ever mis-resolved was fixed by bolting one
more bespoke tie-break function onto the selection path (#466, #510, then #512
widening #466's guard). Each was individually correct and each narrowed the
next one's room: the two functions ran in a fixed order, the second measured
its epsilon band against the *first's* output rather than against the argmax,
and whether they could fight was a property of their guard clauses rather
than of a stated ordering. P2 replaces that with one table, applied once,
all rows measured against the argmax winner:

1. **Eligibility (import guard).** A candidate that imports more grid energy
   than the argmax winner is never preferred.
2. **Eligibility (within epsilon).** Only candidates the DP genuinely cannot
   rank -- inside `epsilon_for_period`'s value noise -- are eligible. A
   decisive winner (every alternative more than epsilon behind) is therefore
   alone in the set and no row can move it.
3. **Prefer the largest load-tracking discharge** up to the period's net
   load (#466).
4. **Prefer the highest-SOE candidate** when this period's sell price was
   floored by the #269 curtailment rule (#510).
5. **Break a value-indistinguishable tie canonically** -- when no row above
   fired and the objective cannot separate the candidates even to float
   precision, order them by action rather than by the float comparison
   (#606).
6. Otherwise the argmax winner stands.

Rows 3 and 4 keep their own, deliberately *different* winner guards -- see
their docstrings. A single shared "bail on any non-idle winner" guard cannot
express the asymmetry and would re-open the hole #512 closed.

Adding a new tie symptom's fix here means adding or reordering a row, with
its rationale and economic bound in the row's docstring. It does not mean a
new function on the selection path; `optimizer-architecture.md`'s compliance
check fails a PR that adds one.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.bess.dp_battery_algorithm import POWER_TOLERANCE_KW

if TYPE_CHECKING:  # circular at runtime: action_selector imports this module
    from core.bess.action_selector import Candidate

# Row 5's float-noise threshold (#606): two candidate values closer than this
# are the same number as far as the objective is concerned. Deliberately NOT
# an epsilon -- see `_row_canonical_among_indistinguishable` for why this does
# not breach P5, and why the epsilon-eligible set is the wrong band here.
VALUE_INDISTINGUISHABLE_SEK = 1e-12


@dataclass(frozen=True)
class TieContext:
    """Everything the table needs about the period being decided.

    `epsilon` comes from `tie_detection.epsilon_for_period` and nowhere else
    (P5) -- no row re-derives or hand-picks a SEK margin.

    The Phase 2 plan sketch also listed a `rate_step` field for a "+half a
    rate step" round-up allowance in row 3. That allowance no longer exists:
    #497 removed it, because every candidate overshooting the deficit by
    less than the export resolution is now excluded from the candidate set
    as unexecutable, and anything overshooting by more is a genuine export.
    Carrying the field would have implied a widening this table does not do.
    """

    epsilon: float
    home_consumption: float
    solar_production: float
    dt: float
    sell_price_floored: bool


def _eligible_indices(
    candidates: "list[Candidate]", argmax_index: int, ctx: TieContext
) -> list[int]:
    """Rows 1-2: the candidates any preference row is allowed to choose.

    **Row 1 -- never import more grid energy than the argmax winner.**
    Lifted out of the retired curtailment tie-break, where it kept the
    charge-early swap free: a candidate that stores more by *buying* the
    energy (the full-rate charge candidate inside a below-floor window) is
    never preferred over one that only absorbs surplus. Promoting it to a
    table-wide guard is a deliberate strengthening. It does bind on the
    load-cover row -- when the winner is itself a partial-cover discharge,
    a *smaller* within-epsilon discharge imports more than the winner and
    is excluded here (115 of 2194 selector calls across the fixture corpus
    have such a candidate) -- but it never changes that row's outcome,
    since row 3 only ever moves to a discharge at least as large as the
    winner's, which by construction imports no more. Do not read this row
    as inert for a future row: it is a live bound.

    Recorded foreclosure: in a negative-buy-price window a within-epsilon
    grid top-up is arguably the safer pick against a solar shortfall, and
    this row permanently bans it. That codifies today's behavior; an
    amendment relaxing it must cite this note and bring field evidence.

    **Row 2 -- within epsilon of the argmax value.** Measured once, against
    `candidates[argmax_index].value`, never against a previous row's output.

    Precision about what this fixes: the retired chained pair could not
    actually spend `2 * epsilon` in any reachable state --
    `_prefer_load_covering_discharge` returned either the argmax or a
    discharge, and `_prefer_curtailed_charge_absorb` returned immediately on
    a discharge winner, so the two bands could never compound. Anchoring
    every row at the argmax makes epsilon-compounding **unrepresentable
    rather than merely unreachable**: it survives inserting a row, widening
    an existing one, or reordering the table, none of which the old
    arrangement would have survived. This is not a record of a past
    miscomputation.

    The band is inclusive (`<= epsilon`), which is what makes the table live
    at `epsilon == 0`. Both retired tie-breaks returned early on a
    flat value function (dV/dSoE == 0 -> epsilon 0 -> no scale for "tied"),
    disabling tie resolution in exactly the most degenerate tie there is.
    At epsilon 0 an inclusive band admits only bit-exact ties -- candidates
    the DP's own objective declares indistinguishable -- and preferring the
    fail-safe side of a bit-exact tie forfeits exactly zero model value.
    Cycle cost already sits inside `_compute_reward`, so the preference is
    not spending wear it failed to price. No epsilon floor is introduced:
    a nonzero gap, however small, still ranks the candidates and the argmax
    winner stands.
    """
    winner = candidates[argmax_index]
    return [
        index
        for index, candidate in enumerate(candidates)
        if candidate.grid_imported <= winner.grid_imported + 1e-9
        and winner.value - candidate.value <= ctx.epsilon
    ]


def _row_load_covering_discharge(
    candidates: "list[Candidate]",
    eligible: list[int],
    argmax_index: int,
    ctx: TieContext,
) -> int:
    """Row 3 (#466): among the eligible candidates, prefer the largest
    discharge that covers no more than this period's forecast net load.

    Rationale (spec 2026-08-07-idle-tie-break-design.md): within epsilon --
    the value noise the DP's own SOE grid-snapping injects -- the DP cannot
    rank the options, but they are not symmetric in risk. A load-covering
    discharge fails safe: the inverter tracks *actual* load, absorbing a
    consumption forecast miss for free. IDLE fails unsafe: discharge is
    hard-disabled, so the entire miss is imported at the buy price. This is
    ridax67's principle in code -- IDLE must mean the optimizer WANTS to
    hold energy (a decisive margin), never that it merely EXPECTS balance
    (a coin flip). Deliberate arbitrage holds are untouched by construction:
    their margin over discharging exceeds epsilon, so nothing else is
    eligible.

    Eligibility is exact cover or under-cover only, with no round-up
    allowance (#497): every candidate overshooting the deficit by less than
    the export resolution was already excluded from the candidate set as
    unexecutable, and anything overshooting by more is a genuine export,
    never a load-cover swap target. Among eligible candidates the largest
    coverage wins -- fuller coverage means less residual import exposed to
    a miss.

    **Winner guard (row 2 of the plan's table, per-preference by design).**
    This row stands down on a *charge* winner and on a discharge already
    beyond the load cover; an IDLE winner or a *partial*-cover winner stays
    eligible so a partial cover can be improved to a fuller one. That last
    part is #512: which of several tied candidates `argmax` returns is an
    enumeration-order accident, and at the finer grid it started landing on
    partial covers, silently skipping the swap and leaving residual import
    exposed. Charge winners are never flipped to discharges -- a semantic
    change no phase has declared. Row 4's guard is deliberately different
    (it bails on discharge winners and may still improve a charge winner),
    which is why the two guards live on their rows instead of being merged.

    Economic bound: each swap forfeits at most `epsilon` (empirically
    ~0.003-0.015 SEK per period, and exactly 0 in the epsilon == 0 case row
    2 newly admits), but a single horizon can contain many swapped periods
    and the aggregate is bounded only empirically -- fixture evidence puts
    the worst observed full-horizon cost at +0.032 SEK, inside the #450
    budget of 0.05 SEK. Separately, for small net loads the eligibility band
    is wide in SEK/kWh terms, so swaps fire more often than #467's tie
    detector flags near-ties; deliberate, since every swapped candidate is
    within epsilon -- value noise, not a real gap -- of the argmax winner.
    """
    net_load_p = (ctx.home_consumption - ctx.solar_production) / ctx.dt
    if net_load_p <= POWER_TOLERANCE_KW:
        return argmax_index
    max_cover_p = net_load_p + 1e-9

    winner_power = candidates[argmax_index].power
    if winner_power > POWER_TOLERANCE_KW:
        return argmax_index
    if -winner_power > max_cover_p:
        return argmax_index

    chosen_index = argmax_index
    chosen_discharge_p = 0.0
    for index in eligible:
        discharge_p = -candidates[index].power
        if discharge_p <= POWER_TOLERANCE_KW or discharge_p > max_cover_p:
            continue
        if discharge_p > chosen_discharge_p:
            chosen_index = index
            chosen_discharge_p = discharge_p
    return chosen_index


def _row_stored_energy(
    candidates: "list[Candidate]",
    eligible: list[int],
    incoming_index: int,
    argmax_index: int,
) -> int:
    """Row 4 (#510): under the #269 curtailment sell-price floor, prefer the
    eligible candidate that stores the most energy.

    Rationale: flooring the sell price makes every below-floor export worth
    exactly 0, so whenever the remaining below-floor surplus exceeds the
    battery's headroom, "charge now, curtail later" and "curtail now, charge
    later" earn identical reward and the argmax picks between them on float
    noise. The options are not symmetric in reality: deferring actuates as
    charge-rate 0% + export-limit 0 (PV physically clipped to house load,
    above-forecast production wasted) and spends the plan's slack against a
    later solar shortfall before the next positive-price block. Charging
    earliest is stochastically dominant -- equal model reward, strictly
    better under forecast error in either direction.

    Row 1 is what keeps the swap free: a candidate that stores more by
    importing from the grid is not eligible in the first place.

    **Winner guard (per-preference, and deliberately not row 3's).** This row
    reorders hold-vs-store picks only, so it stands down on a discharge
    winner -- including a row 3 load-covering swap, which is why the two
    rows cannot fight -- but it may still improve a *charge* winner to a
    larger absorb. Note `incoming_index` rather than `argmax_index`: the
    guard reads the action chosen so far (row 3's output), while eligibility
    and the epsilon band stay anchored at the argmax. That is the whole of
    the ordering contract between the two rows.

    Economic bound: at most `epsilon` per period, and exactly 0 in the
    bit-exact-tie case this row's own reproduction fixture
    (`regression_2026_08_08_143843`) exhibits -- the tie there is exact by
    construction, since a floored sell price makes both options earn
    literally the same reward.
    """
    if candidates[incoming_index].power < -POWER_TOLERANCE_KW:
        return incoming_index

    # Baseline SOE comes from the ARGMAX, not from `incoming_index`. The
    # guard above is this row's only read of a previous row's output (see
    # the winner-guard note); seeding the comparison from it too would be
    # the one surviving piece of row-to-row chaining in a module whose
    # premise is that no row reads another's. Behaviour-identical today --
    # row 3 returns either the argmax or a discharge, and a discharge trips
    # the guard -- but inserting a row between 3 and 4, or widening row 3 to
    # return a non-discharge index, would silently re-anchor this row on
    # that row's output. Anchoring here makes the invariant hold by
    # construction instead of by a coincidence no test covers.
    chosen_index = argmax_index
    chosen_next_soe = candidates[argmax_index].next_soe
    for index in eligible:
        candidate = candidates[index]
        if candidate.power < -POWER_TOLERANCE_KW:
            continue
        if candidate.next_soe > chosen_next_soe + 1e-9:
            chosen_index = index
            chosen_next_soe = candidate.next_soe
    return chosen_index


def _action_class(power: float) -> int:
    """-1 discharge, 0 idle, +1 charge -- the same three-way split, drawn at
    the same `POWER_TOLERANCE_KW` deadband, that rows 3 and 4 use in their own
    winner guards. Row 5 reorders only within one class."""
    if power > POWER_TOLERANCE_KW:
        return 1
    if power < -POWER_TOLERANCE_KW:
        return -1
    return 0


def _row_canonical_among_indistinguishable(
    candidates: "list[Candidate]",
    eligible: list[int],
    incoming_index: int,
    argmax_index: int,
) -> int:
    """Row 5 (#606): when the objective cannot separate the candidates even to
    float precision, order them by action instead of by the float comparison.

    Rationale. Rows 3 and 4 answer "which of several near-tied actions is
    safer?". This row answers a different question: "when the DP is *exactly*
    indifferent, which action do we emit?" -- and before it existed the answer
    was whichever candidate happened to win a `>` comparison in
    `action_selector.select_action`'s argmax loop. That is the one row of the
    old table that was not a preference at all, but a deferral to the last bit
    of a float, and it is the P2 violation #606 reported.

    The degeneracy is structural, not incidental. Four consecutive 15-minute
    slots inside one hourly price block can be bit-identical in buy price, sell
    price, home consumption and solar; if all four are unconstrained battery
    export, the objective is *exactly* invariant to how a fixed total discharge
    is split across them, because only the sum reaches the next period. Every
    split is an optimum and the DP has no basis to prefer one -- so the choice
    fell to accumulated rounding in `V`, measured at 0.93 ULP on
    `regression_2026_08_13_145213` period 18. The two plans there cost
    bit-identically (`battery_solar_cost = -4.954319746390006` for both), and a
    one-ULP change to a single input swaps them. That is why this could differ
    between environments while every economic pin stayed green.

    **Canonical order: the most decisive action of the winner's own class
    (largest magnitude), then lowest candidate index.** Keyed on
    `candidate.power`, never on `candidate.value` -- the whole point is to
    stop reading a quantity whose last bits are noise. The index tiebreak
    makes the result total rather than merely deterministic, so two candidates
    at equal power cannot reopen the gap.

    "Largest magnitude" points the same way as the rest of the table in both
    directions, which is why it is stated as one rule rather than two. On a
    discharge winner it prefers the larger discharge: energy already delivered
    cannot be lost to a later forecast miss, and the alternative defers it to
    a slot the plan may not reach as modelled -- row 3's argument. On a charge
    winner it prefers the larger absorb, which is row 4's argument
    (charging earliest is stochastically dominant at equal model reward). On
    an idle winner every candidate has |power| <= POWER_TOLERANCE_KW and the
    index decides.

    Note the charge and idle directions are **not** exercised by the fixture
    corpus: measured 2026-08-16, this row and its `(power, index)` predecessor
    -- which ordered charge ties the opposite way, preferring the *smallest*
    absorb -- produce byte-identical output on all 38 fixtures, because no
    charge-class or idle-class multi-candidate tie occurs in any of them. The
    direction is therefore chosen for consistency with rows 3 and 4 rather
    than measured, and `test_tie_policy.py` pins it directly so a future edit
    to this key cannot change it unnoticed.

    **Why this needs its own threshold, and why that is not a P5 breach.**
    Eligibility (row 2) is an *economic* band: epsilon is the value noise the
    SOE grid injects, ~7.4e-4 SEK here, and it is `epsilon_for_period`'s to
    own. This row deliberately does not use it. Reordering the whole
    epsilon-eligible set is a real economic preference change -- measured
    across the corpus at 0.006-0.010 SEK per fixture on several fixtures --
    and #606 asked for no such thing. What this row reorders is only what the
    objective declares *indistinguishable*, which needs a float-noise
    threshold, not a SEK one. P5's "one epsilon, one owner" governs the
    economic margin; `VALUE_INDISTINGUISHABLE_SEK` is a statement about IEEE
    doubles, on a quantity whose own accumulated rounding is ~1 ULP (~1e-15
    at these magnitudes). It is ~1000x that noise floor and ~1e7 finer than
    the smallest genuine cost movement this corpus has recorded (0.0181 SEK),
    so nothing economically real can hide under it.

    That reconciliation is **not** settled here: `optimizer-architecture.md`
    names this band as P5's sole permitted exception, fixes its boundary (it
    decides no eligibility, only ordering within an eligible set epsilon has
    already fixed), and its compliance check fails a PR that widens it, reuses
    it for eligibility, or adds a third band. This docstring states the
    reasoning; that document is what a reviewer is entitled to read literally.

    Economic bound: zero in *model* value by construction -- the row only ever
    reorders candidates the objective cannot separate -- but not zero in
    realized cost, because an exact tie in *interpolated* value is not an
    exact tie in realized cost. The residual is grid-snapping interpolation
    error, the same noise epsilon exists for, and it goes both ways. Measured
    across the 38-fixture corpus 2026-08-16, 4 fixtures move:

        synthetic_clear_sky_ac_clipping     -0.03900 SEK  (12 periods)
        regression_2026_08_13_145213        +0.00000 SEK  ( 2 periods)
        realworld_2026_04_19_084608         +0.00000 SEK  ( 2 periods)
        regression_2026_08_08_143843        +0.00154 SEK  (11 periods)

    Net -0.03746 SEK. **The worst case is the +0.00154 SEK regression on
    `regression_2026_08_08_143843`** -- stated here and not only in that
    fixture's re-pinned `_note`, since a maintainer reading this row needs the
    bound, not the favourable half of it. Both extremes are inside the #450
    budget of 0.05 SEK per fixture. A fifth fixture,
    `realworld_2026_04_29_220919`, shifts 2.1e-12 SEK with its plan unchanged:
    the row picked an equal-power duplicate candidate, which is what the index
    tiebreak is for.

    **Winner guard, part 1 -- an earlier row's pick stands.** Rows 3 and 4
    stated a deliberate preference; this one must not overrule it. Hence
    `incoming_index`, and hence this row's position last in the table.

    **Winner guard, part 2 -- never change the action's class.** The row
    reorders only within the winner's own class (charge / idle / discharge),
    which is what keeps it a tie-*break* rather than a re-decision. Without
    this it is not a canonical ordering but a new preference, and a wrong one:
    on a flat continuation value function every candidate is a bit-exact tie,
    so an unrestricted "largest discharge" would turn IDLE into a full-rate
    discharge for no modelled gain (`test_pwl_window_dp.py::
    test_pwl_best_action_at_continuous_state_prefers_idle_when_flat_continuation`),
    and it would flip charge winners to discharges -- the semantic change row
    3's docstring records that no phase has declared
    (`test_tie_policy.py::test_charge_winner_is_untouched`). Both were
    observed failing before this guard existed. The class is exactly the one
    the rest of the table reasons in, so `POWER_TOLERANCE_KW` draws the
    boundary here too.
    """
    if incoming_index != argmax_index:
        return incoming_index

    winner = candidates[argmax_index]
    winner_class = _action_class(winner.power)
    tied = [
        index
        for index in eligible
        if winner.value - candidates[index].value <= VALUE_INDISTINGUISHABLE_SEK
        and _action_class(candidates[index].power) == winner_class
    ]
    return min(tied, key=lambda index: (-abs(candidates[index].power), index))


def apply_tie_policy(
    candidates: "list[Candidate]", argmax_index: int, ctx: TieContext
) -> int:
    """Resolve this period's near-tie: return the index of the action to
    emit, given the raw value argmax.

    The whole table, applied once. Rows 1-2 build the eligible set against
    the argmax winner; rows 3-4 pick within it in order; row 5 breaks a
    value-indistinguishable tie canonically when neither fired; if nothing
    fires, the argmax winner stands (row 6).

    Row 5 is last on purpose. It is the weakest claim in the table -- it
    applies only where the objective is exactly indifferent -- so any row
    with an actual economic or risk argument must get to speak first, and
    its winner guard makes that ordering explicit rather than incidental.
    """
    eligible = _eligible_indices(candidates, argmax_index, ctx)
    chosen_index = _row_load_covering_discharge(candidates, eligible, argmax_index, ctx)
    if ctx.sell_price_floored:
        chosen_index = _row_stored_energy(
            candidates, eligible, chosen_index, argmax_index
        )
    return _row_canonical_among_indistinguishable(
        candidates, eligible, chosen_index, argmax_index
    )
