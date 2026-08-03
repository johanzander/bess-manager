# Control-model-aware schedule display (issue #415 generalization)

## Problem

Issue #415: the Schedule Overview table shows `Mode = Load First` for a
`SOLAR_EXPORT` period on a Growatt inverter running `control_mode="vpp"`
(via `solax_modbus`), but the actual hardware behavior is a grid-first-style
hold (`power=0%`, `remote_control=True`), confirmed against
`_intent_to_vpp()` (`core/bess/solax_modbus_growatt_controller.py:300-340`).

Root cause is structural, not Growatt-specific. `INTENT_TO_MODE`
(`core/bess/inverter_controller.py:60-67`) is a static
`load_first`/`battery_first`/`grid_first` lookup table built for genuine
TOU/register hardware. `get_period_settings()` /
`get_all_tou_segments()` apply it unconditionally across every
`InverterController` subclass. A survey of all six concrete controllers
found only two actually write real TOU-mode registers; the other four
synthesize a `batt_mode` value purely for API/display consistency,
ranging from "wrong for one specific intent" (VPP) to "static stub that
never varies" (period-list controllers):

| Controller | Real hardware model | `batt_mode` today |
|---|---|---|
| `GrowattMinController` | TOU registers (real slots) | Accurate |
| `SolaxModbusGrowattController`, `control_mode="tou"` | TOU register (single slot) | Accurate |
| `SolaxModbusGrowattController`, `control_mode="vpp"` | VPP power + remote_control | **Wrong for SOLAR_EXPORT** |
| `SolaxController` (native SolaX) | VPP power + remote_control | Fictional (same bug, same code shape) |
| `GrowattSphController` | Charge/discharge period-list | Static stub `"load_first"` |
| `SolisModbusController` | Charge/discharge period-list | Static stub `"load_first"` |
| `HuaweiController` | Charge/discharge period-list | Approximated from charge/discharge sign |

## Goals

- Fix the display for all six controllers, not just Growatt VPP, using one
  generic mechanism rather than per-controller patches.
- Never fabricate a mode label that doesn't correspond to real hardware
  behavior.
- Keep `strategic_intent` as the one control-model-agnostic signal already
  threaded through the system (DP schedule → controller → API → frontend
  intent badges) — no new intent-like concept needed.

## Non-goals

- No change to optimizer/DP logic, `INTENT_TO_CONTROL`, or actual hardware
  write behavior (`_intent_to_vpp`, TOU segment writes, period-list writes)
  — this is a display/API-shape fix only.
- No data migration — nothing persisted changes shape, only the live API
  response and its renderers.

## Design

### 1. `CONTROL_MODEL` classification (backend)

Add a classification to `InverterController` with three values:

- **`tou_register`** — `GrowattMinController`; `SolaxModbusGrowattController`
  when `control_mode == "tou"`. Real TOU-mode register exists;
  `batt_mode` stays as-is (`INTENT_TO_MODE` lookup, unconditional).
- **`vpp_power`** — `SolaxModbusGrowattController` when
  `control_mode == "vpp"`; `SolaxController`. No persistent mode register;
  actual behavior is (`power_pct`, `remote_control_enabled`) per period.
  `batt_mode` is **omitted**; `vpp_power_pct` (signed int) and
  `vpp_remote_control` (bool) are returned instead, computed via
  `_intent_to_vpp()`.
- **`period_list`** — `GrowattSphController`, `SolisModbusController`,
  `HuaweiController`. No per-period mode or power value exists; `batt_mode`
  is **omitted** with no numeric replacement — `strategic_intent` is the
  only per-period signal for these platforms.

`SolaxModbusGrowattController` is dual-mode, so `CONTROL_MODEL` is a
`@property` there (`"vpp_power" if self.control_mode == "vpp" else
"tou_register"`); a plain `ClassVar[str]` on the other five.

