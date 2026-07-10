"""Tests for SolaxModbusGrowattController single-segment TOU approach.

Verifies that the Modbus controller:
- Uses a single TOU segment (slot 1) instead of 9
- Only writes TOU segment when mode changes
- Disables legacy segments 2-9 on startup
- Correctly maps strategic intents to TOU modes
"""

from unittest.mock import patch

import pytest  # type: ignore

from core.bess.dp_schedule import DPSchedule
from core.bess.settings import BatterySettings
from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController
from core.bess.tests.conftest import MockHomeAssistantController


def hourly_to_quarterly(
    hourly_intents: dict[int, str], default: str = "IDLE"
) -> list[str]:
    """Convert hourly strategic intents to quarterly (96 periods)."""
    quarterly = [default] * 96
    for hour, intent in hourly_intents.items():
        for period in range(hour * 4, (hour + 1) * 4):
            quarterly[period] = intent
    return quarterly


def make_schedule(intents: list[str]) -> DPSchedule:
    """Create a minimal DPSchedule with strategic intents."""
    return DPSchedule(
        actions=[0.0] * len(intents),
        state_of_energy=[25.0] * (len(intents) + 1),
        prices=[0.1] * len(intents),
        original_dp_results={"strategic_intent": intents},
    )


@pytest.fixture
def battery_settings():
    return BatterySettings(
        total_capacity=50.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        min_soc=10.0,
        max_soc=95.0,
        cycle_cost_per_kwh=0.05,
    )


@pytest.fixture
def controller(battery_settings):
    return SolaxModbusGrowattController(battery_settings)


@pytest.fixture
def mock_ha():
    return MockHomeAssistantController()


class TestCreateSchedule:
    """Test that create_schedule stores intents without computing TOU intervals."""

    def test_stores_strategic_intents(self, controller):
        intents = hourly_to_quarterly({2: "GRID_CHARGING", 18: "LOAD_SUPPORT"})
        schedule = make_schedule(intents)

        controller.create_schedule(schedule, current_period=0)

        assert controller.strategic_intents == intents
        assert controller.current_schedule is schedule

    def test_no_9_segment_tou_computation(self, controller):
        """Single-segment controller should NOT build 9-segment TOU intervals."""
        intents = hourly_to_quarterly(
            dict.fromkeys(range(12), "GRID_CHARGING")  # 12 hours of charging
        )
        schedule = make_schedule(intents)

        controller.create_schedule(schedule, current_period=0)

        # Should not have built multi-segment TOU intervals
        # (parent would create multiple segments for 12 hours of charging)
        assert len(controller.tou_intervals) <= 1


