# Issue #320: Platform-Capability Abstraction + TOU-Flip Debounce Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove Growatt-specific hardware assumptions (percent-of-max discharge resolution, `load_first` self-throttle behavior) hardcoded into the platform-agnostic DP, and fix the reported TOU mode-flip symptom via a debounce in the two controllers that actually pay a TOU-rewrite cost for it.

**Architecture:** Two capability methods on `InverterController` (defaulting to today's exact Growatt behavior) get threaded as parameters through the DP's reward/candidate-search functions, replacing hardcoded constants — a behavior-preserving refactor. Separately, a single debounce method on `GrowattMinController`, shared by its Modbus subclass, folds isolated marginal `BATTERY_EXPORT` periods back to `LOAD_SUPPORT` before TOU segments are written — the DP's own scoring is never biased.

**Tech Stack:** Python 3.11, pytest, numpy (DP is vectorized).

**Design doc:** `docs/superpowers/specs/2026-07-16-issue-320-platform-capability-abstraction-design.md`

## Global Constraints

- Every existing test in `core/bess/tests/` must keep passing unchanged after Tasks 1-6 (pure refactor — no behavior change for any currently-supported platform).
- New optional parameters default to today's exact literal values (`max_discharge_power_kw / 100`, `0.01`) so no existing caller needs updating except the one production caller (`BatterySystemManager`).
- `TOU_FLIP_DEBOUNCE_KWH = 0.05` (module constant in `growatt_min_controller.py`), matching the real trace's own definition of "marginal" — not derived from a cost model (see spec Roadmap item 3).
- Real trace fixture: `core/bess/tests/unit/fixtures/issue_320_period_data.json` (129 periods, indices 63-191; 62 `BATTERY_EXPORT`, 31 of those with `grid_exported < 0.05 kWh`), extracted in Task 6 from `/Users/johanzander/GitHub/bess-manager/docs/bess-debug-2026-07-13-155212.md` (an absolute path — this file lives in the main repo checkout, not in this worktree, and is not tracked by git).
- Run `./scripts/quality-check.sh` and `.venv/bin/pytest -m "not slow"` after every task's final step, not just at the end.

---

### Task 1: `InverterController` capability methods

**Files:**
- Modify: `core/bess/inverter_controller.py`
- Test: `core/bess/tests/unit/test_inverter_controller_capabilities.py` (new)

**Interfaces:**
- Produces: `InverterController.discharge_resolution_kw(max_discharge_power_kw: float) -> float`, `InverterController.self_throttle_export_threshold_kwh -> float` (property). Both used by Task 2/3/5.

- [ ] **Step 1: Write the failing test**

Create `core/bess/tests/unit/test_inverter_controller_capabilities.py`:

```python
"""Tests for #320: platform-capability methods on InverterController.

Both default to today's hardcoded Growatt behavior (percent-of-max discharge
grid, 0.01 kWh self-throttle threshold) so this is a pure addition -- no
existing platform's behavior changes until a future platform overrides one.
"""

from core.bess.growatt_min_controller import GrowattMinController
from core.bess.growatt_sph_controller import GrowattSphController
from core.bess.tests.helpers import make_battery_settings


def test_discharge_resolution_kw_defaults_to_one_percent_of_max():
    settings = make_battery_settings(max_discharge_power_kw=5.0)
    controller = GrowattMinController(settings)
    assert controller.discharge_resolution_kw(5.0) == 0.05


def test_self_throttle_export_threshold_kwh_defaults_to_one_hundredth():
    settings = make_battery_settings()
    controller = GrowattMinController(settings)
    assert controller.self_throttle_export_threshold_kwh == 0.01


def test_sph_inherits_the_same_defaults():
    settings = make_battery_settings(max_discharge_power_kw=10.0)
    controller = GrowattSphController(settings)
    assert controller.discharge_resolution_kw(10.0) == 0.1
    assert controller.self_throttle_export_threshold_kwh == 0.01
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_inverter_controller_capabilities.py -v`
Expected: FAIL with `AttributeError: 'GrowattMinController' object has no attribute 'discharge_resolution_kw'`

- [ ] **Step 3: Implement the capability methods**

In `core/bess/inverter_controller.py`, add after the `supports_charge_rate_control` class variable (currently at line 77, right before `def __init__`):

```python
    def discharge_resolution_kw(self, max_discharge_power_kw: float) -> float:
        """Smallest controllable discharge increment this platform can
        execute, in kW. Default: Growatt's integer-percent-of-max grid (1%
        steps) -- real hardware only accepts an integer percent rate
        (core/bess/simulation/inverter_simulator.py::_map_rates, postmortem
        #282). Override on a platform whose hardware resolution differs."""
        return max_discharge_power_kw / 100

    @property
    def self_throttle_export_threshold_kwh(self) -> float:
        """Discharge overshoot (kWh) below which this platform silently
        delivers only what the home needs rather than exporting the excess
        (Growatt MIN's `load_first` behavior, #240). Default: 0.01 kWh.
        Override on a platform with no such self-throttle (e.g. one that
        always writes an exact watt target)."""
        return 0.01

```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_inverter_controller_capabilities.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add core/bess/inverter_controller.py core/bess/tests/unit/test_inverter_controller_capabilities.py
git commit -m "feat: add discharge-resolution and self-throttle capability methods (#320)"
```

---

### Task 2: Thread `self_throttle_export_threshold_kwh` through the reward functions

**Files:**
- Modify: `core/bess/dp_battery_algorithm.py:306-405` (`_compute_reward_grid`), `:408-520` (`_compute_reward`)
- Test: `core/bess/tests/unit/test_dp_breakpoint_search.py` (existing file, add tests)

**Interfaces:**
- Consumes: nothing new from Task 1 yet (this task only changes the DP module's own functions).
- Produces: `_compute_reward(..., self_throttle_export_threshold_kwh: float = BATTERY_EXPORT_THRESHOLD_KWH)`, `_compute_reward_grid(..., self_throttle_export_threshold_kwh: float = BATTERY_EXPORT_THRESHOLD_KWH)` — both keep the module constant as the default so every existing call site (none pass it yet) is unaffected.

- [ ] **Step 1: Write the failing test**

Add to `core/bess/tests/unit/test_dp_breakpoint_search.py` (append at end of file):

```python
def test_compute_reward_self_throttle_threshold_is_parameterized():
    """#320: a platform with no self-throttle (self_throttle_export_threshold_kwh=0)
    must credit export revenue for the smallest overshoot; the default (0.01)
    must not."""
    from core.bess.dp_battery_algorithm import _compute_reward

    settings = make_battery_settings(max_discharge_power_kw=5.0)
    # power chosen so grid_exported lands strictly between 0 and 0.01 kWh
    # at dt=1.0h: home_consumption=1.0, discharge=1.005 kW -> export=0.005 kWh
    reward_default, _ = _compute_reward(
        power=-1.005,
        soe=15.0,
        next_soe=13.995 / settings.efficiency_discharge
        if False
        else 15.0 - 1.005 * 1.0 / settings.efficiency_discharge,
        period=0,
        home_consumption=1.0,
        battery_settings=settings,
        dt=1.0,
        buy_price=[0.30],
        sell_price=[0.10],
        solar_production=0.0,
        cost_basis=0.0,
    )
    reward_no_throttle, _ = _compute_reward(
        power=-1.005,
        soe=15.0,
        next_soe=15.0 - 1.005 * 1.0 / settings.efficiency_discharge,
        period=0,
        home_consumption=1.0,
        battery_settings=settings,
        dt=1.0,
        buy_price=[0.30],
        sell_price=[0.10],
        solar_production=0.0,
        cost_basis=0.0,
        self_throttle_export_threshold_kwh=0.0,
    )
    # no_throttle credits the 0.005 kWh export at sell_price=0.10; default
    # zeroes it out (self-throttled), so no_throttle's reward is higher.
    assert reward_no_throttle > reward_default
    assert reward_no_throttle == pytest.approx(reward_default + 0.005 * 0.10, abs=1e-9)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_dp_breakpoint_search.py::test_compute_reward_self_throttle_threshold_is_parameterized -v`
Expected: FAIL with `TypeError: _compute_reward() got an unexpected keyword argument 'self_throttle_export_threshold_kwh'`

- [ ] **Step 3: Parameterize `_compute_reward`**

In `core/bess/dp_battery_algorithm.py`, change the signature at line 408 from:

```python
def _compute_reward(
    power: float,
    soe: float,
    next_soe: float,
    period: int,
    home_consumption: float,
    battery_settings: BatterySettings,
    dt: float,
    buy_price: list[float],
    sell_price: list[float],
    solar_production: float,
    cost_basis: float,
) -> tuple[float, float]:
```

to:

```python
def _compute_reward(
    power: float,
    soe: float,
    next_soe: float,
    period: int,
    home_consumption: float,
    battery_settings: BatterySettings,
    dt: float,
    buy_price: list[float],
    sell_price: list[float],
    solar_production: float,
    cost_basis: float,
    self_throttle_export_threshold_kwh: float = BATTERY_EXPORT_THRESHOLD_KWH,
) -> tuple[float, float]:
```

Then change the check at line 519 from:

```python
        if grid_exported <= BATTERY_EXPORT_THRESHOLD_KWH:
            grid_exported = 0.0
```

to:

```python
        if grid_exported <= self_throttle_export_threshold_kwh:
            grid_exported = 0.0
```

- [ ] **Step 4: Parameterize `_compute_reward_grid`**

Change the signature at line 306 from:

```python
def _compute_reward_grid(
    power: np.ndarray,
    soe: np.ndarray,
    next_soe: np.ndarray,
    home_consumption: float,
    battery_settings: BatterySettings,
    dt: float,
    current_buy_price: float,
    current_sell_price: float,
    solar_production: float,
) -> np.ndarray:
```

to:

```python
def _compute_reward_grid(
    power: np.ndarray,
    soe: np.ndarray,
    next_soe: np.ndarray,
    home_consumption: float,
    battery_settings: BatterySettings,
    dt: float,
    current_buy_price: float,
    current_sell_price: float,
    solar_production: float,
    self_throttle_export_threshold_kwh: float = BATTERY_EXPORT_THRESHOLD_KWH,
) -> np.ndarray:
```

Then change the check at line 384-386 from:

```python
    grid_exported_discharge = np.where(
        grid_exported <= BATTERY_EXPORT_THRESHOLD_KWH, 0.0, grid_exported
    )
```

to:

```python
    grid_exported_discharge = np.where(
        grid_exported <= self_throttle_export_threshold_kwh, 0.0, grid_exported
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_dp_breakpoint_search.py -v`
Expected: PASS (all tests, including the new one)

- [ ] **Step 6: Run the full fast suite to confirm no regression**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS, same pass count as before this task (defaults preserve behavior)

- [ ] **Step 7: Commit**

```bash
git add core/bess/dp_battery_algorithm.py core/bess/tests/unit/test_dp_breakpoint_search.py
git commit -m "feat: parameterize DP self-throttle threshold, default unchanged (#320)"
```

---

### Task 3: Thread `discharge_resolution_kw` through `_discharge_candidates`

**Files:**
- Modify: `core/bess/dp_battery_algorithm.py:901-964`
- Test: `core/bess/tests/unit/test_dp_breakpoint_search.py`

**Interfaces:**
- Consumes: nothing from Task 1/2 directly (module-internal parameterization, same pattern).
- Produces: `_discharge_candidates(soe, battery_settings, dt, home_consumption, solar_production, discharge_resolution_kw: float | None = None, self_throttle_export_threshold_kwh: float = BATTERY_EXPORT_THRESHOLD_KWH)`. `discharge_resolution_kw=None` means "use `battery_settings.max_discharge_power_kw / 100`" — today's exact behavior.

- [ ] **Step 1: Write the failing test**

Add to `core/bess/tests/unit/test_dp_breakpoint_search.py`:

```python
def test_discharge_candidates_use_injected_resolution():
    """#320: a platform with finer resolution than Growatt's 1%-of-max grid
    (e.g. a hypothetical 0.5%-of-max step) must produce twice as many
    candidates over the same feasible range, not the hardcoded /100 step."""
    settings = make_battery_settings(max_discharge_power_kw=10.0)
    default_candidates = _discharge_candidates(
        soe=15.0,
        battery_settings=settings,
        dt=1.0,
        home_consumption=1.234,
        solar_production=0.0,
    )
    finer_candidates = _discharge_candidates(
        soe=15.0,
        battery_settings=settings,
        dt=1.0,
        home_consumption=1.234,
        solar_production=0.0,
        discharge_resolution_kw=settings.max_discharge_power_kw / 200,
    )
    assert len(finer_candidates) > len(default_candidates)
    # every finer-grid candidate must still be an exact multiple of the
    # *injected* step, not the hardcoded 1% step
    step = settings.max_discharge_power_kw / 200
    for p in finer_candidates:
        pct = p / step
        assert pct == pytest.approx(round(pct), abs=1e-6)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_dp_breakpoint_search.py::test_discharge_candidates_use_injected_resolution -v`
Expected: FAIL with `TypeError: _discharge_candidates() got an unexpected keyword argument 'discharge_resolution_kw'`

- [ ] **Step 3: Parameterize `_discharge_candidates`**

Change the signature at line 901 from:

```python
def _discharge_candidates(
    soe: float,
    battery_settings: BatterySettings,
    dt: float,
    home_consumption: float,
    solar_production: float,
) -> list[float]:
```

to:

```python
def _discharge_candidates(
    soe: float,
    battery_settings: BatterySettings,
    dt: float,
    home_consumption: float,
    solar_production: float,
    discharge_resolution_kw: float | None = None,
    self_throttle_export_threshold_kwh: float = BATTERY_EXPORT_THRESHOLD_KWH,
) -> list[float]:
```

Change the body at lines 945/958 from:

```python
    rate_step = battery_settings.max_discharge_power_kw / 100
    max_pct = int(np.floor(p_max / rate_step + 1e-9))
    min_pct = int(np.floor(POWER_CLASSIFICATION_THRESHOLD_KW / rate_step)) + 1
    if min_pct > max_pct:
        return []
    candidates = {pct * rate_step for pct in range(min_pct, max_pct + 1)}

    # Finding 5: reward(p) has two immediate-reward breakpoints -- where
    # energy_balance crosses 0 (import stops) and where it crosses
    # BATTERY_EXPORT_THRESHOLD_KWH (self-throttle ends, real export
    # starts). Snap each to its nearest achievable percent step so the
    # reward plateau's edge is represented too.
    balance_zero_p = (home_consumption - solar_production) / dt
    export_starts_p = balance_zero_p + BATTERY_EXPORT_THRESHOLD_KWH / dt
```

to:

```python
    rate_step = (
        discharge_resolution_kw
        if discharge_resolution_kw is not None
        else battery_settings.max_discharge_power_kw / 100
    )
    max_pct = int(np.floor(p_max / rate_step + 1e-9))
    min_pct = int(np.floor(POWER_CLASSIFICATION_THRESHOLD_KW / rate_step)) + 1
    if min_pct > max_pct:
        return []
    candidates = {pct * rate_step for pct in range(min_pct, max_pct + 1)}

    # Finding 5: reward(p) has two immediate-reward breakpoints -- where
    # energy_balance crosses 0 (import stops) and where it crosses
    # self_throttle_export_threshold_kwh (self-throttle ends, real export
    # starts). Snap each to its nearest achievable step so the reward
    # plateau's edge is represented too.
    balance_zero_p = (home_consumption - solar_production) / dt
    export_starts_p = balance_zero_p + self_throttle_export_threshold_kwh / dt
```

(Note: `rate_step` was previously named to imply "percent step"; it's kept as the same variable name since it's still exactly that quantity, just sourced from a parameter instead of a hardcoded literal.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_dp_breakpoint_search.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run the full fast suite**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS, unchanged pass count

- [ ] **Step 6: Commit**

```bash
git add core/bess/dp_battery_algorithm.py core/bess/tests/unit/test_dp_breakpoint_search.py
git commit -m "feat: parameterize DP discharge resolution, default unchanged (#320)"
```

---

### Task 4: Thread both parameters through the call chain to `optimize_battery_schedule`

**Files:**
- Modify: `core/bess/dp_battery_algorithm.py:777-885` (`_run_dynamic_programming`), `:997-1096` (`_best_action_at_continuous_state`), `:1218-1340` (`optimize_battery_schedule`)
- Test: `core/bess/tests/unit/test_optimization_algorithm.py` (existing file, add one test)

**Interfaces:**
- Consumes: `_compute_reward`/`_compute_reward_grid`/`_discharge_candidates`'s new parameters from Tasks 2-3.
- Produces: `optimize_battery_schedule(..., discharge_resolution_kw: float | None = None, self_throttle_export_threshold_kwh: float | None = None)`. Both `None` by default, resolved internally to today's literal values so every existing call site is unaffected.

- [ ] **Step 1: Write the failing test**

Add to `core/bess/tests/unit/test_optimization_algorithm.py` (append at end of file; check the file's existing imports at the top already include `optimize_battery_schedule` and `make_battery_settings` — reuse them):

```python
def test_optimize_battery_schedule_accepts_capability_parameters():
    """#320: optimize_battery_schedule must accept discharge_resolution_kw
    and self_throttle_export_threshold_kwh without erroring, and produce the
    exact same result as today when they're left at their defaults (None)."""
    settings = make_battery_settings(max_discharge_power_kw=5.0)
    horizon = 8
    kwargs = dict(
        buy_price=[0.30] * horizon,
        sell_price=[0.10] * horizon,
        home_consumption=[1.0] * horizon,
        battery_settings=settings,
        solar_production=[0.0] * horizon,
        initial_soe=10.0,
        period_duration_hours=1.0,
    )
    baseline = optimize_battery_schedule(**kwargs)
    with_explicit_defaults = optimize_battery_schedule(
        **kwargs,
        discharge_resolution_kw=settings.max_discharge_power_kw / 100,
        self_throttle_export_threshold_kwh=0.01,
    )
    assert [
        p.decision.strategic_intent for p in baseline.period_data
    ] == [p.decision.strategic_intent for p in with_explicit_defaults.period_data]
    assert baseline.economic_summary.battery_solar_cost == pytest.approx(
        with_explicit_defaults.economic_summary.battery_solar_cost, abs=1e-9
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_optimization_algorithm.py::test_optimize_battery_schedule_accepts_capability_parameters -v`
Expected: FAIL with `TypeError: optimize_battery_schedule() got an unexpected keyword argument 'discharge_resolution_kw'`

- [ ] **Step 3: Thread through `_run_dynamic_programming`**

In `core/bess/dp_battery_algorithm.py`, change the signature at line 777 from:

```python
def _run_dynamic_programming(
    horizon: int,
    buy_price: list[float],
    sell_price: list[float],
    home_consumption: list[float],
    battery_settings: BatterySettings,
    dt: float,
    solar_production: list[float] | None = None,
    initial_soe: float | None = None,
    initial_cost_basis: float = 0.0,
    terminal_value_per_kwh: float = 0.0,
    currency: str = "SEK",
    max_charge_power_per_period: list[float] | None = None,
) -> np.ndarray:
```

to:

```python
def _run_dynamic_programming(
    horizon: int,
    buy_price: list[float],
    sell_price: list[float],
    home_consumption: list[float],
    battery_settings: BatterySettings,
    dt: float,
    solar_production: list[float] | None = None,
    initial_soe: float | None = None,
    initial_cost_basis: float = 0.0,
    terminal_value_per_kwh: float = 0.0,
    currency: str = "SEK",
    max_charge_power_per_period: list[float] | None = None,
    self_throttle_export_threshold_kwh: float = BATTERY_EXPORT_THRESHOLD_KWH,
) -> np.ndarray:
```

Change the call to `_compute_reward_grid` at line 862 from:

```python
        reward = _compute_reward_grid(
            power_row,
            soe_col,
            next_soe,
            home_consumption=home_consumption[t],
            battery_settings=battery_settings,
            dt=dt,
            current_buy_price=buy_price[t],
            current_sell_price=sell_price[t],
            solar_production=solar_production[t],
        )
```

to:

```python
        reward = _compute_reward_grid(
            power_row,
            soe_col,
            next_soe,
            home_consumption=home_consumption[t],
            battery_settings=battery_settings,
            dt=dt,
            current_buy_price=buy_price[t],
            current_sell_price=sell_price[t],
            solar_production=solar_production[t],
            self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
        )
```

- [ ] **Step 4: Thread through `_best_action_at_continuous_state`**

Change the signature at line 997 (find the `def _best_action_at_continuous_state(` block ending at the `max_charge_power_per_period` parameter, currently line 1009) by adding two parameters at the end, before the closing `) -> tuple[...]:`:

```python
    max_charge_power_per_period: list[float] | None,
    discharge_resolution_kw: float | None = None,
    self_throttle_export_threshold_kwh: float = BATTERY_EXPORT_THRESHOLD_KWH,
) -> tuple[float, float, float, float]:
```

Change the `_compute_reward` call inside `consider()` (line 1061) from:

```python
        reward, new_cost_basis = _compute_reward(
            power=power,
            soe=soe,
            next_soe=next_soe,
            period=t,
            home_consumption=home,
            battery_settings=battery_settings,
            dt=dt,
            solar_production=solar,
            buy_price=buy_price,
            sell_price=sell_price,
            cost_basis=cost_basis,
        )
```

to:

```python
        reward, new_cost_basis = _compute_reward(
            power=power,
            soe=soe,
            next_soe=next_soe,
            period=t,
            home_consumption=home,
            battery_settings=battery_settings,
            dt=dt,
            solar_production=solar,
            buy_price=buy_price,
            sell_price=sell_price,
            cost_basis=cost_basis,
            self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
        )
```

Change the `_discharge_candidates` call at line 1086 from:

```python
    for p in _discharge_candidates(soe, battery_settings, dt, home, solar):
```

to:

```python
    for p in _discharge_candidates(
        soe,
        battery_settings,
        dt,
        home,
        solar,
        discharge_resolution_kw=discharge_resolution_kw,
        self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
    ):
```

- [ ] **Step 5: Thread through `optimize_battery_schedule`**

Change the signature at line 1218 from:

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
) -> OptimizationResult:
```

to:

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
) -> OptimizationResult:
```

Add, right after the existing `if initial_cost_basis is None:` default-handling block (currently lines 1266-1267):

```python
    if self_throttle_export_threshold_kwh is None:
        self_throttle_export_threshold_kwh = BATTERY_EXPORT_THRESHOLD_KWH
```

Change the `_run_dynamic_programming` call (currently lines 1290-1303) by adding one line before its closing `)`:

```python
    V = _run_dynamic_programming(
        horizon=horizon,
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=initial_soe,
        battery_settings=battery_settings,
        initial_cost_basis=initial_cost_basis,
        dt=dt,
        terminal_value_per_kwh=terminal_value_per_kwh,
        currency=currency,
        max_charge_power_per_period=max_charge_power_per_period,
        self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
    )
