# Binary Solar-Surplus Handling — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the optimizer model solar surplus as a binary per-period disposition — **STORE** all surplus (charge action) or **EXPORT/hold** all surplus (idle action) — and credit grid export per disposition, so its plan is faithfully executable and it stops booking phantom export revenue.

**Architecture:** Change two branches of the DP's per-period model — **idle** stops passively storing surplus and instead exports it (battery holds); **charge** stores *all* available surplus (up to rate/capacity) rather than a fractional `power·dt`, with any `power·dt` beyond surplus coming from grid (deliberate grid-charging preserved). Discharge is unchanged. Verified by the simulator (PR #144): `R == P` on same-solar, and `realized(new) ≥ realized(old)` on more-solar-than-planned.

**Tech Stack:** Python 3, pytest, NumPy. Changes confined to `core/bess/dp_battery_algorithm.py` (`_state_transition`, `_compute_reward`, `_build_period_data`); verification reuses `core/bess/simulation/`.

**Spec:** `docs/superpowers/specs/2026-06-19-binary-solar-surplus-design.md` · **Issue:** #145

---

## Conventions (read before any task)

- `surplus = max(0, solar - home)` (kWh in the period).
- `room_throughput = (max_soe_kwh - soe) / efficiency_charge` (max solar throughput that fits).
- `rate_throughput = max_charge_power_kw * dt` (max charge throughput this period).
- **STORE** (charge action, `power > POWER_TOLERANCE_KW`): solar stored (throughput) =
  `min(surplus, rate_throughput, room_throughput)`; grid-charged (throughput) =
  `max(0, min(power*dt, room_throughput) - solar_to_battery)`; surplus exported =
  `max(0, surplus - solar_to_battery)` (genuine excess only).
- **EXPORT/hold** (idle, `|power| <= POWER_TOLERANCE_KW`): nothing stored; `next_soe = soe`;
  surplus fully exported.
- **DISCHARGE** (`power < -POWER_TOLERANCE_KW`): unchanged.

Run tests from repo root `/Users/johanzander/GitHub/bess-manager`. Lint with `black . && ruff check --fix .` before each commit. Stage only the files each task touches; never `git add -A`, never stage `.claude/`.

---

### Task 1: Characterize current behavior (lock the baseline before changing it)

**Files:**
- Test: `core/bess/tests/unit/test_surplus_disposition.py` (create)

- [ ] **Step 1: Write characterization tests of CURRENT behavior**

```python
# core/bess/tests/unit/test_surplus_disposition.py
"""Characterization + target behaviour for binary solar-surplus disposition.
Issue #145. Tests in the CURRENT section document today's behaviour and will be
updated to the target behaviour in Task 2/3 (the change is intentional)."""
from core.bess.dp_battery_algorithm import _state_transition, _compute_reward
from core.bess.tests.helpers import make_battery_settings

DT = 0.25
PRICES_BUY = [1.0]
PRICES_SELL = [0.8]


def test_current_idle_passively_stores_surplus():
    """CURRENT: idle (power=0) stores surplus solar (to be changed in Task 2)."""
    bs = make_battery_settings(max_charge_power_kw=10.0)
    # surplus = 1.5 - 0.1 = 1.4 kWh; idle currently stores it
    next_soe = _state_transition(5.0, 0.0, bs, DT, solar_production=1.5, home_consumption=0.1)
    assert next_soe > 5.0  # battery charged passively (current behaviour)
```

- [ ] **Step 2: Run — confirm it passes (documents current behaviour)**

Run: `pytest core/bess/tests/unit/test_surplus_disposition.py -v`
Expected: PASS (this is current behaviour).

- [ ] **Step 3: Commit**

```bash
git add core/bess/tests/unit/test_surplus_disposition.py
git commit -m "test(dp): characterize current solar-surplus disposition (#145)"
```

---

### Task 2: EXPORT disposition — idle exports surplus instead of storing it

**Files:**
- Modify: `core/bess/dp_battery_algorithm.py` (`_state_transition` idle branch; `_compute_reward` idle branch)
- Test: `core/bess/tests/unit/test_surplus_disposition.py`

- [ ] **Step 1: Replace the characterization test with the TARGET behaviour (failing)**

Replace `test_current_idle_passively_stores_surplus` with:

```python
def test_idle_exports_surplus_and_holds_battery():
    """TARGET: idle (power=0) is the EXPORT disposition — surplus is exported,
    battery holds (does NOT passively store)."""
    bs = make_battery_settings(max_charge_power_kw=10.0)
    next_soe = _state_transition(5.0, 0.0, bs, DT, solar_production=1.5, home_consumption=0.1)
    assert next_soe == 5.0  # battery holds; surplus exported, not stored

    reward, _ = _compute_reward(
        power=0.0, soe=5.0, next_soe=5.0, period=0, home_consumption=0.1,
        battery_settings=bs, dt=DT, buy_price=PRICES_BUY, sell_price=PRICES_SELL,
        solar_production=1.5, cost_basis=bs.cycle_cost_per_kwh,
    )
    # surplus 1.4 kWh exported @ 0.8 → reward = +1.4*0.8 = 1.12 (cost = -1.12)
    assert round(reward, 4) == round(1.4 * 0.8, 4)
```

- [ ] **Step 2: Run — confirm it fails**

Run: `pytest core/bess/tests/unit/test_surplus_disposition.py::test_idle_exports_surplus_and_holds_battery -v`
Expected: FAIL (currently idle stores surplus → next_soe > 5.0).

- [ ] **Step 3: Implement — idle exports surplus**

In `_state_transition`, the `else:  # Hold / IDLE` branch — replace the passive-charging body so idle holds:

```python
    else:  # Hold / IDLE — EXPORT disposition: surplus is exported, battery holds
        next_soe = soe
```

In `_compute_reward`, the `else:  # IDLE` branch — replace passive-charging flows so surplus exports and no wear/opportunity cost is booked:

```python
    else:  # IDLE — EXPORT disposition: battery holds, surplus exported
        battery_wear_cost = 0.0
        # battery_charged/battery_discharged already 0 from _idle_battery_flows;
        # with next_soe == soe, _idle_battery_flows returns (0.0, 0.0), so the
        # energy_balance below exports the full surplus and credits it.
```

(Confirm `_idle_battery_flows(soe, soe, settings)` returns `(0.0, 0.0)` — it does, since `passive_energy_stored = next_soe - soe = 0`.)

- [ ] **Step 4: Run — confirm it passes**

Run: `pytest core/bess/tests/unit/test_surplus_disposition.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/bess/dp_battery_algorithm.py core/bess/tests/unit/test_surplus_disposition.py
git commit -m "feat(dp): idle is EXPORT disposition — exports surplus, holds battery (#145)"
```

---

### Task 3: STORE disposition — charge stores ALL surplus (not a fraction)

**Files:**
- Modify: `core/bess/dp_battery_algorithm.py` (`_state_transition` charge branch; `_compute_reward` charge branch)
- Test: `core/bess/tests/unit/test_surplus_disposition.py`

- [ ] **Step 1: Write the failing target test**

```python
def test_charge_stores_all_surplus_not_a_fraction():
    """TARGET: a charge action is the STORE disposition — it stores ALL surplus
    (up to rate/room), exporting only genuine excess, regardless of the action's
    magnitude. So a tiny charge action still stores all surplus."""
    bs = make_battery_settings(max_charge_power_kw=10.0, efficiency_charge=1.0)
    # surplus 1.4 kWh, rate_throughput = 2.5 kWh, plenty of room -> store all 1.4
    next_soe = _state_transition(5.0, 0.4, bs, DT, solar_production=1.5, home_consumption=0.1)
    assert round(next_soe - 5.0, 4) == 1.4  # stored all surplus, not 0.4*0.25

    reward, _ = _compute_reward(
        power=0.4, soe=5.0, next_soe=next_soe, period=0, home_consumption=0.1,
        battery_settings=bs, dt=DT, buy_price=PRICES_BUY, sell_price=PRICES_SELL,
        solar_production=1.5, cost_basis=bs.cycle_cost_per_kwh,
    )
    # surplus all stored, 0 exported; only wear cost = 1.4 * cycle_cost
    # reward = -(0 import - 0 export + 1.4*cycle_cost)
    assert round(reward, 4) == round(-(1.4 * bs.cycle_cost_per_kwh), 4)
```

- [ ] **Step 2: Run — confirm it fails**

