"""Octoplus Power Down session outcome logging.

Design: docs/superpowers/specs/2026-09-13-octopus-power-down-export-pulse-design.md
section 6. The hypothesis that exporting during a Power Down session improves
its odds of being scored isn't established (see the design's evidence table),
so every session's planned vs. realized flows and its eventual Octopoints
outcome are recorded here to build up real evidence across installs.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PowerDownSessionOutcome:
    """One Power Down (Octopus ``TURN_DOWN``) session's outcome record.

    Built once every period of the session is recorded in
    ``HistoricalDataStore`` (i.e. the session has ended), persisted through
    ``DailyViewStore``, and never cleared. ``rewarded_octopoints`` starts
    ``None`` and is filled in later, in place, once Octopus settles the
    session (observed days later).
    """

    session_start: datetime
    session_end: datetime
    target_export_kwh: float
    planned_import_kwh: float
    planned_export_kwh: float
    realized_import_kwh: float
    realized_export_kwh: float
    target_met: bool
    export_curtailment_active: bool
    rewarded_octopoints: int | None


def match_rewarded_octopoints(
    joined_events: list[dict] | None, session_start: datetime
) -> int | None:
    """Find ``rewarded_octopoints`` for one session from the events-entity payload.

    ``joined_events`` is the ``event.…_octoplus_power_down_events`` entity's
    ``joined_events`` attribute. It can be ``None`` right after an
    integration reload -- treated as "nothing reported yet", not an error.
    Matched by ``start`` compared as aware datetimes (the payload's ISO
    string parses to one). A session Octopus hasn't scored yet reports
    ``rewarded_octopoints: null`` on its own matched event, which is
    indistinguishable from "no matching event found" -- both mean "not
    known yet", so both return ``None``.
    """
    if not joined_events:
        return None
    for event in joined_events:
        raw_start = event.get("start")
        if not raw_start:
            continue
        try:
            event_start = datetime.fromisoformat(raw_start)
        except ValueError:
            continue
        if event_start == session_start:
            points = event.get("rewarded_octopoints")
            return int(points) if points is not None else None
    return None
