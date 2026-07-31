"""Tests for the AC-coupled `external_solar_mode` battery setting.

When enabled, the SOLAR_STORAGE strategic intent must translate to
`grid_charge=True` so the battery can AC-charge from surplus solar that
returns via the meter (the battery inverter has no DC solar input).
All other intents must keep their default mapping.
"""

import pytest

from core.bess.growatt_min_controller import GrowattMinController
from core.bess.growatt_sph_controller import GrowattSphController
from core.bess.settings import BatterySettings
from core.bess.solax_controller import SolaxController


def _settings(*, external_solar_mode: bool) -> BatterySettings:
    return BatterySettings(
        total_capacity=10.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        min_soc=15.0,
        max_soc=95.0,
        external_solar_mode=external_solar_mode,
    )


class TestExternalSolarModeOverride:
    def test_default_is_disabled(self) -> None:
        assert BatterySettings(total_capacity=10.0).external_solar_mode is False

    def test_solar_storage_grid_charge_false_when_disabled(self) -> None:
        ctrl = SolaxController(battery_settings=_settings(external_solar_mode=False))
        grid_charge, discharge_rate = ctrl._map_intent_to_rates("SOLAR_STORAGE", 0.0)
        assert grid_charge is False
        assert discharge_rate == 0

    def test_solar_storage_grid_charge_true_when_enabled(self) -> None:
        ctrl = SolaxController(battery_settings=_settings(external_solar_mode=True))
        grid_charge, discharge_rate = ctrl._map_intent_to_rates("SOLAR_STORAGE", 0.0)
        assert grid_charge is True
        assert discharge_rate == 0

    @pytest.mark.parametrize(
        "intent,expected_grid_charge",
        [
            ("GRID_CHARGING", True),
            ("LOAD_SUPPORT", False),
            ("BATTERY_EXPORT", False),
            ("IDLE", False),
        ],
    )
    def test_other_intents_unaffected_when_enabled(
        self, intent: str, expected_grid_charge: bool
    ) -> None:
        ctrl = SolaxController(battery_settings=_settings(external_solar_mode=True))
        grid_charge, _ = ctrl._map_intent_to_rates(intent, 0.0)
        assert grid_charge is expected_grid_charge

    def test_detailed_period_groups_apply_override(self) -> None:
        ctrl = SolaxController(battery_settings=_settings(external_solar_mode=True))
        ctrl.strategic_intents = ["SOLAR_STORAGE"] * 96
        groups = ctrl.get_detailed_period_groups()
        assert groups, "expected at least one period group"
        for group in groups:
            assert group["grid_charge"] is True
            assert group["intent"] == "SOLAR_STORAGE"

    def test_detailed_period_groups_no_override_when_disabled(self) -> None:
        ctrl = SolaxController(battery_settings=_settings(external_solar_mode=False))
        ctrl.strategic_intents = ["SOLAR_STORAGE"] * 96
        groups = ctrl.get_detailed_period_groups()
        for group in groups:
            assert group["grid_charge"] is False

    def test_get_period_settings_applies_override_without_schedule(self) -> None:
        ctrl = SolaxController(battery_settings=_settings(external_solar_mode=True))
        ctrl.strategic_intents = ["SOLAR_STORAGE"] * 96
        ctrl.current_schedule = None
        settings = ctrl.get_period_settings(period=10)
        assert settings["grid_charge"] is True
        assert settings["strategic_intent"] == "SOLAR_STORAGE"


class TestExternalSolarModeBattModeOverride:
    """external_solar_mode should also flip SOLAR_STORAGE's mode to battery_first.

    On AC-coupled setups, Load First mode does not initiate battery charging
    even with grid_charge enabled — the EMS waits for a trigger that never
    comes.  Battery First mode makes the inverter actively charge from the
    AC side.
    """

    def test_solar_storage_mode_is_load_first_when_disabled(self) -> None:
        ctrl = SolaxController(battery_settings=_settings(external_solar_mode=False))
        ctrl.strategic_intents = ["SOLAR_STORAGE"] * 96
        settings = ctrl.get_period_settings(period=10)
        assert settings["batt_mode"] == "load_first"

    def test_solar_storage_mode_is_battery_first_when_enabled(self) -> None:
        ctrl = SolaxController(battery_settings=_settings(external_solar_mode=True))
        ctrl.strategic_intents = ["SOLAR_STORAGE"] * 96
        settings = ctrl.get_period_settings(period=10)
        assert settings["batt_mode"] == "battery_first"

    @pytest.mark.parametrize(
        "intent,expected_mode",
        [
            ("GRID_CHARGING", "battery_first"),
            ("LOAD_SUPPORT", "load_first"),
            ("BATTERY_EXPORT", "grid_first"),
            ("IDLE", "load_first"),
        ],
    )
    def test_other_intents_unaffected_when_enabled(
        self, intent: str, expected_mode: str
    ) -> None:
        ctrl = SolaxController(battery_settings=_settings(external_solar_mode=True))
        ctrl.strategic_intents = [intent] * 96
        settings = ctrl.get_period_settings(period=10)
        assert settings["batt_mode"] == expected_mode

    def test_detailed_period_groups_apply_mode_override(self) -> None:
        ctrl = SolaxController(battery_settings=_settings(external_solar_mode=True))
        ctrl.strategic_intents = ["SOLAR_STORAGE"] * 96
        groups = ctrl.get_detailed_period_groups()
        assert groups, "expected at least one period group"
        for group in groups:
            assert group["mode"] == "battery_first"
            assert group["grid_charge"] is True


