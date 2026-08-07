# Risk-Aware IDLE Tie-Break Implementation Plan (#466)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When IDLE and a load-covering discharge are near-tied in DP value, choose the discharge (fail-safe) side — IDLE only ever appears when holding energy scores decisively better.

**Architecture:** A pure helper `_prefer_load_covering_discharge` in `core/bess/dp_battery_algorithm.py` re-picks the winning candidate index after the argmax in both one-step Bellman replay sites: `_best_action_at_continuous_state` (grid DP forward extraction) and `_pwl_best_action_at_continuous_state` (exact PWL window re-solve, which would otherwise undo the swap when a tied window is re-resolved). The tie band is `epsilon_for_period` from `core/bess/tie_detection.py` (#467) — no new constants. Backward-pass value tables are untouched.

**Tech Stack:** Python 3, numpy, pytest. Spec: `docs/superpowers/specs/2026-08-07-idle-tie-break-design.md`.

## Global Constraints

- Branch: `worktree-design-466-idle-tie-break` (worktree at `.claude/worktrees/design-466-idle-tie-break`); PR target `main`, opened as **draft**; no `Closes #466` footer (beta graduation rule).
- Tests: `.venv/bin/pytest -m "not slow"` must stay green after every task; run from the worktree root.
- Quality gate before every commit: `.venv/bin/black . && .venv/bin/ruff check --fix .` (full `./scripts/quality-check.sh` before the final commit).
- No config knobs, no new thresholds: the only tie band is `epsilon_for_period(value_slope, SOE_STEP_KWH)` (`TIE_NOISE_FACTOR = 0.1`, `SOE_STEP_KWH = 0.05` from `core/bess/dp_constants.py`).
- Scope: IDLE → load-covering discharge only. Never swap into export, never touch charge-side ties, never modify the backward pass.
- **Validation gate (spec §Threshold):** if Task 4's replay of the #466 bundle does not flip the reported 19:00/22:15-class periods, STOP — report measured margins vs epsilon to the user; do not widen any constant.

---

### Task 1: `_prefer_load_covering_discharge` helper

**Files:**
- Modify: `core/bess/dp_battery_algorithm.py` (add helper after `_tie_margin`, which ends near line 1370)
- Test: `core/bess/tests/unit/test_idle_tie_break.py` (new)

**Interfaces:**
- Consumes: candidate tuples `(value, power, next_soe, new_cost_basis, reward, grid_imported)` exactly as built by both `consider()` closures; `POWER_TOLERANCE_KW` (module constant, 0.001).
- Produces: `_prefer_load_covering_discharge(candidates, best_index, epsilon, home_consumption, solar_production, dt, rate_step) -> int` — returns the (possibly swapped) index. Tasks 2 and 3 call it with this exact signature.

- [ ] **Step 1: Write the failing tests**

```python
"""Risk-aware IDLE tie-break (#466): when IDLE and a load-covering discharge
are within the DP's own value noise, prefer the discharge -- it fails safe
(tracks actual load) where IDLE fails unsafe (discharge hard-disabled)."""

from core.bess.dp_battery_algorithm import _prefer_load_covering_discharge

# Candidate tuple: (value, power, next_soe, new_cost_basis, reward, grid_imported)
IDLE = (10.00, 0.0, 6.0, 0.0, 0.0, 0.25)
COVER = (9.995, -1.0, 5.74, 0.0, 0.25, 0.0)  # discharges 1 kW, covers 1 kW net load
OVER = (9.999, -3.0, 5.21, 0.0, 0.30, 0.0)  # discharges past load -> would export
CHARGE = (9.99, 2.0, 6.5, 0.0, -0.5, 0.75)


def _pick(candidates, best_index, epsilon=0.01, home=0.25, solar=0.0):
    return _prefer_load_covering_discharge(
        candidates,
        best_index,
        epsilon=epsilon,
        home_consumption=home,
        solar_production=solar,
        dt=0.25,
        rate_step=0.05,  # 5 kW battery / 100
    )


def test_near_tied_idle_swaps_to_load_covering_discharge():
    candidates = [IDLE, COVER, OVER, CHARGE]
    # IDLE wins argmax; COVER is 0.005 behind, inside epsilon=0.01 -> swap.
    assert _pick(candidates, best_index=0) == 1


def test_decisive_idle_margin_is_never_swapped():
    candidates = [IDLE, COVER, OVER, CHARGE]
    # COVER is 0.005 behind; with epsilon below that the hold is deliberate.
    assert _pick(candidates, best_index=0, epsilon=0.004) == 0


def test_never_swaps_into_exporting_discharge():
    # Only the over-load discharge is within epsilon -> no eligible swap.
    candidates = [IDLE, (9.90, -1.0, 5.74, 0.0, 0.25, 0.0), OVER, CHARGE]
    assert _pick(candidates, best_index=0) == 0


def test_non_idle_winner_is_untouched():
    candidates = [IDLE, COVER, OVER, CHARGE]
    assert _pick(candidates, best_index=3) == 3


def test_no_net_load_means_no_swap():
    # Solar covers the house: balance_zero_p <= 0, nothing to fail-safe.
    candidates = [IDLE, COVER, OVER, CHARGE]
    assert _pick(candidates, best_index=0, home=0.10, solar=0.50) == 0


def test_zero_epsilon_is_a_no_op():
    # Flat value function (dV/dSoE == 0) -> epsilon 0 -> tie-break disabled,
    # mirroring tie_detection's documented blind spot.
    candidates = [IDLE, COVER, OVER, CHARGE]
    assert _pick(candidates, best_index=0, epsilon=0.0) == 0


def test_picks_largest_eligible_coverage_among_ties():
    partial = (9.997, -0.5, 5.87, 0.0, 0.12, 0.12)  # covers half the load
    candidates = [IDLE, partial, COVER]
    # Both discharges are inside epsilon; the fuller cover (1.0 kW) wins.
    assert _pick(candidates, best_index=0) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest core/bess/tests/unit/test_idle_tie_break.py -v`
Expected: FAIL — `ImportError: cannot import name '_prefer_load_covering_discharge'`

- [ ] **Step 3: Implement the helper**

Add to `core/bess/dp_battery_algorithm.py`, directly after `_tie_margin`:

```python
def _prefer_load_covering_discharge(
    candidates: list[tuple[float, float, float, float, float, float]],
    best_index: int,
    epsilon: float,
    home_consumption: float,
    solar_production: float,
    dt: float,
    rate_step: float,
) -> int:
    """Risk-aware tie-break (#466): if the argmax landed on an idle-like
    action (|power| <= POWER_TOLERANCE_KW) while the house has forecast net
    grid import this period, and a discharge candidate that covers no more
    than that net load sits within `epsilon` of the best value, return that
    candidate's index instead.

    Rationale (spec 2026-08-07-idle-tie-break-design.md): within `epsilon`
    -- the value noise the DP's own SOE grid-snapping injects
    (tie_detection.epsilon_for_period) -- the DP cannot rank the two
    options, but they are not symmetric in risk. Load-covering discharge
    fails safe: the inverter tracks *actual* load, absorbing a consumption
    forecast miss for free. IDLE fails unsafe: discharge is hard-disabled,
    so the entire miss is imported at the buy price. Deliberate arbitrage
    holds are untouched by construction -- their margin over discharging
    exceeds `epsilon`.

    `rate_step` is the discharge percent-grid step (see
    _discharge_candidates); the load-cover breakpoint snaps to it, so the
    eligibility cap allows half a step of round-up before a candidate
    counts as exporting. Among eligible candidates the largest coverage
    wins -- fuller coverage means less residual import exposed to a miss.
    """
    if epsilon <= 0.0:
        return best_index
    best_value, best_power = candidates[best_index][0], candidates[best_index][1]
    if abs(best_power) > POWER_TOLERANCE_KW:
        return best_index
    balance_zero_p = (home_consumption - solar_production) / dt
    if balance_zero_p <= POWER_TOLERANCE_KW:
        return best_index
    max_cover_p = balance_zero_p + 0.5 * rate_step + 1e-9
    swap_index = best_index
    swap_power = 0.0
    for index, candidate in enumerate(candidates):
        discharge_p = -candidate[1]
        if discharge_p <= POWER_TOLERANCE_KW or discharge_p > max_cover_p:
            continue
        if best_value - candidate[0] >= epsilon:
            continue
        if discharge_p > swap_power:
            swap_index = index
            swap_power = discharge_p
    return swap_index
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest core/bess/tests/unit/test_idle_tie_break.py -v`
Expected: all 7 PASS

- [ ] **Step 5: Quality gate and commit**

```bash
.venv/bin/black . && .venv/bin/ruff check --fix .
git add core/bess/dp_battery_algorithm.py core/bess/tests/unit/test_idle_tie_break.py
git commit -m "feat: add risk-aware load-covering tie-break helper (#466)"
```

---

### Task 2: Wire into the grid-DP forward extraction

**Files:**
- Modify: `core/bess/dp_battery_algorithm.py:1530-1546` (`_best_action_at_continuous_state`, argmax → return block)
- Test: `core/bess/tests/unit/test_idle_tie_break.py` (extend)

**Interfaces:**
- Consumes: `_prefer_load_covering_discharge` (Task 1 signature); `epsilon_for_period` from `core/bess/tie_detection.py`; `_local_value_slope(V_row, soe, battery_settings)`; `SOE_STEP_KWH` from `core/bess/dp_constants.py`.
- Produces: `_best_action_at_continuous_state` unchanged signature; its returned action now reflects the tie-break. `_tie_margin` is computed on the **final** (possibly swapped) index — a swapped period reports a margin ≤ 0, which still flags for #450's window detection.

- [ ] **Step 1: Write the failing test**

Append to `core/bess/tests/unit/test_idle_tie_break.py`. The test drives the real replay function with a hand-built linear continuation row whose slope makes IDLE and load-covering discharge tie almost exactly; a second case steepens the slope so holding wins decisively. Battery: `_tiny_battery` pattern from `core/bess/tests/unit/test_pwl_window_dp.py:33` but with `efficiency_charge=1.0, efficiency_discharge=1.0` so the tie point is exact-arithmetic.

```python
import numpy as np

from core.bess.dp_battery_algorithm import (
    SOE_STEP_KWH,
    _best_action_at_continuous_state,
    _discretize_state_action_space,
)
from core.bess.settings import BatterySettings


def _lossless_battery() -> BatterySettings:
    return BatterySettings(
        total_capacity=10.0,
        min_soc=10.0,
        max_soc=100.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        efficiency_charge=1.0,
        efficiency_discharge=1.0,
        cycle_cost_per_kwh=0.0,
        inverter_max_ac_power_kw=0.0,
    )


def _replay_choice(value_slope: float) -> float:
    """Run the one-step replay at soe=6.0 with 1 kW net load, no solar,
    buy=1.0, and a linear V[t+1] of the given slope; return chosen power.

    Discharging d kWh saves d*buy now but forfeits d*slope of continuation
    value (lossless battery), so idle-vs-cover margin = d*(slope - buy):
    slope == buy -> exact tie; slope >> buy -> decisive hold.
    """
    settings = _lossless_battery()
    soe_levels = np.arange(
        settings.min_soe_kwh, settings.max_soe_kwh + SOE_STEP_KWH, SOE_STEP_KWH
    )
    V_next = value_slope * (soe_levels - settings.min_soe_kwh)
    _, power_levels = _discretize_state_action_space(settings)
    action, *_rest = _best_action_at_continuous_state(
        soe=6.0,
        t=0,
        V_next=V_next,
        power_levels=power_levels,
        home_consumption=[0.25],
        battery_settings=settings,
        dt=0.25,
        solar_production=[0.0],
        buy_price=[1.0],
        sell_price=[0.4],
        cost_basis=0.0,
        max_charge_power_per_period=None,
    )
    return action


def test_replay_swaps_exact_tie_to_load_cover():
    # slope == buy: idle and cover are exactly tied -> fail-safe side wins.
    action = _replay_choice(value_slope=1.0)
    assert action < 0, f"expected load-covering discharge, got {action}"
    # Covers the 1 kW net load (within one percent-step of 5 kW / 100).
    assert -action == pytest.approx(1.0, abs=0.05)


def test_replay_keeps_decisive_arbitrage_hold():
    # Stored energy worth far more later than covering load now.
    action = _replay_choice(value_slope=2.0)
    assert action == 0.0
```

- [ ] **Step 2: Run tests to verify the tie case fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_idle_tie_break.py -v -k replay`
Expected: `test_replay_swaps_exact_tie_to_load_cover` FAILS (action == 0.0 today — exact ties resolve to first-considered IDLE); `test_replay_keeps_decisive_arbitrage_hold` PASSES (it pins existing behavior).

- [ ] **Step 3: Apply the tie-break in `_best_action_at_continuous_state`**

In `core/bess/dp_battery_algorithm.py`, add the import at the top of the file (`tie_detection` imports nothing back — no cycle):

```python
from core.bess.tie_detection import epsilon_for_period
```

Then replace the block at lines 1530–1546 (argmax through return):

```python
    best_index = 0
    best_value = float("-inf")
    for index, candidate in enumerate(candidates):
        if candidate[0] > best_value:
            best_value = candidate[0]
            best_index = index

    # Risk-aware tie-break (#466): within the value noise grid-snapping
    # injects at this state, prefer the load-covering discharge over an
    # idle-like winner. Epsilon uses the slope at the argmax winner's
    # next_soe -- the same state the margin itself is measured at.
    best_index = _prefer_load_covering_discharge(
        candidates,
        best_index,
        epsilon=epsilon_for_period(
            _local_value_slope(V_next, candidates[best_index][2], battery_settings),
            SOE_STEP_KWH,
        ),
        home_consumption=home,
        solar_production=solar,
        dt=dt,
        rate_step=(
            discharge_resolution_kw
            if discharge_resolution_kw is not None
            else battery_settings.max_discharge_power_kw / 100
        ),
    )

    _, best_action, best_next_soe, best_new_cost_basis, best_reward, _ = candidates[
        best_index
    ]
    return (
        best_action,
        best_next_soe,
        best_new_cost_basis,
        best_reward,
        _tie_margin(candidates, best_index),
    )
```

- [ ] **Step 4: Run the new tests, then the fast suite**

Run: `.venv/bin/pytest core/bess/tests/unit/test_idle_tie_break.py -v`
Expected: all PASS
Run: `.venv/bin/pytest -m "not slow"`
Expected: green. **If any scenario/regression fixture fails:** inspect whether the diff is exactly an IDLE→LOAD_SUPPORT swap inside a near-tie (total cost delta within the fixture's tolerance). If so, update the fixture's expected intents with a comment citing #466. If total cost regresses beyond tolerance, the guard is wrong — stop and re-examine (the swap must be value-free by construction).

- [ ] **Step 5: Quality gate and commit**

```bash
.venv/bin/black . && .venv/bin/ruff check --fix .
git add -A core
git commit -m "feat: break near-tied IDLE toward load-covering discharge in grid replay (#466)"
```

---

### Task 3: Wire into the PWL window re-solve

Without this, any near-tied period that #450's detector flags gets re-solved by the exact PWL DP, whose own argmax would reinstate IDLE — undoing Task 2 exactly where it matters most.

**Files:**
- Modify: `core/bess/pwl_window_dp.py:16-29` (import list), `core/bess/pwl_window_dp.py:411-421` (`_pwl_best_action_at_continuous_state`, argmax → return block)
- Test: `core/bess/tests/unit/test_idle_tie_break.py` (extend)

**Interfaces:**
- Consumes: `_prefer_load_covering_discharge` and `epsilon_for_period` (same signatures as Task 2); `_pwl_eval_array` (already local); `SOE_STEP_KWH` from `core/bess/dp_constants.py` (add to that import line, which today imports only `POWER_STEP_KW`).
- Produces: `_pwl_best_action_at_continuous_state` unchanged signature, tie-break applied. The PWL row has no grid to snap, so the local slope for epsilon comes from a central finite difference of `_pwl_eval_array` one `SOE_STEP_KWH` either side of the winner's `next_soe` — same band definition as the grid site.

- [ ] **Step 1: Write the failing test**

```python
from core.bess.pwl_window_dp import _pwl_best_action_at_continuous_state


def _pwl_replay_choice(value_slope: float) -> float:
    """Same construction as _replay_choice, against the PWL replay: linear
    continuation row as a two-breakpoint PWL, slope == buy -> exact tie."""
    settings = _lossless_battery()
    xs = np.array([settings.min_soe_kwh, settings.max_soe_kwh])
    vs = value_slope * (xs - settings.min_soe_kwh)
    _, power_levels = _discretize_state_action_space(settings)
    action, *_rest = _pwl_best_action_at_continuous_state(
        soe=6.0,
        t=0,
        V_next=(xs, vs),
        power_levels=power_levels,
        home_consumption=[0.25],
        battery_settings=settings,
        dt=0.25,
        solar_production=[0.0],
        buy_price=[1.0],
        sell_price=[0.4],
        cost_basis=0.0,
        max_charge_power_per_period=None,
    )
    return action


def test_pwl_replay_swaps_exact_tie_to_load_cover():
    action = _pwl_replay_choice(value_slope=1.0)
    assert action < 0, f"expected load-covering discharge, got {action}"
    assert -action == pytest.approx(1.0, abs=0.05)


def test_pwl_replay_keeps_decisive_arbitrage_hold():
    assert _pwl_replay_choice(value_slope=2.0) == 0.0
```

- [ ] **Step 2: Run tests to verify the tie case fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_idle_tie_break.py -v -k pwl_replay`
Expected: swap test FAILS (returns 0.0), hold test PASSES.

- [ ] **Step 3: Apply the tie-break in `_pwl_best_action_at_continuous_state`**

In `core/bess/pwl_window_dp.py`: extend the `dp_battery_algorithm` import block (lines 16–29) with `_prefer_load_covering_discharge`, change line 30 to `from core.bess.dp_constants import POWER_STEP_KW, SOE_STEP_KWH`, and add `from core.bess.tie_detection import epsilon_for_period`. Then replace the block at lines 411–421:

```python
    best_index = 0
    best_value = float("-inf")
    for index, candidate in enumerate(candidates):
        if candidate[0] > best_value:
            best_value = candidate[0]
            best_index = index

    # Risk-aware tie-break (#466), mirroring the grid replay so a re-solved
    # tie window cannot silently reinstate the fail-unsafe IDLE pick. The
    # PWL row has no grid snap; the slope for the shared epsilon definition
    # is a central finite difference across the winner's next_soe.
    best_next_soe_candidate = candidates[best_index][2]
    slope = float(
        _pwl_eval_array(V_next, np.asarray(best_next_soe_candidate + SOE_STEP_KWH))
        - _pwl_eval_array(V_next, np.asarray(best_next_soe_candidate - SOE_STEP_KWH))
    ) / (2 * SOE_STEP_KWH)
    best_index = _prefer_load_covering_discharge(
        candidates,
        best_index,
        epsilon=epsilon_for_period(slope, SOE_STEP_KWH),
        home_consumption=home,
        solar_production=solar,
        dt=dt,
        rate_step=(
            discharge_resolution_kw
            if discharge_resolution_kw is not None
            else battery_settings.max_discharge_power_kw / 100
        ),
    )

    _, best_action, best_next_soe, best_new_cost_basis, best_reward, _ = candidates[
        best_index
    ]
    return best_action, best_next_soe, best_new_cost_basis, best_reward
```

- [ ] **Step 4: Run the new tests, then the fast suite**

Run: `.venv/bin/pytest core/bess/tests/unit/test_idle_tie_break.py -v`
Expected: all PASS
Run: `.venv/bin/pytest -m "not slow"`
Expected: green, same fixture-diff policy as Task 2 Step 4. Pay particular attention to `test_pwl_window_dp.py` and `test_issue_450_hybrid_resolution.py` — the 0.05 SEK regression budget there must hold.

- [ ] **Step 5: Quality gate and commit**

```bash
.venv/bin/black . && .venv/bin/ruff check --fix .
git add -A core
git commit -m "feat: apply IDLE tie-break in PWL window re-solve too (#466)"
```

---

### Task 4: Validation gate — replay ridax's #466 bundle

**Files:**
- Create: `core/bess/tests/unit/data/regression_2026_08_06_466.json` (inputs extracted from the bundle)
- Test: extend `core/bess/tests/unit/test_scenarios.py` (or its data-driven fixture list — follow the harness's existing registration mechanism, mirroring how `regression_2026_08_02_043728.json` is wired in)

**Interfaces:**
- Consumes: the debug bundle attached to #466: `https://github.com/user-attachments/files/30781147/bess-debug-2026-08-06-110152.md` (download with `curl -L`). It contains the run's prices, solar/consumption forecasts, SOC, and battery settings.
- Produces: a pinned scenario fixture asserting LOAD_SUPPORT at the previously-IDLE near-tied evening periods.

- [ ] **Step 1: Extract the optimization inputs from the bundle**

Download to the scratchpad, then read the existing `regression_2026_08_02_043728.json` and copy its exact schema. Populate a new `regression_2026_08_06_466.json` from the bundle's data for the run covering 19:00 (buy 0.7235/sell 0.2419) and 22:15 (buy 0.6683/sell 0.1977). Use the bundle's own recorded battery settings and starting SOC — no invented values. Per the reproduce-from-raw-inputs rule: if the bundle lacks a decision-time field, reconstruct it from the raw sensor/price series in the bundle rather than declaring it unreproducible.

- [ ] **Step 2: Register the fixture and write the pin**

Follow `test_scenarios.py`'s existing pattern for regression fixtures (expected-results structure alongside inputs). Pin: the periods corresponding to 19:00 and 22:15 have a discharging intent (LOAD_SUPPORT), not IDLE; total schedule cost within the harness's standard tolerance of the pre-fix cost.

- [ ] **Step 3: Verify the pin discriminates**

```bash
git stash push -u -m "466-tiebreak-wip"
STASH_SHA=$(git stash list --format='%H %gs' | grep 466-tiebreak-wip | head -1 | cut -d' ' -f1)
git stash apply "$STASH_SHA"  # confirm re-apply works before testing pre-fix
```

Actually simpler and safe in the worktree: check out only the two source files at their pre-fix commit, run the new test, then restore:

```bash
git checkout HEAD~3 -- core/bess/dp_battery_algorithm.py core/bess/pwl_window_dp.py
.venv/bin/pytest core/bess/tests/unit/test_scenarios.py -v -k 466
# Expected: FAIL (periods come out IDLE pre-fix). If it PASSES here, the pin
# does not discriminate -- fix the pin before proceeding.
git checkout HEAD -- core/bess/dp_battery_algorithm.py core/bess/pwl_window_dp.py
```

(`HEAD~3` = the commit before Task 1; adjust if the commit count differs. This restores committed files only — safe because Tasks 1–3 are already committed.)

- [ ] **Step 4: Run against the fix — THE GATE**

Run: `.venv/bin/pytest core/bess/tests/unit/test_scenarios.py -v -k 466`

**If it passes:** gate cleared, continue.
**If the periods stay IDLE:** STOP the plan here. Extract the measured `tie_margins` and `value_slopes` for those periods (pass a `tie_diagnostics` dict to `optimize_battery_schedule` — see `dp_battery_algorithm.py:2033`), and report margin vs `epsilon_for_period` to the user. Widening `TIE_NOISE_FACTOR` or adding a risk premium is a design decision the user makes with those numbers — not an implementation fix.

- [ ] **Step 5: Quality gate and commit**

```bash
.venv/bin/black . && .venv/bin/ruff check --fix .
git add core/bess/tests
git commit -m "test: pin #466 bundle replay — near-tied evening IDLE now LOAD_SUPPORT"
```

---

### Task 5: Full verification and draft PR

**Files:**
- Modify: `CHANGELOG.md` (`## [Unreleased]` → `### Fixed`)

- [ ] **Step 1: Full test suite**

```bash
.venv/bin/pytest
```
Expected: green (slow suite ~1–2 min).

- [ ] **Step 2: Quality gate**

```bash
./scripts/quality-check.sh
```
Expected: clean.

- [ ] **Step 3: Changelog entry**

Under `## [Unreleased]` / `### Fixed`:

```markdown
- Near-tied IDLE vs battery-powering decisions now resolve to powering the
  house (fail-safe when consumption exceeds forecast) instead of IDLE, which
  hard-disables discharge at the inverter. Deliberate energy-holding periods
  (genuine arbitrage) are unaffected. (#466)
```

- [ ] **Step 4: Commit, push, open draft PR**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog for #466 IDLE tie-break"
git push origin HEAD:design/466-idle-tie-break
gh pr create --repo johanzander/bess-manager --draft --base main \
  --head design/466-idle-tie-break \
  --title "fix: break near-tied IDLE decisions toward load-covering discharge (#466)" \
  --body "$(cat <<'EOF'
## Summary
- IDLE now only wins when holding energy scores decisively better than powering the house; inside the DP's own value-noise band (#467's `epsilon_for_period`) the tie breaks toward the fail-safe load-covering discharge.
- Applied in both replay sites (grid forward extraction and #450's PWL window re-solve) so a re-solved tie window cannot reinstate the fail-unsafe pick.
- Pinned against the real #466 bundle: the reported 19:00/22:15 near-tied IDLE periods now extract as LOAD_SUPPORT.

Design: docs/superpowers/specs/2026-08-07-idle-tie-break-design.md
Refs #466 (no auto-close — beta graduation rule)

## Test plan
- [x] New unit tests: helper, grid replay tie/hold, PWL replay tie/hold
- [x] #466 bundle regression fixture (verified discriminating pre-fix)
- [x] Full suite + quality gate green

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 5: Run /code-review** (per project convention) — CONFIRMED findings are blockers; the rest go to TODO.md.

---

## Self-Review Notes

- **Spec coverage:** Mechanism (Tasks 1–2), PWL interaction (Task 3 — the spec's "trajectory continues from the swapped SOE" is inherent: both replay loops already thread `next_soe` forward), threshold + validation gate (Task 4), testing incl. discriminating pin (Tasks 2–4), sequencing on merged #467 (branch already contains it).
- **Deviation from spec, deliberate:** the spec placed the swap "in the forward extraction pass"; the plan puts it inside the two replay functions' selection step, which *is* where the extraction pass chooses actions — and is the only placement that also covers the PWL re-solve path the spec didn't anticipate. Spec's intent (backward pass untouched, trajectory consistent) is preserved.
- **Type consistency:** helper signature identical at both call sites; candidate tuple layout `(value, power, next_soe, new_cost_basis, reward, grid_imported)` verified against both `consider()` closures.
