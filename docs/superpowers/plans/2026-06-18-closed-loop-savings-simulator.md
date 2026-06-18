# Closed-loop Savings Simulator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pure scenario simulator that executes the control commands derived from an optimizer plan and computes the *realized* savings, so a control change can be verified to the cent (`realized == planned`, and A/B `delta == 0`).

**Architecture:** The simulator reuses the optimizer's own primitives for accounting parity. The *only* new logic is `mode_to_power` — what battery power each Growatt-MIN inverter mode produces given conditions. That power is then fed through the existing `_state_transition` (SoC) and `_build_period_data` (flows + economics), so if `mode_to_power` reproduces the plan's power, realized economics equal planned economics exactly. Execution-only (no optimizer re-run loop). Growatt MIN / cloud only.

**Tech Stack:** Python 3, pytest, NumPy. Reuses `core/bess/dp_battery_algorithm.py`, `core/bess/models.py`, `core/bess/inverter_controller.py`, `core/bess/settings.py`.

**Spec:** `docs/superpowers/specs/2026-06-18-closed-loop-savings-simulator-design.md`

---

## File Structure

- Create `core/bess/simulation/__init__.py` — package marker.
- Create `core/bess/simulation/inverter_simulator.py` — `ControlCommand`, `derive_control_command`, `mode_to_power`, `simulate`, `SimulationResult`.
- Create `core/bess/simulation/verification.py` — `verify_plan_faithfulness`, `ab_compare` (the harnesses that gate control changes).
- Create `core/bess/tests/unit/test_inverter_simulator.py` — mechanics, hand-computed.
- Create `core/bess/tests/integration/test_plan_faithfulness.py` — `R == P` on a controlled scenario + A/B sanity + the dithering diagnostic.

Internal optimizer functions (`_state_transition`, `_build_period_data`) are reused deliberately for accounting parity; that coupling is the point, not an accident.

---

### Task 1: `ControlCommand` + `derive_control_command`

**Files:**
- Create: `core/bess/simulation/__init__.py`
- Create: `core/bess/simulation/inverter_simulator.py`
- Test: `core/bess/tests/unit/test_inverter_simulator.py`

- [ ] **Step 1: Write the failing test**

```python
# core/bess/tests/unit/test_inverter_simulator.py
from core.bess.simulation.inverter_simulator import ControlCommand, derive_control_command
from core.bess.tests.helpers import make_battery_settings  # see Step 3 note

def test_derive_command_export_arbitrage_scales_discharge():
    bs = make_battery_settings(max_discharge_power_kw=10.0)
    # planned discharge of 5 kW -> grid_first, discharge ~50%
    cmd = derive_control_command("EXPORT_ARBITRAGE", battery_action_kw=-5.0, settings=bs)
    assert cmd.battery_mode == "grid_first"
    assert cmd.discharge_rate_pct == 50
    assert cmd.grid_charge is False

def test_derive_command_solar_storage_is_load_first_no_discharge():
    bs = make_battery_settings()
    cmd = derive_control_command("SOLAR_STORAGE", battery_action_kw=0.4, settings=bs)
    assert cmd.battery_mode == "load_first"
    assert cmd.discharge_rate_pct == 0
    assert cmd.grid_charge is False

def test_derive_command_grid_charging_enables_grid_charge():
    bs = make_battery_settings()
    cmd = derive_control_command("GRID_CHARGING", battery_action_kw=4.0, settings=bs)
    assert cmd.battery_mode == "battery_first"
    assert cmd.grid_charge is True
```

> Note: `make_battery_settings` is a thin helper. If it does not already exist in `core/bess/tests/helpers.py`, add it in this step:
> ```python
> def make_battery_settings(**overrides):
>     from core.bess.settings import BatterySettings
>     defaults = dict(total_capacity=20.0, min_soc=11.0, max_soc=100.0,
>                     max_charge_power_kw=10.0, max_discharge_power_kw=10.0,
>                     efficiency_charge=0.97, efficiency_discharge=0.95,
>                     cycle_cost_per_kwh=0.40)
>     defaults.update(overrides)
>     return BatterySettings(**defaults)
> ```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/bess/tests/unit/test_inverter_simulator.py -v`
Expected: FAIL with `ModuleNotFoundError: core.bess.simulation`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/bess/simulation/__init__.py
```
(empty file)

