"""Debug-log replay must keep the planned loads the optimizer had (#882).

A planned-consumption template typically drops a block once it has passed, so
the entity snapshot in a debug bundle no longer holds the loads for periods that
had already elapsed at export time. Replaying such a bundle at an earlier time
(``./mock-run.sh <bundle> HH:MM``) then planned those periods without the load
the optimizer actually saw, and the incident could not be reproduced (#881).

The bundle still records what the optimizer planned against: every period's
final ``consumption_breakdown`` in the Prediction Snapshots. These tests assert
the outcome -- the overlay the replayed entity produces, composed through the
real ``apply_overlay`` -- rather than the shape of the rebuilt blocks.
"""

import importlib.util
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from core.bess.consumption_overlay import (
    apply_overlay,
    parse_overlay_blocks,
    period_starts_from,
)
from core.bess.tests.debug_log_parser import parse_debug_log

_REPO_ROOT = Path(__file__).resolve().parents[4]
_TZ = ZoneInfo("Europe/Stockholm")
_ENTITY = "sensor.bess_planned_consumption"
_EXPORT_PERIOD = 4  # export at 01:00 -> periods 0..3 have passed
_HORIZON = 8
_RESIDUAL = 0.5


def _load_from_debug_log() -> Any:
    """Import scripts/mock_ha/scenarios/from_debug_log.py (not a package)."""
    path = _REPO_ROOT / "scripts" / "mock_ha" / "scenarios" / "from_debug_log.py"
    spec = importlib.util.spec_from_file_location("from_debug_log", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _starts() -> list[datetime]:
    """Period starts for the horizon, plus the boundary after its last period."""
    return period_starts_from(datetime(2026, 11, 10, tzinfo=_TZ), _HORIZON + 1)


def _block(index: int, energy: float, mode: str = "add") -> dict:
    return {
        "start": _starts()[index].isoformat(),
        "end": _starts()[index + 1].isoformat(),
        "energy_kwh": energy,
        "mode": mode,
    }


def _period(index: int, planned: float) -> dict:
    return {
        "period": index,
        "consumption_breakdown": {
            "residual": _RESIDUAL,
            "planned": planned,
            "total": _RESIDUAL + planned,
        },
    }


# What the optimizer planned against for each period that has since passed.
# Period 2 is covered by a "set" block in the exported entity, so the replayed
# load there must account for set semantics, not just sum block energies.
_PLANNED_PAST = {0: 2.3, 1: 2.3, 2: 1.0, 3: 0.1}
_FUTURE_EXTRA = 0.1  # the small blocks still present in the entity


def _write_bundle(path: Path, *, with_snapshots: bool = True) -> None:
    entity_blocks = [_block(i, _FUTURE_EXTRA) for i in range(_HORIZON) if i != 2]
    entity_blocks.append(_block(2, 0.4, mode="set"))

    snapshots = []
    for op in range(_EXPORT_PERIOD):
        if op == 0:
            delta = [_period(i, _PLANNED_PAST.get(i, 9.9)) for i in range(_HORIZON)]
        else:
            # Field-level delta: only the planned/total fields that moved.
            delta = [
                {
                    "period": op,
                    "consumption_breakdown": {
                        "planned": _PLANNED_PAST[op],
                        "total": _RESIDUAL + _PLANNED_PAST[op],
                    },
                }
            ]
        snapshots.append(
            {
                "snapshot_timestamp": _starts()[op].isoformat(),
                "optimization_period": op,
                "predicted_periods_dropped": [op - 1] if op else [],
                "predicted_periods_delta": delta,
            }
        )

    sections = [
        "## System Information",
        "```json",
        json.dumps(
            {
                "timezone": "Europe/Stockholm",
                "export_timestamp": _starts()[_EXPORT_PERIOD].isoformat(),
            }
        ),
        "```",
        "## BESS Configuration",
        "```json",
        json.dumps({"sensors": {"shared": {"consumption_overlay": _ENTITY}}}),
        "```",
        "## Entity Snapshot",
        "```json",
        json.dumps(
            {
                _ENTITY: {
                    "entity_id": _ENTITY,
                    "state": "1",
                    "attributes": {"blocks": entity_blocks},
                }
            }
        ),
        "```",
        "## Raw Schedule JSON (deep debugging)",
        "```json",
        json.dumps([{"optimization_period": _EXPORT_PERIOD}]),
        "```",
    ]
    if with_snapshots:
        sections += [
            "## Prediction Snapshots",
            "```json",
            json.dumps(snapshots),
            "```",
        ]
    path.write_text("\n".join(sections) + "\n", encoding="utf-8")


def _replayed_overlay(sensors: dict) -> list[float]:
    """Net load the replayed entity adds to each period, via the real overlay."""
    blocks = parse_overlay_blocks(sensors[_ENTITY]["attributes"]["blocks"])
    result = apply_overlay([_RESIDUAL] * _HORIZON, _starts()[:_HORIZON], blocks)
    return [v - _RESIDUAL for v in result.values]


def test_replay_restores_planned_load_for_periods_passed_at_export(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bess-debug-2026-11-10-010000.md"
    _write_bundle(bundle)
    log = parse_debug_log(str(bundle))
    sensors = json.loads(json.dumps(log.entity_snapshot))

    rebuilt = _load_from_debug_log().rebuild_expired_overlay_blocks(log, sensors)

    # Period 3's planned load is exactly what the exported entity still
    # declares there, so only periods 0-2 need a block.
    assert rebuilt == 3
    overlay = _replayed_overlay(sensors)
    for period, planned in _PLANNED_PAST.items():
        assert overlay[period] == pytest.approx(planned), period
    # Periods from the export onward keep exactly what the entity declared.
    for period in range(_EXPORT_PERIOD, _HORIZON):
        assert overlay[period] == pytest.approx(_FUTURE_EXTRA), period


def test_bundle_without_prediction_snapshots_leaves_entity_untouched(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bess-debug-2026-11-10-010000.md"
    _write_bundle(bundle, with_snapshots=False)
    log = parse_debug_log(str(bundle))
    sensors = json.loads(json.dumps(log.entity_snapshot))

    rebuilt = _load_from_debug_log().rebuild_expired_overlay_blocks(log, sensors)

    assert rebuilt == 0
    assert sensors == log.entity_snapshot
