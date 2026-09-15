# Design: Octopus Power Down sessions, a guaranteed export pulse

**Date**: 2026-09-13
**Status**: Proposed. Not implemented. **Depends on**
`2026-09-13-octopus-power-up-price-overlay-design.md` for the calendar read
path (`_get_calendar_windows`, `CalendarWindow`), so it lands second.
**Related**: #429 (house-fuse import cap: the "constrain, don't raise"
candidate filter this design copies), #352 (closed; `grid_first` at a
sub-load rate imports the shortfall), P1/P3 in
`docs/agents/optimizer-architecture.md` (one candidate selector; candidates
are executable commands).

## Problem

A Power Down session (Octopus `TURN_DOWN`, formerly a Saving Session) is a
joined window, usually one evening hour. Octoplus scores it against a
baseline built from your recent consumption in the same window. **Two
completed sessions earn one Weekend Happy Hour**: a free hour, modelled by
the companion spec.

BESS doesn't know sessions exist. On a solar + battery home the evening peak
is usually covered from the battery anyway, so import is already near zero.
But nothing *guarantees* a measurable reduction against the baseline, and
nothing stops the DP from scheduling grid charging, or a low-rate
`BATTERY_EXPORT` that imports the shortfall (#352), inside a session.

The requested behavior: **during each joined Power Down session, BESS
schedules a short battery export, 15 minutes by default**, and doesn't plan
grid import in the window. The rest of the day is optimized knowing that
export is coming, instead of a Home Assistant automation overriding the
inverter behind BESS's back.

## Evidence so far, read before building this

This comes from one install (Growatt MIN, Agile import, flat 12p export).
Session outcomes are from the integration's
`event.…_octoplus_power_down_events` `joined_events[].rewarded_octopoints`;
flows are from the HA recorder.

| Session | Import kWh | Export kWh | Octopoints |
|---|---|---|---|
| 1 Sep 18:00-19:00 | 0.000 | 0.000 | 16 |
| 2 Sep 20:00-21:00 | 0.000 | 0.004 | **0** |
| 3 Sep 18:00-19:00 | 0.000 | 0.148 | 16 |
| 7 Sep 18:00-19:00 | 0.000 | 0.074 | **0** |
| 11 Sep 19:00-20:00 | — | — | not yet scored |

A Happy Hour was then granted and booked for 13 Sep, which fits 1 and 3 Sep
being the two completed sessions.

**What this does and doesn't show.**

- Import was zero in every session, scored or not, so import alone didn't
  decide the outcome.
- Export isn't clearly the deciding factor either:
  - 1 Sep scored with no export.
  - 7 Sep exported half as much as 3 Sep and scored nothing.
- Both scored sessions paid exactly 16 points at different points-per-kWh
  rates, which looks like a flat completion award rather than a per-kWh
  saving.

The hypothesis behind this feature is that exporting during the window
improves the chance a session counts as completed. It's plausible, because
export offsets import on the settlement meter, **but it isn't established**.

So the feature ships **disabled by default**, with the export size
configurable, and with outcome logging (section 6) so the hypothesis gets
tested on real sessions before anyone recommends turning it on.

## Design

### 1. Session windows

- New `METHOD_SENSOR_MAP` entry `get_power_down_windows`, sensor key
  `octoplus_power_down_calendar`. It's a thin wrapper over the
  `_get_calendar_windows` helper from the companion spec.
- Entity: `calendar.octopus_energy_{account}_octoplus_power_down` (unique_id
  `octopus_energy_{ACCOUNT}_octoplus_power_down`).
  - Don't use `…_octoplus_saving_sessions`. It returns identical events
    today, but it's the deprecated name.
  - Verified live: `GET /api/calendars/<entity>?start=&end=` returns every
    joined session in range, past ones included, with `summary` "Octopus
    Energy Saving Session".
- Fetched in `PriceManager.refresh_cache()` next to the power-up windows,
  same refresh cadence, same "keep the previous list on failure" rule.
  **Session windows are not a price concept, though.** The manager only
  caches them. `BatterySystemManager` reads them through its own accessor
  when it builds optimizer inputs (section 3), and nothing is applied to
  price entries.

### 2. What "an export pulse" means to the optimizer

This is expressed as a **per-period minimum grid export**, a constraint on
flows, not a price. It isn't a post-DP override either:

- A **price bonus** on `sellPrice` for the chosen period was rejected. It
  guarantees nothing: a battery the DP values higher later still won't
  export. It also puts fake revenue into the savings figures, and it's
  reward shaping, which P2 would require to ship with a tie-table row.
- **Rewriting the intent after the DP** was rejected. The SoE trajectory for
  every later period would no longer match what executes, which is the
  R ≠ P class of bug.
- A **constraint inside candidate selection** gives the rest of the day the
  real SoE it'll have after the pulse, and keeps the plan honest.

New optimizer input `min_grid_export_kwh_per_period: list[float] | None`,
threaded exactly the way `import_cap_kwh` is today:

- `PeriodInputs` (`action_selector.py`) gets the field. `select_action`
  filters `candidates` after gathering and before the argmax, **with the
  same "constrain, don't raise" floor the #429 import cap uses**:
  `required = min(target, max(c.grid_exported for c in candidates))`, keep
  `c.grid_exported >= required - 1e-9`.
  - The filter can never empty the list, since the max-export candidate
    survives.
  - A battery too empty to export the full target exports what it can
    instead of making the period infeasible.
- The vectorized grid backward pass (`_run_dynamic_programming`,
  `dp_battery_algorithm.py`, where the `effective_import_cap` mask is built)
  and the PWL backward pass (`pwl_window_dp.py`) apply the identical mask.
  `test_vectorized_backward_parity.py` gets a case for it. **Without that
  case the backward passes can value a policy the forward replay can't
  execute** (P1).
- `grid_exported` counts solar surplus as well as battery discharge. That's
  intended: a summer session with solar surplus meets the pulse without
  cycling the battery, and it's equally good for the meter.
- `optimize_battery_schedule` gains the keyword, default `None`, meaning
  today's behavior exactly.

**No grid import in the window.** `import_cap_kwh` becomes per-period, with
the session periods capped at `0.0`. The existing "constrain, don't raise"
floor already means an empty battery still imports the load it must, rather
than failing. This reuses the filter that exists instead of adding a second
one. The scalar-to-list change touches every `import_cap_kwh` site listed by
`grep -n import_cap_kwh core/bess/{action_selector,dp_battery_algorithm,pwl_window_dp}.py`.
That's mechanical but wide, so it goes in its own commit with the parity
test passing before and after.

### 3. Building the per-period targets (`BatterySystemManager`)

A new private method, `_power_down_export_targets(period_count,
prepare_next_day)`, called beside `_apply_consumption_overlay` when
optimizer inputs are built. Its only job is turning session windows plus
progress so far into the per-period list.

- Settings: `power_down.enabled` (bool, default `False`),
  `power_down.export_kw` (default `1.0`),
  `power_down.export_periods` (int, default `1`, i.e. 15 minutes).
  Target energy per session = `export_kw × 0.25 h × export_periods`.
- **Placement**: the pulse targets the first `export_periods` remaining
  whole periods of the session.
- **Rollover**: every quarterly run recomputes. It sums the realized
  `grid_exported` of the session's already-completed periods from the
  historical store (`EnergyData`, the same data the dashboard's actuals
  use). If that meets the target, no further targets are set. If not, the
  unmet remainder moves onto the next remaining period.

  So a failed inverter write, a Growatt cloud 500, or a load spike in the
  first slot is retried in the next one automatically. There's no retry
  logic of its own: it's the normal re-optimization.
- **Rate headroom.** `BATTERY_EXPORT` writes `grid_first` at the planned
  discharge power, which the hardware delivers as a fixed rate. If real load
  exceeds the forecast, the house imports the difference (#352). The
  candidate the filter keeps already covers the *forecast* load plus
  `export_kw`, so `export_kw` doubles as the headroom margin. The settings
  help text says so directly.
- A session with fewer than `export_periods` periods left gets its targets
  on the periods that remain. A session that has ended is ignored.

### 4. Hardware

No controller changes. A period the filter forces to export is a normal
`BATTERY_EXPORT` or `SOLAR_EXPORT` candidate, and both are already
executable on every platform that supports export (P3).

**Open item to verify at implementation time:** `PlatformCapabilities`
(`execution_model.py:253`) has no "battery export allowed" flag. The nearest
concept is the #269 export-curtailment path (`export_curtailment_active`).
Before building the settings gate, find how an export-limited or zero-export
install is actually modelled, and gate the feature on that.

- If there's no such model, the toggle's help text states that exporting
  must be allowed by the grid connection.
- Don't invent a capability flag.
- Either way, the "constrain, don't raise" floor means an install that can't
  export gets a target reduced to whatever it can export, never an
  infeasible plan.

### 5. Configuration and discovery

- Settings section `power_down` (above) plus sensor key
  `octoplus_power_down_calendar`. `discover_octopus_entities` adds the
  unique_id pattern `^octopus_energy_[^_]+_octoplus_power_down$`, domain
  `calendar`, with the same `disabled_by` handling as the power-up calendar.
- Settings page: a "Power Down sessions" block under the Octopus pricing
  section, with an enable toggle, export power, and export duration
  (15/30/45/60 min). Shown only when the provider is Octopus, plus whatever
  export gate section 4's open item settles on.
- `frontend/src/types.ts`, `api_dataclasses.py` and `settings_store`
  defaults/migration are updated together.

### 6. Outcome logging, so the hypothesis gets tested

After each session ends, BESS logs one INFO line and stores one record in
the daily history:

- session start/end;
- planned vs realized import and export over the window;
- whether the export target was met;
- the `rewarded_octopoints` for that session once the integration reports it.
  That's read from
  `event.octopus_energy_{account}_octoplus_power_down_events`, a second
  optional sensor key `octoplus_power_down_events`. Octopus settles it days
  later, so it's filled in on a later run.

The debug export includes these records. That gives the "does exporting
count?" question from the evidence table a real answer across users,
instead of one install's five sessions.

## Testing

- **Selector filter**: a period with a 0.25 kWh export target and a full
  battery selects a candidate with `grid_exported ≥ 0.25`. With a battery at
  its floor and no solar, it selects the max-export candidate (0 kWh) and
  the list isn't empty.
- **Parity**: `test_vectorized_backward_parity.py`, with export targets set,
  still passes both properties it pins.
- **Outcome test**: a synthetic evening with a session 18:00-19:00, a
  battery at 60%, peak import, flat export. Assert:
  - realized export in the window is ≥ target;
  - realized grid import in the window is 0 when the battery covers load;
  - total plan cost is higher than the unconstrained plan by no more than
    the export energy × (value of stored energy − sell price), i.e. the
    constraint's cost is bounded and visible.
- **Rollover**: the first session period realizes 0 export (simulated write
  failure). The next run targets the second period with the full remainder.
  A later run after the target is met sets no further targets.
- **Disabled by default**: with `power_down.enabled = False`, plans are
  bit-identical to today's across the fixture corpus.
- **Import cap refactor**: the scalar-to-per-period `import_cap_kwh` change
  alone leaves every existing fixture's plan unchanged.

## Non-goals

- Joining sessions. The integration's join service and Octopus auto-join
  already cover it.
- Winning a session's Octopoints by raising the baseline (deliberate peak
  import on normal days). It costs more than a Happy Hour is worth.
- Stopping BESS or forcing an inverter mode, as a Home Assistant automation
  would. This design exists to replace that approach.
- `TURN_UP` Power Up baseline rewards. See the companion spec's known
  limitation.
