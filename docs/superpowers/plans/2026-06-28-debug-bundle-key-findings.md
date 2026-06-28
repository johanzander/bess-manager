# Debug Bundle Key-Findings Section — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface pre-digested conclusions (cross-run schedule disagreements + a
deduplicated log-anomaly rollup) at the TOP of the debug bundle and the AI-chat
context, and demote raw logs/JSON to the bottom — so agents and the in-app chat stop
anchoring on the latest run and the green health snapshot.

**Architecture:** One new data-layer module `core/bess/debug_findings.py` computes
findings from structured schedule data (`export.schedules`, already all runs) and the
log text (`export.todays_log_content`). Two thin renderers consume it:
`debug_report_formatter.py` (markdown bundle) and `backend/ai_chat.py` (chat context).
No optimizer behavior changes.

**Tech Stack:** Python 3 (stdlib only — `dataclasses`, `re`), pytest. No new deps.

## Global Constraints

- **No optimizer behavior change.** This plan only adds reporting/aggregation.
- **Findings are derived, deduplicated data** — group by `(category, module:line)`;
  never emit raw per-line counts (220 "restart" hits are one repeated warning).
- **Log anomalies come from `export.todays_log_content`**, NOT the runtime failure
  tracker (unreliable, not exported).
- **Cross-run reconciliation comes from `export.schedules`** — the exporter already
  serializes ALL of today's runs there via `get_all_schedules_today()` + `asdict`.
- **Always-on, self-suppressing:** the Key Findings section renders every time; when
  there is nothing notable it says so explicitly ("No anomalies… detected").
- Run `.venv/bin/pytest -m "not slow"` and `./scripts/quality-check.sh` before any
  commit (Black formatting is the most common CI failure).
- Spec: `docs/superpowers/specs/2026-06-28-bess-analyst-decision-rationale-design.md`
  (Part 5).

---

## File Structure

- `core/bess/debug_findings.py` — NEW. Dataclasses + `summarize_log_anomalies`,
  `reconcile_schedules`, `build_key_findings`. Pure functions, no I/O.
- `core/bess/tests/unit/test_debug_findings.py` — NEW. Unit tests for the above.
- `core/bess/debug_data_exporter.py` — add `key_findings` field to `DebugDataExport`
  and populate it in `aggregate_all_data`.
- `core/bess/debug_report_formatter.py` — render `_format_key_findings` first;
  caption the health snapshot; move full schedule JSON to the bottom.
- `backend/ai_chat.py` — include findings text in `_gather_context`; exclude raw log
  dump.

---

### Task 1: Log-anomaly aggregation (`debug_findings.py`)

**Files:**
- Create: `core/bess/debug_findings.py`
- Test: `core/bess/tests/unit/test_debug_findings.py`

**Interfaces:**
- Produces:
  - `@dataclass LogAnomaly(category: str, source: str, count: int, first_ts: str,
    last_ts: str, sample: str)`
  - `summarize_log_anomalies(log_content: str) -> list[LogAnomaly]`

- [ ] **Step 1: Write the failing test.**

