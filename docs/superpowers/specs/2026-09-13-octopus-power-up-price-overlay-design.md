# Design: Octopus Power Up sessions as a price overlay

**Date**: 2026-09-13
**Status**: Implemented on `feat/octopus-power-up-price-overlay` (see
"Implementation notes" at the end for where the code departs from this text).
**Related**: #709 (the price cache is read cache-only on the optimizer
thread), #428 / `consumption_overlay.py` (the precedent: a per-run overlay
read from an HA entity, composed after the cache), #662 (price health check
must not re-fetch on a schedule). Companion spec:
`2026-09-13-octopus-power-down-export-pulse-design.md`.

## Problem

Octopus gives Octoplus customers free electricity windows. There are two
kinds today:

- **Weekend Happy Hours** (`WEEKEND_HAPPY_HOUR`). You earn one by completing
  two Power Down (saving) sessions, then book an hour at the weekend in the
  Octopus app. The hour is free up to 16 kWh.
- **Power Up sessions** (`TURN_UP`, which replaced "Free Electricity"
  sessions). They're announced nationally and joined automatically.

BESS doesn't know about either. `OctopusEnergySource._fetch_rates`
(`core/bess/octopus_energy_source.py:131`) only reads `value_inc_vat` from
the `*_current_day_rates` / `*_next_day_rates` event entities. **Octopus
doesn't change the published Agile rate for a free window**, so BESS
optimizes the free hour at full Agile price. Observed on 2026-09-13: a booked
11:00-12:00 Happy Hour while the import rates were 32.5p and 33.2p for those
two half-hours.

The result is that BESS makes the wrong call around a free window:

- It grid-charges earlier at a real price when it could fill the battery for
  free in the window.
- It discharges the battery to cover house load *during* the window, spending
  stored energy on load that would have cost nothing.
- Its cost, savings and cost-basis figures price that energy at Agile rates.

Automating around BESS in Home Assistant (forcing a mode during the window)
doesn't fix any of this. The DP still plans the rest of the day without the
free window, and the accounting stays wrong.

## What the Octopus integration exposes (verified 2026-09-13, integration v19.0.1)

Source: `BottlecapDave/HomeAssistant-OctopusEnergy` at tag `v19.0.1`, plus a
live HA instance.

