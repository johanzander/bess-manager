# Design: Stop recreating InverterController every optimization cycle (#369)

**Date**: 2026-07-23
**Status**: Approved, not yet implemented
**Related**: #329 (VPP status/allow-AC-charging registers rewritten on every
schedule change — root cause of this refactor), #368 (merged band-aid fix:
`seed_from()`, carries hardware-derived state onto a freshly recreated
controller; this refactor makes it unnecessary and deletes it), #369 (this
issue).

## Problem

`BatterySystemManager._create_updated_schedule` builds a brand-new
`temp_growatt = self._create_inverter_controller()` every optimization
cycle, computes the candidate schedule into it via `create_schedule()`, then
either discards it or adopts it as `self._inverter_controller`. Each
`InverterController` subclass holds two kinds of state that don't belong in
the same object lifecycle:

1. **Hardware-observed/confirmed state** — genuinely persistent, tied to the
   physical inverter connection: `_vpp_status_confirmed`,
   `_last_written_vpp_remote_control`, `_last_written_vpp_power`,
   `_last_written_tou_mode`, `tou_intervals`, `_active_tou_intervals`.
2. **Per-cycle schedule content** — transient, meant to be recomputed fresh
   every cycle: `strategic_intents`, the computed TOU intervals for the new
   candidate schedule.

Because a fresh controller instance is built every cycle to get (2)
recomputed, (1) has to be explicitly copied forward or it silently resets to
its `__init__` default — the root cause of #329. #368 fixed the immediate
symptom with `seed_from()`, a per-field carry-forward list, but that list is
itself fragile: the pre-#368 version of this same carry-forward already
covered only TOU intervals, missing VPP fields added later and
`_last_written_tou_mode`; `seed_from` consolidates the list into one place
but doesn't stop it from silently drifting out of sync again the next time
a hardware-observed field is added.

Separately, `create_schedule`/`compare_schedules` (the abstract interface
every subclass implements) assume "schedule" means a persisted hardware
object — true for TOU/SPH, false for VPP/SolaX-style ephemeral control
(their own docstrings call it "SM-Ephemeral": no persistent schedule at
all, just per-period commands derived from the intent list on the fly).

## Expected outcome

- **No more controller recreation for schedule updates.** Each
  `InverterController` subclass becomes a single long-lived instance per
  platform selection — created once in `_create_inverter_controller`/
  `switch_inverter_platform`, reused for its entire lifetime. It is only
  ever recreated when the user changes platform/control mode (which
  already correctly does a full re-init including
  `read_and_initialize_from_hardware`).
- **`seed_from()` deleted entirely**, from the base class and all 4
  subclasses (`GrowattMinController`, `GrowattSphController`,
  `SolaxController`, `SolaxModbusGrowattController`). Nothing to carry
  forward if the object is never recreated — the bug class is structurally
  gone, not just made safer to extend.
- **Platform-neutral abstract interface**, renamed while already touching
  every subclass:
  - `create_schedule(schedule, current_period, previous_tou_intervals=None)`
    → `apply_intents(schedule, current_period)`. Drops
    `previous_tou_intervals`: confirmed dead in every subclass today (declared
    in each signature, never read in any method body — `SolaxController`'s
    and `SolaxModbusGrowattController`'s own docstrings already say
    "Unused"). Not a behavior change, just removing an unused parameter
    while the signature is already being touched.
  - `compare_schedules(other_schedule, from_period)` → `evaluate_intents(schedule,
    current_period) -> tuple[bool, str]`. Read-only: "would applying this
    differ from what's currently in effect," computed against `self`
    instead of a second controller instance.
  - `write_schedule_to_hardware(controller, effective_period, current_tou)`
    → `write_to_hardware(controller, effective_period, current_tou)` (minor,
    naming symmetry only).
  - `active_tou_intervals`, the `get_*_tou_*`/`log_*` display methods, and
    `read_and_initialize_from_hardware` are unchanged — already accurately
    scoped (genuinely TOU-specific, or already platform-neutral).
