"""Tests for discharge inhibit behavior.

Covers two mechanisms:
- _apply_period_schedule: checks inhibit at every 15-min period boundary
- apply_discharge_inhibit: reacts to inhibit changes within ~1 minute
"""

from types import SimpleNamespace

import pytest

from core.bess.battery_system_manager import BatterySystemManager
from core.bess.price_manager import MockSource
from core.bess.tests.conftest import MockHomeAssistantController


class InhibitableController(MockHomeAssistantController):
    """Extends mock controller with a controllable discharge inhibit flag."""

    def __init__(self, inhibit_active: bool = False) -> None:
        super().__init__()
        self.inhibit_active = inhibit_active
        self.inhibit_query_count = 0

    def get_discharge_inhibit_active(self) -> bool:
        self.inhibit_query_count += 1
        return self.inhibit_active


def _make_bsm(
    inhibit_active: bool = False,
) -> tuple[BatterySystemManager, InhibitableController]:
    controller = InhibitableController(inhibit_active=inhibit_active)
    bsm = BatterySystemManager(
        controller=controller, price_source=MockSource([1.0] * 96)
    )
    return bsm, controller


def _set_intent(bsm: BatterySystemManager, period: int, intent: str) -> None:
    """Set a single period's strategic intent, padding the rest with IDLE."""
    intents = ["IDLE"] * 96
    intents[period] = intent
    bsm._schedule_manager.strategic_intents = intents


def _set_discharge_action(bsm: BatterySystemManager, period: int, kwh: float) -> None:
    """Set a battery action for EXPORT_ARBITRAGE discharge calculation."""
    actions = [0.0] * 96
    actions[period] = kwh
    bsm._schedule_manager.current_schedule = SimpleNamespace(actions=actions)


PERIOD = 20  # Arbitrary test period


class TestDischargeInhibitSuppressesDischarge:
    def test_load_support_discharges_when_inhibit_inactive(self):
        bsm, controller = _make_bsm(inhibit_active=False)
        _set_intent(bsm, PERIOD, "LOAD_SUPPORT")

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 100

    def test_load_support_discharge_suppressed_when_inhibit_active(self):
        bsm, controller = _make_bsm(inhibit_active=True)
        _set_intent(bsm, PERIOD, "LOAD_SUPPORT")

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 0

    def test_export_arbitrage_discharges_when_inhibit_inactive(self):
        bsm, controller = _make_bsm(inhibit_active=False)
        _set_intent(bsm, PERIOD, "EXPORT_ARBITRAGE")
        _set_discharge_action(bsm, PERIOD, -2.0)  # -2 kWh → -8 kW → ~53%

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] > 0

    def test_export_arbitrage_discharge_suppressed_when_inhibit_active(self):
        bsm, controller = _make_bsm(inhibit_active=True)
        _set_intent(bsm, PERIOD, "EXPORT_ARBITRAGE")
        _set_discharge_action(bsm, PERIOD, -2.0)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 0


class TestDischargeInhibitDoesNotAffectNonDischarge:
    @pytest.mark.parametrize("intent", ["GRID_CHARGING", "SOLAR_STORAGE", "IDLE"])
    def test_non_discharge_intent_unaffected(self, intent: str):
        bsm, controller = _make_bsm(inhibit_active=True)
        _set_intent(bsm, PERIOD, intent)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 0

    def test_inhibit_sensor_not_queried_when_discharge_rate_is_zero(self):
        """Inhibit sensor must not be called when there is nothing to suppress."""
        bsm, controller = _make_bsm(inhibit_active=True)
        _set_intent(bsm, PERIOD, "IDLE")

        bsm._apply_period_schedule(PERIOD)

        assert controller.inhibit_query_count == 0

    def test_grid_charge_not_modified_when_discharge_inhibited(self):
        """Inhibiting discharge must not start grid charging."""
        bsm, controller = _make_bsm(inhibit_active=True)
        _set_intent(bsm, PERIOD, "LOAD_SUPPORT")

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["grid_charge"][-1] is False


class TestApplyDischargeInhibit:
    def test_suppresses_discharge_when_inhibit_becomes_active(self):
        """Inhibit becoming active mid-period must stop discharge within 1 minute."""
        bsm, controller = _make_bsm(inhibit_active=False)
        _set_intent(bsm, PERIOD, "LOAD_SUPPORT")
        bsm._apply_period_schedule(PERIOD)  # Sets desired=100, applied=100
        assert controller.calls["discharge_rate"][-1] == 100

        controller.inhibit_active = True
        bsm.apply_discharge_inhibit()

        assert controller.calls["discharge_rate"][-1] == 0

    def test_restores_discharge_when_inhibit_clears(self):
        """Discharge must resume at the scheduled rate once inhibit clears."""
        bsm, controller = _make_bsm(inhibit_active=True)
        _set_intent(bsm, PERIOD, "LOAD_SUPPORT")
        bsm._apply_period_schedule(PERIOD)  # Sets desired=100, applied=0 (inhibited)

        controller.inhibit_active = False
        bsm.apply_discharge_inhibit()

        assert controller.calls["discharge_rate"][-1] == 100

    def test_no_inverter_write_when_inhibit_state_unchanged(self):
        """Must not write to the inverter on every tick — only on state changes."""
        bsm, controller = _make_bsm(inhibit_active=True)
        _set_intent(bsm, PERIOD, "LOAD_SUPPORT")
        bsm._apply_period_schedule(PERIOD)
        writes_after_schedule = len(controller.calls["discharge_rate"])

        bsm.apply_discharge_inhibit()  # State unchanged — no new write
        bsm.apply_discharge_inhibit()

        assert len(controller.calls["discharge_rate"]) == writes_after_schedule

    def test_no_write_when_desired_rate_is_zero(self):
        """Inhibit changes on a non-discharge period must not trigger any write."""
        bsm, controller = _make_bsm(inhibit_active=False)
        _set_intent(bsm, PERIOD, "IDLE")
        bsm._apply_period_schedule(PERIOD)  # desired=0, applied=0
        writes_after_schedule = len(controller.calls["discharge_rate"])

        controller.inhibit_active = True
        bsm.apply_discharge_inhibit()  # target=0 == last applied=0 → no write

        assert len(controller.calls["discharge_rate"]) == writes_after_schedule

    def test_desired_rate_updated_at_period_boundary_while_inhibited(self):
        """If the schedule changes while inhibit is active, restoring later uses the new rate."""
        bsm, controller = _make_bsm(inhibit_active=True)

        # First period: LOAD_SUPPORT (desired=100), inhibit active → applied=0
        _set_intent(bsm, PERIOD, "LOAD_SUPPORT")
        bsm._apply_period_schedule(PERIOD)
        assert bsm._desired_discharge_rate == 100

        # Period boundary fires while inhibit still active: new period has lower rate
        _set_intent(bsm, PERIOD, "EXPORT_ARBITRAGE")
        _set_discharge_action(bsm, PERIOD, -2.0)  # → ~53%
        bsm._apply_period_schedule(PERIOD)
        desired_after_boundary = bsm._desired_discharge_rate
        assert desired_after_boundary > 0
        assert controller.calls["discharge_rate"][-1] == 0  # Still inhibited

        # Now inhibit clears — must restore the new period's rate, not the old 100%
        controller.inhibit_active = False
        bsm.apply_discharge_inhibit()

        assert controller.calls["discharge_rate"][-1] == desired_after_boundary
