"""Prediction-snapshot delta encoding in the debug bundle (issue #555).

The bundle's largest section by far was `## Prediction Snapshots`: 6.78 MB of
9.04 MB on the reference export, because `_serialize_snapshots` deduped whole
snapshots rather than individual periods. One flipped period re-serialized the
entire remaining forecast, and a marginal period flips on nearly every cycle,
so 4,275 period objects were written to carry 314 periods' worth of change.

The section now carries field-level deltas: per snapshot, only the periods
that moved, and within those only the fields that moved. Two measurements
drove that shape, both taken by driving 96 real optimization runs through a
real BatterySystemManager rather than reasoning about fixtures:

- keying the delta on (intent, battery_action) as the issue proposed is
  LOSSY — 292 decisions moved while 3,073 period payloads did, because a
  period's SOE and economics shift when the DP changes *other* periods;
- emitting whole period objects for those 3,073 costs 3.06 MB against
  0.51 MB for field-level ones, since two or three of ~37 fields typically
  move.

These tests pin, at the outcome level:

1. **Size** — a realistic day's rendered section (`TestRenderedSectionSize`);
   the same fixture renders 6.63 MB through the pre-fix encoder.
2. **No information loss** — replaying the deltas reconstructs every
   snapshot's forecast, byte-identical to the un-deduped forecasts
   (`test_replaying_deltas_reconstructs_every_forecast`).
3. **Both readers** (`TestDownstreamReaders`) — `debug_log_parser` still
   ignores the section, and `extract_decision_evidence` replays deltas into
   full states instead of reading partial ones as whole periods.
"""

