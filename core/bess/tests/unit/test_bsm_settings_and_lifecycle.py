"""Fast unit tests for BatterySystemManager settings, lifecycle, and getters.

These tests exercise orchestration methods that do NOT require the DP optimizer,
using MockHomeAssistantController from conftest.
"""

from unittest.mock import patch

import pytest

from core.bess.battery_system_manager import BatterySystemManager
from core.bess.exceptions import SystemConfigurationError
from core.bess.price_manager import MockSource

_DEFAULT_OPTIONS = {"inverter": {"platform": "growatt_server_min"}}


@pytest.fixture
def system(mock_controller):
    return BatterySystemManager(
        controller=mock_controller,
        price_source=MockSource([1.0] * 96),
        addon_options=_DEFAULT_OPTIONS,
    )


class TestGetSettings:
    def test_returns_battery_home_price(self, system):
        result = system.get_settings()
        assert "battery" in result
        assert "home" in result
        assert "price" in result
        assert result["battery"] is system.battery_settings
        assert result["home"] is system.home_settings
        assert result["price"] is system.price_settings


class TestUpdateSettings:
    def test_battery_settings_updated(self, system):
        system.update_settings({"battery": {"total_capacity": 20.0}})
        assert system.battery_settings.total_capacity == 20.0

    def test_price_settings_synced_to_price_manager(self, system):
        system.update_settings({"price": {"markup_rate": 0.05}})
        assert system.price_settings.markup_rate == 0.05
        assert system._price_manager.markup_rate == 0.05

    def test_price_update_clears_cache(self, system):
        with patch.object(system._price_manager, "clear_cache") as mock_clear:
            system.update_settings({"price": {"vat_multiplier": 1.25}})
            mock_clear.assert_called_once()

    def test_invalid_settings_raises_system_configuration_error(self, system):
        with pytest.raises(SystemConfigurationError):
            system.update_settings({"battery": {"capacity": "not_a_number"}})

    def test_energy_provider_update_creates_new_source(self, system):
        system.update_settings(
            {
                "energy_provider": {
                    "provider": "nordpool_official",
                    "nordpool_official": {"config_entry_id": "abc123"},
                }
            }
        )
        assert system._energy_provider_config["provider"] == "nordpool_official"

    def test_home_settings_enables_power_monitor(self, system):
        assert system._power_monitor is None
        system.update_settings({"home": {"power_monitoring_enabled": True}})
        assert system._power_monitor is not None


class TestSwitchInverterPlatform:
    def test_switch_to_sph(self, system):
        system.switch_inverter_platform("growatt_server_sph")
        assert system.inverter_platform == "growatt_server_sph"
        assert system._inverter_controller is not None

    def test_switch_to_solax_modbus(self, system):
        system.switch_inverter_platform("solax_modbus_growatt_min")
        assert system.inverter_platform == "solax_modbus_growatt_min"

    def test_switch_to_solax_native(self, system):
        system.switch_inverter_platform("solax_modbus_native")
        assert system.inverter_platform == "solax_modbus_native"

    def test_same_platform_is_noop(self, system):
        original_controller = system._inverter_controller
        system.switch_inverter_platform("growatt_server_min")
        assert system._inverter_controller is original_controller

    def test_invalid_platform_raises(self, system):
        with pytest.raises(SystemConfigurationError):
            system.switch_inverter_platform("nonexistent_platform")


class TestResolveInitialPlatform:
    def test_new_format_platform_key(self):
        result = BatterySystemManager._resolve_initial_platform(
            {"inverter": {"platform": "growatt_server_sph"}}
        )
        assert result == "growatt_server_sph"

    def test_legacy_growatt_min(self):
        result = BatterySystemManager._resolve_initial_platform(
            {"growatt": {"inverter_type": "MIN"}}
        )
        assert result == "growatt_server_min"

    def test_legacy_growatt_sph(self):
        result = BatterySystemManager._resolve_initial_platform(
            {"growatt": {"inverter_type": "SPH"}}
        )
        assert result == "growatt_server_sph"

    def test_fresh_install_returns_none(self):
        result = BatterySystemManager._resolve_initial_platform({})
        assert result is None

    def test_unknown_legacy_type_asserts(self):
        with pytest.raises(AssertionError):
            BatterySystemManager._resolve_initial_platform(
                {"growatt": {"inverter_type": "UNKNOWN"}}
            )

    def test_unknown_platform_asserts(self):
        with pytest.raises(AssertionError):
            BatterySystemManager._resolve_initial_platform(
                {"inverter": {"platform": "bogus"}}
            )


class TestCreatePriceSource:
    def test_octopus_source(self, mock_controller):
        system = BatterySystemManager(
            controller=mock_controller,
            energy_provider_config={
                "provider": "octopus",
                "octopus": {
                    "import_today_entity": "event.agile_import_today",
                    "import_tomorrow_entity": "event.agile_import_tomorrow",
                    "export_today_entity": "event.agile_export_today",
                    "export_tomorrow_entity": "event.agile_export_tomorrow",
                },
            },
            addon_options=_DEFAULT_OPTIONS,
        )
        from core.bess.octopus_energy_source import OctopusEnergySource

        assert isinstance(system._price_manager.price_source, OctopusEnergySource)

    def test_unknown_provider_raises(self, mock_controller):
        with pytest.raises(SystemConfigurationError):
            BatterySystemManager(
                controller=mock_controller,
                energy_provider_config={"provider": "unknown_provider"},
                addon_options=_DEFAULT_OPTIONS,
            )


