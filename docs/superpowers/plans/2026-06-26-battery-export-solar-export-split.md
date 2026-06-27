# BATTERY_EXPORT + SOLAR_EXPORT Intent Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename `EXPORT_ARBITRAGE` → `BATTERY_EXPORT` everywhere and introduce `SOLAR_EXPORT` for the zero-action solar-exporting case, fixing a bug where idle daytime periods were locked in `grid_first` mode.

**Architecture:** Three-phase change — (1) mechanical rename, then (2) new intent wired through classification → controller → simulator → schedule, then (3) frontend + docs. Each phase leaves tests green before the next begins.

**Tech Stack:** Python 3.11, pytest, TypeScript/React.

## Global Constraints

- Run tests from repo root with `.venv/bin/pytest`
- Fast suite: `.venv/bin/pytest -m "not slow"` (~3 s)
- Slow suite: `.venv/bin/pytest -m slow` (algorithm + E2E, ~30 min)
- Never edit `.venv/`, `build/`, `.claude/worktrees/`, `docs/bess-debug-*.md`, or `docs/superpowers/specs/2026-06-26-intent-solar-export-split-design.md`
- All commits use message style `type: short description` (no body needed)

---

## File Map

| File | Change |
|---|---|
| `core/bess/decision_intelligence.py` | Fix fallthrough line 443-444: `EXPORT_ARBITRAGE` → `SOLAR_EXPORT`; rename string literal line 433 |
| `core/bess/inverter_controller.py` | Rename `EXPORT_ARBITRAGE` key in 3 dicts + `_map_intent_to_rates`; add `SOLAR_EXPORT` entries |
| `core/bess/simulation/inverter_simulator.py` | Rename `EXPORT_ARBITRAGE` branch in `_map_rates`; add `SOLAR_EXPORT` to idle tuple |
| `core/bess/dp_schedule.py` | Rename `EXPORT_ARBITRAGE` in `get_hour_settings`; add `SOLAR_EXPORT` branch |
| `core/bess/dp_battery_algorithm.py` | Rename `EXPORT_ARBITRAGE` in `StrategicIntent` enum |
| `core/bess/models.py` | Rename string literal(s) |
| `core/bess/growatt_min_controller.py` | Rename string literal(s) |
| `core/bess/growatt_sph_controller.py` | Rename string literal(s) |
| `core/bess/solax_modbus_growatt_controller.py` | Rename string literal(s) |
| `core/bess/solax_controller.py` | Rename string literal(s) |
| `core/bess/battery_system_manager.py` | Rename string literal(s) |
| `core/bess/debug_data_exporter.py` | Rename string literal(s) |
| `core/bess/schedule_store.py` | Rename string literal(s) |
| `core/bess/daily_view_builder.py` | Rename string literal(s) |
| `core/bess/ai_chat.py` | Rename string literal(s) |
| `backend/api_dataclasses.py` | Rename string literal(s) |
| `backend/api.py` | Rename string literal(s) |
| `scripts/bess-mcp-server.py` | Rename string literal(s) |
| `core/bess/tests/unit/test_surplus_disposition.py` | Update 3 tests that defend old behavior; add 2 new tests |
| `core/bess/tests/unit/test_inverter_simulator.py` | Rename test + add `SOLAR_EXPORT` test |
| `core/bess/tests/unit/test_optimization_algorithm.py` | Update `valid_intents` set |
| Other 14 test files | Mechanical rename only |
| `frontend/src/components/BatteryModeTimeline.tsx` | Add `SOLAR_EXPORT` type + display entry; rename key |
| `frontend/src/components/SystemStatusCard.tsx` | Add `SOLAR_EXPORT` label; rename key |
| `frontend/src/components/InverterStatusDashboard.tsx` | Add `SOLAR_EXPORT` colour class; rename key |
| `docs/SOFTWARE_DESIGN.md` | Update intent table + rationale |
| `docs/agents/bess-knowledge.md` | Update intent descriptions table |

---

## Task 1: Mechanical rename EXPORT_ARBITRAGE → BATTERY_EXPORT

**Files:** All `.py`, `.ts`, `.tsx` files except the excluded list above.

**Interfaces:**
- Produces: `"BATTERY_EXPORT"` string used everywhere `"EXPORT_ARBITRAGE"` was

- [ ] **Step 1: Run the rename**

