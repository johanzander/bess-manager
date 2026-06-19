# Design: binary solar-surplus handling (store-all vs export-all)

**Date:** 2026-06-19
**Issue:** #145
**Depends on:** the closed-loop savings simulator (PR #144) — used as the acceptance gate.
**Supersedes:** #141 (the intent-dither hysteresis) if the dither dissolves.

## Problem

The optimizer over-credits solar export. Its reward model computes grid export from
an energy balance using the *planned* (possibly fractional) battery charge, and
credits export of the remainder. But the control applies a fixed `charge_rate =
100%` in storage periods, so the battery charges *all* available surplus up to its
rate — the "export the rest" the optimizer booked never happens. On the
reproduction day this is an **11.85% plan-vs-realized savings gap**, concentrated
in `SOLAR_STORAGE` periods (see #145 and the simulator finding doc).

## Why not the obvious "scale charge_rate to planned charge"

Two reasons (both decisive):

1. **Solar is a forecast.** Encoding a planned charge power into `charge_rate`
   chases noise — actual solar deviates more than the fractional amounts involved.
2. **`charge_rate = 100%` in storage periods is intentional and correct.** If the
   plan is "store, no export" and actual solar exceeds the forecast, the best
   outcome is to store the bonus, not export it. Scaling `charge_rate` down to the
   forecast would throw the bonus away.

## The model: a binary per-period choice for solar surplus

Each period, surplus solar (`solar − home − battery_charged_from_solar`) is handled
one of two ways, and the optimizer credits accordingly:

- **STORE** → `load_first`, `charge_rate = 100%`: store as much surplus as
  physically possible (`min(surplus, max_charge_rate, room)`); `load_first` exports
  only the genuine excess (above rate / when full). The optimizer credits **only
  that genuine excess** as export — never a planned fractional export.
- **EXPORT** → `grid_first`, `charge_rate = 0`: store nothing from solar; export all
  surplus; the battery may additionally discharge to grid (arbitrage). The optimizer
  credits the full surplus (plus any battery-to-grid) as export.

A single period is never "store a little **and** export a little" — that split is
what no real mode can deliver and is the source of the bug.

**Forecast-robustness falls out for free:** STORE periods stay at 100%, so whatever
actual solar arrives is captured (bonus = upside), and because the optimizer books
*no* phantom export in STORE periods, forecast error cannot create a fake-revenue
gap. EXPORT periods export whatever actual solar arrives (bonus = extra revenue).

Grid charging (`GRID_CHARGING` / `battery_first`, buying cheap grid energy) and
battery discharge for home/grid remain as today — those are already faithfully
controllable (discharge power is encoded via `discharge_rate`).

## DP design (the substantive change — to finalize in the plan)

The per-period decision must expose the STORE-vs-EXPORT disposition for surplus, and
the reward/flow model must compute flows + export credit from it.

**Recommended approach — disposition-aware flow model, minimal action-space change:**
Keep the existing power-level action enumeration, but reinterpret a *charging*
action as the **STORE disposition** (store all surplus up to rate; its exact
magnitude no longer matters) and a *non-charging* action in the presence of surplus
as the **EXPORT disposition**. Then in `_compute_reward` / `_state_transition`:
- STORE: `battery_charged = min(surplus, max_charge_rate·dt, room)`; surplus export =
  `max(0, surplus − battery_charged)`; credit that export only.
- EXPORT: `battery_charged_from_solar = 0`; surplus export = full surplus; battery
  may discharge to grid per the (encoded) discharge action; credit accordingly.

This collapses the charge side to effectively one "store-all" action, which is the
point — it removes the fractional charges that drive both the over-crediting and the
dither.

**Alternative considered:** add an explicit per-period boolean disposition to the
state/action tuple. Cleaner conceptually but a larger DP refactor; defer unless the
recommended approach proves awkward.

Either way: **export must be credited per disposition, not from a
disposition-agnostic energy balance.**

## Acceptance gate (the validation loop this enables)

1. **Implement** the change in the optimizer.
2. **Existing suite green** — `pytest -m "not slow"` and `-m slow`; no economic
   regression on planned-case scenarios (savings may *shift* to the correct lower
   number where phantom export is removed — that is expected and must be reviewed,
   not asserted unchanged).
3. **Simulator, same solar:** `verify_plan_faithfulness` gives **`R == P`** (cent-exact)
   on representative scenarios incl. the reproduction day — the plan is now faithfully
   executable.
4. **Simulator, more solar than planned:** a new harness optimizes with *forecast*
   solar and simulates with *higher actual* solar; assert the new implementation is
   **forecast-robust** (STORE captures the bonus with no phantom export; realized ≥
   planned), and A/B it against the old implementation to quantify the improvement.
   (`simulate()` already takes its own `solar_production`, so this only needs a
   harness that decouples forecast from actual.)

**Hard merge condition (financial safety):** ship **only if
`realized(new) ≥ realized(old)`** across the scenario set (same-solar *and*
more-solar-than-planned). The change must never reduce *realized* savings — the
reported (planned) savings dropping to the truthful, executable figure is expected
and is **not** a regression; a drop in *realized* savings **is**, and blocks merge.
This is the simulator-verified answer to "could the binary model cost money?" — it
cannot ship if it does.

## Relationship to #141

This addresses the **economic** root cause. If, as expected, binary dispositions
remove the morning fractional charges, the mode-dither dissolves and #141 (the
cosmetic hysteresis) becomes unnecessary — close it. If any cosmetic flicker
remains, it is then a genuinely separate, low-priority display concern.

## Open questions for the plan

1. Final action-space representation (recommended disposition-aware reinterpretation
   vs explicit boolean disposition).
2. Does `load_first` export excess **immediately** at the inverter, or only when the
   battery is full? (Confirmed: it exports excess — modes are priority orders. The
   flow model uses `export = max(0, surplus − stored)`.)
3. Terminal value and cost-basis interaction (expected unaffected; verify).
4. Whether grid-charge amount remains continuous (deliberate purchase) — expected yes.