class TestStartLifecycle:
    def test_unconfigured_system_start_is_noop(self, mock_controller):
        system = BatterySystemManager(
            controller=mock_controller,
            price_source=MockSource([1.0] * 96),
            addon_options={},
        )
        assert not system.is_configured
        system.start()

    def test_controller_property_raises_when_none(self, system):
        system._controller = None
        with pytest.raises(RuntimeError):
            _ = system.controller


class TestHandleSpecialCases:
    def test_period_zero_captures_initial_soc(self, system, mock_controller):
        mock_controller.settings["battery_soc"] = 75
        system._handle_special_cases(period=0, prepare_next_day=False)
        assert system._initial_soc_pct == 75

    def test_non_zero_period_does_not_capture_soc(self, system):
        system._handle_special_cases(period=5, prepare_next_day=False)
        assert system._initial_soc_pct is None

    def test_prepare_next_day_clears_stores_and_refetches(self, system):
        system._consumption_predictions = [1.0] * 96
        system._solar_predictions = [0.0] * 96
        with patch.object(system, "_fetch_predictions") as mock_fetch:
            system._handle_special_cases(period=0, prepare_next_day=True)
            mock_fetch.assert_called_once()


class TestRuntimeFailureTracking:
    def test_no_failures_initially(self, system):
        assert system.get_runtime_failures() == []

    def test_record_and_retrieve(self, system):
        system._runtime_failure_tracker.record_failure(
            operation="test op", category="test", error=Exception("boom")
        )
        failures = system.get_runtime_failures()
        assert len(failures) == 1
        assert failures[0].operation == "test op"

    def test_dismiss_by_id(self, system):
        system._runtime_failure_tracker.record_failure(
            operation="test", category="test", error=Exception("x")
        )
        fid = system.get_runtime_failures()[0].id
        system.dismiss_runtime_failure(fid)
        assert system.get_runtime_failures() == []

    def test_dismiss_all(self, system):
        for i in range(3):
            system._runtime_failure_tracker.record_failure(
                operation=f"op{i}", category="test", error=Exception("x")
            )
        count = system.dismiss_all_runtime_failures()
        assert count == 3
        assert system.get_runtime_failures() == []

    def test_dismiss_nonexistent_raises(self, system):
        with pytest.raises(ValueError):
            system.dismiss_runtime_failure("nonexistent-id")


class TestCriticalSensorFailures:
    def test_no_failures_initially(self, system):
        assert not system.has_critical_sensor_failures()
        assert system.get_critical_sensor_failures() == []

    def test_after_setting_failures(self, system):
        system._critical_sensor_failures = ["Battery SOC"]
        assert system.has_critical_sensor_failures()
        assert system.get_critical_sensor_failures() == ["Battery SOC"]

    def test_returns_copy(self, system):
        system._critical_sensor_failures = ["x"]
        result = system.get_critical_sensor_failures()
        result.append("y")
        assert system.get_critical_sensor_failures() == ["x"]


class TestGetCurrentDailyView:
    def test_invalid_period_raises(self, system):
        with pytest.raises(SystemConfigurationError):
            system.get_current_daily_view(current_period=100)

    def test_negative_period_raises(self, system):
        with pytest.raises(SystemConfigurationError):
            system.get_current_daily_view(current_period=-1)

    def test_no_schedule_raises_value_error(self, system):
        with pytest.raises(ValueError):
            system.get_current_daily_view(current_period=0)


class TestGetTodayPriceData:
    def test_returns_prices(self, system):
        prices = system._get_today_price_data()
        assert len(prices) > 0

    def test_fallback_on_error(self, system):
        with patch.object(
            system._price_manager, "get_today_prices", side_effect=Exception("fail")
        ):
            prices = system._get_today_price_data()
        assert prices == [1.0] * 24


class TestShouldApplySchedule:
    def test_hardware_write_pending_forces_apply(self, system):
        system._hardware_write_pending = True
        result, reason = system._should_apply_schedule(
            is_first_run=False,
            period=10,
            prepare_next_day=False,
            temp_growatt=system._inverter_controller,
            optimization_period=10,
            temp_schedule=None,
        )
        assert result is True
        assert "Retry" in reason


class TestSetDemoMode:
    """set_demo_mode delegates hardware initialization to the inverter controller."""

    def test_enable_sets_test_mode_true(self, system, mock_controller):
        system.set_demo_mode(True)
        assert mock_controller.test_mode is True

    def test_disable_sets_test_mode_false(self, system, mock_controller):
        system.set_demo_mode(False)
        assert mock_controller.test_mode is False

    def test_going_live_calls_initialize_hardware_on_inverter(self, system):
        """Going live delegates to the inverter controller's public method."""
        from unittest.mock import MagicMock

        system._inverter_controller.initialize_hardware = MagicMock()
        system.set_demo_mode(False)
        system._inverter_controller.initialize_hardware.assert_called_once_with(
            system._controller
        )

    def test_enabling_demo_skips_initialize_hardware(self, system):
        """Enabling demo mode must NOT trigger hardware initialization."""
        from unittest.mock import MagicMock

        system._inverter_controller.initialize_hardware = MagicMock()
        system.set_demo_mode(True)
        system._inverter_controller.initialize_hardware.assert_not_called()
