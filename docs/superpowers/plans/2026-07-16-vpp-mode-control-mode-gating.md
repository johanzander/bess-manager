# VPP Mode Control-Mode Gating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop VPP-mode `SolaxModbusGrowattController` instances from writing
TOU entities or requiring EMS flash-register entities, fixing issues #309,
#308, #302.

**Architecture:** `supports_charge_rate_control` becomes an instance-level
`@property` on `SolaxModbusGrowattController` (overriding the inherited
`ClassVar[bool] = True`), returning `False` when `self.control_mode ==
"vpp"`. This makes every existing capability-gated call site in
`battery_system_manager.py` correct automatically, with zero new
`control_mode` checks outside this one file. Two remaining spots inside
`solax_modbus_growatt_controller.py` that already branch on `control_mode`
elsewhere in the file are made consistent: `initialize_hardware()` stops
writing TOU entities in VPP mode, and `check_health()`'s base `all_methods`
list is mode-gated the same way its `required_keys` list already is.

**Tech Stack:** Python 3.12, pytest, unittest.mock.

## Global Constraints

- No changes to `core/bess/battery_system_manager.py` — the whole point of
  this fix is that it needs none (see design spec).
- Follow `docs/agents/patterns.md`: no `hasattr`/`getattr` defaults, no
  silent fallbacks, exceptions propagate.
- `black . && ruff check --fix .` must pass (`./scripts/quality-check.sh`).
- Design spec: `docs/superpowers/specs/2026-07-16-vpp-mode-control-mode-gating-design.md`.

---

### Task 1: Instance-level `supports_charge_rate_control` for VPP mode

**Files:**
- Modify: `core/bess/solax_modbus_growatt_controller.py:66-88` (`__init__`,
  add property after it)
- Modify: `core/bess/tests/unit/test_platform_capabilities.py:32-35`
- Test: `core/bess/tests/unit/test_platform_capabilities.py`

**Interfaces:**
- Produces: `SolaxModbusGrowattController.supports_charge_rate_control` —
  instance property, `bool`, `False` iff `self.control_mode == "vpp"`.

- [ ] **Step 1: Write the failing test**

Replace the existing class-level assertion (which breaks once this becomes
an instance property) with two instance-level tests, in
`core/bess/tests/unit/test_platform_capabilities.py`:

```python
    def test_solax_modbus_growatt_tou_mode_supports_charge_rate(self):
        # TOU mode uses the EMS charge/discharge-rate registers directly.
        controller = SolaxModbusGrowattController(
            BatterySettings(
                total_capacity=50.0,
                max_charge_power_kw=5.0,
                max_discharge_power_kw=5.0,
                min_soc=10.0,
                max_soc=95.0,
                cycle_cost_per_kwh=0.05,
            ),
            control_mode="tou",
        )
        assert controller.supports_charge_rate_control is True

    def test_solax_modbus_growatt_vpp_mode_does_not_support_charge_rate(self):
        # VPP mode drives power via vpp_power (RAM) — EMS registers unused.
        controller = SolaxModbusGrowattController(
            BatterySettings(
                total_capacity=50.0,
                max_charge_power_kw=5.0,
                max_discharge_power_kw=5.0,
                min_soc=10.0,
                max_soc=95.0,
                cycle_cost_per_kwh=0.05,
            ),
            control_mode="vpp",
        )
        assert controller.supports_charge_rate_control is False
```

Delete the old `test_solax_modbus_growatt_inherits_charge_rate_support` (it
asserted the class attribute directly; superseded by the two tests above).

Add the import at the top of the file:

```python
from core.bess.settings import BatterySettings
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_platform_capabilities.py -v`
Expected: `test_solax_modbus_growatt_vpp_mode_does_not_support_charge_rate`
FAILS with `assert True is False` (no override yet, inherited `ClassVar`
is always `True`).

- [ ] **Step 3: Write minimal implementation**

In `core/bess/solax_modbus_growatt_controller.py`, immediately after
`__init__` (after the `self._last_written_vpp_power: int | None = None`
line, before the `# ── Abstract property ──` comment), add:

```python
    @property
    def supports_charge_rate_control(self) -> bool:
        """VPP mode drives power via vpp_power (RAM); no EMS rate writes.

        TOU mode still uses the EMS charge/discharge-rate registers
        directly, so this stays True there (base class default).
        """
        return self.control_mode != "vpp"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_platform_capabilities.py -v`
Expected: all tests PASS, including
`test_min_platforms_report_charge_rate_control` (unaffected — that fixture
defaults to `control_mode="tou"`).

- [ ] **Step 5: Add the BSM-level integration test proving the orchestrator needs no changes**

Add to `core/bess/tests/unit/test_platform_capabilities.py`, in
`TestAdjustChargingPowerSkipsUnsupported`:

```python
    def test_vpp_mode_adjust_charging_power_is_noop(
        self, mock_controller, arbitrage_prices, monkeypatch
    ):
        """VPP-mode BSM must skip EMS writes without any BSM-level change."""
        from core.bess.battery_system_manager import BatterySystemManager
        from core.bess.price_manager import MockSource

        monkeypatch.setattr(
            "core.bess.sensor_collector.SensorCollector", MockSensorCollector
        )
        system = BatterySystemManager(
            controller=mock_controller,
            price_source=MockSource(arbitrage_prices),
            addon_options={
                "inverter": {
                    "platform": "solax_modbus_growatt_min",
                    "control_mode": "vpp",
                }
            },
        )
        assert system._supports_charge_rate_control is False
        system.adjust_charging_power()  # must not raise
```

Add the needed imports at the top of the file:

```python
from core.bess.tests.conftest import MockSensorCollector
```

Run: `.venv/bin/pytest core/bess/tests/unit/test_platform_capabilities.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add core/bess/solax_modbus_growatt_controller.py core/bess/tests/unit/test_platform_capabilities.py
git commit -m "fix: VPP mode reports no charge-rate-control capability (#308)

adjust_charging_power() and apply_discharge_inhibit() in
battery_system_manager.py already gate on supports_charge_rate_control,
but it was a class-level ClassVar blind to the instance-level
control_mode setting. Making it an instance property closes the gap
with no changes needed outside this controller."
```

---

### Task 2: Stop writing TOU entities in VPP mode

**Files:**
- Modify: `core/bess/solax_modbus_growatt_controller.py:424-441`
  (`initialize_hardware`)
- Test: `core/bess/tests/unit/test_solax_modbus_growatt_vpp.py`

**Interfaces:**
- Consumes: `self.control_mode` (existing instance attribute).
- Produces: no change to any public signature — `initialize_hardware`
  behavior only.

- [ ] **Step 1: Write the failing test**

In `core/bess/tests/unit/test_solax_modbus_growatt_vpp.py`, replace the
`TestDisableLegacyTouOnVppInit` class (currently asserting the old, buggy
behavior — VPP mode disabling TOU slot 1) with:

```python
class TestVppInitDoesNotTouchTou:
    def test_initialize_hardware_writes_no_tou_segments(self, controller, mock_ha):
        """VPP mode must never read or write TOU entities (#309, #302)."""
        mock_ha.read_tou_segments_from_entities = lambda: [
            {
                "segment_id": 1,
                "batt_mode": "battery_first",
                "start_time": "00:00",
                "end_time": "23:59",
                "enabled": True,
            }
        ]

        controller.initialize_hardware(mock_ha)

        assert mock_ha.calls["tou_segments"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_solax_modbus_growatt_vpp.py::TestVppInitDoesNotTouchTou -v`
Expected: FAILS — `mock_ha.calls["tou_segments"]` contains the segment-1
disable write from the current `initialize_hardware()`.

- [ ] **Step 3: Write minimal implementation**

In `core/bess/solax_modbus_growatt_controller.py`, replace the
`initialize_hardware` method body:

```python
    def initialize_hardware(self, controller) -> None:
        if self.control_mode == "vpp":
            # VPP mode must never touch TOU entities — not even to disable
            # them. A GEN4 install switching tou -> vpp with a still-active
            # TOU segment relies on the user (or setup wizard guidance) to
            # clear it, not on a runtime write here — see issue #309.
            return
        self._disable_legacy_tou_slots(controller)
        super().initialize_hardware(controller)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_solax_modbus_growatt_vpp.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full VPP and TOU controller test files to check for regressions**

Run: `.venv/bin/pytest core/bess/tests/unit/test_solax_modbus_growatt_vpp.py core/bess/tests/unit/test_solax_modbus_growatt_single_segment.py -v`
Expected: all PASS (TOU-mode `initialize_hardware` path is untouched —
still calls `_disable_legacy_tou_slots` then `super().initialize_hardware`).

- [ ] **Step 6: Commit**

```bash
git add core/bess/solax_modbus_growatt_controller.py core/bess/tests/unit/test_solax_modbus_growatt_vpp.py
git commit -m "fix: VPP mode never writes TOU entities (#309, #302)