```python
# core/bess/simulation/inverter_simulator.py
"""Pure scenario simulator: execute control commands derived from a plan and
compute realized flows/savings. Growatt MIN / cloud, execution-only.

Reuses the optimizer's own primitives (_state_transition, _build_period_data)
so that faithful control yields cent-exact equality with the plan.
"""
from dataclasses import dataclass

from core.bess.inverter_controller import InverterController
from core.bess.settings import BatterySettings


@dataclass(frozen=True)
class ControlCommand:
    """The hardware control state applied for one period (Growatt MIN)."""
    battery_mode: str          # "load_first" | "grid_first" | "battery_first"
    discharge_rate_pct: int    # 0..100
    grid_charge: bool


def derive_control_command(
    strategic_intent: str, battery_action_kw: float, settings: BatterySettings
) -> ControlCommand:
    """Map a plan period (intent + planned battery power) to the applied command,
    reusing the production controller mappings so the simulator executes exactly
    what the real controller would write."""
    battery_mode = InverterController.INTENT_TO_MODE.get(strategic_intent, "load_first")
    # Reuse the production intent->rates mapping (grid_charge, discharge_rate_pct).
    grid_charge, discharge_rate_pct = _map_rates(strategic_intent, battery_action_kw, settings)
    return ControlCommand(
        battery_mode=battery_mode,
        discharge_rate_pct=discharge_rate_pct,
        grid_charge=grid_charge,
    )


def _map_rates(intent: str, action_kw: float, settings: BatterySettings) -> tuple[bool, int]:
    """Mirror of InverterController._map_intent_to_rates without needing a live
    controller instance (that method is an instance method bound to hardware)."""
    if intent == "GRID_CHARGING":
        return True, 0
    if intent in ("SOLAR_STORAGE", "IDLE"):
        return False, 0
    if intent == "LOAD_SUPPORT":
        return False, 100
    if intent == "EXPORT_ARBITRAGE":
        if action_kw < -0.01:
            rate = min(100, max(0, int(abs(action_kw) / settings.max_discharge_power_kw * 100)))
        else:
            rate = 0
        return False, rate
    raise ValueError(f"Unknown strategic intent: {intent}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest core/bess/tests/unit/test_inverter_simulator.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add core/bess/simulation/__init__.py core/bess/simulation/inverter_simulator.py core/bess/tests/unit/test_inverter_simulator.py core/bess/tests/helpers.py
git commit -m "feat(sim): ControlCommand + derive_control_command for Growatt MIN"
```

---

### Task 2: `mode_to_power` — the only new physics

**Files:**
- Modify: `core/bess/simulation/inverter_simulator.py`
- Test: `core/bess/tests/unit/test_inverter_simulator.py`

- [ ] **Step 1: Write the failing test**

```python
from core.bess.simulation.inverter_simulator import mode_to_power, ControlCommand

def test_grid_first_discharges_to_grid_at_rate():
    bs = make_battery_settings(max_discharge_power_kw=10.0)  # 10kW * 0.25h = 2.5kWh/period
    cmd = ControlCommand("grid_first", discharge_rate_pct=50, grid_charge=False)
    # plenty of stored energy, 50% rate -> 5 kW discharge
    p = mode_to_power(cmd, solar=0.0, home=0.0, soe=15.0, settings=bs, dt=0.25)
    assert p == -5.0

def test_load_first_no_discharge_passively_stores_surplus_power_zero():
    bs = make_battery_settings()
    cmd = ControlCommand("load_first", discharge_rate_pct=0, grid_charge=False)
    # SOLAR_STORAGE/IDLE: power 0; _state_transition does the passive solar charge
    p = mode_to_power(cmd, solar=1.9, home=0.2, soe=3.0, settings=bs, dt=0.25)
    assert p == 0.0

def test_load_support_discharges_to_cover_home_deficit():
    bs = make_battery_settings(max_discharge_power_kw=10.0)
    cmd = ControlCommand("load_first", discharge_rate_pct=100, grid_charge=False)
    # home 1.0 kWh, no solar -> need 1.0 kWh delivered over 0.25h = 4 kW, within rate & energy
    p = mode_to_power(cmd, solar=0.0, home=1.0, soe=15.0, settings=bs, dt=0.25)
    assert p == -4.0

def test_battery_first_charges_at_max_rate():
    bs = make_battery_settings(max_charge_power_kw=10.0)
    cmd = ControlCommand("battery_first", discharge_rate_pct=0, grid_charge=True)
    p = mode_to_power(cmd, solar=0.0, home=0.0, soe=5.0, settings=bs, dt=0.25)
    assert p == 10.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/bess/tests/unit/test_inverter_simulator.py -k mode_to_power -v`
