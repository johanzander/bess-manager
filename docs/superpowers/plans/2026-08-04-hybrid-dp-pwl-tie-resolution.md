# Hybrid Grid-DP + Windowed Exact-PWL Tie Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix #450 (SOE grid-snap noise flipping near-tied DP decisions) by detecting near-tied periods in the existing grid DP and re-solving only those narrow windows exactly with a piecewise-linear (PWL) DP, instead of replacing the whole-horizon solver with a MILP (PR #461's approach).

**Architecture:** The existing grid-based `_best_action_at_continuous_state` in `core/bess/dp_battery_algorithm.py` gains a side-channel that records the cost margin between its chosen action and the runner-up at each period, at zero cost to its existing behavior. A new pure-function tie detector turns those margins into a list of narrow windows. A new PWL window resolver (backward induction over a piecewise-linear value function, continuous SOE, ported from the #461 branch's reference implementation and extended to pin exact start/end SOE) re-solves just those windows exactly. A splicer swaps the windows' actions into the DP's schedule and replays the whole thing through the existing, unmodified `_compute_reward`/`_build_period_data` accounting.

**Tech Stack:** Python, NumPy (existing dependency — no new dependency, unlike PR #461's `scipy`). No MILP solver, no new external dependency.

## Global Constraints

- No new third-party dependencies (this is a design goal of the whole approach — see spec's "Why this instead of full MILP").
- Follow `docs/agents/testing.md` conventions: TDD, `pytest -m "not slow"` for fast unit tests, fixture-based scenario tests via `core/bess/tests/unit/test_scenarios.py`'s `build_scenario_inputs`/`load_test_scenario` pattern.
- No silent fallbacks: any infeasible or unexpected state in the window resolver must raise, never silently fall back to the (possibly wrong) grid-DP choice for that window.
- Run `black .` and `ruff check --fix .` before each commit (project's quality gate).
- The common case (no ties detected) must produce byte-identical output to today's `optimize_battery_schedule` — every task that touches the DP's hot path must preserve this.

---

## File Structure

| File | Responsibility |
|---|---|
| `core/bess/dp_battery_algorithm.py` | Modified: `_best_action_at_continuous_state` records runner-up cost; `optimize_battery_schedule` gains the tie-detect → resolve → splice step. |
| `core/bess/tie_detection.py` | New. Pure function: margins → list of `Window` (start, end period indices). No DP/PWL dependency. |
| `core/bess/pwl_window_dp.py` | New. PWL backward-induction DP (ported from PR #461's reference implementation) with pinned start/end SOE, scoped to a sub-horizon window. |
| `core/bess/schedule_splicer.py` | New. Replaces a schedule's window periods with the PWL resolver's actions, replays through `_compute_reward`/`_build_period_data`. |
| `core/bess/tests/unit/data/regression_2026_08_02_043728.json` | New (ported). The #450 reproduction fixture, ported from the PR #461 branch. |
| `core/bess/tests/unit/test_tie_detection.py` | New. Pure unit tests for the tie detector. |
| `core/bess/tests/unit/test_pwl_window_dp.py` | New. Unit tests for the windowed PWL solver, including terminal-SOE pinning. |
| `core/bess/tests/unit/test_schedule_splicer.py` | New. Unit tests for splicing + accounting replay. |
| `core/bess/tests/unit/test_issue_450_hybrid_resolution.py` | New. End-to-end regression test using the #450 fixture. |

---

### Task 1: Port the #450 regression fixture

**Files:**
- Create: `core/bess/tests/unit/data/regression_2026_08_02_043728.json`

**Interfaces:**
- Produces: a scenario fixture loadable by `load_test_scenario("regression_2026_08_02_043728")` (see `core/bess/tests/unit/test_scenarios.py:38`).

- [ ] **Step 1: Port the fixture verbatim from the PR #461 branch**

```bash
git show fix/issue-450-soe-grid-snap-interpolation:core/bess/tests/unit/data/regression_2026_08_02_043728.json \
  > core/bess/tests/unit/data/regression_2026_08_02_043728.json
```

- [ ] **Step 2: Confirm it loads via the existing scenario loader**

```bash
.venv/bin/python -c "
from core.bess.tests.unit.test_scenarios import load_test_scenario
scenario = load_test_scenario('regression_2026_08_02_043728')
print(scenario['name'], scenario['issue'], len(scenario['buy_price']))
"
```

Expected: prints `regression_2026_08_02_043728 450 <N>` with no error.

- [ ] **Step 3: Commit**

```bash
git add core/bess/tests/unit/data/regression_2026_08_02_043728.json
git commit -m "test: port #450 regression fixture for hybrid tie-resolution work"
```

---

### Task 2: Record the runner-up cost margin in the grid DP's forward replay

**Files:**
- Modify: `core/bess/dp_battery_algorithm.py:1151` (`_best_action_at_continuous_state`)
- Test: `core/bess/tests/unit/test_dp_breakpoint_search.py`

**Interfaces:**
- Consumes: nothing new — same inputs as today's `_best_action_at_continuous_state`.
- Produces: `_best_action_at_continuous_state` returns a 5-tuple instead of 4:
  `(best_action: float, best_next_soe: float, best_new_cost_basis: float, best_reward: float, tie_margin: float)`
  where `tie_margin = best_value - second_best_value` (a large positive number, e.g. `float("inf")`, if fewer than two feasible candidates were considered — meaning "not tied, no comparison possible").

- [ ] **Step 1: Write the failing test**

Add to `core/bess/tests/unit/test_dp_breakpoint_search.py`:

```python
def test_best_action_returns_tie_margin():
    """_best_action_at_continuous_state must report the gap between its
    chosen action's value and the runner-up's, so the hybrid tie detector
    (#450) can find near-tied periods without re-deriving this comparison."""
    battery_settings, buy_prices, sell_prices, home_consumption, solar_production, V, dt = _prepare(
        "regression_2026_08_02_043728"
    )
    t = 0
    soe = 2.0  # matches the fixture's documented initial_soe
    result = _best_action_at_continuous_state(
        soe, t, V[t + 1],
        power_levels=np.array([]),  # unused by current implementation; keep call-compatible
        home_consumption=home_consumption,
        battery_settings=battery_settings,
        dt=dt,
        solar_production=solar_production,
        buy_price=buy_prices,
        sell_price=sell_prices,
        cost_basis=0.0,
        max_charge_power_per_period=None,
    )
    assert len(result) == 5, "expected (action, next_soe, cost_basis, reward, tie_margin)"
    _, _, _, _, tie_margin = result
    assert tie_margin >= 0.0, "margin must be non-negative (best >= second-best by construction)"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest core/bess/tests/unit/test_dp_breakpoint_search.py::test_best_action_returns_tie_margin -v
```

Expected: FAIL — `ValueError: not enough values to unpack (expected 5, got 4)`.

- [ ] **Step 3: Implement the margin tracking**

In `core/bess/dp_battery_algorithm.py`, inside `_best_action_at_continuous_state`, change the `consider()` closure and return statement:

```python
best_value = -float("inf")
second_best_value = -float("inf")
best_action = 0.0
best_next_soe = soe
best_new_cost_basis = cost_basis
best_reward = 0.0

def consider(power: float) -> None:
    nonlocal best_value, second_best_value, best_action, best_next_soe
    nonlocal best_new_cost_basis, best_reward
    next_soe = _state_transition(
        soe, power, battery_settings, dt,
        solar_production=solar, home_consumption=home,
    )
    if next_soe < _soe_floor(soe, battery_settings) or next_soe > battery_settings.max_soe_kwh:
        return
    reward, new_cost_basis = _compute_reward(...)  # unchanged call, same args as today
    value = reward + _interpolate_value(V_next, next_soe, battery_settings)
    if value > best_value:
        second_best_value = best_value
        best_value = value
        best_action = power
        best_next_soe = next_soe
        best_new_cost_basis = new_cost_basis
        best_reward = reward
    elif value > second_best_value:
        second_best_value = value
```

At the end of the function, replace the return statement:

```python
tie_margin = best_value - second_best_value  # +inf-ish (second_best stays -inf) if never demoted
return best_action, best_next_soe, best_new_cost_basis, best_reward, tie_margin
```

Note: keep every existing `consider(...)` call site (`consider(0.0)`, the SOLAR_EXPORT-below-max bypass, the discharge-candidate loop, the charge candidate) exactly as-is — only the closure body and final return line change.

- [ ] **Step 4: Update the one caller in `optimize_battery_schedule`**

At `core/bess/dp_battery_algorithm.py:1567`, the forward loop currently unpacks 4 values. Update it to capture the 5th and accumulate a `tie_margins: list[float]` list alongside the existing per-period accumulation:

```python
tie_margins: list[float] = []
for t in range(horizon):
    action, next_soe, cost_basis, reward, tie_margin = _best_action_at_continuous_state(...)
    tie_margins.append(tie_margin)
    ...  # existing logic unchanged
```

- [ ] **Step 5: Run test to verify it passes**

```bash
.venv/bin/pytest core/bess/tests/unit/test_dp_breakpoint_search.py::test_best_action_returns_tie_margin -v
```

Expected: PASS.

- [ ] **Step 6: Run the full fast suite to confirm no regression**

```bash
.venv/bin/pytest -m "not slow"
```

Expected: same pass count as before this change (this step only added an output field; no DP decision logic changed).

- [ ] **Step 7: Commit**

```bash
git add core/bess/dp_battery_algorithm.py core/bess/tests/unit/test_dp_breakpoint_search.py
git commit -m "feat: record tie margin in grid DP's forward action selection (#450)"
```

---

### Task 3: Tie Detector

**Files:**
- Create: `core/bess/tie_detection.py`
- Test: `core/bess/tests/unit/test_tie_detection.py`

**Interfaces:**
- Consumes: `tie_margins: list[float]` from Task 2, `soe_step_kwh: float` (from `dp_constants.SOE_STEP_KWH`), `buy_price: list[float]`, `sell_price: list[float]`.
- Produces:
  ```python
  @dataclass(frozen=True)
  class Window:
      start: int  # inclusive period index, post-padding
      end: int    # exclusive period index, post-padding

  def detect_tie_windows(
      tie_margins: list[float],
      buy_price: list[float],
      sell_price: list[float],
      soe_step_kwh: float,
      pad: int = 2,
  ) -> list[Window]:
      ...
  ```
  Later tasks (Window Resolver, Splicer) consume `list[Window]` and index into the schedule with `.start`/`.end` (Python slice semantics: `schedule[window.start:window.end]`).

- [ ] **Step 1: Write the failing tests**

Create `core/bess/tests/unit/test_tie_detection.py`:

```python
from core.bess.tie_detection import Window, detect_tie_windows


def _prices(n: int) -> tuple[list[float], list[float]]:
    return [1.0] * n, [0.5] * n


def test_no_ties_returns_empty_list():
    buy, sell = _prices(10)
    margins = [10.0] * 10  # every period has a large, clear margin
    assert detect_tie_windows(margins, buy, sell, soe_step_kwh=0.05) == []


def test_isolated_tie_produces_single_padded_window():
    buy, sell = _prices(10)
    margins = [10.0] * 10
    margins[5] = 0.0001  # near-zero margin at period 5
    windows = detect_tie_windows(margins, buy, sell, soe_step_kwh=0.05, pad=2)
    assert windows == [Window(start=3, end=8)]  # 5-2 .. 5+2+1, clamped to bounds by construction here


def test_two_ties_close_together_merge_into_one_window():
    buy, sell = _prices(10)
    margins = [10.0] * 10
    margins[4] = 0.0001
    margins[5] = 0.0001
    windows = detect_tie_windows(margins, buy, sell, soe_step_kwh=0.05, pad=2)
    assert len(windows) == 1
    assert windows[0].start <= 2 and windows[0].end >= 8


def test_two_ties_far_apart_stay_separate():
    buy, sell = _prices(20)
    margins = [10.0] * 20
    margins[2] = 0.0001
    margins[17] = 0.0001
    windows = detect_tie_windows(margins, buy, sell, soe_step_kwh=0.05, pad=2)
    assert len(windows) == 2


def test_windows_clamped_to_horizon_bounds():
    buy, sell = _prices(5)
    margins = [10.0] * 5
    margins[0] = 0.0001
    margins[4] = 0.0001
    windows = detect_tie_windows(margins, buy, sell, soe_step_kwh=0.05, pad=2)
    for w in windows:
        assert 0 <= w.start < w.end <= 5
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest core/bess/tests/unit/test_tie_detection.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'core.bess.tie_detection'`.

- [ ] **Step 3: Implement**

Create `core/bess/tie_detection.py`:

```python
"""Pure-function detection of near-tied DP decisions (#450).

The grid DP's SOE_STEP_KWH grid-snapping introduces noise into its
continuation-value lookups roughly on the order of
SOE_STEP_KWH/2 * (a representative shadow price). Rather than tune an
arbitrary SEK threshold, epsilon is derived from that same grid step,
scaled by the period's own price spread (buy - sell) as the closest
available stand-in for the local shadow price magnitude -- keeping the
threshold principled and self-scaling across fixtures with very
different price levels.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Window:
    start: int
    end: int


def _epsilon_for_period(buy_price: float, sell_price: float, soe_step_kwh: float) -> float:
    price_spread = max(abs(buy_price - sell_price), 0.01)
    return soe_step_kwh * price_spread


def detect_tie_windows(
    tie_margins: list[float],
    buy_price: list[float],
    sell_price: list[float],
    soe_step_kwh: float,
    pad: int = 2,
) -> list[Window]:
    horizon = len(tie_margins)
    flagged = [
        t for t in range(horizon)
        if tie_margins[t] < _epsilon_for_period(buy_price[t], sell_price[t], soe_step_kwh)
    ]
    if not flagged:
        return []

    raw_windows: list[Window] = []
    for t in flagged:
        start = max(0, t - pad)
        end = min(horizon, t + pad + 1)
        raw_windows.append(Window(start=start, end=end))

    raw_windows.sort(key=lambda w: w.start)
    merged: list[Window] = [raw_windows[0]]
    for w in raw_windows[1:]:
        last = merged[-1]
        if w.start <= last.end:
            merged[-1] = Window(start=last.start, end=max(last.end, w.end))
        else:
            merged.append(w)
    return merged
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest core/bess/tests/unit/test_tie_detection.py -v
```

Expected: PASS, all 5 tests.

- [ ] **Step 5: Commit**

```bash
git add core/bess/tie_detection.py core/bess/tests/unit/test_tie_detection.py
git commit -m "feat: add pure tie-window detector for #450 hybrid resolution"
```

---

### Task 4: Port the PWL backward-induction primitives

**Files:**
- Create: `core/bess/pwl_window_dp.py`
- Test: `core/bess/tests/unit/test_pwl_window_dp.py`

**Interfaces:**
- Consumes (imports from `core/bess/dp_battery_algorithm.py`, all already present in this worktree): `_state_transition`, `_state_transition_grid`, `_compute_reward`, `_compute_reward_grid`, `_soe_floor`, `_discharge_candidates`, `_charge_candidate`, `_effective_ac_cap_kwh`, `BatterySettings`, `POWER_TOLERANCE_KW`, `POWER_CLASSIFICATION_THRESHOLD_KW`, `BATTERY_EXPORT_THRESHOLD_KWH`.
- Produces: `_pwl_eval_array(V_row, soe)`, `_pwl_prune(xs, vs, eps)`, `_pwl_best_action_at_continuous_state(...)` (same shape as the grid DP's `_best_action_at_continuous_state` but reads a PWL `V_row` instead of a grid array) — consumed by Task 5's window resolver.

- [ ] **Step 1: Verify the exact source to port still matches what was found during design research**

```bash
git show fix/issue-450-soe-grid-snap-interpolation:core/bess/dp_battery_algorithm.py | sed -n '899,1308p' > /tmp/pwl_core_extract.py
wc -l /tmp/pwl_core_extract.py
```

Expected: extracts `_pwl_prune`, `_backward_discharge_levels`, `_candidate_values_at`, `_pwl_eval_array`, `_interpolate_value` (PWL variant) — read the extracted file to confirm the boundaries are clean function definitions (no truncated function at the top or bottom). Adjust the `sed` line range if a function is cut mid-body.

- [ ] **Step 2: Write the failing test for the ported PWL evaluator**

Create `core/bess/tests/unit/test_pwl_window_dp.py`:

```python
import numpy as np
from core.bess.pwl_window_dp import _pwl_eval_array, _pwl_prune


def test_pwl_eval_array_interpolates_between_breakpoints():
    xs = np.array([0.0, 5.0, 10.0])
    vs = np.array([0.0, 10.0, 15.0])
    result = _pwl_eval_array((xs, vs), np.array([2.5, 7.5]))
    assert result[0] == pytest.approx(5.0)
    assert result[1] == pytest.approx(12.5)


def test_pwl_eval_array_extrapolates_below_first_breakpoint():
    xs = np.array([1.0, 2.0])
    vs = np.array([10.0, 20.0])
    result = _pwl_eval_array((xs, vs), np.array([0.0]))
    assert result[0] == pytest.approx(0.0)  # slope 10/unit, extrapolated down from (1, 10)


def test_pwl_prune_drops_collinear_interior_points():
    xs = np.array([0.0, 1.0, 2.0, 3.0])
    vs = np.array([0.0, 1.0, 2.0, 3.0])  # perfectly linear -- interior points are redundant
    pruned_xs, pruned_vs = _pwl_prune(xs, vs, eps=1e-9)
    assert len(pruned_xs) == 2
    assert list(pruned_xs) == [0.0, 3.0]
```

Add `import pytest` at the top of the file.

- [ ] **Step 3: Run tests to verify they fail**

```bash
.venv/bin/pytest core/bess/tests/unit/test_pwl_window_dp.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'core.bess.pwl_window_dp'`.

- [ ] **Step 4: Create `core/bess/pwl_window_dp.py` with the ported primitives**

Start the file with the module docstring and imports, then paste in the four functions extracted in Step 1 verbatim (`_pwl_prune`, `_backward_discharge_levels`, `_candidate_values_at`, `_pwl_eval_array`), renaming `_candidate_values_at` to `_pwl_candidate_values_at` for clarity in this new module, and updating its internal calls to `_state_transition_grid`/`_compute_reward_grid`/`_effective_ac_cap_kwh` to be imported from `dp_battery_algorithm`:

```python
"""Windowed piecewise-linear (PWL) DP for exact resolution of near-tied
decisions flagged by core.bess.tie_detection (#450).

This is the exact-PWL backward induction originally prototyped as the
reference implementation on the PR #461 branch (continuous SOE, no grid
snapping, proven exact to ~1e-10 against the true optimum), narrowed here
to run over a short sub-horizon window with pinned start/end SOE instead
of the full schedule -- see
docs/superpowers/specs/2026-08-04-hybrid-dp-pwl-tie-resolution-design.md
for why only the tied window gets this treatment instead of the whole
horizon.
"""

import numpy as np

from core.bess.dp_battery_algorithm import (
    BATTERY_EXPORT_THRESHOLD_KWH,
    POWER_CLASSIFICATION_THRESHOLD_KW,
    POWER_TOLERANCE_KW,
    BatterySettings,
    _compute_reward_grid,
    _effective_ac_cap_kwh,
    _state_transition_grid,
)

PWL_EPS_REFINE = 1e-6
PWL_EPS_PRUNE = 1e-6


# --- paste _pwl_prune, _backward_discharge_levels, _pwl_candidate_values_at,
#     _pwl_eval_array here, verbatim from /tmp/pwl_core_extract.py, with
#     _candidate_values_at renamed to _pwl_candidate_values_at and its
#     internal reference to itself (if recursive/self-referential) updated
#     to match.
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/bin/pytest core/bess/tests/unit/test_pwl_window_dp.py -v
```

Expected: PASS, all 3 tests.

- [ ] **Step 6: Commit**

```bash
git add core/bess/pwl_window_dp.py core/bess/tests/unit/test_pwl_window_dp.py
git commit -m "feat: port PWL value-function primitives for windowed tie resolution (#450)"
```

---

### Task 5: Windowed PWL backward induction with pinned start/end SOE

**Files:**
- Modify: `core/bess/pwl_window_dp.py`
- Test: `core/bess/tests/unit/test_pwl_window_dp.py`

**Interfaces:**
- Consumes: `_pwl_candidate_values_at`, `_pwl_eval_array`, `_pwl_prune` from Task 4.
- Produces:
  ```python
  def run_pwl_window_backward_induction(
      window_horizon: int,
      buy_price: list[float],
      sell_price: list[float],
      home_consumption: list[float],
      solar_production: list[float],
      battery_settings: BatterySettings,
      dt: float,
      end_soe_target: float,
      end_soe_tolerance: float = 1e-6,
      max_charge_power_per_period: list[float] | None = None,
      self_throttle_export_threshold_kwh: float = BATTERY_EXPORT_THRESHOLD_KWH,
      discharge_resolution_kw: float | None = None,
  ) -> list[tuple[np.ndarray, np.ndarray]]:
      ...  # returns V rows, V[window_horizon] pinned near end_soe_target
  ```
  Consumed by Task 6's window resolver, which forward-replays through this V table starting from the window's known start SOE.

This is the design's key open question ("Whether the exact-PWL DP prototype needs adaptation to accept pinned start/end SOE boundary conditions") — resolved here via a steep-penalty terminal value: `V[window_horizon]` is defined as `0.0` within `end_soe_tolerance` of `end_soe_target` and a large negative penalty (`-1e9`) elsewhere, so backward induction only propagates value through trajectories that can actually reach the target end SOE.

- [ ] **Step 1: Write the failing test — a small synthetic window must hit its pinned end SOE**

Add to `core/bess/tests/unit/test_pwl_window_dp.py`:

```python
from core.bess.dp_battery_algorithm import BatterySettings
from core.bess.pwl_window_dp import run_pwl_window_backward_induction, _pwl_eval_array


def _tiny_battery() -> BatterySettings:
    return BatterySettings(
        max_soe_kwh=10.0,
        min_soe_kwh=1.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        efficiency_charge=0.95,
        efficiency_discharge=0.95,
        cycle_cost_per_kwh=0.0,
    )


def test_pinned_terminal_soe_penalizes_states_far_from_target():
    battery = _tiny_battery()
    V = run_pwl_window_backward_induction(
        window_horizon=3,
        buy_price=[1.0, 1.0, 1.0],
        sell_price=[0.5, 0.5, 0.5],
        home_consumption=[0.0, 0.0, 0.0],
        solar_production=[0.0, 0.0, 0.0],
        battery_settings=battery,
        dt=0.25,
        end_soe_target=5.0,
        end_soe_tolerance=1e-3,
    )
    terminal_row = V[3]
    near_target_value = _pwl_eval_array(terminal_row, np.array([5.0]))[0]
    far_from_target_value = _pwl_eval_array(terminal_row, np.array([1.5]))[0]
    assert near_target_value > far_from_target_value + 1e6, (
        "states far from the pinned target must be penalized far below "
        "states at the target, or backward induction won't preferentially "
        "route trajectories toward it"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest core/bess/tests/unit/test_pwl_window_dp.py::test_pinned_terminal_soe_penalizes_states_far_from_target -v
```

Expected: FAIL — `ImportError: cannot import name 'run_pwl_window_backward_induction'`.

- [ ] **Step 3: Implement `run_pwl_window_backward_induction`**

Append to `core/bess/pwl_window_dp.py`:

```python
_TERMINAL_PENALTY = -1e9


def _pinned_terminal_row(
    end_soe_target: float,
    end_soe_tolerance: float,
    battery_settings: BatterySettings,
) -> tuple[np.ndarray, np.ndarray]:
    """A PWL row that is ~0 within `end_soe_tolerance` of the target and a
    steep, large-magnitude penalty immediately outside it -- so backward
    induction only assigns real value to trajectories that land on target."""
    lo = max(battery_settings.min_soe_kwh, end_soe_target - end_soe_tolerance)
    hi = min(battery_settings.max_soe_kwh, end_soe_target + end_soe_tolerance)
    xs = np.array([battery_settings.min_soe_kwh, lo, end_soe_target, hi, battery_settings.max_soe_kwh])
    vs = np.array([_TERMINAL_PENALTY, _TERMINAL_PENALTY, 0.0, _TERMINAL_PENALTY, _TERMINAL_PENALTY])
    return xs, vs


def run_pwl_window_backward_induction(
    window_horizon: int,
    buy_price: list[float],
    sell_price: list[float],
    home_consumption: list[float],
    solar_production: list[float],
    battery_settings: BatterySettings,
    dt: float,
    end_soe_target: float,
    end_soe_tolerance: float = 1e-6,
    max_charge_power_per_period: list[float] | None = None,
    self_throttle_export_threshold_kwh: float = BATTERY_EXPORT_THRESHOLD_KWH,
    discharge_resolution_kw: float | None = None,
) -> list[tuple[np.ndarray, np.ndarray]]:
    horizon_inputs = (buy_price, sell_price, home_consumption, solar_production)
    power_row = np.concatenate((
        [0.0],
        _backward_discharge_levels(battery_settings, discharge_resolution_kw) * -1,
        [battery_settings.max_charge_power_kw],  # single representative charge candidate
    ))

    V: list[tuple[np.ndarray, np.ndarray]] = [None] * (window_horizon + 1)  # type: ignore[list-item]
    V[window_horizon] = _pinned_terminal_row(end_soe_target, end_soe_tolerance, battery_settings)

    xs_seed = np.linspace(battery_settings.min_soe_kwh, battery_settings.max_soe_kwh, 21)
    for t in range(window_horizon - 1, -1, -1):
        period_max_charge = (
            max_charge_power_per_period[t] if max_charge_power_per_period is not None else None
        )
        vs_seed = _pwl_candidate_values_at(
            xs_seed, t, V[t + 1], power_row, horizon_inputs,
            battery_settings, dt, period_max_charge, self_throttle_export_threshold_kwh,
        )
        V[t] = _pwl_prune(xs_seed, vs_seed, eps=PWL_EPS_PRUNE)

    return V
```

Note: this uses a fixed 21-point seed grid rather than the #461 branch's adaptive breakpoint refinement — adequate for a short window (a handful of periods) where exactness matters most near the terminal pin, not across the whole state space. If Step 5 (accuracy test against the DP's own boundary values) shows this isn't tight enough, increase the seed density or port the #461 branch's adaptive refinement loop instead — flag this decision in the commit message either way.

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest core/bess/tests/unit/test_pwl_window_dp.py::test_pinned_terminal_soe_penalizes_states_far_from_target -v
```

Expected: PASS. If it fails because the penalty isn't propagating (e.g. `_pwl_prune` collapses the sharp penalty spike into a smoother line), reduce `PWL_EPS_PRUNE` for this call site or skip pruning on the terminal-adjacent row — adjust and re-run rather than weakening the test.

- [ ] **Step 5: Add and pass a forward-replay accuracy test**

Add:

```python
from core.bess.pwl_window_dp import _pwl_best_action_at_continuous_state  # implemented in Task 6

# (This test belongs here but depends on Task 6's forward-replay function;
# if implementing tasks strictly in order, move this test into Task 6 instead.)
```

Defer this specific test to Task 6, where the forward-replay function it needs is implemented — note this explicitly rather than leaving a dangling import.

- [ ] **Step 6: Commit**

```bash
git add core/bess/pwl_window_dp.py core/bess/tests/unit/test_pwl_window_dp.py
git commit -m "feat: windowed PWL backward induction with pinned terminal SOE (#450)"
```

---

### Task 6: PWL forward replay (window resolver's action extraction)

**Files:**
- Modify: `core/bess/pwl_window_dp.py`
- Test: `core/bess/tests/unit/test_pwl_window_dp.py`

**Interfaces:**
- Consumes: `V: list[tuple[np.ndarray, np.ndarray]]` from Task 5, a window's `start_soe: float`.
- Produces:
  ```python
  def resolve_pwl_window(
      V: list[tuple[np.ndarray, np.ndarray]],
      start_soe: float,
      window_horizon: int,
      buy_price: list[float],
      sell_price: list[float],
      home_consumption: list[float],
      solar_production: list[float],
      battery_settings: BatterySettings,
      dt: float,
      cost_basis: float,
      max_charge_power_per_period: list[float] | None = None,
      self_throttle_export_threshold_kwh: float = BATTERY_EXPORT_THRESHOLD_KWH,
      discharge_resolution_kw: float | None = None,
  ) -> list[tuple[float, float]]:
      """Returns [(power, next_soe), ...] for each of the window's periods."""
  ```
  Consumed by Task 7's splicer.

- [ ] **Step 1: Write the failing end-to-end window test**

Add to `core/bess/tests/unit/test_pwl_window_dp.py`:

```python
from core.bess.pwl_window_dp import resolve_pwl_window


def test_resolve_pwl_window_reaches_pinned_end_soe_exactly():
    battery = _tiny_battery()
    V = run_pwl_window_backward_induction(
        window_horizon=3,
        buy_price=[1.0, 1.0, 1.0],
        sell_price=[0.5, 0.5, 0.5],
        home_consumption=[0.0, 0.0, 0.0],
        solar_production=[0.0, 0.0, 0.0],
        battery_settings=battery,
        dt=0.25,
        end_soe_target=5.0,
        end_soe_tolerance=1e-3,
    )
    actions = resolve_pwl_window(
        V, start_soe=3.0, window_horizon=3,
        buy_price=[1.0, 1.0, 1.0], sell_price=[0.5, 0.5, 0.5],
        home_consumption=[0.0, 0.0, 0.0], solar_production=[0.0, 0.0, 0.0],
        battery_settings=battery, dt=0.25, cost_basis=0.0,
    )
    assert len(actions) == 3
    final_soe = actions[-1][1]
    assert final_soe == pytest.approx(5.0, abs=1e-2)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest core/bess/tests/unit/test_pwl_window_dp.py::test_resolve_pwl_window_reaches_pinned_end_soe_exactly -v
```

Expected: FAIL — `ImportError: cannot import name 'resolve_pwl_window'`.

- [ ] **Step 3: Implement `_pwl_best_action_at_continuous_state` and `resolve_pwl_window`**

Append to `core/bess/pwl_window_dp.py`. This mirrors `dp_battery_algorithm.py`'s `_best_action_at_continuous_state` (see Task 2) exactly, except it reads `V_next` as a PWL row via `_pwl_eval_array` instead of the grid-array `_interpolate_value`:

```python
from core.bess.dp_battery_algorithm import (
    _charge_candidate,
    _compute_reward,
    _discharge_candidates,
    _soe_floor,
    _state_transition,
)


def _pwl_best_action_at_continuous_state(
    soe: float,
    t: int,
    V_next: tuple[np.ndarray, np.ndarray],
    home_consumption: list[float],
    battery_settings: BatterySettings,
    dt: float,
    solar_production: list[float],
    buy_price: list[float],
    sell_price: list[float],
    cost_basis: float,
    max_charge_power_per_period: list[float] | None,
    discharge_resolution_kw: float | None = None,
    self_throttle_export_threshold_kwh: float = BATTERY_EXPORT_THRESHOLD_KWH,
) -> tuple[float, float, float, float]:
    home = home_consumption[t]
    solar = solar_production[t]
    best_value = -float("inf")
    best_action = 0.0
    best_next_soe = soe
    best_new_cost_basis = cost_basis
    best_reward = 0.0

    def consider(power: float) -> None:
        nonlocal best_value, best_action, best_next_soe, best_new_cost_basis, best_reward
        next_soe = _state_transition(
            soe, power, battery_settings, dt,
            solar_production=solar, home_consumption=home,
        )
        if next_soe < _soe_floor(soe, battery_settings) or next_soe > battery_settings.max_soe_kwh:
            return
        reward, new_cost_basis = _compute_reward(
            power=power, soe=soe, next_soe=next_soe, period=t,
            home_consumption=home, battery_settings=battery_settings, dt=dt,
            buy_price=buy_price, sell_price=sell_price, solar_production=solar,
            cost_basis=cost_basis,
            self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
        )
        value = reward + float(_pwl_eval_array(V_next, np.asarray(next_soe)))
        if value > best_value:
            best_value = value
            best_action = power
            best_next_soe = next_soe
            best_new_cost_basis = new_cost_basis
            best_reward = reward

    consider(0.0)
    period_max_charge = (
        max_charge_power_per_period[t] if max_charge_power_per_period is not None else None
    )
    for p in _discharge_candidates(
        soe, battery_settings, dt, home, solar,
        discharge_resolution_kw=discharge_resolution_kw,
        self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
    ):
        consider(-p)
    charge_candidate = _charge_candidate(soe, battery_settings, dt, period_max_charge)
    if charge_candidate is not None:
        consider(charge_candidate)

    return best_action, best_next_soe, best_new_cost_basis, best_reward


def resolve_pwl_window(
    V: list[tuple[np.ndarray, np.ndarray]],
    start_soe: float,
    window_horizon: int,
    buy_price: list[float],
    sell_price: list[float],
    home_consumption: list[float],
    solar_production: list[float],
    battery_settings: BatterySettings,
    dt: float,
    cost_basis: float,
    max_charge_power_per_period: list[float] | None = None,
    self_throttle_export_threshold_kwh: float = BATTERY_EXPORT_THRESHOLD_KWH,
    discharge_resolution_kw: float | None = None,
) -> list[tuple[float, float]]:
    soe = start_soe
    basis = cost_basis
    actions: list[tuple[float, float]] = []
    for t in range(window_horizon):
        action, next_soe, basis, _reward = _pwl_best_action_at_continuous_state(
            soe, t, V[t + 1], home_consumption, battery_settings, dt,
            solar_production, buy_price, sell_price, basis,
            max_charge_power_per_period, discharge_resolution_kw,
            self_throttle_export_threshold_kwh,
        )
        actions.append((action, next_soe))
        soe = next_soe
    return actions
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest core/bess/tests/unit/test_pwl_window_dp.py -v
```

Expected: PASS, all tests including the new one.

- [ ] **Step 5: If the final SOE misses the 1e-2 tolerance**, this is the real signal that the terminal-pin approach from Task 5 needs a tighter seed grid or the ported adaptive-refinement loop from the #461 branch (see Task 5 Step 3's note) — fix at the source (Task 5's seeding), not by loosening this test's tolerance.

- [ ] **Step 6: Commit**

```bash
git add core/bess/pwl_window_dp.py core/bess/tests/unit/test_pwl_window_dp.py
git commit -m "feat: PWL window forward replay, completing the windowed exact solver (#450)"
```

---

### Task 7: Splicer

**Files:**
- Create: `core/bess/schedule_splicer.py`
- Test: `core/bess/tests/unit/test_schedule_splicer.py`

**Interfaces:**
- Consumes: the grid DP's full `actions: list[float]` and `soe_trajectory: list[float]` (length `horizon`/`horizon+1`), a `list[Window]` from Task 3, and per-window `list[tuple[float, float]]` action/next_soe pairs from Task 6.
- Produces:
  ```python
  def splice_schedule(
      actions: list[float],
      soe_trajectory: list[float],
      windows: list[Window],
      window_resolutions: dict[int, list[tuple[float, float]]],  # keyed by Window.start
  ) -> tuple[list[float], list[float]]:
      """Returns (spliced_actions, spliced_soe_trajectory), same shapes as input."""
  ```
  Consumed by `optimize_battery_schedule` (Task 8), which then replays the spliced actions through the existing `_compute_reward`/`_build_period_data` two-pass pattern (same reuse pattern PR #461 used for MILP's chosen actions — see design spec's Component 4).

- [ ] **Step 1: Write the failing test**

Create `core/bess/tests/unit/test_schedule_splicer.py`:

```python
from core.bess.schedule_splicer import splice_schedule
from core.bess.tie_detection import Window


def test_splice_replaces_only_window_periods():
    actions = [1.0, 1.0, 1.0, 1.0, 1.0]
    soe_trajectory = [2.0, 2.5, 3.0, 3.5, 4.0, 4.5]  # length horizon+1
    windows = [Window(start=1, end=3)]
    window_resolutions = {1: [(9.0, 2.9), (9.0, 3.8)]}  # replaces periods 1,2

    spliced_actions, spliced_soe = splice_schedule(
        actions, soe_trajectory, windows, window_resolutions
    )

    assert spliced_actions == [1.0, 9.0, 9.0, 1.0, 1.0]
    assert spliced_soe == [2.0, 2.5, 2.9, 3.8, 4.0, 4.5]


def test_splice_with_no_windows_is_a_no_op():
    actions = [1.0, 2.0, 3.0]
    soe_trajectory = [0.0, 1.0, 2.0, 3.0]
    spliced_actions, spliced_soe = splice_schedule(actions, soe_trajectory, [], {})
    assert spliced_actions == actions
    assert spliced_soe == soe_trajectory
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest core/bess/tests/unit/test_schedule_splicer.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'core.bess.schedule_splicer'`.

- [ ] **Step 3: Implement**

Create `core/bess/schedule_splicer.py`:

```python
"""Splices a windowed exact solver's (#450) chosen actions back into the
grid DP's full schedule. See core.bess.tie_detection for window discovery
and core.bess.pwl_window_dp for how a window's actions are computed."""

from core.bess.tie_detection import Window


def splice_schedule(
    actions: list[float],
    soe_trajectory: list[float],
    windows: list[Window],
    window_resolutions: dict[int, list[tuple[float, float]]],
) -> tuple[list[float], list[float]]:
    spliced_actions = list(actions)
    spliced_soe = list(soe_trajectory)

    for window in windows:
        resolution = window_resolutions[window.start]
        for offset, (action, next_soe) in enumerate(resolution):
            period = window.start + offset
            spliced_actions[period] = action
            spliced_soe[period + 1] = next_soe

    return spliced_actions, spliced_soe
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest core/bess/tests/unit/test_schedule_splicer.py -v
```

Expected: PASS, both tests.

- [ ] **Step 5: Commit**

```bash
git add core/bess/schedule_splicer.py core/bess/tests/unit/test_schedule_splicer.py
git commit -m "feat: splice windowed exact-solver actions into the grid DP schedule (#450)"
```

---

### Task 8: Wire tie detection, window resolution, and splicing into `optimize_battery_schedule`

**Files:**
- Modify: `core/bess/dp_battery_algorithm.py` (`optimize_battery_schedule`, the function containing the Task 2 forward loop)
- Test: `core/bess/tests/unit/test_scenarios.py` (existing, run as regression)

**Interfaces:**
- Consumes: `tie_margins` (Task 2), `detect_tie_windows` (Task 3), `run_pwl_window_backward_induction` + `resolve_pwl_window` (Tasks 5-6), `splice_schedule` (Task 7).
- Produces: no change to `optimize_battery_schedule`'s public signature or return type — this task only changes what happens internally between "grid DP forward loop finishes" and "accounting replay begins."

- [ ] **Step 1: Write the failing test — no-tie fast path must be unchanged**

This is primarily a regression-guard test, added to `core/bess/tests/unit/test_scenarios.py` or a new small file:

```python
import pytest

from core.bess.tests.unit.test_scenarios import build_scenario_inputs
from core.bess.dp_battery_algorithm import optimize_battery_schedule


def test_hybrid_wiring_is_no_op_when_no_ties_detected():
    """A fixture with no near-tied periods must produce byte-identical
    output whether or not the hybrid tie-detect/resolve/splice path exists
    -- this is the core latency guarantee of the hybrid design."""

    scenario, battery_settings, buy_prices, sell_prices, period_duration_hours = (
        build_scenario_inputs("synthetic_consumption_efficient")  # no known #450-style tie
    )
    result = optimize_battery_schedule(
        buy_price=buy_prices,
        sell_price=sell_prices,
        home_consumption=scenario["home_consumption"],
        solar_production=scenario["solar_production"],
        initial_soe=scenario["battery"]["initial_soe"],
        battery_settings=battery_settings,
        period_duration_hours=period_duration_hours,
        terminal_value_per_kwh=scenario.get("terminal_value_per_kwh", 0.0),
    )
    # "synthetic_consumption_efficient" has no near-tied periods, so the
    # hybrid path must be a no-op: this must still match the fixture's
    # own pinned expected_results (core/bess/tests/unit/data/
    # synthetic_consumption_efficient.json), unchanged by this task's wiring.
    assert result.economic_summary.battery_solar_cost == pytest.approx(-28.28496, abs=1e-4)
    assert result.economic_summary.base_to_battery_solar_savings == pytest.approx(88.22186, abs=1e-3)
```

Note: the meaningful verification for this step is not a single assertion but a before/after diff — run `pytest core/bess/tests/unit/test_scenarios.py -v` and capture output *before* Step 2's implementation, then again *after*, and confirm zero fixtures changed cost. Do this explicitly rather than trusting a single test.

```bash
.venv/bin/pytest core/bess/tests/unit/test_scenarios.py -v > /tmp/scenarios_before.txt
```

- [ ] **Step 2: Implement the wiring**

In `core/bess/dp_battery_algorithm.py`'s `optimize_battery_schedule`, after the Task 2 forward loop produces `actions`, `soe_trajectory` (or equivalent existing variable names — use whatever the function already calls its accumulated action/SOE lists), and `tie_margins`, insert:

```python
from core.bess.tie_detection import detect_tie_windows
from core.bess.pwl_window_dp import run_pwl_window_backward_induction, resolve_pwl_window
from core.bess.schedule_splicer import splice_schedule
from core.bess.dp_constants import SOE_STEP_KWH

windows = detect_tie_windows(tie_margins, buy_price, sell_price, soe_step_kwh=SOE_STEP_KWH)

if windows:
    window_resolutions: dict[int, list[tuple[float, float]]] = {}
    for window in windows:
        window_horizon = window.end - window.start
        start_soe = soe_trajectory[window.start]
        end_soe_target = soe_trajectory[window.end]
        V = run_pwl_window_backward_induction(
            window_horizon=window_horizon,
            buy_price=buy_price[window.start:window.end],
            sell_price=sell_price[window.start:window.end],
            home_consumption=home_consumption[window.start:window.end],
            solar_production=solar_production[window.start:window.end],
            battery_settings=battery_settings,
            dt=dt,
            end_soe_target=end_soe_target,
            max_charge_power_per_period=(
                max_charge_power_per_period[window.start:window.end]
                if max_charge_power_per_period is not None else None
            ),
            self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
        )
        window_resolutions[window.start] = resolve_pwl_window(
            V, start_soe=start_soe, window_horizon=window_horizon,
            buy_price=buy_price[window.start:window.end],
            sell_price=sell_price[window.start:window.end],
            home_consumption=home_consumption[window.start:window.end],
            solar_production=solar_production[window.start:window.end],
            battery_settings=battery_settings, dt=dt, cost_basis=cost_basis_at(window.start),
            max_charge_power_per_period=(
                max_charge_power_per_period[window.start:window.end]
                if max_charge_power_per_period is not None else None
            ),
            self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
        )
    actions, soe_trajectory = splice_schedule(actions, soe_trajectory, windows, window_resolutions)
```

Note: `cost_basis_at(window.start)` is a placeholder name for whatever the existing forward loop's cost-basis-per-period tracking is actually called (confirm the exact variable/list name while implementing — Task 2's forward loop already threads `cost_basis` period-by-period, so this should be an existing value, not new state).

Leave the accounting replay (existing `_compute_reward`/`_build_period_data` pass) exactly as it is, just make sure it consumes the (possibly spliced) `actions`/`soe_trajectory` rather than the raw grid-DP output.

- [ ] **Step 3: Run test to verify the no-tie fast path is unchanged**

```bash
.venv/bin/pytest core/bess/tests/unit/test_scenarios.py -v > /tmp/scenarios_after.txt
diff /tmp/scenarios_before.txt /tmp/scenarios_after.txt
```

Expected: no differences (aside from timing/ordering noise) — same pass/fail per fixture, same costs.

- [ ] **Step 4: Run the full fast suite**

```bash
.venv/bin/pytest -m "not slow"
```

Expected: all passing, same count as before this task (no fixture in the current suite is known to trip a tie — that's exactly why #450 needed a dedicated new fixture, added next in Task 9).

- [ ] **Step 5: Commit**

```bash
git add core/bess/dp_battery_algorithm.py
git commit -m "feat: wire tie-detect/resolve/splice into optimize_battery_schedule (#450)"
```

---

### Task 9: End-to-end #450 regression test

**Files:**
- Create: `core/bess/tests/unit/test_issue_450_hybrid_resolution.py`

**Interfaces:**
- Consumes: the ported fixture from Task 1, `optimize_battery_schedule` (now hybrid-aware per Task 8).

- [ ] **Step 1: Write the test**

```python
"""End-to-end regression test for #450: the grid DP's SOE grid-snapping
must no longer be able to flip a near-tied window's choice, now that the
hybrid tie-detect/resolve/splice path (this branch) replaces PR #461's
full-MILP fix.

Expected cost matches the exact-PWL reference value established during
the #461 branch's own cross-check of its PWL prototype against a direct
joint-integer solve on this exact fixture (commit bccb1ab, "test(milp):
pin MILP core against the PWL reference's own fixture cost"):
cost == -5.998358429 (SEK), to the same tolerance that cross-check used.
"""

import pytest

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.tests.unit.test_scenarios import build_scenario_inputs


def test_450_fixture_reaches_bellman_optimal_window():
    scenario, battery_settings, buy_prices, sell_prices, period_duration_hours = (
        build_scenario_inputs("regression_2026_08_02_043728")
    )
    result = optimize_battery_schedule(
        buy_price=buy_prices,
        sell_price=sell_prices,
        home_consumption=scenario["home_consumption"],
        solar_production=scenario["solar_production"],
        initial_soe=scenario["battery"]["initial_soe"],
        battery_settings=battery_settings,
        period_duration_hours=period_duration_hours,
        terminal_value_per_kwh=scenario.get("terminal_value_per_kwh", 0.0),
    )
    assert result.economic_summary.battery_solar_cost == pytest.approx(-5.998358429, abs=1e-6)
```

- [ ] **Step 2: Run test to verify it fails first (should currently be red without the hybrid path, or if any prior task has a bug)**

```bash
.venv/bin/pytest core/bess/tests/unit/test_issue_450_hybrid_resolution.py -v
```

Expected: if Tasks 1-8 are correctly implemented, this should already PASS at this point (it's a regression/acceptance test for prior tasks' work, not new production code) — if it fails, the failure pinpoints exactly which upstream task (margin recording, tie detection, window resolution, or splicing) produced the wrong result. Debug there, not here.

- [ ] **Step 3: If passing, run the full fast + slow suites for final confirmation**

```bash
.venv/bin/pytest -m "not slow"
.venv/bin/pytest -m slow
```

Expected: all green. Compare slow-suite runtime against the pre-hybrid baseline (~12s per the design spec) — a few extra seconds for the one fixture that trips the tie detector is expected and fine; anything close to PR #461's ~113-258s would indicate the window isn't staying narrow (check `detect_tie_windows`'s padding/merge logic against this fixture's actual margins).

- [ ] **Step 4: Commit**

```bash
git add core/bess/tests/unit/test_issue_450_hybrid_resolution.py
git commit -m "test: end-to-end #450 regression via hybrid tie-resolution path"
```

---

### Task 10: Quality gate and final verification

**Files:** none new — verification only.

- [ ] **Step 1: Run the project's quality gate**

```bash
./scripts/quality-check.sh
```

Expected: clean (black, ruff, all fast tests).

- [ ] **Step 2: Run the full test suite one more time**

```bash
.venv/bin/pytest
```

Expected: all green.

- [ ] **Step 3: Confirm the no-regression invariant one final time across the whole fixture suite**

```bash
.venv/bin/pytest core/bess/tests/unit/test_scenarios.py -v
```

Expected: every fixture's `expected_results` still matches — this branch must not have re-pinned any fixture the way PR #461 needed to (no MILP-vs-DP cost differences to reconcile; the hybrid's fast path is provably identical to today's DP).

- [ ] **Step 4: Commit any final formatting fixes, if quality-check.sh made changes**

```bash
git add -A
git commit -m "chore: quality-check formatting fixes"
```

(Only if Step 1 produced changes — skip if clean.)
