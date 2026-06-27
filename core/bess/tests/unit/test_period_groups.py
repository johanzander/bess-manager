"""Tests for get_detailed_period_groups() discharge rate computation."""

import pytest

from core.bess.dp_schedule import DPSchedule
from core.bess.growatt_min_controller import GrowattMinController
from core.bess.settings import BatterySettings


@pytest.fixture
def settings():
    return BatterySettings(
        total_capacity=30.0,
        max_charge_power_kw=6.0,
        max_discharge_power_kw=6.0,
        min_soc=10.0,
        max_soc=95.0,
        cycle_cost_per_kwh=0.05,
    )


@pytest.fixture
def controller(settings):
    return GrowattMinController(settings)


def _make_schedule(actions: list[float]) -> DPSchedule:
    n = len(actions)
    return DPSchedule(
        actions=actions,
        state_of_energy=[20.0] * n,
        prices=[2.0] * n,
    )


class TestDischargeRateFromSchedule:
    def test_export_arbitrage_uses_action_derived_rate(self, controller):
        """BATTERY_EXPORT discharge_rate reflects actual battery action, not 100%."""
        # -0.9 kWh / 0.25 h = -3.6 kW; 3.6 / 6.0 * 100 = 60%
        intents = ["IDLE"] * 96
        intents[20] = "BATTERY_EXPORT"
        intents[21] = "BATTERY_EXPORT"
        intents[22] = "BATTERY_EXPORT"
        intents[23] = "BATTERY_EXPORT"

        actions = [0.0] * 96
        actions[20] = -0.9
        actions[21] = -0.9
        actions[22] = -0.9
        actions[23] = -0.9

        controller.strategic_intents = intents
        controller.current_schedule = _make_schedule(actions)

        groups = controller.get_detailed_period_groups()

        export_group = next(g for g in groups if g["intent"] == "BATTERY_EXPORT")
        assert export_group["discharge_rate"] == 60  # round(3.6/6.0*100)

    def test_no_schedule_gives_zero_rate(self, controller):
        """With no current_schedule, discharge_rate is 0 (no fallback to static 100)."""
        intents = ["IDLE"] * 96
        intents[20] = "BATTERY_EXPORT"

        controller.strategic_intents = intents
        controller.current_schedule = None

        groups = controller.get_detailed_period_groups()

        export_group = next(g for g in groups if g["intent"] == "BATTERY_EXPORT")
        assert export_group["discharge_rate"] == 0

    def test_actions_parameter_overrides_schedule(self, controller):
        """Explicit actions parameter takes precedence over current_schedule."""
        intents = ["BATTERY_EXPORT"] * 4  # four 15-min periods = 1 hour

        # schedule has 0.9 kWh (would give 60%), but we pass 0.45 kWh (should give 30%)
        controller.current_schedule = _make_schedule([-0.9] * 4)

        groups = controller.get_detailed_period_groups(
            intents=intents,
            actions=[-0.45, -0.45, -0.45, -0.45],
        )

        assert len(groups) == 1
        # 0.45 / 0.25 = 1.8 kW; round(1.8 / 6.0 * 100) = 30
        assert groups[0]["discharge_rate"] == 30

    def test_load_support_uses_action_derived_rate(self, controller):
        """LOAD_SUPPORT discharge_rate reflects action, not 100%."""
        intents = ["IDLE"] * 96
        intents[18] = "LOAD_SUPPORT"
        intents[19] = "LOAD_SUPPORT"
        intents[20] = "LOAD_SUPPORT"
        intents[21] = "LOAD_SUPPORT"

        actions = [0.0] * 96
        # -0.3 kWh / 0.25 h = -1.2 kW; round(1.2 / 6.0 * 100) = 20
        actions[18] = -0.3
        actions[19] = -0.3
        actions[20] = -0.3
        actions[21] = -0.3

        controller.strategic_intents = intents
        controller.current_schedule = _make_schedule(actions)

        groups = controller.get_detailed_period_groups()
        ls_group = next(g for g in groups if g["intent"] == "LOAD_SUPPORT")
        assert ls_group["discharge_rate"] == 20

    def test_idle_always_zero(self, controller):
        """IDLE periods always produce discharge_rate=0 regardless of schedule."""
        intents = ["IDLE"] * 4
        actions = [-0.9] * 4  # would produce non-zero rate for discharge intents

        controller.strategic_intents = intents
        controller.current_schedule = _make_schedule(actions)

        groups = controller.get_detailed_period_groups()
        assert len(groups) == 1
        assert groups[0]["discharge_rate"] == 0

    def test_different_rates_split_into_separate_groups(self, controller):
        """Consecutive BATTERY_EXPORT periods with different rates form separate groups."""
        intents = ["BATTERY_EXPORT"] * 8
        actions = [-0.9] * 4 + [-0.45] * 4  # 60% then 30%

        controller.strategic_intents = intents
        controller.current_schedule = _make_schedule(actions)

        groups = controller.get_detailed_period_groups()
        assert len(groups) == 2
        assert groups[0]["discharge_rate"] == 60
        assert groups[1]["discharge_rate"] == 30