import importlib.util
import json
import re
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.bess.daily_view_builder import DailyView
from core.bess.debug_data_exporter import DebugDataAggregator
from core.bess.debug_report_formatter import DebugReportFormatter
from core.bess.models import DecisionData, EconomicData, EnergyData, PeriodData
from core.bess.prediction_snapshot import PredictionSnapshot
from core.bess.tests.debug_log_parser import parse_debug_log

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _load_extract_decision_evidence():
    """Import scripts/extract_decision_evidence.py (not an importable package)."""
    path = _REPO_ROOT / "scripts" / "extract_decision_evidence.py"
    spec = importlib.util.spec_from_file_location("extract_decision_evidence", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _period(period: int, intent: str, action: float) -> PeriodData:
    """A predicted period carrying the full field set a real forecast has."""
    return PeriodData(
        period=period,
        energy=EnergyData(
            solar_production=0.42,
            home_consumption=0.51,
            grid_imported=0.13,
            grid_exported=0.0,
            battery_charged=max(action, 0.0),
            battery_discharged=max(-action, 0.0),
            battery_soe_start=10.0 + period * 0.01,
            battery_soe_end=10.0 + period * 0.01 + action,
        ),
        timestamp=datetime(2026, 8, 12, period // 4, (period % 4) * 15),
        data_source="predicted",
        economic=EconomicData(
            buy_price=1.0631,
            sell_price=0.4612,
            hourly_cost=0.1234,
            grid_only_cost=0.2345,
        ),
        decision=DecisionData(
            strategic_intent=intent,
            battery_action=action,
            cost_basis=0.55,
            shadow_price=0.61,
        ),
    )


def _snapshot(hhmm: str, optimization_period: int, plan: dict[int, tuple]):
    """A PredictionSnapshot whose forecast is `plan` (period -> (intent, action))."""
    periods = [
        _period(p, intent, action) for p, (intent, action) in sorted(plan.items())
    ]
    return PredictionSnapshot(
        snapshot_timestamp=datetime(
            2026, 8, 12, int(hhmm[:2]), int(hhmm[3:]), tzinfo=None
        ),
        optimization_period=optimization_period,
        daily_view=DailyView(
            date=date(2026, 8, 12),
            periods=periods,
            total_savings=1.23,
            actual_count=96 - len(periods),
            predicted_count=len(periods),
        ),
        growatt_schedule=[],
        predicted_daily_savings=1.23,
    )


def _aggregator(snapshots) -> DebugDataAggregator:
    system = MagicMock()
    system.prediction_snapshot_store.get_all_snapshots_today.return_value = snapshots
    return DebugDataAggregator(system)


def _baseline_plan(size: int = 56, start: int = 40) -> dict[int, tuple]:
    return dict.fromkeys(range(start, start + size), ("IDLE", 0.0))


class TestPerPeriodDelta:
    """`predicted_periods_delta` carries only what moved since the last run."""

    def test_first_snapshot_carries_the_full_baseline(self):
        plan = _baseline_plan()
        out = _aggregator([_snapshot("06:00", 24, plan)])._serialize_snapshots()

        assert len(out[0]["predicted_periods_delta"]) == len(plan)

    def test_one_flipped_period_emits_one_period(self):
        """The whole point: a marginal period flipping must not re-serialize
        the other 55. Pre-fix this emitted the entire forecast."""
        plan = _baseline_plan()
        flipped = {**plan, 63: ("BATTERY_EXPORT", -1.5)}
        out = _aggregator(
            [_snapshot("06:00", 24, plan), _snapshot("06:15", 25, flipped)]
        )._serialize_snapshots()

        delta = out[1]["predicted_periods_delta"]
        assert [p["period"] for p in delta] == [63]
        assert delta[0]["decision"]["strategic_intent"] == "BATTERY_EXPORT"

    def test_unchanged_plan_emits_nothing(self):
        plan = _baseline_plan()
        out = _aggregator(
            [_snapshot("06:00", 24, plan), _snapshot("06:15", 25, dict(plan))]
        )._serialize_snapshots()

        assert out[1]["predicted_periods_delta"] == []

    def test_period_newly_entering_the_window_is_emitted(self):
        """A period the previous snapshot never covered is new information,
        not an unchanged one — it must survive the delta."""
        first = _baseline_plan(size=4, start=40)
        second = {**first, 44: ("GRID_CHARGING", 2.0)}
        out = _aggregator(
            [_snapshot("06:00", 24, first), _snapshot("06:15", 25, second)]
        )._serialize_snapshots()

        assert [p["period"] for p in out[1]["predicted_periods_delta"]] == [44]

    def test_same_decision_with_moved_soe_is_still_emitted(self):
        """A period can keep its decision while its SOE trajectory and
        economics move underneath it, because those depend on what the DP
        decided for *other* periods.

        Keying the delta on (intent, battery_action) alone therefore drops
        real input changes — the ones `bess-analyst` is documented to diff
        when explaining a run-to-run flip. Caught by driving 96 real
        optimization runs (issue #555): 2,588 period payloads moved while
        only 292 decisions did.
        """
        first = _snapshot("06:00", 24, _baseline_plan(size=3, start=40))
        second = _snapshot("06:15", 25, _baseline_plan(size=3, start=40))
        moved = second.daily_view.periods[1]
        moved.energy.battery_soe_start += 0.4
        moved.economic.buy_price += 0.05

        out = _aggregator([first, second])._serialize_snapshots()

        emitted = out[1]["predicted_periods_delta"]
        assert [p["period"] for p in emitted] == [moved.period]
        assert emitted[0]["economic"]["buy_price"] == pytest.approx(1.1131)

    def test_only_the_changed_fields_are_emitted(self):
        """The delta is field-level, not object-level: a period whose SOE
        moved carries that field, not all ~37 of them. This is what takes the
        section from 3.06 MB to 0.51 MB on a real 96-run day.
        """
        first = _snapshot("06:00", 24, _baseline_plan(size=3, start=40))
        second = _snapshot("06:15", 25, _baseline_plan(size=3, start=40))
        second.daily_view.periods[1].energy.battery_soe_start += 0.4

        out = _aggregator([first, second])._serialize_snapshots()

        emitted = out[1]["predicted_periods_delta"]
        assert len(emitted) == 1
        assert set(emitted[0]) == {"period", "energy"}
        assert set(emitted[0]["energy"]) == {"battery_soe_start"}

    def test_first_appearance_of_a_period_carries_everything(self):
        """A delta is only replayable onto a baseline, so a period's first
        appearance must be complete — including one entering mid-day."""
        first = _baseline_plan(size=2, start=40)
        second = {**first, 42: ("GRID_CHARGING", 2.0)}
        out = _aggregator(
            [_snapshot("06:00", 24, first), _snapshot("06:15", 25, second)]
        )._serialize_snapshots()

        new_period = out[1]["predicted_periods_delta"][0]
        assert new_period["period"] == 42
        assert set(new_period) == set(out[0]["predicted_periods_delta"][0])

    def test_realized_periods_are_reported_as_dropped(self):
        """The predicted window shrinks as periods realize. A period leaving
        the window is not "unchanged" — a reader replaying deltas has no other
        way to learn it left, and would carry it forward as a ghost forever.
        """
        out = _aggregator(
            [
                _snapshot("10:00", 40, _baseline_plan(size=56, start=40)),
                _snapshot("10:15", 44, _baseline_plan(size=52, start=44)),
            ]
        )._serialize_snapshots()

        assert out[0]["predicted_periods_dropped"] == []
        assert out[1]["predicted_periods_dropped"] == [40, 41, 42, 43]

    def test_replaying_deltas_reconstructs_every_forecast(self):
        """No information loss: delta replay == the un-deduped forecasts.

        Compared against `compact=False`, which serializes every snapshot's
        full forecast, so this is a real equivalence check rather than a
        restatement of the delta logic.

        The window SHRINKS across these snapshots, which is what a real day
        does — periods realize into actuals and leave the forecast. An
        earlier version of this test held the period set fixed across all
        four fixtures and therefore could not catch the reconstruction
        carrying realized periods forward as ghosts.
        """
        plans = [
            _baseline_plan(size=56, start=40),
            {**_baseline_plan(size=55, start=41), 63: ("BATTERY_EXPORT", -1.5)},
            {
                **_baseline_plan(size=54, start=42),
                63: ("BATTERY_EXPORT", -1.5),
                70: ("IDLE", 0.0),
            },
            {**_baseline_plan(size=53, start=43), 50: ("GRID_CHARGING", 2.0)},
        ]
        snapshots = [
            _snapshot(f"10:{i * 15:02d}", 40 + i, plan) for i, plan in enumerate(plans)
        ]
        agg = _aggregator(snapshots)

        deltas = agg._serialize_snapshots(compact=True)
        full = agg._serialize_snapshots(compact=False)

        # Replay with the shipped reader's own merge helper, so this pins the
        # algorithm readers actually run rather than a test-local restatement.
        merge = _load_extract_decision_evidence()._merge_delta

        reconstructed: dict[int, dict] = {}
        for i, sn in enumerate(deltas):
            for p in sn["predicted_periods_delta"]:
                key = p["period"]
                reconstructed[key] = merge(reconstructed.get(key, {}), p)
            for period in sn["predicted_periods_dropped"]:
                del reconstructed[period]
            expected = {
                p["period"]: p
                for p in full[i]["daily_view"]["periods"]
                if p["data_source"] == "predicted"
            }
            assert reconstructed == expected, f"snapshot {i} did not reconstruct"


class TestRenderedSectionSize:
    """The deliverable: a realistic day's section is ~1 MB-scale, not 7 MB."""

    def _render(self, snapshots) -> str:
        agg = _aggregator(snapshots)
        export = MagicMock()
        export.compact = True
        export.snapshots = agg._serialize_snapshots(compact=True)
        export.snapshots_summary = {
            "total_snapshots": len(snapshots),
            "first_snapshot": "2026-08-12T06:00:00",
            "last_snapshot": "2026-08-12T22:30:00",
        }
        return DebugReportFormatter()._format_snapshots(export)

    def _realistic_day(self):
        """83 runs over the day, ~56-period forecast — the measured shape of
        the reference bundle in issue #555.

        Two kinds of churn, both measured on 96 real optimization runs:
        3 decisions flip per run (which alone defeated the pre-fix
        whole-snapshot dedup on 75 of 83 snapshots), and about a third of
        periods have their SOE/economics move without their decision
        changing, because those depend on what the DP decided elsewhere.
        Modelling only the first kind makes this section look ~10x cheaper
        than it really is.
        """
        snapshots = []
        plan = _baseline_plan()
        for i in range(83):
            for k in range(3):
                p = 40 + (i * 7 + k * 11) % 56
                plan = {**plan, p: ("BATTERY_EXPORT", -0.5 - k - i * 0.01)}
            snapshot = _snapshot(f"{6 + i // 6:02d}:{(i % 6) * 10:02d}", 24 + i, plan)
            for n, pd in enumerate(snapshot.daily_view.periods):
                if (n + i) % 3 == 0:
                    pd.energy.battery_soe_start += i * 0.001
                    pd.economic.hourly_cost += i * 0.0001
            snapshots.append(snapshot)
        return snapshots

    def test_realistic_day_section_stays_well_under_the_prefix_size(self):
        """Pre-fix this section was 6.78 MB for the same 83 runs (~1,663 bytes
        per period object x 4,275 objects); this exact fixture renders 6.63 MB
        through the pre-fix encoder and 0.37 MB through this one. The budget
        sits well above the expected size so it pins the order of magnitude,
        not the exact bytes -- but well under an object-level delta (2.9 MB on
        this fixture), so a regression to whole-object emission fails here.
        """
        rendered = self._render(self._realistic_day())
        assert (
            len(rendered.encode()) < 800_000
        ), f"snapshots section is {len(rendered.encode()) / 1e6:.2f} MB"

    def test_period_objects_are_single_line(self):
        """Compact encoding: one line per period object, not ~45 pretty-printed
        lines. Keeps the section diffable and greppable while small."""
        rendered = self._render(self._realistic_day())
        block = re.search(r"```json\n(.*?)\n```", rendered, re.DOTALL).group(1)

        period_lines = [ln for ln in block.splitlines() if '"period":' in ln]
        assert period_lines, "no period objects in the rendered section"
        for line in period_lines:
            assert line.rstrip(",").endswith(
                "}"
            ), f"period object spans lines: {line[:80]}"


class TestDownstreamReaders:
    """The two bundle readers, against the new encoding.

    `debug_log_parser` never parsed this section and still doesn't.
    `extract_decision_evidence` did, and had to learn to replay deltas —
    reading a field-level delta as if it were a whole period reports a period
    as having no intent or no price merely because that field didn't move.
    """

    def _bundle_text(self) -> str:
        plan = _baseline_plan(size=6, start=60)
        flipped = {**plan, 63: ("BATTERY_EXPORT", -1.5)}
        agg = _aggregator(
            [_snapshot("06:00", 24, plan), _snapshot("06:15", 25, flipped)]
        )
        export = MagicMock()
        export.compact = True
        export.snapshots = agg._serialize_snapshots(compact=True)
        export.snapshots_summary = {
            "total_snapshots": 2,
            "first_snapshot": "2026-08-12T06:00:00",
            "last_snapshot": "2026-08-12T06:15:00",
        }
        return DebugReportFormatter()._format_snapshots(export)

    def test_section_is_valid_json(self):
        block = re.search(r"```json\n(.*?)\n```", self._bundle_text(), re.DOTALL).group(
            1
        )
        parsed = json.loads(block)

        assert [p["period"] for p in parsed[1]["predicted_periods_delta"]] == [63]

    def test_extract_decision_evidence_replays_deltas_into_full_states(self):
        """The flip snapshot's delta carries only `decision`; `sell_price`
        lives in the baseline. Both must show up on the same reconstructed
        state, or cross-run reconciliation reports a slot with a price and no
        intent (or the reverse) and invents a disagreement.
        """
        module = _load_extract_decision_evidence()

        found = module.parse_json_economics(self._bundle_text(), 63)

        flipped = [e for e in found if e["intent"] == "BATTERY_EXPORT"]
        assert flipped, "delta-only decision change was not reconstructed"
        assert flipped[-1]["sell_price"] == 0.4612
        assert flipped[-1]["soe_start"] is not None

    def test_extract_decision_evidence_still_reads_pre_555_bundles(self):
        """Bundles already attached to issues are regression fixtures: they
        have whole `predicted_periods`, no delta key, and must keep working
        through the untouched recursive path."""
        module = _load_extract_decision_evidence()
        legacy = json.dumps(
            [
                {
                    "snapshot_timestamp": "2026-08-12T06:00:00",
                    "predicted_periods": [
                        {
                            "period": 63,
                            "decision": {"strategic_intent": "GRID_CHARGING"},
                            "economic": {"sell_price": 0.31, "buy_price": 0.9},
                        }
                    ],
                }
            ]
        )

        found = module.parse_json_economics(f"```json\n{legacy}\n```", 63)

        assert [e["intent"] for e in found] == ["GRID_CHARGING"]
        assert found[0]["sell_price"] == 0.31

    def test_debug_log_parser_does_not_mistake_snapshots_for_a_schedule(self, tmp_path):
        """The parser has no snapshot branch; the section must stay inert to
        it, and must not swallow a following section's JSON."""
        bundle = tmp_path / "bundle.md"
        bundle.write_text(
            self._bundle_text()
            + "\n\n### Battery Settings\n\n```json\n"
            + json.dumps({"total_capacity": 30.0})
            + "\n```\n"
        )

        parsed = parse_debug_log(str(bundle))

        assert parsed.battery_settings == {"total_capacity": 30.0}
        assert parsed.last_schedule == {}
