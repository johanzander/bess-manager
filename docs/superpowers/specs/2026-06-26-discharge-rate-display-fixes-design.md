# Discharge Rate Display Fixes — Design Spec

**Date:** 2026-06-26  
**Status:** Approved

## Problem

Two display inaccuracies on the dashboard:

1. **Schedule Overview always shows D: 100% for EXPORT_ARBITRAGE.** The period group computation reads from the static `INTENT_TO_CONTROL` table, which hardcodes 100 for that intent. The optimizer's actual per-period battery action (e.g. -0.9 kWh → 30% of max power) is ignored.

2. **Battery Settings card shows 0% discharge rate with no explanation.** When a discharge inhibit sensor is active (e.g. EV charging), `_apply_period_schedule` forces the hardware rate to 0% but the card shows "0 %" with no indication that this is intentional suppression.

---

## Fix 1 — Schedule Overview: action-derived discharge rate

### Scope

`core/bess/inverter_controller.py` — `get_detailed_period_groups()` only.

### What changes

Replace the static-table lookup for `discharge_rate` with a call to `_map_intent_to_rates(intent, battery_action_kw)` using the actual battery action for that period from `self.current_schedule.actions[period]`.

**Conversion:** `battery_action_kw = actions[period] / 0.25` (each period is 15 min = 0.25 h). The action value is already in kWh.

**No fallback:** if `self.current_schedule` is `None`, or `period >= len(self.current_schedule.actions)`, `battery_action_kw = 0.0` — which correctly produces `discharge_rate = 0` via `_map_intent_to_rates`. The static table is not consulted.

### Side effect on grouping

The existing grouping logic (`discharge_rate == current_group["discharge_rate"]`) will now split consecutive EXPORT_ARBITRAGE periods that have different discharge rates. This is correct behaviour — each rate should be its own group.

### No API changes

The existing `discharge_power_rate` field on period group objects already carries this value to the frontend. No frontend changes needed for this fix.

---

## Fix 2 — Battery Settings card: discharge inhibit badge

### Backend

**File:** `backend/api.py`, route `/api/inverter/status`

Add one field to the response dict:

```python
"discharge_inhibit_active": controller.get_discharge_inhibit_active(),
```

`get_discharge_inhibit_active()` already exists on `HAApiController` and returns `False` when the sensor is not configured — so this is always safe to call.

After `convert_keys_to_camel_case` this becomes `dischargeInhibitActive` in the JSON response.

### Frontend — `StatusCard` extension

**File:** `frontend/src/components/InverterStatusDashboard.tsx`

Extend the metric item type in `StatusCardProps`:

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

Update the metric row render in `StatusCard` to:
- Apply `opacity-40` to the entire row when `metric.dimmed` is true
- Render a small pill (`px-1.5 py-0.5 rounded text-xs font-medium`) to the left of the value when `metric.badge` is set, using amber/yellow colours for `'yellow'` and red for `'red'`

### Frontend — Battery Settings card wiring

**File:** `frontend/src/components/InverterStatusDashboard.tsx`

- Add `dischargeInhibitActive?: boolean` to the `InverterStatus` interface
- On the Discharge Power Rate metric entry, set `dimmed` and `badge` conditionally:

```typescript
{
  label: "Discharge Power Rate",
  value: inverterStatus?.dischargePowerRate || 0,
  unit: "%",
  icon: TrendingDown,
  dimmed: inverterStatus?.dischargeInhibitActive,
  badge: inverterStatus?.dischargeInhibitActive
    ? { text: 'Inhibited', color: 'yellow' }
    : undefined,
}
```

---

## What is NOT changing

- The discharge inhibit logic in `_apply_period_schedule` — it works correctly
- The Schedule Overview does not show inhibit state (it shows the planned rate regardless of current live inhibit)
- No new API endpoints
- No changes to other inverter controller subclasses (fix 1 is in the base class)

---

## Files touched

| File | Change |
|------|--------|
| `core/bess/inverter_controller.py` | `get_detailed_period_groups()`: use action-derived rate |
| `backend/api.py` | `/api/inverter/status`: add `discharge_inhibit_active` |
| `frontend/src/components/InverterStatusDashboard.tsx` | `StatusCard` metric: `dimmed`/`badge`; `InverterStatus`: `dischargeInhibitActive`; Battery Settings wiring |