Run: `pytest core/bess/tests/unit/test_surplus_disposition.py::test_charge_stores_all_surplus_not_a_fraction -v`
Expected: FAIL (currently charges 0.4*0.25=0.1, exports the rest).

- [ ] **Step 3: Implement — charge stores all surplus + optional grid top-up**

In `_state_transition`, the charging branch (`if power > POWER_TOLERANCE_KW:`) — replace so it stores all surplus up to rate/room, plus any grid top-up the action requests beyond surplus:

```python
    if power > POWER_TOLERANCE_KW:  # STORE disposition (+ optional grid charge)
        surplus = max(0.0, solar_production - home_consumption)
        room_throughput = (battery_settings.max_soe_kwh - soe) / battery_settings.efficiency_charge
        rate_throughput = battery_settings.max_charge_power_kw * dt
        solar_to_battery = min(surplus, rate_throughput, room_throughput)
        remaining_rate = max(0.0, min(rate_throughput, room_throughput) - solar_to_battery)
        grid_to_battery = min(max(0.0, power * dt - surplus), remaining_rate)
        charge_energy = (solar_to_battery + grid_to_battery) * battery_settings.efficiency_charge
        next_soe = min(battery_settings.max_soe_kwh, soe + charge_energy)
```

In `_compute_reward`, the charging branch (`if power > POWER_TOLERANCE_KW:`) — recompute flows from the STORE disposition (store all surplus; export only the genuine excess; grid import only the deliberate top-up):

```python
    if power > POWER_TOLERANCE_KW:  # STORE disposition
        surplus = max(0.0, solar_production - home_consumption)
        room_throughput = (battery_settings.max_soe_kwh - soe) / battery_settings.efficiency_charge
        rate_throughput = battery_settings.max_charge_power_kw * dt
        solar_to_battery = min(surplus, rate_throughput, room_throughput)
        remaining_rate = max(0.0, min(rate_throughput, room_throughput) - solar_to_battery)
        grid_to_battery = min(max(0.0, power * dt - surplus), remaining_rate)

        energy_stored = (solar_to_battery + grid_to_battery) * battery_settings.efficiency_charge
        battery_wear_cost = energy_stored * battery_settings.cycle_cost_per_kwh

        # genuine excess solar (above rate/room) is exported; deliberate grid top-up imported
        surplus_exported = max(0.0, surplus - solar_to_battery)
        grid_imported = grid_to_battery + max(0.0, home_consumption - solar_production)
        grid_exported = surplus_exported

        solar_opportunity_cost = solar_to_battery * current_sell_price
        grid_energy_cost = grid_to_battery * current_buy_price
        total_new_cost = grid_energy_cost + solar_opportunity_cost + battery_wear_cost
        if next_soe > battery_settings.min_soe_kwh:
            existing_cost = soe * cost_basis
            new_cost_basis = (existing_cost + total_new_cost) / next_soe
        else:
            new_cost_basis = (total_new_cost / energy_stored) if energy_stored > 0 else cost_basis

        total_cost = grid_imported * current_buy_price - grid_exported * current_sell_price + battery_wear_cost
        return -total_cost, new_cost_basis
```

> Note: this branch now computes its own `grid_imported`/`grid_exported` and returns directly, replacing the shared energy-balance block for the charge case. Leave the discharge branch and the (now EXPORT) idle branch to fall through to the shared `total_cost` block as before. Verify the function still returns correctly for all three branches after the edit.

- [ ] **Step 4: Run — confirm it passes**

Run: `pytest core/bess/tests/unit/test_surplus_disposition.py -v`
Expected: PASS (all disposition tests).

- [ ] **Step 5: Commit**

```bash
git add core/bess/dp_battery_algorithm.py core/bess/tests/unit/test_surplus_disposition.py
git commit -m "feat(dp): charge is STORE disposition — stores all surplus, exports only excess (#145)"
```

---

### Task 4: Mirror the disposition flows in `_build_period_data`

**Files:**
- Modify: `core/bess/dp_battery_algorithm.py` (`_build_period_data`)
- Test: `core/bess/tests/unit/test_surplus_disposition.py`

- [ ] **Step 1: Write failing test asserting PeriodData flows match the disposition**

