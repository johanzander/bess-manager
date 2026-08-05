# Synthetic Tie-Detection Coverage Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a permanent, CI-enforced synthetic scenario suite that measures the real financial impact of the #450 tie-detector's known coverage blind spot, using perturbed variants of the existing 34 fixtures, and use that measured evidence to set a real regression budget instead of guessing at one.

**Architecture:** A pure perturbation generator creates seeded scenario variants from existing fixtures (price level, volatility, solar, battery size). A diagnostics hook on `optimize_battery_schedule` exposes the per-period tie margins/value-slopes/flagged-windows it already computes internally. A measurement harness runs both the hybrid path and a full-horizon exact-PWL reference (only for scenarios with zero flagged windows) and computes the financial gap. A slow-suite pytest test runs this across a fixed seeded matrix; the pass/fail budget is calibrated from real measured data in the final task, not guessed upfront.

**Tech Stack:** Python, pytest, NumPy (all already in use — no new dependencies).

## Global Constraints

- No new third-party dependencies.
- Follow `docs/agents/testing.md` conventions: TDD, `pytest -m slow` for this suite (it runs full-horizon exact solves, too expensive for the fast suite).
- No silent fallbacks: an invalid perturbation raises at scenario-list-construction time; any raise from the hybrid path during measurement (e.g. `PWLWindowUnderRefinedError`) is NOT caught — it's a real finding and must fail the test.
- Perturbation seeding must be fully deterministic — `random.Random(seed)`, never an unseeded global RNG or wall-clock time.
- Run `black`/`ruff` before each commit.
- The financial-impact measurement uses the DP's real `reward_objective_cost`, never `battery_solar_cost` (documented reporting-drift bug, see `TODO.md`'s #450 entry).

---

## File Structure

| File | Responsibility |
|---|---|
| `core/bess/tests/synthetic/__init__.py` | New package marker (empty). |
| `core/bess/tests/synthetic/perturb_scenario.py` | New. Pure function: base fixture + seed + params → perturbed scenario dict. |
| `core/bess/dp_battery_algorithm.py` | Modified: `optimize_battery_schedule` gains an optional `tie_diagnostics: dict \| None` parameter. |
| `core/bess/tests/synthetic/measure_tie_coverage.py` | New. Margin-ratio classification + the full-horizon "true optimal" reference + `measure_scenario`. |
| `core/bess/tests/unit/test_perturb_scenario.py` | New. Unit tests for the perturbation generator. |
| `core/bess/tests/synthetic/test_measure_tie_coverage.py` | New. Unit tests for classification + the measurement harness's pure logic. |
| `core/bess/tests/unit/test_tie_detection_synthetic_coverage.py` | New. The slow-suite integration test — the actual regression gate. |

---

### Task 1: Perturbation generator

**Files:**
- Create: `core/bess/tests/synthetic/__init__.py` (empty)
- Create: `core/bess/tests/synthetic/perturb_scenario.py`
- Test: `core/bess/tests/unit/test_perturb_scenario.py`

**Interfaces:**
- Consumes: a scenario dict in the shape `load_test_scenario()`/`core.bess.tests.helpers._scenario_inputs()` already expect — top-level keys `buy_price`, `sell_price` (or `base_prices` + `price_data`), `home_consumption`, `solar_production`, `battery` (a dict with `max_soe_kwh`, `min_soe_kwh`, `max_charge_power_kw`, `max_discharge_power_kw`, `efficiency_charge`, `efficiency_discharge`, `cycle_cost_per_kwh`, `initial_soe`, optionally `inverter_max_ac_power_kw`/`inverter_ac_power_margin`).
- Produces:
  ```python
  @dataclass(frozen=True)
  class PerturbationParams:
      price_level_multiplier: float = 1.0
      volatility_jitter: float = 0.0  # fraction of price magnitude, e.g. 0.1 = ±10%
      solar_scale: float = 1.0
      battery_capacity_override_kwh: float | None = None

  def perturb_scenario(base_fixture: dict, seed: int, params: PerturbationParams) -> dict:
      ...  # returns a new scenario dict, same shape as base_fixture
  ```
  Consumed by Task 5's measurement harness and Task 6's test, which pass the result straight into `core.bess.tests.helpers._scenario_inputs()`.

- [ ] **Step 1: Write the failing tests**

Create `core/bess/tests/unit/test_perturb_scenario.py`:

