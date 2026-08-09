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
5. Otherwise the argmax winner stands.

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
    `candidates[argmax_index].value`, never against a previous row's output:
    chaining let two rows spend up to `2 * epsilon` between them, which is
    the epsilon-compounding P2 exists to make unrepresentable.

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
    candidates: "list[Candidate]", eligible: list[int], incoming_index: int
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
    incoming = candidates[incoming_index]
    if incoming.power < -POWER_TOLERANCE_KW:
        return incoming_index

    chosen_index = incoming_index
    chosen_next_soe = incoming.next_soe
    for index in eligible:
        candidate = candidates[index]
        if candidate.power < -POWER_TOLERANCE_KW:
            continue
        if candidate.next_soe > chosen_next_soe + 1e-9:
            chosen_index = index
            chosen_next_soe = candidate.next_soe
    return chosen_index


def apply_tie_policy(
    candidates: "list[Candidate]", argmax_index: int, ctx: TieContext
) -> int:
    """Resolve this period's near-tie: return the index of the action to
    emit, given the raw value argmax.

    The whole table, applied once. Rows 1-2 build the eligible set against
    the argmax winner; rows 3-4 pick within it in order; if neither fires,
    the argmax winner stands (row 5).
    """
    eligible = _eligible_indices(candidates, argmax_index, ctx)
    chosen_index = _row_load_covering_discharge(candidates, eligible, argmax_index, ctx)
    if ctx.sell_price_floored:
        chosen_index = _row_stored_energy(candidates, eligible, chosen_index)
    return chosen_index