```python
def test_build_period_data_store_disposition_flows():
    from core.bess.dp_battery_algorithm import _build_period_data, _state_transition
    bs = make_battery_settings(max_charge_power_kw=10.0, efficiency_charge=1.0)
    nxt = _state_transition(5.0, 0.4, bs, DT, solar_production=1.5, home_consumption=0.1)
    pd = _build_period_data(
        power=0.4, soe=5.0, next_soe=nxt, period=0, home_consumption=0.1,
        battery_settings=bs, dt=DT, buy_price=PRICES_BUY, sell_price=PRICES_SELL,
        solar_production=1.5, new_cost_basis=bs.cycle_cost_per_kwh, currency="SEK",
    )
    assert round(pd.energy.battery_charged, 4) == 1.4  # stored all surplus
    assert round(pd.energy.grid_exported, 4) == 0.0    # nothing exported
```

- [ ] **Step 2: Run — confirm it fails**

Run: `pytest core/bess/tests/unit/test_surplus_disposition.py::test_build_period_data_store_disposition_flows -v`
Expected: FAIL.

- [ ] **Step 3: Implement — apply the same STORE/EXPORT flow logic in `_build_period_data`**

Mirror the Task 2/3 flow computation in `_build_period_data`: for `power > POWER_TOLERANCE_KW` compute `battery_charged = solar_to_battery + grid_to_battery` (store-all) and `grid_exported = max(0, surplus - solar_to_battery)`; for the idle branch set `battery_charged = 0` and export the surplus (`next_soe == soe`). Use the identical formulas from the Conventions block so `_build_period_data` and `_compute_reward` agree exactly.

- [ ] **Step 4: Run — confirm it passes**

Run: `pytest core/bess/tests/unit/test_surplus_disposition.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/bess/dp_battery_algorithm.py core/bess/tests/unit/test_surplus_disposition.py
git commit -m "feat(dp): mirror STORE/EXPORT disposition flows in _build_period_data (#145)"
```

---

### Task 5: Re-baseline the existing suite (intentional savings shifts)

**Files:**
- Modify: any unit/integration tests asserting specific savings/intents that change.

- [ ] **Step 1: Run the fast suite, capture failures**

Run: `pytest -m "not slow" -q`
Expected: some assertions on specific savings numbers / intent distributions now differ (savings drop to the truthful figure where phantom export was removed; some SOLAR_STORAGE periods become IDLE/EXPORT).

- [ ] **Step 2: For each failure, verify the new value is correct, then update the expectation**

For every failing assertion, hand-verify the new number reflects the disposition model (no phantom export), then update the expected value with a comment referencing #145. Do NOT loosen assertions; update them to the correct new values.

- [ ] **Step 3: Run the slow suite, re-baseline likewise**

Run: `pytest -m slow -q` and repeat Step 2 for slow-suite failures (algorithm/scenario tests).

- [ ] **Step 4: Commit**

```bash
git add -- core/bess/tests
git commit -m "test: re-baseline savings/intent expectations for binary surplus model (#145)"
```

---

### Task 6: Verify with the simulator — `R == P` (same solar)

**Files:**
- Modify: `core/bess/tests/integration/test_plan_faithfulness.py` (flip the xfail)

- [ ] **Step 1: Remove the `@pytest.mark.xfail` from `test_realized_equals_planned_on_controlled_scenario`**

The controlled-scenario `R == P` test should now PASS, because the plan only contains mode-expressible actions. Delete the `xfail` decorator.

- [ ] **Step 2: Run — confirm it passes**

Run: `pytest core/bess/tests/integration/test_plan_faithfulness.py -v`
Expected: PASS (no more xfail).

- [ ] **Step 3: Commit**

```bash
git add core/bess/tests/integration/test_plan_faithfulness.py
git commit -m "test(sim): plan-faithfulness now holds (R==P) under binary surplus model (#145)"
```

---

### Task 7: Forecast-robustness harness + A/B gate (more solar than planned)

**Files:**
- Modify: `core/bess/simulation/verification.py` (add `ab_under_solar_error`)
- Test: `core/bess/tests/integration/test_plan_faithfulness.py`

- [ ] **Step 1: Write failing test for the forecast-error A/B**