```python
import copy

import pytest

from core.bess.tests.synthetic.perturb_scenario import (
    PerturbationParams,
    perturb_scenario,
)
from core.bess.tests.unit.test_scenarios import load_test_scenario


def _base():
    return load_test_scenario("synthetic_consumption_efficient")


def test_same_seed_produces_identical_output():
    base = _base()
    params = PerturbationParams(
        price_level_multiplier=1.5, volatility_jitter=0.1, solar_scale=0.5
    )
    a = perturb_scenario(base, seed=42, params=params)
    b = perturb_scenario(base, seed=42, params=params)
    assert a == b


def test_different_seed_produces_different_jitter():
    base = _base()
    params = PerturbationParams(volatility_jitter=0.2)
    a = perturb_scenario(base, seed=1, params=params)
    b = perturb_scenario(base, seed=2, params=params)
    assert a["buy_price"] != b["buy_price"]


def test_price_level_multiplier_scales_only_prices():
    base = _base()
    params = PerturbationParams(price_level_multiplier=2.0)
    result = perturb_scenario(base, seed=0, params=params)
    for orig, scaled in zip(base["buy_price"], result["buy_price"]):
        assert scaled == pytest.approx(orig * 2.0)
    for orig, scaled in zip(base["sell_price"], result["sell_price"]):
        assert scaled == pytest.approx(orig * 2.0)
    assert result["home_consumption"] == base["home_consumption"]
    assert result["solar_production"] == base["solar_production"]


def test_solar_scale_scales_only_solar():
    base = _base()
    params = PerturbationParams(solar_scale=0.0)
    result = perturb_scenario(base, seed=0, params=params)
    assert all(v == 0.0 for v in result["solar_production"])
    assert result["buy_price"] == base["buy_price"]
    assert result["home_consumption"] == base["home_consumption"]


def test_battery_override_replaces_capacity_and_clamps_initial_soe():
    base = _base()
    # base fixture's initial_soe is within its own capacity; overriding to a
    # much smaller battery must not leave initial_soe above the new max.
    params = PerturbationParams(battery_capacity_override_kwh=1.0)
    result = perturb_scenario(base, seed=0, params=params)
    assert result["battery"]["max_soe_kwh"] == pytest.approx(1.0)
    assert result["battery"]["initial_soe"] <= result["battery"]["max_soe_kwh"]


def test_invalid_battery_override_raises():
    base = _base()
    params = PerturbationParams(battery_capacity_override_kwh=-1.0)
    with pytest.raises(ValueError, match="battery_capacity_override_kwh"):
        perturb_scenario(base, seed=0, params=params)


def test_does_not_mutate_input():
    base = _base()
    original = copy.deepcopy(base)
    perturb_scenario(base, seed=0, params=PerturbationParams(price_level_multiplier=3.0))
    assert base == original
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest core/bess/tests/unit/test_perturb_scenario.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'core.bess.tests.synthetic'`.

- [ ] **Step 3: Implement**

Create `core/bess/tests/synthetic/__init__.py` (empty file).

Create `core/bess/tests/synthetic/perturb_scenario.py`:

```python
"""Deterministic scenario perturbation for the #450 tie-detection coverage
validation suite (see docs/superpowers/specs/2026-08-05-tie-detection-
synthetic-validation-design.md). Generates realistic-shaped variants of the
existing fixtures rather than a from-scratch synthetic price model -- every
perturbed scenario keeps a real diurnal price shape and consumption profile;
only the parameters relevant to this investigation move.
"""

import copy
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class PerturbationParams:
    price_level_multiplier: float = 1.0
    volatility_jitter: float = 0.0
    solar_scale: float = 1.0
    battery_capacity_override_kwh: float | None = None


def perturb_scenario(base_fixture: dict, seed: int, params: PerturbationParams) -> dict:
    scenario = copy.deepcopy(base_fixture)
    rng = random.Random(seed)

    for key in ("buy_price", "sell_price"):
        if key in scenario:
            scaled = [v * params.price_level_multiplier for v in scenario[key]]
            if params.volatility_jitter:
                scaled = [
                    v * (1.0 + rng.uniform(-params.volatility_jitter, params.volatility_jitter))
                    for v in scaled
                ]
            scenario[key] = scaled

    if params.solar_scale != 1.0:
        scenario["solar_production"] = [
            v * params.solar_scale for v in scenario["solar_production"]
        ]

    if params.battery_capacity_override_kwh is not None:
        if params.battery_capacity_override_kwh <= 0:
            raise ValueError(
                "battery_capacity_override_kwh must be positive, got "
                f"{params.battery_capacity_override_kwh}"
            )
        battery = scenario["battery"]
        old_max = battery["max_soe_kwh"]
        new_max = params.battery_capacity_override_kwh
        # Keep min/initial SOE proportional to the old capacity, then clamp
        # into the new range so a large capacity reduction can't leave
        # initial_soe or min_soe_kwh above the new max.
        battery["min_soe_kwh"] = min(
            battery["min_soe_kwh"] * (new_max / old_max), new_max
        )
        battery["initial_soe"] = min(
            battery["initial_soe"] * (new_max / old_max), new_max
        )
        battery["max_soe_kwh"] = new_max

    return scenario
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest core/bess/tests/unit/test_perturb_scenario.py -v
```

Expected: PASS, all 7 tests.

- [ ] **Step 5: Commit**

```bash
git add core/bess/tests/synthetic/__init__.py core/bess/tests/synthetic/perturb_scenario.py core/bess/tests/unit/test_perturb_scenario.py
git commit -m "feat: add deterministic scenario perturbation generator for #450 coverage validation"
```

---

### Task 2: Diagnostics hook on `optimize_battery_schedule`