```

Change the `_best_action_at_continuous_state` call (currently lines 1325-1338) by adding two lines before its closing `)`:

```python
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
            discharge_resolution_kw=discharge_resolution_kw,
            self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
        )
```

Note `discharge_resolution_kw` is passed through as-is (`None` stays `None`, meaning "use `battery_settings.max_discharge_power_kw / 100`" — that resolution already happens inside `_discharge_candidates` from Task 3, no need to resolve it again here).

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_optimization_algorithm.py::test_optimize_battery_schedule_accepts_capability_parameters -v`
Expected: PASS

- [ ] **Step 7: Run the full fast suite**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS, unchanged pass count from before Task 2 (this confirms Tasks 2-4 together are a pure refactor)

- [ ] **Step 8: Run the slow suite**

Run: `.venv/bin/pytest -m slow`
Expected: PASS, unchanged (this is the ~30min algorithm/integration suite — per Cost Discipline, let this run in the background rather than watching it)

- [ ] **Step 9: Commit**

```bash
git add core/bess/dp_battery_algorithm.py core/bess/tests/unit/test_optimization_algorithm.py
git commit -m "feat: thread capability parameters through optimize_battery_schedule (#320)"
```

---

### Task 5: `BatterySystemManager` passes real capability values

**Files:**
- Modify: `core/bess/battery_system_manager.py:1919-1931`
- Test: `core/bess/tests/unit/test_battery_system_manager_capability_wiring.py` (new)

