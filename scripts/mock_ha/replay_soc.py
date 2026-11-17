"""Battery SOC a debug-log replay should present at an earlier time (#889).

A scenario's entity snapshot holds every value as it was at export, so
``./mock-run.sh <scenario> HH:MM`` alone would replay an earlier time from the
export-time battery level. The bundle's historical periods record where the
battery actually started each period; this resolves that into the state the
mock Home Assistant should serve for the battery SOC entity.

Runs on the host (it needs ``core``), and prints the overrides as JSON for
``mock-run.sh`` to hand to the mock-ha container:

    .venv/bin/python scripts/mock_ha/replay_soc.py <scenario.json> HH:MM
"""

import json
import re
import sys
from datetime import UTC, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root))

from core.bess.consumption_overlay import period_starts_from  # noqa: E402
from core.bess.settings_store import flatten_sensors  # noqa: E402

# Enough quarter-hours to cover the longest (fall-back) day.
_MAX_PERIODS_PER_DAY = 100


def _period_index(moment: datetime) -> int:
    day_start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    starts = period_starts_from(day_start, _MAX_PERIODS_PER_DAY)
    # Same-zone datetimes compare by wall clock, which misorders the fall-back
    # day's repeated hour; UTC compares real time.
    instant = moment.astimezone(UTC)
    return max(i for i, s in enumerate(starts) if s.astimezone(UTC) <= instant)


def replay_soc_overrides(scenario: dict, replay_time: str) -> dict[str, str]:
    """Return the battery SOC entity state for a replay at ``replay_time``.

    Args:
        scenario: A mock_ha scenario (as written by ``from_debug_log.py``).
        replay_time: ``HH:MM`` on the scenario date, in the scenario timezone.

    Returns:
        ``{battery_soc_entity_id: soc_percent}`` when the replay period precedes
        the export period and the bundle recorded its starting level; ``{}``
        otherwise, in which case the export-time snapshot is served unchanged.
        A replay before export with no recorded level is reported on stderr.

    """
    bess_config = scenario.get("bess_config") or {}
    entity_id = flatten_sensors(bess_config.get("sensors", {})).get("battery_soc")
    if not entity_id:
        print(
            "Note: scenario maps no battery_soc sensor -- no battery SOC to replay.",
            file=sys.stderr,
        )
        return {}

    tz = ZoneInfo(scenario["timezone"])
    match = re.fullmatch(
        r"@(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", scenario["mock_time"]
    )
    if match is None:
        raise ValueError(f"Unrecognised mock_time: {scenario['mock_time']!r}")
    export_dt = datetime.fromisoformat(match.group(1)).replace(tzinfo=tz)
    replay_dt = datetime.combine(
        export_dt.date(), time.fromisoformat(replay_time), tzinfo=tz
    )

    period = _period_index(replay_dt)
    if period >= _period_index(export_dt):
        return {}

    snapshot = scenario["sensors"][entity_id]["state"]
    history = scenario.get("historical_periods") or []
    recorded = history[period] if period < len(history) else None
    if recorded is None:
        print(
            f"WARNING: the bundle has no recorded battery level for period {period} "
            f"({replay_time}) -- {entity_id} stays at its export-time value "
            f"{snapshot}%, which the battery may not have had then.",
            file=sys.stderr,
        )
        return {}

    soe_start = recorded["energy"]["battery_soe_start"]
    capacity = bess_config["battery"]["total_capacity"]
    soc = str(round(soe_start / capacity * 100, 4))
    print(
        f"Battery SOC for {replay_time}: {entity_id} = {soc}% "
        f"(period {period} started at {soe_start} kWh; export-time value {snapshot}%).",
        file=sys.stderr,
    )
    return {entity_id: soc}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(f"Usage: {sys.argv[0]} <scenario.json> HH:MM")
    with open(sys.argv[1], encoding="utf-8") as f:
        loaded = json.load(f)
    print(json.dumps(replay_soc_overrides(loaded, sys.argv[2])))