**Files:**
- Modify: `core/bess/dp_battery_algorithm.py:1784` (`optimize_battery_schedule` signature) and its Step 2b block (currently around line 2036, where `windows = detect_tie_windows(...)` is computed)
- Test: `core/bess/tests/unit/test_dp_breakpoint_search.py` (or a new small test file — see Step 1)

**Interfaces:**
- Consumes: nothing new from other tasks.
- Produces: `optimize_battery_schedule(..., tie_diagnostics: dict | None = None)`. When a caller passes a mutable dict, after the function computes `tie_margins`, `value_slopes`, `windows`, and `soe_trajectory` (all already local variables in the existing code, per Task 8 of the original hybrid plan), it populates:
  ```python
  tie_diagnostics["tie_margins"] = list(tie_margins)
  tie_diagnostics["value_slopes"] = list(value_slopes)
  tie_diagnostics["windows"] = list(windows)
  tie_diagnostics["soe_trajectory"] = list(soe_trajectory)
  tie_diagnostics["resolved_initial_cost_basis"] = initial_cost_basis
  ```
  Consumed by Task 5's measurement harness.

- [ ] **Step 1: Write the failing test**

Create `core/bess/tests/unit/test_tie_diagnostics_hook.py`:

```python
"""Tests for optimize_battery_schedule's optional tie_diagnostics hook
(#450 synthetic coverage validation suite)."""

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.tests.helpers import _scenario_inputs
from core.bess.tests.unit.test_scenarios import load_test_scenario


def test_tie_diagnostics_populated_when_dict_passed():
    scenario = load_test_scenario("regression_2026_08_02_043728")
    inputs = _scenario_inputs(scenario)
    diagnostics: dict = {}

    result = optimize_battery_schedule(
        buy_price=inputs["buy_price"],
        sell_price=inputs["sell_price"],
        home_consumption=scenario["home_consumption"],
        solar_production=scenario["solar_production"],
        initial_soe=scenario["battery"]["initial_soe"],
        battery_settings=inputs["battery_settings"],
        period_duration_hours=inputs["period_duration_hours"],
        terminal_value_per_kwh=scenario.get("terminal_value_per_kwh", 0.0),
        tie_diagnostics=diagnostics,
    )

    horizon = len(inputs["buy_price"])
    assert len(diagnostics["tie_margins"]) == horizon
    assert len(diagnostics["value_slopes"]) == horizon
    assert len(diagnostics["soe_trajectory"]) == horizon + 1
    # This fixture is #450's own reproduction case -- known to flag exactly
    # one window.
    assert len(diagnostics["windows"]) == 1
    assert result.reward_objective_cost is not None


def test_tie_diagnostics_none_by_default_is_a_no_op():
    scenario = load_test_scenario("synthetic_consumption_efficient")
    inputs = _scenario_inputs(scenario)

    # Must not raise when tie_diagnostics is omitted -- this is the default,
    # unmodified call shape every existing production caller uses.
    result = optimize_battery_schedule(
        buy_price=inputs["buy_price"],
        sell_price=inputs["sell_price"],
        home_consumption=scenario["home_consumption"],
        solar_production=scenario["solar_production"],
        initial_soe=scenario["battery"]["initial_soe"],
        battery_settings=inputs["battery_settings"],
        period_duration_hours=inputs["period_duration_hours"],
        terminal_value_per_kwh=scenario.get("terminal_value_per_kwh", 0.0),
    )
    assert result.economic_summary is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest core/bess/tests/unit/test_tie_diagnostics_hook.py -v
```

Expected: FAIL — `TypeError: optimize_battery_schedule() got an unexpected keyword argument 'tie_diagnostics'`.

- [ ] **Step 3: Implement**

In `core/bess/dp_battery_algorithm.py`, add the parameter to the signature (around line 1799, alongside the existing `home_settings: HomeSettings | None = None`):

```python
def optimize_battery_schedule(
    buy_price: list[float],
    sell_price: list[float],
    home_consumption: list[float],
    battery_settings: BatterySettings,
    solar_production: list[float] | None = None,
    initial_soe: float | None = None,
    initial_cost_basis: float | None = None,
    period_duration_hours: float = 0.25,
    terminal_value_per_kwh: float = 0.0,
    currency: str = "SEK",
    max_charge_power_per_period: list[float] | None = None,
    discharge_resolution_kw: float | None = None,
    self_throttle_export_threshold_kwh: float | None = None,
    export_curtailment_active: bool = False,
    home_settings: HomeSettings | None = None,
    tie_diagnostics: dict | None = None,
) -> OptimizationResult:
```

Then, immediately after the existing line that computes `windows = detect_tie_windows(...)` (around line 2038-2042 in the current file — search for `windows = detect_tie_windows(`), insert:

```python
    if tie_diagnostics is not None:
        tie_diagnostics["tie_margins"] = list(tie_margins)
        tie_diagnostics["value_slopes"] = list(value_slopes)
        tie_diagnostics["windows"] = list(windows)
        tie_diagnostics["soe_trajectory"] = list(soe_trajectory)
        tie_diagnostics["resolved_initial_cost_basis"] = initial_cost_basis
```

