"""Test the new BatterySettings dataclass implementation."""

from core.bess.settings import BatterySettings


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