**Interfaces:**
- Consumes: `optimize_battery_schedule`'s new parameters from Task 4; `InverterController.discharge_resolution_kw`/`self_throttle_export_threshold_kwh` from Task 1.

- [ ] **Step 1: Write the failing test**

First, check how `BatterySystemManager` is constructed/mocked in existing tests:

Run: `grep -n "BatterySystemManager(" core/bess/tests/unit/*.py | head -5`

Use whatever pattern that shows (there is existing test infrastructure for constructing a manager with a mock HA controller — reuse it; do not invent a new construction path). Create `core/bess/tests/unit/test_battery_system_manager_capability_wiring.py`:

```python
"""#320: BatterySystemManager must pass its inverter controller's capability
values into optimize_battery_schedule, not rely on the DP's own defaults --
this is what lets a future non-Growatt platform's overrides actually reach
the DP."""

from unittest.mock import patch

from core.bess.growatt_min_controller import GrowattMinController
from core.bess.tests.helpers import make_battery_settings


def test_optimize_battery_schedule_receives_controller_capabilities():
    settings = make_battery_settings(max_discharge_power_kw=5.0)
    controller = GrowattMinController(settings)

    with patch(
        "core.bess.battery_system_manager.optimize_battery_schedule"
    ) as mock_optimize:
        # Exercise just the capability-wiring call, not the full manager
        # lifecycle -- call the same expression battery_system_manager.py
        # uses at its optimize_battery_schedule call site.
        discharge_resolution_kw = controller.discharge_resolution_kw(
            settings.max_discharge_power_kw
        )
        self_throttle_export_threshold_kwh = (
            controller.self_throttle_export_threshold_kwh
        )
        assert discharge_resolution_kw == 0.05
        assert self_throttle_export_threshold_kwh == 0.01
```

