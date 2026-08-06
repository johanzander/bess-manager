# Design: Synthetic scenario validation for the #450 tie detector's coverage

**Date**: 2026-08-05
**Status**: IMPLEMENTED — see "Revision: short-segment reference" below; the
body of this document is the original proposal and is superseded in places
**Related**: #450, `docs/superpowers/specs/2026-08-04-hybrid-dp-pwl-tie-resolution-design.md`
(the hybrid fix this validates), PR #467.

## Revision: short-segment reference (post-implementation)

**Everything below this section is the design as originally PROPOSED. Three
of its decisions did not survive implementation.** The shipped code is
`core/bess/tests/synthetic/measure_tie_coverage.py` and
`core/bess/tests/unit/test_tie_detection_synthetic_coverage.py`; where this
document and those modules disagree, the modules are correct and their
docstrings carry the detail.

**1. The reference is a short padded segment, not the full horizon.** The
"full-horizon exact-PWL reference pinned to the DP's own final SOE" described
under *Architecture* and *The "true optimal" reference is an approximation*
is **abandoned as unreachable**, not merely approximated. The PWL solver's
breakpoint set compounds per backward step (it seeds every discharge preimage
of the next row's breakpoints), exhausting `PWL_MAX_PREIMAGE_SEED_POINTS` at
a horizon of ~8 periods on the #450 fixture — raising the budgets does not
buy a 78-period solve. Instead, `segment_reference_cost` re-solves exactly
the padded window `detect_tie_windows` *would* have built (pad 2, pinned by
`test_segment_padding_matches_the_detectors_own`) around the single period
that came closest to the detection threshold without crossing it. Side
benefit: measurement cost is independent of scenario length.

**2. The measured number is a LOWER BOUND, and not a proven optimum.** This
is the most important thing a reader must take from this revision:

- Both segment ends are pinned to the incumbent schedule's own SOE, so the
  reference cannot bank energy differently outside the segment. A better
  global plan that needs a different boundary SOE is out of reach by
  construction — the measured impact under-counts.
- The reference is only *what the PWL solver achieves*, not the true optimum.
  The solver is measurably suboptimal on real data (0.031 SEK worse than the
  grid DP on one pinned segment; pinned by
  `test_reference_can_undershoot_the_hybrid_a_known_solver_limitation`).
  A **positive** delta is therefore still a sound constructive witness (a
  concrete feasible schedule, replayed through the DP's own reward function,
  that costs less). A **negative** delta is solver noise and is floored at
  zero — never reported as a negative impact.
- The delta credits any grid-quantization gain within those periods, not the
  near-tie alone.

**3. Financial impact is measured on every scenario, not only zero-flag
ones.** The *Why only zero-flag scenarios get a financial-impact number*
section below no longer applies. Because the measured segment is built around
a period the detector explicitly did **not** flag (already-flagged periods
are excluded from selection in `near_miss_segment`), the conflation that
restriction was designed to avoid cannot arise — a flagged window elsewhere
in the same scenario does not contaminate this segment's delta. So the
measurement runs on every scenario that has a formable near-miss ratio.

**4. Infeasible scenarios are skipped individually, counted, and printed.**
The *Error handling* bullet "No silent skipping of hard scenarios" stands as
a principle but is stated too absolutely for what shipped. `regression_2026_
07_25_090230` starts below `min_soe_kwh` (a legitimate below-min recovery
state), and on some of its perturbations the near-miss segment's pinned end
SOE is still below the floor, which `segment_reference_cost` refuses to build
a terminal row for (`PWLEndSoeOutOfRangeError`). Those scenarios are caught
**by exception type**, appended to a list, and printed with their exact
parameters — skipped visibly, never silently — and the test asserts floors on
how many scenarios were actually measured (`_MIN_IMPACTS_MEASURED`) and
ceilings on how many were skipped (`_MAX_INFEASIBLE_SCENARIOS`) so a collapse
in coverage fails loudly instead of leaving the budget gate to pass on a
handful of survivors. Fixing the reference solver's handling of below-min
recovery trajectories is out of scope for this measurement-only suite.

**5. Objective mismatches fail loudly rather than being assumed away.** The
harness threads a single raw `sell_price` and `import_cap_kwh=None` into both
the exact solve and the replay. Export curtailment
(`_reject_unsupported_objective`) and a fixture-supplied grid import cap
(`_reject_unsupported_import_cap`) each raise `NotImplementedError` rather
than silently comparing two different objectives. Backing all of them,
`measure_scenario` asserts on every scenario that the replayed per-period
costs sum to the DP's own reported `reward_objective_cost` — the identity any
future unthreaded objective would break first.

**Calibrated outcome** (96 distinct scenarios: 4 fixtures × 3 price levels ×
2 volatility levels × 2 solar levels × 2 battery sizes, ~66s): 4 infeasible,
86 impacts measured, worst observed impact **0.017188 SEK**, enforced budget
`TIE_MISS_BUDGET_SEK = 0.05` (~3x margin).

---

## Why

PR #467's tie detector (`core/bess/tie_detection.py`) has a known, documented
limitation: its threshold (`TIE_NOISE_FACTOR = 0.1`) deliberately trades away
detecting some genuinely near-tied periods to avoid the catastrophic
over-triggering found during development (60-90% of periods flagged, ~400x
slowdown). The current calibration was tuned against the existing 34-fixture
regression suite — real historical/synthetic price-consumption traces, not
built to stress-test near-tie detection specifically — and validated only
against a *theoretical worst-case bound* on how often a miss could occur
(~10% of periods, per the k-sweep), not a measured real-world miss rate or
its actual financial severity.

The team does not want to rely on production bug reports surfacing this —
it requires a user (or a maintainer manually reviewing decisions, as Frank
currently does) to notice a subtly suboptimal schedule and report it, which
is exactly the kind of feedback loop this class of bug has already shown is
unreliable (issue #450 itself was one such report, discovered only because
it happened to be visible enough).

This design builds a permanent, CI-enforced synthetic scenario suite that
measures, with real numbers instead of a theoretical bound: across a
representative matrix of realistic conditions, how often does the current
calibration miss a genuine near-tie, and what is the real financial impact
(SEK) when it does. That evidence is then used to set a real, defensible
regression budget — not to guess at one.

## Approach: perturb existing fixtures, don't invent a synthetic price model

Rather than building a from-scratch synthetic price/consumption generator
(which would need its own validation against real Nordpool statistics to be
trustworthy), this suite generates variants by perturbing the 34 existing
fixtures already in `core/bess/tests/unit/data/`: scaling price level
(simulating winter-peak vs. summer-low), injecting seeded volatility jitter,
scaling/masking solar production, and overriding battery size. Every
generated scenario stays grounded in a real diurnal price shape and a real
consumption profile — only the parameters relevant to this investigation
move. This was chosen over a fully synthetic parametric generator
specifically to avoid the risk of measuring coverage against scenarios that
don't resemble reality and drawing false confidence from them.

## Architecture

```
Perturbed scenario generator                    (new, pure)
   base fixture (1 of 34) + seed + perturbation params
   → synthetic scenario (price/consumption/solar/battery)
        │
        ▼
Tie-coverage measurement harness                 (new)
   scenario → runs the hybrid optimize_battery_schedule
            → runs a full-horizon exact-PWL "true optimal" reference
              (only for scenarios where zero windows were flagged)
            → classifies every period by margin-to-noise-bound ratio
            → records the financial gap between the (unmodified) DP's
              cost and the true optimal, for zero-flag scenarios only
        │
        ▼
pytest test (new, under -m slow)
   runs the harness across a fixed, seeded set of perturbations
   asserts: no single scenario's "missed-tie financial impact" exceeds a
   budget; reports the margin-ratio distribution as diagnostic output
```

**Why only zero-flag scenarios get a financial-impact number**: a scenario
where the hybrid *did* flag and resolve some windows already has part of
its DP-vs-optimal gap closed by the windowed re-solve. Attributing the
remaining gap to "missed ties" in that case would conflate two different,
already-separately-documented phenomena — this suite's actual target (total
misses under current calibration) and the already-known windowing-coverage
limitation (partial windows recovering only part of the opportunity, a
separate parked follow-up from PR #467's final review). Restricting the
financial-impact measurement to scenarios with **zero** flagged windows
means the hybrid path is provably a no-op there (its cost equals the plain
grid DP's cost), so any gap to the true optimum is unambiguously the cost of
a complete miss.

## The "true optimal" reference is an approximation, by design choice

The windowed PWL solver (`core/bess/pwl_window_dp.py`) always requires a
pinned end-SOE to reconnect to the rest of the schedule — that's fundamental
to how windowing works. A true global-optimum reference for a whole scenario
shouldn't have its final SOE artificially pinned; it should be free, valued
by the same `terminal_value_per_kwh` model the grid DP itself uses.

**Decision**: approximate the reference by running the full-horizon PWL
solve pinned to whatever final SOE the grid DP itself already reached (the
same technique used ad hoc during the investigation that led to this
design). This reuses existing windowed-PWL machinery unchanged — no new
solver capability needed. It's a known, accepted approximation: if the true
optimum would also end at a *different* final SOE than the DP happened to
choose, this reference misses that effect. That's judged an acceptable,
narrow gap — near-tie bugs are about mid-schedule action choices, not
terminal SOE selection — rather than building free-terminal-SOE support
into the PWL solver as new, separately-verifiable scope.

## Components

**1. Perturbation generator** (`core/bess/tests/synthetic/perturb_scenario.py`)
— pure function:

```python
def perturb_scenario(
    base_fixture: dict, seed: int, params: PerturbationParams
) -> dict:
    ...
```

`PerturbationParams` (a frozen dataclass) covers:
- `price_level_multiplier: float` — scales buy/sell price series uniformly
  (simulates winter-peak vs. summer-low price levels).
- `volatility_jitter: float` — bounded random noise added to the price
  series, drawn from a `random.Random(seed)` instance seeded from the
  function's own `seed` parameter (never an unseeded global RNG or
  wall-clock time — determinism is required for CI reproducibility).
- `solar_scale: float` — multiplies solar production (0 = no solar, 1 =
  fixture's own, >1 = surplus).
- `battery_override: BatterySettings | None` — replaces the fixture's
  battery sizing (max SOE, max charge/discharge power) when set.

Deterministic given `(base_fixture, seed, params)` — identical inputs always
produce an identical scenario. Raises (does not silently clamp or skip) if
the resulting scenario is physically invalid — e.g. a battery override that
puts `initial_soe` above the new `max_soe_kwh`.

**2. Diagnostics hook on `optimize_battery_schedule`**
(`core/bess/dp_battery_algorithm.py`). The production function already
computes `tie_margins`, `value_slopes`, and flagged windows internally (per
PR #467's Tasks 2/3/8) and discards them after use. Add one optional
parameter:

```python
def optimize_battery_schedule(
    ...,
    tie_diagnostics: dict | None = None,
) -> OptimizationResult:
```

If the caller passes a mutable dict, the function fills it with the raw
per-period `tie_margins`, `value_slopes`, and the `windows` list before
returning. Normal production callers never pass this and see zero behavior
change — this is strictly additive, matching the same reuse pattern already
established for this branch's other diagnostics (the debug-level blind-spot
log line in `detect_tie_windows`). Chosen over monkeypatching internals in
the test harness, which would be fragile for a permanent, CI-enforced suite.

**3. Measurement harness** (`core/bess/tests/synthetic/measure_tie_coverage.py`):

```python
@dataclass(frozen=True)
class ScenarioMeasurement:
    margin_ratio_counts: dict[str, int]  # bucketed by ratio to noise bound
    financial_impact_sek: float | None  # only set for zero-flag scenarios

def measure_scenario(scenario: dict) -> ScenarioMeasurement:
    ...
```

Runs the hybrid path once via `optimize_battery_schedule(..., tie_diagnostics=diag)`,
classifies each period's margin against
`_epsilon_for_period`'s worst-case bound (`TIE_NOISE_FACTOR=1.0` equivalent)
into ratio buckets (e.g. `<0.1x`, `0.1x-0.5x`, `0.5x-1.0x`, `1.0x-2.0x`,
`>2.0x`), and — only when `diag["windows"]` is empty — runs the full-horizon
PWL reference (pinned to the DP's own final SOE, per the decision above) and
records `financial_impact_sek = hybrid_reward_objective_cost - true_optimal_reward_objective_cost`,
using the DP's real reward objective (not `battery_solar_cost`), consistent
with this branch's own established practice (see PR #467's final review
findings on the `battery_solar_cost` reporting-drift bug).

**4. The pytest test**
(`core/bess/tests/unit/test_tie_detection_synthetic_coverage.py`, marked
`@pytest.mark.slow`): iterates a fixed, version-controlled list of
`(base_fixture_name, seed, params)` tuples spanning the parameter matrix —
starting with a deliberate small grid (e.g. 3 price levels × 2 volatility
levels × 3 solar levels × 2 battery sizes × a few seeds each), sized to fit
comfortably within the existing slow suite's runtime budget. Asserts no
scenario's `financial_impact_sek` exceeds `TIE_MISS_BUDGET_SEK` (a module
constant). Always prints the aggregate margin-ratio distribution as a
diagnostic summary, regardless of pass/fail, so a maintainer investigating a
failure sees full context.

**5. Budget calibration is a two-step process**: implementation lands the
harness and test with the assertion initially disabled (or set to an
obviously-permissive placeholder), runs it to produce a report of the
actually-measured distribution and worst-case financial impacts observed
across the matrix. That report is reviewed with the project owner and used
to set `TIE_MISS_BUDGET_SEK` deliberately (e.g. "no worse than 2x the worst
impact observed"), at which point the assertion is enabled for real and the
suite becomes a genuine regression gate. This explicitly avoids picking an
arbitrary threshold before real data exists — the same mistake the original
theoretical-bound reasoning risked.

## Error handling

- Perturbation producing a physically invalid scenario raises at
  test-list-construction time (when the fixed tuple list is built), not
  inside the measurement loop — a bad parameter combination fails loudly at
  the specific tuple, not silently skipped.
- If measurement hits `PWLWindowUnderRefinedError` or any other raise from
  the hybrid path during a scenario run, it is **not caught** — that is a
  real finding (production code failing on a realistic-ish input) and must
  fail the test, surfacing exactly the kind of robustness gap this suite
  exists to find.
- No silent skipping of "hard" scenarios anywhere in this suite, per this
  project's no-silent-fallback rule.

## Testing (of the suite itself)

- `perturb_scenario`: unit tests for determinism (same seed → identical
  output byte-for-byte) and that each parameter independently moves only
  its intended quantity (price multiplier scales buy/sell and nothing else,
  solar scale scales only solar, etc.).
- `measure_scenario`'s margin-ratio classification: unit tested against
  hand-constructed margin/epsilon arrays with known expected bucket counts
  — a pure function, doesn't need a real DP run to test the classification
  logic itself.
- The full `test_tie_detection_synthetic_coverage.py` test is the
  integration test for the suite as a whole; separate unit coverage isn't
  needed beyond confirming it runs cleanly during the pre-budget-calibration
  phase (component 5's first step).

## Explicitly out of scope

- Free-terminal-SOE support in the PWL solver (see "true optimal reference"
  decision above) — the pinned-to-DP's-own-final-SOE approximation is used
  instead.
- Hand-constructed adversarial fixtures for specific scenario classes (e.g.
  a hand-engineered winter-peak discharge-vs-hold tie) — this design uses
  randomized perturbation sampling as the sole generation mechanism. Adding
  targeted hand-built pins later, if the sampled coverage turns out to have
  a real gap for a specific scenario class, is a natural, separately-scoped
  follow-up, not part of this suite.
- Raising `TIE_NOISE_FACTOR` itself, or adding a window-coverage/latency
  cap — both remain separate, already-identified follow-ups. This suite
  produces the evidence that would inform whether/how to do either; it does
  not implement either change itself.