- **Single source of truth for "what would this schedule look like."** Each
  subclass gets a new private helper, `_build_candidate(schedule,
  current_period) -> CandidateT`, extracted from the guts of today's
  `create_schedule` (e.g. `GrowattMinController`'s period-grouping →
  TOU-interval building; a near-passthrough of `schedule.strategic_intents`
  for VPP/SolaX-style platforms). `_build_candidate` is pure — no mutation
  of `self`, no hardware calls. Both new public methods call it:
  - `apply_intents` calls `_build_candidate`, then assigns the result onto
    `self`'s fields (the commit/mutation) — same net effect as today's
    `create_schedule`, just always on the one persistent instance.
  - `evaluate_intents` calls the *same* `_build_candidate`, diffs the
    result against `self`'s currently-applied fields, returns `(differs,
    reason)`.

  Using one shared helper for both is the key point: it is the reason
  evaluate and commit can never silently drift apart, unlike two
  independently-maintained code paths (which is how the pre-#368 carry-
  forward bug, and #329 itself, kept recurring).

  Exception: `GrowattMinController`'s corruption detection (validates
  `self.tou_intervals`'s ordering, sets `self.corruption_detected = True` on
  failure) is a read-only check of `self`'s *current* state that lives
  naturally inside `_build_candidate` — it's a diagnostic status flag, not
  schedule content, so this one exception to "no mutation" is accepted as-is.

## BatterySystemManager call-site changes

- `_create_updated_schedule`: drops `temp_growatt` creation entirely. Still
  builds `temp_schedule: DPSchedule` exactly as today (controller-
  independent); returns just `temp_schedule` instead of a tuple. Also
  removes the `previous_tou` computation
  (`self._inverter_controller.active_tou_intervals.copy()`) that only
  existed to feed the now-dead `previous_tou_intervals` parameter.
- `_should_apply_schedule`: calls `self._inverter_controller.evaluate_intents(temp_schedule,
  from_period)` instead of `compare_schedules(other_schedule=temp_growatt,
  ...)`. The existing special-casing around it (`_hardware_write_pending`
  retry, `prepare_next_day`) is unchanged — that logic lives in
  `BatterySystemManager`, not the controller.
- `_apply_schedule`: drops its `temp_growatt` parameter. Reads
  `current_tou = self._inverter_controller.active_tou_intervals` (unchanged),
  calls `self._inverter_controller.apply_intents(temp_schedule,
  effective_period)` (mutates the one persistent instance in place),
  then `self._inverter_controller.write_to_hardware(self._controller,
  effective_period, current_tou)`. No more `self._inverter_controller =
  temp_growatt` swap — nothing to swap.
- The `should_apply=False` branch in `update_battery_schedule` (today:
  adopt `temp_growatt` for display purposes) becomes: update
  `self._current_schedule` and `self._inverter_controller.strategic_intents`
  directly — display data still refreshes every cycle, applied TOU/VPP
  state is left untouched.

## Testing & migration

- **Deleted**: `seed_from()` on all 4 subclasses + base class, and its
  tests (`TestSeedFromVpp`, `TestSeedFrom` from #368).
- **Rewritten**: any `TestCompareSchedules`-style test that constructs two
  controller instances and calls `compare_schedules(other)` is rewritten
  against `evaluate_intents(schedule, ...)` — one instance, a `DPSchedule`
  as the comparison input instead of a second controller.
- **New**: `_build_candidate` unit tests per subclass (pure function: given
  intents, what would the candidate look like — no mutation, no hardware
  calls), plus `evaluate_intents` correctly detecting "no change" when a
  schedule with identical intents is evaluated against the currently-
  applied one.
- **Regression coverage for the #329 bug class**: a test that calls
  `apply_intents` twice in a row on the *same* controller instance with
  unchanged intents, asserting zero hardware writes on the second call —
  trivial to prove now (no recreation involved at all), vs. #368's
  recreation-simulation gymnastics.
- **Full-suite risk**: this touches core scheduling for all 4 platforms, so
  both the fast and slow suites (all existing schedule/TOU/VPP tests) and
  the `min_schedule_e2e`/scenario tests must stay green — no scenario
  should produce a different *applied* schedule, only fewer redundant
  hardware writes.

## Also worth checking while in here (from #369)

Code review during #329 flagged `growatt_sph_controller.py`
(`_charge_periods`/`_discharge_periods`) and `solax_controller.py` as not
audited for the same carry-forward gap. This refactor covers all 4
subclasses in one pass (per explicit scope decision), so both are included
and the gap is closed by construction rather than needing a separate audit.

## Out of scope

- Renaming `DPSchedule` itself, or any of its fields — it is a genuinely
  universal "the optimizer's day-plan" concept across all platforms, not a
  misnomer.
- Any behavior change to what schedule gets applied or when — this is a
  pure architectural refactor. Acceptance criterion: identical applied
  schedules across all pinned scenario fixtures, only the redundant-write
  pattern changes.