```bash
find . -type f \( -name "*.py" -o -name "*.ts" -o -name "*.tsx" \) \
  -not -path "./.venv/*" \
  -not -path "./.claude/*" \
  -not -path "./build/*" \
  -not -name "2026-06-26-intent-solar-export-split-design.md" \
  | xargs sed -i '' 's/EXPORT_ARBITRAGE/BATTERY_EXPORT/g'
```

- [ ] **Step 2: Verify no EXPORT_ARBITRAGE remains in code**

```bash
grep -r "EXPORT_ARBITRAGE" . \
  --include="*.py" --include="*.ts" --include="*.tsx" \
  --exclude-dir=.venv --exclude-dir=build --exclude-dir=.claude \
  | grep -v "bess-debug\|intent-solar-export-split-design"
```

Expected: no output.

- [ ] **Step 3: Run fast tests**

```bash
.venv/bin/pytest -m "not slow" -q
```

Expected: same pass count as before the rename, zero failures.

- [ ] **Step 4: Commit**

```bash
git add -p   # stage all changed .py .ts .tsx files
git commit -m "refactor: rename EXPORT_ARBITRAGE → BATTERY_EXPORT"
```

---

## Task 2: Add SOLAR_EXPORT to classification logic

**Files:**
- Modify: `core/bess/decision_intelligence.py:429-445`
- Modify: `core/bess/dp_battery_algorithm.py:111-119`
- Modify: `core/bess/tests/unit/test_surplus_disposition.py` (3 existing tests + 2 new)

**Interfaces:**
- Produces: `classify_strategic_intent` returns `"SOLAR_EXPORT"` when `power ≈ 0`, `grid_exported > 0.01`, `solar_to_grid > 0.01`

- [ ] **Step 1: Update the 3 tests in test_surplus_disposition.py that defend old behaviour**

These tests were written for issue #145 and now encode the wrong expected value. Replace them:

```python
# OLD test name: test_idle_with_surplus_classifies_as_export_arbitrage  (line ~99)
# NEW:
def test_idle_with_solar_surplus_classifies_as_solar_export():
    from core.bess.decision_intelligence import classify_strategic_intent

    # power 0, surplus exported, battery holds → SOLAR_EXPORT (not BATTERY_EXPORT)
    ed = EnergyData(
        solar_production=1.5,
        home_consumption=0.1,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=0.0,
        grid_exported=1.4,
        battery_soe_start=5.0,
        battery_soe_end=5.0,
    )
    assert classify_strategic_intent(0.0, ed) == "SOLAR_EXPORT"
    ed2 = EnergyData(
        solar_production=0.1,
        home_consumption=0.1,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=0.0,
        grid_exported=0.0,
        battery_soe_start=5.0,
        battery_soe_end=5.0,
    )
    assert classify_strategic_intent(0.0, ed2) == "IDLE"


# OLD test name: test_export_arbitrage_maps_to_grid_first_hold  (line ~132)
# NEW (just update the key name — BATTERY_EXPORT still maps to grid_first):
def test_battery_export_maps_to_grid_first_hold():
    from core.bess.inverter_controller import InverterController
    from core.bess.simulation.inverter_simulator import derive_control_command

    bs = make_battery_settings()
    assert InverterController.INTENT_TO_MODE["BATTERY_EXPORT"] == "grid_first"
    cmd = derive_control_command("BATTERY_EXPORT", battery_action_kw=0.0, settings=bs)
    assert cmd.battery_mode == "grid_first"
    assert cmd.grid_charge is False
    assert cmd.discharge_rate_pct == 0


# OLD test name: test_small_surplus_at_idle_classifies_as_export_arbitrage  (line ~235)
# NEW:
def test_small_solar_surplus_at_idle_classifies_as_solar_export():
    """A power-0 period with exportable surplus classifies as SOLAR_EXPORT → load_first.
    Battery can charge from solar naturally; grid_first is only for active battery discharge."""
    from core.bess.decision_intelligence import classify_strategic_intent

    ed = EnergyData(
        solar_production=0.3,
        home_consumption=0.2,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=0.0,
        grid_exported=0.1,
        battery_soe_start=5.0,
        battery_soe_end=5.0,
    )
    assert classify_strategic_intent(0.0, ed) == "SOLAR_EXPORT"
```

Also add 2 new tests at the end of `test_surplus_disposition.py`:

```python
def test_solar_export_maps_to_load_first():
    from core.bess.inverter_controller import InverterController
    from core.bess.simulation.inverter_simulator import derive_control_command

    bs = make_battery_settings()
    assert InverterController.INTENT_TO_MODE["SOLAR_EXPORT"] == "load_first"
    cmd = derive_control_command("SOLAR_EXPORT", battery_action_kw=0.0, settings=bs)
    assert cmd.battery_mode == "load_first"
    assert cmd.grid_charge is False
    assert cmd.discharge_rate_pct == 0


def test_battery_export_active_discharge_still_grid_first():
    """BATTERY_EXPORT with real discharge action → grid_first + action-derived rate."""
    from core.bess.simulation.inverter_simulator import derive_control_command

    bs = make_battery_settings(max_discharge_power_kw=10.0)
    cmd = derive_control_command("BATTERY_EXPORT", battery_action_kw=-5.0, settings=bs)
    assert cmd.battery_mode == "grid_first"
    assert cmd.discharge_rate_pct == 50
    assert cmd.grid_charge is False
```

- [ ] **Step 2: Run tests to confirm they fail for the right reason**

```bash
.venv/bin/pytest core/bess/tests/unit/test_surplus_disposition.py -v
```

Expected: `test_idle_with_solar_surplus_classifies_as_solar_export`, `test_small_solar_surplus_at_idle_classifies_as_solar_export`, `test_solar_export_maps_to_load_first` FAIL with `AssertionError` (returned `"BATTERY_EXPORT"` not `"SOLAR_EXPORT"`). `test_battery_export_maps_to_grid_first_hold` should PASS (pure rename, already done).

- [ ] **Step 3: Fix the fallthrough in `decision_intelligence.py:429-445`**

Replace the function's docstring return line and the fallthrough:

```python
def classify_strategic_intent(power: float, energy_data: EnergyData) -> str:
    """Classify the strategic intent of a battery action based on power and energy flows.

    Intent controls hardware behavior via the Growatt TOU schedule and is displayed
    to the user in the UI. Must accurately reflect the actual action.

    The main branches use ``_POWER_THRESHOLD_KW`` (0.1 kW) to filter noise.
    Fallthrough branches catch passive solar charging and small residual
    discharge that fall below the threshold.

    Args:
        power: Battery power action (+ charge, - discharge) in kW.
        energy_data: Complete energy flow data for the period.

    Returns:
        One of: GRID_CHARGING, SOLAR_STORAGE, LOAD_SUPPORT, BATTERY_EXPORT, SOLAR_EXPORT, IDLE.
    """
    if power < -_POWER_THRESHOLD_KW:  # Discharging
        if energy_data.battery_to_grid > 0.1:
            return "BATTERY_EXPORT"
        return "LOAD_SUPPORT"
    elif power > _POWER_THRESHOLD_KW:  # Charging
        if energy_data.grid_to_battery > energy_data.solar_to_battery:
            return "GRID_CHARGING"
        return "SOLAR_STORAGE"
    elif energy_data.battery_charged > 0.01:
        return "SOLAR_STORAGE"
    elif energy_data.battery_discharged > 0.01:
        return "LOAD_SUPPORT"
    elif energy_data.grid_exported > 0.01 and energy_data.solar_to_grid > 0.01:
        return "SOLAR_EXPORT"
    return "IDLE"
```

- [ ] **Step 4: Update `StrategicIntent` enum in `dp_battery_algorithm.py:111-119`**

```python
class StrategicIntent(Enum):
    """Strategic intents for battery actions, determined at decision time."""

    # Primary intents (mutually exclusive)
    GRID_CHARGING = "GRID_CHARGING"    # Storing cheap grid energy for arbitrage
    SOLAR_STORAGE = "SOLAR_STORAGE"    # Storing excess solar for later use
    LOAD_SUPPORT = "LOAD_SUPPORT"      # Discharging to meet home load
    BATTERY_EXPORT = "BATTERY_EXPORT"  # Discharging battery to grid for profit
    SOLAR_EXPORT = "SOLAR_EXPORT"      # Solar surplus exporting to grid, battery idle
    IDLE = "IDLE"                      # No significant action
```

- [ ] **Step 5: Run tests — classification tests should pass now**

```bash
.venv/bin/pytest core/bess/tests/unit/test_surplus_disposition.py -v
```

