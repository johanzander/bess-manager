"""Octoplus Power Down: session windows -> per-period export targets and
session import caps (BatterySystemManager._power_down_export_targets).

Turns joined Power Down session windows (never applied to prices, unlike the
companion Power Up overlay) into the optimizer's
min_grid_export_kwh_per_period and session_import_cap_kwh_per_period inputs.
See docs/superpowers/specs/2026-09-13-octopus-power-down-export-pulse-design.md.
"""

from datetime import datetime
from typing import Any
from unittest.mock import patch

import pytest

from core.bess.battery_system_manager import BatterySystemManager
from core.bess.calendar_windows import CalendarWindow
from core.bess.exceptions import SystemConfigurationError
from core.bess.models import DecisionData, EnergyData, OptimizationResult, PeriodData
from core.bess.price_manager import MockSource
from core.bess.time_utils import TIMEZONE

_DEFAULT_OPTIONS = {"inverter": {"platform": "growatt_server_min"}}

# 18:00-19:00, an hour session on Octopus's usual half-hour boundaries ->
# periods 72-75 of a 96-period day (period i = 00:00 + i * 15 min).
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


def _record_realized_export(
    system: BatterySystemManager, period_index: int, grid_exported: float
) -> None:
    system.historical_store.record_period(
        period_index,
        PeriodData(
            period=period_index,
            energy=EnergyData(
                solar_production=0.0,
                home_consumption=0.25,
                battery_charged=0.0,
                battery_discharged=0.25 + grid_exported,
                grid_imported=0.0,
                grid_exported=grid_exported,
                battery_soe_start=5.0,
                battery_soe_end=5.0 - (0.25 + grid_exported),
            ),
            timestamp=datetime.now(tz=TIMEZONE),
            data_source="actual",
            decision=DecisionData(),
        ),
    )


def _freeze(mock_datetime: Any, fixed_now: datetime) -> None:
    mock_datetime.now.return_value = fixed_now
    mock_datetime.combine = datetime.combine


class TestDisabledByDefault:
    def test_returns_none_none_with_default_settings(
        self, system: BatterySystemManager
    ) -> None:
        assert system._power_down_export_targets(96, False) == (None, None)

    def test_no_calendar_fetch_when_power_down_disabled(
        self, system: BatterySystemManager, mock_controller: Any
    ) -> None:
        _enable_power_down(system, power_down_enabled=False)

        with patch.object(mock_controller, "get_calendar_windows") as mock_fetch:
            windows = system._fetch_power_down_windows(
                datetime(2026, 9, 13, tzinfo=TIMEZONE),
                datetime(2026, 9, 15, tzinfo=TIMEZONE),
            )

        assert windows == []
        mock_fetch.assert_not_called()

    def test_no_calendar_fetch_when_no_calendar_configured(
        self, system: BatterySystemManager, mock_controller: Any
    ) -> None:
        _enable_power_down(system, power_down_calendar_entity="")

        with patch.object(mock_controller, "get_calendar_windows") as mock_fetch:
            windows = system._fetch_power_down_windows(
                datetime(2026, 9, 13, tzinfo=TIMEZONE),
                datetime(2026, 9, 15, tzinfo=TIMEZONE),
            )

        assert windows == []
        mock_fetch.assert_not_called()

    @patch("core.bess.time_utils.datetime")
    def test_returns_none_none_when_disabled_even_with_a_cached_window(
        self, mock_datetime: Any, system: BatterySystemManager
    ) -> None:
        """A window can still be cached (fetched before the feature was
        turned off, or by another window source) -- the enabled flag inside
        _power_down_export_targets itself must gate its use, not just the
        earlier fetch."""
        _freeze(mock_datetime, datetime(2026, 9, 13, 17, 0, tzinfo=TIMEZONE))
        _enable_power_down(system, power_down_enabled=False)
        _set_session_window(system)

        assert system._power_down_export_targets(96, False) == (None, None)

    @patch("core.bess.time_utils.datetime")
    def test_returns_none_none_when_no_calendar_configured(
        self, mock_datetime: Any, system: BatterySystemManager
    ) -> None:
        _freeze(mock_datetime, datetime(2026, 9, 13, 17, 0, tzinfo=TIMEZONE))
        _enable_power_down(system, power_down_calendar_entity="")
        _set_session_window(system)

        assert system._power_down_export_targets(96, False) == (None, None)

    def test_no_optimizer_kwargs_when_disabled(
        self, system: BatterySystemManager
    ) -> None:
        """_gather_optimization_data stores None/None, and _run_optimization
        forwards them straight through to optimize_battery_schedule."""
        optimization_data: dict[str, Any] = {
            "combined_soe": [5.0] * 4,
            "full_consumption": [0.5] * 4,
            "full_solar": [0.0] * 4,
            "power_down_export_targets": None,
            "power_down_session_import_caps": None,
        }
        prices = [1.0] * 4
        price_entries = [
            {
                "timestamp": f"2026-09-14 00:{15 * i:02d}",
                "buyPrice": 1.0,
                "sellPrice": 0.1,
            }
            for i in range(4)
        ]

        with (
            patch.object(system, "_calculate_terminal_curve", return_value=None),
            patch.object(
                system, "_get_temperature_derated_charge_limits", return_value=None
            ),
            patch(
                "core.bess.battery_system_manager.optimize_battery_schedule"
            ) as mock_optimize,
        ):
            mock_optimize.return_value = OptimizationResult(
                input_data={}, period_data=[]
            )
            result = system._run_optimization(
                0, optimization_data, prices, price_entries, prepare_next_day=True
            )

        assert result is not None
        kwargs = mock_optimize.call_args.kwargs
        assert kwargs["min_grid_export_kwh_per_period"] is None
        assert kwargs["session_import_cap_kwh_per_period"] is None