```python
# core/bess/tests/unit/test_debug_findings.py
from core.bess.debug_findings import LogAnomaly, summarize_log_anomalies

SAMPLE_LOG = """2026-06-28 00:16:00 | WARNING | core.bess.battery_system_manager:1439 - Historical data unavailable for period 0 (00:00): No InfluxDB data available
2026-06-28 00:31:00 | WARNING | core.bess.battery_system_manager:1439 - Historical data unavailable for period 1 (00:15): No InfluxDB data available
2026-06-28 10:31:00 | ERROR | core.bess.influxdb_helper:519 - Error connecting to InfluxDB: HTTPConnectionPool: Max retries exceeded
2026-06-28 11:31:00 | ERROR | core.bess.influxdb_helper:519 - Error connecting to InfluxDB: HTTPConnectionPool: Max retries exceeded
2026-06-28 09:00:00 | INFO | core.bess.app:12 - nothing interesting here
"""


def test_summarize_dedups_by_category_and_source():
    out = summarize_log_anomalies(SAMPLE_LOG)
    by_source = {a.source: a for a in out}

    data_gap = by_source["core.bess.battery_system_manager:1439"]
    assert data_gap.category == "data_gap"
    assert data_gap.count == 2
    assert data_gap.first_ts == "2026-06-28 00:16:00"
    assert data_gap.last_ts == "2026-06-28 00:31:00"

    network = by_source["core.bess.influxdb_helper:519"]
    assert network.category == "network"
    assert network.count == 2


def test_summarize_ignores_uncategorized_info_lines():
    out = summarize_log_anomalies(SAMPLE_LOG)
    assert all("app:12" not in a.source for a in out)


def test_summarize_empty_log_returns_empty():
    assert summarize_log_anomalies("") == []
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `.venv/bin/pytest core/bess/tests/unit/test_debug_findings.py -q`
Expected: FAIL — `ModuleNotFoundError: core.bess.debug_findings`.

- [ ] **Step 3: Implement the minimal code.**

```python
# core/bess/debug_findings.py
"""Pre-digested findings for the debug bundle / AI-chat context.

Pure functions over already-collected data: the log text and the serialized
schedules. No I/O. Two consumers render the result (the markdown formatter and the
AI-chat context builder) so the logic lives here once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A categorized, deduplicated log finding.
@dataclass
class LogAnomaly:
    category: str
    source: str  # "module:line"
    count: int
    first_ts: str
    last_ts: str
    sample: str


_LOG_LINE_RE = re.compile(r"^(\S+ \S+) \| (\w+) \| ([\w.]+:\d+) - (.*)$")

# (category, compiled message/source matcher). First match wins; order matters.
_CATEGORY_RULES = [
    ("network", re.compile(
        r"Max retries|Connection error|Failed to establish a new connection"
        r"|Failed to load batch data")),
    ("data_gap", re.compile(
        r"Historical data unavailable|No InfluxDB data|missing period")),
    ("restart", re.compile(
        r"Starting BESS Manager|BESS Manager started|Application startup")),
]


def _categorize(level: str, message: str) -> str | None:
    for category, matcher in _CATEGORY_RULES:
        if matcher.search(message):
            return category
    if level == "ERROR":
        return "runtime_error"
    return None  # uncategorized WARNING/INFO — not actionable, ignore


def summarize_log_anomalies(log_content: str) -> list[LogAnomaly]:
    """Categorize + deduplicate actionable log lines by (category, source)."""
    agg: dict[tuple[str, str], LogAnomaly] = {}
    for line in log_content.splitlines():
        m = _LOG_LINE_RE.match(line)
        if not m:
            continue
        ts, level, source, message = m.groups()
        category = _categorize(level, message)
        if category is None:
            continue
        key = (category, source)
        existing = agg.get(key)
        if existing is None:
            agg[key] = LogAnomaly(category, source, 1, ts, ts, message.strip())
        else:
            existing.count += 1
            existing.first_ts = min(existing.first_ts, ts)
            existing.last_ts = max(existing.last_ts, ts)
    return sorted(agg.values(), key=lambda a: a.count, reverse=True)
```

- [ ] **Step 4: Run the tests.**

Run: `.venv/bin/pytest core/bess/tests/unit/test_debug_findings.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit.**

```bash
git add core/bess/debug_findings.py core/bess/tests/unit/test_debug_findings.py
git commit -m "feat: deduplicated log-anomaly aggregation for debug findings"
```

---

### Task 2: Cross-run reconciliation + `build_key_findings`

**Files:**
- Modify: `core/bess/debug_findings.py`
- Modify: `core/bess/tests/unit/test_debug_findings.py`

**Interfaces:**
- Consumes: `LogAnomaly`, `summarize_log_anomalies` (Task 1).
- Produces:
  - `@dataclass SlotDisagreement(period: int, time: str,
    occurrences: list[tuple[str, str, float]], intents: list[str])`
    where each occurrence is `(schedule_timestamp, strategic_intent, battery_action)`.
  - `reconcile_schedules(schedules: list[dict]) -> list[SlotDisagreement]`
  - `build_key_findings(schedules: list[dict], log_content: str) -> dict`
    returning `{"disagreements": [...], "anomalies": [...], "clean": bool}`.

`schedules` is `export.schedules`: a list of dicts, each
`{"timestamp": str, "optimization_result": {"period_data": [
{"period": int, "decision": {"strategic_intent": str, "battery_action": float}}, ...]}}`.

- [ ] **Step 1: Write the failing test.**

```python
from core.bess.debug_findings import (
    SlotDisagreement,
    build_key_findings,
    reconcile_schedules,
)


def _sched(ts, period, intent, action):
    return {
        "timestamp": ts,
        "optimization_result": {
            "period_data": [
                {"period": period, "decision": {
                    "strategic_intent": intent, "battery_action": action}}
            ]
        },
    }


def test_reconcile_flags_intent_disagreement_on_same_slot():
    schedules = [
        _sched("2026-06-28 10:31:00", 63, "BATTERY_EXPORT", -0.1),
        _sched("2026-06-28 11:31:00", 63, "SOLAR_EXPORT", -0.0),
    ]
    out = reconcile_schedules(schedules)
    assert len(out) == 1
    d = out[0]
    assert d.period == 63
    assert d.time == "15:45"
    assert set(d.intents) == {"BATTERY_EXPORT", "SOLAR_EXPORT"}


def test_reconcile_no_disagreement_when_all_runs_agree():
    schedules = [
        _sched("2026-06-28 10:31:00", 63, "SOLAR_EXPORT", -0.0),
        _sched("2026-06-28 11:31:00", 63, "SOLAR_EXPORT", -0.0),
    ]
    assert reconcile_schedules(schedules) == []


def test_build_key_findings_clean_when_nothing_notable():
    schedules = [_sched("2026-06-28 11:31:00", 63, "SOLAR_EXPORT", -0.0)]
    result = build_key_findings(schedules, "")
    assert result["clean"] is True
    assert result["disagreements"] == []
    assert result["anomalies"] == []
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `.venv/bin/pytest core/bess/tests/unit/test_debug_findings.py -q`
Expected: FAIL — `ImportError: cannot import name 'reconcile_schedules'`.

- [ ] **Step 3: Implement.**

```python
# add to core/bess/debug_findings.py

@dataclass
class SlotDisagreement:
    period: int
    time: str
    occurrences: list[tuple[str, str, float]]  # (timestamp, intent, battery_action)
    intents: list[str]


def _period_to_time(period: int) -> str:
    return f"{period // 4:02d}:{(period % 4) * 15:02d}"


def reconcile_schedules(schedules: list[dict]) -> list[SlotDisagreement]:
    """Flag slots whose strategic_intent differs across today's runs."""
    by_period: dict[int, list[tuple[str, str, float]]] = {}
    for sched in schedules:
        ts = sched.get("timestamp", "")
        result = sched.get("optimization_result") or {}
        for pd in result.get("period_data", []):
            period = pd.get("period")
            dec = pd.get("decision") or {}
            intent = dec.get("strategic_intent")
            action = dec.get("battery_action") or 0.0
            if period is None or intent is None:
                continue
            by_period.setdefault(period, []).append((ts, intent, action))

    out = []
    for period in sorted(by_period):
        occ = by_period[period]
        intents = sorted({intent for _, intent, _ in occ})
        if len(intents) > 1:
            out.append(
                SlotDisagreement(
                    period=period,
                    time=_period_to_time(period),
                    occurrences=occ,
                    intents=intents,
                )
            )
    return out