Expected: FAIL with `ImportError: cannot import name 'mode_to_power'`.

- [ ] **Step 3: Write minimal implementation**

```python
def mode_to_power(
    command: ControlCommand,
    solar: float,
    home: float,
    soe: float,
    settings: BatterySettings,
    dt: float,
) -> float:
    """Battery power (kW; + charge, - discharge) the Growatt MIN inverter applies
    for one period under the given command and conditions. This is the v1 mode
    policy; check 1 (plan-faithfulness) validates/refines it."""
    if command.battery_mode == "battery_first":  # grid charging
        room = settings.max_soe_kwh - soe
        max_charge_kwh = min(settings.max_charge_power_kw * dt, room / settings.efficiency_charge)
        return max(0.0, max_charge_kwh) / dt

    if command.battery_mode == "grid_first":  # export arbitrage: discharge to grid at rate
        available = max(0.0, soe - settings.min_soe_kwh)
        rate_kw = settings.max_discharge_power_kw * command.discharge_rate_pct / 100.0
        delivered_kwh = min(rate_kw * dt, available * settings.efficiency_discharge)
        return -delivered_kwh / dt

    # load_first
    if command.discharge_rate_pct > 0:  # LOAD_SUPPORT: cover home deficit
        deficit = max(0.0, home - solar)
        available = max(0.0, soe - settings.min_soe_kwh)
        rate_kw = settings.max_discharge_power_kw * command.discharge_rate_pct / 100.0
        delivered_kwh = min(deficit, rate_kw * dt, available * settings.efficiency_discharge)
        return -delivered_kwh / dt

    # SOLAR_STORAGE / IDLE: power 0 -> _state_transition stores surplus solar passively
    return 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest core/bess/tests/unit/test_inverter_simulator.py -k mode_to_power -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add core/bess/simulation/inverter_simulator.py core/bess/tests/unit/test_inverter_simulator.py
git commit -m "feat(sim): mode_to_power policy for Growatt MIN modes"
```

---

### Task 3: `simulate` — per-period execution reusing optimizer primitives

**Files:**
- Modify: `core/bess/simulation/inverter_simulator.py`
- Test: `core/bess/tests/unit/test_inverter_simulator.py`

- [ ] **Step 1: Write the failing test**

```python
from core.bess.simulation.inverter_simulator import simulate, ControlCommand

def test_simulate_idle_day_costs_grid_import_only():
    bs = make_battery_settings()
    n = 4
    commands = [ControlCommand("load_first", 0, False)] * n  # idle/store
    solar = [0.0] * n
    home = [1.0] * n
    buy = [2.0] * n
    sell = [1.0] * n
    res = simulate(commands, solar, home, buy, sell, initial_soe=3.0,
                   settings=bs, dt=0.25)
    # no solar, no battery action -> all home from grid: 4 * 1.0 kWh * 2.0 = 8.0
    assert res.realized_cost == 8.0
    assert len(res.period_data) == n
    assert res.period_data[0].energy.battery_soe_start == 3.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/bess/tests/unit/test_inverter_simulator.py -k simulate -v`
Expected: FAIL with `ImportError: cannot import name 'simulate'`.

- [ ] **Step 3: Write minimal implementation**

