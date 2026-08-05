# Control-Model-Aware Schedule Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop every `InverterController` subclass from displaying a `load_first`/`battery_first`/`grid_first` TOU-register mode label for control models that don't have one (VPP power+remote_control, or charge/discharge period-lists), replacing it with data that reflects each platform's real behavior.

**Architecture:** Add a `CONTROL_MODEL` classification (`tou_register` | `vpp_power` | `period_list`) to every controller. A new shared base-class helper, `_mode_display_fields()`, computes the right output fields (`batt_mode`, or `vpp_power_pct`/`vpp_remote_control`, or neither) branching on that classification, and is wired into the three base-class methods that currently embed their own `INTENT_TO_MODE` lookup: `get_period_settings()`, `get_detailed_period_groups()`, and (via each subclass's own `get_all_tou_segments()` override) the TOU-segment display path. The two `vpp_power` controllers (`SolaxModbusGrowattController` in `vpp` mode, `SolaxController`) keep **separate** power-computation methods, not a shared one — their real hardware behavior has diverged (see design spec) — but expose the same field shape.

**Tech Stack:** Python (FastAPI backend, `core/bess/` controller layer), React/TypeScript (frontend), pytest, Playwright.

## Global Constraints

- No change to optimizer/DP logic, `INTENT_TO_CONTROL`, or actual hardware write behavior — display/API-shape only (design spec Non-goals).
- `SolaxController`'s VPP power computation must mirror its own current `_write_period_to_hardware()` logic exactly — do not port Growatt's `block_passive_charging`/LOAD_SUPPORT fixes into it (tracked separately in TODO.md).
- `strategic_intent` stays present unconditionally in every payload shape — never gated by `CONTROL_MODEL`.
- Run `.venv/bin/pytest -m "not slow"` after every backend task; run `cd frontend && npm run lint:fix` after every frontend task. Run `./scripts/quality-check.sh` before the final commit of the whole plan.
- Every task's commit message references issue #415 or the design spec path `docs/superpowers/specs/2026-07-29-control-model-display-design.md`.

---

### Task 1: `CONTROL_MODEL` classification on all six controllers

**Files:**
- Modify: `core/bess/inverter_controller.py:79-122` (Platform capabilities section)
- Modify: `core/bess/growatt_min_controller.py` (class body, near other `ClassVar`s)
- Modify: `core/bess/solax_modbus_growatt_controller.py:113-124` (near `_is_tou_control` property)
- Modify: `core/bess/growatt_sph_controller.py` (class body)
- Modify: `core/bess/solis_modbus_controller.py` (class body)
- Modify: `core/bess/huawei_controller.py` (class body)
- Modify: `core/bess/solax_controller.py:51-56` (near other `ClassVar`s)
- Test: `core/bess/tests/unit/test_control_model_classification.py` (new)

**Interfaces:**
- Produces: `InverterController.CONTROL_MODEL: ClassVar[str]` default value `"tou_register"` on the base class; each subclass overrides or computes it. Valid values: `"tou_register"`, `"vpp_power"`, `"period_list"`.

- [ ] **Step 1: Write the failing test**

```python
# core/bess/tests/unit/test_control_model_classification.py
"""CONTROL_MODEL must correctly classify every controller's real hardware model."""

import pytest

from core.bess.growatt_min_controller import GrowattMinController
from core.bess.growatt_sph_controller import GrowattSphController
from core.bess.huawei_controller import HuaweiController
from core.bess.solax_controller import SolaxController
from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController
from core.bess.solis_modbus_controller import SolisModbusController


def _make(cls, battery_settings, **kwargs):
    return cls(battery_settings=battery_settings, **kwargs)


def test_growatt_min_is_tou_register(battery_settings):
    controller = _make(GrowattMinController, battery_settings)
    assert controller.CONTROL_MODEL == "tou_register"


def test_solax_modbus_growatt_tou_mode_is_tou_register(battery_settings):
    controller = _make(
        SolaxModbusGrowattController, battery_settings, control_mode="tou"
    )
    assert controller.CONTROL_MODEL == "tou_register"


def test_solax_modbus_growatt_vpp_mode_is_vpp_power(battery_settings):
    controller = _make(
        SolaxModbusGrowattController, battery_settings, control_mode="vpp"
    )
    assert controller.CONTROL_MODEL == "vpp_power"


def test_solax_controller_is_vpp_power(battery_settings):
    controller = _make(SolaxController, battery_settings)
    assert controller.CONTROL_MODEL == "vpp_power"


def test_growatt_sph_is_period_list(battery_settings):
    controller = _make(GrowattSphController, battery_settings)
    assert controller.CONTROL_MODEL == "period_list"


def test_solis_modbus_is_period_list(battery_settings):
    controller = _make(SolisModbusController, battery_settings)
    assert controller.CONTROL_MODEL == "period_list"


def test_huawei_is_period_list(battery_settings):
    controller = _make(HuaweiController, battery_settings)
    assert controller.CONTROL_MODEL == "period_list"
```

Check `core/bess/tests/unit/conftest.py` for an existing `battery_settings` fixture before adding one — reuse it if present (the `conftest.py` hits noted in the design-time audit, lines 240-268, confirm one exists for TOU-segment tests).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_control_model_classification.py -v`
Expected: FAIL — `AttributeError: 'GrowattMinController' object has no attribute 'CONTROL_MODEL'` (or similar) on every test.

- [ ] **Step 3: Add the classification**

In `core/bess/inverter_controller.py`, add near the other `ClassVar` platform-capability declarations (after `dedupe_register_writes`, around line 122):

```python
    # Real hardware control model this platform uses, driving what fields
    # get_period_settings()/get_detailed_period_groups()/get_all_tou_segments()
    # attach to each period (see _mode_display_fields()):
    # - "tou_register": genuine load_first/battery_first/grid_first hardware
    #   register exists (Growatt MIN, solax_modbus Growatt in TOU mode).
    # - "vpp_power": no mode register; behavior is (power_pct,
    #   remote_control) per period (solax_modbus Growatt VPP mode, native
    #   SolaX).
    # - "period_list": no per-period mode or power value; behavior is
    #   discrete charge/discharge time slots (Growatt SPH, Solis, Huawei).
    CONTROL_MODEL: ClassVar[str] = "tou_register"
```

In `core/bess/growatt_min_controller.py`, no change needed — inherits the base class default `"tou_register"`.

In `core/bess/solax_modbus_growatt_controller.py`, add a property near `_is_tou_control` (line 113-124), and remove reliance on the base `ClassVar` for this subclass since it's dual-mode:

```python
    @property
    def CONTROL_MODEL(self) -> str:  # noqa: N802 (matches base ClassVar name)
        """Dual-mode: real TOU register in "tou" mode, VPP power+remote_control
        in "vpp" mode — see _is_tou_control for the underlying capability
        split this mirrors."""
        return "tou_register" if self._is_tou_control else "vpp_power"
```

In `core/bess/growatt_sph_controller.py`, add near the top of the class body:

```python
    CONTROL_MODEL: ClassVar[str] = "period_list"
```

(Add `from typing import ClassVar` to imports if not already present — check first.)

In `core/bess/solis_modbus_controller.py`, same pattern:

```python
    CONTROL_MODEL: ClassVar[str] = "period_list"
```

In `core/bess/huawei_controller.py`, same pattern:

```python
    CONTROL_MODEL: ClassVar[str] = "period_list"
```

In `core/bess/solax_controller.py`, add near `discharge_rate_is_load_following` (line 51-56):

```python
    CONTROL_MODEL: ClassVar[str] = "vpp_power"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_control_model_classification.py -v`
Expected: PASS, all 7 tests.

- [ ] **Step 5: Commit**

```bash
git add core/bess/inverter_controller.py core/bess/growatt_min_controller.py \
  core/bess/solax_modbus_growatt_controller.py core/bess/growatt_sph_controller.py \
  core/bess/solis_modbus_controller.py core/bess/huawei_controller.py \
  core/bess/solax_controller.py core/bess/tests/unit/test_control_model_classification.py
git commit -m "feat(#415): classify each controller's real CONTROL_MODEL

Adds tou_register/vpp_power/period_list classification per design spec
docs/superpowers/specs/2026-07-29-control-model-display-design.md,
section 1. No behavior change yet — this is the foundation the display
fix (get_period_settings/get_detailed_period_groups/get_all_tou_segments)
branches on in the following tasks."
```

---

### Task 2: `SolaxController._vpp_display_state()` — own VPP display method

**Files:**
- Modify: `core/bess/solax_controller.py`
- Test: `core/bess/tests/unit/test_solax_controller.py`

**Interfaces:**
- Consumes: nothing new — mirrors `_write_period_to_hardware()` (`solax_controller.py:104-151`), already in this file.
- Produces: `SolaxController._vpp_display_state(self, grid_charge: bool, discharge_rate: int) -> tuple[int, bool]` returning `(power_pct, remote_control_enabled)`. Later tasks (Task 6) call this via `_mode_display_fields()`.

- [ ] **Step 1: Write the failing test**

Add to `core/bess/tests/unit/test_solax_controller.py` (check existing fixture/setup pattern in that file first, e.g. how a `SolaxController` instance is constructed elsewhere in the file, and match it):

```python
class TestVppDisplayState:
    """_vpp_display_state must mirror _write_period_to_hardware exactly —
    same three branches, same sign convention (power_pct as percent of
    max, matching the discharge_rate parameter it's built from)."""

    def test_grid_charge_shows_full_positive_power_remote_enabled(self, solax_controller):
        power_pct, remote_control = solax_controller._vpp_display_state(
            grid_charge=True, discharge_rate=0
        )
        assert (power_pct, remote_control) == (100, True)

    def test_discharge_shows_negative_power_remote_enabled(self, solax_controller):
        power_pct, remote_control = solax_controller._vpp_display_state(
            grid_charge=False, discharge_rate=60
        )
        assert (power_pct, remote_control) == (-60, True)

    def test_idle_shows_zero_power_remote_disabled(self, solax_controller):
        """Matches _write_period_to_hardware's `set_solax_vpp_disabled()`
        branch (grid_charge=False, discharge_rate=0) -- self-use passthrough,
        NOT a grid-first hold. SolaX has no block_passive_charging
        equivalent (see TODO.md gap note)."""
        power_pct, remote_control = solax_controller._vpp_display_state(
            grid_charge=False, discharge_rate=0
        )
        assert (power_pct, remote_control) == (0, False)
```

If a `solax_controller` fixture doesn't already exist in that test file's local fixtures or `conftest.py`, add one matching however `SolaxController` is instantiated elsewhere in `test_solax_controller.py` (it's tested directly on line 401 per the design-time audit) — use that existing construction pattern, do not invent a new one.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_solax_controller.py::TestVppDisplayState -v`
Expected: FAIL — `AttributeError: 'SolaxController' object has no attribute '_vpp_display_state'`.

- [ ] **Step 3: Implement**

In `core/bess/solax_controller.py`, add after `_write_period_to_hardware` (after line 151):

```python
    def _vpp_display_state(
        self, grid_charge: bool, discharge_rate: int
    ) -> tuple[int, bool]:
        """Map (grid_charge, discharge_rate) to (power_pct, remote_control_enabled)
        for display, mirroring _write_period_to_hardware()'s three branches
        exactly. Unlike SolaxModbusGrowattController._intent_to_vpp(), this
        has no block_passive_charging or strategic_intent input -- SolaX's
        actual hardware write logic doesn't use them either (see the
        TODO.md gap note: SolaX never received the #355/#413 Growatt VPP
        fixes, so its real behavior for SOLAR_EXPORT/LOAD_SUPPORT differs).

        Returns:
            (power_pct, remote_control_enabled) -- power_pct expressed as a
            percent of max charge/discharge power, matching discharge_rate's
            own convention (not raw watts).
        """
        if not grid_charge and discharge_rate == 0:
            return 0, False
        if grid_charge:
            return 100, True
        return -discharge_rate, True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_solax_controller.py::TestVppDisplayState -v`
Expected: PASS, all 3 tests.

- [ ] **Step 5: Commit**

```bash
git add core/bess/solax_controller.py core/bess/tests/unit/test_solax_controller.py
git commit -m "feat(#415): add SolaxController._vpp_display_state()

Own VPP display computation for SolaX, deliberately NOT shared with
SolaxModbusGrowattController._intent_to_vpp() -- the two controllers'
real hardware behavior has diverged (see design spec section 1
correction, and TODO.md's SolaX VPP gap note)."
```

---

### Task 3: Shared `_mode_display_fields()` helper on the base class

**Files:**
- Modify: `core/bess/inverter_controller.py`
- Test: `core/bess/tests/unit/test_mode_display_fields.py` (new)

**Interfaces:**
- Consumes: `self.CONTROL_MODEL` (Task 1), `self.INTENT_TO_MODE` (existing), `SolaxModbusGrowattController._intent_to_vpp()` (existing, unchanged), `SolaxController._vpp_display_state()` (Task 2).
- Produces: `InverterController._mode_display_fields(self, intent: str, grid_charge: bool, discharge_rate: int, block_passive_charging: bool) -> dict`. Returns `{"batt_mode": <str>}` for `tou_register`, `{"vpp_power_pct": <int>, "vpp_remote_control": <bool>}` for `vpp_power`, or `{}` for `period_list`. Called by Task 4 (`get_period_settings`), Task 5 (`get_detailed_period_groups`), and Task 6/7 (each `get_all_tou_segments` override).

- [ ] **Step 1: Write the failing test**

```python
# core/bess/tests/unit/test_mode_display_fields.py
"""_mode_display_fields() is the single source of truth for what mode-
related fields a period gets, branching on CONTROL_MODEL. No batt_mode
fiction, no static stubs -- see design spec section 1."""

import pytest

from core.bess.growatt_min_controller import GrowattMinController
from core.bess.growatt_sph_controller import GrowattSphController
from core.bess.solax_controller import SolaxController
from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController


def test_tou_register_returns_batt_mode_only(battery_settings):
    controller = GrowattMinController(battery_settings=battery_settings)
    fields = controller._mode_display_fields(
        intent="SOLAR_EXPORT",
        grid_charge=False,
        discharge_rate=0,
        block_passive_charging=True,
    )
    assert fields == {"batt_mode": "load_first"}


def test_vpp_power_growatt_returns_vpp_fields_not_batt_mode(battery_settings):
    controller = SolaxModbusGrowattController(
        battery_settings=battery_settings, control_mode="vpp"
    )
    fields = controller._mode_display_fields(
        intent="SOLAR_EXPORT",
        grid_charge=False,
        discharge_rate=0,
        block_passive_charging=True,
    )
    assert "batt_mode" not in fields
    assert fields["vpp_power_pct"] == 0
    assert fields["vpp_remote_control"] is True  # grid-first hold, #355


def test_vpp_power_solax_returns_vpp_fields_reflecting_its_own_behavior(battery_settings):
    controller = SolaxController(battery_settings=battery_settings)
    fields = controller._mode_display_fields(
        intent="SOLAR_EXPORT",
        grid_charge=False,
        discharge_rate=0,
        block_passive_charging=True,  # SolaX ignores this -- see TODO.md gap
    )
    assert "batt_mode" not in fields
    assert fields["vpp_power_pct"] == 0
    assert fields["vpp_remote_control"] is False  # self-use passthrough, NOT a hold


def test_period_list_returns_no_mode_fields(battery_settings):
    controller = GrowattSphController(battery_settings=battery_settings)
    fields = controller._mode_display_fields(
        intent="GRID_CHARGING",
        grid_charge=True,
        discharge_rate=0,
        block_passive_charging=False,
    )
    assert fields == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_mode_display_fields.py -v`
Expected: FAIL — `AttributeError: ... no attribute '_mode_display_fields'`.

- [ ] **Step 3: Implement**

In `core/bess/inverter_controller.py`, add a new method after `get_period_settings()` (after line 596, before `get_strategic_intent_summary`):

```python
    def _mode_display_fields(
        self,
        intent: str,
        grid_charge: bool,
        discharge_rate: int,
        block_passive_charging: bool,
    ) -> dict:
        """Single source of truth for what mode-related fields a period
        gets, branching on CONTROL_MODEL. Never fabricates a label the
        hardware doesn't back — see design spec
        docs/superpowers/specs/2026-07-29-control-model-display-design.md.

        vpp_power controllers each keep their own power-computation method
        (SolaxModbusGrowattController._intent_to_vpp,
        SolaxController._vpp_display_state) rather than sharing one --
        their real hardware behavior has diverged (design spec section 1
        correction).

        Returns:
            {"batt_mode": str} for tou_register.
            {"vpp_power_pct": int, "vpp_remote_control": bool} for vpp_power.
            {} for period_list.
        """
        if self.CONTROL_MODEL == "tou_register":
            return {"batt_mode": self.INTENT_TO_MODE[intent]}

        if self.CONTROL_MODEL == "vpp_power":
            if hasattr(self, "_intent_to_vpp"):
                power_pct, remote_control = self._intent_to_vpp(
                    grid_charge, discharge_rate, block_passive_charging, intent
                )
            else:
                power_pct, remote_control = self._vpp_display_state(
                    grid_charge, discharge_rate
                )
            return {
                "vpp_power_pct": power_pct,
                "vpp_remote_control": remote_control,
            }

        return {}
```

Note: `hasattr(self, "_intent_to_vpp")` dispatches to `SolaxModbusGrowattController._intent_to_vpp` when present, else `SolaxController._vpp_display_state` (Task 2) — both are the only two `vpp_power` controllers, and this avoids adding an abstract method that every `tou_register`/`period_list` controller would need to no-op. If a third `vpp_power` controller is ever added, it must implement one of these two method names.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_mode_display_fields.py -v`
Expected: PASS, all 4 tests.

- [ ] **Step 5: Commit**

```bash
git add core/bess/inverter_controller.py core/bess/tests/unit/test_mode_display_fields.py
git commit -m "feat(#415): add shared _mode_display_fields() helper

Single choke point for batt_mode/vpp_power_pct/vpp_remote_control field
computation, branching on CONTROL_MODEL. Not yet wired into
get_period_settings/get_detailed_period_groups/get_all_tou_segments --
next tasks."
```

---

### Task 4: Wire into `get_period_settings()`

**Files:**
- Modify: `core/bess/inverter_controller.py:549-596`
- Test: `core/bess/tests/unit/test_get_period_settings_control_model.py` (new)

**Interfaces:**
- Consumes: `_mode_display_fields()` (Task 3).
- Produces: `get_period_settings()` return dict now has `batt_mode` OR `vpp_power_pct`/`vpp_remote_control` OR neither, instead of always `batt_mode`. `backend/api.py` callers (Task 9) must be updated to use `.get("batt_mode")` (already the case at two call sites) and read the new fields.

- [ ] **Step 1: Write the failing test**

```python
# core/bess/tests/unit/test_get_period_settings_control_model.py
"""get_period_settings() must stop always returning batt_mode -- issue #415."""

import pytest

from core.bess.dp_schedule import DPSchedule
from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController


def test_vpp_mode_solar_export_period_has_no_batt_mode_and_correct_vpp_fields(
    battery_settings,
):
    controller = SolaxModbusGrowattController(
        battery_settings=battery_settings, control_mode="vpp"
    )
    controller.strategic_intents = ["SOLAR_EXPORT"] * 96
    settings = controller.get_period_settings(period=25)  # 06:15
    assert "batt_mode" not in settings
    assert settings["vpp_power_pct"] == 0
    assert settings["vpp_remote_control"] is True  # grid-first hold, matches issue #415
    assert settings["strategic_intent"] == "SOLAR_EXPORT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_get_period_settings_control_model.py -v`
Expected: FAIL — `assert "batt_mode" not in settings` fails because `settings["batt_mode"] == "load_first"` (the exact issue #415 bug, reproduced as a test).

- [ ] **Step 3: Implement**

In `core/bess/inverter_controller.py`, replace lines 566-596:

```python
        intent = self.strategic_intents[period]

        if (
            self.current_schedule is not None
            and self.current_schedule.actions
            and period < len(self.current_schedule.actions)
        ):
            battery_action_kwh = self.current_schedule.actions[period]
            num_periods = len(self.current_schedule.actions)
            period_duration_hours = 24.0 / num_periods
            battery_action_kw = battery_action_kwh / period_duration_hours
            grid_charge, discharge_rate, block_passive_charging = (
                self.compute_rates_for_period(period, battery_action_kw)
            )
            charge_rate = self._compute_charge_rate(
                intent, self.INTENT_TO_CONTROL[intent], battery_action_kw
            )
        else:
            control = self.INTENT_TO_CONTROL[intent]
            grid_charge = control["grid_charge"]
            charge_rate = control["charge_rate"]
            discharge_rate = control["discharge_rate"]
            block_passive_charging = control["charge_rate"] == 0

        return {
            "grid_charge": grid_charge,
            "charge_rate": charge_rate,
            "discharge_rate": discharge_rate,
            "strategic_intent": intent,
            **self._mode_display_fields(
                intent, grid_charge, discharge_rate, block_passive_charging
            ),
        }
```

(This removes the old `mode = self.INTENT_TO_MODE[intent]` line and the unconditional `"batt_mode": mode` key, and computes `block_passive_charging` in the `else` branch the same way `compute_rates_for_period` does — `control["charge_rate"] == 0` — since that branch doesn't call `compute_rates_for_period`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_get_period_settings_control_model.py -v`
Expected: PASS.

Also run the full existing test suite for this method to catch regressions in `tou_register` controllers:

Run: `.venv/bin/pytest core/bess/tests/unit/test_growatt_tou_scheduling.py core/bess/tests/unit/test_solax_modbus_growatt_single_segment.py -v`
Expected: PASS unchanged (these are `tou_register`-only tests; `batt_mode` still present for them).

- [ ] **Step 5: Commit**

```bash
git add core/bess/inverter_controller.py core/bess/tests/unit/test_get_period_settings_control_model.py
git commit -m "fix(#415): get_period_settings() stops fabricating batt_mode

Root-cause fix for issue #415: SOLAR_EXPORT on a VPP-controlled Growatt
install no longer reports batt_mode=load_first when the hardware is
actually doing a grid-first hold. Wires the CONTROL_MODEL-driven
_mode_display_fields() helper (Task 3) into the one shared
get_period_settings() implementation."
```

---

### Task 5: Wire into `get_detailed_period_groups()` — the actual Schedule Overview data source

**Files:**
- Modify: `core/bess/inverter_controller.py:635-760`
- Test: `core/bess/tests/unit/test_detailed_period_groups_control_model.py` (new)

**Interfaces:**
- Consumes: `_mode_display_fields()` (Task 3).
- Produces: each group dict returned by `get_detailed_period_groups()` gains `batt_mode`/`vpp_power_pct`+`vpp_remote_control`/neither instead of always `mode`. **Grouping key changes**: groups can no longer be split on a static `mode` string comparison for `vpp_power` controllers, since `vpp_power_pct` is a signed int, not `mode`. `backend/api.py` (Task 9) and `PeriodGroup` in `InverterStatusDashboard.tsx` (Task 11) both consume this — this is the fix for the exact Schedule Overview screenshot in issue #415.

- [ ] **Step 1: Write the failing test**

```python
# core/bess/tests/unit/test_detailed_period_groups_control_model.py
"""get_detailed_period_groups() feeds the Schedule Overview table shown
in issue #415's screenshot -- must stop fabricating a mode label."""

import pytest

from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController


def test_vpp_solar_export_group_has_no_mode_and_correct_vpp_fields(battery_settings):
    controller = SolaxModbusGrowattController(
        battery_settings=battery_settings, control_mode="vpp"
    )
    groups = controller.get_detailed_period_groups(
        intents=["SOLAR_EXPORT"] * 4,
        actions=[0.0] * 4,
    )
    assert len(groups) == 1
    group = groups[0]
    assert "mode" not in group
    assert group["vpp_power_pct"] == 0
    assert group["vpp_remote_control"] is True
    assert group["intent"] == "SOLAR_EXPORT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_detailed_period_groups_control_model.py -v`
Expected: FAIL — `group["mode"] == "load_first"` is present, reproducing the exact issue #415 screenshot bug at its real source.

- [ ] **Step 3: Implement**

In `core/bess/inverter_controller.py`, replace the `period_settings` construction loop (lines 670-697):

```python
        period_settings = []
        for period in range(num_periods):
            intent = effective_intents[period]
            control = self.INTENT_TO_CONTROL.get(
                intent,
                {"grid_charge": False, "charge_rate": 100, "discharge_rate": 0},
            )

            action_kwh = 0.0
            if schedule_actions is not None and period < len(schedule_actions):
                action_kwh = schedule_actions[period]
            action_kw = action_kwh / 0.25

            _, discharge_rate = self._map_intent_to_rates(intent, action_kw)
            charge_rate = self._compute_charge_rate(intent, control, action_kw)
            block_passive_charging = control["charge_rate"] == 0
            mode_fields = self._mode_display_fields(
                intent, control["grid_charge"], discharge_rate, block_passive_charging
            )

            period_settings.append(
                {
                    "period": period,
                    "intent": intent,
                    **mode_fields,
                    "grid_charge": control["grid_charge"],
                    "charge_rate": charge_rate,
                    "discharge_rate": discharge_rate,
                    "action_kwh": action_kwh,
                }
            )
```

Then update the grouping comparison (lines 699-729) to key on the mode fields generically instead of a hardcoded `"mode"` key — replace:

```python
        for ps in period_settings:
            if current_group is not None and (
                ps["intent"] == current_group["intent"]
                and ps["mode"] == current_group["mode"]
                and ps["grid_charge"] == current_group["grid_charge"]
                and ps["charge_rate"] == current_group["charge_rate"]
                and ps["discharge_rate"] == current_group["discharge_rate"]
            ):
```

with:

```python
        mode_field_keys = ("batt_mode", "vpp_power_pct", "vpp_remote_control")

        for ps in period_settings:
            if current_group is not None and (
                ps["intent"] == current_group["intent"]
                and all(
                    ps.get(k) == current_group.get(k) for k in mode_field_keys
                )
                and ps["grid_charge"] == current_group["grid_charge"]
                and ps["charge_rate"] == current_group["charge_rate"]
                and ps["discharge_rate"] == current_group["discharge_rate"]
            ):
```

And in both places building `current_group` (the `else` branch dict at ~716-726, and the final `result.append` dict at ~743-758), replace the hardcoded `"mode": ps["mode"]` / `"mode": group["mode"]` with spreading the same mode fields:

```python
                current_group = {
                    "start_period": ps["period"],
                    "end_period": ps["period"],
                    "intent": ps["intent"],
                    **{k: ps[k] for k in mode_field_keys if k in ps},
                    "grid_charge": ps["grid_charge"],
                    "charge_rate": ps["charge_rate"],
                    "discharge_rate": ps["discharge_rate"],
                    "count": 1,
                    "total_action_kwh": ps["action_kwh"],
                }
```

and in the final result-building loop:

```python
            result.append(
                {
                    "start_time": f"{start_h:02d}:{start_m:02d}",
                    "end_time": f"{end_h:02d}:{end_m:02d}",
                    "start_period": group["start_period"],
                    "end_period": group["end_period"],
                    "intent": group["intent"],
                    **{k: group[k] for k in mode_field_keys if k in group},
                    "grid_charge": group["grid_charge"],
                    "charge_rate": group["charge_rate"],
                    "discharge_rate": group["discharge_rate"],
                    "period_count": group["count"],
                    "duration_minutes": group["count"] * 15,
                    "total_action_kwh": group["total_action_kwh"],
                    "soc_end_pct": soc_end,
                }
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_detailed_period_groups_control_model.py -v`
Expected: PASS.

Run the full existing suite touching this method to catch regressions:

Run: `.venv/bin/pytest core/bess/tests/unit/test_growatt_tou_scheduling.py -v -k "period_groups or detailed"`
Expected: PASS unchanged (`tou_register` controllers still get `mode` renamed to `batt_mode` — check whether any existing test asserts the literal key `"mode"` rather than `"batt_mode"` and update it if so, since this task also renames the field from `mode` to `batt_mode` for consistency with `get_period_settings()`'s field name; grep first: `grep -rn '\["mode"\]\|get("mode"' core/bess/tests/`).

- [ ] **Step 5: Commit**

```bash
git add core/bess/inverter_controller.py core/bess/tests/unit/test_detailed_period_groups_control_model.py
git commit -m "fix(#415): get_detailed_period_groups() stops fabricating mode label

This is the actual data source behind issue #415's Schedule Overview
screenshot (backend/api.py period_groups/tomorrow_period_groups), not
get_all_tou_segments() as originally assumed -- see design spec section
1, 'Second correction'. Also renames the group field from 'mode' to
'batt_mode' for consistency with get_period_settings()."
```

---

### Task 6: `SolaxModbusGrowattController.get_all_tou_segments()` — branch on control_mode

**Files:**
- Modify: `core/bess/solax_modbus_growatt_controller.py:615-654`
- Test: rewrite `core/bess/tests/unit/test_solax_modbus_growatt_vpp.py`

**Interfaces:**
- Consumes: `_mode_display_fields()` (Task 3), existing `get_detailed_period_groups()` (Task 5, now control-model-aware).
- Produces: segments returned by `get_all_tou_segments()` carry `batt_mode` (tou) or `vpp_power_pct`/`vpp_remote_control` (vpp) instead of always `batt_mode`.

- [ ] **Step 1: Write the failing test**

In `core/bess/tests/unit/test_solax_modbus_growatt_vpp.py`, find the existing assertion at line 449 (per design-time audit: `"batt_mode": "battery_first"`). Read the surrounding test first to understand its full setup, then replace that assertion's expectation. Add a new test alongside it:

```python
def test_get_all_tou_segments_vpp_mode_solar_export_has_no_batt_mode(
    solax_modbus_growatt_vpp_controller,  # use whatever fixture name this file already uses
):
    controller = solax_modbus_growatt_vpp_controller
    controller.strategic_intents = ["SOLAR_EXPORT"] * 96
    controller.current_schedule = None
    segments = controller.get_all_tou_segments()
    assert len(segments) >= 1
    segment = segments[0]
    assert "batt_mode" not in segment
    assert segment["vpp_power_pct"] == 0
    assert segment["vpp_remote_control"] is True
```

(Match the exact fixture name and controller-construction pattern already used in this file — read it first rather than guessing; the design-time audit found this file already has a working VPP controller fixture given its 125-474 line range of `batt_mode` assertions.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_solax_modbus_growatt_vpp.py -v`
Expected: FAIL on both the new test and the pre-existing line-449 assertion (now asserting the old, wrong shape).

- [ ] **Step 3: Implement**

In `core/bess/solax_modbus_growatt_controller.py`, replace lines 638-653 (inside the `for group in groups:` loop):

```python
        result = []
        for group in groups:
            block_passive_charging = (
                self.INTENT_TO_CONTROL.get(group["intent"], {}).get("charge_rate") == 0
            )
            mode_fields = self._mode_display_fields(
                group["intent"],
                group["grid_charge"],
                group["discharge_rate"],
                block_passive_charging,
            )
            is_current = group["start_period"] <= current_p <= group["end_period"]
            is_default_display = mode_fields.get("batt_mode") == "load_first"
            result.append(
                {
                    "segment_id": len(result) + 1,
                    "start_time": group["start_time"],
                    "end_time": group["end_time"],
                    **mode_fields,
                    "enabled": not is_default_display,
                    "is_default": is_default_display,
                    "is_current": is_current,
                    "strategic_intent": group["intent"],
                }
            )
        return result
```

Note: the old `"enabled": mode != "load_first"` / `"is_default": mode == "load_first"` logic only makes sense for `tou_register`; for `vpp_power` groups (no `batt_mode` key), `mode_fields.get("batt_mode")` is `None`, so `is_default_display` is `False` and every VPP segment is `enabled=True, is_default=False` — correct, since VPP has no "default/inactive" TOU-slot concept, every period is an active command.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_solax_modbus_growatt_vpp.py -v`
Expected: PASS, including the corrected line-449 assertion.

Also run the TOU-mode counterpart to confirm no regression:

Run: `.venv/bin/pytest core/bess/tests/unit/test_solax_modbus_growatt_single_segment.py -v`
Expected: PASS unchanged (TOU mode, `batt_mode` still present).

- [ ] **Step 5: Commit**

```bash
git add core/bess/solax_modbus_growatt_controller.py core/bess/tests/unit/test_solax_modbus_growatt_vpp.py
git commit -m "fix(#415): SolaxModbusGrowattController.get_all_tou_segments() branches on control_mode

VPP-mode segments now carry vpp_power_pct/vpp_remote_control instead of
a fabricated batt_mode label. TOU mode unchanged."
```

---

### Task 7: `SolaxController.get_all_tou_segments()` — own VPP fields

**Files:**
- Modify: `core/bess/solax_controller.py:345-376`
- Test: `core/bess/tests/unit/test_solax_controller.py`

**Interfaces:**
- Consumes: `_mode_display_fields()` (Task 3), which dispatches to `_vpp_display_state()` (Task 2) for this class.

- [ ] **Step 1: Write the failing test**

Add to `core/bess/tests/unit/test_solax_controller.py`:

```python
def test_get_all_tou_segments_solar_export_reflects_self_use_not_a_hold(solax_controller):
    solax_controller.strategic_intents = ["SOLAR_EXPORT"] * 4
    solax_controller.current_schedule = None
    segments = solax_controller.get_all_tou_segments()
    assert len(segments) == 1
    segment = segments[0]
    assert "batt_mode" not in segment
    assert segment["vpp_power_pct"] == 0
    assert segment["vpp_remote_control"] is False  # SolaX's real (unfixed) behavior
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_solax_controller.py::test_get_all_tou_segments_solar_export_reflects_self_use_not_a_hold -v`
Expected: FAIL — current code returns `"batt_mode": group["mode"]` (`"load_first"`, from the old `INTENT_TO_MODE` lookup baked into `get_detailed_period_groups()` before Task 5 — now that Task 5 shipped, `group["mode"]` no longer exists as a key at all, so this fails with a `KeyError` instead, equally proving the bug existed).

- [ ] **Step 3: Implement**

In `core/bess/solax_controller.py`, replace lines 364-376:

```python
        result = []
        for i, group in enumerate(groups, 1):
            result.append(
                {
                    "segment_id": i,
                    "start_time": group["start_time"],
                    "end_time": group["end_time"],
                    "vpp_power_pct": group["vpp_power_pct"],
                    "vpp_remote_control": group["vpp_remote_control"],
                    "enabled": True,
                    "strategic_intent": group["intent"],
                }
            )
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_solax_controller.py -v`
Expected: PASS, full file.

- [ ] **Step 5: Commit**

```bash
git add core/bess/solax_controller.py core/bess/tests/unit/test_solax_controller.py
git commit -m "fix(#415): SolaxController.get_all_tou_segments() uses vpp_power_pct

Reflects SolaX's own real (self-use passthrough) SOLAR_EXPORT behavior
instead of a fabricated batt_mode label -- see TODO.md gap note for why
this differs from Growatt VPP's grid-first hold."
```

---

### Task 8: Drop `batt_mode` from period-list controllers (SPH, Solis, Huawei)

**Files:**
- Modify: `core/bess/inverter_controller.py:335-379` (`_periods_to_tou_intervals`, shared by SPH/Solis)
- Modify: `core/bess/growatt_sph_controller.py:478-491` (default-stub fallback)
- Modify: `core/bess/solis_modbus_controller.py:375-388` (default-stub fallback)
- Modify: `core/bess/huawei_controller.py:172-194` (`_build_huawei_periods`) and `:348-360` (default-stub fallback)
- Test: `core/bess/tests/unit/test_period_list_no_batt_mode.py` (new)

**Interfaces:**
- Produces: no controller with `CONTROL_MODEL == "period_list"` ever includes a `batt_mode` key in `get_all_tou_segments()` output, including its "no schedule yet" default-stub fallback.

- [ ] **Step 1: Write the failing test**

```python
# core/bess/tests/unit/test_period_list_no_batt_mode.py
"""period_list controllers must never fabricate a batt_mode label --
their real hardware model has no per-period mode concept at all."""

import pytest

from core.bess.growatt_sph_controller import GrowattSphController
from core.bess.huawei_controller import HuaweiController
from core.bess.solis_modbus_controller import SolisModbusController


@pytest.mark.parametrize(
    "controller_cls", [GrowattSphController, SolisModbusController, HuaweiController]
)
def test_default_stub_has_no_batt_mode(controller_cls, battery_settings):
    controller = controller_cls(battery_settings=battery_settings)
    segments = controller.get_all_tou_segments()
    assert len(segments) == 1
    assert "batt_mode" not in segments[0]


@pytest.mark.parametrize("controller_cls", [GrowattSphController, SolisModbusController])
def test_built_period_list_has_no_batt_mode(controller_cls, battery_settings):
    controller = controller_cls(battery_settings=battery_settings)
    controller.strategic_intents = ["GRID_CHARGING"] * 4 + ["LOAD_SUPPORT"] * 4
    controller._build_period_list_schedule()
    segments = controller.get_all_tou_segments()
    assert segments
    assert all("batt_mode" not in s for s in segments)


def test_huawei_built_period_list_has_no_batt_mode(battery_settings):
    controller = HuaweiController(battery_settings=battery_settings)
    controller.strategic_intents = ["GRID_CHARGING"] * 4 + ["LOAD_SUPPORT"] * 4
    controller._build_huawei_periods()
    segments = controller.get_all_tou_segments()
    assert segments
    assert all("batt_mode" not in s for s in segments)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_period_list_no_batt_mode.py -v`
Expected: FAIL — all controllers currently return `batt_mode: "load_first"` (default stub) or `batt_mode: "battery_first"/"grid_first"` (built schedule).

- [ ] **Step 3: Implement**

In `core/bess/inverter_controller.py`, `_periods_to_tou_intervals` (lines 335-379) — this static method is used exclusively by period-list controllers (`GrowattSphController`, `SolisModbusController`, via `_build_period_list_schedule`); remove the `"batt_mode"` key from both dict-building loops:

```python
        intervals = []
        for p in charge_periods:
            intervals.append(
                {
                    "start_time": p["start_time"],
                    "end_time": p["end_time"],
                    "enabled": p.get("enabled", True),
                    "is_default": is_default,
                    "strategic_intent": charge_intent,
                }
            )
        for p in discharge_periods:
            intervals.append(
                {
                    "start_time": p["start_time"],
                    "end_time": p["end_time"],
                    "enabled": p.get("enabled", True),
                    "is_default": is_default,
                    "strategic_intent": discharge_intent,
                }
            )
```

In `core/bess/growatt_sph_controller.py`, the default-stub dict (lines 481-489), remove the `"batt_mode": "load_first"` line:

```python
        if not self.tou_intervals:
            return [
                {
                    "segment_id": 0,
                    "start_time": "00:00",
                    "end_time": "23:59",
                    "enabled": False,
                    "is_default": True,
                }
            ]
```

Apply the identical change to `core/bess/solis_modbus_controller.py:378-386` (same stub shape).

In `core/bess/huawei_controller.py`, `_build_huawei_periods` (lines 178-194), remove the `"batt_mode": ...` line:

```python
        self.tou_intervals = []
        for idx, p in enumerate(self._periods):
            self.tou_intervals.append(
                {
                    "start_time": p["start_time"],
                    "end_time": p["end_time"],
                    "enabled": True,
                    "is_default": False,
                    "strategic_intent": (
                        "GRID_CHARGING"
                        if p["flag"] == "+"
                        else "LOAD_SUPPORT/BATTERY_EXPORT"
                    ),
                    "segment_id": idx + 1,
                }
            )
```

And the Huawei default-stub at `get_all_tou_segments()` (lines 351-358), same removal as SPH/Solis.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_period_list_no_batt_mode.py -v`
Expected: PASS, all 8 parametrized cases.

Run the full existing suite for these three controllers to check for regressions (e.g. any test asserting the removed key):

Run: `.venv/bin/pytest core/bess/tests/unit/test_solis_modbus_controller.py core/bess/tests/unit/test_huawei_controller.py core/bess/tests/unit/test_huawei_ha_controller.py -v`
Expected: some pre-existing failures possible if those files assert `batt_mode` presence — fix each by removing the assertion (not by re-adding the field), since the field's absence is the intended fix. Also grep for and check any Growatt SPH test file (search: `grep -rln "GrowattSphController" core/bess/tests/unit/`).

- [ ] **Step 5: Commit**

```bash
git add core/bess/inverter_controller.py core/bess/growatt_sph_controller.py \
  core/bess/solis_modbus_controller.py core/bess/huawei_controller.py \
  core/bess/tests/unit/test_period_list_no_batt_mode.py
git commit -m "fix(#415): period-list controllers stop fabricating batt_mode

GrowattSphController, SolisModbusController, HuaweiController have no
per-period mode or power concept -- their static 'load_first' stub
(and Huawei's charge/discharge-sign approximation) is dropped entirely
rather than replaced, per design spec section 1."
```

---

### Task 9: Backend API — `controlModel` field + `vppPowerPct`/`vppRemoteControl` propagation

**Files:**
- Modify: `backend/api.py:1500-1562` (`/api/inverter/status`)
- Modify: `backend/api.py:1565-1780` (`/api/inverter/schedule`, `_get_hourly_settings_from_periods`)
- Modify: `backend/api.py:1690-1880` (`period_groups`/`tomorrow_period_groups` building)
- Test: `backend/tests/test_inverter_api.py`, `backend/tests/test_dashboard_api.py`

**Interfaces:**
- Consumes: `get_period_settings()` (Task 4), `get_detailed_period_groups()` (Task 5) — both now conditionally include `batt_mode`/`vpp_power_pct`/`vpp_remote_control`.
- Produces: JSON responses (after `convert_keys_to_camel_case`) with `controlModel: 'tou_register' | 'vpp_power' | 'period_list'` at the top level, and per-period-group `vppPowerPct`/`vppRemoteControl` when applicable. `battMode`/`batteryMode` become conditionally absent in the raw per-period dicts (but the existing `.get(..., "load_first")` defaults at lines 1525 and 1607 keep the top-level summary fields always present — unchanged, intentional, per design spec section 3's note not to treat that default as covering the per-group display).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_inverter_api.py` (check existing fixture/mock pattern in the file first — likely a mocked `bess_controller.system._inverter_controller`):

```python
def test_inverter_status_includes_control_model(client, mock_bess_controller):
    # Configure the mock inverter controller's CONTROL_MODEL per whatever
    # mocking pattern this file already uses (see existing fixtures at
    # lines 43, 53 per the design-time audit).
    mock_bess_controller.system._inverter_controller.CONTROL_MODEL = "vpp_power"
    response = client.get("/api/inverter/status")
    assert response.status_code == 200
    assert response.json()["controlModel"] == "vpp_power"
```

Add to `backend/tests/test_dashboard_api.py` (near the existing `batt_mode` fixture at line 142):

```python
def test_schedule_period_groups_include_vpp_fields_when_vpp_power(
    client, mock_bess_controller
):
    mock_bess_controller.system._inverter_controller.CONTROL_MODEL = "vpp_power"
    # Configure get_detailed_period_groups() mock return to include
    # vpp_power_pct/vpp_remote_control per Task 5's new shape, matching
    # whatever mocking pattern this file already uses for period_groups.
    response = client.get("/api/inverter/schedule")
    assert response.status_code == 200
    body = response.json()
    assert body["controlModel"] == "vpp_power"
    if body["periodGroups"]:
        assert "vppPowerPct" in body["periodGroups"][0]
        assert "battMode" not in body["periodGroups"][0]
```

(Read `backend/tests/test_inverter_api.py` and `test_dashboard_api.py` fully first to match their exact fixture/mocking conventions — the design-time audit found working fixtures at the cited line numbers; don't invent a different mocking approach.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest backend/tests/test_inverter_api.py backend/tests/test_dashboard_api.py -v -k control_model`
Expected: FAIL — `KeyError: 'controlModel'`.

- [ ] **Step 3: Implement**

In `backend/api.py`, `/api/inverter/status` (around line 1539, after `inverter_platform = bess_controller.system.inverter_platform`):

```python
        inverter_platform = bess_controller.system.inverter_platform
        control_model = schedule_manager.CONTROL_MODEL
```

(`schedule_manager` here is `bess_controller.system._inverter_controller`, already assigned at line 1522 for the `current_battery_mode` lookup — reuse that variable rather than re-fetching.)

Then add `"control_model": control_model,` to the `response` dict (line 1541-1555), alongside `"inverter_platform": inverter_platform,`.

In `/api/inverter/schedule` (around line 1574, `schedule_manager = bess_controller.system._inverter_controller` already exists), add after it:

```python
        control_model = schedule_manager.CONTROL_MODEL
```

In the `period_groups`/`tomorrow_period_groups` building loops (lines 1763-1779 and 1839-1857), replace the hardcoded `"mode": group["mode"],` line in each dict with:

```python
                        **(
                            {"vpp_power_pct": group["vpp_power_pct"], "vpp_remote_control": group["vpp_remote_control"]}
                            if "vpp_power_pct" in group
                            else {"batt_mode": group["batt_mode"]}
                            if "batt_mode" in group
                            else {}
                        ),
```

(Both loops build a dict via `period_groups.append({...})` / `tomorrow_period_groups.append({...})` — apply the same replacement to both, matching each loop's existing dict-literal style rather than introducing a shared helper function, since the two loops are Python dict literals in different scopes.)

Add `"control_model": control_model,` to the final `response` dict (around line 1864-1870), alongside `"inverter_platform": inverter_platform,`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest backend/tests/test_inverter_api.py backend/tests/test_dashboard_api.py -v`
Expected: PASS, full files (check for any other test in these files asserting the now-removed `mode`/`battMode` keys unconditionally, and fix per the intended shape).

- [ ] **Step 5: Commit**

```bash
git add backend/api.py backend/tests/test_inverter_api.py backend/tests/test_dashboard_api.py
git commit -m "feat(#415): expose controlModel + vppPowerPct/vppRemoteControl in API

/api/inverter/status and /api/inverter/schedule now surface controlModel
so the frontend can branch display logic instead of inferring TOU-vs-not
from the platform string (InverterStatusDashboard.tsx's isTouBased bug)."
```

---

### Task 10: Fix prediction-snapshot endpoint (plain `interval["batt_mode"]` indexing)

**Files:**
- Modify: `backend/api.py:2690-2720`
- Test: `backend/tests/test_inverter_api.py` (or wherever the prediction-snapshot endpoint's tests live — grep: `grep -rln "growattScheduleA\|snapshot_to_snapshot\|periodComparisons" backend/tests/`)

**Interfaces:**
- Consumes: `snapshot_a.growatt_schedule` / `snapshot_b.growatt_schedule` (raw dicts, from `self._inverter_controller.tou_intervals.copy()` at `battery_system_manager.py:768` — shape now matches Task 6/7/8's controller-specific output, i.e. conditionally has `batt_mode` or `vpp_power_pct`/`vpp_remote_control`).
- Produces: `growattScheduleA`/`growattScheduleB` entries carry `battMode` (if present) or `vppPowerPct`/`vppRemoteControl` (if present) instead of assuming `batt_mode` always exists.

- [ ] **Step 1: Write the failing test**

Find the existing test file covering this endpoint (grep above) and read its current test for `growattScheduleA`/`growattScheduleB` to match conventions. Add:

```python
def test_snapshot_comparison_handles_vpp_schedule_without_batt_mode(
    client, mock_snapshot_store
):
    # Configure snapshot_a.growatt_schedule to contain a dict shaped like
    # Task 6's vpp_power output: {"start_time": ..., "end_time": ...,
    # "vpp_power_pct": 0, "vpp_remote_control": True, ...} -- no batt_mode
    # key at all, matching whatever mocking convention this test file uses
    # for snapshot_a/snapshot_b.
    response = client.get(
        "/api/predictions/compare", params={"period_a": 10, "period_b": 50}
    )
    assert response.status_code == 200  # must not 500/KeyError
    schedule_a = response.json()["growattScheduleA"]
    if schedule_a:
        assert "vppPowerPct" in schedule_a[0] or "battMode" in schedule_a[0]
```

(Confirm the actual route path/params by reading the endpoint's `@router.get(...)` decorator above line 2690 first — don't guess the path.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest backend/tests/test_inverter_api.py -v -k vpp_schedule_without_batt_mode` (adjust file name per Step 1's grep result)
Expected: FAIL — `KeyError: 'batt_mode'` from the plain-index at line 2702/2712.

- [ ] **Step 3: Implement**

In `backend/api.py`, replace the `growattScheduleA`/`growattScheduleB` list-comprehensions (lines 2699-2718):

```python
        def _interval_display_fields(interval: dict) -> dict:
            if "vpp_power_pct" in interval:
                return {
                    "vppPowerPct": interval["vpp_power_pct"],
                    "vppRemoteControl": interval["vpp_remote_control"],
                }
            if "batt_mode" in interval:
                return {"battMode": interval["batt_mode"]}
            return {}

        response = {
            "snapshotAPeriod": period_a,
            "snapshotATimestamp": snapshot_a.snapshot_timestamp.isoformat(),
            "snapshotBPeriod": period_b,
            "snapshotBTimestamp": snapshot_b.snapshot_timestamp.isoformat(),
            "periodComparisons": period_comparisons,
            "growattScheduleA": [
                {
                    "segmentId": i + 1,
                    **_interval_display_fields(interval),
                    "startTime": interval["start_time"],
                    "endTime": interval["end_time"],
                    "enabled": interval.get("enabled", True),
                }
                for i, interval in enumerate(snapshot_a.growatt_schedule)
            ],
            "growattScheduleB": [
                {
                    "segmentId": i + 1,
                    **_interval_display_fields(interval),
                    "startTime": interval["start_time"],
                    "endTime": interval["end_time"],
                    "enabled": interval.get("enabled", True),
                }
                for i, interval in enumerate(snapshot_b.growatt_schedule)
            ],
        }
```

This dict is already inside camelCase-key territory (`snapshotAPeriod` etc. are hand-written camelCase, not run through `convert_keys_to_camel_case` for this section — verify by checking whether `convert_keys_to_camel_case(response)` is called on this specific response before returning, at the end of this endpoint function; if so, keep `_interval_display_fields` returning snake_case keys instead (`"vpp_power_pct"`/`"batt_mode"`) so the converter handles them uniformly, matching how the rest of this dict is written).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest backend/tests/test_inverter_api.py -v -k vpp_schedule_without_batt_mode`
Expected: PASS.

Run the full file to confirm no regression in the `tou_register` case (Growatt period-list schedules, `batt_mode` still present and correctly mapped):

Run: `.venv/bin/pytest backend/tests/test_inverter_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/api.py backend/tests/test_inverter_api.py
git commit -m "fix(#415): prediction-snapshot endpoint no longer assumes batt_mode

Plain interval[\"batt_mode\"] indexing (no default) would KeyError once
Task 6-8 made batt_mode conditionally absent. Now branches on which
fields the interval actually carries."
```

---

### Task 11: Frontend — `InverterStatusDashboard.tsx`

**Files:**
- Modify: `frontend/src/components/InverterStatusDashboard.tsx`
- Test: new Playwright spec, `e2e/tests/inverter-schedule-control-model.spec.ts`

**Interfaces:**
- Consumes: `controlModel` (Task 9), `vppPowerPct`/`vppRemoteControl` on `PeriodGroup`/`TOUInterval` (Task 9).
- Produces: three-way column branching replacing the two-way `isTouBased` heuristic.

- [ ] **Step 1: Update TypeScript interfaces**

In `frontend/src/components/InverterStatusDashboard.tsx`, update the interfaces (lines 19-100):

```typescript
type ControlModel = 'tou_register' | 'vpp_power' | 'period_list';

interface InverterStatus {
  // ... existing fields unchanged ...
  inverterPlatform?: string;
  controlModel?: ControlModel;
  // ... rest unchanged
}

interface TOUInterval {
  segmentId: number;
  startTime: string;
  endTime: string;
  battMode?: string;
  vppPowerPct?: number;
  vppRemoteControl?: boolean;
  enabled: boolean;
  isEmpty?: boolean;
  isDefault?: boolean;
  isExpired?: boolean;
  pendingWrite?: boolean;
}

interface PeriodGroup {
  startTime: string;
  endTime: string;
  battMode?: string;
  vppPowerPct?: number;
  vppRemoteControl?: boolean;
  dominantIntent: string;
  intentCounts: Record<string, number>;
  periodCount: number;
  durationMinutes: number;
  chargePowerRate: number;
  dischargePowerRate: number;
  gridCharge: boolean;
  totalActionKwh?: number;
  socEndPct?: number;
  socDeltaKwh?: number | null;
}

interface InverterSchedule {
  currentHour: number;
  inverterPlatform?: string;
  controlModel?: ControlModel;
  touIntervals: TOUInterval[];
  scheduleData: ScheduleHour[];
  periodGroups: PeriodGroup[];
  tomorrowPeriodGroups: PeriodGroup[] | null;
  batteryCapacity: number;
  lastUpdated: string;
}
```

(Remove the `mode: string;` field from `PeriodGroup` — replaced by the three optional fields above. `ScheduleHour.batteryMode` at line 62 stays as-is; it's a separate summary field defaulted server-side, out of scope for this task per Task 9's note.)

- [ ] **Step 2: Replace the `isTouBased` heuristic**

Replace line 727-730:

```typescript
          {inverterSchedule?.periodGroups && inverterSchedule.periodGroups.length > 0 ? (() => {
            const controlModel: ControlModel = inverterSchedule.controlModel ?? 'tou_register';
            const isTouBased = controlModel === 'tou_register';
            const isVppPower = controlModel === 'vpp_power';
            const totalCols = isTouBased ? 10 : isVppPower ? 7 : 6;
            return (
```

- [ ] **Step 3: Add the VPP Power column header, conditionally**

Replace lines 748-752 (the `colSpan={4}` "Inverter Configuration" header, currently `isTouBased`-only):

```typescript
                    {isTouBased && (
                      <th colSpan={4} className="px-3 py-2 text-center text-xs font-semibold text-indigo-700 dark:text-indigo-300 uppercase tracking-wider border border-gray-200 dark:border-gray-700 bg-indigo-50 dark:bg-indigo-900/20">
                        Inverter Configuration
                      </th>
                    )}
                    {isVppPower && (
                      <th colSpan={1} className="px-3 py-2 text-center text-xs font-semibold text-indigo-700 dark:text-indigo-300 uppercase tracking-wider border border-gray-200 dark:border-gray-700 bg-indigo-50 dark:bg-indigo-900/20">
                        VPP Control
                      </th>
                    )}
```

Replace lines 767-780 (the second header row's `isTouBased`-only Mode/Charge %/Discharge %/Grid Charge block):

```typescript
                    {isTouBased && (<>
                      <th className="px-3 py-2 text-center text-xs font-semibold text-indigo-600 dark:text-indigo-400 uppercase tracking-wider border border-gray-200 dark:border-gray-700 bg-indigo-50/70 dark:bg-indigo-900/10">
                        Mode
                      </th>
                      <th className="px-3 py-2 text-center text-xs font-semibold text-indigo-600 dark:text-indigo-400 uppercase tracking-wider border border-gray-200 dark:border-gray-700 bg-indigo-50/70 dark:bg-indigo-900/10">
                        Charge %
                      </th>
                      <th className="px-3 py-2 text-center text-xs font-semibold text-indigo-600 dark:text-indigo-400 uppercase tracking-wider border border-gray-200 dark:border-gray-700 bg-indigo-50/70 dark:bg-indigo-900/10">
                        Discharge %
                      </th>
                      <th className="px-3 py-2 text-center text-xs font-semibold text-indigo-600 dark:text-indigo-400 uppercase tracking-wider border border-gray-200 dark:border-gray-700 bg-indigo-50/70 dark:bg-indigo-900/10">
                        Grid Charge
                      </th>
                    </>)}
                    {isVppPower && (
                      <th className="px-3 py-2 text-center text-xs font-semibold text-indigo-600 dark:text-indigo-400 uppercase tracking-wider border border-gray-200 dark:border-gray-700 bg-indigo-50/70 dark:bg-indigo-900/10">
                        VPP Power
                      </th>
                    )}
```

- [ ] **Step 4: Replace the row body's Mode cell with three-way branching**

Replace lines 860-883 (today's rows) — the `isTouBased && (<> ... </>)` block:

```typescript
                        {isTouBased && (<>
                          <td className={`${invCell} text-center`}>{getBatteryModeDisplay(group.battMode!)}</td>
                          <td className={`${invCell} text-center`}>
                            {group.chargePowerRate > 0 ? (
                              <span className="text-green-600 dark:text-green-400 font-medium">{group.chargePowerRate}%</span>
                            ) : (
                              <span className="text-gray-300 dark:text-gray-600">—</span>
                            )}
                          </td>
                          <td className={`${invCell} text-center`}>
                            {group.dischargePowerRate > 0 ? (
                              <span className="text-orange-500 dark:text-orange-400 font-medium">{group.dischargePowerRate}%</span>
                            ) : (
                              <span className="text-gray-300 dark:text-gray-600">—</span>
                            )}
                          </td>
                          <td className={`${invCell} text-center`}>
                            {group.gridCharge ? (
                              <span className="text-green-600 dark:text-green-400 font-medium">Yes</span>
                            ) : (
                              <span className="text-gray-300 dark:text-gray-600">—</span>
                            )}
                          </td>
                        </>)}
                        {isVppPower && (
                          <td className={`${invCell} text-center`}>
                            {group.vppPowerPct !== undefined ? (
                              <span className={`font-medium ${group.vppPowerPct > 0 ? 'text-green-600 dark:text-green-400' : group.vppPowerPct < 0 ? 'text-orange-500 dark:text-orange-400' : 'text-gray-500 dark:text-gray-400'}`}>
                                {group.vppPowerPct > 0 ? '+' : ''}{group.vppPowerPct}%
                              </span>
                            ) : (
                              <span className="text-gray-300 dark:text-gray-600">—</span>
                            )}
                          </td>
                        )}
```

Apply the identical `isVppPower` addition to the tomorrow-rows block (lines 956-979), matching the same pattern.

- [ ] **Step 5: Update `getBatteryModeDisplay` call site guard and the raw TOU-intervals section**

`getBatteryModeDisplay` (lines 494-510) itself is unchanged — it's only ever called from `isTouBased`-gated branches now (Step 4's `group.battMode!` non-null assertion is safe because it's inside `isTouBased && (...)`, where `battMode` is always present per Task 9).

Update the "Hardware Schedule Section" (lines 996-1010) to branch on `controlModel` instead of `platform === 'solax_modbus_native'`:

```typescript
      {(() => {
        const platform = inverterSchedule?.inverterPlatform ?? inverterStatus?.inverterPlatform ?? 'growatt_server_min';
        const controlModel: ControlModel = inverterSchedule?.controlModel ?? 'tou_register';
        const isPerPeriodCommand = controlModel !== 'tou_register';

        return (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
            <div className="p-6">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center">
                  <Clock className="h-5 w-5 text-blue-600 mr-2" />
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                    {isPerPeriodCommand ? (controlModel === 'vpp_power' ? 'VPP Control' : 'Charge/Discharge Periods') : 'Time of Use (TOU) Intervals'}
                  </h3>
                </div>
```

(Keep the existing platform-name badge unchanged.) Replace `isSolax ?` at the ternary controlling which body renders (previously line ~1019) with `isPerPeriodCommand ?`, and adjust its message text to be control-model-generic rather than SolaX-specific:

```typescript
              {isPerPeriodCommand ? (
                <div className="rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 p-4">
                  <p className="text-sm font-medium text-blue-800 dark:text-blue-300 mb-1">
                    {controlModel === 'vpp_power' ? 'Per-period VPP commands' : 'Charge/discharge time periods'}
                  </p>
                  <p className="text-sm text-blue-700 dark:text-blue-400">
                    {controlModel === 'vpp_power'
                      ? 'This inverter uses real-time power commands instead of a stored schedule. Commands are issued at each 15-minute period boundary and kept active via autorepeat. The strategic intent timeline above shows what the optimizer has planned.'
                      : 'This inverter uses discrete charge/discharge time slots instead of a mode register. The strategic intent timeline above shows what the optimizer has planned; the schedule table shows the periods actually written to hardware.'}
                  </p>
                </div>
              ) : (
```

Everywhere inside the `else` branch (the `touIntervals` rendering, `interval.battMode`), no change needed — that branch now only runs for `tou_register`, where `battMode` is always present per Task 9.

- [ ] **Step 6: Lint**

Run: `cd frontend && npm run lint:fix`
Expected: no errors. Fix any TypeScript type errors surfaced (e.g. a stray reference to the removed `PeriodGroup.mode` field elsewhere in the file — grep first: `grep -n '\.mode\b' frontend/src/components/InverterStatusDashboard.tsx`).

- [ ] **Step 7: Write the Playwright spec**

```typescript
// e2e/tests/inverter-schedule-control-model.spec.ts
import { test, expect } from '@playwright/test';

test.describe('Inverter schedule display branches on controlModel', () => {
  test('tou_register install shows Mode/Charge%/Discharge%/Grid Charge columns', async ({ page }) => {
    // Mock /api/inverter/schedule to return controlModel: 'tou_register'
    // with a periodGroups entry carrying battMode. Assert the "Mode"
    // column header and a rendered battery-mode badge are visible.
    // (Follow this repo's existing e2e mocking convention -- check other
    // specs in e2e/tests/ for how API responses are stubbed, e.g. via
    // page.route(), before writing this.)
  });

  test('vpp_power install shows VPP Power column, not Mode/Charge%', async ({ page }) => {
    // Mock controlModel: 'vpp_power' with vppPowerPct/vppRemoteControl on
    // periodGroups. Assert "VPP Power" column header is visible, "Mode"
    // header is not, and the signed percent value renders.
  });

  test('period_list install shows neither Mode nor VPP Power columns', async ({ page }) => {
    // Mock controlModel: 'period_list'. Assert neither "Mode" nor
    // "VPP Power" headers are present -- only Intent/Solar/Grid/Target SOC.
  });
});
```

Read an existing spec in `e2e/tests/` first to match the actual mocking/setup convention (base URL, auth, how the dev server or mock-HA stack is expected to be running) before filling in the bodies — do not invent a different harness.

- [ ] **Step 8: Run the Playwright spec**

Run: `cd frontend && npx playwright test e2e/tests/inverter-schedule-control-model.spec.ts` (adjust per this repo's actual npm script — check `frontend/package.json` for the exact e2e command first).
Expected: PASS, all 3 cases.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/InverterStatusDashboard.tsx e2e/tests/inverter-schedule-control-model.spec.ts
git commit -m "fix(#415): InverterStatusDashboard branches on controlModel

Replaces the isTouBased platform-string heuristic (blind to VPP-mode
Growatt) with a proper three-way branch (tou_register/vpp_power/
period_list), adding a VPP Power column for vpp_power installs and
dropping TOU-only columns entirely for both non-tou_register cases."
```

---

### Task 12: Frontend — `SystemStatusCard.tsx`

**Files:**
- Modify: `frontend/src/components/SystemStatusCard.tsx:257-260,346-347,466-479`

**Interfaces:**
- Consumes: `controlModel` from `/api/inverter/status` (Task 9) — needs a new prop/data source; check how `inverterData` is currently sourced into this component (likely a hook near the top of the file) and thread `controlModel` through the same path.

- [ ] **Step 1: Write the failing test**

Check `frontend/src/components/__tests__/SystemStatusCard.test.tsx:170` (existing `batteryMode: 'LOAD_FIRST'` fixture per design-time audit). Add a companion test:

```typescript
it('hides the Battery Mode metric when controlModel is not tou_register', () => {
  const inverterData = { ...baseInverterData, controlModel: 'vpp_power', batteryMode: undefined };
  render(<SystemStatusCard {...propsWith(inverterData)} />);
  expect(screen.queryByText('Battery Mode')).not.toBeInTheDocument();
});
```

(Match this test file's existing render/props setup exactly — read the file first, since the hard-throw at line 257-258 means the test harness must supply a `controlModel` field for the "no batteryMode" case to not throw before reaching the component under test.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- SystemStatusCard`
Expected: FAIL — throws `MISSING DATA: inverterData.batteryMode is required but missing` at line 258, since that guard doesn't yet know about `controlModel`.

- [ ] **Step 3: Implement**

In `frontend/src/components/SystemStatusCard.tsx`, replace lines 256-260:

```typescript
    // Get actual battery mode from inverter status (not schedule) -- only
    // meaningful for tou_register installs; vpp_power/period_list have no
    // mode register, see docs/superpowers/specs/2026-07-29-control-model-display-design.md.
    const controlModel = inverterData.controlModel ?? 'tou_register';
    if (controlModel === 'tou_register' && !inverterData.batteryMode) {
      throw new Error('MISSING DATA: inverterData.batteryMode is required but missing');
    }
    const actualBatteryMode = controlModel === 'tou_register' ? inverterData.batteryMode : undefined;
```

Update line 347 (`batteryMode: actualBatteryMode` inside `batteryStatus`) — no change needed, `actualBatteryMode` is now `string | undefined`.

Replace the "Battery Mode" metric definition (lines 466-479) to conditionally include itself in the `metrics` array rather than always rendering:

```typescript
        {
          label: "State of Energy",
          value: (() => {
            if (!statusData.batteryStatus?.soe?.display) {
              throw new Error('MISSING DATA: batterySoe.display is required for SOE display');
            }
            if (!statusData.batteryCapacity) {
              throw new Error('MISSING DATA: batteryCapacity is required for SOE display');
            }
            return `${statusData.batteryStatus.soe.display}/${statusData.batteryCapacity}`;
          })(),
          unit: "kWh",
          icon: Zap
        },
        ...(statusData.batteryStatus.batteryMode ? [{
          label: "Battery Mode",
          value: (() => {
            const mode = statusData.batteryStatus.batteryMode?.toLowerCase() ?? '';
            switch (mode) {
              case 'load_first': return 'Load First';
              case 'battery_first': return 'Battery First';
              case 'grid_first': return 'Grid First';
              default: return statusData.batteryStatus.batteryMode ?? 'Unknown';
            }
          })(),
          unit: "",
          icon: Battery
        }] : [])
```

Need `statusData.batteryStatus.batteryMode` (the object built inside the `useMemo`, line 347) to be `undefined` rather than a stale/defaulted string when `controlModel !== 'tou_register'` — already satisfied by the Step 3 change to `actualBatteryMode` above, since `batteryMode: actualBatteryMode` now flows through as `undefined`.

Also update the local `InverterStatus`-shaped type this component imports/uses (check its source — likely `frontend/src/types.ts` or inline) to add `controlModel?: ControlModel;` mirroring Task 11's addition, and export/reuse the same `ControlModel` type rather than redefining it (check whether Task 11 already put it somewhere importable, e.g. `frontend/src/types.ts`; if it's currently only local to `InverterStatusDashboard.tsx`, move it to `frontend/src/types.ts` in this task and update Task 11's file to import it from there instead — small follow-up edit to `InverterStatusDashboard.tsx`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- SystemStatusCard`
Expected: PASS, full file.

- [ ] **Step 5: Lint and commit**

Run: `cd frontend && npm run lint:fix`

```bash
git add frontend/src/components/SystemStatusCard.tsx frontend/src/components/__tests__/SystemStatusCard.test.tsx frontend/src/types.ts
git commit -m "fix(#415): SystemStatusCard hides Battery Mode metric for non-tou_register

The hard-throw on missing batteryMode now only applies when
controlModel === 'tou_register'; the metric itself is omitted from the
card (not shown as 'Unknown' or a stale value) for vpp_power/period_list
installs."
```

---

### Task 13: Frontend — `PredictionAnalysisView.tsx`

**Files:**
- Modify: `frontend/src/components/PredictionAnalysisView.tsx:1-16,640-770`

**Interfaces:**
- Consumes: `vppPowerPct`/`vppRemoteControl` on `growattScheduleA`/`growattScheduleB` entries (Task 10).

- [ ] **Step 1: Write the failing test**

Check for an existing test file for this component (grep: `grep -rln "PredictionAnalysisView" frontend/src/components/__tests__/ 2>/dev/null`); if none exists, add one at `frontend/src/components/__tests__/PredictionAnalysisView.test.tsx` matching this repo's existing component-test conventions (check a sibling test file, e.g. `SystemStatusCard.test.tsx`, for the render/mock pattern). Add:

```typescript
it('renders VPP power percent instead of Mode label when battMode is absent', () => {
  const comparison = {
    ...baseComparison,
    growattScheduleA: [
      { segmentId: 1, startTime: '06:00', endTime: '06:15', enabled: true, vppPowerPct: 0, vppRemoteControl: true },
    ],
  };
  render(<PredictionAnalysisView />, { /* mock the hook to return `comparison` per this file's existing test setup */ });
  expect(screen.getByText(/VPP Power/i)).toBeInTheDocument();
  expect(screen.queryByText(/Load First|Battery First/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- PredictionAnalysisView`
Expected: FAIL — component currently renders `interval.battMode === 'battery_first' ? '⚡ Battery First' : '🏠 Load First'` unconditionally, so `/Load First|Battery First/` is always present regardless of the mocked data shape.

- [ ] **Step 3: Implement**

In `frontend/src/components/PredictionAnalysisView.tsx`, update the `GrowattInterval` type (lines 8-16):

```typescript
interface GrowattInterval {
  startTime: string;
  endTime: string;
  enabled: boolean;
  battMode?: string;
  vppPowerPct?: number;
  vppRemoteControl?: boolean;
  power: number;
  acChargeEnabled?: boolean;
}
```

Add a helper near the top of the component (after the imports, before the component body):

```typescript
function renderModeCell(interval: GrowattInterval, comparedTo?: GrowattInterval): { label: string; changed: boolean } {
  if (interval.vppPowerPct !== undefined) {
    const changed = comparedTo !== undefined && (
      comparedTo.vppPowerPct !== interval.vppPowerPct ||
      comparedTo.vppRemoteControl !== interval.vppRemoteControl
    );
    const sign = interval.vppPowerPct > 0 ? '+' : '';
    return {
      label: `⚡ VPP Power: ${sign}${interval.vppPowerPct}% (${interval.vppRemoteControl ? 'remote' : 'self-use'})`,
      changed,
    };
  }
  if (interval.battMode !== undefined) {
    const changed = comparedTo !== undefined && comparedTo.battMode !== interval.battMode;
    return {
      label: interval.battMode === 'battery_first' ? '⚡ Battery First' : '🏠 Load First',
      changed,
    };
  }
  return { label: '—', changed: false };
}
```

Replace line 669 (Snapshot A's Mode row):

```typescript
                            <span className="font-medium text-gray-900 dark:text-white">
                              {renderModeCell(interval).label}
                            </span>
```

Replace lines 710-714 (the `hasChanges` computation) to use the helper instead of directly comparing `battMode`/`power`:

```typescript
                      const modeCell = renderModeCell(interval, matchingA);
                      const hasChanges = matchingA && (
                        modeCell.changed ||
                        matchingA.power !== interval.power ||
                        matchingA.enabled !== interval.enabled ||
                        matchingA.acChargeEnabled !== interval.acChargeEnabled
                      );
```

Replace lines 746-754 (Snapshot B's Mode row):

```typescript
                            <div className="flex justify-between">
                              <span className="text-gray-600 dark:text-gray-400">Mode:</span>
                              <span className={`font-medium ${
                                modeCell.changed
                                  ? 'text-yellow-700 dark:text-yellow-300'
                                  : 'text-gray-900 dark:text-white'
                              }`}>
                                {modeCell.label}
                              </span>
                            </div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- PredictionAnalysisView`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

Run: `cd frontend && npm run lint:fix`

```bash
git add frontend/src/components/PredictionAnalysisView.tsx frontend/src/components/__tests__/PredictionAnalysisView.test.tsx
git commit -m "fix(#415): PredictionAnalysisView renders VPP power, not a fake Mode label

Previously a binary battery_first/else-'Load First' ternary that would
mislabel any VPP interval. Now branches on whether the interval carries
battMode or vppPowerPct/vppRemoteControl."
```

---

### Task 14: CHANGELOG entry

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add entry under `## [Unreleased]`**

Follow the existing `[Unreleased]` section's format (read the top of `CHANGELOG.md` first to match style — likely a `### Fixed`/`### Changed` subsection convention). Add:

```markdown
### Fixed

- Inverter schedule display no longer shows a fictional TOU mode label
  (Load First/Battery First/Grid First) for VPP-controlled or
  period-list-controlled installs. Growatt VPP mode in particular no
  longer mislabels a SOLAR_EXPORT grid-first hold as "Load First" (#415).
  The Schedule Overview table, Current Mode card, and prediction
  comparison view now show each platform's actual control behavior
  (VPP power percent + remote-control state, or nothing, as appropriate)
  instead.
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog entry for #415 control-model display fix"
```

---

### Task 15: Full quality gate

**Files:** none (verification only)

- [ ] **Step 1: Backend full suite**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS, zero failures.

Run: `.venv/bin/pytest -m slow`
Expected: PASS (per project memory, ~1-2 min not ~30 min).

- [ ] **Step 2: Quality check script**

Run: `./scripts/quality-check.sh`
Expected: PASS (Black, Ruff, mypy, full suite).

- [ ] **Step 3: Frontend**

Run: `cd frontend && npm run lint:fix && npm run build`
Expected: PASS, no type errors, clean build.

- [ ] **Step 4: E2E (if a local mock-HA stack is available)**

Follow the `verify` skill to stand up the real mock-HA + backend E2E stack and confirm the Schedule Overview table for a VPP-mode Growatt install now shows "VPP Power" instead of "Load First" for a SOLAR_EXPORT period — this is the literal reproduction of issue #415's screenshot, and the acceptance criterion for the whole plan.

- [ ] **Step 5: Final commit check**

Run: `git log --oneline design/issue-415-control-model-display ^origin/main`
Confirm every task's commit is present and the branch is ready for PR (per this repo's release workflow — a PR against `origin/main`, not a direct push).
