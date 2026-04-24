"""Integration tests for SolaX controller within BatterySystemManager.

Tests verify that VPP commands are issued at period boundaries and that
the SolaX controller integrates correctly with the battery system lifecycle.
"""

from types import SimpleNamespace

from core.bess.battery_system_manager import BatterySystemManager
from core.bess.price_manager import MockSource
from core.bess.solax_controller import SolaxController
from core.bess.tests.conftest import MockHomeAssistantController


class SolaxMockController(MockHomeAssistantController):
    """Extends mock controller with SolaX VPP tracking."""

    def __init__(self) -> None:
        super().__init__()
        self.vpp_calls: list[int] = []  # watts sent to active_power_control
        self.vpp_disabled_count: int = 0
        self.min_soc_set: list[int] = []
        self.power_control_mode: str | None = "Self Use Mode"
        self.sensors.update({
            "solax_power_control_mode": "select.solax_remotecontrol_power_control",
            "solax_active_power": "number.solax_remotecontrol_active_power",
            "solax_autorepeat_duration": "number.solax_remotecontrol_autorepeat_duration",
            "solax_power_control_trigger": "button.solax_remotecontrol_trigger",
            "solax_battery_min_soc": "number.solax_battery_minimum_capacity",
        })

    def set_solax_active_power_control(self, watts: int) -> None:
        self.vpp_calls.append(watts)

    def set_solax_vpp_disabled(self) -> None:
        self.vpp_disabled_count += 1

    def set_solax_min_soc(self, soc: int) -> None:
        self.min_soc_set.append(soc)

    def get_solax_power_control_mode(self) -> str | None:
        return self.power_control_mode


def _make_bsm_solax(
    prices: list[float] | None = None,
) -> tuple[BatterySystemManager, SolaxMockController]:
    """Create a BatterySystemManager wired with a SolaxController."""
    controller = SolaxMockController()
    price_source = MockSource(prices or [1.0] * 96)
    bsm = BatterySystemManager(controller=controller, price_source=price_source)

    # Replace the default Growatt controller with SolaX
    battery_settings = bsm._inverter_controller.battery_settings
    bsm._inverter_controller = SolaxController(battery_settings=battery_settings)

    return bsm, controller


def _set_intent(bsm: BatterySystemManager, period: int, intent: str) -> None:
    """Set a single period's strategic intent, padding the rest with IDLE."""
    intents = ["IDLE"] * 96
    intents[period] = intent
    bsm._inverter_controller.strategic_intents = intents


def _set_action(bsm: BatterySystemManager, period: int, kwh: float) -> None:
    """Set a battery action for the given period."""
    actions = [0.0] * 96
    actions[period] = kwh
    bsm._inverter_controller.current_schedule = SimpleNamespace(actions=actions)


PERIOD = 20


# ── VPP commands per intent ───────────────────────────────────────────────────


class TestSolaxVppCommandsPerIntent:
    def test_grid_charging_period_sends_positive_watts(self) -> None:
        bsm, hw = _make_bsm_solax()
        _set_intent(bsm, PERIOD, "GRID_CHARGING")

        bsm._apply_period_schedule(PERIOD)

        assert len(hw.vpp_calls) == 1
        assert hw.vpp_calls[0] > 0

    def test_load_support_period_sends_negative_watts(self) -> None:
        bsm, hw = _make_bsm_solax()
        _set_intent(bsm, PERIOD, "LOAD_SUPPORT")

        bsm._apply_period_schedule(PERIOD)

        assert len(hw.vpp_calls) == 1
        assert hw.vpp_calls[0] < 0

    def test_export_arbitrage_period_sends_negative_watts(self) -> None:
        bsm, hw = _make_bsm_solax()
        _set_intent(bsm, PERIOD, "EXPORT_ARBITRAGE")
        _set_action(bsm, PERIOD, -2.0)

        bsm._apply_period_schedule(PERIOD)

        assert len(hw.vpp_calls) == 1
        assert hw.vpp_calls[0] < 0

    def test_idle_period_disables_vpp(self) -> None:
        bsm, hw = _make_bsm_solax()
        _set_intent(bsm, PERIOD, "IDLE")

        bsm._apply_period_schedule(PERIOD)

        assert hw.vpp_disabled_count == 1
        assert len(hw.vpp_calls) == 0

    def test_solar_storage_period_disables_vpp(self) -> None:
        bsm, hw = _make_bsm_solax()
        _set_intent(bsm, PERIOD, "SOLAR_STORAGE")

        bsm._apply_period_schedule(PERIOD)

        assert hw.vpp_disabled_count == 1
        assert len(hw.vpp_calls) == 0