```python
from core.bess.dp_battery_algorithm import _build_period_data, _state_transition
from core.bess.models import PeriodData  # noqa: F401  (type clarity)


@dataclass
class SimulationResult:
    period_data: list           # list[PeriodData]
    realized_cost: float        # sum of economic.hourly_cost


def simulate(
    commands: list[ControlCommand],
    solar_production: list[float],
    home_consumption: list[float],
    buy_price: list[float],
    sell_price: list[float],
    initial_soe: float,
    settings: BatterySettings,
    dt: float,
    currency: str = "SEK",
) -> SimulationResult:
    """Execute the command sequence period-by-period, carrying SoC forward, using
    the optimizer's own _state_transition + _build_period_data for accounting
    parity. Returns realized PeriodData and total realized cost."""
    soe = initial_soe
    period_data = []
    for t, cmd in enumerate(commands):
        power = mode_to_power(cmd, solar_production[t], home_consumption[t], soe, settings, dt)
        next_soe = _state_transition(
            soe, power, settings, dt,
            solar_production=solar_production[t],
            home_consumption=home_consumption[t],
        )
        pd = _build_period_data(
            power=power, soe=soe, next_soe=next_soe, period=t,
            home_consumption=home_consumption[t], battery_settings=settings, dt=dt,
            buy_price=buy_price, sell_price=sell_price,
            solar_production=solar_production[t], new_cost_basis=settings.cycle_cost_per_kwh,
            currency=currency,
        )
        period_data.append(pd)
        soe = next_soe
    realized_cost = sum(pd.economic.hourly_cost for pd in period_data)
    return SimulationResult(period_data=period_data, realized_cost=realized_cost)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest core/bess/tests/unit/test_inverter_simulator.py -k simulate -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/bess/simulation/inverter_simulator.py core/bess/tests/unit/test_inverter_simulator.py
git commit -m "feat(sim): simulate() execution loop reusing optimizer primitives"
```

---

### Task 4: `verify_plan_faithfulness` — realized == planned (check 1)

**Files:**
- Create: `core/bess/simulation/verification.py`
- Test: `core/bess/tests/integration/test_plan_faithfulness.py`

- [ ] **Step 1: Write the failing test**

```python
# core/bess/tests/integration/test_plan_faithfulness.py
from core.bess.simulation.verification import verify_plan_faithfulness
from core.bess.tests.helpers import make_battery_settings

def _controlled_scenario():
    """A scenario whose optimal plan uses only faithfully-executable actions:
    night grid-charge at a clear low price, evening discharge-to-grid at a clear
    high price, no fractional solar-storage. dt = 1.0h for simple arithmetic."""
    n = 6
    buy =  [0.5, 0.5, 2.0, 2.0, 1.0, 1.0]
    sell = [0.4, 0.4, 1.8, 1.8, 0.9, 0.9]
    solar = [0.0] * n
    home = [0.5] * n
    return buy, sell, solar, home

def test_realized_equals_planned_on_controlled_scenario():
    bs = make_battery_settings()
    buy, sell, solar, home = _controlled_scenario()
    planned_cost, realized_cost, per_period = verify_plan_faithfulness(
        buy_price=buy, sell_price=sell, solar=solar, home=home,
        initial_soe=3.0, settings=bs, dt=1.0,
    )
    # cent-exact: faithful control reproduces the plan
    assert round(realized_cost, 2) == round(planned_cost, 2), (
        f"R={realized_cost} != P={planned_cost}; per-period deltas: {per_period}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/bess/tests/integration/test_plan_faithfulness.py -k controlled -v`
Expected: FAIL with `ModuleNotFoundError: core.bess.simulation.verification`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/bess/simulation/verification.py
"""Verification harnesses: plan-faithfulness (R == P) and A/B economic gate."""
from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.settings import BatterySettings
from core.bess.simulation.inverter_simulator import (
    ControlCommand, derive_control_command, simulate,
)


def commands_from_result(result, settings: BatterySettings) -> list[ControlCommand]:
    """Derive the applied control command for each planned period."""
    return [
        derive_control_command(
            pd.decision.strategic_intent, pd.decision.battery_action / _dt(pd), settings
        )
        for pd in result.period_data
    ]


def _dt(pd) -> float:
    # battery_action is energy (kWh) = power(kW) * dt; recover dt from period span.
    # All scenarios pass a fixed dt; verify_plan_faithfulness supplies it explicitly,
    # so commands_from_result is only used internally with that dt (see below).
    raise NotImplementedError  # replaced by closure in verify_plan_faithfulness