def build_key_findings(schedules: list[dict], log_content: str) -> dict:
    disagreements = reconcile_schedules(schedules)
    anomalies = summarize_log_anomalies(log_content)
    return {
        "disagreements": disagreements,
        "anomalies": anomalies,
        "clean": not disagreements and not anomalies,
    }
```

- [ ] **Step 4: Run the tests.**

Run: `.venv/bin/pytest core/bess/tests/unit/test_debug_findings.py -q`
Expected: 6 passed.

- [ ] **Step 5: Commit.**

```bash
git add core/bess/debug_findings.py core/bess/tests/unit/test_debug_findings.py
git commit -m "feat: cross-run schedule reconciliation + build_key_findings"
```

---

### Task 3: Populate `key_findings` in the exporter

**Files:**
- Modify: `core/bess/debug_data_exporter.py` (`DebugDataExport` dataclass ~line 287;
  `aggregate_all_data` ~line 374)
- Test: `core/bess/tests/unit/test_debug_findings.py` (one integration-style test)

**Interfaces:**
- Consumes: `build_key_findings` (Task 2).
- Produces: `DebugDataExport.key_findings: dict` populated from `self.schedules`
  (serialized runs) and `self.todays_log_content`.

- [ ] **Step 1: Add the field.** In `DebugDataExport` (after `ha_ws_discovery`), add:

```python
    key_findings: dict = field(default_factory=dict)
