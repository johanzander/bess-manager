# Discharge Rate Display Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix Schedule Overview showing D: 100% for all discharge intents, and add an "Inhibited" badge to the Battery Settings card when the EV discharge inhibit is active.

**Architecture:** Two independent changes. Task 1 fixes the backend period group computation to use action-derived rates. Task 2 adds `dischargeInhibitActive` to the status API and wires it to the frontend card.

**Tech Stack:** Python (FastAPI backend), TypeScript/React (frontend), pytest, Tailwind CSS.

## Global Constraints

- No fallbacks: if data is missing, produce 0, never read from static table as a fallback
- No silent degradation: if `current_schedule` is None, discharge_rate is 0 — not 100
- Follow rules.md: no speculative error handling, no defensive shims
- Test commands: `.venv/bin/pytest -m "not slow"` (fast tests); `cd frontend && npm run build` (TS check)

---

## Task 1: Fix action-derived discharge rate in `get_detailed_period_groups()`

**Files:**
- Modify: `core/bess/inverter_controller.py` — `get_detailed_period_groups()` method
- Modify: `backend/api.py` — tomorrow period groups call site (pass actions alongside intents)
- Test: `core/bess/tests/unit/test_period_groups.py` (new file)

**Interfaces:**
- Produces: `get_detailed_period_groups(intents=None, actions=None)` — `actions: list[float] | None` is kWh per period (positive=charge, negative=discharge); when provided, overrides reading from `self.current_schedule.actions`
- Produces: `discharge_rate` in each returned dict is now action-derived (0–100), not always 100

- [ ] **Step 1: Write the failing tests**

Create `core/bess/tests/unit/test_period_groups.py`:

```python
"""Tests for get_detailed_period_groups() discharge rate computation."""

import pytest

from core.bess.growatt_min_controller import GrowattMinController
from core.bess.dp_schedule import DPSchedule
from core.bess.settings import BatterySettings


@pytest.fixture
def settings():
    return BatterySettings(
        total_capacity=30.0,
        max_charge_power_kw=6.0,
        max_discharge_power_kw=6.0,
        min_soc=10.0,
        max_soc=95.0,
        cycle_cost_per_kwh=0.05,
    )


@pytest.fixture
def controller(settings):
    return GrowattMinController(settings)


def _make_schedule(actions: list[float]) -> DPSchedule:
    n = len(actions)
    return DPSchedule(
        actions=actions,
        state_of_energy=[20.0] * n,
        prices=[2.0] * n,
    )


class TestDischargeRateFromSchedule:
    def test_export_arbitrage_uses_action_derived_rate(self, controller):
        """EXPORT_ARBITRAGE discharge_rate reflects actual battery action, not 100%."""
        # -0.9 kWh / 0.25 h = -3.6 kW; 3.6 / 6.0 * 100 = 60%
        intents = ["IDLE"] * 96
        intents[20] = "EXPORT_ARBITRAGE"
        intents[21] = "EXPORT_ARBITRAGE"
        intents[22] = "EXPORT_ARBITRAGE"
        intents[23] = "EXPORT_ARBITRAGE"

        actions = [0.0] * 96
        actions[20] = -0.9
        actions[21] = -0.9
        actions[22] = -0.9
        actions[23] = -0.9

        controller.strategic_intents = intents
        controller.current_schedule = _make_schedule(actions)

        groups = controller.get_detailed_period_groups()

        export_group = next(g for g in groups if g["intent"] == "EXPORT_ARBITRAGE")
        assert export_group["discharge_rate"] == 60  # round(3.6/6.0*100)

    def test_no_schedule_gives_zero_rate(self, controller):
        """With no current_schedule, discharge_rate is 0 (no fallback to static 100)."""
        intents = ["IDLE"] * 96
        intents[20] = "EXPORT_ARBITRAGE"

        controller.strategic_intents = intents
        controller.current_schedule = None

        groups = controller.get_detailed_period_groups()

        export_group = next(g for g in groups if g["intent"] == "EXPORT_ARBITRAGE")
        assert export_group["discharge_rate"] == 0

    def test_actions_parameter_overrides_schedule(self, controller):
        """Explicit actions parameter takes precedence over current_schedule."""
        intents = ["EXPORT_ARBITRAGE"] * 4  # four 15-min periods = 1 hour

        # schedule has 0.9 kWh (would give 60%), but we pass 0.45 kWh (should give 30%)
        controller.current_schedule = _make_schedule([-0.9] * 4)

        groups = controller.get_detailed_period_groups(
            intents=intents,
            actions=[-0.45, -0.45, -0.45, -0.45],
        )

        assert len(groups) == 1
        # 0.45 / 0.25 = 1.8 kW; round(1.8 / 6.0 * 100) = 30
        assert groups[0]["discharge_rate"] == 30

    def test_load_support_uses_action_derived_rate(self, controller):
        """LOAD_SUPPORT discharge_rate reflects action, not 100%."""
        intents = ["IDLE"] * 96
        intents[18] = "LOAD_SUPPORT"
        intents[19] = "LOAD_SUPPORT"
        intents[20] = "LOAD_SUPPORT"
        intents[21] = "LOAD_SUPPORT"

        actions = [0.0] * 96
        # -0.3 kWh / 0.25 h = -1.2 kW; round(1.2 / 6.0 * 100) = 20
        actions[18] = -0.3
        actions[19] = -0.3
        actions[20] = -0.3
        actions[21] = -0.3

        controller.strategic_intents = intents
        controller.current_schedule = _make_schedule(actions)

        groups = controller.get_detailed_period_groups()
        ls_group = next(g for g in groups if g["intent"] == "LOAD_SUPPORT")
        assert ls_group["discharge_rate"] == 20

    def test_idle_always_zero(self, controller):
        """IDLE periods always produce discharge_rate=0 regardless of schedule."""
        intents = ["IDLE"] * 4
        actions = [-0.9] * 4  # would produce non-zero rate for discharge intents

        controller.strategic_intents = intents
        controller.current_schedule = _make_schedule(actions)

        groups = controller.get_detailed_period_groups()
        assert len(groups) == 1
        assert groups[0]["discharge_rate"] == 0

    def test_different_rates_split_into_separate_groups(self, controller):
        """Consecutive EXPORT_ARBITRAGE periods with different rates form separate groups."""
        intents = ["EXPORT_ARBITRAGE"] * 8
        actions = [-0.9] * 4 + [-0.45] * 4  # 60% then 30%

        controller.strategic_intents = intents
        controller.current_schedule = _make_schedule(actions)

        groups = controller.get_detailed_period_groups()
        assert len(groups) == 2
        assert groups[0]["discharge_rate"] == 60
        assert groups[1]["discharge_rate"] == 30
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest core/bess/tests/unit/test_period_groups.py -v
```