def verify_plan_faithfulness(
    buy_price, sell_price, solar, home, initial_soe, settings, dt,
):
    """Run optimizer -> derive commands -> simulate -> compare. Returns
    (planned_cost, realized_cost, per_period_deltas)."""
    result = optimize_battery_schedule(
        buy_price=buy_price, sell_price=sell_price, home_consumption=home,
        solar_production=solar, initial_soe=initial_soe, battery_settings=settings,
        period_duration_hours=dt,
    )
    commands = [
        derive_control_command(
            pd.decision.strategic_intent, pd.decision.battery_action / dt, settings
        )
        for pd in result.period_data
    ]
    sim = simulate(commands, solar, home, buy_price, sell_price, initial_soe, settings, dt)
    planned_cost = result.economic_summary.battery_solar_cost
    realized_cost = sim.realized_cost
    per_period_deltas = [
        round(sim.period_data[i].economic.hourly_cost - result.period_data[i].economic.hourly_cost, 4)
        for i in range(len(result.period_data))
    ]
    return planned_cost, realized_cost, per_period_deltas
```

> Note: delete the unused `commands_from_result`/`_dt` stub if it stays unused — keep only `verify_plan_faithfulness`. It is shown above only to make the dt-from-energy subtlety explicit; the working code derives power as `battery_action / dt` with the known `dt`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest core/bess/tests/integration/test_plan_faithfulness.py -k controlled -v`
Expected: PASS. If it FAILS, the per-period deltas in the assertion message pinpoint which intents the command does not faithfully carry — that is a genuine finding (see Task 6); capture it and raise with the team before adjusting `mode_to_power`.

- [ ] **Step 5: Commit**

```bash
git add core/bess/simulation/verification.py core/bess/tests/integration/test_plan_faithfulness.py
git commit -m "feat(sim): plan-faithfulness harness (realized == planned, cent-exact)"
```

---

### Task 5: `ab_compare` — the A/B economic gate (delta == 0)

**Files:**
- Modify: `core/bess/simulation/verification.py`
- Test: `core/bess/tests/integration/test_plan_faithfulness.py`

- [ ] **Step 1: Write the failing test**

```python
from core.bess.simulation.verification import ab_compare

def test_identical_command_sequences_have_zero_delta():
    bs = make_battery_settings()
    n = 6
    buy = [1.0] * n; sell = [0.8] * n; solar = [0.5] * n; home = [0.3] * n
    from core.bess.simulation.inverter_simulator import ControlCommand
    base = [ControlCommand("load_first", 0, False)] * n
    delta = ab_compare(base, base, solar, home, buy, sell, initial_soe=5.0,
                       settings=bs, dt=1.0)
    assert delta == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/bess/tests/integration/test_plan_faithfulness.py -k zero_delta -v`
Expected: FAIL with `ImportError: cannot import name 'ab_compare'`.

- [ ] **Step 3: Write minimal implementation**

```python
def ab_compare(
    baseline_commands, modified_commands, solar, home, buy_price, sell_price,
    initial_soe, settings, dt,
) -> float:
    """Realized-savings delta (modified - baseline) under identical conditions.
    Both run through the same simulator, so simulator error cancels: assert exactly."""
    base = simulate(baseline_commands, solar, home, buy_price, sell_price, initial_soe, settings, dt)
    mod = simulate(modified_commands, solar, home, buy_price, sell_price, initial_soe, settings, dt)
    # cost delta; savings delta is the negation. Positive cost delta = modified costs more.
    return mod.realized_cost - base.realized_cost
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest core/bess/tests/integration/test_plan_faithfulness.py -k zero_delta -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/bess/simulation/verification.py core/bess/tests/integration/test_plan_faithfulness.py
git commit -m "feat(sim): ab_compare economic gate (exact realized-savings delta)"
```

---

### Task 6: Dithering-scenario diagnostic + scenario `expected_savings`

**Files:**
- Modify: `core/bess/tests/integration/test_plan_faithfulness.py`
- Test: same file

- [ ] **Step 1: Write the diagnostic test (records the finding)**