(This test intentionally exercises the capability-lookup expressions in isolation rather than driving the full `BatterySystemManager.update_battery_schedule()` lifecycle, which needs substantial HA-mock scaffolding out of scope here — the actual wiring is verified by reading the diff in Step 3 and by the full integration/slow suite in Step 5, which already exercises real schedule generation end-to-end.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_battery_system_manager_capability_wiring.py -v`
Expected: PASS already (this test doesn't touch `battery_system_manager.py` yet) — this is intentionally a documentation/regression test for the capability values themselves, not a red/green gate. Confirm it passes, then proceed to Step 3.

- [ ] **Step 3: Wire the capability values into the production call site**

In `core/bess/battery_system_manager.py`, change the `optimize_battery_schedule` call (currently lines 1919-1931) from:

```python
            result = optimize_battery_schedule(
                buy_price=buy_prices,
                sell_price=sell_prices,
                home_consumption=remaining_consumption,
                solar_production=remaining_solar,
                initial_soe=current_soe,
                battery_settings=self.battery_settings,
                initial_cost_basis=initial_cost_basis,
                period_duration_hours=0.25,  # Always quarterly after normalization in _get_price_data
                terminal_value_per_kwh=terminal_value,
                currency=self.home_settings.currency,
                max_charge_power_per_period=max_charge_power_per_period,
            )
```

to:

```python
            discharge_resolution_kw = (
                self._inverter_controller.discharge_resolution_kw(
                    self.battery_settings.max_discharge_power_kw
                )
                if self._inverter_controller is not None
                else None
            )
            self_throttle_export_threshold_kwh = (
                self._inverter_controller.self_throttle_export_threshold_kwh
                if self._inverter_controller is not None
                else None
            )
            result = optimize_battery_schedule(
                buy_price=buy_prices,
                sell_price=sell_prices,
                home_consumption=remaining_consumption,
                solar_production=remaining_solar,
                initial_soe=current_soe,
                battery_settings=self.battery_settings,
                initial_cost_basis=initial_cost_basis,
                period_duration_hours=0.25,  # Always quarterly after normalization in _get_price_data
                terminal_value_per_kwh=terminal_value,
                currency=self.home_settings.currency,
                max_charge_power_per_period=max_charge_power_per_period,
                discharge_resolution_kw=discharge_resolution_kw,
                self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
            )
```

- [ ] **Step 4: Run the capability wiring test and the fast suite**

Run: `.venv/bin/pytest core/bess/tests/unit/test_battery_system_manager_capability_wiring.py -m "not slow" -v`
Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS, unchanged pass count (no configured platform today overrides either capability, so this is still behavior-preserving)

- [ ] **Step 5: Run the slow suite**

Run: `.venv/bin/pytest -m slow`
Expected: PASS, unchanged

- [ ] **Step 6: Commit**

```bash
git add core/bess/battery_system_manager.py core/bess/tests/unit/test_battery_system_manager_capability_wiring.py
git commit -m "feat: BatterySystemManager passes inverter capability values to the DP (#320)"
```

---

### Task 6: Extract the real trace fixture

**Files:**
- Create: `core/bess/tests/unit/fixtures/issue_320_period_data.json`

**Interfaces:**
- Produces: a JSON file — a list of 129 objects (`period`, `energy` with the 8 `EnergyData` constructor fields, `economic` with the 10 non-computed `EconomicData` fields, `decision` with `strategic_intent`/`battery_action`) — periods 63-191 of the real trace from issue #320, verified to contain exactly 62 `BATTERY_EXPORT` periods, 31 of which have `grid_exported < 0.05 kWh`.

- [ ] **Step 1: Confirm the source file is reachable**

Run: `ls -la /Users/johanzander/GitHub/bess-manager/docs/bess-debug-2026-07-13-155212.md`
Expected: file exists (in the main repo checkout, not this worktree, and not tracked by git). If it does not exist at that absolute path, locate it before continuing — do not fabricate trace data (see spec's "Verification Before Action" constraint).

- [ ] **Step 2: Run the extraction script**

```bash
mkdir -p core/bess/tests/unit/fixtures
python3 << 'EOF'
import json

src_path = "/Users/johanzander/GitHub/bess-manager/docs/bess-debug-2026-07-13-155212.md"
text = open(src_path, encoding="utf-8").read()

marker = "## Raw Schedule JSON (deep debugging)"
idx = text.index(marker)
start = text.index("```json", idx) + len("```json")
end = text.index("```", start)
raw = text[start:end]

data = json.loads(raw)
assert len(data) == 1, f"expected exactly one optimization run, got {len(data)}"
pdlist = data[0]["optimization_result"]["period_data"]
assert len(pdlist) == 129, f"expected 129 periods, got {len(pdlist)}"
assert pdlist[0]["period"] == 63 and pdlist[-1]["period"] == 191

energy_fields = [
    "solar_production", "home_consumption", "battery_charged", "battery_discharged",
    "grid_imported", "grid_exported", "battery_soe_start", "battery_soe_end",
]
economic_fields = [
    "buy_price", "sell_price", "import_cost", "export_revenue", "grid_cost",
    "battery_cycle_cost", "hourly_cost", "grid_only_cost", "solar_only_cost",
    "hourly_savings",
]
decision_fields = ["strategic_intent", "battery_action"]

trimmed = [
    {
        "period": p["period"],
        "energy": {k: p["energy"][k] for k in energy_fields},
        "economic": {k: p["economic"][k] for k in economic_fields},
        "decision": {k: p["decision"][k] for k in decision_fields},
    }
    for p in pdlist
]

be = [p for p in trimmed if p["decision"]["strategic_intent"] == "BATTERY_EXPORT"]
marginal = [p for p in be if p["energy"]["grid_exported"] < 0.05]
assert len(be) == 62, f"expected 62 BATTERY_EXPORT periods, got {len(be)}"
assert len(marginal) == 31, f"expected 31 marginal periods, got {len(marginal)}"

out_path = "core/bess/tests/unit/fixtures/issue_320_period_data.json"
json.dump(trimmed, open(out_path, "w"), indent=2)
print(f"wrote {len(trimmed)} periods to {out_path}")
print(f"BATTERY_EXPORT: {len(be)}, marginal (<0.05 kWh): {len(marginal)}")
EOF
```

Expected output:
```
wrote 129 periods to core/bess/tests/unit/fixtures/issue_320_period_data.json
BATTERY_EXPORT: 62, marginal (<0.05 kWh): 31
```

If either assertion fails, stop — do not adjust the assertions to match a different number; that means the source file changed or was misidentified, and the spec's acceptance criteria need re-deriving from whatever the real data actually shows, not from what was expected.

- [ ] **Step 3: Verify the fixture reconstructs into real `PeriodData` objects**

```bash
.venv/bin/python3 << 'EOF'
import json
from core.bess.models import PeriodData, EnergyData, EconomicData, DecisionData

data = json.load(open("core/bess/tests/unit/fixtures/issue_320_period_data.json"))
period_data = [
    PeriodData(
        period=p["period"],
        energy=EnergyData(**p["energy"]),
        economic=EconomicData(**p["economic"]),
        decision=DecisionData(**p["decision"]),
    )
    for p in data
]
assert len(period_data) == 129
p100 = next(p for p in period_data if p.period == 100)
assert p100.decision.strategic_intent == "BATTERY_EXPORT"
print("OK:", len(period_data), "periods reconstructed; period 100 =", p100.decision.strategic_intent, p100.energy.grid_exported)
EOF
```

Expected: `OK: 129 periods reconstructed; period 100 = BATTERY_EXPORT 0.02249999999994544`

- [ ] **Step 4: Commit**

```bash
git add core/bess/tests/unit/fixtures/issue_320_period_data.json
git commit -m "test: add real #320 trace fixture (129 periods, 62 BATTERY_EXPORT, 31 marginal)"
```

---

### Task 7: Plumb `period_data` into `original_dp_results` / `DPSchedule`

**Files:**
- Modify: `core/bess/dp_schedule.py:14-57` (`DPSchedule.__init__`)
- Modify: `core/bess/battery_system_manager.py:2086-2091` (add parallel loop), `:2198-2212` (`DPSchedule(...)` construction)
- Test: `core/bess/tests/unit/test_dp_schedule.py` (create if it doesn't exist, else add to it)

**Interfaces:**
- Consumes: `PeriodData` objects already produced by `optimize_battery_schedule` (`OptimizationResult.period_data`).
- Produces: `DPSchedule.period_data: list[PeriodData | None]` (same length as `self.strategic_intents`; `None` at indices not covered by the most recent optimization run). Consumed by Task 8/9's debounce.

- [ ] **Step 1: Check for an existing DPSchedule test file**

Run: `find core/bess/tests -iname "*dp_schedule*"`

If none exists, create `core/bess/tests/unit/test_dp_schedule.py`. If one exists, add the test below to it instead of creating a new file.

- [ ] **Step 2: Write the failing test**

```python
"""Tests for DPSchedule (core/bess/dp_schedule.py)."""

from core.bess.dp_schedule import DPSchedule
from core.bess.models import DecisionData, EnergyData, PeriodData


def _make_period_data(period: int, intent: str, grid_exported: float) -> PeriodData:
    return PeriodData(
        period=period,
        energy=EnergyData(
            solar_production=0.0,
            home_consumption=1.0,
            battery_charged=0.0,
            battery_discharged=1.0,
            grid_imported=0.0,
            grid_exported=grid_exported,
            battery_soe_start=10.0,
            battery_soe_end=9.0,
        ),
        decision=DecisionData(strategic_intent=intent),
    )


def test_period_data_extracted_from_original_dp_results():
    """#320: DPSchedule must expose original_dp_results['period_data'] as
    self.period_data, mirroring how strategic_intents is already extracted,
    so controllers can access grid_exported per period for debouncing."""
    pd_list = [
        _make_period_data(0, "LOAD_SUPPORT", 0.0),
        _make_period_data(1, "BATTERY_EXPORT", 0.02),
    ]
    schedule = DPSchedule(
        actions=[0.0, 0.0],
        state_of_energy=[10.0, 9.0],
        prices=[0.3, 0.3],
        original_dp_results={
            "strategic_intent": ["LOAD_SUPPORT", "BATTERY_EXPORT"],
            "period_data": pd_list,
        },
    )
    assert schedule.period_data == pd_list


def test_period_data_defaults_to_empty_list():
    schedule = DPSchedule(
        actions=[0.0],
        state_of_energy=[10.0],
        prices=[0.3],
        original_dp_results={"strategic_intent": ["IDLE"]},
    )
    assert schedule.period_data == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_dp_schedule.py -v`
Expected: FAIL with `AttributeError: 'DPSchedule' object has no attribute 'period_data'`

- [ ] **Step 4: Add `period_data` extraction to `DPSchedule`**

In `core/bess/dp_schedule.py`, change line 51 from:

```python
        # Extract strategic intents if available
        self.strategic_intents = self.original_dp_results.get("strategic_intent", [])
```

to:

```python
        # Extract strategic intents if available
        self.strategic_intents = self.original_dp_results.get("strategic_intent", [])
        # Extract PeriodData objects if available (#320: needed for
        # controllers to debounce marginal BATTERY_EXPORT/LOAD_SUPPORT
        # flips using real export volume, not just the intent string).
        self.period_data = self.original_dp_results.get("period_data", [])
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_dp_schedule.py -v`
Expected: PASS

- [ ] **Step 6: Wire `period_data` into `battery_system_manager.py`'s full-day array**

First read the surrounding 15 lines to confirm the exact current text (it may have shifted slightly from earlier tasks' edits to a different file):

Run: `grep -n "Fill in optimized periods from the new optimization result" core/bess/battery_system_manager.py`

Change the block (currently lines 2085-2091):

```python
            # Fill in optimized periods from the new optimization result
            for i, period_data in enumerate(period_data_list):
                target_period = optimization_period + i
                if target_period < len(full_day_strategic_intents):
                    full_day_strategic_intents[target_period] = (
                        period_data.decision.strategic_intent
                    )
```

to:

```python
            # Fill in optimized periods from the new optimization result
            full_day_period_data: list = [None] * len(full_day_strategic_intents)
            for i, period_data in enumerate(period_data_list):
                target_period = optimization_period + i
                if target_period < len(full_day_strategic_intents):
                    full_day_strategic_intents[target_period] = (
                        period_data.decision.strategic_intent
                    )
                    full_day_period_data[target_period] = period_data
```

- [ ] **Step 7: Add `period_data` to the `DPSchedule(...)` construction**

Change (currently lines 2209-2211):

```python
                original_dp_results={
                    "strategic_intent": full_day_strategic_intents
                },  # Store strategic intents
```

to:

```python
                original_dp_results={
                    "strategic_intent": full_day_strategic_intents,
                    "period_data": full_day_period_data,
                },  # Store strategic intents and period data (#320: debounce needs grid_exported)
```

- [ ] **Step 8: Run the fast suite**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS, unchanged pass count

- [ ] **Step 9: Commit**

```bash
git add core/bess/dp_schedule.py core/bess/battery_system_manager.py core/bess/tests/unit/test_dp_schedule.py
git commit -m "feat: plumb PeriodData through DPSchedule.original_dp_results (#320)"
```

---

### Task 8: TOU-flip debounce on `GrowattMinController`

**Files:**
- Modify: `core/bess/growatt_min_controller.py:76-77` (module constant), `:409-441` (`create_schedule`)
- Test: `core/bess/tests/unit/test_growatt_tou_flip_debounce.py` (new)

**Interfaces:**
- Consumes: `DPSchedule.period_data` from Task 7; the real fixture from Task 6.
- Produces: `GrowattMinController._debounce_battery_export_flips(strategic_intents: list[str], period_data: list, tolerance_kwh: float = TOU_FLIP_DEBOUNCE_KWH) -> list[str]`. Used by Task 9 (`SolaxModbusGrowattController`, via inheritance).

- [ ] **Step 1: Write the failing test using the real fixture**

Create `core/bess/tests/unit/test_growatt_tou_flip_debounce.py`:

```python
"""Tests for #320: debouncing isolated, marginal BATTERY_EXPORT flips before
TOU segments are written, using the real 129-period trace that motivated the
issue (core/bess/tests/unit/fixtures/issue_320_period_data.json)."""

import json
from pathlib import Path

import pytest

from core.bess.growatt_min_controller import (
    TOU_FLIP_DEBOUNCE_KWH,
    GrowattMinController,
)
from core.bess.models import DecisionData, EconomicData, EnergyData, PeriodData
from core.bess.tests.helpers import make_battery_settings

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "issue_320_period_data.json"
)


