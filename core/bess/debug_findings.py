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
    (
        "network",
        re.compile(
            r"Max retries|Connection error|Failed to establish a new connection"
            r"|Failed to load batch data"
        ),
    ),
    (
        "data_gap",
        re.compile(r"Historical data unavailable|No InfluxDB data|missing period"),
    ),
    (
        "restart",
        re.compile(r"Starting BESS Manager|BESS Manager started|Application startup"),
    ),
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
