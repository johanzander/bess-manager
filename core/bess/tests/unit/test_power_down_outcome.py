"""Octoplus Power Down: session outcome logging.

Design section 6: after each session ends, BESS logs one INFO line and
persists one outcome record (planned vs realized import/export, whether the
export target was met), later updated in place with rewarded_octopoints once
Octopus settles the session (days later).
See docs/superpowers/specs/2026-09-13-octopus-power-down-export-pulse-design.md.
"""

import logging
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.calendar_windows import CalendarWindow
from core.bess.daily_view_store import DailyViewStore
from core.bess.debug_data_exporter import DebugDataAggregator
from core.bess.models import DecisionData, EnergyData, OptimizationResult, PeriodData
from core.bess.power_down_outcome import PowerDownSessionOutcome
from core.bess.price_manager import MockSource
from core.bess.time_utils import TIMEZONE

_DEFAULT_OPTIONS = {"inverter": {"platform": "growatt_server_min"}}

# 18:00-19:00 -> periods 72-75 of a 96-period day (period i = 00:00 + i*15min).
SESSION_START = datetime(2026, 9, 13, 18, 0, tzinfo=TIMEZONE)
SESSION_END = datetime(2026, 9, 13, 19, 0, tzinfo=TIMEZONE)
SESSION_PERIODS = [72, 73, 74, 75]

ENABLED_OCTOPUS_CONFIG: dict[str, Any] = {
    "provider": "octopus",
    "octopus": {
        "power_down_enabled": True,
        "power_down_calendar_entity": "calendar.octopus_energy_x_octoplus_power_down",
        "power_down_export_kw": 1.0,
        "power_down_export_minutes": 15,
        "power_down_events_entity": "",
        "free_import_price": 0.0,
        "power_up_calendar_entity": "",
    },
}


@pytest.fixture
def system(mock_controller: Any) -> BatterySystemManager:
    return BatterySystemManager(
        controller=mock_controller,
        price_source=MockSource([1.0] * 96),
        addon_options=_DEFAULT_OPTIONS,
    )


def _enable_power_down(system: BatterySystemManager, **overrides: Any) -> None:
    config = {
        "provider": "octopus",
        "octopus": {**ENABLED_OCTOPUS_CONFIG["octopus"], **overrides},
    }
    system._energy_provider_config = config


def _set_session_window(
    system: BatterySystemManager,
    start: datetime = SESSION_START,
    end: datetime = SESSION_END,
) -> None:
    system._price_manager.get_power_down_windows = lambda: [  # type: ignore[method-assign]
        CalendarWindow(start=start, end=end)
    ]


def _freeze(mock_datetime: Any, fixed_now: datetime) -> None:
    mock_datetime.now.return_value = fixed_now
    mock_datetime.combine = datetime.combine


def _period_data(period: int, grid_imported: float, grid_exported: float) -> PeriodData:
    return PeriodData(
        period=period,
        energy=EnergyData(
            solar_production=0.0,
            home_consumption=0.1,
            battery_charged=0.0,
            battery_discharged=0.1,
            grid_imported=grid_imported,
            grid_exported=grid_exported,
            battery_soe_start=5.0,
            battery_soe_end=5.0,
        ),
        timestamp=time_utils.period_index_to_timestamp(period),
        data_source="predicted",
        decision=DecisionData(),
    )


def _store_planned_schedule(
    system: BatterySystemManager,
    periods: dict[int, tuple[float, float]],
    optimization_period: int = 68,
) -> None:
    """Store one schedule -- as store_schedule does every quarterly tick --
    with the given {period: (grid_imported, grid_exported)} planned flows."""
    period_data = [
        _period_data(p, imported, exported)
        for p, (imported, exported) in periods.items()
    ]
    system.schedule_store.store_schedule(
        OptimizationResult(input_data={}, period_data=period_data),
        optimization_period=optimization_period,
    )


def _record_realized(
    system: BatterySystemManager,
    period: int,
    grid_imported: float,
    grid_exported: float,
) -> None:
    system.historical_store.record_period(
        period,
        PeriodData(
            period=period,
            energy=EnergyData(
                solar_production=0.0,
                home_consumption=0.1,
                battery_charged=0.0,
                battery_discharged=0.1 + grid_exported,
                grid_imported=grid_imported,
                grid_exported=grid_exported,
                battery_soe_start=5.0,
                battery_soe_end=5.0,
            ),
            timestamp=datetime.now(tz=TIMEZONE),
            data_source="actual",
            decision=DecisionData(),
        ),
    )


