# Issue #387: InfluxDB-free power-sensor gap-fill for runtime energy collection

## Problem

`sensor_collector.py`'s per-period `EnergyData` (`battery_charged`,
`battery_discharged`, `solar_production`, `grid_imported`, `grid_exported`,
`home_consumption`) can show a "0 → double" attribution pattern: cumulative
HA energy counters (e.g. Growatt lifetime discharge energy) only tick in
0.1 kWh steps, so a real but small discharge within a 15-minute period can
leave that period's counter delta at exactly zero, with the energy showing
up doubled in the following period once the counter catches up. Observed 3
times in one night's debug bundle (periods 5→6, 9→10, 25→26).

This is not cosmetic. Independent tracing of the downstream call graph
found real behavioral impact:

- `_calculate_initial_cost_basis` (`battery_system_manager.py:2715`) walks
  every completed period's charged/discharged energy from the historical
  store to compute the running weighted-average acquisition cost of energy
  currently in the battery, fed directly into the DP as the discharge cost
  floor for the rest of that day — a doubled/zeroed period shifts today's
  optimizer decisions.
- `daily_view_builder.py:143` sums realized savings per period using that
  period's own buy/sell price; misattributing energy from a cheap-hour
  period to an expensive-hour period distorts the user-facing savings
  total by `(price_B − price_A) × energy`, not zero-sum noise.
- `infer_intent_from_flows`/`observed_intent` can mislabel a period,
  affecting the plan-vs-actual divergence diagnostic (lower stakes, display
  only).
- Consumption-forecast strategies (`influxdb_7d_avg`, `ha_statistics`) are
  confirmed unaffected — they query InfluxDB/HA statistics directly, not
  the historical store.

A fix already exists for the historical/backfill collection path: when all
cumulative-counter flows read zero for a period, fall back to power (W)
sensors (which report far more often and don't have the 0.1 kWh
quantization problem), averaging readings within the period and converting
W → kWh (`mean_watts * 0.25 / 1000.0`). That correction was gated to
`is_historical_backfill` and never reachable from **runtime** collection —
the path that actually runs every 15 minutes in production via
`_update_energy_data`.

## Constraint: no new InfluxDB dependency

The project is working to remove its InfluxDB dependency. The historical
path's existing gap-fill queries InfluxDB (`get_power_sensor_data_batch`),
and a first attempt at this fix (already committed on this branch, to be
reverted as part of this work) simply removed the `is_historical_backfill`
gate — which would have made runtime collection depend on InfluxDB for
gap-fill too, going the wrong direction. This design instead builds a
live, in-memory power-sampling mechanism so runtime gap-fill has **no**
InfluxDB dependency at all. The historical-backfill path is unaffected and
keeps its existing InfluxDB-based gap-fill (backfill already requires
InfluxDB for its base historical query, so this isn't a regression there).

## Design

### Components

**`PowerSampleBuffer`** (new, owned by `SensorCollector` as
`self._power_sample_buffer`) — a rolling in-memory buffer:
`{period: {sensor_key: [watts, ...]}}`.

- `record(period: int, readings: dict[str, float]) -> None` — appends one
  poll's readings into that period's bucket. Also prunes any bucket older
  than 2 periods, so a period that's somehow never consumed can't leak
  memory indefinitely.
- `consume(period: int) -> dict[str, float] | None` — averages each
  sensor's samples for that period, converts W → kWh
  (`mean_watts * 0.25 / 1000.0`, reusing the existing conversion constant
  from `influxdb_helper._parse_power_batch_response`), clears that
  period's bucket, and returns the per-flow-name dict (or `None` if the
  bucket was empty). Always clears on read, whether or not the caller ends
  up using the result for gap-fill.