```

- [ ] **Step 2: Populate it in `aggregate_all_data`.** After the `DebugDataExport(...)`
  instance is built (it needs `schedules` and `todays_log_content` already set),
  compute and attach findings. Locate the `return DebugDataExport(...)` /
  construction in `aggregate_all_data` and set `key_findings` from the same inputs:

```python
from .debug_findings import build_key_findings  # top-of-file import

# where the export object is assembled (it already has schedules + todays_log_content):
export.key_findings = build_key_findings(export.schedules, export.todays_log_content)
return export
```

If `aggregate_all_data` constructs and returns in one expression, assign to a local
`export` first, then set `export.key_findings`, then return it.

- [ ] **Step 3: Write the test.**

```python
def test_build_key_findings_surfaces_the_15_45_case():
    schedules = [
        _sched("2026-06-28 10:31:00", 63, "BATTERY_EXPORT", -0.1),
        _sched("2026-06-28 11:31:00", 63, "SOLAR_EXPORT", -0.0),
    ]
    log = (
        "2026-06-28 10:31:00 | ERROR | core.bess.influxdb_helper:519 - "
        "Error connecting to InfluxDB: Max retries exceeded\n"
    )
    result = build_key_findings(schedules, log)
    assert result["clean"] is False
    assert result["disagreements"][0].time == "15:45"
    assert result["anomalies"][0].category == "network"
```

- [ ] **Step 4: Run the tests + quality gate.**

Run: `.venv/bin/pytest core/bess/tests/unit/test_debug_findings.py -q && ./scripts/quality-check.sh`
Expected: tests pass; quality gate green.

- [ ] **Step 5: Commit.**

```bash
git add core/bess/debug_data_exporter.py core/bess/tests/unit/test_debug_findings.py
git commit -m "feat: attach key_findings to DebugDataExport"
```

---

### Task 4: Render Key Findings at the top; demote raw data

**Files:**
- Modify: `core/bess/debug_report_formatter.py` (`format_report` ~line 19;
  `_format_health_status` ~line 86; `_format_schedules` ~line 400)

**Interfaces:**
- Consumes: `export.key_findings` (Task 3).

- [ ] **Step 1: Add `_format_key_findings`.**

```python
    def _format_key_findings(self, export: DebugDataExport) -> str:
        kf = export.key_findings or {}
        lines = ["## ⚠️ Key Findings (auto-generated — read first)"]
        if kf.get("clean", False) or (not kf.get("disagreements") and not kf.get("anomalies")):
            lines.append("\nNo cross-run disagreements or log anomalies detected.")
            return "\n".join(lines)

        disagreements = kf.get("disagreements", [])
        if disagreements:
            lines.append("\n### Cross-run schedule disagreements")
            for d in disagreements:
                lines.append(
                    f"- Period {d.period} ({d.time}): {', '.join(d.intents)} "
                    f"across {len(d.occurrences)} runs — explain WHY runs differ; "
                    f"do NOT conclude it didn't happen."
                )

        anomalies = kf.get("anomalies", [])
        if anomalies:
            lines.append("\n### Today's log anomalies (deduplicated)")
            for a in anomalies:
                lines.append(
                    f"- [{a.category}] {a.source} ×{a.count} "
                    f"({a.first_ts} → {a.last_ts}): {a.sample}"
                )
        return "\n".join(lines)
```

- [ ] **Step 2: Put it first in `format_report`.** In the section list assembled by
  `format_report` (~line 30), insert `self._format_key_findings(export)` immediately
  after `self._format_header(export)`.

- [ ] **Step 3: Caption the health snapshot as point-in-time.** In
  `_format_health_status`, change the heading line `## System Health Status` to:

```python
        summary = f"""## System Health Status (point-in-time snapshot at export)

*This reflects health at export time only. For problems earlier today, see Key
Findings (top) and System Logs (bottom).*
"""
```

(keep the rest of the method unchanged).

- [ ] **Step 4: Move the full schedule JSON to the bottom.** In `_format_schedules`,
  remove the `details` (`<details>Full Schedule JSON…`) block from its return value
  (return only `summary_text + econ_block + Period Decisions table`). Add a new
  `_format_raw_schedule_json(export)` method that returns that `<details>` block, and
  append it LAST in `format_report` (after `_format_logs`).

```python
    def _format_raw_schedule_json(self, export: DebugDataExport) -> str:
        return f"""## Raw Schedule JSON (deep debugging)

<details>
<summary>Full Schedule JSON (all runs)</summary>

```json
{self._format_json(export.schedules)}
```

</details>"""
```