class TestSessionMapping:
    """now=17:00, before the 18:00-19:00 session: everything is still ahead,
    so the export target lands on the session's first remaining period and
    the import cap covers all four."""

    @patch("core.bess.time_utils.datetime")
    def test_placement_targets_the_first_configured_periods(
        self, mock_datetime: Any, system: BatterySystemManager
    ) -> None:
        _freeze(mock_datetime, datetime(2026, 9, 13, 17, 0, tzinfo=TIMEZONE))
        _enable_power_down(system)
        _set_session_window(system)

        targets, caps = system._power_down_export_targets(96, False)

        assert targets is not None and caps is not None
        assert targets[72] == pytest.approx(0.25)  # 1.0 kW * 0.25 h * 1 period
        assert all(targets[p] == 0.0 for p in [73, 74, 75])
        assert all(caps[p] == 0.0 for p in SESSION_PERIODS)
        assert all(caps[p] is None for p in range(96) if p not in SESSION_PERIODS)
        assert all(t == 0.0 for i, t in enumerate(targets) if i != 72)

    @patch("core.bess.time_utils.datetime")
    def test_no_session_in_horizon_returns_none_none(
        self, mock_datetime: Any, system: BatterySystemManager
    ) -> None:
        _freeze(mock_datetime, datetime(2026, 9, 13, 17, 0, tzinfo=TIMEZONE))
        _enable_power_down(system)
        system._price_manager.get_power_down_windows = lambda: []  # type: ignore[method-assign]

        assert system._power_down_export_targets(96, False) == (None, None)

    @patch("core.bess.time_utils.datetime")
    def test_export_minutes_must_be_a_multiple_of_15_in_range(
        self, mock_datetime: Any, system: BatterySystemManager
    ) -> None:
        _freeze(mock_datetime, datetime(2026, 9, 13, 17, 0, tzinfo=TIMEZONE))
        _enable_power_down(system, power_down_export_minutes=20)
        _set_session_window(system)

        with pytest.raises(SystemConfigurationError):
            system._power_down_export_targets(96, False)