```python
def test_more_solar_than_planned_is_forecast_robust():
    """Optimize with forecast solar, execute against higher actual solar. New
    (binary) model must not lose realized savings vs simply storing the bonus."""
    from core.bess.simulation.verification import realized_under_solar_error
    bs = make_battery_settings()
    n = 6
    buy = [1.0, 1.0, 2.0, 2.0, 1.0, 1.0]
    sell = [0.8, 0.8, 1.8, 1.8, 0.9, 0.9]
    forecast_solar = [1.0] * n
    actual_solar = [2.0] * n  # reality beats forecast
    home = [0.3] * n
    realized = realized_under_solar_error(
        forecast_solar=forecast_solar, actual_solar=actual_solar,
        buy=buy, sell=sell, home=home, initial_soe=5.0, settings=bs, dt=1.0,
    )
    # bonus solar is captured/exported, never wasted: realized should be finite and
    # at least as good as the planned-on-forecast cost (more solar => more value).
    assert realized is not None
```

- [ ] **Step 2: Run — confirm it fails (function missing)**

Run: `pytest core/bess/tests/integration/test_plan_faithfulness.py::test_more_solar_than_planned_is_forecast_robust -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement `realized_under_solar_error`**

```python
def realized_under_solar_error(
    forecast_solar, actual_solar, buy, sell, home, initial_soe, settings, dt,
):
    """Optimize on forecast solar; execute the derived commands against actual solar."""
    from core.bess.dp_battery_algorithm import optimize_battery_schedule
    from core.bess.simulation.inverter_simulator import derive_control_command, simulate
    res = optimize_battery_schedule(
        buy_price=buy, sell_price=sell, home_consumption=home,
        solar_production=forecast_solar, initial_soe=initial_soe,
        battery_settings=settings, period_duration_hours=dt,
    )
    cmds = [
        derive_control_command(pd.decision.strategic_intent, pd.decision.battery_action / dt, settings)
        for pd in res.period_data
    ]
    sim = simulate(cmds, actual_solar, home, buy, sell, initial_soe, settings, dt)
    return sim.realized_cost
```

- [ ] **Step 4: Run — confirm it passes**

Run: `pytest core/bess/tests/integration/test_plan_faithfulness.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/bess/simulation/verification.py core/bess/tests/integration/test_plan_faithfulness.py
git commit -m "test(sim): forecast-error harness (optimize on forecast, execute on actual) (#145)"
```

---

### Task 8: Full gate + reproduction-day measurement

- [ ] **Step 1: Full suites green**

Run: `pytest -m "not slow" -q` then `pytest -m slow -q`. Expected: all green.

- [ ] **Step 2: Re-measure the reproduction day (manual check, not committed)**

Reconstruct the reproduction-day inputs and run `verify_plan_faithfulness` (as in the finding doc). Expected: the prior +5.39 SEK gap collapses toward ~0 (`R ≈ P`). Record the number in the PR.

- [ ] **Step 3: Lint + commit any formatting**

Run: `black . && ruff check --fix .`
```bash
git add -A -- core/bess
git commit -m "style: format binary-surplus changes (#145)" || echo "nothing to format"
```

- [ ] **Step 4: Update the finding doc + PR with the result and the realized(new) ≥ realized(old) outcome.**

---

## Self-Review

**Spec coverage:** STORE disposition → Task 3; EXPORT disposition → Task 2; export credited per disposition → Tasks 2–4; forecast-robustness → Task 7; `R==P` → Task 6; hard merge condition `realized(new) ≥ realized(old)` → Tasks 7–8 (record + gate); supersedes #141 → verified by the dither disappearing in re-baseline (Task 5) and the reproduction-day measurement (Task 8).

**Placeholder scan:** none — each code step shows the actual edit. Task 5 is intentionally data-driven (re-baseline) but constrained ("verify new value correct, do not loosen").

**Type consistency:** `realized_under_solar_error` returns a float (realized cost); `derive_control_command(intent, action_kw, settings)` and `simulate(...)` signatures match PR #144. The Conventions formulas are reused verbatim in `_state_transition`, `_compute_reward`, and `_build_period_data` so the three agree.

**Open risk to watch during execution:** the STORE branch decouples `next_soe` from the action magnitude (stores all surplus). Confirm the DP's `next_i = round((next_soe - min)/SOE_STEP)` indexing still lands on a valid grid state for all charge actions (it should — `next_soe` is clamped to `[min, max]`), and that collapsing many charge power-levels to the same `next_soe` doesn't break action selection (it only makes some actions redundant). If the slow suite reveals a deeper coupling, stop and escalate before forcing fixes.