- [ ] **Step 5: Test the rendering end to end.**

Run:
```bash
.venv/bin/python -c "
from core.bess.debug_report_formatter import DebugReportFormatter
from core.bess.debug_data_exporter import DebugDataExport
from core.bess.debug_findings import build_key_findings
sched=[{'timestamp':'2026-06-28 10:31:00','optimization_result':{'period_data':[{'period':63,'decision':{'strategic_intent':'BATTERY_EXPORT','battery_action':-0.1}}]}},
       {'timestamp':'2026-06-28 11:31:00','optimization_result':{'period_data':[{'period':63,'decision':{'strategic_intent':'SOLAR_EXPORT','battery_action':-0.0}}]}}]
kf=build_key_findings(sched,'2026-06-28 10:31:00 | ERROR | core.bess.influxdb_helper:519 - Max retries exceeded')
print('Period 63' in DebugReportFormatter()._format_key_findings(type('E',(),{'key_findings':kf})()))
"
```
Expected: `True`.

- [ ] **Step 6: Quality gate + commit.**

```bash
./scripts/quality-check.sh
git add core/bess/debug_report_formatter.py
git commit -m "feat: render Key Findings at top, demote raw logs/JSON to bottom"
```

---

### Task 5: Include findings in AI-chat context; drop the raw log dump

**Files:**
- Modify: `backend/ai_chat.py` (`_gather_context` ~line 725)
- Test: `backend/tests/test_ai_chat.py`

**Interfaces:**
- Consumes: `export.key_findings` (Task 3).

- [ ] **Step 1: Read `_gather_context`** to see how it builds the context string from
  the export (it already calls the exporter). Identify where the log content is added.

- [ ] **Step 2: Prepend findings, exclude raw logs.** In `_gather_context`, render the
  key findings (reuse the formatter's `_format_key_findings`, or format inline) at the
  START of the context, and ensure the raw `todays_log_content` dump is NOT included
  (the findings replace it for the chat path).

- [ ] **Step 3: Add a test** asserting the gathered context contains the Key Findings
  heading and does NOT contain the full raw log body. Follow the existing patterns in
  `backend/tests/test_ai_chat.py` for constructing a fake system_manager/export.

- [ ] **Step 4: Run tests.**

Run: `.venv/bin/pytest backend/tests/test_ai_chat.py -q`
Expected: pass.

- [ ] **Step 5: Quality gate + commit.**

```bash
./scripts/quality-check.sh
git add backend/ai_chat.py backend/tests/test_ai_chat.py
git commit -m "feat: surface key findings in AI-chat context, drop raw log dump"
```

---

### Task 6: Validate end to end

**Files:** none (validation only).

- [ ] **Step 1: Run the full fast suite.**

Run: `.venv/bin/pytest -m "not slow" -q`
Expected: green.

- [ ] **Step 2: Re-invoke the analyst** on `docs/bess-debug-2026-06-28-113159.md`
  with the original `docs/dialogue.txt` question (regenerate the bundle if needed so
  it has the new top section). Confirm, on the FIRST attempt, the agent:
  1. Reads the Key Findings section and reports the 15:45 BATTERY_EXPORT vs
     SOLAR_EXPORT disagreement without being prompted.
  2. Flags the InfluxDB-outage anomaly rather than reporting "system OK".
  3. Gives the marginal `shadow_price > sell` loss verdict and cites `_compute_reward`.

- [ ] **Step 3: If it still anchors,** the gap is renderer prominence/wording, not
  data — adjust `_format_key_findings` phrasing and re-run. Do not add optimizer logic.

---

## Self-Review

- **Spec coverage (Part 5):** Key Findings section → Tasks 1-4; log rollup (dedup) →
  Task 1; reconciliation → Task 2; exporter wiring → Task 3; bundle restructure +
  health caption → Task 4; AI-chat parity + token reduction → Task 5; validation →
  Task 6.
- **Placeholder scan:** all code steps show real code; tests have real assertions.
  Task 5 steps 1-3 describe inspection-then-edit because `_gather_context`'s exact
  body must be read first; the assertions to add are specified.
- **Type consistency:** `LogAnomaly` / `SlotDisagreement` field names and the
  `build_key_findings` dict keys (`disagreements`, `anomalies`, `clean`) are used
  identically across Tasks 2-5; `export.schedules` shape is the same one the exporter
  already produces (`asdict` of `StoredSchedule`).