Expected: all pass. `test_solar_export_maps_to_load_first` still FAILS (controller not updated yet — that's Task 3).

- [ ] **Step 6: Commit**

```bash
git add core/bess/decision_intelligence.py \
        core/bess/dp_battery_algorithm.py \
        core/bess/tests/unit/test_surplus_disposition.py
git commit -m "feat: add SOLAR_EXPORT intent, fix fallthrough in classify_strategic_intent"
```

---

## Task 3: Wire SOLAR_EXPORT through controller, simulator, and schedule

**Files:**
- Modify: `core/bess/inverter_controller.py:33-56, 116-163`
- Modify: `core/bess/simulation/inverter_simulator.py:43-70`
- Modify: `core/bess/dp_schedule.py:71-86`
- Modify: `core/bess/tests/unit/test_inverter_simulator.py`
- Modify: `core/bess/tests/unit/test_optimization_algorithm.py:222-231`

**Interfaces:**
- Consumes: `"SOLAR_EXPORT"` string from Task 2
- Produces: `INTENT_TO_MODE["SOLAR_EXPORT"] == "load_first"`, `_map_rates("SOLAR_EXPORT", ...) == (False, 0)`

- [ ] **Step 1: Rename test in `test_inverter_simulator.py` and add SOLAR_EXPORT test**

Find `test_derive_command_export_arbitrage_scales_discharge` and rename to `test_derive_command_battery_export_scales_discharge`. Change the intent string inside it:

```python
def test_derive_command_battery_export_scales_discharge():
    bs = make_battery_settings(max_discharge_power_kw=10.0)
    # planned discharge of 5 kW -> grid_first, discharge ~50%
    cmd = derive_control_command(
        "BATTERY_EXPORT", battery_action_kw=-5.0, settings=bs
    )
    assert cmd.battery_mode == "grid_first"
    assert cmd.discharge_rate_pct == 50
    assert cmd.grid_charge is False
```

Add a new test after it:

```python
def test_derive_command_solar_export_is_load_first_no_discharge():
    bs = make_battery_settings()
    cmd = derive_control_command("SOLAR_EXPORT", battery_action_kw=0.0, settings=bs)
    assert cmd.battery_mode == "load_first"
    assert cmd.discharge_rate_pct == 0
    assert cmd.grid_charge is False
```

- [ ] **Step 2: Update `valid_intents` set in `test_optimization_algorithm.py:222-231`**

```python
    valid_intents = {
        "IDLE",
        "GRID_CHARGING",
        "SOLAR_STORAGE",
        "LOAD_SUPPORT",
        "BATTERY_EXPORT",
        "SOLAR_EXPORT",
    }
```

- [ ] **Step 3: Run to confirm new tests fail**

```bash
.venv/bin/pytest core/bess/tests/unit/test_inverter_simulator.py::test_derive_command_solar_export_is_load_first_no_discharge -v
```

Expected: FAIL — `ValueError: Unknown strategic intent: SOLAR_EXPORT`

- [ ] **Step 4: Add SOLAR_EXPORT to `inverter_controller.py`**

In `INTENT_TO_CONTROL` (around line 33), add after the `BATTERY_EXPORT` entry:

```python
        "SOLAR_EXPORT": {
            "grid_charge": False,
            "charge_rate": 100,
            "discharge_rate": 0,
        },
```

In `INTENT_TO_MODE` (around line 50), add:

```python
        "SOLAR_EXPORT": "load_first",
```

In `INTENT_DESCRIPTIONS` (around line 58), add:

```python
        "SOLAR_EXPORT": "Solar surplus exporting directly to grid",
```

In `_map_intent_to_rates` (around line 160), add before the `raise ValueError`:

```python
        elif intent == "SOLAR_EXPORT":
            return False, 0
```

Also update the class docstring at lines 24-28:

```python
    - GRID_CHARGING    → grid_charge=True,  discharge_rate=0
    - SOLAR_STORAGE    → grid_charge=False, discharge_rate=0
    - LOAD_SUPPORT     → grid_charge=False, discharge_rate=<action-derived>
    - BATTERY_EXPORT   → grid_charge=False, discharge_rate=<action-derived>
    - SOLAR_EXPORT     → grid_charge=False, discharge_rate=0
    - IDLE             → grid_charge=False, discharge_rate=0
```

- [ ] **Step 5: Add SOLAR_EXPORT to `inverter_simulator.py:_map_rates`**

Change the `SOLAR_STORAGE`/`IDLE` tuple line (around line 50):

```python
    if intent in ("SOLAR_STORAGE", "IDLE", "SOLAR_EXPORT"):
        return False, 0
```

- [ ] **Step 6: Add SOLAR_EXPORT to `dp_schedule.py:get_hour_settings`**

In the intent dispatch block (around line 71), add before the `else: # IDLE` branch:

```python
        elif intent == "BATTERY_EXPORT":
            state = "grid_first"  # Priority to grid export
            grid_charge = False
        elif intent == "SOLAR_EXPORT":
            state = "idle"
            grid_charge = False
        else:  # IDLE
            state = "idle"
            grid_charge = False
```

(The old `elif intent == "BATTERY_EXPORT"` line from Task 1's rename already handles the first branch — just add the `SOLAR_EXPORT` elif above the else.)

- [ ] **Step 7: Run fast tests**

```bash
.venv/bin/pytest -m "not slow" -q
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add core/bess/inverter_controller.py \
        core/bess/simulation/inverter_simulator.py \
        core/bess/dp_schedule.py \
        core/bess/tests/unit/test_inverter_simulator.py \
        core/bess/tests/unit/test_optimization_algorithm.py
git commit -m "feat: wire SOLAR_EXPORT through controller, simulator, and schedule"
```

---

## Task 4: Frontend — add SOLAR_EXPORT, rename BATTERY_EXPORT

**Files:**
- Modify: `frontend/src/components/BatteryModeTimeline.tsx`
- Modify: `frontend/src/components/SystemStatusCard.tsx`
- Modify: `frontend/src/components/InverterStatusDashboard.tsx`

**Interfaces:**
- Consumes: `"SOLAR_EXPORT"` and `"BATTERY_EXPORT"` as intent strings from the API

- [ ] **Step 1: Update `BatteryModeTimeline.tsx`**

Find the `StrategicIntent` type and the display config map. Make these changes:

```typescript
// Type union — add SOLAR_EXPORT
type StrategicIntent =
  | 'GRID_CHARGING'
  | 'SOLAR_STORAGE'
  | 'LOAD_SUPPORT'
  | 'BATTERY_EXPORT'
  | 'SOLAR_EXPORT'
  | 'IDLE';

// Display map — rename BATTERY_EXPORT entry, add SOLAR_EXPORT
const INTENT_DISPLAY: Record<StrategicIntent, { label: string; color: string; darkColor: string }> = {
  GRID_CHARGING:  { label: 'Grid Charging',   color: '#3b82f6', darkColor: '#60a5fa' },
  SOLAR_STORAGE:  { label: 'Solar Storage',   color: '#f59e0b', darkColor: '#fbbf24' },
  LOAD_SUPPORT:   { label: 'Load Support',    color: '#8b5cf6', darkColor: '#a78bfa' },
  BATTERY_EXPORT: { label: 'Battery Export',  color: '#22c55e', darkColor: '#4ade80' },
  SOLAR_EXPORT:   { label: 'Solar Export',    color: '#84cc16', darkColor: '#a3e635' },
  IDLE:           { label: 'Idle',            color: '#6b7280', darkColor: '#9ca3af' },
};

// INTENT_ORDER — add SOLAR_EXPORT
const INTENT_ORDER: StrategicIntent[] = [
  'GRID_CHARGING', 'SOLAR_STORAGE', 'LOAD_SUPPORT', 'BATTERY_EXPORT', 'SOLAR_EXPORT', 'IDLE'
];
```

(The existing map key may be named differently — find the object that maps intent strings to `label`/`color` and apply the equivalent changes.)

- [ ] **Step 2: Update `SystemStatusCard.tsx`**

Find the intent→label map and add/rename:

```typescript
// rename key, add SOLAR_EXPORT
BATTERY_EXPORT: 'Selling to Grid',
SOLAR_EXPORT:   'Solar Exporting',
```

- [ ] **Step 3: Update `InverterStatusDashboard.tsx`**

Find the intent→CSS class map and add/rename:

```typescript
// rename key, add SOLAR_EXPORT
'BATTERY_EXPORT': 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300',
'SOLAR_EXPORT':   'bg-lime-100 text-lime-800 dark:bg-lime-900 dark:text-lime-300',
```

- [ ] **Step 4: TypeScript build check**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: clean build, no type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/BatteryModeTimeline.tsx \
        frontend/src/components/SystemStatusCard.tsx \
        frontend/src/components/InverterStatusDashboard.tsx
git commit -m "feat: add SOLAR_EXPORT to frontend intent display maps"
```

---

## Task 5: Update documentation

**Files:**
- Modify: `docs/SOFTWARE_DESIGN.md`
- Modify: `docs/agents/bess-knowledge.md`

- [ ] **Step 1: Update intent table in `SOFTWARE_DESIGN.md`**

Find the table around line 330-336 and replace:

```markdown
| Intent | Battery Mode | Grid Charge | Discharge Rate |
|---|---|---|---|
| GRID_CHARGING | battery_first | On | 0% |
| SOLAR_STORAGE | load_first | Off | 0% |
| LOAD_SUPPORT | load_first | Off | action-derived |
| BATTERY_EXPORT | grid_first | Off | action-derived |
| SOLAR_EXPORT | load_first | Off | 0% |
| IDLE | load_first | Off | 0% |
```

Replace the "Why SOLAR_STORAGE and IDLE share the same inverter settings" paragraph with:

```markdown
**Why SOLAR_EXPORT and IDLE share the same inverter settings**: Both use `load_first`
with no discharge. Solar exports naturally when surplus exceeds consumption in `load_first`
mode — no special mode is needed. `SOLAR_EXPORT` exists as a distinct intent solely for
UI display (distinguishing "solar is actively exporting" from "truly nothing happening").

**Why BATTERY_EXPORT requires grid_first**: The inverter must route battery discharge
toward the grid rather than the home. `load_first` with discharge would serve home load
first; only `grid_first` guarantees battery energy reaches the grid.

**Why the old EXPORT_ARBITRAGE fallthrough was removed**: The previous fallthrough
returned `EXPORT_ARBITRAGE` (→ `grid_first`) for any period where solar was exporting
with the battery idle. This locked the inverter in `grid_first` with `discharge_rate=0`
during long daytime windows — preventing the battery from supporting house load when
solar was temporarily insufficient. The correct mode for an idle battery is always
`load_first`.
```

- [ ] **Step 2: Update `bess-knowledge.md`**

Find the intent table (around line 73-85) and replace:

```markdown
| Intent | Condition | What it means |
|--------|-----------|---------------|
| **GRID_CHARGING** | grid_to_battery >= 0.1 kWh | Buying cheap grid electricity to store in battery |
| **SOLAR_STORAGE** | solar_to_battery > 0.1 kWh, grid_to_battery < 0.1 | Storing excess solar production for later |
| **LOAD_SUPPORT** | battery_to_home > 0.1 kWh, battery_to_grid <= 0.1 | Using battery to power home (avoid expensive grid) |
| **BATTERY_EXPORT** | battery_to_grid > 0.1 kWh | Selling stored battery energy to grid at high prices |
| **SOLAR_EXPORT** | power ≈ 0, solar_to_grid > 0.01 kWh | Solar surplus exporting directly to grid, battery idle |
| **IDLE** | No significant battery flows | No profitable action — direct solar/grid consumption |

**Hardware mapping**:
- GRID_CHARGING → battery_first mode + grid charge ON
- LOAD_SUPPORT → load_first mode
- BATTERY_EXPORT → grid_first mode (battery discharge to grid)
- SOLAR_STORAGE / SOLAR_EXPORT / IDLE → load_first mode (solar serves home first)
```

- [ ] **Step 3: Commit**

```bash
git add docs/SOFTWARE_DESIGN.md docs/agents/bess-knowledge.md
git commit -m "docs: update intent table for BATTERY_EXPORT + SOLAR_EXPORT split"
```

---

## Task 6: Full test suite

- [ ] **Step 1: Fast suite — must be green**

```bash
.venv/bin/pytest -m "not slow" -q 2>&1 | tail -10
```

Expected: all pass. If any failures, fix before proceeding.

- [ ] **Step 2: Slow suite — algorithm + E2E inverter tests**

```bash
.venv/bin/pytest -m slow -v 2>&1 | tee /tmp/slow-test-results.txt
tail -30 /tmp/slow-test-results.txt
```

Expected: all pass. Pay particular attention to:
- `test_plan_faithfulness.py` — should pass unchanged (controlled scenario has no solar)
- Any scenario test with solar surplus + zero-action periods: if realized cost differs slightly from planned, check whether the battery was non-full during those periods. A small upward delta on the SOLAR_EXPORT period offset by a downward delta on later discharge periods is expected correct behaviour, not a regression. Update assertion tolerances if needed.

- [ ] **Step 3: Commit if any tolerance adjustments were needed**

```bash
git add core/bess/tests/
git commit -m "test: adjust plan-faithfulness tolerances for SOLAR_EXPORT load_first behaviour"
```

Only commit this if Step 2 required changes. If all passed without changes, skip.
