"""Test the new BatterySettings dataclass implementation."""

from core.bess.settings import (
    BatterySettings,
    TemperatureDeratingSettings,
    apply_temperature_derating,
    interpolate_derating,
)


def test_battery_settings_properties():
    """Test that the battery settings properties are correctly set and accessible."""
    # Create with default values
    settings = BatterySettings()

    # Test that primary fields are set correctly
    assert settings.total_capacity == 30.0
    assert settings.min_soc == 10
    assert settings.max_soc == 100
    assert settings.max_charge_power_kw == 15.0
    assert settings.max_discharge_power_kw == 15.0

    # Test that computed fields are calculated correctly
    assert settings.reserved_capacity == 3.0  # 10% of 30

    # Test with custom values
    custom_settings = BatterySettings(
        total_capacity=50.0,
        min_soc=20,
        max_soc=90,
        max_charge_power_kw=10.0,
        max_discharge_power_kw=8.0,
        cycle_cost_per_kwh=0.25,
    )

    assert custom_settings.total_capacity == 50.0
    assert custom_settings.min_soc == 20
    assert custom_settings.max_soc == 90
    assert custom_settings.max_charge_power_kw == 10.0
    assert custom_settings.max_discharge_power_kw == 8.0

    # Test computed fields with custom values
    assert custom_settings.reserved_capacity == 10.0  # 20% of 50


def test_battery_settings_update():
    """Test the update method of BatterySettings."""
    settings = BatterySettings()

    # Update with canonical keys
    settings.update(
        total_capacity=40.0, min_soc=15, max_soc=95, max_charge_power_kw=12.0
    )

    assert settings.total_capacity == 40.0
    assert settings.min_soc == 15
    assert settings.max_soc == 95
    assert settings.max_charge_power_kw == 12.0

    # Verify computed fields are updated
    assert settings.reserved_capacity == 6.0  # 15% of 40

    # Update with canonical keys again
    settings.update(
        total_capacity=35.0, min_soc=20, max_soc=90, max_charge_power_kw=10.0
    )

    assert settings.total_capacity == 35.0
    assert settings.min_soc == 20
    assert settings.max_soc == 90
    assert settings.max_charge_power_kw == 10.0

    # Verify computed fields are updated again
    assert settings.reserved_capacity == 7.0  # 20% of 35


def test_battery_settings_from_ha_config():
    """Test creating BatterySettings from Home Assistant config."""
    settings = BatterySettings()

    # Test with valid config using only canonical keys
    config = {
        "battery": {
            "total_capacity": 40.0,
            "max_charge_power_kw": 12.0,
            "max_discharge_power_kw": 12.0,
            "cycle_cost_per_kwh": 0.35,
        }
    }

    settings.from_ha_config(config)

    assert settings.total_capacity == 40.0
    assert settings.max_charge_power_kw == 12.0
    assert settings.max_discharge_power_kw == 12.0
    assert settings.cycle_cost_per_kwh == 0.35

    # Verify computed fields
    assert settings.reserved_capacity == 4.0  # 10% of 40


def test_battery_settings_action_threshold():
    """Test action threshold setting is properly handled."""
    settings = BatterySettings()

    # Test default value (should be 0.0 to not affect existing tests)
    assert settings.min_action_profit_threshold == 0.0

    # Test update
    settings.update(min_action_profit_threshold=1.5)
    assert settings.min_action_profit_threshold == 1.5

    # Test from_ha_config
    config = {
        "battery": {
            "min_action_profit_threshold": 2.0,
        }
    }
    settings.from_ha_config(config)
    assert settings.min_action_profit_threshold == 2.0


def test_battery_settings_camelcase_update():
    """Test that update method handles camelCase keys from API layer."""
    settings = BatterySettings()

    # Update with camelCase keys (as sent from frontend/API)
    settings.update(
        totalCapacity=25.0,
        maxChargePowerKw=8.0,
        cycleCostPerKwh=0.55,
        minActionProfitThreshold=1.2,
    )

    # Verify that values were correctly mapped to snake_case attributes
    assert settings.total_capacity == 25.0
    assert settings.max_charge_power_kw == 8.0
    assert settings.cycle_cost_per_kwh == 0.55
    assert settings.min_action_profit_threshold == 1.2

    # Verify computed fields are updated
    assert settings.reserved_capacity == 2.5  # 10% of 25


