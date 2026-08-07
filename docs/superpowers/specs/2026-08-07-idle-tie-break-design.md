# Risk-aware tie-break: IDLE vs load-covering discharge (#466)

**Date:** 2026-08-07
**Issue:** [#466](https://github.com/johanzander/bess-manager/issues/466)
**Related:** [#418](https://github.com/johanzander/bess-manager/issues/418) (parked, different layer),
[#485](https://github.com/johanzander/bess-manager/issues/485) (run-to-run hysteresis, separate),
[PR #467](https://github.com/johanzander/bess-manager/pull/467) (provides `tie_detection.epsilon_for_period`)
**Depends on:** #467 merged to main.

## Problem

The DP picks per-period actions purely on expected-value score. When IDLE and a
load-covering discharge (LOAD_SUPPORT) are near-tied, the winner is effectively
arbitrary — decided by whichever forecast was marginally more favorable at solve
time. But the two options are not symmetric in downside risk when the
consumption forecast is wrong:

- **LOAD_SUPPORT fails safe.** The inverter runs load-first with discharge
  enabled and tracks *actual* load up to its rate limit. A forecast miss (dinner
  at 19:15 instead of 18:45) is absorbed by the battery for free.
- **IDLE fails unsafe.** Discharge is hard-disabled at the inverter. A forecast
  miss during an IDLE period is bought from the grid at the full buy price, at
  exactly the moment the forecast was most wrong.

Real instance (ridax67, #466, 2026-08-06 bundle): 19:00 and 22:15 chosen IDLE
with a whole-day margin of ~1.7 öre over the discharge alternative; actual load
ran 0.8 kW against a 0.67 kW forecast, and the entire miss went to the grid.

Framing credit to ridax67: **IDLE should be chosen when the DP deliberately
wants to hold energy for a strictly better later use, not when it merely wins a
coin flip.** The DP can already distinguish the two: a deliberate hold has a
decisive `V(hold) − V(discharge)` margin; a coin flip has it within noise.

## Non-goals

- No forecast-uncertainty model or time-of-day variance heuristic (#418
  territory; data-gated, parked).
- No IDLE→export swap (exporting is not fail-safe) and no charge-side ties.
- No generic "preferred action" framework; scope is exactly IDLE vs
  load-covering discharge.
- No config knob.
- Not a fix for run-to-run plan churn — that is #485 (though determinism of
  this tie-break shrinks the churn population as a side effect).

## Design

### Mechanism

In the **forward extraction pass**, along the realized trajectory — the same
place #467's tie detection measures per-period margins — at each period whose
chosen action is IDLE:

1. Identify the best **load-covering discharge** candidate: discharge sized to
   forecast home consumption net of solar, subject to existing feasibility
   (reserve floor, rate limits) via the existing `_discharge_candidates`
   machinery. If no such candidate is feasible, the period is left as IDLE.
2. Compare total values from the DP's own tables: `V_idle` vs `V_discharge`.
3. If `V_idle − V_discharge < epsilon_for_period(value_slope, soe_step_kwh)`,
   swap the period to the discharge candidate. The trajectory continues from
   the swapped SOE, so downstream periods re-extract consistently.

Deliberate arbitrage holds are untouched by construction: holding for a
strictly better later sale carries a decisive margin and never falls inside the
epsilon.

The swap is deterministic — both sides of a 15-minute re-plan break the same
way — which independently reduces the near-tie flip-flopping that #485's
hysteresis has to absorb.

### Threshold

Reuse `epsilon_for_period(value_slope, soe_step_kwh)` from #467's
`tie_detection.py` (`TIE_NOISE_FACTOR × SOE_STEP_KWH × |dV/dSoE|`). Rationale:
within that band the DP's own snapped value table cannot rank the two options,
so the swap is free by the DP's own accounting, and the threshold definition
stays shared across #467 / #485 / this fix instead of introducing a new magic
constant.

**Validation gate (open risk):** `TIE_NOISE_FACTOR = 0.1` was calibrated for
detecting grid-snap misranking, and it is unverified whether ridax's actual
19:00/22:15 periods fall inside it. Implementation must replay the 2026-08-06
debug bundle from #466 and confirm those periods flip to LOAD_SUPPORT. If they
do not, stop and return with the measured margins; widening would then be a
deliberate, documented risk-premium threshold decision (escalated, not a
silently grown constant).

### Economic bound

This threshold is a per-period bound, not a horizon bound. Each swap forfeits
at most `epsilon` (empirically ~0.003-0.015 SEK), but a single horizon can
contain many swapped periods, and the aggregate cost is bounded only
empirically, not analytically per-horizon — fixture evidence puts the worst
observed full-horizon cost at +0.032 SEK, inside the #450 regression budget
of 0.05 SEK. Separately, for small net loads the eligibility band is wide in
SEK/kWh terms, so swaps fire more often than #467's tie detector flags
near-ties; this is deliberate, since every swapped candidate sits within
`epsilon` of the argmax winner and is therefore within value noise, not a
real gap.

## Testing

- **Unit, synthetic near-tie fixture:** IDLE and load-covering discharge within
  epsilon → discharge chosen; margin decisively favoring IDLE (arbitrage hold)
  → IDLE preserved.
- **Regression replay:** ridax's 2026-08-06 bundle through the canonical
  scenario harness (`test_scenarios.py` + expected_results); pin that the
  19:00/22:15-class periods extract as LOAD_SUPPORT. Verify the pin
  discriminates: it must fail against pre-fix code.
- **Existing suite green:** in particular the #450/#467 tie fixtures and the
  0.05 SEK regression budget — proving the swap never costs measurable EV.

## Issue hygiene

- **#466:** reply crediting ridax67's framing, link this design; the fix lands
  against this issue. No auto-close until graduation through beta.
- **#418:** cross-link comment; stays open and parked — it targets overnight
  floor breaches via the forecast *input*, a different layer, explicitly not
  superseded.
- **New issue:** consumption-statistics feedback loop (battery at floor →
  inverter asleep → its self-consumption unmeasured → HA-statistics night
  estimate degrades further → earlier drain next night). Filed as an unverified
  report with ridax67's mechanism, labeled needs-verification.
- **Sequencing:** implement only after PR #467 merges; this builds directly on
  `tie_detection.py`.