initialize_hardware() disabled TOU slot 1 (and legacy slots 2-9) on
every VPP-mode startup, including a write of tou_time_1_end=\"00:00\"
that 500s against some solax_modbus integration versions. Per the
agreed design in #309, VPP mode should not touch TOU entities at all."
```

---

### Task 3: Mode-gate the health check's base EMS-register requirement

**Files:**
- Modify: `core/bess/solax_modbus_growatt_controller.py:575-589`
  (`check_health`)
- Test: `core/bess/tests/unit/test_solax_modbus_growatt_vpp.py`

**Interfaces:**
- Consumes: `self.control_mode`.
- Produces: no signature change — `check_health` return value only.

- [ ] **Step 1: Write the failing test**

Add to `TestCheckHealthVpp` in
`core/bess/tests/unit/test_solax_modbus_growatt_vpp.py`:

```python
    def test_ems_rate_and_stop_soc_not_required(self, controller, mock_ha):
        """VPP setups commonly have these EMS entities disabled in HA
        (they're unused in VPP mode) — health check must not require them."""
        mock_ha.sensors.update(
            {
                "growatt_vpp_status": "select.growatt_vpp_status",
                "growatt_vpp_remote_control": "select.growatt_vpp_remote_control",
                "growatt_vpp_allow_ac_charging": "select.growatt_vpp_allow_ac_charging",
                "growatt_vpp_time": "number.growatt_vpp_time",
                "growatt_vpp_power": "number.growatt_vpp_power",
            }
        )
        # No get_charge_stop_soc/get_discharge_stop_soc/rate methods mocked
        # on mock_ha — if check_health still calls them, this must not
        # register as an ERROR the way it did in the reported bug.
        for method in (
            "get_charging_power_rate",
            "get_discharging_power_rate",
            "get_charge_stop_soc",
            "get_discharge_stop_soc",
        ):
            def _raise(*_a, **_kw):
                raise ConnectionError("simulated: entity disabled in HA")

            setattr(mock_ha, method, _raise)

        [health] = controller.check_health(mock_ha)

        checked_names = {c["method_name"] for c in health["checks"]}
        assert "get_charge_stop_soc" not in checked_names
        assert "get_discharge_stop_soc" not in checked_names
        assert "get_charging_power_rate" not in checked_names
        assert "get_discharging_power_rate" not in checked_names
        assert health["status"] == "OK"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest "core/bess/tests/unit/test_solax_modbus_growatt_vpp.py::TestCheckHealthVpp::test_ems_rate_and_stop_soc_not_required" -v`
Expected: FAILS — `checked_names` still contains
`get_charge_stop_soc` etc., and `health["status"]` is `"ERROR"`.

- [ ] **Step 3: Write minimal implementation**

In `core/bess/solax_modbus_growatt_controller.py`, in `check_health`,
replace the hardcoded `all_methods=[...]` list:

```python
        all_methods = (
            ["grid_charge_enabled"]
            if self.control_mode == "vpp"
            else [
                "get_charging_power_rate",
                "get_discharging_power_rate",
                "grid_charge_enabled",
                "get_charge_stop_soc",
                "get_discharge_stop_soc",
            ]
        )
        health_check = perform_health_check(
            component_name="Battery Control",
            description="Controls battery charging and discharging schedule",
            is_required=True,
            controller=controller,
            all_methods=all_methods,
        )
```

(`grid_charge_enabled` stays required in both modes — the debug-log evidence
confirms `select.growatt_inverter_allow_grid_charge` is a shared entity that
works fine in this VPP install; it's not EMS-flash-specific.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_solax_modbus_growatt_vpp.py -v`
Expected: all PASS, including the pre-existing
`test_missing_vpp_entity_is_error` (still ERRORs correctly — that test
doesn't populate `mock_ha.sensors`, so the `required_keys` loop still
fails).

- [ ] **Step 5: Run the full fast suite**

Run: `.venv/bin/pytest -m "not slow" -q`
Expected: all PASS, no regressions in TOU-mode health checks (TOU mode's
`all_methods` list is unchanged).

- [ ] **Step 6: Commit**

```bash
git add core/bess/solax_modbus_growatt_controller.py core/bess/tests/unit/test_solax_modbus_growatt_vpp.py
git commit -m "fix: VPP mode health check does not require EMS rate/stop-SOC entities (#308)

check_health()'s required_keys list already branched on control_mode
for VPP vs TOU entities, but the base all_methods list didn't — VPP
installs with ems_discharging_stop_soc_on_grid disabled in HA (the
normal state per #118) hit SYSTEM DEGRADED on every health check."
```

---

### Task 4: Update CHANGELOG and open draft PR

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add changelog entry**

Under `## [Unreleased]` (create if missing) → `### Fixed`:

```markdown
- **VPP mode no longer touches TOU entities or requires EMS flash
  registers** — fixes VPP-mode installs seeing repeated 500 errors from
  stale TOU-entity writes and false "SYSTEM DEGRADED" health-check
  failures when EMS rate/stop-SOC entities are disabled in Home
  Assistant (the normal state for VPP setups). (#309, #308, #302)
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog entry for VPP mode control_mode gating fix"
```

- [ ] **Step 3: Run the full fast suite one more time, then hand off to `implement-issue` steps 6-9**

Run: `./scripts/quality-check.sh`
Expected: `🎉 All quality checks passed!`

This plan covers Task 1-4 (steps 4-9 of `implement-issue`: TDD done here;
next is the background quality-gate + code-review agent, confirm gate 2,
`verify` skill local run, then commit + draft PR per `implement-issue`).