class TestSessionOutcomeRecording:
    @patch("core.bess.time_utils.datetime")
    def test_records_outcome_after_session_ends(
        self,
        mock_datetime: Any,
        system: BatterySystemManager,
        tmp_path: Any,
        caplog: Any,
    ) -> None:
        system.daily_view_store = DailyViewStore(persist_dir=tmp_path)
        _enable_power_down(system)
        _set_session_window(system)

        # The plan "in effect when the session started": created at 17:45,
        # before the 18:00 session start.
        _freeze(mock_datetime, datetime(2026, 9, 13, 17, 45, tzinfo=TIMEZONE))
        _store_planned_schedule(system, dict.fromkeys(SESSION_PERIODS, (0.1, 0.0)))

        # Realized: the first period exports 0.3 (meets the 0.25 kWh
        # target); the rest of the session records no flows at all.
        _record_realized(system, 72, grid_imported=0.0, grid_exported=0.3)

        # Now the session has fully ended.
        _freeze(mock_datetime, datetime(2026, 9, 13, 19, 15, tzinfo=TIMEZONE))

        with caplog.at_level(logging.INFO):
            system._record_power_down_session_outcomes()

        assert len(system._power_down_session_outcomes) == 1
        outcome = system._power_down_session_outcomes[0]
        assert outcome.session_start == SESSION_START
        assert outcome.session_end == SESSION_END
        assert outcome.target_export_kwh == pytest.approx(0.25)
        assert outcome.planned_import_kwh == pytest.approx(0.4)
        assert outcome.planned_export_kwh == pytest.approx(0.0)
        assert outcome.realized_import_kwh == pytest.approx(0.0)
        assert outcome.realized_export_kwh == pytest.approx(0.3)
        assert outcome.target_met is True
        assert outcome.rewarded_octopoints is None
        assert any(
            "Power Down session" in r.message and "ended" in r.message
            for r in caplog.records
        )

        # Persisted through DailyViewStore, on the same tick.
        system._persist_today_view()
        saved = system.daily_view_store.load_day(time_utils.today())
        assert saved is not None
        assert len(saved.power_down_sessions) == 1
        assert saved.power_down_sessions[0].session_start == SESSION_START
        assert saved.power_down_sessions[0].realized_export_kwh == pytest.approx(0.3)

        # Idempotent: a second run on the same (now stale) window adds nothing.
        system._record_power_down_session_outcomes()
        assert len(system._power_down_session_outcomes) == 1

    @patch("core.bess.time_utils.datetime")
    def test_no_record_before_session_ends(
        self, mock_datetime: Any, system: BatterySystemManager
    ) -> None:
        _enable_power_down(system)
        _set_session_window(system)
        _freeze(mock_datetime, datetime(2026, 9, 13, 18, 30, tzinfo=TIMEZONE))

        system._record_power_down_session_outcomes()

        assert system._power_down_session_outcomes == []

    @patch("core.bess.time_utils.datetime")
    def test_disabled_records_nothing_and_reads_no_events_entity(
        self, mock_datetime: Any, system: BatterySystemManager, mock_controller: Any
    ) -> None:
        _enable_power_down(
            system,
            power_down_enabled=False,
            power_down_events_entity="event.octopus_energy_x_octoplus_power_down_events",
        )
        _set_session_window(system)
        _freeze(mock_datetime, datetime(2026, 9, 13, 19, 15, tzinfo=TIMEZONE))

        with patch.object(mock_controller, "get_entity_state_raw") as mock_get_state:
            system._record_power_down_session_outcomes()

        assert system._power_down_session_outcomes == []
        mock_get_state.assert_not_called()