Expected: all 6 tests FAIL (ImportError or assertion errors against current behaviour).

- [ ] **Step 3: Implement the fix in `get_detailed_period_groups()`**

In `core/bess/inverter_controller.py`, replace the `get_detailed_period_groups` method signature and body:

```python
def get_detailed_period_groups(
    self, intents: list[str] | None = None, actions: list[float] | None = None
) -> list[dict]:
    """Get period groups with full control parameters for display/API.

    Groups consecutive 15-minute periods ONLY when ALL parameters are identical:
    strategic intent, battery mode, grid charge, charge rate, and discharge rate.

    Args:
        intents: Optional list of strategic intents to group. If None,
                 uses self.strategic_intents (today's schedule).
        actions: Optional list of battery actions in kWh per period (negative=discharge).
                 If None, reads from self.current_schedule.actions. If current_schedule
                 is also None or the period is out of range, action defaults to 0.0.

    Returns:
        List of period groups with all control parameters and time strings
    """
    effective_intents = intents if intents is not None else self.strategic_intents
    if not effective_intents:
        return []

    num_periods = len(effective_intents)

    schedule_actions: list[float] | None = None
    if actions is not None:
        schedule_actions = actions
    elif self.current_schedule is not None:
        schedule_actions = self.current_schedule.actions

    period_settings = []
    for period in range(num_periods):
        intent = effective_intents[period]
        mode = self.INTENT_TO_MODE.get(intent, "load_first")
        control = self.INTENT_TO_CONTROL.get(
            intent,
            {"grid_charge": False, "charge_rate": 100, "discharge_rate": 0},
        )

        action_kwh = 0.0
        if schedule_actions is not None and period < len(schedule_actions):
            action_kwh = schedule_actions[period]
        action_kw = action_kwh / 0.25

        _, discharge_rate = self._map_intent_to_rates(intent, action_kw)

        period_settings.append(
            {
                "period": period,
                "intent": intent,
                "mode": mode,
                "grid_charge": control["grid_charge"],
                "charge_rate": control["charge_rate"],
                "discharge_rate": discharge_rate,
            }
        )

    groups = []
    current_group: dict | None = None

    for ps in period_settings:
        if current_group is not None and (
            ps["intent"] == current_group["intent"]
            and ps["mode"] == current_group["mode"]
            and ps["grid_charge"] == current_group["grid_charge"]
            and ps["charge_rate"] == current_group["charge_rate"]
            and ps["discharge_rate"] == current_group["discharge_rate"]
        ):
            current_group["end_period"] = ps["period"]
            current_group["count"] += 1
        else:
            if current_group is not None:
                groups.append(current_group)
            current_group = {
                "start_period": ps["period"],
                "end_period": ps["period"],
                "intent": ps["intent"],
                "mode": ps["mode"],
                "grid_charge": ps["grid_charge"],
                "charge_rate": ps["charge_rate"],
                "discharge_rate": ps["discharge_rate"],
                "count": 1,
            }

    if current_group is not None:
        groups.append(current_group)

    result = []
    for group in groups:
        start_h, start_m = self._period_to_time(group["start_period"])
        end_h, end_m = self._period_to_time(group["end_period"])
        end_m += 14
        if end_h >= 24:
            end_h = 23
            end_m = 59
        result.append(
            {
                "start_time": f"{start_h:02d}:{start_m:02d}",
                "end_time": f"{end_h:02d}:{end_m:02d}",
                "start_period": group["start_period"],
                "end_period": group["end_period"],
                "intent": group["intent"],
                "mode": group["mode"],
                "grid_charge": group["grid_charge"],
                "charge_rate": group["charge_rate"],
                "discharge_rate": group["discharge_rate"],
                "period_count": group["count"],
                "duration_minutes": group["count"] * 15,
            }
        )
    return result
```