class TestExternalSolarModeGrowattMinTouPath:
    """The MIN controller's TOU grouping builds the segments actually written
    to hardware.  It must apply the external_solar_mode override, otherwise
    SOLAR_STORAGE stays load_first, no TOU segment is created (load_first
    groups are skipped) and an AC-coupled battery never charges during the
    solar window.
    """

    def _controller(self, *, external_solar_mode: bool) -> GrowattMinController:
        ctrl = GrowattMinController(
            battery_settings=_settings(external_solar_mode=external_solar_mode)
        )
        ctrl.strategic_intents = ["IDLE"] * 40 + ["SOLAR_STORAGE"] * 16 + ["IDLE"] * 40
        return ctrl

    def test_solar_storage_grouped_as_battery_first_when_enabled(self) -> None:
        ctrl = self._controller(external_solar_mode=True)
        groups = ctrl._group_periods_by_mode(ctrl.strategic_intents)
        solar_group = next(g for g in groups if g["mode"] == "battery_first")
        assert solar_group["start_period"] == 40
        assert solar_group["end_period"] == 55

    def test_solar_storage_grouped_as_load_first_when_disabled(self) -> None:
        ctrl = self._controller(external_solar_mode=False)
        groups = ctrl._group_periods_by_mode(ctrl.strategic_intents)
        assert all(g["mode"] == "load_first" for g in groups)

    def test_solar_storage_produces_tou_interval_when_enabled(self) -> None:
        ctrl = self._controller(external_solar_mode=True)
        intervals = ctrl._groups_to_tou_intervals(
            ctrl._group_periods_by_mode(ctrl.strategic_intents)
        )
        assert len(intervals) == 1
        assert intervals[0]["batt_mode"] == "battery_first"

    def test_no_tou_interval_when_disabled(self) -> None:
        ctrl = self._controller(external_solar_mode=False)
        assert (
            ctrl._groups_to_tou_intervals(
                ctrl._group_periods_by_mode(ctrl.strategic_intents)
            )
            == []
        )


class TestExternalSolarModeChargePeriodPlatforms:
    """Period-list platforms (SPH, Solis) exclude SOLAR_STORAGE from charge
    periods because a DC-coupled inverter charges from its own MPPT.  With
    external_solar_mode there is no DC solar input, so SOLAR_STORAGE must
    produce an AC charge period.
    """

    def _controller(self, *, external_solar_mode: bool) -> GrowattSphController:
        ctrl = GrowattSphController(
            battery_settings=_settings(external_solar_mode=external_solar_mode)
        )
        ctrl.strategic_intents = ["IDLE"] * 40 + ["SOLAR_STORAGE"] * 16 + ["IDLE"] * 40
        return ctrl

    def test_solar_storage_becomes_charge_block_when_enabled(self) -> None:
        ctrl = self._controller(external_solar_mode=True)
        charge_blocks, discharge_blocks = ctrl._group_period_blocks()
        assert len(charge_blocks) == 1
        assert charge_blocks[0]["start_period"] == 40
        assert charge_blocks[0]["end_period"] == 55
        assert discharge_blocks == []

    def test_solar_storage_not_a_charge_block_when_disabled(self) -> None:
        ctrl = self._controller(external_solar_mode=False)
        charge_blocks, _ = ctrl._group_period_blocks()
        assert charge_blocks == []

    def test_grid_charging_still_a_charge_block_when_disabled(self) -> None:
        ctrl = self._controller(external_solar_mode=False)
        ctrl.strategic_intents = ["GRID_CHARGING"] * 8 + ["IDLE"] * 88
        charge_blocks, _ = ctrl._group_period_blocks()
        assert len(charge_blocks) == 1