class TestOctopointsBackfill:
    def _outcome(
        self, rewarded_octopoints: int | None = None
    ) -> PowerDownSessionOutcome:
        return PowerDownSessionOutcome(
            session_start=SESSION_START,
            session_end=SESSION_END,
            target_export_kwh=0.25,
            planned_import_kwh=0.0,
            planned_export_kwh=0.0,
            realized_import_kwh=0.0,
            realized_export_kwh=0.3,
            target_met=True,
            export_curtailment_active=False,
            rewarded_octopoints=rewarded_octopoints,
        )

    def test_none_becomes_16_once_entity_reports_it(
        self, system: BatterySystemManager, mock_controller: Any
    ) -> None:
        _enable_power_down(
            system,
            power_down_events_entity="event.octopus_energy_x_octoplus_power_down_events",
        )
        system._power_down_session_outcomes = [self._outcome(None)]
        mock_controller.get_entity_state_raw = MagicMock(
            return_value={
                "attributes": {
                    "joined_events": [
                        {
                            "id": 6203,
                            "start": SESSION_START.isoformat(),
                            "end": SESSION_END.isoformat(),
                            "rewarded_octopoints": 16,
                        }
                    ]
                }
            }
        )

        system._backfill_power_down_octopoints(
            system._energy_provider_config["octopus"]
        )

        assert system._power_down_session_outcomes[0].rewarded_octopoints == 16

    def test_a_null_reward_stays_none(
        self, system: BatterySystemManager, mock_controller: Any
    ) -> None:
        _enable_power_down(
            system,
            power_down_events_entity="event.octopus_energy_x_octoplus_power_down_events",
        )
        system._power_down_session_outcomes = [self._outcome(None)]
        mock_controller.get_entity_state_raw = MagicMock(
            return_value={
                "attributes": {
                    "joined_events": [
                        {
                            "start": SESSION_START.isoformat(),
                            "rewarded_octopoints": None,
                        }
                    ]
                }
            }
        )

        system._backfill_power_down_octopoints(
            system._energy_provider_config["octopus"]
        )

        assert system._power_down_session_outcomes[0].rewarded_octopoints is None

    def test_joined_events_none_does_not_raise(
        self, system: BatterySystemManager, mock_controller: Any
    ) -> None:
        """Right after an integration reload, joined_events can be None --
        treated as "nothing yet", not an error (design section 6)."""
        _enable_power_down(
            system,
            power_down_events_entity="event.octopus_energy_x_octoplus_power_down_events",
        )
        system._power_down_session_outcomes = [self._outcome(None)]
        mock_controller.get_entity_state_raw = MagicMock(
            return_value={"attributes": {"joined_events": None}}
        )

        system._backfill_power_down_octopoints(
            system._energy_provider_config["octopus"]
        )

        assert system._power_down_session_outcomes[0].rewarded_octopoints is None

    def test_no_events_entity_configured_skips_the_read(
        self, system: BatterySystemManager, mock_controller: Any
    ) -> None:
        _enable_power_down(system, power_down_events_entity="")
        system._power_down_session_outcomes = [self._outcome(None)]

        with patch.object(mock_controller, "get_entity_state_raw") as mock_get_state:
            system._backfill_power_down_octopoints(
                system._energy_provider_config["octopus"]
            )

        mock_get_state.assert_not_called()

    def test_rate_limited_to_once_per_hour(
        self, system: BatterySystemManager, mock_controller: Any
    ) -> None:
        _enable_power_down(
            system,
            power_down_events_entity="event.octopus_energy_x_octoplus_power_down_events",
        )
        system._power_down_session_outcomes = [self._outcome(None)]
        mock_controller.get_entity_state_raw = MagicMock(return_value=None)

        octopus_config = system._energy_provider_config["octopus"]
        system._backfill_power_down_octopoints(octopus_config)
        system._backfill_power_down_octopoints(octopus_config)

        mock_controller.get_entity_state_raw.assert_called_once()


class TestOldDailyViewWithoutPowerDownSessions:
    def test_old_json_without_the_field_loads(self, tmp_path: Any) -> None:
        import json

        store = DailyViewStore(persist_dir=tmp_path)
        old_payload = {
            "date": "2026-09-01",
            "periods": [],
            "total_savings": 1.0,
            "actual_count": 0,
            "predicted_count": 0,
        }
        path = tmp_path / "2026-09-01.json"
        path.write_text(json.dumps(old_payload))

        from datetime import date as date_cls

        view = store.load_day(date_cls(2026, 9, 1))

        assert view is not None
        assert view.power_down_sessions == []


class TestDebugExportIncludesTodaysSessions:
    def test_debug_export_contains_the_record(
        self, system: BatterySystemManager
    ) -> None:
        outcome = PowerDownSessionOutcome(
            session_start=SESSION_START,
            session_end=SESSION_END,
            target_export_kwh=0.25,
            planned_import_kwh=0.4,
            planned_export_kwh=0.0,
            realized_import_kwh=0.0,
            realized_export_kwh=0.3,
            target_met=True,
            export_curtailment_active=False,
            rewarded_octopoints=None,
        )
        system._power_down_session_outcomes = [outcome]

        aggregator = DebugDataAggregator(system)
        result = aggregator._serialize_power_down_sessions_today()

        assert len(result) == 1
        assert result[0]["session_start"] == SESSION_START
        assert result[0]["realized_export_kwh"] == pytest.approx(0.3)