- [ ] **Step 4: Pass tomorrow's actions in api.py**

In `backend/api.py`, find the block starting around line 1630 that builds `tomorrow_intents` and calls `get_detailed_period_groups(intents=tomorrow_intents)`. Add a parallel list for tomorrow's actions:

```python
tomorrow_intents: list[str] = []
tomorrow_actions: list[float] = []
for period_idx in range(
    today_period_count,
    today_period_count + tomorrow_period_count,
):
    data_idx = period_idx - period_data_anchor
    if 0 <= data_idx < len(opt_result.period_data):
        pd = opt_result.period_data[data_idx]
        tomorrow_intents.append(
            pd.decision.strategic_intent
        )
        tomorrow_actions.append(
            pd.decision.battery_action or 0.0
        )
if tomorrow_intents:
    raw_tomorrow_groups = schedule_manager.get_detailed_period_groups(
        intents=tomorrow_intents,
        actions=tomorrow_actions,
    )
```

- [ ] **Step 5: Run tests — all should pass**

```bash
.venv/bin/pytest core/bess/tests/unit/test_period_groups.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 6: Run full fast suite to check for regressions**

```bash
.venv/bin/pytest -m "not slow" -x -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add core/bess/inverter_controller.py backend/api.py core/bess/tests/unit/test_period_groups.py
git commit -m "fix: use action-derived discharge rate in period group display

get_detailed_period_groups() was reading discharge_rate from the static
INTENT_TO_CONTROL table (always 100 for EXPORT_ARBITRAGE/LOAD_SUPPORT).
Now computes it via _map_intent_to_rates() using the per-period battery
action from current_schedule.actions, matching what _apply_period_schedule
writes to hardware. Also adds actions= parameter for tomorrow's groups.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Expose discharge inhibit in status API and Battery Settings card

**Files:**
- Modify: `backend/api.py` — `/api/inverter/status` route, add `discharge_inhibit_active`
- Modify: `frontend/src/components/InverterStatusDashboard.tsx` — `StatusCard` metric type, `InverterStatus` interface, Battery Settings card wiring

**Interfaces:**
- Consumes: `controller.get_discharge_inhibit_active() -> bool` (already exists in `HAApiController`)
- Produces: `GET /api/inverter/status` response includes `dischargeInhibitActive: boolean`
- Produces: `StatusCard` metric items accept optional `dimmed?: boolean` and `badge?: { text: string; color: 'yellow' | 'red' }`

- [ ] **Step 1: Add `discharge_inhibit_active` to the status endpoint**

In `backend/api.py`, in the `/api/inverter/status` route handler, find the `response` dict (around line 1430). Add one entry alongside the others:

```python
response = {
    "battery_soc": battery_soc,
    "battery_soe": battery_soe,
    "battery_charge_power": battery_charge_power,
    "battery_discharge_power": battery_discharge_power,
    "battery_mode": current_battery_mode,
    "grid_charge_enabled": grid_charge_enabled,
    "charge_stop_soc": battery_settings.max_soc,
    "discharge_stop_soc": battery_settings.min_soc,
    "discharge_power_rate": discharge_power_rate,
    "discharge_inhibit_active": controller.get_discharge_inhibit_active(),
    "inverter_platform": inverter_platform,
    "timestamp": datetime.now().isoformat(),
}
```

`convert_keys_to_camel_case(response)` (called on the next line) will produce `dischargeInhibitActive` in the JSON.

- [ ] **Step 2: Verify API change with a quick curl (manual)**

With the dev stack running (`docker-compose up -d`):

```bash
curl -s http://localhost:8099/api/inverter/status | python3 -m json.tool | grep -i inhibit
```

Expected output: `"dischargeInhibitActive": false` (or `true` if EV is charging).

- [ ] **Step 3: Extend `StatusCard` metric type and render**

In `frontend/src/components/InverterStatusDashboard.tsx`, update the `StatusCardProps` metrics array item type (around line 107):

```typescript
metrics: Array<{
  label: string;
  value: number | string;
  unit: string;
  icon?: React.ComponentType<{ className?: string }>;
  color?: 'green' | 'red' | 'yellow' | 'blue';
  dimmed?: boolean;
  badge?: { text: string; color: 'yellow' | 'red' };
}>;
```

In the `StatusCard` render, replace the metric row (around line 194) with:

```tsx
{metrics.map((metric, index) => (
  <div
    key={index}
    className={`flex items-center justify-between ${metric.dimmed ? 'opacity-40' : ''}`}
  >
    <div className="flex items-center">
      {metric.icon && <metric.icon className="h-4 w-4 mr-2 text-gray-500 dark:text-gray-400" />}
      <span className="text-sm text-gray-700 dark:text-gray-300">{metric.label}</span>
    </div>
    <div className="flex items-center gap-2">
      {metric.badge && (
        <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${
          metric.badge.color === 'yellow'
            ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400'
            : 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
        }`}>
          {metric.badge.text}
        </span>
      )}
      <span className={`text-sm font-semibold ${
        metric.color ? metricColorClasses[metric.color] : 'text-gray-900 dark:text-gray-100'
      }`}>
        {metric.value}
        {metric.unit && <span className="opacity-70 ml-1">{metric.unit}</span>}
      </span>
    </div>
  </div>
))}
```

- [ ] **Step 4: Add `dischargeInhibitActive` to `InverterStatus` interface**

In `InverterStatusDashboard.tsx`, update the `InverterStatus` interface (around line 18):

```typescript
interface InverterStatus {
  batterySoc: number;
  batterySoe: number;
  batteryChargePower: number;
  batteryDischargePower: number;
  pvPower: number;
  consumption: number;
  gridPower: number;
  chargeStopSoc: number;
  dischargeStopSoc: number;
  dischargePowerRate: number;
  dischargeInhibitActive?: boolean;
  maxChargingPower: number;
  maxDischargingPower: number;
  gridChargeEnabled: boolean;
  cycleCost: number;
  systemStatus: string;
  lastUpdated: string;
  inverterPlatform?: string;
  batterySoeCapacityFormatted?: string;
}
```

- [ ] **Step 5: Wire inhibit to Discharge Power Rate metric**

In `InverterStatusDashboard.tsx`, find the Battery Settings `StatusCard` metrics array (around line 654). Replace the Discharge Power Rate entry:

```typescript
{
  label: "Discharge Power Rate",
  value: inverterStatus?.dischargePowerRate || 0,
  unit: "%",
  icon: TrendingDown,
  dimmed: inverterStatus?.dischargeInhibitActive,
  badge: inverterStatus?.dischargeInhibitActive
    ? { text: 'Inhibited', color: 'yellow' as const }
    : undefined,
},
```

- [ ] **Step 6: TypeScript build check**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: build succeeds with no TypeScript errors.

- [ ] **Step 7: Run fast backend tests**

```bash
.venv/bin/pytest -m "not slow" -x -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add backend/api.py frontend/src/components/InverterStatusDashboard.tsx
git commit -m "feat: show discharge inhibit badge in Battery Settings card

Adds dischargeInhibitActive to /api/inverter/status response.
When active, the Discharge Power Rate row in the Battery Settings
card dims and shows an amber 'Inhibited' pill, making it clear
the 0% rate is intentional EV-charging suppression.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```
