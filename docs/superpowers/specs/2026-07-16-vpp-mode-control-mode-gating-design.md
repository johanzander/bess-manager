# Design: VPP mode must not fall back to TOU/EMS-register behavior

**Date**: 2026-07-16
**Issues**: [#309](https://github.com/johanzander/bess-manager/issues/309),
[#308](https://github.com/johanzander/bess-manager/issues/308),
[#302](https://github.com/johanzander/bess-manager/issues/302)
**Related**: [#118](https://github.com/johanzander/bess-manager/issues/118)
(original VPP mode request), PR #297 (VPP mode implementation, on
`origin/main` — not present on the branch this investigation started from)

## Problem

`SolaxModbusGrowattController` supports two control strategies on one class,
selected by an instance-level `control_mode` ("tou" / "vpp"). Several
hardware-facing code paths still act as if TOU/EMS-register behavior is
always in effect, regardless of `control_mode`:

1. `initialize_hardware()` / `_disable_legacy_tou_slots()` write to TOU
   entities even when `control_mode == "vpp"` — disabling segment 1, and
   writing `end_time="00:00"` to stale slots.
2. `check_health()`'s base `all_methods` list (`get_charging_power_rate`,
   `get_discharging_power_rate`, `get_charge_stop_soc`,
   `get_discharge_stop_soc`) is required unconditionally, even though the
   mode-specific `required_keys` list in the same method already correctly
   branches on `control_mode`.
3. `battery_system_manager.py`'s `adjust_charging_power()` (5-min cron, plus
   after every period apply) and `apply_discharge_inhibit()` (1-min cron)
   write `ems_charging_rate` / `ems_discharging_rate` gated only on the
   class-level `supports_charge_rate_control` capability flag, which cannot
   see the instance-level `control_mode`.

## Root cause

(1) and (2) are plain implementation gaps inside a file that otherwise
branches on `control_mode` correctly. (3) is structural: capability queries
in this codebase are class-level (`ClassVar[bool]`, per
`InverterController.supports_charge_rate_control`), by established
convention (`docs/agents/patterns.md`) — orchestrator code is supposed to
query a capability flag rather than branch on platform/mode directly. VPP
mode broke that convention's assumption: it's a per-instance runtime toggle
on a class whose capability flag is declared once, at the class level. The
orchestrator code did exactly the right thing by the existing pattern and
still got it wrong, because the flag itself couldn't reflect the mode.

## Evidence

Debug bundle `bess-debug-2026-07-14-231249.md` (same file, attached to both
#302 and #300 by the same reporter), system running `control_mode: "vpp"`:

- `"last_operation": "TOU slot 1 set tou_time_1_end=00:00"` → `500 Server
  Error` on `select.select_option`, ×8 over 8 hours — matches #302's report
  and is the TOU "scrambling" reported in #309.
- `number.growatt_inverter_ems_discharging_stop_soc_on_grid` → 404 (disabled
  in HA, expected for VPP setups per #118) → `SYSTEM DEGRADED: Critical
  sensor failures... Battery Control`, repeated on every health check all
  day — direct confirmation of gap (2) above.

## Design

### `core/bess/solax_modbus_growatt_controller.py`

1. Override `supports_charge_rate_control` as an instance `@property`,
   returning `False` when `self.control_mode == "vpp"`, else the inherited
   `True`. This is the structural fix for gap (3) — no changes needed in
   `battery_system_manager.py`, since `_supports_charge_rate_control`
   already reads the attribute off the instance
   (`self._inverter_controller.supports_charge_rate_control`), and Python
   resolves an instance property transparently wherever a `ClassVar` read
   used to work.
2. `initialize_hardware()`: skip `_disable_legacy_tou_slots()` and the
   explicit segment-1 disable write entirely when `control_mode == "vpp"`.
   Fixes #309 (per your and ridax67's agreed direction: VPP mode should not
   touch TOU entities at all) and #302 (same call is the one erroring).
3. `check_health()`: mode-gate the base `all_methods` list the same way
   `required_keys` already is — VPP mode should not require
   `get_charging_power_rate` / `get_discharging_power_rate` /
   `get_charge_stop_soc` / `get_discharge_stop_soc`.

### `core/bess/battery_system_manager.py`

No code changes. Confirms the fix is structural rather than another
scattered `if control_mode` check — `adjust_charging_power()` and
`apply_discharge_inhibit()` become correct automatically once the capability
flag reflects the mode.

### Out of scope

Splitting `SolaxModbusGrowattController` into separate TOU/VPP controller
classes (the project's usual "one class per scheduling model" convention,
per `add-inverter-platform`). Considered and rejected for now: the existing
single-class design already branches correctly in most places (this fix
closes the remaining gaps rather than proving the branching approach
unsound), the module docstring frames the dual-mode class as intentionally
transitional ("VPP intended to eventually replace TOU once proven"), and a
full split is a much larger change (factory, both suffix maps, docs, mock-HA
scenarios, wizard E2E) than three field-reported bugs justify. Revisit at
VPP graduation time if TOU mode on this platform is deprecated.

## Testing

In `core/bess/tests/unit/` (new or existing
`test_solax_modbus_growatt_single_segment.py`-adjacent file):

- `supports_charge_rate_control` is `False` when `control_mode == "vpp"`,
  `True` when `control_mode == "tou"`.
- `initialize_hardware()` issues zero `select.select_option` TOU-entity
  writes in VPP mode.
- `check_health()` does not mark EMS rate/stop-SOC entities as required in
  VPP mode.
- `adjust_charging_power()` / `apply_discharge_inhibit()` skip their
  EMS-register writes in VPP mode (verify existing capability-gated tests
  cover this once the property returns `False`; add if not).
