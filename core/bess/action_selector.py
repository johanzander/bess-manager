"""The single candidate enumeration + evaluation + selection implementation
(principle P1, `docs/agents/optimizer-architecture.md`).

Every pass that has to *choose* a battery action calls `select_action`,
parameterized by a continuation-value evaluator `eval_V(next_soe)` and its
local slope: the grid DP's forward replay evaluates V by interpolating a
grid row, the PWL window's forward replay evaluates the same objective
against a piecewise-linear row. Nothing else differs between them, which is
why they were two hand-mirrored 200-line functions until Phase 1 of
`docs/superpowers/plans/2026-08-09-optimizer-target-architecture.md` --
kept in sync by "mirror" comments and by whoever remembered to read them.
Adding a candidate type, guard, cap or preference to one of those and
missing the other is the #236 bug class; here it is unrepresentable.

The two *backward* passes -- `dp_battery_algorithm._run_dynamic_programming`
and `pwl_window_dp._pwl_candidate_values_at` -- keep their own numpy
evaluators for speed (P1 permits this explicitly: they estimate V over a
whole state grid at once and never emit an action). They consume this
module's candidate-space definitions -- `_residual_cover_p`,
`_discharge_is_unexecutable`, `_solar_export_bypass_is_unexecutable` -- and
the platform lattice from
`execution_model.PlatformCapabilities` rather than restating them, so the
action space itself has one definition even where the evaluation loop does
not.
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from core.bess.dp_battery_algorithm import (
    POWER_TOLERANCE_KW,
    PeriodFlows,
    _ac_flows,
    _compute_reward,
    _effective_ac_cap_kwh,
    _soe_floor,
    _state_transition,
)
from core.bess.dp_constants import (
    POWER_CLASSIFICATION_THRESHOLD_KW,
    POWER_STEP_KW,
    SOE_STEP_KWH,
)
from core.bess.execution_model import (
    DEFAULT_CAPABILITIES,
    LATTICE_EPS,
    PlatformCapabilities,
)
from core.bess.models import GRID_FLOW_RESOLUTION_KWH
from core.bess.settings import BatterySettings
from core.bess.strategic_intent import FLOW_NOISE_FLOOR_KWH
from core.bess.tie_detection import epsilon_for_period
from core.bess.tie_policy import TieContext, apply_tie_policy


def _discharge_is_unexecutable(
    discharge_power_kw,
    home_consumption: float,
    solar_production: float,
    dt: float,
):
    """Is this discharge one no inverter can actually carry out as commanded?

    True when the commanded discharge overshoots the home deficit by less than
    `GRID_FLOW_RESOLUTION_KWH`. Such an action is unexecutable on every
    platform, for two different reasons that happen to coincide:

    - Load-following firmware simply throttles it back to the deficit
      (`inverter_simulator.mode_to_power`: `min(deficit, rate_kw * dt, ...)`),
      so the overshoot never leaves the property.
    - Hardware that would deliver it produces an export below the resolution
      of the energy counters that measure exports, so `EnergyData`'s noise
      fold (#350) attributes it back to the home regardless.

    Excluding these is the whole of the #497 fix. Proposing one anyway meant
    the DP priced an export that never happened and drew energy from the
    battery that never left it, emitting a period whose reported flows did not
    add up. Every earlier attempt patched a consequence instead -- #240 zeroed
    the export *credit* in the reward and left the *energy* overstated, which
    is precisely the band this predicate removes. Nothing downstream needs a
    threshold now, so none of them have to be kept in sync with each other.

    The lower boundary deliberately mirrors `EnergyData`'s fold condition
    (`battery_to_home > 0`, models.py): the band starts at any positive
    deficit at all, not at `POWER_TOLERANCE_KW` -- the fold has no such
    stand-down, so neither can this.

    The upper boundary is inclusive (`<=`) even though the fold's own bound
    is strict (`< GRID_FLOW_RESOLUTION_KWH`) -- deliberately, as float
    safety margin, not drift. At an overshoot of exactly the resolution the
    two sites compute the same physical quantity through different float
    paths (this predicate subtracts powers, the fold subtracts energies),
    and they can land on opposite sides of the boundary: measured on
    synthetic_seasonal_summer period 16, the DP saw overshoot 0.1 + 1e-16
    ("real export") while the fold saw battery_to_grid 0.1 - 2e-17 (folded
    to zero), yielding a period whose planned 0.16 SEK export revenue
    load-first execution never delivers. Excluding the exact boundary costs
    at most one marginal export candidate; admitting it re-opens the #497
    incoherence at float precision.

    Accepts a scalar or an array; returns the matching shape. Both the replay
    candidate set (`_discharge_candidates`) and the PWL window's feasibility
    mask (`pwl_window_dp._pwl_candidate_values_at`) route through here, so the
    two action-choosing passes cannot drift onto different action sets -- the
    failure mode `_backward_discharge_levels`' docstring warns about. The
    coarse-grid backward pass is the one deliberate exception: it only
    estimates V, never emits an action, and keeping in-band grid points there
    approximates the exact-cover breakpoint its lattice lacks -- see the
    comment at its feasibility mask in `_run_dynamic_programming`.
    """
    deficit_kw = (home_consumption - solar_production) / dt
    if deficit_kw <= 0.0:
        return np.zeros_like(discharge_power_kw, dtype=bool)
    return (discharge_power_kw > deficit_kw) & (
        discharge_power_kw <= deficit_kw + GRID_FLOW_RESOLUTION_KWH / dt
    )


def _solar_export_bypass_is_unexecutable(
    solar_production: float,
    home_consumption: float,
    battery_settings: BatterySettings,
    dt: float,
) -> bool:
    """Is the SOLAR_EXPORT-below-max bypass (#313) one no inverter can carry
    out as commanded this period? (#630)

    The bypass holds SoE exactly and lets the period's own solar surplus
    export instead of passively charging. Nothing commands that directly --
    it is delivered by `classify_strategic_intent` labelling the period
    SOLAR_EXPORT, which is the intent that writes charge rate 0 and so stops
    the inverter absorbing the surplus. That label needs
    `grid_exported > FLOW_NOISE_FLOOR_KWH`; at or below it the period falls
    through to IDLE, whose command is `load_first` at charge rate 100 --
    which absorbs. So the plan books export revenue on energy the hardware
    puts in the battery, and the battery runs fuller than planned until it
    hits a bound and spills the difference (#630: +0.0016 SEK over one
    quarterly day, from a single 0.0034 kWh surplus).

    This is the charge-side twin of `_residual_cover_p`'s first gate, which
    excludes discharges the same classifier would call IDLE (the #282 shape),
    and it gates on the same constant for the same reason -- one threshold,
    so the candidate space and the classifier cannot drift apart.

    Withholding the candidate is always safe: plain IDLE is offered
    unconditionally, and wherever the bypass diverts nothing (no surplus, or
    a battery already at `max_soe`) the two coincide exactly -- the same
    duplication `_tie_margin` already documents.

    Scalar per period, not per state: with no battery flow at all,
    `_ac_flows` reads only solar, load and the AC cap, so the export this
    candidate produces does not depend on SoE. The backward passes evaluate
    it once for the whole bypass column rather than per grid state.

    The AC cap is derived here rather than accepted as an argument, even
    though all three call sites already hold the identical value. That
    repeated call is deliberate, for the reason `_period_flows`' docstring
    gives: a cap passed in is a cap a caller can get wrong, and gating this
    candidate under a different cap than `_period_flows` prices it under is
    the reward-vs-flows divergence P4 exists to remove. One derivation per
    period is not a cost worth reopening that seam for.
    """
    _, grid_exported, _ = _ac_flows(
        solar_production,
        home_consumption,
        0.0,
        0.0,
        _effective_ac_cap_kwh(battery_settings, dt),
    )
    return grid_exported <= FLOW_NOISE_FLOOR_KWH


def _residual_cover_p(
    home_consumption: float,
    solar_production: float,
    dt: float,
    capabilities: PlatformCapabilities,
    battery_settings: BatterySettings,
) -> float | None:
    """Exact net-load residual as a discharge power (kW, positive) wherever
    the lattice cannot represent covering it exactly -- else None (#466
    sunrise crossover; generalized above the lattice by Phase 4b to close
    #352 Shape B).

    The percent lattice is coarse, and the net load almost never lands on
    it. Whenever it does not, no lattice action covers the house exactly:
    the step below under-covers and imports the difference at buy price,
    and every step above either is excluded by `_discharge_is_unexecutable`
    (#497) or exports for real at sell price. With buy > sell that is a
    forced loss in both directions, and which one the DP takes is decided
    by the tariff rather than by intent.

    On ceiling hardware the missing action is not merely desirable, it is
    directly commandable. `load_first` delivers `min(ceiling, actual load)`,
    so writing the smallest lattice step at or above the residual
    (`PlatformCapabilities.covering_ceiling_kw`) delivers the residual
    *exactly* (`inverter_simulator.py::mode_to_power`; VPP LOAD_SUPPORT is
    rate-less load-following, #413). The plan is the delivery; the command
    is on the lattice. That is what keeps exact plan-faithfulness, and it is
    why this is a candidate rather than a post-hoc demotion of the export.

    **This was previously offered only below the smallest lattice step**,
    which made it look like a narrow #466 special case. It was not: at
    `regression_2026_08_12_202906` period 99 the house needs 2.80 kW, the
    lattice offers 2.70 and 2.85, #497 removes 2.85/3.00/3.15, and the DP
    took 3.30 kW -- exporting 0.125 kWh, which classified the period
    BATTERY_EXPORT and wrote `grid_first` at a sub-load rate, forfeiting
    2.925 kWh of load-following headroom for 0.33 SEK. That is #352 Shape B,
    and it is what an absent candidate looks like from the outside. Removing
    the below-lattice restriction is the fix (design doc section 2, "the root
    cause is a missing candidate"); the DP is left to choose, and it chooses
    cover because cover is cheaper.

    Three executability gates, each verified against the execution path
    rather than assumed:

    - `residual * dt > FLOW_NOISE_FLOOR_KWH`:
      `classify_strategic_intent` labels a discharge LOAD_SUPPORT only above
      its `battery_discharged > 0.01` kWh noise floor -- at or below it the
      period classifies IDLE and the command mapper discharges nothing
      (R != P, the #282 failure shape).
    - `residual > POWER_CLASSIFICATION_THRESHOLD_KW`: the same classifier
      treats any *magnitude* at or below the threshold as noise, whatever
      its energy. This is stated directly now; before 4b it was enforced as
      a side effect of the nearest-rounding gate below, which rejected
      sub-half-step residuals because they wrote 0%.
    - a covering ceiling exists on this platform (`covering_ceiling_kw`).
      This replaces the old `residual <= round(residual / rate_step) *
      rate_step` gate, which existed because the write path rounded to
      nearest and a ceiling rounded *down* under-delivers the plan (repro:
      residual 0.12 kW -> 1% of 10 kW = 0.10 kW ceiling -> realized 0.10 for
      a planned 0.12). The write path now rounds ceilings up
      (`execution_model.command_index`), so the whole round-DOWN
      band is executable and the gate reduces to "is the ceiling
      commandable at all", i.e. at or below 100%. Rejecting 39% of the
      corpus's deficits was never the intent; it was the conversion's
      rounding direction showing through into the action space.

    **Only where a LOAD_SUPPORT discharge is actually delivered as
    `min(plan, actual load)`** (#580, Phase 4a). The paragraph above is the
    whole argument for this candidate: the plan is the *delivery*, and it is
    exact only if the hardware throttles to the real load. On native SolaX
    LOAD_SUPPORT is a forced `-(rate% x max_discharge)`, and on the
    period-list platforms (Growatt SPH, Solis, Huawei) there is no
    per-period control at all -- planning a partial cover there is planning
    a delivery that will not happen, the #282 shape. Before 4a the candidate
    was added unconditionally, which is what #580 records.

    Note this is `load_support_delivers_exact_cover`, **not**
    `discharge_rate_is_load_following`: on solax-modbus Growatt in VPP mode
    the rate register is a forced power, but LOAD_SUPPORT writes no rate --
    #413 releases the period to the inverter's own load-following self-use,
    so the cover is delivered exactly and the candidate belongs there.
    Gating on the register's semantics would have silently withdrawn #466's
    sunrise-crossover saving from that platform. Gated once, where the
    candidate is defined, rather than at each of the four call sites.
    """
    if not capabilities.load_support_delivers_exact_cover:
        return None
    residual_p = (home_consumption - solar_production) / dt
    if residual_p * dt <= FLOW_NOISE_FLOOR_KWH:
        return None
    if residual_p <= POWER_CLASSIFICATION_THRESHOLD_KW:
        return None
    if capabilities.covering_ceiling_kw(residual_p, battery_settings) is None:
        return None
    return residual_p


def _discharge_candidates(
    soe: float,
    battery_settings: BatterySettings,
    dt: float,
    home_consumption: float,
    solar_production: float,
    capabilities: PlatformCapabilities = DEFAULT_CAPABILITIES,
    ac_cap_kwh: float | None = None,
) -> list[float]:
    """Candidate discharge magnitudes (kW, positive) to evaluate for the
    single-period objective (reward + interpolated continuation value) --
    see docs/superpowers/specs/2026-07-12-dp-continuous-action-reformulation-design.md,
    Findings 1/2/3/5.

    Real hardware executes discharge as an integer percent (0-100) of
    `max_discharge_power_kw`
    (core/bess/simulation/inverter_simulator.py::_map_rates) -- it cannot
    apply an arbitrary continuous kW value. So the actually-achievable
    action space is that discrete percent grid, not the real line
    (postmortem, #282: an earlier version of this function returned exact
    analytic breakpoints like -7.505 kW out of a 10 kW max, which
    percent-rounds to 7.5 kW on real hardware -- a planned action execution
    silently can't reproduce, breaking plan-faithfulness/R==P). Enumerating
    that percent grid directly is both exact with respect to the true
    (discrete) action space and guarantees every candidate is executable
    exactly as planned.

    Second postmortem (#282): `classify_strategic_intent` treats any
    discharge magnitude at or below `POWER_CLASSIFICATION_THRESHOLD_KW`
    (derived from the fixed `POWER_STEP_KW`, not from
    `max_discharge_power_kw`) as noise, falling through to a different
    classification branch. That was safe by construction under the old
    fixed grid (smallest nonzero action, `POWER_STEP_KW`, always exceeded
    it), but 1% of `max_discharge_power_kw` can land at or below it for any
    battery with `max_discharge_power_kw <= 10 kW` -- so candidates at or
    below the threshold are excluded here too, not just candidates at or
    below zero.
    """
    available_energy = soe - battery_settings.min_soe_kwh
    p_max = min(
        battery_settings.max_discharge_power_kw,
        available_energy / dt * battery_settings.efficiency_discharge,
    )
    if ac_cap_kwh is not None:
        # Discharge shares the inverter's AC stage with PV conversion — see
        # the matching feasibility mask in _run_dynamic_programming.
        ac_headroom_kwh = max(0.0, ac_cap_kwh - min(solar_production, ac_cap_kwh))
        p_max = min(p_max, ac_headroom_kwh / dt)
    if p_max <= POWER_TOLERANCE_KW:
        return []

    rate_step = capabilities.discharge_rate_step_kw(battery_settings)
    max_pct = int(np.floor(p_max / rate_step + LATTICE_EPS))
    min_pct = capabilities.min_discharge_gear_index(battery_settings)
    if min_pct > max_pct:
        # No lattice candidate fits, but the off-lattice residual-cover
        # candidate (below) may still: a nearly-empty battery can be able to
        # cover a small net load while unable to sustain any percent-grid
        # discharge.
        #
        # The `cover_p <= p_max` check below is load-bearing here, not
        # belt-and-braces. Before 4b the cover candidate sat under the
        # smallest lattice power *by construction*, so feasibility followed
        # from the branch itself; now the residual can be any size and only
        # the explicit check keeps an infeasible one out.
        cover_p = _residual_cover_p(
            home_consumption, solar_production, dt, capabilities, battery_settings
        )
        if cover_p is not None and cover_p <= p_max:
            return [cover_p]
        return []
    candidates = {pct * rate_step for pct in range(min_pct, max_pct + 1)}

    # The largest step at or below the deficit is already in the enumeration
    # above, so dropping the unexecutable steps needs nothing added back: it
    # leaves as-exact-as-possible load cover the best available discharge, and
    # any surviving larger candidate exports enough to be real.
    #
    # Unconditional, with no "but keep one anyway if this empties the set"
    # carve-out. When the deficit is smaller than the smallest commandable
    # discharge, every discharge overshoots it and the honest answer is that
    # this hardware cannot serve that deficit from the battery -- so the DP
    # proposes none and the home imports it. An earlier draft kept the
    # smallest step in that case; it cost exact plan-faithfulness (one fixture
    # period, 0.0034 kWh) to save a fraction of an öre, and reintroduced the
    # asymmetry between this pass and the PWL window that the whole predicate
    # exists to prevent.
    executable = [
        p
        for p in candidates
        if not _discharge_is_unexecutable(p, home_consumption, solar_production, dt)
    ]

    # One deliberate off-lattice candidate: discharge exactly the forecast
    # net-load residual (#466 sunrise crossover; extended above the lattice
    # by 4b for #352). This is not the carve-out the paragraph above
    # rejects: that draft planned the smallest *step* and let the plan
    # overstate delivery by the overshoot, breaking exact plan-faithfulness.
    # This candidate plans the *delivery* itself -- load-first executes
    # `min(actual load, ceiling)`, so commanding the smallest step at or
    # above the deficit delivers exactly the deficit -- which is why R == P
    # holds exactly. See _residual_cover_p for the gates.
    cover_p = _residual_cover_p(
        home_consumption, solar_production, dt, capabilities, battery_settings
    )
    if cover_p is not None and cover_p <= p_max:
        # Only when it is not already one of the lattice steps. Since 4b the
        # residual can be any size, so a deficit landing exactly on the grid
        # makes cover_p a duplicate -- differing by float dust rather than
        # exactly (measured: 2.6999999999999997 against 2.7, 4.4e-16 apart),
        # which no set/`in` test would catch. A duplicate decides nothing
        # differently (the tie policy's dedup distance and its strict `>`
        # both absorb it) but costs a Candidate, a _compute_reward and an
        # eval_V per period, plus a state column in each backward pass.
        #
        # Compared in lattice-index units, which is what `LATTICE_EPS` is
        # defined in -- every other site divides by the step before applying
        # it. Comparing kW against it directly happens to work at today's
        # step sizes (the dust is ~4e-16, the tolerance 1e-9) but silently
        # scales with `rate_step`, which is the drift P5's one-owner rule
        # exists to stop.
        if not any(abs(p - cover_p) / rate_step <= LATTICE_EPS for p in executable):
            executable.append(cover_p)

    return sorted(executable)


def _charge_candidate(
    soe: float,
    battery_settings: BatterySettings,
    dt: float,
    period_max_charge: float | None,
) -> float | None:
    """The single representative STORE (charge) candidate power, or `None`
    if no genuine charge is possible -- see Finding 4 in
    docs/superpowers/specs/2026-07-12-dp-continuous-action-reformulation-design.md:
    any power above `POWER_TOLERANCE_KW` produces an identical reward
    (binary store physics; actual throughput is governed by
    `max_charge_power_kw`/solar/room, not the chosen power value), so a
    single feasible positive power fully represents the action.

    Same classification-threshold guard as `_discharge_candidates`: a
    candidate at or below `POWER_CLASSIFICATION_THRESHOLD_KW` would be
    misclassified as noise by `classify_strategic_intent` rather than as a
    genuine charge (reachable when very little room remains near a full
    battery), so treat that case as no charge available rather than
    returning a candidate the classifier can't recognize.
    """
    available_capacity = battery_settings.max_soe_kwh - soe
    max_charge_power = available_capacity / dt / battery_settings.efficiency_charge
    if period_max_charge is not None:
        max_charge_power = min(max_charge_power, period_max_charge)
    if max_charge_power <= POWER_CLASSIFICATION_THRESHOLD_KW:
        return None
    return min(POWER_STEP_KW, max_charge_power)


# Minimum SOE separation at which two candidate actions count as different
# *decisions* rather than two power levels of the same decision, when
# measuring how ambiguous a period's choice is (#450). See _tie_margin.
#
# This is a behavioural-DISTINCTNESS threshold, empirically calibrated --
# not a duplicate-removal tolerance, despite the duplicate candidates
# (IDLE vs the SOLAR_EXPORT-below-max bypass, which land on the identical
# next_soe) being what first exposed the problem. Removing literal
# duplicates needs only ~SOE_STEP_KWH; 1.0 kWh is 40x that (#512), and
# per the calibration sweep it is the DOMINANT lever on the trigger rate,
# not a safety margin around a smaller principled value. Sweeping it over
# 0.05 -> 1.5 kWh moves suite-wide flagging from 15.6% of periods to 0.4%.
#
# It is set where it is because #450's own reproduction fixture has its
# genuine alternative 1.25-1.5 kWh away from the chosen action's next_soe
# -- charging in a different window -- while the mass of spurious
# near-ties across every other fixture sits below 1 kWh, i.e. nudging the
# same plan's power level. #450's case is still caught the whole way up to
# 1.25 kWh, so 1.0 kWh keeps margin on both sides.
#
# Two consequences worth knowing before touching this:
#
# 1. It suppresses the charge side almost entirely. _charge_candidate
#    returns a single POWER_STEP_KW (0.1 kW) gradient probe, which moves
#    SOE by only ~0.025 kWh at dt=0.25h (~0.1 kWh at dt=1h) -- always well
#    under this threshold. So the charge candidate can essentially never
#    be the runner-up, and "charge now vs charge later" (the case the
#    _tie_margin docstring names as the target) can only register as a tie
#    when the CHOSEN action is a large discharge and the alternative is
#    the far-away no-discharge state, never when the chosen action is
#    itself a charge.
# 2. TODO: it is an absolute kWh figure that scales with neither battery
#    capacity nor dt. Every fixture in the suite uses a similar-sized
#    battery, so no test can catch this. On a much smaller battery (say
#    5 kWh usable) a 1.0 kWh separation is a fifth of the whole range and
#    the detector would likely go silent -- and silently, since a missed
#    tie reproduces #450's bug rather than raising. Making it relative to
#    usable capacity needs a fixture with a small battery to calibrate
#    against.
TIE_DEDUP_SOE_KWH = 1.0


@dataclass(frozen=True)
class Candidate:
    """One evaluated action at a state: what it does, where it lands, what it
    earns this period, and its total value including the continuation term.

    `flows` is this candidate's complete `PeriodFlows` record, produced once
    by the `_compute_reward` call that priced it (P4). Carrying the whole
    record rather than the single `grid_imported` scalar is what lets the
    reported `PeriodData` be built from the same physics the objective
    scored: the import-cap feasibility filter (#429), the "never prefer a
    candidate that imports more grid energy than the argmax winner"
    eligibility row in `tie_policy`, and the winning period's reporting all
    read this one record.
    """

    power: float  # kW, signed (+charge / -discharge / 0 idle)
    next_soe: float  # kWh
    reward: float  # this period's reward (currency)
    new_cost_basis: float
    flows: PeriodFlows
    value: float  # reward + eval_V(next_soe)

    @property
    def grid_imported(self) -> float:
        """kWh imported from the grid under this candidate."""
        return self.flows.grid_imported


def _tie_margin(candidates: list[Candidate], best_index: int) -> float:
    """Value gap between the chosen candidate and the best *behaviourally
    distinct* alternative (#450).

    `candidates` are the evaluated candidates built by `select_action`,
    already filtered against the import cap (#429) so every entry here is an
    action the house's fuse can actually support.

    A raw best-minus-second-best gap over the full candidate list is not a
    usable ambiguity signal, because several of those candidates are the
    same decision expressed twice:

    - IDLE and the SOLAR_EXPORT-below-max candidate coincide exactly
      whenever there is no solar surplus to route differently (both hold
      soe, both score identically) -- a margin of 0.0 that says nothing
      about ambiguity;
    - adjacent discharge breakpoints can sit a fraction of a grid step
      apart, which the grid DP's SOE_STEP_KWH-resolution value table cannot
      even distinguish.

    The alternatives that matter for #450 are ones landing at a materially
    different SOE -- e.g. charging in this window versus a later one. So a
    candidate only counts as a runner-up if its next_soe differs from the
    chosen candidate's by more than TIE_DEDUP_SOE_KWH.

    Returns float("inf") when no distinct alternative is feasible ("not
    tied, no comparison possible").
    """
    best = candidates[best_index]
    runner_up = float("-inf")
    for index, candidate in enumerate(candidates):
        if index == best_index:
            continue
        if abs(candidate.next_soe - best.next_soe) <= TIE_DEDUP_SOE_KWH:
            continue
        if candidate.value > runner_up:
            runner_up = candidate.value
    if runner_up == float("-inf"):
        return float("inf")
    return best.value - runner_up


@dataclass(frozen=True)
class PeriodInputs:
    """The horizon-level inputs a selection needs, bundled once per solve.

    Deviation from the Phase 1 plan's sketch, which described these as
    per-period scalars: `_compute_reward` takes the price *lists* plus a
    period index, so scalars here would mean either rebuilding throwaway
    lists per candidate or changing the physics core's signature -- a
    fifteen-call-site edit in a phase whose whole claim is that it changed
    nothing. The bundle is still built once per solve and indexed by `t`,
    which is what the plan was actually after. Converting `_compute_reward`
    to the scalar convention its vectorized twin `_compute_reward_grid`
    already uses belongs with a phase that is allowed to touch that
    signature.

    `sell_price` is the *reward-facing* series (#269 floors it to zero
    below the curtailment threshold); `sell_price_floored[t]` records where
    that floor was applied, which is what arms the charge-early tie-break.
    """

    buy_price: list[float]
    sell_price: list[float]
    home_consumption: list[float]
    solar_production: list[float]
    dt: float
    max_charge_power_per_period: list[float] | None = None
    import_cap_kwh: float | None = None
    capabilities: PlatformCapabilities = DEFAULT_CAPABILITIES
    sell_price_floored: list[bool] | None = None


@dataclass(frozen=True)
class SelectionResult:
    """What `select_action` decided, and the evidence behind it.

    `chosen` is post-tie-break; `argmax_index` is the raw value winner, and
    `tie_margin`/`value_slope` are measured there rather than at the chosen
    candidate. That split is deliberate (#466): tie detection (#450)
    measures the DP's own ambiguity at its value argmax, so a tie-break swap
    changes which action executes but must not itself register as a tie
    window.
    """

    chosen: Candidate
    candidates: list[Candidate]
    argmax_index: int
    chosen_index: int
    tie_margin: float
    value_slope: float


def select_action(
    soe: float,
    t: int,
    cost_basis: float,
    eval_V: Callable[[float], float],
    eval_value_slope: Callable[[float], float],
    period_inputs: PeriodInputs,
    battery_settings: BatterySettings,
) -> SelectionResult:
    """One-step Bellman recompute at a true continuous SoE: enumerate every
    executable candidate action, evaluate `reward + eval_V(next_soe)` for
    each, take the argmax, then apply the tie-breaks.

    `eval_V` is the continuation-value evaluator and `eval_value_slope` its
    local dV/dSoE -- the only thing that differs between the grid DP's
    forward replay (a linearly interpolated value-function row) and the PWL
    window's (a piecewise-linear row). Both are evaluated at a candidate's
    *true* continuous next_soe, never at one snapped to a grid index; that
    is the whole point of recomputing the action here instead of reading a
    policy table.

    Candidate actions are the exact breakpoints of the piecewise-linear
    reward+continuation objective (see
    docs/superpowers/specs/2026-07-12-dp-continuous-action-reformulation-design.md)
    rather than a fixed power grid.

    `period_inputs.import_cap_kwh` is the house fuse's per-period
    grid-import ceiling (#429): candidates are gathered first and filtered
    against it afterwards, so the cap's "constrain, don't raise" floor --
    the minimum grid_imported any candidate actually achieves -- is
    computable before anything is discarded.
    """
    period_max_charge = (
        period_inputs.max_charge_power_per_period[t]
        if period_inputs.max_charge_power_per_period is not None
        else None
    )
    dt = period_inputs.dt
    import_cap_kwh = period_inputs.import_cap_kwh
    home = period_inputs.home_consumption[t]
    solar = period_inputs.solar_production[t]
    ac_cap_kwh = _effective_ac_cap_kwh(battery_settings, dt)

    # Candidates are gathered first, then filtered against the import cap
    # (#429), so the cap's "constrain, don't raise" floor -- the minimum
    # grid_imported any candidate in this set actually achieves -- can be
    # computed before any candidate is discarded. They are appended in
    # consideration order so that exact value ties still resolve to the
    # first-considered candidate.
    candidates: list[Candidate] = []

    def consider(power: float, forced_next_soe: float | None = None) -> None:
        next_soe = (
            forced_next_soe
            if forced_next_soe is not None
            else _state_transition(
                soe,
                power,
                battery_settings,
                dt,
                solar_production=solar,
                home_consumption=home,
                ac_cap_kwh=ac_cap_kwh,
                import_cap_kwh=import_cap_kwh,
            )
        )
        # See _soe_floor's docstring (#233): the feasible floor for this
        # candidate is soe itself until real charging crosses back above
        # min_soe_kwh.
        if (
            next_soe < _soe_floor(soe, battery_settings)
            or next_soe > battery_settings.max_soe_kwh
        ):
            return
        reward, new_cost_basis, flows = _compute_reward(
            power=power,
            soe=soe,
            next_soe=next_soe,
            period=t,
            home_consumption=home,
            battery_settings=battery_settings,
            dt=dt,
            solar_production=solar,
            buy_price=period_inputs.buy_price,
            sell_price=period_inputs.sell_price,
            cost_basis=cost_basis,
            import_cap_kwh=import_cap_kwh,
        )
        candidates.append(
            Candidate(
                power=power,
                next_soe=next_soe,
                reward=reward,
                new_cost_basis=new_cost_basis,
                flows=flows,
                value=reward + eval_V(next_soe),
            )
        )

    # IDLE -- always a feasible candidate.
    consider(0.0)

    # SOLAR_EXPORT-below-max (#313): soe held exactly unchanged, this
    # period's own solar surplus exports directly instead of passively
    # charging -- see the backward passes' matching candidate for the full
    # rationale. Bypasses _state_transition (whose power=0 branch always
    # charges as much as room/rate permit) to force next_soe == soe
    # directly, then reuses the same _compute_reward call every other
    # candidate uses. Withheld where the classifier would call the period
    # IDLE rather than SOLAR_EXPORT, since nothing then commands the hold
    # (#630).
    if not _solar_export_bypass_is_unexecutable(solar, home, battery_settings, dt):
        consider(0.0, forced_next_soe=soe)

    # Discharge -- exact breakpoint enumeration (Finding 1/2/3/5).
    for p in _discharge_candidates(
        soe,
        battery_settings,
        dt,
        home,
        solar,
        capabilities=period_inputs.capabilities,
        ac_cap_kwh=ac_cap_kwh,
    ):
        consider(-p)

    # Charge (STORE) -- Finding 4: no grid search needed on this side at
    # all, a single representative candidate fully covers it.
    charge_candidate = _charge_candidate(soe, battery_settings, dt, period_max_charge)
    if charge_candidate is not None:
        consider(charge_candidate)

    # Import-cap filtering (#429) runs BEFORE the argmax and before the tie
    # margin is measured: a candidate the fuse cannot actually support is not
    # a runner-up, so letting it into _tie_margin would report ambiguity
    # against an action that was never on the table.
    if import_cap_kwh is not None and candidates:
        floor_grid_imported = min(c.grid_imported for c in candidates)
        effective_import_cap = max(import_cap_kwh, floor_grid_imported)
        candidates = [
            c for c in candidates if c.grid_imported <= effective_import_cap + 1e-9
        ]

    # Plain IDLE is offered unconditionally and holds soe within bounds at
    # every state, so it is always feasible, and the import-cap filter above
    # cannot empty a non-empty list (its threshold is floored at the minimum
    # grid_imported any candidate achieves, so that candidate always
    # survives) -- `candidates` is never empty and an IndexError below would
    # be a real bug, not a case to defend against.
    #
    # This used to name the SOLAR_EXPORT-below-max candidate instead. That
    # stopped being the guarantee when #630 made the bypass conditional; IDLE
    # is the unconditional one, and always was.
    argmax_index = 0
    best_value = float("-inf")
    for index, candidate in enumerate(candidates):
        if candidate.value > best_value:
            best_value = candidate.value
            argmax_index = index

    # The one ordered preference table (P2, tie_policy.py) -- the single
    # place near-tie resolution happens. Epsilon uses the slope at the
    # argmax winner's next_soe, the same state the margin itself is
    # measured at, and every table row is measured against that winner.
    value_slope = eval_value_slope(candidates[argmax_index].next_soe)
    epsilon = epsilon_for_period(value_slope, SOE_STEP_KWH)
    chosen_index = apply_tie_policy(
        candidates,
        argmax_index,
        TieContext(
            epsilon=epsilon,
            home_consumption=home,
            solar_production=solar,
            dt=dt,
            sell_price_floored=(
                period_inputs.sell_price_floored is not None
                and period_inputs.sell_price_floored[t]
            ),
        ),
    )

    return SelectionResult(
        chosen=candidates[chosen_index],
        candidates=candidates,
        argmax_index=argmax_index,
        chosen_index=chosen_index,
        tie_margin=_tie_margin(candidates, argmax_index),
        value_slope=value_slope,
    )
