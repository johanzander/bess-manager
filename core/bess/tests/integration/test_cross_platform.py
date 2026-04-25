"""Cross-platform integration tests for all inverter types.

Verifies that the optimization → schedule → hardware write pipeline works
correctly for Growatt MIN, Growatt SPH, and SolaX platforms. Each test runs
3 times (once per platform) via the parametrized ``platform_system`` fixture.

Tests verify BEHAVIOR (what the system does) not IMPLEMENTATION (how it does it).
"""

from types import SimpleNamespace

from core.bess.growatt_sph_controller import GrowattSphController
from core.bess.solax_controller import SolaxController

PERIOD = 20  # Arbitrary test period (quarter-hour slot)

VALID_INTENTS = {
    "GRID_CHARGING",
    "SOLAR_STORAGE",
    "LOAD_SUPPORT",
    "EXPORT_ARBITRAGE",
    "IDLE",
}


def _set_intent(system, period: int, intent: str) -> None:
    """Set a single period's strategic intent, padding the rest with IDLE."""
    intents = ["IDLE"] * 96
    intents[period] = intent
    system._inverter_controller.strategic_intents = intents


def _set_action(system, period: int, kwh: float) -> None:
    """Set a battery action for the given period."""
    actions = [0.0] * 96
    actions[period] = kwh
    system._inverter_controller.current_schedule = SimpleNamespace(actions=actions)


def _is_solax(system) -> bool:
    return isinstance(system._inverter_controller, SolaxController)


def _is_sph(system) -> bool:
    return isinstance(system._inverter_controller, GrowattSphController)


# ── Schedule creation ────────────────────────────────────────────────────────


class TestCrossPlatformScheduleCreation:
    def test_optimization_produces_valid_schedule(self, platform_system):
        """Full optimization pipeline produces a schedule with valid intents."""
        system = platform_system
        system.update_battery_schedule(0, prepare_next_day=False)

        schedule = system.schedule_store.get_latest_schedule()
        assert schedule is not None
        assert len(schedule.optimization_result.period_data) > 0

        for intent in system._inverter_controller.strategic_intents:
            assert intent in VALID_INTENTS


# ── Hardware writes per intent ───────────────────────────────────────────────


class TestCrossPlatformHardwareWrites:
    def test_grid_charging_commands_hardware(self, platform_system, mock_controller):
        """GRID_CHARGING produces the correct hardware call for each platform."""
        _set_intent(platform_system, PERIOD, "GRID_CHARGING")

        platform_system._apply_period_schedule(PERIOD)

        if _is_solax(platform_system):
            assert len(mock_controller.calls["vpp_calls"]) == 1
            assert mock_controller.calls["vpp_calls"][0] > 0
        else:
            assert True in mock_controller.calls["grid_charge"]

    def test_discharge_commands_hardware(self, platform_system, mock_controller):
        """LOAD_SUPPORT produces a discharge command for each platform."""
        _set_intent(platform_system, PERIOD, "LOAD_SUPPORT")

        platform_system._apply_period_schedule(PERIOD)

        if _is_solax(platform_system):
            assert len(mock_controller.calls["vpp_calls"]) == 1
            assert mock_controller.calls["vpp_calls"][0] < 0
        else:
            assert any(r > 0 for r in mock_controller.calls["discharge_rate"])

    def test_export_arbitrage_commands_hardware(self, platform_system, mock_controller):
        """EXPORT_ARBITRAGE produces a discharge command for each platform."""
        _set_intent(platform_system, PERIOD, "EXPORT_ARBITRAGE")
        _set_action(platform_system, PERIOD, -2.0)

        platform_system._apply_period_schedule(PERIOD)

        if _is_solax(platform_system):
            assert len(mock_controller.calls["vpp_calls"]) == 1
            assert mock_controller.calls["vpp_calls"][0] < 0
        else:
            assert any(r > 0 for r in mock_controller.calls["discharge_rate"])

    def test_idle_produces_no_active_command(self, platform_system, mock_controller):
        """IDLE does not issue charge or discharge commands."""
        _set_intent(platform_system, PERIOD, "IDLE")

        platform_system._apply_period_schedule(PERIOD)

        if _is_solax(platform_system):
            assert len(mock_controller.calls["vpp_disabled"]) == 1
            assert len(mock_controller.calls["vpp_calls"]) == 0
        else:
            # IDLE: grid_charge=False and discharge_rate=0
            assert mock_controller.calls["grid_charge"][-1] is False
            assert mock_controller.calls["discharge_rate"][-1] == 0

    def test_solar_storage_no_grid_charge(self, platform_system, mock_controller):
        """SOLAR_STORAGE does not enable grid charging."""
        _set_intent(platform_system, PERIOD, "SOLAR_STORAGE")

        platform_system._apply_period_schedule(PERIOD)

        if _is_solax(platform_system):
            assert len(mock_controller.calls["vpp_disabled"]) == 1
        else:
            assert mock_controller.calls["grid_charge"][-1] is False


# ── SOC limits ───────────────────────────────────────────────────────────────


class TestCrossPlatformSocLimits:
    def test_sync_soc_limits(self, platform_system, mock_controller):
        """sync_soc_limits writes SOC bounds to the inverter."""
        platform_system.battery_settings.min_soc = 15
        platform_system.battery_settings.max_soc = 95

        platform_system._inverter_controller.sync_soc_limits(mock_controller)

        if _is_solax(platform_system):
            # SolaX only has min SOC
            assert 15 in mock_controller.calls["min_soc"]
        elif _is_sph(platform_system):
            # SPH writes SOC via AC charge/discharge service calls
            assert len(mock_controller.calls["ac_charge_times"]) > 0
            assert mock_controller.calls["ac_charge_times"][-1]["charge_stop_soc"] == 95
            assert len(mock_controller.calls["ac_discharge_times"]) > 0
            assert (
                mock_controller.calls["ac_discharge_times"][-1]["discharge_stop_soc"]
                == 15
            )
        else:
            # Growatt MIN sets via entity writes
            assert mock_controller.settings["charge_stop_soc"] == 95
            assert mock_controller.settings["discharge_stop_soc"] == 15


# ── Health checks ────────────────────────────────────────────────────────────


class TestCrossPlatformHealthCheck:
    def test_health_check_returns_results(self, platform_system, mock_controller):
        """check_health returns a list of health check results for each platform."""
        result = platform_system._inverter_controller.check_health(mock_controller)

        assert isinstance(result, list)
        assert len(result) > 0
        for item in result:
            assert "status" in item