Note: `initial_cost_basis` at this point in the function must already be resolved to a concrete float (not `None`) — confirm this by reading the function's early parameter-resolution section (search for where `initial_cost_basis` is first assigned/defaulted, typically near the top of the function body) before writing this line; if it's still resolved later than this insertion point, move the diagnostics-population block after that resolution instead.

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest core/bess/tests/unit/test_tie_diagnostics_hook.py -v
```

Expected: PASS, both tests.

- [ ] **Step 5: Run the fast suite to confirm zero regressions**

```bash
.venv/bin/pytest -m "not slow"
```

Expected: same pass count as before this change (purely additive, optional parameter).

- [ ] **Step 6: Commit**

```bash
git add core/bess/dp_battery_algorithm.py core/bess/tests/unit/test_tie_diagnostics_hook.py
git commit -m "feat: add optional tie_diagnostics hook to optimize_battery_schedule"
```

---

### Task 3: Margin-ratio classification

**Files:**
- Create: `core/bess/tests/synthetic/measure_tie_coverage.py` (this task adds only the classification piece; Task 4 adds the reference-cost piece to the same file)
- Test: `core/bess/tests/synthetic/test_measure_tie_coverage.py`

**Interfaces:**
- Consumes: `tie_margins: list[float]`, `value_slopes: list[float]` (from Task 2's diagnostics), `soe_step_kwh: float` (from `core.bess.dp_constants.SOE_STEP_KWH`).
- Produces:
  ```python
  def classify_margin_ratios(
      tie_margins: list[float], value_slopes: list[float], soe_step_kwh: float
  ) -> dict[str, int]:
      ...  # bucket name -> count, e.g. {"<0.1x": 12, "0.1x-0.5x": 3, ...}
  ```
  Consumed by Task 5's `measure_scenario`.

- [ ] **Step 1: Write the failing tests**

Create `core/bess/tests/synthetic/test_measure_tie_coverage.py`:

```python
from core.bess.tests.synthetic.measure_tie_coverage import classify_margin_ratios


def test_classifies_into_expected_buckets():
    # worst_case_noise = soe_step_kwh * abs(value_slope); ratio = margin / worst_case_noise
    # soe_step_kwh=0.1, value_slope=1.0 -> worst_case_noise=0.1 for every period below
    tie_margins = [0.005, 0.03, 0.08, 0.15, 0.25]
    value_slopes = [1.0, 1.0, 1.0, 1.0, 1.0]
    result = classify_margin_ratios(tie_margins, value_slopes, soe_step_kwh=0.1)
    # ratios: 0.05, 0.3, 0.8, 1.5, 2.5
    assert result == {
        "<0.1x": 1,
        "0.1x-0.5x": 1,
        "0.5x-1.0x": 1,
        "1.0x-2.0x": 1,
        ">2.0x": 1,
    }


def test_zero_value_slope_counts_as_over_2x():
    # worst_case_noise == 0 when value_slope == 0 -- ratio is undefined/infinite,
    # meaning grid-snapping cannot affect this period's ranking at all. Bucket
    # it in the "clearly not a tie" bucket rather than raising or dividing by zero.
    result = classify_margin_ratios([0.01], [0.0], soe_step_kwh=0.1)
    assert result == {">2.0x": 1}


def test_empty_input_returns_zero_counts():
    result = classify_margin_ratios([], [], soe_step_kwh=0.1)
    assert result == {
        "<0.1x": 0,
        "0.1x-0.5x": 0,
        "0.5x-1.0x": 0,
        "1.0x-2.0x": 0,
        ">2.0x": 0,
    }
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest core/bess/tests/synthetic/test_measure_tie_coverage.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'core.bess.tests.synthetic.measure_tie_coverage'`.

- [ ] **Step 3: Implement**

Create `core/bess/tests/synthetic/measure_tie_coverage.py`:

```python
"""Measurement harness for the #450 tie-detection coverage validation
suite (see docs/superpowers/specs/2026-08-05-tie-detection-synthetic-
validation-design.md)."""

_BUCKET_ORDER = ["<0.1x", "0.1x-0.5x", "0.5x-1.0x", "1.0x-2.0x", ">2.0x"]


def _bucket_for_ratio(ratio: float) -> str:
    if ratio < 0.1:
        return "<0.1x"
    if ratio < 0.5:
        return "0.1x-0.5x"
    if ratio < 1.0:
        return "0.5x-1.0x"
    if ratio < 2.0:
        return "1.0x-2.0x"
    return ">2.0x"