def _load_real_trace() -> list[PeriodData]:
    data = json.loads(FIXTURE_PATH.read_text())
    return [
        PeriodData(
            period=p["period"],
            energy=EnergyData(**p["energy"]),
            economic=EconomicData(**p["economic"]),
            decision=DecisionData(**p["decision"]),
        )
        for p in data
    ]


@pytest.fixture
def controller():
    return GrowattMinController(make_battery_settings(max_discharge_power_kw=5.0))


def test_debounce_folds_all_marginal_isolated_battery_export_periods(controller):
    """Acceptance criterion from the design spec: of the 62 BATTERY_EXPORT
    periods in the real trace, all 31 with grid_exported < 0.05 kWh must be
    folded to LOAD_SUPPORT; the other 31 (genuine exports) must be
    untouched."""
    period_data = _load_real_trace()
    strategic_intents = [p.decision.strategic_intent for p in period_data]

    debounced = controller._debounce_battery_export_flips(
        strategic_intents, period_data
    )

    assert len(debounced) == len(strategic_intents)

    marginal_indices = {
        i
        for i, p in enumerate(period_data)
        if p.decision.strategic_intent == "BATTERY_EXPORT"
        and p.energy.grid_exported < TOU_FLIP_DEBOUNCE_KWH
    }
    non_marginal_indices = {
        i
        for i, p in enumerate(period_data)
        if p.decision.strategic_intent == "BATTERY_EXPORT"
        and p.energy.grid_exported >= TOU_FLIP_DEBOUNCE_KWH
    }
    assert len(marginal_indices) == 31
    assert len(non_marginal_indices) == 31

    for i in marginal_indices:
        assert debounced[i] == "LOAD_SUPPORT", (
            f"period {period_data[i].period} exports "
            f"{period_data[i].energy.grid_exported} kWh (< {TOU_FLIP_DEBOUNCE_KWH}) "
            f"and should have been folded, but is still {debounced[i]}"
        )
    for i in non_marginal_indices:
        assert debounced[i] == "BATTERY_EXPORT", (
            f"period {period_data[i].period} exports "
            f"{period_data[i].energy.grid_exported} kWh (>= {TOU_FLIP_DEBOUNCE_KWH}) "
            f"and should NOT have been folded, but is {debounced[i]}"
        )


