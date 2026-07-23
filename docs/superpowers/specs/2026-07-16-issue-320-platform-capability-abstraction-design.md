# Design: Platform-capability abstraction for discharge resolution, self-throttle modeling, and TOU-flip avoidance (#320)

**Date**: 2026-07-16
**Status**: Parts 1-2 (capability abstraction — sections 1-2 below) implemented
and shipped. Part 3 (TOU-flip debounce) is **deferred, not implemented** — see
"Part 3 status update" below; do not treat the debounce design in this doc as
current.
**Related**: #320 (this issue), #282 (postmortem — exact analytic breakpoints
broke plan-faithfulness, established today's percent-grid candidate search),
#240 (self-throttling reward fix — established `BATTERY_EXPORT_THRESHOLD_KWH`),
2026-07-12-dp-continuous-action-reformulation-design.md (investigated, not
implemented, continuous/piecewise-linear reformulation of the DP — a larger,
separate effort this design does not attempt), #313/#315 (unrelated defect
found during the same investigation that surfaced #320), #276/#285 (value-
function interpolation error investigation — ruled out for #313, referenced
here only as a reason to distrust small value differences near decision
boundaries without separate verification).

## Problem

`core/bess/dp_battery_algorithm.py` bakes two Growatt-MIN-specific hardware
behaviors directly into code that is meant to be platform-agnostic:

1. **Discharge candidate search** (`_discharge_candidates`) enumerates
   discharge magnitudes as integer percent (0-100) of
   `battery_settings.max_discharge_power_kw` — `rate_step =
   max_discharge_power_kw / 100` — on the stated assumption that hardware
   only accepts an integer percent rate. True for Growatt (both MIN and
   SPH), but SolaX's VPP path is watt-native and has no such constraint.
2. **Reward computation**'s self-throttle handling (`dp_battery_algorithm.py:509-520`)
   zeroes export credit for any discharge overshoot at or below
   `BATTERY_EXPORT_THRESHOLD_KWH` (0.01 kWh), because Growatt MIN's
   `load_first` mode physically cannot export a small overshoot past home
   consumption — it silently delivers only what the home needs. This is a
   real, correct model of `load_first` hardware behavior, but it is not a
   generic economic truth: a platform that always writes an exact watt
   target every period (SolaX) has no such self-throttle, and would
   genuinely export that overshoot.

Because (1) restricts the search to whole-percent steps, the DP occasionally
can't represent the exact discharge magnitude that would zero out grid
import/export (the "home-matching breakpoint"), and is forced onto a nearby
grid point that crosses `BATTERY_EXPORT_THRESHOLD_KWH` for a marginal
(often sub-cent) gain. Since `decision_intelligence.classify_strategic_intent`
uses that same threshold to decide `LOAD_SUPPORT` (`load_first`) vs
`BATTERY_EXPORT` (`grid_first`), and Growatt MIN writes a real TOU mode
segment per the classification, this produces frequent, real,
low-value-justified inverter mode flips: in the real trace analyzed for
#320, 62 of 129 periods (48%) classify as `BATTERY_EXPORT`, and 31 of those
62 (50%) export under 0.05 kWh — the same marginal character as the
motivating example (period 2026-07-14 01:00: DP's chosen 11% narrowly beats
the non-crossing 9% option by ~0.0001 in `reward + V`, both far below the
economically meaningful 9.2% exact match, which isn't representable on the
1%-of-max grid).

## Expected outcome

This design has two parts with very different risk/visibility profiles, and
it matters that they not be conflated:

- **Parts 1-2 (capability methods + DP parameterization) are a pure
  refactor.** No observable behavior changes for any currently-supported
  platform (Growatt MIN, Growatt SPH). Their entire value is architectural:
  the DP module no longer contains a hardcoded assumption about hardware
  resolution or self-throttle behavior, so a future platform (SolaX) can
  override either capability without touching `dp_battery_algorithm.py`
  again.
- **Part 3 (the TOU-flip debounce) is the actual behavior change, and the
  only part that resolves #320's reported symptom.** Concretely, on both
  `GrowattMinController` (cloud) and `SolaxModbusGrowattController` (local
  Modbus — Growatt MIN hardware, despite the name): an isolated
  `BATTERY_EXPORT`-classified period surrounded by `LOAD_SUPPORT`, exporting
  under **0.05 kWh** (matching the real trace's own definition of
  "marginal" — see Problem above), is folded into the surrounding
  `LOAD_SUPPORT` segment before either controller writes anything to
  hardware, so no TOU/mode change happens for it.