```python
import pytest

# Reproduction-day inputs (2026-06-16, periods 21-95) trimmed to the morning window
# that exhibits the dither. Values lifted from docs/investigations/intent-dither-sample.txt.
MORNING_BUY  = [1.46, 1.52, 1.42, 1.45, 1.50, 1.45, 1.56, 1.52, 1.50, 1.48]
MORNING_SELL = [1.14, 1.19, 1.11, 1.14, 1.17, 1.14, 1.22, 1.19, 1.17, 1.16]
MORNING_SOLAR = [0.6, 0.6, 1.0, 1.0, 1.0, 1.0, 1.3, 1.3, 1.3, 1.3]
MORNING_HOME  = [0.1] * 10

def test_dithering_scenario_faithfulness_is_diagnostic():
    """Diagnostic: does the coarse control faithfully carry the optimizer's
    fine-grained morning plan? If R != P here, that is the spec's anticipated
    finding (control cannot losslessly express the plan), not a test bug."""
    bs = make_battery_settings()
    planned, realized, deltas = verify_plan_faithfulness(
        buy_price=MORNING_BUY, sell_price=MORNING_SELL,
        solar=MORNING_SOLAR, home=MORNING_HOME,
        initial_soe=3.3, settings=bs, dt=0.25,
    )
    gap = round(realized - planned, 4)
    print(f"\nDITHER DIAGNOSTIC: planned={planned:.4f} realized={realized:.4f} "
          f"gap={gap:+.4f}  per-period deltas={deltas}")
    # This test documents the gap rather than asserting it away. It only fails if
    # the gap is *large enough to matter* and thus needs a decision before the
    # hysteresis work proceeds.
    assert abs(gap) < 5.0, (
        f"R-P gap of {gap} SEK on a 10-period morning window is a control-fidelity "
        f"finding that must be reviewed (see spec risk section) before proceeding."
    )
```

- [ ] **Step 2: Run it and read the diagnostic output**

Run: `pytest core/bess/tests/integration/test_plan_faithfulness.py -k dithering -s -v`
Expected: PASS, and the printed `DITHER DIAGNOSTIC` line shows whether `R == P` (gap ≈ 0, control is faithful) or a non-zero gap (the anticipated finding). **Record this number in the PR — it determines whether the hysteresis plan can proceed as designed or must be reframed.**

- [ ] **Step 3: Document the result**

Append the observed `planned/realized/gap` to the investigation doc under a new "## Simulator findings" heading in `docs/investigations/intent-dither-morning.md`, stating whether plan-faithfulness holds for the morning window.

- [ ] **Step 4: Commit**

```bash
git add core/bess/tests/integration/test_plan_faithfulness.py docs/investigations/intent-dither-morning.md
git commit -m "test(sim): dithering-scenario plan-faithfulness diagnostic + finding"
```

---

### Task 7: Full-suite + lint gate

- [ ] **Step 1: Run fast suite**

Run: `pytest -m "not slow"`
Expected: all green (new sim tests + existing).

- [ ] **Step 2: Run slow suite (optimizer unchanged — must stay green)**

Run: `pytest -m slow`
Expected: all green; we did not touch the optimizer.

- [ ] **Step 3: Format + lint**

Run: `black . && ruff check --fix .`
Expected: clean.

- [ ] **Step 4: Commit any formatting**

```bash
git add -A
git commit -m "style: format simulation module" || echo "nothing to format"
```

---

## Self-Review

**Spec coverage:**
- Pure scenario simulation, same accounting + discretization → Tasks 3 (reuses `_state_transition`/`_build_period_data`). ✅
- Check 1 (R == P, cent-exact) → Task 4. ✅
- Check 2 (A/B delta exact) → Task 5. ✅
- Growatt MIN only → `mode_to_power` (Task 2) + `INTENT_TO_MODE`/`_map_rates` (Task 1). ✅
- Reuse existing scenarios + single `expected_savings` → Task 4 uses optimizer on scenario inputs; `expected_savings` regression locking is folded into the controlled-scenario test (the planned cost is the locked value). A dedicated scenario-JSON `expected_savings` field is **deferred** — see open item below. ⚠️
- Execution-only, no feedback loop → no re-optimization in `simulate`. ✅
- Mismatch = finding → Task 6 diagnostic. ✅

**Placeholder scan:** Task 4 contains an intentionally-illustrative `commands_from_result`/`_dt` stub flagged for deletion; the working path is the inline `battery_action / dt`. No other placeholders.

**Type consistency:** `ControlCommand(battery_mode, discharge_rate_pct, grid_charge)` used identically across Tasks 1–5. `simulate(...)` signature matches its callers in Tasks 4–5. `verify_plan_faithfulness` returns `(planned, realized, deltas)` consistently.

**Open item for the engineer:** the spec mentions extending scenario JSONs with `expected_savings`. This plan locks regression via the controlled-scenario test's planned cost instead. If a JSON-level `expected_savings` is wanted, add it as a follow-up task wiring `helpers.run_scenario` outputs to a stored value — not required for the verification capability itself.
