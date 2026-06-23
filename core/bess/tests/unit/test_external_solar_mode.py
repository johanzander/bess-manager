"""Tests for the AC-coupled `external_solar_mode` battery setting.

When enabled, the SOLAR_STORAGE strategic intent must translate to
`grid_charge=True` so the battery can AC-charge from surplus solar that
returns via the meter (the battery inverter has no DC solar input).
All other intents must keep their default mapping.
"""

import pytest

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
            ("EXPORT_ARBITRAGE", False),
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