class TestRollover:
    """Spec scenario: the session's first period (72, 18:00-18:15) realizes
    zero export -- a simulated write failure. The next run must retarget the
    next remaining period with the full remainder; a later run after the
    target is actually met must set no further targets, while the import cap
    stays applied to whatever of the session remains."""

    @patch("core.bess.time_utils.datetime")
    def test_a_failed_first_period_rolls_the_full_target_onto_the_next(
        self, mock_datetime: Any, system: BatterySystemManager
    ) -> None:
        _freeze(mock_datetime, datetime(2026, 9, 13, 18, 15, tzinfo=TIMEZONE))
        _enable_power_down(system)
        _set_session_window(system)
        _record_realized_export(system, 72, grid_exported=0.0)

        targets, caps = system._power_down_export_targets(96, False)

        assert targets is not None and caps is not None
        assert targets[73] == pytest.approx(0.25)
        assert all(targets[p] == 0.0 for p in [72, 74, 75])
        assert all(caps[p] == 0.0 for p in SESSION_PERIODS)

    @patch("core.bess.time_utils.datetime")
    def test_a_met_target_sets_no_further_export_but_keeps_the_import_cap(
        self, mock_datetime: Any, system: BatterySystemManager
    ) -> None:
        _freeze(mock_datetime, datetime(2026, 9, 13, 18, 30, tzinfo=TIMEZONE))
        _enable_power_down(system)
        _set_session_window(system)
        _record_realized_export(system, 72, grid_exported=0.0)
        _record_realized_export(system, 73, grid_exported=0.30)  # exceeds 0.25

        targets, caps = system._power_down_export_targets(96, False)

        assert targets is not None and caps is not None
        assert all(t == 0.0 for t in targets)
        assert all(caps[p] == 0.0 for p in SESSION_PERIODS)

    @patch("core.bess.time_utils.datetime")
    def test_a_met_first_slot_of_a_multi_period_pulse_rolls_only_the_shortfall(
        self, mock_datetime: Any, system: BatterySystemManager
    ) -> None:
        """A 30-minute pulse (periods_needed=2) whose first slot (72) fully
        delivered its 0.25 kWh share must NOT have the run at 18:15 spread
        the remaining 0.25 kWh back over two periods (73 and 74) at half
        rate -- that stretches the pulse to 45 minutes at half the
        configured power. Completed periods count against the pulse
        duration regardless of whether they met their share, so only one
        placement period (periods_needed=2 minus 1 completed = 1) remains,
        and it alone gets the full 0.25 kWh shortfall."""
        _freeze(mock_datetime, datetime(2026, 9, 13, 18, 15, tzinfo=TIMEZONE))
        _enable_power_down(system, power_down_export_minutes=30)
        _set_session_window(system)
        _record_realized_export(system, 72, grid_exported=0.25)  # met its share

        targets, caps = system._power_down_export_targets(96, False)

        assert targets is not None and caps is not None
        assert targets[73] == pytest.approx(0.25)
        assert targets[74] == 0.0
        assert all(targets[p] == 0.0 for p in [72, 75])
        assert all(caps[p] == 0.0 for p in SESSION_PERIODS)

    @patch("core.bess.time_utils.datetime")
    def test_an_ended_session_before_the_horizon_is_ignored(
        self, mock_datetime: Any, system: BatterySystemManager
    ) -> None:
        """A session entirely on yesterday's date can't be read by
        timestamp_to_period_index (today/tomorrow only) -- it's simply not
        reachable from today's horizon, which is the "ended session" case in
        practice for a same-day-only integration."""
        _freeze(mock_datetime, datetime(2026, 9, 13, 12, 0, tzinfo=TIMEZONE))
        _enable_power_down(system)
        _set_session_window(
            system,
            start=datetime(2026, 9, 12, 18, 0, tzinfo=TIMEZONE),
            end=datetime(2026, 9, 12, 19, 0, tzinfo=TIMEZONE),
        )

        assert system._power_down_export_targets(96, False) == (None, None)