def test_battery_settings_invalid_key_raises_error():
    """Test that update method raises AttributeError for invalid keys."""
    import pytest

    settings = BatterySettings()

    # Attempt to update with an invalid key should raise AttributeError
    with pytest.raises(AttributeError) as exc_info:
        settings.update(invalidKey=123)

    assert "BatterySettings has no attribute 'invalid_key'" in str(exc_info.value)
    assert "from key 'invalidKey'" in str(exc_info.value)


def test_battery_settings_independent_charge_discharge_power():
    """Test that charge and discharge power can be set independently."""
    settings = BatterySettings()

    # Test both orderings - should give same result regardless of key order
    settings.update(maxChargePowerKw=10.0, maxDischargePowerKw=8.0)
    assert settings.max_charge_power_kw == 10.0
    assert settings.max_discharge_power_kw == 8.0

    # Test reverse order - should NOT have dict ordering bugs
    settings2 = BatterySettings()
    settings2.update(maxDischargePowerKw=8.0, maxChargePowerKw=10.0)
    assert settings2.max_charge_power_kw == 10.0
    assert settings2.max_discharge_power_kw == 8.0


def test_temperature_derating_defaults():
    """Test TemperatureDeratingSettings defaults."""
    settings = TemperatureDeratingSettings()
    assert settings.enabled is False
    assert len(settings.derating_curve) == 5
    assert settings.derating_curve[0] == (-1.0, 0.0)
    assert settings.derating_curve[-1] == (15.0, 100.0)


def test_temperature_derating_from_ha_config():
    """Test loading temperature derating settings from config."""
    settings = TemperatureDeratingSettings()
    config = {
        "battery": {
            "temperature_derating": {
                "enabled": True,
                "derating_curve": [
                    [0, 0],
                    [10, 50],
                    [20, 100],
                ],
            }
        }
    }
    settings.from_ha_config(config)
    assert settings.enabled is True
    assert len(settings.derating_curve) == 3
    assert settings.derating_curve[0] == (0.0, 0.0)
    assert settings.derating_curve[1] == (10.0, 50.0)
    assert settings.derating_curve[2] == (20.0, 100.0)


def test_temperature_derating_from_ha_config_disabled():
    """Test loading with derating disabled."""
    settings = TemperatureDeratingSettings()
    config = {"battery": {}}
    settings.from_ha_config(config)
    assert settings.enabled is False


def test_interpolate_derating_below_range():
    """Test derating below the curve range returns lowest point value."""
    curve = [(-1.0, 0.0), (0.0, 20.0), (15.0, 100.0)]
    assert interpolate_derating(-10.0, curve) == 0.0
    assert interpolate_derating(-1.0, curve) == 0.0


def test_interpolate_derating_above_range():
    """Test derating above the curve range returns highest point value."""
    curve = [(-1.0, 0.0), (0.0, 20.0), (15.0, 100.0)]
    assert interpolate_derating(15.0, curve) == 100.0
    assert interpolate_derating(30.0, curve) == 100.0


def test_interpolate_derating_at_points():
    """Test derating at exact curve points."""
    curve = [(-1.0, 0.0), (0.0, 20.0), (5.0, 50.0), (10.0, 80.0), (15.0, 100.0)]
    assert interpolate_derating(0.0, curve) == 20.0
    assert interpolate_derating(5.0, curve) == 50.0
    assert interpolate_derating(10.0, curve) == 80.0


def test_interpolate_derating_between_points():
    """Test linear interpolation between curve points."""
    curve = [(0.0, 0.0), (10.0, 100.0)]
    assert interpolate_derating(5.0, curve) == 50.0
    assert interpolate_derating(2.5, curve) == 25.0
    assert interpolate_derating(7.5, curve) == 75.0


def test_interpolate_derating_empty_curve():
    """Test empty curve returns 100%."""
    assert interpolate_derating(10.0, []) == 100.0


def test_apply_temperature_derating():
    """Test applying derating to produce per-period charge power limits."""
    curve = [(0.0, 0.0), (10.0, 50.0), (20.0, 100.0)]
    max_power = 5.0
    temperatures = [0.0, 5.0, 10.0, 15.0, 20.0, 25.0]

    result = apply_temperature_derating(max_power, temperatures, curve)

    assert len(result) == 6
    assert result[0] == 0.0  # 0°C -> 0% -> 0kW
    assert result[1] == 1.25  # 5°C -> 25% -> 1.25kW
    assert result[2] == 2.5  # 10°C -> 50% -> 2.5kW
    assert result[3] == 3.75  # 15°C -> 75% -> 3.75kW
    assert result[4] == 5.0  # 20°C -> 100% -> 5kW
    assert result[5] == 5.0  # 25°C -> 100% -> 5kW