class TestApplyPeriod:
    """Test per-period mode updates via apply_period."""

    def _apply_at_period(self, controller, mock_ha, period, intent):
        """Helper: set strategic intents and call apply_period for a given period."""
        from datetime import datetime

        hour = period // 4
        minute = (period % 4) * 15

        with patch("core.bess.solax_modbus_growatt_controller.time_utils") as mock_time:
            mock_time.now.return_value = datetime(2026, 5, 20, hour, minute, 0)
            grid_charge, discharge_rate = controller.compute_rates_for_period(
                period, 0.0
            )
            controller.apply_period(mock_ha, grid_charge, discharge_rate)

    def test_mode_changes_trigger_tou_write(self, controller, mock_ha):
        """TOU segment should be written when mode changes."""
        intents = hourly_to_quarterly({0: "IDLE", 2: "GRID_CHARGING", 4: "IDLE"})
        schedule = make_schedule(intents)
        controller.create_schedule(schedule, current_period=0)

        # Period 0 (00:00): IDLE -> load_first
        # Initial mode is None, so first period should trigger a write
        self._apply_at_period(controller, mock_ha, 0, "IDLE")
        assert len(mock_ha.calls["tou_segments"]) == 1
        seg = mock_ha.calls["tou_segments"][-1]
        assert seg["enabled"] is False  # load_first disables segment

        # Period 8 (02:00): GRID_CHARGING -> battery_first
        self._apply_at_period(controller, mock_ha, 8, "GRID_CHARGING")
        assert len(mock_ha.calls["tou_segments"]) == 2
        seg = mock_ha.calls["tou_segments"][-1]
        assert seg["batt_mode"] == "battery_first"
        assert seg["enabled"] is True
        assert seg["start_time"] == "00:00"
        assert seg["end_time"] == "23:59"

    def test_same_mode_skips_write(self, controller, mock_ha):
        """No TOU write when mode hasn't changed."""
        intents = hourly_to_quarterly({0: "IDLE"})
        schedule = make_schedule(intents)
        controller.create_schedule(schedule, current_period=0)

        # First apply: writes because _last_written_tou_mode is None
        self._apply_at_period(controller, mock_ha, 0, "IDLE")
        initial_writes = len(mock_ha.calls["tou_segments"])

        # Second apply same mode: no new TOU write
        self._apply_at_period(controller, mock_ha, 4, "IDLE")
        assert len(mock_ha.calls["tou_segments"]) == initial_writes

    def test_grid_first_mode(self, controller, mock_ha):
        """BATTERY_EXPORT should set grid_first mode."""
        intents = hourly_to_quarterly({10: "BATTERY_EXPORT"})
        schedule = make_schedule(intents)
        controller.create_schedule(schedule, current_period=0)

        # Set initial mode
        controller._last_written_tou_mode = "load_first"

        self._apply_at_period(controller, mock_ha, 40, "BATTERY_EXPORT")
        seg = mock_ha.calls["tou_segments"][-1]
        assert seg["batt_mode"] == "grid_first"
        assert seg["enabled"] is True

    def test_full_mode_cycle(self, controller, mock_ha):
        """Test complete cycle: load_first -> battery_first -> grid_first -> load_first."""
        intents = hourly_to_quarterly(
            {
                0: "IDLE",
                2: "GRID_CHARGING",
                6: "BATTERY_EXPORT",
                10: "LOAD_SUPPORT",
            }
        )
        schedule = make_schedule(intents)
        controller.create_schedule(schedule, current_period=0)

        modes_written = []

        # Period 0: IDLE -> load_first
        self._apply_at_period(controller, mock_ha, 0, "IDLE")
        modes_written.append(controller._last_written_tou_mode)

        # Period 8: GRID_CHARGING -> battery_first
        self._apply_at_period(controller, mock_ha, 8, "GRID_CHARGING")
        modes_written.append(controller._last_written_tou_mode)

        # Period 24: BATTERY_EXPORT -> grid_first
        self._apply_at_period(controller, mock_ha, 24, "BATTERY_EXPORT")
        modes_written.append(controller._last_written_tou_mode)

        # Period 40: LOAD_SUPPORT -> load_first
        self._apply_at_period(controller, mock_ha, 40, "LOAD_SUPPORT")
        modes_written.append(controller._last_written_tou_mode)

        assert modes_written == [
            "load_first",
            "battery_first",
            "grid_first",
            "load_first",
        ]

    def test_per_period_always_sets_grid_charge_and_discharge(
        self, controller, mock_ha
    ):
        """grid_charge and discharge_rate are always written, regardless of mode change."""
        intents = hourly_to_quarterly({0: "GRID_CHARGING"})
        schedule = make_schedule(intents)
        controller.create_schedule(schedule, current_period=0)

        self._apply_at_period(controller, mock_ha, 0, "GRID_CHARGING")

        assert len(mock_ha.calls["grid_charge"]) == 1
        assert mock_ha.calls["grid_charge"][-1] is True
        assert len(mock_ha.calls["discharge_rate"]) == 1

    def test_load_first_writes_zero_ems_discharge_rate(self, controller, mock_ha):
        """EMS discharge rate=0 must be written in load_first mode (experimental).

        #166 previously gated this write out, on the unconfirmed theory that
        writing discharge_rate=0 to the EMS register disables the inverter's
        native self-use discharge. That gate left SOLAR_STORAGE/IDLE with a
        stale discharge_rate register (reported against #200 by Doodlehusse).
        This beta build removes the gate to test on real GEN4 hardware — it
        now writes unconditionally, same as GrowattMinController's cloud path.
        """
        intents = hourly_to_quarterly({0: "IDLE"})
        schedule = make_schedule(intents)
        controller.create_schedule(schedule, current_period=0)
        controller._last_written_tou_mode = "load_first"

        self._apply_at_period(controller, mock_ha, 0, "IDLE")

        assert mock_ha.calls["discharge_rate"] == [0]

    def test_load_first_writes_nonzero_load_support_discharge_rate(
        self, controller, mock_ha
    ):
        """LOAD_SUPPORT's real discharge rate must reach the inverter.

        Regression test for #200: LOAD_SUPPORT maps to load_first, same as
        IDLE, and both now write discharge_rate unconditionally (see
        test_load_first_writes_zero_ems_discharge_rate above).
        """
        from datetime import datetime

        intents = hourly_to_quarterly({0: "LOAD_SUPPORT"})
        schedule = make_schedule(intents)
        controller.create_schedule(schedule, current_period=0)
        controller._last_written_tou_mode = "load_first"

        with patch("core.bess.solax_modbus_growatt_controller.time_utils") as mock_time:
            mock_time.now.return_value = datetime(2026, 5, 20, 0, 0, 0)
            # -2.0 kW discharge -> non-zero discharge_rate for LOAD_SUPPORT
            grid_charge, discharge_rate = controller.compute_rates_for_period(0, -2.0)
            assert discharge_rate > 0  # sanity: scenario must produce a rate
            controller.apply_period(mock_ha, grid_charge, discharge_rate)

        assert mock_ha.calls["discharge_rate"] == [discharge_rate]