def classify_margin_ratios(
    tie_margins: list[float], value_slopes: list[float], soe_step_kwh: float
) -> dict[str, int]:
    counts = {bucket: 0 for bucket in _BUCKET_ORDER}
    for margin, slope in zip(tie_margins, value_slopes):
        worst_case_noise = soe_step_kwh * abs(slope)
        ratio = margin / worst_case_noise if worst_case_noise > 0 else float("inf")
        counts[_bucket_for_ratio(ratio)] += 1
    return counts
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest core/bess/tests/synthetic/test_measure_tie_coverage.py -v
```

Expected: PASS, all 3 tests.

- [ ] **Step 5: Commit**

```bash
git add core/bess/tests/synthetic/measure_tie_coverage.py core/bess/tests/synthetic/test_measure_tie_coverage.py
git commit -m "feat: add margin-ratio classification for #450 coverage validation"
```

---

### Task 4: Full-horizon "true optimal" reference cost

**Files:**
- Modify: `core/bess/tests/synthetic/measure_tie_coverage.py` (append)
- Test: `core/bess/tests/synthetic/test_measure_tie_coverage.py` (append)

**Interfaces:**
- Consumes: `run_pwl_window_backward_induction`, `resolve_pwl_window` (from `core.bess.pwl_window_dp`, both already accept `import_cap_kwh` per the #429 merge), `_compute_reward` (from `core.bess.dp_battery_algorithm`, returns `(reward, new_cost_basis, grid_imported)`).
- Produces:
  ```python
  def full_horizon_reference_cost(
      buy_price: list[float],
      sell_price: list[float],
      home_consumption: list[float],
      solar_production: list[float],
      battery_settings,
      dt: float,
      start_soe: float,
      end_soe_target: float,
      initial_cost_basis: float,
      self_throttle_export_threshold_kwh: float,
      import_cap_kwh: float | None,
  ) -> float:
      ...  # returns the reward_objective_cost of the exact full-horizon solve
  ```
  Consumed by Task 5's `measure_scenario`.

This reuses the windowed PWL solver over the *entire* horizon (not a narrow window) as the "true optimal" reference, pinned to the grid DP's own realized final SOE (per the design doc's accepted approximation — no free-terminal-SOE solver capability is being added).

- [ ] **Step 1: Write the failing test**

Append to `core/bess/tests/synthetic/test_measure_tie_coverage.py`:

```python
import pytest

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.tests.helpers import _scenario_inputs
from core.bess.tests.synthetic.measure_tie_coverage import full_horizon_reference_cost
from core.bess.tests.unit.test_scenarios import load_test_scenario


def test_full_horizon_reference_matches_or_beats_the_hybrid_on_450_fixture():
    scenario = load_test_scenario("regression_2026_08_02_043728")
    inputs = _scenario_inputs(scenario)
    diagnostics: dict = {}

    hybrid_result = optimize_battery_schedule(
        buy_price=inputs["buy_price"],
        sell_price=inputs["sell_price"],
        home_consumption=scenario["home_consumption"],
        solar_production=scenario["solar_production"],
        initial_soe=scenario["battery"]["initial_soe"],
        battery_settings=inputs["battery_settings"],
        period_duration_hours=inputs["period_duration_hours"],
        terminal_value_per_kwh=scenario.get("terminal_value_per_kwh", 0.0),
        tie_diagnostics=diagnostics,
    )

    reference_cost = full_horizon_reference_cost(
        buy_price=inputs["buy_price"],
        sell_price=inputs["sell_price"],
        home_consumption=scenario["home_consumption"],
        solar_production=scenario["solar_production"],
        battery_settings=inputs["battery_settings"],
        dt=inputs["period_duration_hours"],
        start_soe=diagnostics["soe_trajectory"][0],
        end_soe_target=diagnostics["soe_trajectory"][-1],
        initial_cost_basis=diagnostics["resolved_initial_cost_basis"],
        self_throttle_export_threshold_kwh=0.01,
        import_cap_kwh=None,
    )

    # The exact full-horizon solve can only match or beat the hybrid's
    # windowed (partial-coverage) result -- it is solving the same problem
    # with no windowing restriction at all.
    assert reference_cost <= hybrid_result.reward_objective_cost + 1e-6
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest core/bess/tests/synthetic/test_measure_tie_coverage.py::test_full_horizon_reference_matches_or_beats_the_hybrid_on_450_fixture -v
```

Expected: FAIL — `ImportError: cannot import name 'full_horizon_reference_cost'`.

- [ ] **Step 3: Implement**

Append to `core/bess/tests/synthetic/measure_tie_coverage.py`:

```python
from core.bess.dp_battery_algorithm import _compute_reward
from core.bess.pwl_window_dp import resolve_pwl_window, run_pwl_window_backward_induction


