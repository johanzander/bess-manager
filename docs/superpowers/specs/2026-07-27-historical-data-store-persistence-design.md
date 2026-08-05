# Persistent `HistoricalDataStore`

## Problem

`HistoricalDataStore` (`core/bess/historical_data_store.py`) holds today's
real sensor/economic actuals — the data the "Incomplete Historical Data"
dashboard banner and the savings numbers are built from — entirely in a
`dict[int, PeriodData]` in memory. It is the only one of the project's four
"today" stores with zero disk persistence:

| Store | Persists? | Where |
|---|---|---|
| `HistoricalDataStore` | ❌ in-memory only | — |
| `PredictionSnapshotStore` | ✅ | `/data/bess_prediction_snapshots.json` |
| `ScheduleStore` (strategic intents) | ✅ | `/config/bess_strategic_intents.json` |
| `DailyViewStore` | ✅ (forever, until user clears) | `/data/daily_views/{date}.json`, one file/day |

Any process restart during the day — a crash, an add-on auto-update, a
manual restart — wipes everything `HistoricalDataStore` has collected so
far. Recovery depends entirely on `_fetch_and_initialize_historical_data`
re-querying InfluxDB at the next startup, and that only covers periods that
had already fully elapsed *before that particular process started*.

Two real production incidents on 2026-07-27 (beta b25) demonstrated the
gap:

1. The add-on auto-updated (b24→b25) at 00:26:58, restarting the container
   mid-period. InfluxDB backfill on restart correctly recovered the one
   already-elapsed period — but this depends on InfluxDB being configured,
   and is a slow, indirect round-trip for data the process had itself
   already collected minutes earlier.