class TestWriteScheduleToHardware:
    """Test write_schedule_to_hardware initialises segment 1."""

    def test_sets_initial_mode(self, controller, mock_ha):
        intents = hourly_to_quarterly({2: "GRID_CHARGING"})
        schedule = make_schedule(intents)
        controller.create_schedule(schedule, current_period=0)

        writes, _disables = controller.write_schedule_to_hardware(
            mock_ha, effective_period=8, current_tou=[]
        )

        assert writes == 1
        seg = mock_ha.calls["tou_segments"][-1]
        assert seg["segment_id"] == 1
        assert seg["batt_mode"] == "battery_first"
        assert seg["enabled"] is True
        assert seg["start_time"] == "00:00"
        assert seg["end_time"] == "23:59"

    def test_idle_schedule_disables_segment(self, controller, mock_ha):
        intents = hourly_to_quarterly({})  # all IDLE
        schedule = make_schedule(intents)
        controller.create_schedule(schedule, current_period=0)

        controller.write_schedule_to_hardware(
            mock_ha, effective_period=0, current_tou=[]
        )

        seg = mock_ha.calls["tou_segments"][-1]
        assert seg["enabled"] is False

    def test_seeds_mode_tracker(self, controller, mock_ha):
        intents = hourly_to_quarterly({5: "BATTERY_EXPORT"})
        schedule = make_schedule(intents)
        controller.create_schedule(schedule, current_period=0)

        controller.write_schedule_to_hardware(
            mock_ha, effective_period=20, current_tou=[]
        )

        assert controller._last_written_tou_mode == "grid_first"


class TestReadAndInitialize:
    """Test read_and_initialize_from_hardware with migration cleanup."""

    def test_seeds_mode_from_segment_1(self, controller, mock_ha):
        """Should read segment 1 and seed _last_written_tou_mode."""
        mock_ha.read_tou_segments_from_entities = lambda: [
            {
                "segment_id": 1,
                "batt_mode": "battery_first",
                "start_time": "00:00",
                "end_time": "23:59",
                "enabled": True,
            }
        ]

        controller.read_and_initialize_from_hardware(mock_ha, current_hour=10)

        assert controller._last_written_tou_mode == "battery_first"

    def test_defaults_to_load_first_when_disabled(self, controller, mock_ha):
        mock_ha.read_tou_segments_from_entities = lambda: [
            {
                "segment_id": 1,
                "batt_mode": "load_first",
                "start_time": "00:00",
                "end_time": "00:00",
                "enabled": False,
            }
        ]

        controller.read_and_initialize_from_hardware(mock_ha, current_hour=10)

        assert controller._last_written_tou_mode == "load_first"

    def test_disables_legacy_segments_2_through_9(self, controller, mock_ha):
        """Legacy segments from 9-segment setup should be disabled on startup."""
        mock_ha.read_tou_segments_from_entities = lambda: [
            {
                "segment_id": 1,
                "batt_mode": "battery_first",
                "start_time": "02:00",
                "end_time": "05:59",
                "enabled": True,
            },
            {
                "segment_id": 2,
                "batt_mode": "grid_first",
                "start_time": "18:00",
                "end_time": "20:59",
                "enabled": True,
            },
            {
                "segment_id": 3,
                "batt_mode": "battery_first",
                "start_time": "22:00",
                "end_time": "23:59",
                "enabled": True,
            },
        ]

        controller.initialize_hardware(mock_ha)

        # Segments 2 and 3 should have been disabled
        disable_calls = [
            c
            for c in mock_ha.calls["tou_segments"]
            if c["segment_id"] >= 2 and c["enabled"] is False
        ]
        assert len(disable_calls) == 2
        disabled_ids = {c["segment_id"] for c in disable_calls}
        assert disabled_ids == {2, 3}

    def test_skips_already_disabled_legacy_segments(self, controller, mock_ha):
        """Already-disabled segments should not be written to."""
        mock_ha.read_tou_segments_from_entities = lambda: [
            {
                "segment_id": 1,
                "batt_mode": "load_first",
                "start_time": "00:00",
                "end_time": "00:00",
                "enabled": False,
            },
            {
                "segment_id": 2,
                "batt_mode": "load_first",
                "start_time": "00:00",
                "end_time": "00:00",
                "enabled": False,
            },
        ]

        controller.initialize_hardware(mock_ha)

        # No disable writes should have been made (both already disabled)
        assert len(mock_ha.calls["tou_segments"]) == 0

    def test_handles_no_segments_found(self, controller, mock_ha):
        """Gracefully handles case where no entities are configured."""
        mock_ha.read_tou_segments_from_entities = lambda: []

        controller.read_and_initialize_from_hardware(mock_ha, current_hour=10)

        assert controller._last_written_tou_mode == "load_first"


