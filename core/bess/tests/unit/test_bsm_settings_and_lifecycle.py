"""Fast unit tests for BatterySystemManager settings, lifecycle, and getters.

These tests exercise orchestration methods that do NOT require the DP optimizer,
using MockHomeAssistantController from conftest.
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from core.bess.battery_system_manager import BatterySystemManager
from core.bess.exceptions import SystemConfigurationError
from core.bess.models import (
    EnergyData,
    OptimizationResult,
    PeriodData,
)
from core.bess.price_manager import MockSource
from core.bess.time_utils import TIMEZONE

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

    def test_spot_multiplier_synced_to_price_manager(self, system):
        system.update_settings(
            {
                "price": {
                    "spot_multiplier": 1.0175,
                    "export_spot_multiplier": 1.018,
                }
            }
        )
        assert system.price_settings.spot_multiplier == 1.0175
        assert system.price_settings.export_spot_multiplier == 1.018
        assert system._price_manager.spot_multiplier == 1.0175
        assert system._price_manager.export_spot_multiplier == 1.018

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
        system._handle_special_cases(
            period=0, prepare_next_day=False, is_first_run=True
        )
        assert system._initial_soc_pct == 75

    def test_non_zero_period_does_not_capture_soc(self, system):
        system._handle_special_cases(
            period=5, prepare_next_day=False, is_first_run=True
        )
        assert system._initial_soc_pct is None

    def test_prepare_next_day_clears_stores_and_refetches(self, system):
        system._consumption_predictions = [1.0] * 96
        system._solar_predictions = [0.0] * 96
        with (
            patch.object(system, "get_current_daily_view"),
            patch.object(system.daily_view_store, "save_day"),
            patch.object(system, "_fetch_predictions") as mock_fetch,
        ):
            system._handle_special_cases(
                period=0, prepare_next_day=True, is_first_run=False
            )
            mock_fetch.assert_called_once()

    def test_prepare_next_day_saves_daily_view_before_clearing(self, system, tmp_path):
        from datetime import date as date_cls
        from unittest.mock import patch

        from core.bess.daily_view_builder import DailyView
        from core.bess.daily_view_store import DailyViewStore

        # Use a temp persist dir instead of the production default (/data/daily_views),
        # which isn't writable in local/sandboxed test environments.
        system.daily_view_store = DailyViewStore(persist_dir=tmp_path)

        fake_view = DailyView(
            date=date_cls(2026, 7, 9),
            periods=[],
            total_savings=1.5,
            actual_count=0,
            predicted_count=0,
        )

        with patch.object(system, "get_current_daily_view", return_value=fake_view):
            with patch.object(system, "_fetch_predictions"):
                system._handle_special_cases(
                    period=0, prepare_next_day=True, is_first_run=False
                )

        saved = system.daily_view_store.load_day(date_cls(2026, 7, 9))
        assert saved is not None
        assert saved.total_savings == 1.5

    def test_prepare_next_day_skips_save_on_first_run(self, system, tmp_path):
        """No schedule has ever been created yet, so there is nothing to save.

        This reproduces the CI failure in PR #260: build_daily_view() raises
        ValueError("No optimization schedule available") when schedule_store
        is empty, which previously aborted update_battery_schedule entirely
        on the very first call of a fresh run.
        """
        from core.bess.daily_view_store import DailyViewStore

        system.daily_view_store = DailyViewStore(persist_dir=tmp_path)

        with (
            patch.object(system, "get_current_daily_view") as mock_get_view,
            patch.object(system.daily_view_store, "save_day") as mock_save,
            patch.object(system, "_fetch_predictions"),
        ):
            system._handle_special_cases(
                period=0, prepare_next_day=True, is_first_run=True
            )

        mock_get_view.assert_not_called()
        mock_save.assert_not_called()


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


class TestRefreshHealthCheck:
    """Public wrapper so callers outside BatterySystemManager (the scheduler,
    a manual-recheck endpoint) can re-run health checks without reaching into
    the private ``_run_health_check`` method.
    """

    def test_updates_cached_results_from_a_fresh_run(self, system):
        system._critical_sensor_failures = ["Battery SOC"]
        healthy_result = {
            "status": "OK",
            "checks": [{"name": "Battery SOC", "status": "OK", "required": True}],
        }
        with patch(
            "core.bess.battery_system_manager.run_system_health_checks",
            return_value=healthy_result,
        ):
            system.refresh_health_check()

        assert system.get_cached_health_results() == healthy_result
        assert not system.has_critical_sensor_failures()

    def test_recovers_failures_that_are_still_present(self, system):
        failing_result = {
            "status": "ERROR",
            "checks": [
                {
                    "name": "Battery SOC",
                    "status": "ERROR",
                    "required": True,
                    "checks": [],
                }
            ],
        }
        with patch(
            "core.bess.battery_system_manager.run_system_health_checks",
            return_value=failing_result,
        ):
            system.refresh_health_check()

        assert system.has_critical_sensor_failures()
        assert system.get_critical_sensor_failures() == ["Battery SOC"]


class TestHealthRecoveryTracking:
    """A component that goes ERROR/WARNING -> OK between health checks should
    be recorded as a recovery, surviving even if nobody was watching the live
    banner when it happened. See #215.
    """

    def _run(self, system, result):
        with patch(
            "core.bess.battery_system_manager.run_system_health_checks",
            return_value=result,
        ):
            system.refresh_health_check()

    def test_no_recoveries_initially(self, system):
        assert system.get_health_recoveries() == []

    def test_recovery_recorded_on_error_to_ok_transition(self, system):
        self._run(
            system,
            {
                "status": "ERROR",
                "checks": [
                    {
                        "name": "Battery SOC",
                        "status": "ERROR",
                        "required": True,
                        "checks": [],
                    }
                ],
            },
        )
        self._run(
            system,
            {
                "status": "OK",
                "checks": [{"name": "Battery SOC", "status": "OK", "required": True}],
            },
        )

        recoveries = system.get_health_recoveries()
        assert len(recoveries) == 1
        assert recoveries[0].component == "Battery SOC"
        assert recoveries[0].previous_status == "ERROR"

    def test_recovery_detail_names_the_failing_sensor(self, system):
        self._run(
            system,
            {
                "status": "ERROR",
                "checks": [
                    {
                        "name": "Battery Control",
                        "status": "ERROR",
                        "required": True,
                        "checks": [
                            {
                                "name": "Battery Charging Power Rate",
                                "entity_id": "number.growatt_battery_charging_power_rate",
                                "status": "WARNING",
                                "error": "Entity state is 'unavailable'",
                            },
                            {
                                "name": "Grid Charge Enabled",
                                "entity_id": "switch.growatt_grid_charge",
                                "status": "OK",
                                "error": None,
                            },
                        ],
                    }
                ],
            },
        )
        self._run(
            system,
            {
                "status": "OK",
                "checks": [
                    {"name": "Battery Control", "status": "OK", "required": True}
                ],
            },
        )

        recoveries = system.get_health_recoveries()
        assert len(recoveries) == 1
        assert (
            recoveries[0].detail
            == "Battery Charging Power Rate (number.growatt_battery_charging_power_rate)"
        )

    def test_no_recovery_recorded_when_first_check_is_ok(self, system):
        self._run(
            system,
            {
                "status": "OK",
                "checks": [{"name": "Battery SOC", "status": "OK", "required": True}],
            },
        )
        assert system.get_health_recoveries() == []

    def test_no_recovery_recorded_while_still_erroring(self, system):
        self._run(
            system,
            {
                "status": "ERROR",
                "checks": [
                    {
                        "name": "Battery SOC",
                        "status": "ERROR",
                        "required": True,
                        "checks": [],
                    }
                ],
            },
        )
        self._run(
            system,
            {
                "status": "ERROR",
                "checks": [
                    {
                        "name": "Battery SOC",
                        "status": "ERROR",
                        "required": True,
                        "checks": [],
                    }
                ],
            },
        )
        assert system.get_health_recoveries() == []

    def test_pending_recovery_cleared_if_component_errors_again(self, system):
        self._run(
            system,
            {
                "status": "ERROR",
                "checks": [
                    {
                        "name": "Battery SOC",
                        "status": "ERROR",
                        "required": True,
                        "checks": [],
                    }
                ],
            },
        )
        self._run(
            system,
            {
                "status": "OK",
                "checks": [{"name": "Battery SOC", "status": "OK", "required": True}],
            },
        )
        assert len(system.get_health_recoveries()) == 1

        self._run(
            system,
            {
                "status": "ERROR",
                "checks": [
                    {
                        "name": "Battery SOC",
                        "status": "ERROR",
                        "required": True,
                        "checks": [],
                    }
                ],
            },
        )
        assert system.get_health_recoveries() == []

    def test_acknowledge_health_recoveries_clears_them(self, system):
        self._run(
            system,
            {
                "status": "ERROR",
                "checks": [
                    {
                        "name": "Battery SOC",
                        "status": "ERROR",
                        "required": True,
                        "checks": [],
                    }
                ],
            },
        )
        self._run(
            system,
            {
                "status": "OK",
                "checks": [{"name": "Battery SOC", "status": "OK", "required": True}],
            },
        )
        assert len(system.get_health_recoveries()) == 1

        count = system.acknowledge_health_recoveries()

        assert count == 1
        assert system.get_health_recoveries() == []


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


def _make_minimal_optimization_result(count: int) -> OptimizationResult:
    """Build a minimal OptimizationResult with *count* PeriodData entries."""
    energy = EnergyData(
        solar_production=0.0,
        home_consumption=0.5,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=0.5,
        grid_exported=0.0,
        battery_soe_start=5.0,
        battery_soe_end=5.0,
    )
    return OptimizationResult(
        input_data={},
        period_data=[
            PeriodData(period=i, energy=energy, timestamp=None) for i in range(count)
        ],
    )


class TestAddTimestampsToPeriodData:
    """_add_timestamps_to_period_data must stamp next-day schedules with tomorrow's date.

    Regression for issue #155: the prepare_next_day path set optimization_period=0
    and called period_index_to_timestamp(0..95), which resolves to today's date.
    The fix offsets by today's period count so the timestamps land on tomorrow.
    """

    @patch("core.bess.time_utils.datetime")
    def test_next_day_timestamps_carry_tomorrows_date(self, mock_datetime, system):
        """When next_day=True, every period timestamp must have tomorrow's date."""
        fixed_now = datetime(2025, 11, 15, 23, 55, tzinfo=TIMEZONE)
        mock_datetime.now.return_value = fixed_now
        mock_datetime.combine = datetime.combine

        result = _make_minimal_optimization_result(4)
        system._add_timestamps_to_period_data(
            result, optimization_period=0, next_day=True
        )

        expected_date = fixed_now.date() + timedelta(days=1)
        for pd in result.period_data:
            assert pd.timestamp is not None
            assert (
                pd.timestamp.date() == expected_date
            ), f"Period {pd.period}: got {pd.timestamp.date()}, want {expected_date}"

    @patch("core.bess.time_utils.datetime")
    def test_today_timestamps_carry_todays_date(self, mock_datetime, system):
        """When next_day=False, every period timestamp must have today's date."""
        fixed_now = datetime(2025, 11, 15, 12, 0, tzinfo=TIMEZONE)
        mock_datetime.now.return_value = fixed_now
        mock_datetime.combine = datetime.combine

        result = _make_minimal_optimization_result(4)
        system._add_timestamps_to_period_data(
            result, optimization_period=0, next_day=False
        )

        expected_date = fixed_now.date()
        for pd in result.period_data:
            assert pd.timestamp is not None
            assert pd.timestamp.date() == expected_date
