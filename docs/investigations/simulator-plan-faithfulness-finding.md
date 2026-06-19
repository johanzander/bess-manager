# Finding: control layer does not faithfully realize the optimizer's plan (`R ≠ P`)

**Date:** 2026-06-19
**Surfaced by:** the closed-loop savings simulator (PR #144), first run.
**Status:** finding for review — **not resolved**. The intent-dither hysteresis
(PR #141) is **blocked pending a decision on this**, because it may be the deeper
root cause of the symptom #141 targets.

## What the simulator found

Running the simulator's plan-faithfulness check (`verify_plan_faithfulness`):
executing the control commands derived from the optimizer's own plan, on the same
scenario inputs, does **not** reproduce the planned economics.

- **Controlled 6-period scenario (Task 4 test):** `planned = −11.4888`,
  `realized = −11.3771`, gap **+0.11 SEK**, located entirely in the two
  `GRID_CHARGING` periods.
- **Full reproduction day (periods 21–95, terminal value 0.824):**
  `planned = −45.4995`, `realized = −40.1056`, gap **+5.39 SEK ≈ 11.85 % of
  planned savings**, concentrated in **`SOLAR_STORAGE`** periods (P36, P42–49 …).

So the simulator's central check (`R == P`) **fails**, and it localizes the
divergence precisely.

## Root cause: charge power is not encoded in the control command

The optimizer plans a specific battery **power** per period. The control layer
encodes that power for **discharge** but not for **charge**:

- `EXPORT_ARBITRAGE` scales `discharge_rate_pct` from the planned power
  (`InverterController._map_intent_to_rates`), so discharge is faithful — these
  periods show **zero** gap.
- `GRID_CHARGING` → `battery_first` and `SOLAR_STORAGE` → `load_first` charge at
  the **fixed default rate** (grid-charge on / store-all-surplus). The planned
  *partial* charge is lost; the inverter charges faster/more than planned,
  overshoots the SoE trajectory, stores solar that the plan intended to export,
  and realizes less savings.

This is the same mechanism behind the morning "dither": the optimizer plans
fine-grained partial solar storage (±0.1 kWh to hold near the floor / export
surplus), but `load_first` stores *all* surplus — the plan is not executable as
written.

## Important caveat — is this a real loss or a v1 model gap?

The simulator's `mode_to_power` is a **v1 model** of Growatt-MIN mode behaviour.
The `R ≠ P` gap is real **in the model**; whether it reflects a real on-hardware
savings loss depends on whether the model is faithful for the charging modes:

- If the real inverter under `load_first` / grid-charge genuinely stores all
  available surplus (no finer control than the TOU on/off + 100 % rate), then the
  ~11.85 % gap is a **real, previously-invisible loss** — the headline savings the
  optimizer reports are partly unrealizable.
- If the real system has additional charge-limiting control not yet modelled
  (e.g. the **power-monitor** path, or charge-rate scaling analogous to the
  discharge-rate scaling), then the gap is partly a **model-fidelity** artifact and
  the model must be extended before trusting the magnitude.

Resolving this requires either modelling the power-monitor/charge-rate path and
re-checking, or validating against measured hardware data (out of scope for v1).

## Why this blocks the hysteresis (#141)

PR #141 proposed a downstream hysteresis to stop the cosmetic mode flicker,
assuming the underlying plan was sound and only the *labels* churned. This finding
suggests the plan itself may **not be faithfully executable** in
`SOLAR_STORAGE`/charging periods — a more fundamental issue than label churn.
Stabilizing the labels would not address (and could mask) a real execution gap.
The right sequence is: decide on this finding first.

## Suggested next steps (for review)

1. Decide whether to extend `mode_to_power` to model charge-rate / power-monitor
   control, then re-measure `R` vs `P`.
2. If the gap persists with a faithful charge model, treat it as a real
   optimizer↔control contract bug: either the optimizer should plan only
   executable (mode-expressible) actions, or the control layer should encode
   planned charge power (charge-rate scaling, mirroring discharge).
3. Only then revisit #141 — the hysteresis may become unnecessary or change shape.

The simulator itself (PR #144) is complete and working: it did exactly its job —
surface, quantify, and localize a control-fidelity gap that no existing test could
see.