def full_horizon_reference_cost(
    buy_price: list[float],
    sell_price: list[float],
    home_consumption: list[float],
    solar_production: list[float],
    battery_settings,
    dt: float,
    start_soe: float,
    end_soe_target: float,
    initial_cost_basis: float,
    self_throttle_export_threshold_kwh: float,
    import_cap_kwh: float | None,
) -> float:
    """Exact reward-objective cost of the whole horizon, solved with no
    windowing restriction -- the "true optimal" reference this validation
    suite compares the hybrid's (possibly partial-coverage) result against.

    Pinned to `end_soe_target` (the grid DP's own realized final SOE) rather
    than a free terminal state -- an accepted approximation, see
    docs/superpowers/specs/2026-08-05-tie-detection-synthetic-validation-design.md.
    """
    horizon = len(buy_price)
    V = run_pwl_window_backward_induction(
        window_horizon=horizon,
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        battery_settings=battery_settings,
        dt=dt,
        end_soe_target=end_soe_target,
        self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
        import_cap_kwh=import_cap_kwh,
    )
    actions = resolve_pwl_window(
        V,
        start_soe=start_soe,
        window_horizon=horizon,
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        battery_settings=battery_settings,
        dt=dt,
        cost_basis=initial_cost_basis,
        self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
        import_cap_kwh=import_cap_kwh,
    )

    soe = start_soe
    cost_basis = initial_cost_basis
    reward_objective_cost = 0.0
    for t, (power, next_soe) in enumerate(actions):
        reward, cost_basis, _grid_imported = _compute_reward(
            power=power,
            soe=soe,
            next_soe=next_soe,
            period=t,
            home_consumption=home_consumption[t],
            battery_settings=battery_settings,
            dt=dt,
            buy_price=buy_price,
            sell_price=sell_price,
            solar_production=solar_production[t],
            cost_basis=cost_basis,
            self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
            import_cap_kwh=import_cap_kwh,
        )
        reward_objective_cost -= reward
        soe = next_soe

    return reward_objective_cost
```

Note: `resolve_pwl_window`'s exact parameter order/names must be double-checked against `core/bess/pwl_window_dp.py`'s current definition before this compiles — read that file's current `resolve_pwl_window` and `run_pwl_window_backward_induction` signatures first (they may have evolved slightly beyond what's summarized above) and adjust the call sites to match exactly.

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest core/bess/tests/synthetic/test_measure_tie_coverage.py -v
```

Expected: PASS, all tests including the new one. If `reference_cost` comes out *worse* than `hybrid_result.reward_objective_cost` (violating the assertion), that indicates a real bug in this reference implementation (e.g. a mismatched parameter, wrong sign) — debug there; the exact full-horizon solve must never be worse than a windowed subset of the same solve.

- [ ] **Step 5: Commit**

```bash
git add core/bess/tests/synthetic/measure_tie_coverage.py core/bess/tests/synthetic/test_measure_tie_coverage.py
git commit -m "feat: add full-horizon exact-PWL reference cost for #450 coverage validation"
```

---

### Task 5: `measure_scenario` — tying it together

**Files:**
- Modify: `core/bess/tests/synthetic/measure_tie_coverage.py` (append)
- Test: `core/bess/tests/synthetic/test_measure_tie_coverage.py` (append)

**Interfaces:**
- Consumes: `classify_margin_ratios` (Task 3), `full_horizon_reference_cost` (Task 4), `optimize_battery_schedule(..., tie_diagnostics=...)` (Task 2).
- Produces:
  ```python
  @dataclass(frozen=True)
  class ScenarioMeasurement:
      margin_ratio_counts: dict[str, int]
      financial_impact_sek: float | None  # None unless zero windows were flagged

  def measure_scenario(scenario: dict) -> ScenarioMeasurement:
      ...
  ```
  Consumed by Task 6's test.

- [ ] **Step 1: Write the failing tests**

Append to `core/bess/tests/synthetic/test_measure_tie_coverage.py`:

```python
from core.bess.tests.synthetic.measure_tie_coverage import ScenarioMeasurement, measure_scenario


def test_measure_scenario_on_450_fixture_has_no_financial_impact_since_it_flags_a_window():
    scenario = load_test_scenario("regression_2026_08_02_043728")
    result = measure_scenario(scenario)
    assert isinstance(result, ScenarioMeasurement)
    assert sum(result.margin_ratio_counts.values()) == len(scenario["home_consumption"])
    # This fixture's tie IS caught (that's #450's own regression pin) --
    # financial_impact_sek is only computed for zero-flag scenarios.
    assert result.financial_impact_sek is None


def test_measure_scenario_on_a_quiet_fixture_has_zero_or_near_zero_impact():
    scenario = load_test_scenario("synthetic_consumption_efficient")
    result = measure_scenario(scenario)
    # No known near-tie in this fixture -- if it flags zero windows, impact
    # should be ~0 (the grid DP already found the true optimum here).
    if result.financial_impact_sek is not None:
        assert result.financial_impact_sek == pytest.approx(0.0, abs=1e-6)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest core/bess/tests/synthetic/test_measure_tie_coverage.py -v -k measure_scenario
```

Expected: FAIL — `ImportError: cannot import name 'ScenarioMeasurement'`.

- [ ] **Step 3: Implement**

Append to `core/bess/tests/synthetic/measure_tie_coverage.py`:

```python
from dataclasses import dataclass

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.dp_constants import SOE_STEP_KWH
from core.bess.tests.helpers import _scenario_inputs


@dataclass(frozen=True)
class ScenarioMeasurement:
    margin_ratio_counts: dict[str, int]
    financial_impact_sek: float | None


def measure_scenario(scenario: dict) -> ScenarioMeasurement:
    inputs = _scenario_inputs(scenario)
    diagnostics: dict = {}

    hybrid_result = optimize_battery_schedule(
        buy_price=inputs["buy_price"],
        sell_price=inputs["sell_price"],
        home_consumption=scenario["home_consumption"],
        solar_production=scenario["solar_production"],
        initial_soe=scenario["battery"]["initial_soe"],
        battery_settings=inputs["battery_settings"],
        period_duration_hours=inputs["period_duration_hours"],
        terminal_value_per_kwh=scenario.get("terminal_value_per_kwh", 0.0),
        tie_diagnostics=diagnostics,
    )

    margin_ratio_counts = classify_margin_ratios(
        diagnostics["tie_margins"], diagnostics["value_slopes"], SOE_STEP_KWH
    )

    financial_impact_sek = None
    if not diagnostics["windows"]:
        reference_cost = full_horizon_reference_cost(
            buy_price=inputs["buy_price"],
            sell_price=inputs["sell_price"],
            home_consumption=scenario["home_consumption"],
            solar_production=scenario["solar_production"],
            battery_settings=inputs["battery_settings"],
            dt=inputs["period_duration_hours"],
            start_soe=diagnostics["soe_trajectory"][0],
            end_soe_target=diagnostics["soe_trajectory"][-1],
            initial_cost_basis=diagnostics["resolved_initial_cost_basis"],
            self_throttle_export_threshold_kwh=0.01,
            import_cap_kwh=None,
        )
        financial_impact_sek = hybrid_result.reward_objective_cost - reference_cost

    return ScenarioMeasurement(
        margin_ratio_counts=margin_ratio_counts,
        financial_impact_sek=financial_impact_sek,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest core/bess/tests/synthetic/test_measure_tie_coverage.py -v
```

Expected: PASS, all tests.

- [ ] **Step 5: Commit**

```bash
git add core/bess/tests/synthetic/measure_tie_coverage.py core/bess/tests/synthetic/test_measure_tie_coverage.py
git commit -m "feat: add measure_scenario, completing the #450 coverage measurement harness"
```

---

### Task 6: The slow-suite test — measure only, no budget yet

**Files:**
- Create: `core/bess/tests/unit/test_tie_detection_synthetic_coverage.py`

**Interfaces:**
- Consumes: `perturb_scenario`, `PerturbationParams` (Task 1), `measure_scenario` (Task 5), `load_test_scenario` (existing, `core.bess.tests.unit.test_scenarios`).
- Produces: a report (printed, not asserted yet) that Task 7 uses to set the real budget.

- [ ] **Step 1: Measure single-scenario cost before committing to a matrix size**