**`SensorCollector.sample_live_power()`** (new method) — called every
minute by a new scheduler job. No-ops immediately if `self.power_sensors`
is empty. Otherwise calls `ha_controller._fetch_all_states()` (one bulk
`GET /api/states`, already used by discovery — avoids 6 separate
per-sensor HTTP calls), extracts the 6 configured power entities, skips
any that are missing or non-numeric (logs `WARNING`, doesn't raise), and
calls `buffer.record(current_period, readings)`.

**New scheduler job** (`backend/app.py`, `_init_scheduler_jobs`):
```python
self.scheduler.add_job(
    self.system.sensor_collector.sample_live_power,
    CronTrigger(minute="*"),
    misfire_grace_time=30,
)
```
Matches the existing 1-minute cadence tier (`apply_discharge_inhibit`).

**`collect_energy_data()` runtime branch** — after computing `flow_dict`
from the cumulative-counter delta (unchanged):

```python
buffer_estimate = self._power_sample_buffer.consume(period)
if all_energy_zero:
    if buffer_estimate:
        # apply as gap-fill, same key/threshold logic as today's
        # InfluxDB-based path
        ...
elif buffer_estimate:
    # counter had a real nonzero delta - log DEBUG comparison only,
    # no behavior change. Validates power-sample accuracy against the
    # ground-truth counter over time.
    logger.debug(
        "Period %d: counter vs power-sample estimate: %s",
        period,
        {k: f"{flow_dict.get(k, 0.0):.4f} vs {buffer_estimate.get(k, 0.0):.4f}"
         for k in energy_flow_keys if k in buffer_estimate},
    )
```

The W→kWh conversion math is factored into a small shared helper so both
the InfluxDB path (`influxdb_helper._parse_power_batch_response`) and the
buffer path (`PowerSampleBuffer.consume`) compute it identically.

**Historical-backfill branch** — unchanged. The already-committed
unconditional-gate change (`if all_energy_zero:`) is reverted back to
`if all_energy_zero and is_historical_backfill:`, restoring the original
gate for the InfluxDB-based `_get_power_based_flows` call.

### Why not go power-primary

Considered and rejected: making power-sensor estimation the primary
source for all periods (not just gap-fill) instead of a fallback.

- Cumulative counters are exact and self-correcting — each period's
  counter starts exactly where the last one ended, so error cannot
  accumulate across a day. A power-based estimate integrates a handful of
  samples; every period carries some sampling error (missed spikes between
  polls, aliasing on fast-changing loads) with nothing forcing it back to
  zero.
- Power sensors are optional in the health check; cumulative energy
  sensors are closer to a hard setup requirement. Flipping primacy would
  turn a graceful fallback into a new hard dependency for every user.
- Cumulative counters are the vendor's own metering value — the same
  number users see in their inverter's own app. Silently diverging from it
  risks trust.

The DEBUG-level counter-vs-estimate comparison logging (above) is included
specifically to build evidence toward any future reconsideration of this,
without committing to it now or expanding this spec into a
validation-reporting feature (no new storage, no dashboard surface).

### Error handling

| Case | Behavior |
|---|---|
| A specific power entity missing/invalid in a poll | That sensor skipped for that sample; other 5 still recorded; `WARNING` logged |
| No power sensors configured | `sample_live_power()` no-ops immediately, no HA call |
| Buffer empty at `consume()` time (startup, restart mid-period, unconfigured) | Returns `None`; gap-fill silently no-ops — same as today's "no correction available" behavior |
| Restart mid-period | In-memory buffer lost; that period's partial samples gone (accepted — restarts are rare relative to 15-min periods, affects at most one period per restart) |
| A period's bucket somehow never consumed | Pruned by `record()` once its bucket is more than 2 periods old |

### Testing

- `PowerSampleBuffer` unit tests: multi-sample accumulation per period,
  average + clear on `consume()`, `None` on empty/unknown period, max-age
  prune.
- `sample_live_power()` unit tests: happy path (all 6 recorded), missing/
  invalid entity skipped without raising, no-op when unconfigured.
- `collect_energy_data()` runtime-branch tests (extend
  `test_sensor_collector_gapfill.py`): zero-delta + populated buffer →
  gap-filled from buffer; zero-delta + empty buffer → stays `0.0`, no
  exception; nonzero-delta + populated buffer → counter value wins,
  `DEBUG` comparison logged (assert via `caplog`), buffer still cleared.
- Historical-backfill tests: unchanged, confirm the gate revert didn't
  regress the InfluxDB path.
- No new podman/mock-HA E2E scenario file. Re-run the same style of
  live-mock-HA check already used to verify graceful degradation (calling
  `sample_live_power()`/`collect_energy_data()` against a running mock-HA
  via the real `HomeAssistantAPIController`) as part of implementation
  Step 8, to confirm the new scheduler job doesn't error against
  real HA-shaped responses.

## Out of scope

- Removing InfluxDB from the historical-backfill path, health checks, or
  consumption-forecast strategies (`influxdb_7d_avg`) — this spec only
  removes the InfluxDB dependency from the runtime gap-fill path.
- Any change to how the cumulative-counter delta itself is computed for
  the common case (nonzero delta) — only the zero-delta fallback source
  changes.
- Persisting or surfacing the counter-vs-estimate comparison anywhere
  beyond a DEBUG log line.