2. Separately (tracked as #403), the quarterly schedule-update job's tight
   `misfire_grace_time=30` let a scheduler tick get silently coalesced away
   while the previous tick was still busy retrying a slow hardware write —
   permanently dropping a whole 15-minute period's actuals, with no
   recovery path at all (InfluxDB backfill only covers periods elapsed
   *before* the current process's startup, not gaps that open up mid-day).

This design fixes the first class of loss directly (a file to restart
from) and, as a side effect, also closes gaps like #403 (see "Startup
recovery" below) without needing that fix to land first.

**Scope**: this design covers `HistoricalDataStore` only.
`PredictionSnapshotStore` and `ScheduleStore` already persist (just via
different bespoke formats/paths) and are not being touched here — their
inconsistency is real but isn't causing data loss today. The direction
chosen below is explicitly the one that leads toward eventually folding all
"today" stores into one, but that consolidation is future work, not part of
this change.

## Design

### Architecture

`HistoricalDataStore` stops being the source of truth and becomes a
**write-through in-memory cache** in front of `DailyViewStore`'s existing
per-day file (`/data/daily_views/{date}.json`), rather than gaining its own
separate persistence file. `DailyViewStore` already exists, is already
keyed one-file-per-calendar-day, and its `DailyView` schema already
supports a mix of `data_source == "actual"` / `"predicted"` / `"missing"`
per period — exactly what an in-progress "today" needs, and exactly what
gets written for a completed day already (via `prepare_next_day` at
23:55). Reusing it avoids introducing a fifth on-disk format.

- **Write path**: every `HistoricalDataStore.record_period()` call (≈ once
  per 15-minute tick, plus each period written during InfluxDB backfill)
  additionally calls `DailyViewBuilder.get_current_daily_view()` — the same
  function `prepare_next_day` already calls once at 23:55 — and passes the
  result to `DailyViewStore.save_day()`. No new merge logic: this reuses
  the existing actual+predicted merge that already runs once a day, just
  starting from period 0 and running on every tick instead of only at
  23:55.
- **Read path (intraday)**: unchanged. `DailyViewBuilder` continues to read
  live from the in-memory `HistoricalDataStore` for "today" — nothing
  needs to read the file back during normal operation.
- **Read path (startup)**: new — see "Startup recovery" below.
- **Midnight rollover**: because the file is date-keyed, no explicit
  "close out today's file" step is needed — once the date rolls over, all
  new writes target a new filename, and yesterday's file is already
  complete from its last tick before midnight. This makes the existing
  23:55 `prepare_next_day` → `daily_view_store.save_day()` call redundant;
  **this design removes that call** rather than leaving two write paths to
  the same file.

### Startup recovery

Replaces `_fetch_and_initialize_historical_data`'s current "InfluxDB or
nothing" logic with a layered recovery:

1. On `start()`, before anything else, try
   `daily_view_store.load_day(today)`.
2. If a file exists: seed `HistoricalDataStore`'s in-memory dict from every
   period in it with `data_source == "actual"`. Periods marked
   `"predicted"` or `"missing"` in the file are not seeded — they're not
   real actuals.
3. Run the existing InfluxDB backfill loop
   (`is_influxdb_configured()` check, `for period in range(0,
   current_period)`) as today, but skip any period step 2 already
   populated from the file. Periods the file marked `"missing"` (e.g. a
   past #403-style dropped tick) or `"predicted"` are attempted via
   InfluxDB exactly like any other unrecovered period — the file is not
   treated as a final answer for those.
4. If no file exists at all (first-ever run, or an unreadable/corrupt
   file — `DailyViewStore.load_day()` already catches
   `json.JSONDecodeError`/`OSError`/`KeyError`/`ValueError`, logs a
   warning, and returns `None`), behavior is exactly what it is today:
   InfluxDB backfill only, or skipped entirely if InfluxDB isn't
   configured.

Neither source (file or InfluxDB) is trusted exclusively; each fills in
whatever the other doesn't have.

### Clearing semantics

"Clear Savings History" (`DELETE /api/savings/history` →
`DailyViewStore.clear_all()`) must **not** touch today's file:

- `clear_all()` gets a date-exclusion: skip `{today}.json` when deleting.
- `list_available_dates()` and `get_disk_usage()` (used for the "N days
  recorded (size)" text in Settings) also exclude today's file, so the
  displayed count/size continues to mean "completed days," matching
  current behavior.
- No new UI or endpoint for clearing today's in-progress data — out of
  scope. Today's file is naturally superseded at midnight rollover as
  described above.

### Error handling

Mirrors `DailyViewStore.save_day()`'s existing pattern — disk writes are
best-effort, never fatal:

- Write failure (`OSError`, disk full, permissions): log a warning,
  continue operating from the in-memory cache, retry naturally on the next
  tick's write. Never raises out of `record_period()`.
- Read failure at startup: already handled by `DailyViewStore.load_day()`
  today; startup recovery falls through to "no file" behavior (step 4
  above).
- No new exception types.

### Testing

- **Unit** (`core/bess/tests/unit/`): extend
  `test_historical_data_store.py` to cover the write-through behavior —
  `record_period()` triggers a `DailyViewStore.save_day()` call with the
  merged view; a write failure logs but does not raise.
- **Startup recovery**: new tests for the three paths — file-only,
  file+InfluxDB-fills-gaps (a file with some `"missing"`/`"predicted"`
  periods, asserting InfluxDB is queried only for those), and no-file
  (today's existing InfluxDB-only behavior, unchanged).
- **Clear History**: test that `{today}.json` survives `clear_all()` /
  `DELETE /api/savings/history`, and that disk-usage/day-count figures
  exclude it.
- **Removed 23:55 save**: update `test_bsm_settings_and_lifecycle.py`
  (already covers the `prepare_next_day` clear-timing fix, #396) to
  reflect that `prepare_next_day` no longer calls
  `daily_view_store.save_day()` itself, and instead assert the day's file
  is already correct at that point because of incremental writes.
- No new integration/E2E coverage planned — this is a backend persistence
  change with no UI surface beyond the existing Settings "days recorded"
  count already covered above.

## Out of scope

- Consolidating `PredictionSnapshotStore` and `ScheduleStore` into the same
  file/format. Explicitly deferred; this design is one step toward that
  end state, not the full migration.
- A UI/endpoint for clearing only today's in-progress data.
- Fixing #403 (silently-skipped scheduler tick) directly — this design
  incidentally recovers from its symptom via InfluxDB backfill (step 3
  above) but does not address its root cause.

## Related

- #403 — quarterly schedule-update tick can be silently skipped, dropping
  a period's actuals with no recovery path (this design's startup recovery
  covers the resulting gap when InfluxDB is configured, but does not fix
  the underlying scheduler issue).
- #396 — `historical_store.clear()` timing fix (23:55 → true midnight).
  Unrelated failure mode (premature clearing vs. mid-day data loss on
  restart) but touches the same clear/save lifecycle code
  (`_handle_special_cases`).