`full_horizon_reference_cost` (Task 4) runs the adaptive PWL backward induction over the *entire* horizon, not a narrow window — this is a fundamentally more expensive call than the windowed solves elsewhere in this codebase, and it fires on every zero-flag scenario (the large majority, based on the existing fixture suite's ~90% zero-flag rate). Before writing the full matrix, time one representative call:

```bash
.venv/bin/python -c "
import time
from core.bess.tests.synthetic.measure_tie_coverage import measure_scenario
from core.bess.tests.synthetic.perturb_scenario import PerturbationParams, perturb_scenario
from core.bess.tests.unit.test_scenarios import load_test_scenario

base = load_test_scenario('synthetic_consumption_efficient')
scenario = perturb_scenario(base, seed=1, params=PerturbationParams(price_level_multiplier=2.5))
start = time.time()
result = measure_scenario(scenario)
print(f'{time.time() - start:.2f}s, financial_impact={result.financial_impact_sek}')
"
```

Use the measured per-scenario time to size the matrix in Step 2 so the whole suite adds roughly 30-90 seconds to the existing ~150s slow suite, not minutes — if a single scenario takes noticeably more than ~1s, shrink the matrix below the counts suggested in Step 2 accordingly (fewer seeds first, then fewer battery overrides, then fewer solar/volatility levels — keep price-level coverage, since that's the dimension motivating this suite).

- [ ] **Step 2: Write the test with the assertion disabled**

Create `core/bess/tests/unit/test_tie_detection_synthetic_coverage.py`:

```python
"""Synthetic scenario coverage validation for the #450 tie detector (see
docs/superpowers/specs/2026-08-05-tie-detection-synthetic-validation-design.md).

Perturbs a fixed set of existing fixtures across price level, volatility,
solar, and battery size to measure the real financial impact of the tie
detector's known coverage blind spot -- not a theoretical worst-case bound.
"""

import pytest

from core.bess.tests.synthetic.measure_tie_coverage import measure_scenario
from core.bess.tests.synthetic.perturb_scenario import PerturbationParams, perturb_scenario
from core.bess.tests.unit.test_scenarios import load_test_scenario

pytestmark = pytest.mark.slow

# Fixed, version-controlled matrix: (base_fixture_name, seed, params).
# Every entry is deterministic -- re-running this list reproduces identical
# scenarios and identical measurements.
#
# Deliberately small (2*3*2*2*1*1 = 24 scenarios): full_horizon_reference_cost
# is expensive (a full-horizon adaptive PWL solve, not a narrow window), and
# fires on most of these since the large majority of scenarios flag zero
# windows. Widen this matrix later, informed by Step 1's measured per-scenario
# runtime, rather than guessing a larger size upfront.
_BASE_FIXTURES = [
    "synthetic_consumption_efficient",
    "realworld_2026_04_11_004719",
]
_PRICE_LEVELS = [0.5, 1.0, 2.5]  # low / baseline / winter-peak-like
_VOLATILITY_LEVELS = [0.0, 0.15]
_SOLAR_LEVELS = [0.0, 1.0]
_BATTERY_OVERRIDES = [None]
_SEEDS = [1]

_SCENARIO_MATRIX = [
    (
        base,
        seed,
        PerturbationParams(
            price_level_multiplier=price,
            volatility_jitter=volatility,
            solar_scale=solar,
            battery_capacity_override_kwh=battery,
        ),
    )
    for base in _BASE_FIXTURES
    for price in _PRICE_LEVELS
    for volatility in _VOLATILITY_LEVELS
    for solar in _SOLAR_LEVELS
    for battery in _BATTERY_OVERRIDES
    for seed in _SEEDS
]

# TIE_MISS_BUDGET_SEK is deliberately not enforced yet -- see Task 7 of
# docs/superpowers/plans/2026-08-05-tie-detection-synthetic-validation.md.
# This test currently only measures and reports; run it directly to produce
# the data that sets the real budget.
TIE_MISS_BUDGET_SEK = None


def test_synthetic_scenario_tie_coverage():
    aggregate_ratio_counts: dict[str, int] = {}
    worst_impact = 0.0
    worst_impact_scenario = None
    impacts_measured = 0

    for base_name, seed, params in _SCENARIO_MATRIX:
        base = load_test_scenario(base_name)
        scenario = perturb_scenario(base, seed=seed, params=params)
        measurement = measure_scenario(scenario)

        for bucket, count in measurement.margin_ratio_counts.items():
            aggregate_ratio_counts[bucket] = aggregate_ratio_counts.get(bucket, 0) + count

        if measurement.financial_impact_sek is not None:
            impacts_measured += 1
            if measurement.financial_impact_sek > worst_impact:
                worst_impact = measurement.financial_impact_sek
                worst_impact_scenario = (base_name, seed, params)

    print(f"\nAggregate margin-ratio distribution across {len(_SCENARIO_MATRIX)} scenarios:")
    for bucket, count in aggregate_ratio_counts.items():
        print(f"  {bucket}: {count}")
    print(f"Financial impact measured on {impacts_measured} zero-flag scenarios")
    print(f"Worst observed financial impact: {worst_impact:.6f} SEK ({worst_impact_scenario})")

    if TIE_MISS_BUDGET_SEK is not None:
        assert worst_impact <= TIE_MISS_BUDGET_SEK, (
            f"Worst observed missed-tie financial impact ({worst_impact:.6f} SEK, "
            f"scenario {worst_impact_scenario}) exceeds the budget "
            f"({TIE_MISS_BUDGET_SEK} SEK)"
        )
```

- [ ] **Step 3: Run the test and capture the report**

```bash
.venv/bin/pytest core/bess/tests/unit/test_tie_detection_synthetic_coverage.py -v -s
```

Expected: PASS (no budget enforced yet), with printed output showing the aggregate margin-ratio distribution and the worst observed financial impact across the matrix. Save this output — Task 7 needs it.

- [ ] **Step 4: Commit**

```bash
git add core/bess/tests/unit/test_tie_detection_synthetic_coverage.py
git commit -m "test: add synthetic tie-coverage measurement suite (budget not yet enforced)"
```

---

### Task 7: Review results and enable the real regression budget

**Files:**
- Modify: `core/bess/tests/unit/test_tie_detection_synthetic_coverage.py` (only `TIE_MISS_BUDGET_SEK`)

This task is a checkpoint, not pure implementation — it requires the real numbers from Task 6's run to be reviewed with the project owner before a budget is chosen.

- [ ] **Step 1: Present Task 6's captured output** (the aggregate margin-ratio distribution and worst observed financial impact) to the project owner for review.

- [ ] **Step 2: Agree on and set a real `TIE_MISS_BUDGET_SEK`** based on the observed worst-case impact (e.g. "no worse than 2x the worst impact observed" was the design doc's suggested starting point — confirm the actual multiplier/value with the owner rather than assuming it).

- [ ] **Step 3: Set the constant**

```python
TIE_MISS_BUDGET_SEK = <agreed value>  # replace None
```

- [ ] **Step 4: Run the test to confirm it now passes with the real assertion enabled**

```bash
.venv/bin/pytest core/bess/tests/unit/test_tie_detection_synthetic_coverage.py -v -s
```

Expected: PASS, with the assertion now actually checked (not skipped).

- [ ] **Step 5: Run the full fast + slow suites for final confirmation**

```bash
.venv/bin/pytest -m "not slow"
.venv/bin/pytest -m slow
```

Expected: all green.

- [ ] **Step 6: Run black/ruff, commit**

```bash
.venv/bin/black core/bess/tests/unit/test_tie_detection_synthetic_coverage.py
.venv/bin/ruff check --fix core/bess/tests/unit/test_tie_detection_synthetic_coverage.py
git add core/bess/tests/unit/test_tie_detection_synthetic_coverage.py
git commit -m "feat: enable real regression budget for #450 synthetic tie-coverage suite"
```