**Correction from initial draft**: `_intent_to_vpp()` is *not* shared
between `SolaxModbusGrowattController` and `SolaxController` today, and
must not be hoisted into one implementation. Verified by reading both:
`SolaxController._write_period_to_hardware()`
(`core/bess/solax_controller.py:104-151`) derives its power target from
`(grid_charge, discharge_rate)` alone, ignoring `block_passive_charging`
and `strategic_intent` entirely — it never received the #355 SOLAR_EXPORT
grid-first-hold fix or the #413 LOAD_SUPPORT remote-control-release fix
that `SolaxModbusGrowattController._intent_to_vpp()`
(`core/bess/solax_modbus_growatt_controller.py:298-340`) has. SolaX's own
docstring already flags the SOLAR_EXPORT gap as known and unverified on
real hardware. These are two inverters with genuinely different actual
firmware behavior for the same strategic intent today — unifying them
would either misrepresent SolaX's real (weaker) behavior or silently
change what gets written to SolaX hardware, both of which violate the
non-goal of a display-only, hardware-behavior-preserving change. Tracked
as a separate future TODO item (see TODO.md, "SolaxController VPP
behavior has fallen behind SolaxModbusGrowattController's VPP fixes").

Instead, each `vpp_power` controller keeps its own method computing
`(power_pct, remote_control_enabled)` for display, mirroring its own
actual `_write_period_to_hardware()` logic exactly:
`SolaxModbusGrowattController` reuses its existing `_intent_to_vpp()`
unchanged; `SolaxController` gets a new method with the same
`(power_pct, remote_control_enabled)` shape but SolaX's own (simpler,
`block_passive_charging`/`strategic_intent`-blind) logic. Both are
exposed to the frontend through the same `vpp_power_pct` /
`vpp_remote_control` API field names — the fields are shape-shared, the
computation is not. This also satisfies the transparency goal: each
platform's display reflects what it actually does, divergence included,
rather than a unified fiction.

**Second correction**: the Schedule Overview table in issue #415's
screenshot is *not* fed by `get_all_tou_segments()` at all — it's fed by
`get_detailed_period_groups()` (`core/bess/inverter_controller.py:635-760`,
also defined once on the base class, never overridden), which has its own
independent `mode = self.INTENT_TO_MODE.get(intent, "load_first")` lookup
(line 673) feeding `backend/api.py`'s `period_groups`/
`tomorrow_period_groups` (lines 1745-1860), which is what the frontend's
`PeriodGroup.mode` / `getBatteryModeDisplay(group.mode)` actually
displays. This is a third, independent place carrying the same static
lookup, on top of `get_period_settings()` and `get_all_tou_segments()`
identified originally — and it's the primary one, since it's what issue
#415's screenshot shows. Being a single un-overridden base-class method
is good news: fixing it once via `self.CONTROL_MODEL` covers the primary
table for all six controllers in one place, same as `get_period_settings()`.

`get_period_settings()` and `get_detailed_period_groups()` (both defined
once, on the base class — neither overridden by any subclass) are updated
to compute their `batt_mode`/`vpp_power_pct`/`vpp_remote_control`/(nothing)
fields via a new shared base-class helper, `_mode_display_fields(intent,
grid_charge, discharge_rate, block_passive_charging)`, branching on
`self.CONTROL_MODEL`.
`get_all_tou_segments()` is `@abstractmethod` with six independent
concrete overrides (one per controller) building fundamentally different
segment structures (real TOU-register readback for `GrowattMinController`
and `SolaxModbusGrowattController` in `tou` mode; charge/discharge
period-list grouping for `GrowattSphController`/`SolisModbusController`/
`HuaweiController`; strategic-intent grouping for the `vpp_power`
controllers) — these are **not** merged into one shared implementation.
Each override instead calls the same `_mode_display_fields()` helper at
the point where it currently sets `batt_mode`, replacing its own
`INTENT_TO_MODE` lookup or hardcoded `"load_first"` stub. This is the
"one generic mechanism" the goals call for: a single source of truth for
what fields a period gets, reused everywhere, without pretending the six
segment-building implementations were ever going to unify.

### 2. API contract

New field `controlModel: 'tou_register' | 'vpp_power' | 'period_list'`
exposed alongside `inverterPlatform` in schedule/status responses, derived
from the controller's `CONTROL_MODEL`. Per-period/segment payloads:

- `tou_register`: `battMode` present (unchanged).
- `vpp_power`: `battMode` absent; `vppPowerPct` + `vppRemoteControl`
  present.
- `period_list`: `battMode` absent; no replacement numeric field.

`strategicIntent` is present unconditionally in all three cases (already
true today).