**Acceptance criteria** (verified in the implementation's TDD step against
the real fixture, `docs/bess-debug-2026-07-13-155212.md`): of the 62
`BATTERY_EXPORT`-classified periods in that trace, the 31 marginal ones
(`grid_exported < 0.05 kWh`) no longer produce a `grid_first` TOU segment;
the other 31 (genuine, larger exports) are unaffected. This is the number
that should visibly change when this ships — not a vaguer "should reduce
flips somewhat."

## Roadmap / next steps beyond this PR

This design deliberately does the minimum needed to (a) stop baking
Growatt-specific behavior into supposedly-generic code and (b) fix the
reported symptom, without picking up the larger items it makes possible.
Suggested order for follow-up work, each its own spec:

1. **SolaX capability overrides** — override `discharge_resolution_kw` and
   `self_throttle_export_threshold_kwh` on the SolaX controller to reflect
   its actual watt-native, no-self-throttle hardware. Cheap now that the
   injection points exist; blocked on nothing else in this list.
2. **SolaX modbus simulation** — `core/bess/simulation/inverter_simulator.py`
   currently only simulates Growatt MIN cloud TOU execution. Needed to
   validate (1) the same way Growatt MIN's plan-faithfulness is validated
   today. Depends on (1) existing so there's something platform-specific to
   simulate.
3. **Configurable/dynamic debounce tolerance** — 0.05 kWh is pinned as a
   concrete default here because it matches real evidence, but it's a fixed
   guess, not derived from an actual TOU-rewrite cost model, and there's no
   reason it should be identical for every battery size or user. Making it
   configurable (or deriving it from a real switching-cost estimate) is a
   reasonable follow-up once there's usage data on whether 0.05 kWh is
   actually the right cutoff in practice.
4. **Continuous/exact DP reformulation**
   (2026-07-12-dp-continuous-action-reformulation-design.md) — the
   long-term architectural direction (piecewise-linear breakpoint search
   instead of a percent grid), which would make the discharge-resolution
   capability largely moot for platforms that adopt it. Materially larger
   than everything above; not blocked by it, but also not worth starting
   until there's a concrete reason (e.g. a platform where 1%-of-max
   resolution is provably too coarse even with debounce in place).

## Non-goals

