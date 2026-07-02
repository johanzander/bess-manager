# LOAD_SUPPORT Discharge Pacing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the inverter execute LOAD_SUPPORT periods at the DP-planned discharge power instead of always dumping at 100% rate, so the plan-faithfulness simulator returns R≈P for high-consumption scenarios.

**Architecture:** The fix is entirely in the real-time control translation layer. `_map_intent_to_rates` in `InverterController` and its mirror `_map_rates` in the inverter simulator both hard-code `discharge_rate=100` for LOAD_SUPPORT. Change both to scale from the planned `battery_action_kw` exactly as EXPORT_ARBITRAGE already does. The DP optimizer's reward/transition model for discharge is already correct and unchanged.

**Tech Stack:** Python, pytest. No new dependencies.

## Global Constraints

- Never add fallbacks, silent error handling, or graceful degradation — fail explicitly per `docs/agents/rules.md`
- `black . && ruff check --fix .` must pass before committing
- Run `pytest -m "not slow"` (fast suite) to verify each task; the slow suite runs in CI
- `BATTERY_MAX_CHARGE_DISCHARGE_POWER_KW = 15.0` is the default used by `BatterySettings()`

---

### Task 1: Scale LOAD_SUPPORT discharge_rate in the production controller

The production controller (`InverterController._map_intent_to_rates`) hard-codes `discharge_rate=100` for LOAD_SUPPORT. Change it to compute the rate from `battery_action_kw`, mirroring EXPORT_ARBITRAGE.

**Files:**
- Modify: `core/bess/inverter_controller.py:116-149`
- Test: `core/bess/tests/unit/test_controller_coverage.py:395-425`

**Interfaces:**
- Produces: `_map_intent_to_rates("LOAD_SUPPORT", battery_action_kw)` returns `(False, int)` where the int is `0..100` proportional to `abs(battery_action_kw) / max_discharge_power_kw * 100`, clamped to `[0, 100]`, truncated with `int()`.

- [ ] **Step 1: Write failing tests**

Add to `class TestComputeRatesForPeriod` in `core/bess/tests/unit/test_controller_coverage.py` (after line 425, before the `# ── SolaxController ──` comment):

```python
def test_load_support_partial_discharge(self, min_ctrl):
    # 1.5 kW of 15.0 kW max → 10%
    min_ctrl.strategic_intents = ["LOAD_SUPPORT"] * 4
    grid_charge, discharge_rate = min_ctrl.compute_rates_for_period(
        0, battery_action_kw=-1.5
    )
    assert grid_charge is False
    assert discharge_rate == 10

def test_load_support_full_discharge(self, min_ctrl):
    min_ctrl.strategic_intents = ["LOAD_SUPPORT"] * 4
    _grid_charge, discharge_rate = min_ctrl.compute_rates_for_period(
        0, battery_action_kw=-min_ctrl.max_discharge_power_kw
    )
    assert discharge_rate == 100

def test_load_support_zero_action(self, min_ctrl):
    min_ctrl.strategic_intents = ["LOAD_SUPPORT"] * 4
    _grid_charge, discharge_rate = min_ctrl.compute_rates_for_period(
        0, battery_action_kw=0.0
    )
    assert discharge_rate == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest core/bess/tests/unit/test_controller_coverage.py::TestComputeRatesForPeriod -v
```

Expected: 3 new tests FAIL (`assert 100 == 10`, `assert 100 == 10`, `assert 100 == 0`).

- [ ] **Step 3: Implement the fix in `_map_intent_to_rates`**

In `core/bess/inverter_controller.py`, replace lines 132-133:

```python
        elif intent == "LOAD_SUPPORT":
            return False, 100
```

with:

```python
        elif intent == "LOAD_SUPPORT":
            if battery_action_kw < -0.01:
                discharge_rate = min(
                    100,
                    max(
                        0,
                        int(abs(battery_action_kw) / self.max_discharge_power_kw * 100),
                    ),
                )
            else:
                discharge_rate = 0
            return False, discharge_rate
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest core/bess/tests/unit/test_controller_coverage.py::TestComputeRatesForPeriod -v
```

Expected: all 7 tests in `TestComputeRatesForPeriod` PASS.

- [ ] **Step 5: Run fast suite to catch regressions**

```bash
pytest -m "not slow" -x -q
```

Expected: all fast tests PASS.

- [ ] **Step 6: Format and commit**

```bash
black . && ruff check --fix .
git add core/bess/inverter_controller.py core/bess/tests/unit/test_controller_coverage.py
git commit -m "fix: scale LOAD_SUPPORT discharge_rate from planned action (mirrors EXPORT_ARBITRAGE)"
```

---

### Task 2: Mirror the fix in the inverter simulator

The simulator's `_map_rates` in `core/bess/simulation/inverter_simulator.py` must mirror `_map_intent_to_rates` exactly — it is the function the plan-faithfulness simulator uses to derive what `derive_control_command` sends. Without this change R≠P even after Task 1.

**Files:**
- Modify: `core/bess/simulation/inverter_simulator.py:43-62`
- Test: `core/bess/tests/unit/test_controller_coverage.py` (new test class)

**Interfaces:**
- Consumes: `_map_rates(intent, action_kw, settings)` where `settings` is a `BatterySettings` instance with `.max_discharge_power_kw`
- Produces: same `(bool, int)` tuple as `_map_intent_to_rates` for LOAD_SUPPORT

- [ ] **Step 1: Write failing test**