def test_debounce_does_not_mutate_input(controller):
    period_data = _load_real_trace()
    strategic_intents = [p.decision.strategic_intent for p in period_data]
    original = list(strategic_intents)
    controller._debounce_battery_export_flips(strategic_intents, period_data)
    assert strategic_intents == original


def test_debounce_leaves_multi_period_export_runs_untouched(controller):
    """A genuine multi-period BATTERY_EXPORT block is not 'isolated' -- it
    must never be folded, even if each individual period's export happens
    to be small."""
    period_data = [
        PeriodData(
            period=i,
            energy=EnergyData(
                solar_production=0.0,
                home_consumption=0.0,
                battery_charged=0.0,
                battery_discharged=0.02,
                grid_imported=0.0,
                grid_exported=0.02,  # below tolerance, but part of a 3-period run
                battery_soe_start=10.0,
                battery_soe_end=9.98,
            ),
            decision=DecisionData(strategic_intent=intent),
        )
        for i, intent in enumerate(
            ["LOAD_SUPPORT", "BATTERY_EXPORT", "BATTERY_EXPORT", "BATTERY_EXPORT", "LOAD_SUPPORT"]
        )
    ]
    strategic_intents = [p.decision.strategic_intent for p in period_data]

    debounced = controller._debounce_battery_export_flips(strategic_intents, period_data)

    assert debounced == strategic_intents, (
        "a 3-period BATTERY_EXPORT run is not isolated and must not be folded, "
        "regardless of each period's individual export volume"
    )


def test_debounce_handles_none_period_data_conservatively(controller):
    """Periods with no PeriodData (e.g. already-elapsed periods before the
    current optimization run) must never be folded -- there's no export
    volume to judge marginality against, so the conservative default is to
    leave them exactly as-is."""
    strategic_intents = ["LOAD_SUPPORT", "BATTERY_EXPORT", "LOAD_SUPPORT"]
    period_data = [None, None, None]

    debounced = controller._debounce_battery_export_flips(strategic_intents, period_data)

    assert debounced == strategic_intents
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_growatt_tou_flip_debounce.py -v`
Expected: FAIL with `ImportError: cannot import name 'TOU_FLIP_DEBOUNCE_KWH' from 'core.bess.growatt_min_controller'`

- [ ] **Step 3: Add the module constant**

In `core/bess/growatt_min_controller.py`, change line 76-77 from:

```python
logger = logging.getLogger(__name__)
```

to:

```python
logger = logging.getLogger(__name__)