- Decoupling the DP's search *density* from `max_discharge_power_kw` for
  platforms where raw magnitude precision matters (e.g. giving SolaX finer
  resolution than Growatt's 1%) is out of scope. This design only removes
  the *hardcoding*; it does not change any platform's actual behavior
  today. SolaX's discretization override, and a SolaX simulation path to
  validate it, are separate future work.
- The continuous/exact-piecewise-linear DP reformulation
  (2026-07-12-dp-continuous-action-reformulation-design.md, Approaches 1/2)
  is a materially larger, separate effort. This design keeps the existing
  percent-grid-search structure and #282's plan-faithfulness guarantee
  entirely intact — it only parameterizes the constants that grid is built
  from.
- No change to Growatt SPH or SolaX (VPP) controller behavior. SPH already
  collapses `LOAD_SUPPORT`/`BATTERY_EXPORT` into one undifferentiated
  discharge block (`growatt_sph_controller.py:47-49`) — it has no per-period
  mode-flip cost to avoid. `SolaxController` (true SolaX VPP hardware) has
  no mode concept at all (`solax_controller.py`). Neither calls the debounce
  helper below — applying it there would suppress genuine marginal exports
  for no reason, since neither pays a TOU-rewrite cost. The TOU-flip
  debounce is scoped to the two controllers that share Growatt MIN's mode
  semantics: `GrowattMinController` (cloud) and `SolaxModbusGrowattController`
  (local Modbus — despite the name, this is Growatt MIN hardware, a subclass
  of `GrowattMinController`; "SolaX" here refers to the `solax_modbus` HACS
  integration used to reach it locally, not SolaX inverter hardware).

## Design

### 1. Platform capability methods on `InverterController`

Two new methods on the base class (`core/bess/inverter_controller.py`),
each with a default implementation equal to today's hardcoded Growatt
behavior — so this part of the change is behavior-preserving for every
existing platform and caller until a future platform overrides one:

```python
def discharge_resolution_kw(self, max_discharge_power_kw: float) -> float:
    """Smallest controllable discharge increment this platform can execute,
    in kW. Default: Growatt's integer-percent-of-max grid (1% steps)."""
    return max_discharge_power_kw / 100

@property
def self_throttle_export_threshold_kwh(self) -> float:
    """Discharge overshoot (kWh) below which this platform silently
    delivers only what the home needs rather than exporting the excess
    (Growatt MIN's `load_first` behavior, #240). Default: 0.01 kWh."""
    return 0.01
```

No subclass overrides either yet (SPH and SolaX inherit the Growatt
defaults unchanged — the SolaX-specific values are the explicitly
out-of-scope follow-up).

### 2. DP takes these as parameters, not constants

`_discharge_candidates(soe, battery_settings, dt, home_consumption,
solar_production, discharge_resolution_kw)` — replaces the inline
`rate_step = battery_settings.max_discharge_power_kw / 100` with the passed-in
value. All other logic (bounds, the Finding-5 breakpoint snapping, the
returned candidate set) is unchanged.

The reward function's self-throttle check
(`dp_battery_algorithm.py:519`, `if grid_exported <= BATTERY_EXPORT_THRESHOLD_KWH`)
takes `self_throttle_export_threshold_kwh` as a parameter instead of the
module-level `BATTERY_EXPORT_THRESHOLD_KWH` constant. The Finding-5
breakpoint computation (`export_starts_p = balance_zero_p +
BATTERY_EXPORT_THRESHOLD_KWH / dt`) uses the same passed-in value, so the
two stay in sync by construction (today's comment manually asserting they
must be kept in sync becomes structurally enforced instead).

`optimize_battery_schedule` and `_run_dynamic_programming`'s call chain gain
a `discharge_resolution_kw` and `self_throttle_export_threshold_kwh`
parameter (both optional, defaulting to today's literal values — `max_discharge_power_kw
/ 100` and `0.01` — so every existing caller that doesn't pass them, e.g.
tests, backtests, the simulator, is unaffected). `BatterySystemManager`
(which already holds `self.inverter_controller`) is the one production
caller updated to pass `self.inverter_controller.discharge_resolution_kw(...)`
and `self.inverter_controller.self_throttle_export_threshold_kwh` explicitly.

The backward DP pass (`_run_dynamic_programming`) itself is untouched — it
already uses a separate, platform-agnostic fixed grid
(`_discretize_state_action_space`, `POWER_STEP_KW`-based) to build `V`. Only
the Step 2 continuous-path reconstruction (`_best_action_at_continuous_state`,
which calls `_discharge_candidates`) and reward computation are affected.

### 3. TOU-flip debounce — one shared function, two call sites, two controllers excluded

The DP's `consider()` scoring (`dp_battery_algorithm.py:1043-1080`) is
**not** changed — it stays a plain, unbiased `value > best_value` comparison
over honest economic candidates. Introducing a bias there would conflate a
hardware-specific concern (TOU rewrite cost) with the DP's core economic
optimization, and there is no principled way to derive the "how much
economic value is a mode flip worth avoiding" tradeoff from inside the DP
without a real switching-cost model, which this design does not attempt.

Instead, the debounce operates once on the flat per-period intent sequence,
**before** either controller's TOU-writing mechanics ever see it — so
`_groups_to_tou_intervals` (`growatt_min_controller.py:224-241`, batch
9-segment grouping) needs no changes at all; it already just groups
whatever intent list it's handed. `SolaxModbusGrowattController.create_schedule`
(`solax_modbus_growatt_controller.py:61-100`) reads intents per-period live
via `apply_period` instead of grouping them, but consumes the same
pre-corrected list, so it too needs no bespoke logic — both controllers get
the fix by construction, not by two separate implementations of it.

**Data needed, and why the whole `PeriodData` struct, not just `grid_exported`:**
`optimize_battery_schedule`'s result already computes a full `list[PeriodData]`
per period (`dp_battery_algorithm.py:1114-1176` — `energy.grid_exported`,
`economic.export_revenue`/`hourly_cost`, `decision.strategic_intent`, all of
it). Today, `BatterySystemManager` discards all of this except
`strategic_intent` when building `DPSchedule.original_dp_results`
(`battery_system_manager.py:2209-2211`). Since it's already computed, this
design carries the existing `period_data` list through
`original_dp_results["period_data"]` instead of re-deriving a narrower
projection of it — this isn't speculative: Roadmap item 3 (a real
switching-cost model instead of a flat 0.05 kWh guess) would need exactly
this price/revenue data, and passing the full struct now avoids widening
this same plumbing a second time later for a follow-up we already know is
coming.

**The function itself**, a method on `GrowattMinController` (the common
ancestor of both controllers that share Growatt MIN's mode semantics):

```python
def _debounce_battery_export_flips(
    self, period_data: list[PeriodData], tolerance_kwh: float = TOU_FLIP_DEBOUNCE_KWH
) -> list[str]:
    """Fold isolated, marginal BATTERY_EXPORT periods back into LOAD_SUPPORT.

    An isolated single-period BATTERY_EXPORT surrounded by LOAD_SUPPORT on
    both sides, exporting under `tolerance_kwh`, is not worth the TOU
    rewrite it triggers. Returns a corrected strategic_intent list; input
    period_data is not mutated.
    """
```

Called once by each controller's `create_schedule`, immediately after
loading `strategic_intent`/`period_data` from `original_dp_results`, storing
the corrected list as `self.strategic_intents` — everything downstream
(grouping, live per-period apply) consumes the corrected list identically
to how it consumes the DP's raw output today. `TOU_FLIP_DEBOUNCE_KWH = 0.05`
(module constant, `growatt_min_controller.py`) matches the real trace's own
definition of "marginal" (31 of 62 `BATTERY_EXPORT` periods in the #320
trace export under this amount) — a fixed, hand-picked value, not a derived
switching-cost model; see Roadmap item 3. Runs longer than a single period
are explicitly not folded in this pass (a genuine multi-period export block
is not "isolated" by construction); if the real trace shows a short
multi-period marginal run that should also debounce, that's a reason to
revisit during implementation, not to silently widen scope here.

`GrowattSphController` and `SolaxController` do not call this method — see
Non-goals for why applying it there would be actively wrong, not merely
unnecessary.

## Part 3 status update (deferred during implementation)

Section 3 above assumed each of the 31 "marginal" `BATTERY_EXPORT` periods in
the real trace was an isolated single-period flip, bordered by `LOAD_SUPPORT`
on both sides. Implementation against the real fixture
(`core/bess/tests/unit/fixtures/issue_320_period_data.json`, added as part of
this work) disproved that assumption: the trace has only **7 contiguous
`BATTERY_EXPORT` runs total**, not 62 isolated flips. Only one run (periods
96-103, 8 periods) is wholly marginal — every period under 0.05 kWh, bordered
by `LOAD_SUPPORT` both sides. The other six runs mix marginal and clearly
substantial exports (e.g. 0.222, 0.234, 1.039 kWh) within the same contiguous
run — the "isolated single period" rule cannot touch these at all, and
folding individual marginal periods *inside* a mixed run would fragment one
continuous export block into several alternating `LOAD_SUPPORT`/
`BATTERY_EXPORT` sub-segments, which would *increase* TOU rewrites rather
than reduce them — the opposite of this section's goal.

**Decision:** Part 3 is deferred as its own follow-up, to be redesigned
against this real run structure (e.g. a "fold the whole run only if every
period in it is marginal" rule, or a different formulation entirely) rather
than the single-period assumption above. Parts 1-2 (the capability
abstraction — a pure, behavior-preserving refactor) are unaffected by this
and shipped independently; they do not depend on Part 3 in either direction.
An interactive explorer against the real trace, useful for prototyping the
next attempt, was built during this investigation — ask if you need it
reconstructed, it was not committed to the repo (a throwaway HTML artifact).

## Testing

- **Refactor-safety**: existing DP/scheduling tests must pass unchanged
  with the new parameters defaulted to today's literal values — this proves
  parts 1-2 are a pure refactor for every currently-supported platform.
- **Capability defaults**: a unit test asserting
  `InverterController.discharge_resolution_kw(5.0) == 0.05` and
  `self_throttle_export_threshold_kwh == 0.01` on the base class (and that
  `GrowattMinController`/`GrowattSphController` inherit them unchanged).
- **Debounce logic** (TDD against the real fixture,
  `docs/bess-debug-2026-07-13-155212.md`, full 129-period trace): a test
  constructing the real `PeriodData` sequence from the trace and asserting,
  per the Expected Outcome acceptance criteria above, that
  `_debounce_battery_export_flips` folds all 31 marginal
  (`grid_exported < 0.05 kWh`) `BATTERY_EXPORT` periods back to
  `LOAD_SUPPORT`, and leaves all 31 non-marginal `BATTERY_EXPORT` periods
  untouched. Run once against `GrowattMinController` and once against
  `SolaxModbusGrowattController` to confirm both consume the corrected list
  identically (inherited method, no per-controller logic to diverge).
- **Exclusion check**: a test asserting `GrowattSphController` and
  `SolaxController` schedules are unaffected by marginal-export periods in
  the same trace — i.e. confirming the debounce genuinely isn't invoked for
  either, not just that it happens not to change their output.