This affects every endpoint that calls `get_period_settings()`,
`get_detailed_period_groups()`, or `get_all_tou_segments()` — including
`/api/inverter/schedule`'s `period_groups`/`tomorrow_period_groups`
(the primary Schedule Overview data, `backend/api.py:1745-1860`) and the
prediction-snapshot comparison endpoint (`backend/api.py:2699-2718`,
currently `interval["batt_mode"]` plain-indexed with no default — must be
updated to branch on `controlModel` rather than assume presence). Each
`PeriodGroup` gains the same conditional `vppPowerPct`/`vppRemoteControl`
fields as per-period payloads, mirroring the `batt_mode`-present/absent
rule.

### 3. Frontend

**`InverterStatusDashboard.tsx`**: replace the `isTouBased =
schedulePlatform !== 'solax_modbus_native'` heuristic (line 729) with a
direct read of `controlModel`. Column rendering branches three ways:

- `tou_register`: today's columns unchanged (Mode, Charge %, Discharge %,
  Grid Charge).
- `vpp_power`: Intent badge (existing) + new "VPP Power" column (signed %,
  from `vppPowerPct`). Drop the TOU-only columns entirely.
- `period_list`: Intent badge only, no extra numeric column.

`getBatteryModeDisplay()` / `formatBatteryMode()` remain used only for the
`tou_register` branch — no new fallback/throw handling needed since
non-`tou_register` rows never call them.

**`SystemStatusCard.tsx`**: the separate "Battery Mode" metric
(lines 467-474) becomes `controlModel`-aware — hidden/replaced for
`vpp_power` and `period_list` installs rather than rendering a stale or
defaulted value. (The backend's existing `.get("batt_mode",
"load_first")` default at `backend/api.py:1525` must not be used to
paper over this — that default exists for other reasons and should not
be read as "safe to ignore" for this card; the card itself must branch.)

**`PredictionAnalysisView.tsx`**: same treatment. Currently a binary
`battery_first`/else-"Load First" ternary (lines 669, 753) with mismatch
detection via `battMode !== battMode` (lines 711, 749) — silently
mislabels rather than crashes today, and will misbehave further once
`battMode` becomes conditionally absent upstream. Needs `controlModel`
branching mirroring the main dashboard, sourced from the corrected
prediction-snapshot endpoint (section 2).

### 4. Testing

- Backend: parametrized tests across all six controllers asserting
  `CONTROL_MODEL` (or the computed property) and the resulting field set
  from `get_period_settings()` / `get_all_tou_segments()`.
- Rewrite `core/bess/tests/unit/test_solax_modbus_growatt_vpp.py` and
  `unit/test_solax_controller.py`, which currently assert `batt_mode`
  present with TOU-style values — update for the new
  `vpp_power_pct`/`vpp_remote_control`, `batt_mode`-absent shape.
- If `_intent_to_vpp()` is hoisted, existing VPP tests for both
  controllers should continue passing unchanged — a regression signal
  that the dedup preserved behavior.
- `GrowattMinController` tests (`tou_register`, unchanged) should require
  no changes — confirms the classification doesn't disturb the one
  platform already correct today.
- Frontend: Playwright coverage for all three `controlModel` branches in
  `InverterStatusDashboard.tsx`, plus `PredictionAnalysisView.tsx`
  rendering a `vpp_power`/`period_list` snapshot without mislabeling.

### 5. Migration / rollout

- Additive API fields (`controlModel`, `vppPowerPct`, `vppRemoteControl`);
  `battMode` becomes conditionally absent. No external consumers exist —
  confirmed no Home Assistant sensor/entity exposes `batt_mode`; it is
  purely an internal REST field consumed only by this repo's frontend.
- No data migration — nothing persisted changes shape.
- Debug bundle generation (`core/bess/debug_data_exporter.py`) does not
  call `get_period_settings()` / `get_all_tou_segments()` directly — it
  snapshots `active_tou_intervals` raw dicts, which will naturally reflect
  each controller's corrected output with no code change needed. This is
  itself part of the fix: future debug bundles from VPP/period-list
  installs will show the real absence of a mode concept instead of a
  fictional label.
- CHANGELOG entry under `Unreleased` noting the API shape change.

## Resolved during review

- `_intent_to_vpp()` in `SolaxModbusGrowattController` and
  `SolaxController` are confirmed **not** identical post-#355/#413 — see
  the correction in section 1. No open question remains; the design
  keeps them as separate implementations behind a shared field shape.