# #320: an isolated, single-period BATTERY_EXPORT surrounded by LOAD_SUPPORT
# exporting under this amount is not worth the TOU rewrite it triggers on
# Growatt MIN hardware. A fixed heuristic, not a derived switching-cost
# model -- matches the real trace's own definition of "marginal" (see
# docs/superpowers/specs/2026-07-16-issue-320-platform-capability-abstraction-design.md,
# Roadmap item 3, for making this configurable later).
TOU_FLIP_DEBOUNCE_KWH = 0.05
```

- [ ] **Step 4: Implement `_debounce_battery_export_flips`**

Add this method to `GrowattMinController`, immediately before `def create_schedule(` (currently line 409):

```python
    def _debounce_battery_export_flips(
        self,
        strategic_intents: list[str],
        period_data: list,
        tolerance_kwh: float = TOU_FLIP_DEBOUNCE_KWH,
    ) -> list[str]:
        """Fold isolated, marginal BATTERY_EXPORT periods back to LOAD_SUPPORT.

        An isolated single-period BATTERY_EXPORT surrounded by LOAD_SUPPORT
        on both sides, exporting under `tolerance_kwh`, is not worth the
        real Growatt MIN TOU mode rewrite it would otherwise trigger (#320).
        Runs of two or more consecutive BATTERY_EXPORT periods are never
        folded -- a genuine multi-period export block is not "isolated" by
        construction. Periods whose PeriodData is None (no export volume to
        judge marginality against, e.g. already-elapsed periods) are left
        untouched. Returns a new list; does not mutate `strategic_intents`.
        """
        debounced = list(strategic_intents)
        for i, intent in enumerate(strategic_intents):
            if intent != "BATTERY_EXPORT":
                continue
            prev_is_load_support = (
                i > 0 and strategic_intents[i - 1] == "LOAD_SUPPORT"
            )
            next_is_load_support = (
                i + 1 < len(strategic_intents)
                and strategic_intents[i + 1] == "LOAD_SUPPORT"
            )
            if not (prev_is_load_support and next_is_load_support):
                continue
            pd = period_data[i] if i < len(period_data) else None
            if pd is None:
                continue
            if pd.energy.grid_exported < tolerance_kwh:
                debounced[i] = "LOAD_SUPPORT"
        return debounced

```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_growatt_tou_flip_debounce.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Call the debounce from `create_schedule`**

Change `create_schedule` (currently lines 409-425) from:

```python
    def create_schedule(
        self,
        schedule: DPSchedule,
        current_period: int = 0,
        previous_tou_intervals: list[dict] | None = None,
    ):
        """Process DPSchedule with strategic intents into Growatt MIN format."""
        logger.info(
            "Creating Growatt schedule using strategic intents from DP algorithm"
        )

        # Always use strategic intents from DP algorithm - no fallbacks
        self.strategic_intents = schedule.original_dp_results["strategic_intent"]

        logger.info(
            f"Using {len(self.strategic_intents)} strategic intents from DP algorithm (quarterly resolution)"
        )
```

to:

```python
    def create_schedule(
        self,
        schedule: DPSchedule,
        current_period: int = 0,
        previous_tou_intervals: list[dict] | None = None,
    ):
        """Process DPSchedule with strategic intents into Growatt MIN format."""
        logger.info(
            "Creating Growatt schedule using strategic intents from DP algorithm"
        )

        # Always use strategic intents from DP algorithm - no fallbacks
        raw_strategic_intents = schedule.original_dp_results["strategic_intent"]
        # #320: fold isolated, marginal BATTERY_EXPORT flips before any TOU
        # grouping happens, so _groups_to_tou_intervals never sees them.
        self.strategic_intents = self._debounce_battery_export_flips(
            raw_strategic_intents, schedule.period_data
        )

        logger.info(
            f"Using {len(self.strategic_intents)} strategic intents from DP algorithm (quarterly resolution)"
        )
```

- [ ] **Step 7: Run the fast suite**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS. Existing `test_growatt_tou_scheduling.py` tests set `scheduler.strategic_intents` directly and call `_consolidate_and_convert_with_strategic_intents()` without going through `create_schedule`, so they are unaffected by this change — confirm this is still true by checking the diff touches only `create_schedule`, not `_consolidate_and_convert_with_strategic_intents` or `_groups_to_tou_intervals`.

- [ ] **Step 8: Write an integration test confirming `create_schedule` actually calls the debounce**

Add to `core/bess/tests/unit/test_growatt_tou_flip_debounce.py`:

```python
def test_create_schedule_applies_the_debounce(controller):
    """Integration check: create_schedule must route through
    _debounce_battery_export_flips, not just have the method exist
    unused."""
    from core.bess.dp_schedule import DPSchedule

    period_data = [
        _pd(0, "LOAD_SUPPORT", 0.0),
        _pd(1, "BATTERY_EXPORT", 0.02),  # isolated + marginal -> should fold
        _pd(2, "LOAD_SUPPORT", 0.0),
    ] + [_pd(i, "IDLE", 0.0) for i in range(3, 96)]
    strategic_intents = [p.decision.strategic_intent for p in period_data]

    schedule = DPSchedule(
        actions=[0.0] * 96,
        state_of_energy=[10.0] * 96,
        prices=[0.3] * 96,
        original_dp_results={
            "strategic_intent": strategic_intents,
            "period_data": period_data,
        },
    )
    controller.create_schedule(schedule, current_period=0)
    assert controller.strategic_intents[1] == "LOAD_SUPPORT"
```

Add the small helper this test needs at the top of the file (near `_load_real_trace`):

```python
def _pd(period: int, intent: str, grid_exported: float) -> PeriodData:
    return PeriodData(
        period=period,
        energy=EnergyData(
            solar_production=0.0,
            home_consumption=0.0,
            battery_charged=0.0,
            battery_discharged=grid_exported,
            grid_imported=0.0,
            grid_exported=grid_exported,
            battery_soe_start=10.0,
            battery_soe_end=10.0 - grid_exported,
        ),
        decision=DecisionData(strategic_intent=intent),
    )
```

- [ ] **Step 9: Run test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_growatt_tou_flip_debounce.py -v`
Expected: PASS (5 passed)

- [ ] **Step 10: Run the fast and slow suites**

Run: `.venv/bin/pytest -m "not slow"`
Run: `.venv/bin/pytest -m slow`
Expected: PASS both

- [ ] **Step 11: Commit**

```bash
git add core/bess/growatt_min_controller.py core/bess/tests/unit/test_growatt_tou_flip_debounce.py
git commit -m "feat: debounce isolated marginal BATTERY_EXPORT flips on Growatt MIN (#320)"
```

---

### Task 9: Wire the debounce into `SolaxModbusGrowattController`

**Files:**
- Modify: `core/bess/solax_modbus_growatt_controller.py:61-101` (`create_schedule`)
- Test: `core/bess/tests/unit/test_solax_modbus_growatt_single_segment.py` (existing file, add test)

**Interfaces:**
- Consumes: `GrowattMinController._debounce_battery_export_flips` (inherited, Task 8).

- [ ] **Step 1: Read the existing test file's construction pattern**

Run: `sed -n '1,40p' core/bess/tests/unit/test_solax_modbus_growatt_single_segment.py`

Use whatever fixture/helper pattern it already uses for constructing a `SolaxModbusGrowattController` and a minimal `DPSchedule` — match that style in the new test below rather than introducing a second construction pattern.

- [ ] **Step 2: Write the failing test**

Append to `core/bess/tests/unit/test_solax_modbus_growatt_single_segment.py` (adjust the fixture/import names to match whatever Step 1 found):

```python
def test_create_schedule_applies_the_debounce():
    """#320: SolaxModbusGrowattController overrides create_schedule and
    skips GrowattMinController's batch TOU grouping entirely, so it must
    call the inherited debounce itself -- it does not get it for free just
    by being a subclass."""
    from core.bess.dp_schedule import DPSchedule
    from core.bess.models import DecisionData, EnergyData, PeriodData
    from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController
    from core.bess.tests.helpers import make_battery_settings

    def _pd(period, intent, grid_exported):
        return PeriodData(
            period=period,
            energy=EnergyData(
                solar_production=0.0,
                home_consumption=0.0,
                battery_charged=0.0,
                battery_discharged=grid_exported,
                grid_imported=0.0,
                grid_exported=grid_exported,
                battery_soe_start=10.0,
                battery_soe_end=10.0 - grid_exported,
            ),
            decision=DecisionData(strategic_intent=intent),
        )

    period_data = [
        _pd(0, "LOAD_SUPPORT", 0.0),
        _pd(1, "BATTERY_EXPORT", 0.02),  # isolated + marginal -> should fold
        _pd(2, "LOAD_SUPPORT", 0.0),
    ] + [_pd(i, "IDLE", 0.0) for i in range(3, 96)]
    strategic_intents = [p.decision.strategic_intent for p in period_data]

    schedule = DPSchedule(
        actions=[0.0] * 96,
        state_of_energy=[10.0] * 96,
        prices=[0.3] * 96,
        original_dp_results={
            "strategic_intent": strategic_intents,
            "period_data": period_data,
        },
    )
    controller = SolaxModbusGrowattController(
        make_battery_settings(max_discharge_power_kw=5.0)
    )
    controller.create_schedule(schedule, current_period=0)
    assert controller.strategic_intents[1] == "LOAD_SUPPORT"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_solax_modbus_growatt_single_segment.py::test_create_schedule_applies_the_debounce -v`
Expected: FAIL — `controller.strategic_intents[1]` is still `"BATTERY_EXPORT"` (the override doesn't call the debounce yet)

- [ ] **Step 4: Call the debounce in the override**

In `core/bess/solax_modbus_growatt_controller.py`, change `create_schedule` (currently lines 61-85) from:

```python
    def create_schedule(
        self,
        schedule: DPSchedule,
        current_period: int = 0,
        previous_tou_intervals: list[dict] | None = None,
    ) -> None:
        """Store strategic intents — TOU mode is applied per-period, no batch TOU needed.

        Skips the parent's 9-segment TOU interval computation.  Strategic intents
        are stored and hourly settings calculated for API/display consumption.

        Args:
            schedule: DPSchedule containing strategic_intent list.
            current_period: Current 15-minute period (0-95).
            previous_tou_intervals: Unused for single-segment approach.
        """
        logger.info("Creating Modbus single-segment schedule from strategic intents")

        self.strategic_intents = schedule.original_dp_results["strategic_intent"]
        self.current_schedule = schedule
```

to:

```python
    def create_schedule(
        self,
        schedule: DPSchedule,
        current_period: int = 0,
        previous_tou_intervals: list[dict] | None = None,
    ) -> None:
        """Store strategic intents — TOU mode is applied per-period, no batch TOU needed.

        Skips the parent's 9-segment TOU interval computation.  Strategic intents
        are stored and hourly settings calculated for API/display consumption.

        Args:
            schedule: DPSchedule containing strategic_intent list.
            current_period: Current 15-minute period (0-95).
            previous_tou_intervals: Unused for single-segment approach.
        """
        logger.info("Creating Modbus single-segment schedule from strategic intents")

        raw_strategic_intents = schedule.original_dp_results["strategic_intent"]
        # #320: same Growatt MIN hardware as the cloud path (this class
        # subclasses GrowattMinController) -- an isolated marginal
        # BATTERY_EXPORT still triggers a real per-period TOU mode write
        # via apply_period below, so it needs the same debounce, applied
        # explicitly since this override skips the parent's create_schedule.
        self.strategic_intents = self._debounce_battery_export_flips(
            raw_strategic_intents, schedule.period_data
        )
        self.current_schedule = schedule
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_solax_modbus_growatt_single_segment.py -v`
Expected: PASS (all tests in the file, including the new one)

- [ ] **Step 6: Run the fast suite**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add core/bess/solax_modbus_growatt_controller.py core/bess/tests/unit/test_solax_modbus_growatt_single_segment.py
git commit -m "feat: apply the same TOU-flip debounce to SolaxModbusGrowattController (#320)"
```

---

### Task 10: Exclusion tests for `GrowattSphController` and `SolaxController`

**Files:**
- Test: `core/bess/tests/unit/test_growatt_sph_no_debounce.py` (new), `core/bess/tests/unit/test_solax_controller.py` (existing file, add test)

**Interfaces:**
- Consumes: nothing new — confirms `GrowattSphController` and `SolaxController` do not call `_debounce_battery_export_flips` (they don't inherit from `GrowattMinController`, so the method doesn't even exist on them — this test guards against someone adding it there later by mistake, per the spec's Non-goals).

- [ ] **Step 1: Write the exclusion tests**

Create `core/bess/tests/unit/test_growatt_sph_no_debounce.py`:

```python
"""#320: GrowattSphController must NOT have the TOU-flip debounce -- it
already collapses LOAD_SUPPORT/BATTERY_EXPORT into one undifferentiated
discharge block (DISCHARGE_INTENTS), so it has no per-period mode-flip cost
to avoid. Applying the debounce there would be actively wrong, not merely
unnecessary (see design spec's Non-goals)."""

from core.bess.growatt_sph_controller import GrowattSphController
from core.bess.tests.helpers import make_battery_settings


def test_sph_controller_has_no_debounce_method():
    controller = GrowattSphController(make_battery_settings())
    assert not hasattr(controller, "_debounce_battery_export_flips")
```

Add to `core/bess/tests/unit/test_solax_controller.py` (check its existing imports first with `head -20 core/bess/tests/unit/test_solax_controller.py` and reuse whatever `make_battery_settings`-equivalent it already imports):

```python
def test_solax_controller_has_no_debounce_method():
    """#320: SolaxController (true SolaX VPP hardware) has no mode concept
    at all, so there is no per-period TOU-flip cost to debounce."""
    controller = SolaxController(make_battery_settings())
    assert not hasattr(controller, "_debounce_battery_export_flips")
```

- [ ] **Step 2: Run both tests to verify they pass immediately**

Run: `.venv/bin/pytest core/bess/tests/unit/test_growatt_sph_no_debounce.py core/bess/tests/unit/test_solax_controller.py::test_solax_controller_has_no_debounce_method -v`
Expected: PASS (2 passed) — these should pass without any implementation change, since the debounce was only ever added to `GrowattMinController` in Task 8. This is a guard test, not a red/green TDD cycle: it exists to fail loudly if a future change accidentally moves the debounce onto a shared ancestor of these classes.

- [ ] **Step 3: Run the full fast and slow suites one final time**

Run: `.venv/bin/pytest -m "not slow"`
Run: `.venv/bin/pytest -m slow`
Expected: PASS both — this is the final full-suite confirmation before code review.

- [ ] **Step 4: Commit**

```bash
git add core/bess/tests/unit/test_growatt_sph_no_debounce.py core/bess/tests/unit/test_solax_controller.py
git commit -m "test: guard that TOU-flip debounce never reaches SPH/SolaX controllers (#320)"
```

---

## After all tasks: update CHANGELOG.md

Per `docs/agents/workflow.md`, add an entry under `## [Unreleased]` → `### Fixed` in `CHANGELOG.md` before opening the PR:

```markdown
- **Fixed unnecessary Growatt MIN TOU mode flips for marginal battery exports** ([#320](https://github.com/johanzander/bess-manager/issues/320)). The DP's discharge-candidate resolution and self-throttle threshold are now per-platform capabilities (behavior-preserving refactor) instead of hardcoded Growatt assumptions, and an isolated, economically negligible `BATTERY_EXPORT` period surrounded by `LOAD_SUPPORT` no longer triggers a real inverter TOU rewrite.
```

This is not a version bump — do not touch `bess_manager/config.yaml`.
