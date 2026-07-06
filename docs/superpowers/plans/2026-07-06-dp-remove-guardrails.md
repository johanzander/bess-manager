# DP Guardrail Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the DP optimizer's ad hoc profitability floors and rejection gate with pure backward induction plus a trivial numerical safety net, per the approved design spec.

**Architecture:** `core/bess/dp_battery_algorithm.py` keeps its existing backward-induction structure; we delete the `cost_basis` veto and whole-day rejection gate (both provably unnecessary given `IDLE` is always feasible), fix a real flow-accounting bug (#240) in the same reward branch, and replace a grid-snapping approximation in the continuous-path replay with an interpolated one-step recompute. No new dependencies, no new files except tests.

**Tech Stack:** Python, numpy, pytest.

## Global Constraints

- Every task must leave `.venv/bin/pytest -m "not slow"` green before moving to the next task.
- `_run_dynamic_programming` has exactly one caller (`optimize_battery_schedule`, same file) and no external test calls it directly — confirmed via repo-wide grep. Signature changes across tasks are safe as long as the sole call site is updated in the same task.
- Design spec: `docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md` — read it before Task 1 if you weren't the one who wrote it.
- Run `.venv/bin/black . && .venv/bin/ruff check --fix .` before every commit (per `./scripts/quality-check.sh`).
- `BatterySettings.min_action_profit_threshold` and `bess_manager/config.yaml`'s corresponding schema entry are **not touched** in this plan — the algorithm stops reading the field, but the field itself stays defined. Its removal is a separate follow-up issue.

---

### Task 1: Remove the discharge profitability floor; fix #240 flow accounting

**Files:**
- Modify: `core/bess/dp_battery_algorithm.py:106-108` (constants), `:249-421` (`_compute_reward`)
- Test: `core/bess/tests/unit/test_dp_no_guardrails.py` (new file)

**Interfaces:**
- Consumes: nothing new.
- Produces: `_compute_reward` signature is unchanged (`power, soe, next_soe, period, home_consumption, battery_settings, dt, buy_price, sell_price, solar_production, cost_basis) -> tuple[float, float]`), but it now **never returns `-inf`** for any physically valid action. Later tasks rely on this.

- [ ] **Step 1: Write the failing tests**

Create `core/bess/tests/unit/test_dp_no_guardrails.py`:

```python
"""Tests for the removed discharge profitability floor and the #240
flow-accounting fix, per docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md.
"""

import pytest

from core.bess.dp_battery_algorithm import _compute_reward
from core.bess.tests.helpers import make_battery_settings


def test_discharge_no_longer_blocked_by_cost_basis_floor():
    """The old cost_basis profitability floor (removed) used to veto a
    discharge outright by returning -inf whenever its value didn't clear a
    historical average cost -- even though IDLE, competing in the same
    max() in _run_dynamic_programming, already makes that comparison
    correctly via the forward-looking value function. _compute_reward must
    now always return a finite reward for a physically valid discharge."""
    settings = make_battery_settings()
    power = -1.0
    next_soe = 5.0 - (abs(power) * 1.0 / settings.efficiency_discharge)
    reward, _ = _compute_reward(
        power=power,
        soe=5.0,
        next_soe=next_soe,
        period=0,
        home_consumption=0.5,
        battery_settings=settings,
        dt=1.0,
        buy_price=[0.6],
        sell_price=[0.5],
        solar_production=0.0,
        cost_basis=2.0,  # old floor would have blocked this: 2.0 >> ~0.57
    )
    assert reward != float("-inf"), (
        "discharge was vetoed by a profitability floor that no longer exists"
    )


def test_small_discharge_overshoot_not_credited_as_export():
    """#240: load-first hardware self-throttles -- a discharge that
    overshoots home_consumption by less than the BATTERY_EXPORT
    classification threshold (0.1 kWh) never actually reaches the grid, so
    it must not be credited as export revenue."""
    settings = make_battery_settings()
    dt = 1.0
    home_consumption = 1.0
    power = -1.05  # discharges 1.05 kWh -- 0.05 kWh over consumption
    next_soe = 5.0 - (abs(power) * dt / settings.efficiency_discharge)
    reward, _ = _compute_reward(
        power=power,
        soe=5.0,
        next_soe=next_soe,
        period=0,
        home_consumption=home_consumption,
        battery_settings=settings,
        dt=dt,
        buy_price=[1.0],
        sell_price=[1.0],
        solar_production=0.0,
        cost_basis=0.1,
    )
    # No import (fully covered) and no export credit for the 0.05 kWh
    # overshoot: net cost should be exactly zero, not a phantom profit.
    assert reward == pytest.approx(0.0, abs=1e-9), (
        f"expected zero net cost (no import, no phantom export credit), got {reward}"
    )


def test_large_discharge_overshoot_still_credited_as_export():
    """A discharge that overshoots home_consumption by 0.1 kWh or more is a
    genuine deliberate export (BATTERY_EXPORT), not self-throttled
    load-following -- it must still be credited as export revenue."""
    settings = make_battery_settings()
    dt = 1.0
    home_consumption = 1.0
    power = -2.0  # discharges 2.0 kWh -- 1.0 kWh over consumption
    next_soe = 5.0 - (abs(power) * dt / settings.efficiency_discharge)
    reward, _ = _compute_reward(
        power=power,
        soe=5.0,
        next_soe=next_soe,
        period=0,
        home_consumption=home_consumption,
        battery_settings=settings,
        dt=dt,
        buy_price=[1.0],
        sell_price=[0.8],
        solar_production=0.0,
        cost_basis=0.1,
    )
    # 1.0 kWh exported at sell_price=0.8, no import, no wear on discharge.
    assert reward == pytest.approx(0.8, abs=1e-9)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest core/bess/tests/unit/test_dp_no_guardrails.py -v`
Expected: `test_discharge_no_longer_blocked_by_cost_basis_floor` FAILS (reward is `-inf`); `test_small_discharge_overshoot_not_credited_as_export` FAILS (reward is negative, not 0 — the current code credits the 0.05 kWh as export); `test_large_discharge_overshoot_still_credited_as_export` PASSES already (no code path change needed for genuine exports, this one's a guard-rail for step 3).

- [ ] **Step 3: Add the `BATTERY_EXPORT_THRESHOLD_KWH` constant**

In `core/bess/dp_battery_algorithm.py`, next to the existing constants (currently lines 106-108):

```python
# Algorithm parameters
SOE_STEP_KWH = 0.1
POWER_STEP_KW = 0.2
POWER_TOLERANCE_KW = 0.001  # Threshold to distinguish IDLE from charge/discharge
# Matches decision_intelligence._POWER_THRESHOLD_KW's own use as the
# BATTERY_EXPORT vs LOAD_SUPPORT classification boundary (kept as a separate
# constant here, not imported, to avoid coupling to that module's private
# threshold -- if one changes, check the other).
BATTERY_EXPORT_THRESHOLD_KWH = 0.1
```

- [ ] **Step 4: Replace the discharge branch in `_compute_reward`**

Replace the entire `elif power < -POWER_TOLERANCE_KW:` block (currently lines 358-402) with:

```python
    elif power < -POWER_TOLERANCE_KW:  # Discharging
        battery_wear_cost = 0.0

        # Self-throttling fix (#240): load-first hardware never actually
        # exports a small discharge overshoot beyond home_consumption -- it
        # delivers only what the home needs. Below BATTERY_EXPORT_THRESHOLD_KWH
        # (the same boundary decision_intelligence.classify_strategic_intent
        # uses to call something BATTERY_EXPORT vs LOAD_SUPPORT), treat the
        # overshoot as self-throttled: no export credit. At or above it, it's
        # a genuine deliberate export.
        if grid_exported <= BATTERY_EXPORT_THRESHOLD_KWH:
            grid_exported = 0.0
```

This deletes the old profitability-check block entirely (`avoid_purchase_value`,
`export_value`, `excess_solar`, `effective_value_per_kwh_stored`,
`effective_cost_basis`, and the `return float("-inf"), cost_basis` line). The
function falls through to the existing shared final block (currently lines
413-421, unchanged) which computes `total_cost` from `grid_imported`,
`grid_exported`, and `battery_wear_cost`.

- [ ] **Step 5: Update the function's docstring**

Replace the `PROFITABILITY CHECK` section of `_compute_reward`'s docstring
(currently lines 270-286) with:

```python
    """Hot-path reward computation — returns scalars only, no dataclass allocation.

    CYCLE COST POLICY:
    - Applied only to charging operations (not discharging)
    - Applied to energy actually stored (after efficiency losses)
    - Grid costs applied to energy throughput (what you draw from grid)
    - Cost basis includes BOTH grid costs AND cycle costs for profitability analysis

    DISCHARGE ACCOUNTING:
    - No profitability veto: every physically valid discharge gets a finite
      reward. IDLE, competing in the same max() during backward induction,
      already makes the hold-vs-discharge call correctly via the
      forward-looking value function -- a separate floor on top of that is
      redundant at best (see docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md).
    - Self-throttling (#240): a discharge overshooting home_consumption by
      less than BATTERY_EXPORT_THRESHOLD_KWH is not credited as export
      revenue -- load-first hardware never actually delivers it to the grid.

    Returns:
        (reward, new_cost_basis).
    """
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest core/bess/tests/unit/test_dp_no_guardrails.py -v`
Expected: all 3 tests PASS.

- [ ] **Step 7: Run the fast suite to check for regressions**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS. (Slow tests, including the 26-fixture suite, are handled in Task 8.)

- [ ] **Step 8: Commit**

```bash
git add core/bess/dp_battery_algorithm.py core/bess/tests/unit/test_dp_no_guardrails.py
git commit -m "$(cat <<'EOF'
fix: remove discharge profitability floor, fix #240 export miscrediting

_compute_reward no longer vetoes a discharge via a cost_basis floor -- IDLE
already makes that comparison correctly through the forward-looking value
function during backward induction (Bellman's principle of optimality).
Also fixes #240: a discharge overshooting home_consumption by less than the
BATTERY_EXPORT threshold (0.1 kWh) is no longer credited as export revenue,
since load-first hardware self-throttles and never actually exports it.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Remove the dead `C` grid, dead fallback branch, and dead `stored_period_data` computation

**Files:**
- Modify: `core/bess/dp_battery_algorithm.py:659-907` (`_run_dynamic_programming`), `:1101` (its call site)
- Test: `core/bess/tests/unit/test_dp_no_guardrails.py` (append)

**Interfaces:**
- Consumes: `_compute_reward` from Task 1 (never returns `-inf`).
- Produces: `_run_dynamic_programming(...) -> tuple[np.ndarray, np.ndarray]` — returns `(V, policy)` only (drops `C` and `stored_period_data`). Task 4 depends on this signature.

- [ ] **Step 1: Write the failing test**

Append to `core/bess/tests/unit/test_dp_no_guardrails.py`:

```python
def test_run_dynamic_programming_returns_two_values():
    """_run_dynamic_programming's C grid (dead since #234: a loop-order bug
    meant it was never read back) and stored_period_data (already discarded
    by the sole caller before this change) are removed. Only V and policy
    remain."""
    from core.bess.dp_battery_algorithm import _run_dynamic_programming

    settings = make_battery_settings()
    result = _run_dynamic_programming(
        horizon=3,
        buy_price=[1.0, 1.0, 1.0],
        sell_price=[0.8, 0.8, 0.8],
        home_consumption=[0.5, 0.5, 0.5],
        battery_settings=settings,
        dt=1.0,
        solar_production=[0.0, 0.0, 0.0],
        initial_soe=5.0,
    )
    assert len(result) == 2, f"expected (V, policy), got {len(result)} values"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_dp_no_guardrails.py::test_run_dynamic_programming_returns_two_values -v`
Expected: FAIL (`AssertionError: expected (V, policy), got 4 values`)

- [ ] **Step 3: Rewrite `_run_dynamic_programming`**

Replace the entire function body from `V = np.zeros((horizon + 1, len(soe_levels)))`
(currently line 690) through `return V, policy, C, stored_period_data`
(currently line 907) with:

```python
    V = np.zeros((horizon + 1, len(soe_levels)))

    # Terminal value: assign value to usable energy remaining at end of horizon
    if terminal_value_per_kwh > 0.0:
        for i, soe in enumerate(soe_levels):
            usable_energy = soe - battery_settings.min_soe_kwh
            V[horizon, i] = max(0.0, usable_energy) * terminal_value_per_kwh

    policy = np.zeros((horizon, len(soe_levels)))

    # Backward induction
    for t in reversed(range(horizon)):
        for i, soe in enumerate(soe_levels):
            best_value = float("-inf")
            best_action = 0

            # Per-period charge power limit (from temperature derating or None)
            period_max_charge = (
                max_charge_power_per_period[t]
                if max_charge_power_per_period is not None
                else None
            )

            # Try all possible actions
            for power in power_levels:
                # Skip physically impossible actions
                if power < -POWER_TOLERANCE_KW:  # Discharging
                    available_energy = soe - battery_settings.min_soe_kwh
                    max_discharge_power = (
                        available_energy / dt * battery_settings.efficiency_discharge
                    )
                    if abs(power) > max_discharge_power:
                        continue
                elif power > POWER_TOLERANCE_KW:  # Charging
                    # Apply temperature derating limit if provided
                    if period_max_charge is not None and power > period_max_charge:
                        continue

                    available_capacity = battery_settings.max_soe_kwh - soe
                    max_charge_power = (
                        available_capacity / dt / battery_settings.efficiency_charge
                    )
                    if power > max_charge_power:
                        continue
                # else: IDLE (near-zero power) - no physical constraints to check

                # Calculate next state
                next_soe = _state_transition(
                    soe,
                    power,
                    battery_settings,
                    dt,
                    solar_production=solar_production[t],
                    home_consumption=home_consumption[t],
                )
                if (
                    next_soe < battery_settings.min_soe_kwh
                    or next_soe > battery_settings.max_soe_kwh
                ):
                    continue

                # Compute reward scalars only — no dataclass allocation in hot path
                reward, _ = _compute_reward(
                    power=power,
                    soe=soe,
                    next_soe=next_soe,
                    period=t,
                    home_consumption=home_consumption[t],
                    battery_settings=battery_settings,
                    dt=dt,
                    solar_production=solar_production[t],
                    buy_price=buy_price,
                    sell_price=sell_price,
                    cost_basis=initial_cost_basis,
                )

                # Find next state index
                next_i = round((next_soe - battery_settings.min_soe_kwh) / SOE_STEP_KWH)
                next_i = min(max(0, next_i), len(soe_levels) - 1)

                # Calculate total value
                value = reward + V[t + 1, next_i]

                # Update if better
                if value > best_value:
                    best_value = value
                    best_action = power

            # IDLE is always a feasible, finite-reward action (no physical
            # constraint check applies to it, and _compute_reward never
            # returns -inf), so best_value can never remain -inf here.
            V[t, i] = best_value
            policy[t, i] = best_action

    # Final safety check
    if max_charge_power_per_period is not None:
        # Apply per-period charge limits
        for t in range(horizon):
            policy[t] = np.clip(
                policy[t],
                -battery_settings.max_discharge_power_kw,
                max_charge_power_per_period[t],
            )
    else:
        policy = np.clip(
            policy,
            -battery_settings.max_discharge_power_kw,
            battery_settings.max_charge_power_kw,
        )

    return V, policy
```

Also update the function's return type annotation (currently
`-> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:`) to
`-> tuple[np.ndarray, np.ndarray]:`.

Note what this deletes versus the pre-Task-1 code: the `C` grid and all its
reads/writes; the `stored_period_data` dict and its per-cell
`_build_period_data(...)` call (confirmed dead — discarded by the sole
caller both before and after this change); the `else` "No valid action
found" fallback branch (currently lines 810-881, including its `logger.warning`
and manual IDLE reconstruction) — now unreachable since `best_value` can
never stay at `-inf`; and the `if reward == float("-inf"): continue` skip
(now unreachable, since Task 1 made `_compute_reward` never return `-inf`).

- [ ] **Step 4: Update the call site**

In `optimize_battery_schedule` (currently line 1101):

```python
    V, policy, _, _ = _run_dynamic_programming(
```

becomes:

```python
    V, policy = _run_dynamic_programming(
```

(Same argument list, unchanged.)

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_dp_no_guardrails.py -v`
Expected: all tests PASS.

- [ ] **Step 6: Run the fast suite to check for regressions**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add core/bess/dp_battery_algorithm.py core/bess/tests/unit/test_dp_no_guardrails.py
git commit -m "$(cat <<'EOF'
refactor: remove dead C grid, dead fallback, and dead stored_period_data

C was the cost-basis-threading grid #234 found dead (loop-order bug meant it
was never read back); stored_period_data was already discarded by the sole
caller before this change, so building a full PeriodData per grid cell in
the hot loop was pure waste. The "no valid action found" fallback branch is
now unreachable since IDLE is always feasible and _compute_reward never
returns -inf (Task 1).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Replace the whole-day rejection gate with a trivial idle-vs-DP-cost safety net

**Files:**
- Modify: `core/bess/dp_battery_algorithm.py:1236-1292` (`optimize_battery_schedule`, profitability gate section)
- Test: `core/bess/tests/unit/test_dp_no_guardrails.py` (append)

**Interfaces:**
- Consumes: `_create_idle_schedule` (existing, unchanged signature: `horizon, buy_price, sell_price, home_consumption, solar_production, initial_soe, battery_settings, dt) -> OptimizationResult`).
- Produces: `optimize_battery_schedule` no longer reads `battery_settings.min_action_profit_threshold`.

- [ ] **Step 1: Write the failing test**

Append to `core/bess/tests/unit/test_dp_no_guardrails.py`:

```python
def test_optimizer_ignores_min_action_profit_threshold():
    """The whole-day rejection gate is gone -- setting an absurdly high
    min_action_profit_threshold must no longer force an all-IDLE fallback
    when the DP found a genuinely better schedule."""
    from core.bess.dp_battery_algorithm import optimize_battery_schedule

    settings = make_battery_settings(min_action_profit_threshold=1_000_000.0)
    buy_price = [0.3, 0.3, 3.0, 3.0] * 6
    sell_price = [0.25, 0.25, 2.8, 2.8] * 6
    home_consumption = [1.0] * 24
    solar_production = [0.0] * 24

    result = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=5.0,
        battery_settings=settings,
        period_duration_hours=1.0,
    )
    # A real arbitrage opportunity (0.3 -> 3.0 spread) should be captured
    # despite the absurd threshold -- the old gate would have rejected this
    # to an all-IDLE schedule.
    assert result.economic_summary.grid_to_battery_solar_savings > 0.0, (
        "optimizer fell back to all-IDLE despite a genuine arbitrage "
        "opportunity -- min_action_profit_threshold should have no effect"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_dp_no_guardrails.py::test_optimizer_ignores_min_action_profit_threshold -v`
Expected: FAIL (savings near zero — the old gate rejects to all-IDLE given the absurd threshold).

- [ ] **Step 3: Replace the profitability gate**

Replace the entire section from the `# PROFITABILITY GATE` comment through the
end of the `if solar_to_battery_solar_savings < effective_threshold:` block
(currently lines 1236-1278) with:

```python
    # ============================================================================
    # NUMERICAL SAFETY NET: guard against SoE-grid discretization residual
    # ============================================================================
    # Bellman's principle of optimality guarantees the DP's own schedule is
    # never worse than doing nothing: IDLE is always a feasible action every
    # period, so backward induction already picks it whenever it's the best
    # available option. The only way the realized schedule can still cost
    # slightly more than an all-IDLE schedule is SoE-grid discretization
    # residual (see docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md)
    # -- a numerical artifact, not an economic one. This is a trivial O(1)
    # comparison, not a configurable threshold.
    idle_schedule = _create_idle_schedule(
        horizon=horizon,
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=initial_soe,
        battery_settings=battery_settings,
        dt=dt,
    )
    if idle_schedule.economic_summary.battery_solar_cost < total_optimized_cost:
        return idle_schedule
```

The following `return OptimizationResult(...)` block (currently lines
1280-1292) is unchanged and stays immediately after this.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_dp_no_guardrails.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Run the fast suite to check for regressions**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/bess/dp_battery_algorithm.py core/bess/tests/unit/test_dp_no_guardrails.py
git commit -m "$(cat <<'EOF'
refactor: replace whole-day rejection gate with idle-cost safety net

The min_action_profit_threshold gate distrusted the DP's own economics
wholesale. Replaced with a trivial comparison against the all-IDLE schedule,
justified purely by SoE-grid discretization noise (verified empirically),
not by an economic threshold. The algorithm no longer reads
min_action_profit_threshold; the config field itself is left in place for a
separate follow-up issue.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Replace Step 2's grid-snapped policy lookup with an interpolated-V recompute

**Files:**
- Modify: `core/bess/dp_battery_algorithm.py:1030-1193` (`optimize_battery_schedule`, Step 1 call site and Step 2 loop), add two new module-level helper functions near `_run_dynamic_programming`
- Test: `core/bess/tests/unit/test_dp_no_guardrails.py` (append)

**Interfaces:**
- Consumes: `V` from `_run_dynamic_programming` (Task 2).
- Produces: `_run_dynamic_programming(...) -> np.ndarray` (returns `V` only — `policy` is no longer used by any caller, so it's dropped). A new helper `_best_action_at_continuous_state(soe, t, V_next, power_levels, home_consumption, battery_settings, dt, solar_production, buy_price, sell_price, cost_basis, max_charge_power_per_period) -> tuple[float, float, float, float]` (returns `best_action, best_next_soe, best_new_cost_basis, best_reward`) and `_interpolate_value(V_row, soe, battery_settings) -> float`.

- [ ] **Step 1: Replace Task 2's now-obsolete return-shape test**

Task 2's `test_run_dynamic_programming_returns_two_values` asserted
`len(result) == 2` for a `(V, policy)` tuple. This task changes the return
to a bare `V` array, so that assertion would instead silently check
`len(V)` (the array's first-dimension size) — a confusing false signal, not
a clean failure. Delete that test from
`core/bess/tests/unit/test_dp_no_guardrails.py` and replace it with:

```python
def test_run_dynamic_programming_returns_one_value():
    """policy is no longer used by any caller once Step 2 recomputes actions
    directly from V -- _run_dynamic_programming returns V only."""
    from core.bess.dp_battery_algorithm import _run_dynamic_programming

    settings = make_battery_settings()
    result = _run_dynamic_programming(
        horizon=3,
        buy_price=[1.0, 1.0, 1.0],
        sell_price=[0.8, 0.8, 0.8],
        home_consumption=[0.5, 0.5, 0.5],
        battery_settings=settings,
        dt=1.0,
        solar_production=[0.0, 0.0, 0.0],
        initial_soe=5.0,
    )
    import numpy as np
    assert isinstance(result, np.ndarray), f"expected a bare V array, got {type(result)}"
```

The general property this task's fix improves — the DP schedule never
costs more than an all-IDLE schedule, across every pinned fixture including
`historical_2025_01_05_no_spread_no_solar` (the one fixture where this gap
was investigated) — is covered by Task 5's parametrized test, not
duplicated here.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_dp_no_guardrails.py::test_run_dynamic_programming_returns_one_value -v`
Expected: FAILS (`_run_dynamic_programming` still returns a 2-tuple).

- [ ] **Step 3: Add the two helper functions**

Add these two functions immediately after `_run_dynamic_programming` (i.e.,
right after its `return V, policy` line from Task 2, before
`_create_idle_schedule`):

```python
def _interpolate_value(
    V_row: np.ndarray, soe: float, battery_settings: BatterySettings
) -> float:
    """Linearly interpolate a value-function row (V[t, :]) at a continuous
    SoE, rather than snapping to the nearest discretized grid point."""
    idx = (soe - battery_settings.min_soe_kwh) / SOE_STEP_KWH
    idx = min(max(0.0, idx), len(V_row) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(V_row) - 1)
    frac = idx - lo
    return V_row[lo] * (1 - frac) + V_row[hi] * frac


def _best_action_at_continuous_state(
    soe: float,
    t: int,
    V_next: np.ndarray,
    power_levels: np.ndarray,
    home_consumption: list[float],
    battery_settings: BatterySettings,
    dt: float,
    solar_production: list[float],
    buy_price: list[float],
    sell_price: list[float],
    cost_basis: float,
    max_charge_power_per_period: list[float] | None,
) -> tuple[float, float, float, float]:
    """One-step Bellman recompute at a true continuous SoE, using the
    already-known V[t+1, :] (linearly interpolated) as the continuation
    value -- the same reward+max(V) logic as _run_dynamic_programming's
    backward pass, applied at the true replay state instead of one snapped
    to the nearest grid index. Used by optimize_battery_schedule's Step 2 to
    reconstruct the continuous path without trusting a policy table computed
    for a slightly different state. See
    docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md.

    Returns (best_action, best_next_soe, best_new_cost_basis, best_reward).
    """
    period_max_charge = (
        max_charge_power_per_period[t]
        if max_charge_power_per_period is not None
        else None
    )
    best_value = float("-inf")
    best_action = 0.0
    best_next_soe = soe
    best_new_cost_basis = cost_basis
    best_reward = 0.0
    for power in power_levels:
        if power < -POWER_TOLERANCE_KW:
            available_energy = soe - battery_settings.min_soe_kwh
            max_discharge_power = (
                available_energy / dt * battery_settings.efficiency_discharge
            )
            if abs(power) > max_discharge_power:
                continue
        elif power > POWER_TOLERANCE_KW:
            if period_max_charge is not None and power > period_max_charge:
                continue
            available_capacity = battery_settings.max_soe_kwh - soe
            max_charge_power = (
                available_capacity / dt / battery_settings.efficiency_charge
            )
            if power > max_charge_power:
                continue

        next_soe = _state_transition(
            soe,
            power,
            battery_settings,
            dt,
            solar_production=solar_production[t],
            home_consumption=home_consumption[t],
        )
        if (
            next_soe < battery_settings.min_soe_kwh
            or next_soe > battery_settings.max_soe_kwh
        ):
            continue

        reward, new_cost_basis = _compute_reward(
            power=power,
            soe=soe,
            next_soe=next_soe,
            period=t,
            home_consumption=home_consumption[t],
            battery_settings=battery_settings,
            dt=dt,
            solar_production=solar_production[t],
            buy_price=buy_price,
            sell_price=sell_price,
            cost_basis=cost_basis,
        )
        value = reward + _interpolate_value(V_next, next_soe, battery_settings)
        if value > best_value:
            best_value = value
            best_action = power
            best_next_soe = next_soe
            best_new_cost_basis = new_cost_basis
            best_reward = reward
    return best_action, best_next_soe, best_new_cost_basis, best_reward
```

- [ ] **Step 4: Drop `policy` from `_run_dynamic_programming`**

In the function body from Task 2, remove `policy = np.zeros((horizon, len(soe_levels)))`,
remove `policy[t, i] = best_action`, remove the entire "Final safety check"
`np.clip` block at the end (it operated on `policy`, which no longer exists —
the per-action feasibility checks inside the loop already bound every chosen
`power` within `[-max_discharge_power_kw, max_charge_power_kw]`), and change
the final line to `return V`. Update the return type annotation to
`-> np.ndarray:`.

- [ ] **Step 5: Update the Step 1 call site**

In `optimize_battery_schedule` (currently `V, policy = _run_dynamic_programming(...)`
from Task 2):

```python
    V = _run_dynamic_programming(
```

- [ ] **Step 6: Rewrite Step 2**

Replace the entire Step 2 block, from the `hourly_results = []` line through
the end of the `for t in range(horizon):` loop (currently lines 1121-1193),
with:

```python
    hourly_results = []
    current_soe = initial_soe
    current_cost_basis = initial_cost_basis
    soe_levels = np.arange(
        battery_settings.min_soe_kwh,
        battery_settings.max_soe_kwh + SOE_STEP_KWH,
        SOE_STEP_KWH,
    )
    _, power_levels = _discretize_state_action_space(battery_settings)

    for t in range(horizon):
        # Recompute the action directly at the true continuous SoE using the
        # already-known V[t+1, :] (linearly interpolated) as the continuation
        # value -- the same reward+max(V) logic as the backward pass, applied
        # at the true state instead of one snapped to the nearest grid index.
        action, next_soe, new_cost_basis, _ = _best_action_at_continuous_state(
            soe=current_soe,
            t=t,
            V_next=V[t + 1],
            power_levels=power_levels,
            home_consumption=home_consumption,
            battery_settings=battery_settings,
            dt=dt,
            solar_production=solar_production,
            buy_price=buy_price,
            sell_price=sell_price,
            cost_basis=current_cost_basis,
            max_charge_power_per_period=max_charge_power_per_period,
        )

        period_data = _build_period_data(
            power=action,
            soe=current_soe,
            next_soe=next_soe,
            period=t,
            home_consumption=home_consumption[t],
            battery_settings=battery_settings,
            dt=dt,
            buy_price=buy_price,
            sell_price=sell_price,
            solar_production=solar_production[t],
            new_cost_basis=new_cost_basis,
            currency=currency,
        )

        # Shadow price = marginal opportunity value of stored energy (dV/dSoE),
        # by backward difference at the nearest grid level i (the kWh we
        # would remove by discharging). Unchanged from the previous
        # implementation -- this task only changes action selection, not
        # shadow_price reporting.
        i = round((current_soe - battery_settings.min_soe_kwh) / SOE_STEP_KWH)
        i = min(max(0, i), len(soe_levels) - 1)
        if i > 0:
            period_data.decision.shadow_price = float(
                (V[t, i] - V[t, i - 1]) / SOE_STEP_KWH
            )

        hourly_results.append(period_data)
        current_soe = next_soe
        current_cost_basis = new_cost_basis
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/bin/pytest core/bess/tests/unit/test_dp_no_guardrails.py -v`
Expected: all tests PASS.

- [ ] **Step 8: Run the fast suite to check for regressions**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add core/bess/dp_battery_algorithm.py core/bess/tests/unit/test_dp_no_guardrails.py
git commit -m "$(cat <<'EOF'
refactor: recompute replay actions from interpolated V instead of grid snap

Step 2 of optimize_battery_schedule used to snap the continuous SoE to the
nearest discretized grid index and trust that cell's stored policy action --
a policy computed for a slightly different state than the one actually
reached. Replaced with a one-step recompute at the true continuous SoE using
the already-known V[t+1, :] (linearly interpolated) as the continuation
value: the same reward+max(V) logic as the backward pass, just applied at
the true state. Reduces (does not eliminate) the SoE-grid discretization
residual the Task 3 safety net guards against. policy is no longer needed by
any caller and is dropped from _run_dynamic_programming's return.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Add the DP-never-worse-than-idle regression test across all fixtures

**Files:**
- Test: `core/bess/tests/unit/test_dp_no_guardrails.py` (append)

**Interfaces:**
- Consumes: `build_scenario_inputs`, `get_all_scenario_files` from `core/bess/tests/unit/test_scenarios.py` (existing, unchanged).

- [ ] **Step 1: Write the test**

Append to `core/bess/tests/unit/test_dp_no_guardrails.py`:

```python
import pytest as _pytest  # already imported above; kept for clarity in diff review

from core.bess.dp_battery_algorithm import _create_idle_schedule, optimize_battery_schedule
from core.bess.tests.unit.test_scenarios import build_scenario_inputs, get_all_scenario_files

pytestmark = _pytest.mark.slow


@_pytest.mark.parametrize("scenario_name", get_all_scenario_files())
def test_dp_output_never_worse_than_all_idle_schedule(scenario_name):
    """The numerical safety net in optimize_battery_schedule always returns
    whichever of (DP schedule, all-IDLE schedule) is cheaper -- so the
    optimizer's returned cost must never exceed the all-IDLE baseline,
    across every pinned fixture. This is the property the whole redesign
    rests on (docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md)."""
    scenario, battery_settings, buy_prices, sell_prices, dt = build_scenario_inputs(
        scenario_name
    )
    home_consumption = scenario["home_consumption"]
    solar_production = scenario["solar_production"]
    battery = scenario["battery"]
    horizon = len(buy_prices)

    result = optimize_battery_schedule(
        buy_price=buy_prices,
        sell_price=sell_prices,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=battery["initial_soe"],
        battery_settings=battery_settings,
        period_duration_hours=dt,
    )
    idle_result = _create_idle_schedule(
        horizon=horizon,
        buy_price=buy_prices,
        sell_price=sell_prices,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=battery["initial_soe"],
        battery_settings=battery_settings,
        dt=dt,
    )
    assert result.economic_summary.battery_solar_cost <= (
        idle_result.economic_summary.battery_solar_cost + 1e-6
    ), (
        f"{scenario_name}: DP schedule cost "
        f"{result.economic_summary.battery_solar_cost:.4f} exceeds all-IDLE "
        f"cost {idle_result.economic_summary.battery_solar_cost:.4f}"
    )
```

Note: this duplicates the assertion from Task 4's fixture-specific test, but
parametrized across all 26 fixtures rather than just one — both are kept
since the Task 4 test pins the specific regression the design doc
investigated, and this one is the general property check going forward.

- [ ] **Step 2: Run the test**

Run: `.venv/bin/pytest core/bess/tests/unit/test_dp_no_guardrails.py -m slow -v`
Expected: PASS for all 26 fixtures (this exercises the Task 3 safety net directly, so it should pass immediately given Tasks 1-4 are already in place).

- [ ] **Step 3: Commit**

```bash
git add core/bess/tests/unit/test_dp_no_guardrails.py
git commit -m "$(cat <<'EOF'
test: add DP-never-worse-than-idle regression across all pinned fixtures

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Add the plan-faithfulness test for the #240 self-throttling boundary

**Files:**
- Modify: `core/bess/tests/integration/test_plan_faithfulness.py` (append)

**Interfaces:**
- Consumes: `ControlCommand`, `simulate` from `core/bess/simulation/inverter_simulator.py` (existing, unchanged).

- [ ] **Step 1: Write the test**

Append to `core/bess/tests/integration/test_plan_faithfulness.py`:

```python
def test_load_support_self_throttles_discretization_overshoot():
    """#240 regression: load-first hardware never exports a discharge that
    overshoots home_consumption -- it self-throttles to the actual deficit,
    regardless of what a coarser discretized plan might have assumed. This
    locks in the physical behavior the #240 reward-model fix
    (core/bess/dp_battery_algorithm.py's _compute_reward) now assumes:
    before that fix, the plan credited export revenue for energy that was
    never actually exported, breaking R == P for these periods -- a case
    the existing hand-crafted plan-faithfulness scenarios were deliberately
    designed to avoid (see their own docstrings), so nothing else covers it.
    """
    from core.bess.simulation.inverter_simulator import ControlCommand, simulate
    from core.bess.tests.helpers import make_battery_settings

    bs = make_battery_settings()
    home = 1.15
    solar = 0.0
    cmd = ControlCommand("load_first", discharge_rate_pct=100, grid_charge=False)
    sim = simulate(
        [cmd],
        solar_production=[solar],
        home_consumption=[home],
        buy_price=[1.0],
        sell_price=[1.0],
        initial_soe=5.0,
        settings=bs,
        dt=1.0,
    )
    assert sim.period_data[0].energy.grid_exported == pytest.approx(0.0, abs=1e-9), (
        "load_first should never export -- it self-throttles to the actual "
        "home deficit, matching the #240-fixed reward model's assumption"
    )
```

- [ ] **Step 2: Run the test**

Run: `.venv/bin/pytest core/bess/tests/integration/test_plan_faithfulness.py::test_load_support_self_throttles_discretization_overshoot -v`
Expected: PASS (this tests `mode_to_power`'s existing, unchanged behavior — it already self-throttles; the test locks that in as a named, documented property rather than an implicit side effect).

- [ ] **Step 3: Commit**

```bash
git add core/bess/tests/integration/test_plan_faithfulness.py
git commit -m "$(cat <<'EOF'
test: lock in load_first self-throttling for the #240 boundary case

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Delete the two obsolete test files/tests

**Files:**
- Delete: `core/bess/tests/unit/test_action_threshold.py`
- Modify: `core/bess/tests/unit/test_scenarios.py:308-369` (remove `test_gate_never_substitutes_a_worse_fallback`)

- [ ] **Step 1: Delete `test_action_threshold.py`**

```bash
git rm core/bess/tests/unit/test_action_threshold.py
```

This file tested `min_action_profit_threshold`'s whole-day gate directly
(now removed in Task 3); the config field it exercised is no longer read by
the algorithm at all.

- [ ] **Step 2: Remove `test_gate_never_substitutes_a_worse_fallback`**

In `core/bess/tests/unit/test_scenarios.py`, delete the entire
`@pytest.mark.parametrize(...)` block and `test_gate_never_substitutes_a_worse_fallback`
function (currently lines 308-369). This test's premise — comparing the
gated result against a "gate disabled" re-run via
`dataclasses.replace(battery_settings, min_action_profit_threshold=-1e9)` —
no longer applies: there is no gate to disable, and the property it checked
("the fallback is never worse than the schedule it replaces") is now
unconditionally true by construction, covered by Task 5's regression test
instead.

Check whether `import dataclasses` (used only by this test, currently at
line 329) is still needed elsewhere in the file — if not, remove the
now-unused import too.

- [ ] **Step 3: Run the fast and slow suites**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS.

Run: `.venv/bin/pytest -m slow`
Expected: PASS. (This is the first full run of the slow suite in this plan — investigate and fix any failure here before continuing; do not loosen an assertion without understanding why it changed.)

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
test: remove tests for the removed min_action_profit_threshold gate

test_action_threshold.py tested the whole-day rejection gate directly, and
test_gate_never_substitutes_a_worse_fallback compared against a
gate-disabled re-run -- both premises no longer apply now that the gate is
gone and the property it checked is unconditionally true by construction
(see the Task 5 regression test).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Regenerate pinned fixture expectations and hand-verify every delta

**Files:**
- Modify: `core/bess/tests/unit/data/*.json` (only the files with an `expected_results` block: `historical_2024_08_16_high_spread_no_solar.json`, `historical_2025_01_05_no_spread_no_solar.json`, `historical_2025_01_12_evening_peak_no_solar.json`, `historical_2025_06_02_high_solar_export.json`, `historical_2025_01_13_night_low_no_solar.json`, `realworld_2026_03_24_225535.json`, `realworld_2026_04_11_004719.json`, `realworld_2026_04_22_202249.json` — confirm the full list with `grep -l expected_results core/bess/tests/unit/data/*.json` since this plan's earlier grep may be incomplete)

- [ ] **Step 1: Run the full scenario suite and capture failures**

Run: `.venv/bin/pytest core/bess/tests/unit/test_scenarios.py -m slow -v 2>&1 | tee /tmp/scenario_run.log`

Expected: some `test_all_scenarios[...]` cases FAIL on the `expected_results`
mismatch assertions (grid-only cost is unaffected by this redesign, but
`battery_solar_cost`, the savings, and the savings percentage will differ
for fixtures where the DP's chosen schedule changed).

- [ ] **Step 2: For each failing fixture, compute the new values directly**

For each fixture named in a failure, run:

```bash
.venv/bin/python3 -c "
import json
from core.bess.tests.unit.test_scenarios import build_scenario_inputs
from core.bess.dp_battery_algorithm import optimize_battery_schedule

name = 'REPLACE_WITH_FIXTURE_NAME'
scenario, battery_settings, buy_prices, sell_prices, dt = build_scenario_inputs(name)
result = optimize_battery_schedule(
    buy_price=buy_prices, sell_price=sell_prices,
    home_consumption=scenario['home_consumption'],
    solar_production=scenario['solar_production'],
    initial_soe=scenario['battery']['initial_soe'],
    battery_settings=battery_settings, period_duration_hours=dt,
)
s = result.economic_summary
print(f'base_cost: {s.grid_only_cost:.2f}')
print(f'battery_solar_cost: {s.battery_solar_cost:.2f}')
print(f'base_to_battery_solar_savings: {s.grid_to_battery_solar_savings:.2f}')
print(f'base_to_battery_solar_savings_pct: {s.grid_to_battery_solar_savings_pct:.2f}')
"
```

Before updating the fixture's `expected_results` block, sanity-check the
delta against this plan's design doc: per the empirical validation there,
every fixture except `historical_2025_01_05_no_spread_no_solar` should show
the new `battery_solar_cost` equal to or lower than the old pinned value
(savings equal or higher). If a fixture shows a *higher* cost (worse
savings) that isn't `historical_2025_01_05_no_spread_no_solar`, stop and
investigate — that would contradict this plan's own validation and points
to a real bug in Tasks 1-4, not a fixture that needs updating.

- [ ] **Step 3: Update each fixture's `expected_results` block**

Edit the JSON's `expected_results` object with the new values (matching the
JSON's existing key names: `base_cost`, `battery_solar_cost`,
`base_to_battery_solar_savings`, `base_to_battery_solar_savings_pct`). Leave
`base_cost` unchanged (grid-only cost doesn't depend on the DP at all, so it
should already match — if it doesn't, that's a separate bug, investigate
before proceeding).

- [ ] **Step 4: Re-run the scenario suite**

Run: `.venv/bin/pytest core/bess/tests/unit/test_scenarios.py -m slow -v`
Expected: all PASS, including the R == P plan-faithfulness assertion at the
end of `test_all_scenarios` (lines 271-305) for every one of the 26
fixtures — this is the check most directly relevant to the #240 fix; if it
fails for any fixture, that's a real control-fidelity bug to fix, not a
tolerance to loosen (the existing tolerance is
`max(0.5, 0.01 * abs(planned_cost))`).

- [ ] **Step 5: Commit**

```bash
git add core/bess/tests/unit/data/
git commit -m "$(cat <<'EOF'
test: regenerate pinned expected_results after guardrail removal

Each delta was hand-verified against the design doc's empirical validation
before updating -- every fixture except historical_2025_01_05_no_spread_no_solar
(the known, safety-net-covered regression) should show equal or better
savings, never worse.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8b: Fix `classify_strategic_intent`'s inconsistent BATTERY_EXPORT threshold

**Discovered mid-Task-8, not in the original spec.** Running the R == P
plan-faithfulness check (in `test_scenarios.py::test_all_scenarios`) after
updating the 15 legitimate fixtures in Task 8 revealed a real
control-fidelity bug on 8 of 9 quarter-hourly (`period_duration_hours=0.25`)
fixtures, with gaps of 1.6-18.7 SEK between planned and realized cost —
`realized` always worse than `planned`.

**Root cause, traced on `realworld_2026_04_27_211212` period 42:** the DP
plans a genuinely tiny discharge (0.05 kWh) during a period with abundant
solar surplus (solar=3.5, home=0.2) — this discharge is 100% export
(`battery_to_home=0.0`, `battery_to_grid=0.05`), a real, marginally
profitable micro-arbitrage, not a discretization artifact (the #240 fix from
Task 1 only zeroes out overshoot *up to* 0.1 kWh **beyond consumption**; this
period's total exported energy is 3.35 kWh, far above that — #240's fix
correctly does not suppress it).

But `decision_intelligence.classify_strategic_intent`
(`core/bess/decision_intelligence.py:414-445`) classifies a discharge as
`BATTERY_EXPORT` only if `battery_to_grid > 0.1` — otherwise `LOAD_SUPPORT`,
regardless of whether any home deficit was actually covered. Since
`0.05 <= 0.1`, this 100%-export discharge is mislabeled `LOAD_SUPPORT`. Every
other flow check in the same function uses `0.01` as its "meaningfully
nonzero" threshold (`grid_to_battery > 0.01`, `battery_charged > 0.01`,
`battery_discharged > 0.01`, `grid_exported > 0.01`) — only this one check
uses the ten-times-coarser `0.1`, with no evident reason.

`LOAD_SUPPORT` maps to `load_first` mode. In
`core/bess/simulation/inverter_simulator.py`'s `mode_to_power`, `load_first`
computes `deficit = max(0.0, home - solar) = max(0.0, 0.2 - 3.5) = 0.0` (correctly
— there is no real deficit) and returns exactly `0.0`. But
`_state_transition` (`core/bess/dp_battery_algorithm.py`) treats `power == 0`
as "IDLE — passive solar charging," which absorbs the *entire* solar surplus
that period (~3.3 kWh) into the battery — a completely different, much larger
action than either the plan or "do nothing." That single period's SoE
diverges by kWh, not by 0.05 kWh, and every subsequent period's decision
depends on the SoE actually reached, so the error compounds for the rest of
the horizon instead of washing out.

`grid_first` (`BATTERY_EXPORT`'s mode) has no equivalent discontinuity: it
always delivers `rate_kw * dt` proportional to `discharge_rate_pct`, and
since it's a strict superset of `load_first`'s capability (the resulting
energy balance naturally splits between covering any real deficit and
exporting the rest), reclassifying this case as `BATTERY_EXPORT` makes the
plan physically realizable with no discontinuity.

**This fix does not change the DP's own cost calculation.**
`classify_strategic_intent` is a post-hoc labeling/execution-mapping
function; backward induction never reads it. So this task changes zero
`expected_results` values — only the reported intent label for borderline
periods and which hardware mode gets commanded at execution time (which is
exactly what closes the R == P gap).

**Files:**
- Modify: `core/bess/decision_intelligence.py:432` (the `BATTERY_EXPORT`
  threshold inside `classify_strategic_intent`)
- Modify: `core/bess/models.py:53` (the same threshold bug in
  `infer_intent_from_flows` — this function's own docstring says it's
  "OBSERVATIONAL purposes only (dashboard display)... not authoritative,"
  so it doesn't cause the R == P failures this task is primarily about, but
  it has the identical inconsistency: every other check in that function
  uses `0.01` (`grid_to_battery > 0.01`), and its own comment on the `0.1`
  line literally says "ANY export needs capability" — contradicting the
  threshold it's attached to. Fix for consistency while touching this
  pattern.
- Test: add to `core/bess/tests/unit/test_dp_no_guardrails.py`, or a new
  small test file if you judge the existing one doesn't fit topically — your
  call, but justify it in the report if you deviate from
  `test_dp_no_guardrails.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `classify_strategic_intent`'s public signature is unchanged;
  only the `BATTERY_EXPORT` vs `LOAD_SUPPORT` boundary for discharges moves
  from `0.1` to `0.01`.

- [ ] **Step 1: Write the failing test**

```python
def test_small_export_only_discharge_classified_as_battery_export():
    """A discharge with zero home-deficit coverage and a small (but
    meaningfully nonzero) export must be classified BATTERY_EXPORT, not
    LOAD_SUPPORT -- LOAD_SUPPORT maps to load_first, which physically cannot
    export at all (core/bess/simulation/inverter_simulator.py's mode_to_power
    caps load_first delivery at max(0, home-solar), i.e. zero when solar
    already covers home). Mislabeling this as LOAD_SUPPORT makes the plan
    unrealizable: real/simulated hardware delivers zero instead of the
    planned export, and that zero triggers passive solar charging instead
    (_state_transition's IDLE branch), a much larger, unplanned action.
    Regression for the R == P failures traced on
    realworld_2026_04_27_211212 period 42 during Task 8's fixture
    regeneration."""
    from core.bess.decision_intelligence import classify_strategic_intent
    from core.bess.models import EnergyData

    energy_data = EnergyData(
        solar_production=3.5,
        home_consumption=0.2,
        battery_charged=0.0,
        battery_discharged=0.05,
        grid_imported=0.0,
        grid_exported=3.35,
        battery_soe_start=7.68,
        battery_soe_end=7.63,
    )
    intent = classify_strategic_intent(power=-0.2, energy_data=energy_data)
    assert intent == "BATTERY_EXPORT", (
        f"expected BATTERY_EXPORT for a 100%-export discharge, got {intent}"
    )
```

Note: `EnergyData`'s `battery_to_grid`/`battery_to_home` are derived
properties computed from the constructor fields above (energy conservation
decomposition) — check `core/bess/models.py` for their exact derivation if
the test doesn't produce `battery_to_grid=0.05`/`battery_to_home=0.0` as
expected, and adjust the constructor fields (not the assertion) to match a
genuine 100%-export scenario.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_dp_no_guardrails.py::test_small_export_only_discharge_classified_as_battery_export -v`
Expected: FAIL (`AssertionError: expected BATTERY_EXPORT ..., got LOAD_SUPPORT`)

- [ ] **Step 3: Fix the threshold in `decision_intelligence.py`**

In `core/bess/decision_intelligence.py`, change:

```python
    if power < -_POWER_THRESHOLD_KW:  # Discharging
        if energy_data.battery_to_grid > 0.1:
            return "BATTERY_EXPORT"
        return "LOAD_SUPPORT"
```

to:

```python
    if power < -_POWER_THRESHOLD_KW:  # Discharging
        # Any meaningfully nonzero export (same 0.01 kWh noise floor used by
        # every other flow check in this function) must be BATTERY_EXPORT:
        # LOAD_SUPPORT maps to load_first, which can only ever cover a real
        # deficit and physically cannot export -- see
        # docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md
        # for the R == P failure this threshold mismatch caused.
        if energy_data.battery_to_grid > 0.01:
            return "BATTERY_EXPORT"
        return "LOAD_SUPPORT"
```

- [ ] **Step 3b: Fix the identical threshold bug in `models.py`**

In `core/bess/models.py`'s `infer_intent_from_flows`, change:

```python
    elif power < -0.1:  # DISCHARGING
        if energy_data.battery_to_grid > 0.1:  # ANY export needs capability
            return "BATTERY_EXPORT"  # Enable export capability
        else:
            return "LOAD_SUPPORT"  # Pure home support
```

to:

```python
    elif power < -0.1:  # DISCHARGING
        if energy_data.battery_to_grid > 0.01:  # ANY export needs capability
            return "BATTERY_EXPORT"  # Enable export capability
        else:
            return "LOAD_SUPPORT"  # Pure home support
```

This function is observational/dashboard-display only (per its own
docstring) and isn't in the R == P execution path, but it has the identical
inconsistency against its own sibling check (`grid_to_battery > 0.01`) and
its own comment ("ANY export needs capability") already states the intent
the `0.01` threshold now matches.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_dp_no_guardrails.py::test_small_export_only_discharge_classified_as_battery_export -v`
Expected: PASS

- [ ] **Step 5: Run the fast suite**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS. If any existing test asserts a specific intent label for a
borderline discharge (`battery_to_grid` between 0.01 and 0.1) that now
flips from `LOAD_SUPPORT` to `BATTERY_EXPORT`, investigate whether that
test's fixture genuinely has zero home-deficit coverage for that period
(in which case update the expected label, it was asserting the old bug) or
a real deficit (in which case something in this fix's reasoning is wrong —
escalate, don't force the test to pass).

- [ ] **Step 6: Re-run the specific R == P failures this fix targets**

Run: `.venv/bin/pytest core/bess/tests/unit/test_scenarios.py -k "realworld_2026_04_11_004719 or realworld_2026_04_19_084608 or realworld_2026_04_22_202249 or realworld_2026_04_24_090423 or realworld_2026_04_27_184643 or realworld_2026_04_27_211212 or realworld_2026_04_29_195900 or realworld_2026_04_29_220919" -m slow -v`

Expected: the R == P plan-faithfulness assertion (not necessarily the
`expected_results` assertion — that's Task 8's job, unaffected by this fix)
now passes for all 8. If any still fail R == P, report DONE_WITH_CONCERNS
with specifics rather than treating this step as optional.

- [ ] **Step 7: Commit**

```bash
git add core/bess/decision_intelligence.py core/bess/models.py core/bess/tests/unit/test_dp_no_guardrails.py
git commit -m "$(cat <<'EOF'
fix: classify_strategic_intent uses consistent 0.01 kWh export threshold

The BATTERY_EXPORT check used a 0.1 kWh threshold, ten times coarser than
every other flow check in this function (0.01). A discharge with zero home-
deficit coverage and a small (0.01-0.1 kWh) export was misclassified
LOAD_SUPPORT, which maps to load_first -- a mode that can only cover a real
deficit and physically cannot export. When the deficit-based delivery
computed exactly zero, _state_transition's IDLE branch absorbed the entire
solar surplus instead, a much larger unplanned action whose error compounded
for the rest of the horizon. Traced via Task 8's R == P failures on 8 of 9
quarter-hourly fixtures (gaps up to 18.7 SEK).

Also fixes the identical inconsistency in models.py's infer_intent_from_flows
(observational/dashboard-display only, not in the R == P execution path, but
the same threshold mismatch against its own sibling checks).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Verify `test_cost_basis_calculation.py`, `test_solar_export_discharge_gate.py`, and `test_optimization_algorithm.py` still pass

**Files:**
- Read-only verification: `core/bess/tests/unit/test_cost_basis_calculation.py`, `core/bess/tests/unit/test_solar_export_discharge_gate.py`, `core/bess/tests/unit/test_optimization_algorithm.py`

- [ ] **Step 1: Run all three files**

Run: `.venv/bin/pytest core/bess/tests/unit/test_cost_basis_calculation.py core/bess/tests/unit/test_solar_export_discharge_gate.py core/bess/tests/unit/test_optimization_algorithm.py -v -m "not slow"`

Run: `.venv/bin/pytest core/bess/tests/unit/test_optimization_algorithm.py -v -m slow`

Expected: all PASS. `test_cost_basis_calculation.py` tests
`BatterySystemManager._calculate_initial_cost_basis`, an independent
FIFO-accounting code path unrelated to `_compute_reward`'s removed floor —
should be entirely unaffected. `test_solar_export_discharge_gate.py` tests
the intra-period `solar_export_discharge_rate` runtime gate in
`battery_system_manager.py`, a different mechanism not touched by this
plan — should be entirely unaffected.
`test_optimization_algorithm.py::test_defers_charging_to_cheaper_overnight_window`
(the multi-window scenario at line 308, using `initial_cost_basis=1.644`)
exercises behavior close to what Tasks 1 and 3 changed — if it fails,
investigate whether the new schedule's `max_soe_during_tonight`,
`discharged_in_window`, and `grid_to_battery_solar_savings` assertions still
hold for a legitimate reason (the schedule genuinely changed but the
underlying property being tested — no over-charging tonight, batteries used
during the expensive window, savings aren't near-zero — should still be
true) before touching any assertion threshold.

- [ ] **Step 2: If `test_defers_charging_to_cheaper_overnight_window` fails, investigate before changing anything**

Print the actual schedule and compare against the assertions' intent (see
the test's own docstring for the property being guarded). Only adjust an
assertion's numeric threshold if the underlying property still holds and
the old threshold was simply tuned to the old algorithm's specific output;
if the property itself no longer holds, that's a bug in Tasks 1-4, not a
test to relax.

- [ ] **Step 3: Commit (only if any file needed changes)**

```bash
git add core/bess/tests/unit/test_optimization_algorithm.py
git commit -m "$(cat <<'EOF'
test: update test_defers_charging_to_cheaper_overnight_window expectations

State, in the commit body, exactly which assertion(s) changed and why the
underlying property (no over-charging tonight / battery used during the
expensive window / savings aren't near-zero) still holds with the new
threshold -- not just that a number moved.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

If nothing needed changes, skip this commit.

---

### Task 10: Full regression suite and quality gate

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `.venv/bin/pytest`
Expected: PASS, no skips beyond pre-existing ones unrelated to this plan.

- [ ] **Step 2: Run the quality gate**

Run: `./scripts/quality-check.sh`
Expected: PASS (Black formatting, Ruff lint, mypy).

- [ ] **Step 3: Confirm no stray references to removed symbols**

Run: `grep -rn "min_action_profit_threshold" core/bess/dp_battery_algorithm.py`
Expected: no output (the algorithm no longer reads this field anywhere).

Run: `grep -rn "THRESHOLD_HORIZON_FLOOR\|effective_cost_basis\|stored_period_data" core/bess/dp_battery_algorithm.py`
Expected: no output.

- [ ] **Step 4: Commit if quality-check.sh made formatting changes**

```bash
git add -A
git commit -m "$(cat <<'EOF'
style: black/ruff formatting pass

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

If `quality-check.sh` made no changes, skip this commit.

---

## Follow-up (not in this plan)

- File a separate issue: remove `min_action_profit_threshold` from
  `bess_manager/config.yaml`'s HA add-on schema and `BatterySettings`, once
  this plan has shipped and the field is confirmed unused in production.