Add a new test class in `core/bess/tests/unit/test_controller_coverage.py` (after `TestComputeRatesForPeriod`, before the `# ── SolaxController ──` comment):

```python
class TestSimulatorMapRates:
    """_map_rates must mirror _map_intent_to_rates for every intent."""

    def _settings(self):
        return BatterySettings()

    def test_load_support_partial(self):
        from core.bess.simulation.inverter_simulator import _map_rates
        grid_charge, rate = _map_rates("LOAD_SUPPORT", -1.5, self._settings())
        assert grid_charge is False
        assert rate == 10  # 1.5 / 15.0 * 100 = 10

    def test_load_support_full(self):
        from core.bess.simulation.inverter_simulator import _map_rates
        s = self._settings()
        grid_charge, rate = _map_rates("LOAD_SUPPORT", -s.max_discharge_power_kw, s)
        assert grid_charge is False
        assert rate == 100

    def test_load_support_zero(self):
        from core.bess.simulation.inverter_simulator import _map_rates
        grid_charge, rate = _map_rates("LOAD_SUPPORT", 0.0, self._settings())
        assert grid_charge is False
        assert rate == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest core/bess/tests/unit/test_controller_coverage.py::TestSimulatorMapRates -v
```

Expected: 3 tests FAIL (`assert 100 == 10`, etc.) — the current code returns 100 unconditionally.

- [ ] **Step 3: Implement the fix in `_map_rates`**

In `core/bess/simulation/inverter_simulator.py`, replace lines 52-53:

```python
    if intent == "LOAD_SUPPORT":
        return False, 100
```

with:

```python
    if intent == "LOAD_SUPPORT":
        if action_kw < -0.01:
            rate = min(
                100,
                max(0, int(abs(action_kw) / settings.max_discharge_power_kw * 100)),
            )
        else:
            rate = 0
        return False, rate
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest core/bess/tests/unit/test_controller_coverage.py::TestSimulatorMapRates -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Run fast suite to catch regressions**

```bash
pytest -m "not slow" -x -q
```

Expected: all fast tests PASS.

- [ ] **Step 6: Format and commit**

```bash
black . && ruff check --fix .
git add core/bess/simulation/inverter_simulator.py core/bess/tests/unit/test_controller_coverage.py
git commit -m "fix: mirror LOAD_SUPPORT discharge_rate scaling in inverter simulator"
```

---

### Task 3: Remove xfail from the four pacing scenarios

Now that R≈P holds for LOAD_SUPPORT, the four scenarios that were marked xfail in `test_scenarios.py` should pass. Remove the xfail gate and verify they do.

**Files:**
- Modify: `core/bess/tests/unit/test_scenarios.py:292-304`

**Interfaces:**
- Consumes: Task 1 + Task 2 fixes (controller + simulator both scale LOAD_SUPPORT rate)

- [ ] **Step 1: Remove the xfail block**

In `core/bess/tests/unit/test_scenarios.py`, delete lines 292-304 entirely (the `DISCHARGE_PACING_SCENARIOS` set and the `if scenario_name in DISCHARGE_PACING_SCENARIOS: pytest.xfail(...)` block):

```python
    # Known control-fidelity gap: LOAD_SUPPORT cannot pace battery discharge for
    # home support, so deep-evening-peak high-consumption days realize worse than
    # planned. Tracked in #147 — xfail (not silently tolerated) until fixed.
    DISCHARGE_PACING_SCENARIOS = {
        "synthetic_consumption_high_no_solar",
        "synthetic_seasonal_winter",
        "synthetic_consumption_ev_charging",
        "historical_2025_01_12_evening_peak_no_solar",
    }
    if scenario_name in DISCHARGE_PACING_SCENARIOS:
        pytest.xfail(
            f"discharge cannot be paced for home support (R-P={gap:+.2f} SEK) — #147"
        )
```

After deletion, line 292 should be the existing tolerance assertion:

```python
    tol = max(0.5, 0.01 * abs(planned_cost))
    assert abs(gap) <= tol, (
        f"{scenario_name}: realized != planned — R={sim.realized_cost:.2f}, "
        f"P={planned_cost:.2f}, gap {gap:+.3f} SEK exceeds tolerance {tol:.2f}"
    )
```

- [ ] **Step 2: Run the four previously-xfail scenarios in fast mode**

These scenarios run under the fast marker (they don't invoke the slow DP optimizer — they load pre-computed scenario JSON). Run them individually to confirm they pass:

```bash
pytest core/bess/tests/unit/test_scenarios.py -k "high_no_solar or seasonal_winter or ev_charging or evening_peak_no_solar" -v
```

Expected: 4 tests PASS (not xfail-pass, not xfail-fail — genuine PASS).

- [ ] **Step 3: Run the full scenario suite**

```bash
pytest core/bess/tests/unit/test_scenarios.py -v
```

Expected: all scenario tests PASS with no xfail markers remaining for pacing.

- [ ] **Step 4: Run fast suite**

```bash
pytest -m "not slow" -x -q
```

Expected: all fast tests PASS.

- [ ] **Step 5: Format and commit**

```bash
black . && ruff check --fix .
git add core/bess/tests/unit/test_scenarios.py
git commit -m "test: remove xfail for LOAD_SUPPORT pacing scenarios — fixed by #147"
```

---

## After All Tasks

Open a PR against `main`. Title: `fix: pace LOAD_SUPPORT discharge to match DP plan (issue #147)`. The PR closes #147.