- The account's joined events come back from Octopus's `savingSessions`
  GraphQL query. `api_client/__init__.py` splits them by `eventType`:
  `power_down_event_types = ["TURN_DOWN"]` and
  `power_up_event_types = ["TURN_UP", "WEEKEND_HAPPY_HOUR"]`. v19.0.1 fixed
  Happy Hours showing up as Power Down events (integration issue #1820).
- Joined power-up events, plus the integration's own national
  free-electricity dataset, are published on two entities.
  **Both are disabled by default**:
  - `calendar.octopus_energy_{account}_octoplus_power_up` (unique_id
    `octopus_energy_{ACCOUNT}_octoplus_power_up`).
  - `event.octopus_energy_{account}_octoplus_power_up_events`, whose
    `events` attribute holds `id, code, start, end, duration_in_minutes`.
- **The integration doesn't forward the event type.** A booked Happy Hour
  and a national Power Up look identical: same calendar summary
  (`"Octopus Energy Power Up"`), and no `eventType` field on the event
  entity.
- **Nobody is building a rates overlay upstream.** No open issue or PR in
  the integration touches the rate entities for free sessions. The
  maintainer's position (#1820, #1845) is that sessions live on the Octoplus
  entities, not the tariff entities. Predbat handles this on its own side
  (batpred#4548). So BESS must compose the overlay itself.

The HA REST calendar endpoint returns the booked event including past ones
on the same day. Verified response:

```
GET /api/calendars/calendar.octopus_energy_a_982b3d40_octoplus_power_up
    ?start=2026-09-13T00:00:00+01:00&end=2026-09-15T00:00:00+01:00
[{"start":{"dateTime":"2026-09-13T11:00:00+01:00"},
  "end":{"dateTime":"2026-09-13T12:00:00+01:00"},
  "summary":"Octopus Energy Power Up","description":null,
  "location":null,"uid":6134,"recurrence_id":null,"rrule":null}]
```

The calendar is the source of truth, not the event entity. The event
entity's attributes are only rewritten when the integration fires its
event, so they're empty right after an integration reload. The calendar
endpoint answers a time-range query directly. That was observed on the same
day: `joined_events` was `None` after the reload, while the calendar had
the event.

## Design

### 1. Read path: a new sensor key, through `ha_api_controller`

This follows the `consumption_overlay` precedent (`METHOD_SENSOR_MAP` entry
`get_consumption_overlay_blocks`, `ha_api_controller.py:1528`):

- A new `METHOD_SENSOR_MAP` entry `get_power_up_windows` with sensor key
  `octoplus_power_up_calendar`. Optional: no entity configured means "no
  overlay", a supported configuration that behaves exactly like today.
- `HomeAssistantAPIController.get_power_up_windows(start, end) ->
  list[CalendarWindow]` calls `GET /api/calendars/{entity}?start=&end=`
  through `_api_request`. It parses each event's `start.dateTime` /
  `end.dateTime` into timezone-aware datetimes.
  - An all-day event (a `date` key instead of `dateTime`) raises. So does a
    malformed entry. The new `CalendarWindowError` goes in
    `core/bess/exceptions.py`, per the rules' explicit-failure policy.
  - A 404 on a configured entity also raises, because that means the entity
    is disabled or renamed. The user configured it, so a silently ignored
    free hour is worse than a visible error.
- The REST call and parsing live in a private
  `_get_calendar_windows(sensor_key, start, end)`. `get_power_up_windows` is
  a thin wrapper around it. The Power Down spec adds a second wrapper,
  `get_power_down_windows`, over the same helper, so there's one calendar
  reader, not two.
- `CalendarWindow` is a frozen dataclass `(start, end)` in a new
  `core/bess/calendar_windows.py`, together with its payload parser. It isn't
  in `models.py`, the same way `OverlayBlock` lives in
  `consumption_overlay.py`. It's shared by both Octoplus specs. **This is a
  new class and needs maintainer approval** per the rules.

### 2. Fetch timing: in the price refresh job, never on the optimizer thread

`PriceManager.refresh_cache()` (`price_manager.py:631`) runs from the
dedicated `refresh_prices` job at :05/:20/:35/:50. Today it's a no-op once a
day's prices are cached. The window fetch is **not** gated by that no-op:
bookings change during the day, while rates don't.

- `refresh_cache()` gains one step. When a window source is configured, it
  fetches windows for `[today 00:00, tomorrow 24:00)` and stores them in the
  manager's own `_free_import_windows`, replacing the previous list.
- A failed fetch keeps the previous list and records a runtime failure. It's
  swallowed the same way today's price fetch failures are (#709), so a flaky
  integration can't block a period switch.
- The quarterly optimizer keeps reading cache-only. A booking made at 09:00
  for 11:00 lands in the plan at the 09:15 run at the latest (fetched 09:05).
  **No cache invalidation is needed**, because the overlay is applied at read
  time (section 3).

This fixes the problem that makes a Home-Assistant-side workaround
unreliable: `get_price_data` caches today once, so changing the rate entity
mid-day never reaches the optimizer without a restart.

### 3. Compose at read time, in one funnel

The overlay is applied to cached price entries **when they're read**, not
when they're fetched and cached. Raw Agile prices stay in the cache
untouched, and the overlay always reflects the latest window list.

- New module-level function in a new file `core/bess/free_import_overlay.py`:
  `apply_free_import_windows(entries, windows, free_price) -> list[dict]`.
  - For each quarterly entry whose `[timestamp, timestamp+15min)` lies
    **fully** inside a window, set `buyPrice = free_price`. `price` (raw)
    and `sellPrice` stay unchanged.
  - A period only partly covered keeps its buy price. Octopus windows are
    whole hours on half-hour boundaries, so partial overlap only happens with
    a malformed event. That case is logged at warning with the event bounds.
  - It returns new entries and never mutates the cache.
- `PriceManager` applies it in the one place every cached read already goes
  through: `_cached_today_prices()` / `_cached_tomorrow_prices()`
  (`price_manager.py:799`). Those feed:
  - `get_cached_today_prices()` / `get_cached_tomorrow_prices()`, the
    optimizer's reads (`battery_system_manager.py:1747`);
  - `get_price_data()`, and so `get_available_prices()`, used for historical
    period cost at `battery_system_manager.py:1050` and `:1827`.

  One funnel means the plan, the dashboard's planned cost, and the realized
  per-period cost recorded at collection time all see the same 0p. A consumer
  that prices the window at Agile while the plan assumes free is the bug
  class this avoids.
- `free_price` defaults to `0.0`. It's configurable (section 5) because the
  integration can't tell a Happy Hour from a `TURN_UP` Power Up (see
  "Known limitation").

### 4. The 16 kWh cap is not modelled, deliberately

The Happy Hour is free "up to 16 kWh". The DP has no tiered price, and
adding one would change `_price_flows`, the protected physics core. The cap
isn't reachable on the homes this targets:

- It needs a sustained 16 kW import for a full hour.
- `_effective_import_cap_kwh` already limits import to the fuse. The
  default `HOUSE_MAX_FUSE_CURRENT_A = 25` gives 5.75 kW single phase. Even a
  large 63 A single-phase supply is 14.5 kW, still under 16 kW.
- Actual draw is battery max charge plus house load. The reference install
  charges at 6 kW or less.

The overlay logs one warning per window when
`max_fuse_current × voltage × phase_count × window_hours > 16 kWh`, so a
three-phase install knows the model is optimistic. No behavior change.

### 5. Configuration and discovery

- Persisted as a new optional sensor key `octoplus_power_up_calendar` in
  `settings_store` (same section as `consumption_overlay`), plus
  `energy_provider.octopus.free_import_price` (float, default `0.0`).
- `discover_octopus_entities` (`ha_api_controller.py:3836`) adds a
  unique_id pattern `^octopus_energy_[^_]+_octoplus_power_up$` on platform
  `octopus_energy`, domain `calendar`. **If the registry entry has
  `disabled_by` set**, the setup wizard and settings page show "enable this
  entity in Home Assistant", not a silently empty field. This entity ships
  disabled, so most users would otherwise never get the feature.
- Settings page (`PricingFormSection.tsx`, Octopus branch): one entity picker
  ("Octoplus free power calendar") and one numeric field ("Price during free
  windows"). `frontend/src/types.ts` and `api_dataclasses.py` get the two
  fields.
- Health check: a configured calendar that 404s, or whose last fetch failed,
  reports `WARNING` ("free power windows may be missing from the plan"). It
  reports `ERROR` only if the problem persists past the price-refresh
  interval × 2. Today's prices remain usable, so this never blocks
  optimization.

### 6. UI

- The price chart marks overlaid periods. Add a boolean `isFreeImport` on the
  price entry DTO, set by the overlay, so the frontend doesn't re-derive
  windows.
- The Savings page needs no change: realized cost is already computed from
  the overlaid buy price.

## Known limitation: TURN_UP vs WEEKEND_HAPPY_HOUR

The integration v19.0.1 drops `eventType` before publishing, so every event
on the power-up calendar is treated as a free window at `free_price`:

- A Happy Hour is genuinely 0p (up to 16 kWh).
- A national free-electricity session from the integration's dataset has
  historically also been free.
- A `TURN_UP` "Power Up" pays a reward for consumption *above a baseline*.
  That isn't a flat free price, and 0p overstates it.

Proposed mitigation, out of scope here: ask the integration to expose
`event_type` on the power-up calendar event description or event attributes
(new integration issue; #1845 is the closest). Once it's exposed,
`get_power_up_windows` filters to `WEEKEND_HAPPY_HOUR` and free-electricity
events, and `TURN_UP` gets its own treatment. Until then, a user who wants to
stay conservative sets `free_price` to a low non-zero value.

## Testing

Behavioral tests, per `docs/agents/testing.md`:

- **Overlay composition** (`test_free_import_overlay.py`):
  - periods fully inside a window get `free_price` buy and unchanged sell;
  - periods outside are untouched;
  - partial overlap leaves the price unchanged;
  - windows spanning midnight land on the right day;
  - a DST day (92/100 periods) aligns by timestamp, not index.
- **Read-time application** (`test_price_manager.py`): after a window
  appears, `get_cached_today_prices()` reflects it with no `clear_cache()`
  and no source re-fetch. The source mock's call count stays at 1.
- **Refresh isolation**: a window-fetch exception inside `refresh_cache()`
  keeps the previous windows and doesn't raise.
- **Controller parsing**: verified REST payload above parses; all-day event,
  missing `dateTime`, 404 each raise `CalendarWindowError`.
- **Outcome test** (the one that matters): a synthetic day with
  - flat 30p import, 12p export, a 6 kW / 10 kWh battery at 20% SoC;
  - a free window 11:00-12:00.

  Assert:
  - realized grid-charge cost before 11:00 is zero, i.e. the plan defers
    charging into the window;
  - battery discharge covering house load inside the window is zero;
  - the plan's total cost is lower than the same fixture without the window,
    by at least the value of the window's free energy after losses:
    `30p × (grid→home + grid→battery × η_charge × η_discharge) − cycle cost ×
    grid→battery`. (The original "window import × 30p" bound is physically
    unreachable: energy charged in the window loses round-trip efficiency and
    cycle wear before it displaces a 30p import.)

  Assert costs and flows, not intents.
- No change to `test_vectorized_backward_parity.py`: prices are an input,
  and the optimizer core is untouched.

## Non-goals

- Booking Happy Hour slots (integration issue #1845, the integration's
  `join_octoplus_weekend_happy_hour_event` action). That's user preference
  and stays outside BESS.
- Modelling `TURN_UP` baseline rewards (see "Known limitation").
- Non-Octopus providers. The read path and overlay are provider-agnostic, but
  only the Octopus settings branch exposes the picker in this change.
- Any change to `optimize_battery_schedule`, `action_selector.py`, or the
  tie table. This design is price-input only.

## Implementation notes

Verified against upstream `3c8643ff`; all file:line citations above held.
Where the implementation differs from the text:

- **The funnel had two bypasses.** `get_price_data()` returned the cached
  tomorrow slot directly and returned freshly fetched entries without going
  through `_cached_*`. Both now return overlaid entries, so every read path
  (optimizer, `get_available_prices()`, dashboard) sees the same price.
- **DST alignment is by elapsed time.** Price entries' naive timestamps are
  `midnight + i × 15 min` wall clock, which is wrong after a DST change. The
  overlay therefore takes the day explicitly —
  `apply_free_import_windows(entries, day, windows, free_price)` — and places
  period `i` at local midnight (UTC) + `i × 15 min`, matching how the price
  sources and `get_period_count` index a 92/100-period day.
- **Window source is injected.** `PriceManager` takes
  `free_import_window_source` (BSM passes `_fetch_free_import_windows`, which
  calls `get_power_up_windows` and emits the 16 kWh warning once per window)
  and `free_import_price`.
- **Health** is a separate optional component, "Octoplus Free Import
  Windows", returned by `PriceManager.check_health()` only while the fetch is
  failing: WARNING, then ERROR once the failure has persisted > 30 min.
- **Discovery** returns `powerUpCalendar`, plus `powerUpCalendarDisabledBy`
  when the registry entry is disabled.
- **Settings**: `energy_provider.octopus.free_import_price` is added by
  `_migrate_schema` (default `FREE_IMPORT_PRICE = 0.0` in `settings.py`) and
  read strictly for the octopus provider.