class TestCompareSchedules:
    """Test schedule comparison by strategic intents."""

    def test_identical_schedules(self, controller, battery_settings):
        other = SolaxModbusGrowattController(battery_settings)
        intents = hourly_to_quarterly({2: "GRID_CHARGING"})

        controller.strategic_intents = intents
        other.strategic_intents = list(intents)

        differs, _reason = controller.compare_schedules(other)
        assert not differs

    def test_different_schedules(self, controller, battery_settings):
        other = SolaxModbusGrowattController(battery_settings)

        controller.strategic_intents = hourly_to_quarterly({2: "GRID_CHARGING"})
        other.strategic_intents = hourly_to_quarterly(
            {2: "GRID_CHARGING", 18: "BATTERY_EXPORT"}
        )

        differs, _reason = controller.compare_schedules(other)
        assert differs

    def test_respects_from_period(self, controller, battery_settings):
        other = SolaxModbusGrowattController(battery_settings)

        # Different at period 0-3 (hour 0), same from period 8 onwards
        controller.strategic_intents = hourly_to_quarterly(
            {0: "GRID_CHARGING", 2: "LOAD_SUPPORT"}
        )
        other.strategic_intents = hourly_to_quarterly({0: "IDLE", 2: "LOAD_SUPPORT"})

        # Comparing from period 8 (hour 2) — should match
        differs, _ = controller.compare_schedules(other, from_period=8)
        assert not differs

        # Comparing from period 0 — should differ
        differs, _ = controller.compare_schedules(other, from_period=0)
        assert differs


class TestDisplayMethods:
    """Test TOU display/API methods."""

    def test_get_daily_tou_settings_with_active_mode(self, controller):
        controller._last_written_tou_mode = "battery_first"
        controller._update_tou_display_state()

        settings = controller.get_daily_TOU_settings()
        assert len(settings) == 1
        assert settings[0]["batt_mode"] == "battery_first"
        assert settings[0]["segment_id"] == 1

    def test_get_daily_tou_settings_load_first(self, controller):
        controller._last_written_tou_mode = "load_first"
        controller._update_tou_display_state()

        settings = controller.get_daily_TOU_settings()
        assert len(settings) == 0

    def test_get_all_tou_segments_no_schedule(self, controller):
        segments = controller.get_all_tou_segments()
        assert len(segments) == 1
        assert segments[0]["is_default"] is True
        assert segments[0]["batt_mode"] == "load_first"

    def test_get_all_tou_segments_with_schedule(self, controller):
        intents = hourly_to_quarterly(
            {2: "GRID_CHARGING", 6: "IDLE", 18: "LOAD_SUPPORT"}
        )
        schedule = make_schedule(intents)
        controller.create_schedule(schedule, current_period=0)

        segments = controller.get_all_tou_segments()
        # Should have groups for each intent run
        assert len(segments) > 0
        # Verify battery_first group exists for hour 2
        battery_first_segs = [s for s in segments if s["batt_mode"] == "battery_first"]
        assert len(battery_first_segs) > 0
