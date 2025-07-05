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