# ── Grid charge command at max power ──────────────────────────────────────────


class TestSolaxGridChargeAtMaxPower:
    def test_grid_charge_power_equals_max_charge_setting(self) -> None:
        bsm, hw = _make_bsm_solax()
        max_kw = bsm._inverter_controller.max_charge_power_kw
        _set_intent(bsm, PERIOD, "GRID_CHARGING")

        bsm._apply_period_schedule(PERIOD)

        expected_watts = int(max_kw * 1000)
        assert hw.vpp_calls[0] == expected_watts


# ── No TOU hardware writes ────────────────────────────────────────────────────


class TestSolaxNoTouHardwareWrites:
    def test_write_schedule_to_hardware_is_noop(self) -> None:
        bsm, hw = _make_bsm_solax()
        intents = ["IDLE"] * 96
        intents[PERIOD] = "GRID_CHARGING"
        bsm._inverter_controller.strategic_intents = intents

        # write_schedule_to_hardware should not call any hardware method
        writes, disables = bsm._inverter_controller.write_schedule_to_hardware(
            hw, effective_period=0, current_tou=[]
        )

        assert writes == 0
        assert disables == 0
        assert len(hw.vpp_calls) == 0
        assert hw.vpp_disabled_count == 0

    def test_active_tou_intervals_always_empty(self) -> None:
        bsm, _hw = _make_bsm_solax()
        assert bsm._inverter_controller.active_tou_intervals == []


# ── Schedule comparison ───────────────────────────────────────────────────────


class TestSolaxScheduleComparison:
    def test_identical_schedules_are_equal(self) -> None:
        bsm, _ = _make_bsm_solax()
        settings = bsm._inverter_controller.battery_settings

        intents = ["IDLE"] * 96
        intents[8 * 4] = "GRID_CHARGING"

        bsm._inverter_controller.strategic_intents = intents

        other = SolaxController(battery_settings=settings)
        other.strategic_intents = list(intents)

        differ, _ = bsm._inverter_controller.compare_schedules(other)
        assert not differ

    def test_changed_intent_triggers_redeploy(self) -> None:
        bsm, _ = _make_bsm_solax()
        settings = bsm._inverter_controller.battery_settings

        bsm._inverter_controller.strategic_intents = ["IDLE"] * 96

        other = SolaxController(battery_settings=settings)
        other.strategic_intents = ["IDLE"] * 95 + ["GRID_CHARGING"]

        differ, reason = bsm._inverter_controller.compare_schedules(other)
        assert differ
        assert reason


# ── Health check integration ──────────────────────────────────────────────────


class TestSolaxHealthCheck:
    def test_health_check_ok_when_entity_readable(self) -> None:
        bsm, hw = _make_bsm_solax()
        hw.power_control_mode = "Self Use Mode"

        result = bsm._inverter_controller.check_health(hw)

        assert isinstance(result, list)
        assert any(item["status"] == "OK" for item in result)

    def test_health_check_error_when_entity_missing(self) -> None:
        bsm, hw = _make_bsm_solax()
        hw.power_control_mode = None

        result = bsm._inverter_controller.check_health(hw)

        assert any(item["status"] == "ERROR" for item in result)
