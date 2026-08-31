"""Fast unit tests for BatterySystemManager settings, lifecycle, and getters.

These tests exercise orchestration methods that do NOT require the DP optimizer,
using MockHomeAssistantController from conftest.
"""

import logging
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.exceptions import (
    HistoricalDataUnavailableError,
    SystemConfigurationError,
)
from core.bess.models import (
    EconomicSummary,
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

    def test_max_discharge_power_synced_to_inverter_controller(self, system):
        """Issue #398: discharge_rate% used the InverterController's stale
        max_discharge_power_kw snapshot from construction time, so a user
        lowering the power setting kept getting rates computed against the
        old (higher) value."""
        system.update_settings({"battery": {"max_discharge_power_kw": 10.0}})
        assert system._inverter_controller.max_discharge_power_kw == 10.0

    def test_max_charge_power_synced_to_inverter_controller(self, system):
        system.update_settings({"battery": {"max_charge_power_kw": 10.0}})
        assert system._inverter_controller.max_charge_power_kw == 10.0

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

    def test_away_from_growatt_vpp_disables_vpp_status(self, system, mock_controller):
        """Issue #479 (2nd entry point): switching the inverter platform
        entirely -- not just control_mode -- also discards the Growatt
        controller and must disable a stuck VPP register the same way
        switch_control_mode() does, or the hardware override survives the
        platform change too."""
        system.switch_inverter_platform("solax_modbus_growatt_min")
        system.switch_control_mode("vpp")
        mock_controller.set_growatt_vpp_status(True)

        system.switch_inverter_platform("huawei_solar_luna2000")

        assert mock_controller.get_growatt_vpp_status() == "Disabled"

    def test_away_from_growatt_tou_never_touches_vpp_status(
        self, system, mock_controller
    ):
        system.switch_inverter_platform("solax_modbus_growatt_min")
        assert mock_controller.calls["growatt_vpp_status"] == []
        system.switch_inverter_platform("huawei_solar_luna2000")
        assert mock_controller.calls["growatt_vpp_status"] == []


class TestSwitchControlMode:
    def test_gen4_defaults_to_tou(self, system):
        system.switch_inverter_platform("solax_modbus_growatt_min")
        assert system.control_mode == "tou"

    def test_gen4_can_switch_to_vpp(self, system):
        system.switch_inverter_platform("solax_modbus_growatt_min")
        system.switch_control_mode("vpp")
        assert system.control_mode == "vpp"
        assert system._inverter_controller.control_mode == "vpp"

    def test_gen3_always_vpp(self, system):
        system.switch_inverter_platform("solax_modbus_growatt_sph")
        assert system.control_mode == "vpp"

    def test_gen3_rejects_tou(self, system):
        system.switch_inverter_platform("solax_modbus_growatt_sph")
        with pytest.raises(SystemConfigurationError):
            system.switch_control_mode("tou")

    def test_invalid_control_mode_raises(self, system):
        system.switch_inverter_platform("solax_modbus_growatt_min")
        with pytest.raises(SystemConfigurationError):
            system.switch_control_mode("bogus")

    def test_not_applicable_to_other_platforms(self, system):
        system.switch_inverter_platform("solax_modbus_native")
        with pytest.raises(SystemConfigurationError):
            system.switch_control_mode("vpp")

    def test_same_control_mode_is_noop(self, system):
        system.switch_inverter_platform("solax_modbus_growatt_min")
        original_controller = system._inverter_controller
        system.switch_control_mode("tou")
        assert system._inverter_controller is original_controller

    def test_vpp_to_tou_disables_vpp_status(self, system, mock_controller):
        """Issue #479: switching vpp -> tou left VPP Status enabled on the
        inverter, so VPP Remote Control kept overriding TOU segment writes."""
        system.switch_inverter_platform("solax_modbus_growatt_min")
        system.switch_control_mode("vpp")
        mock_controller.set_growatt_vpp_status(True)

        system.switch_control_mode("tou")

        assert mock_controller.get_growatt_vpp_status() == "Disabled"
        assert mock_controller.calls["growatt_vpp_status"][-1] is False

    def test_vpp_to_tou_skips_write_when_already_disabled(
        self, system, mock_controller
    ):
        system.switch_inverter_platform("solax_modbus_growatt_min")
        system.switch_control_mode("vpp")
        assert mock_controller.get_growatt_vpp_status() == "Disabled"
        mock_controller.calls["growatt_vpp_status"].clear()

        system.switch_control_mode("tou")

        assert mock_controller.calls["growatt_vpp_status"] == []

    def test_tou_to_tou_never_touches_vpp_status(self, system, mock_controller):
        system.switch_inverter_platform("solax_modbus_growatt_min")
        system.switch_control_mode("tou")
        assert mock_controller.calls["growatt_vpp_status"] == []

    def test_toggling_through_vpp_recovers_a_pre_fix_stuck_install(
        self, system, mock_controller
    ):
        """A user stuck from before leave_control_mode() existed (hardware
        VPP Status left Enabled, but BESS's stored control_mode already
        "tou" since the buggy switch already happened) can recover by
        selecting VPP then TOU again in Settings -- leave_control_mode()
        reads live hardware state (get_growatt_vpp_status()), not any
        BESS-side cache, so this works even though nothing here has ever
        seen this particular register as "confirmed enabled"."""
        system.switch_inverter_platform("solax_modbus_growatt_min")
        assert system.control_mode == "tou"
        mock_controller.set_growatt_vpp_status(True)  # stuck from before the fix

        system.switch_control_mode("vpp")
        system.switch_control_mode("tou")

        assert mock_controller.get_growatt_vpp_status() == "Disabled"


class TestResolveInitialPlatform:
    def test_new_format_platform_key(self):
        result = BatterySystemManager._resolve_initial_platform(
            {"inverter": {"platform": "growatt_server_sph"}}
        )
        assert result == "growatt_server_sph"

    def test_fresh_install_returns_none(self):
        result = BatterySystemManager._resolve_initial_platform({})
        assert result is None

    def test_legacy_growatt_key_is_ignored(self):
        """growatt.inverter_type is no longer read here — SettingsStore's
        migration rewrites it to inverter.platform before startup."""
        result = BatterySystemManager._resolve_initial_platform(
            {"growatt": {"inverter_type": "MIN"}}
        )
        assert result is None

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

    def test_period_zero_actual_rollover_clears_historical_store(self, system):
        """The true midnight boundary (00:00 quarterly job) is the only place
        that should clear today's actuals - see issue #380 follow-up."""
        with patch.object(system.historical_store, "clear") as mock_clear:
            system._handle_special_cases(
                period=0, prepare_next_day=False, is_first_run=True
            )
            mock_clear.assert_called_once()

    def test_prepare_next_day_does_not_clear_historical_store(self, system):
        """prepare_next_day fires at 23:55, 5 minutes before midnight, while
        today's dashboard still needs today's actuals. Clearing here wiped
        today's real sensor data early and produced false "missing hours"
        and a broken chart (issue #380 follow-up)."""
        with (
            patch.object(system, "_fetch_predictions"),
            patch.object(system.historical_store, "clear") as mock_clear,
        ):
            system._handle_special_cases(
                period=95, prepare_next_day=True, is_first_run=False
            )
            mock_clear.assert_not_called()

    def test_prepare_next_day_clears_stores_and_refetches(self, system):
        system._consumption_predictions = [1.0] * 96
        with (
            patch.object(system, "get_current_daily_view"),
            patch.object(system.daily_view_store, "save_day"),
            patch.object(system, "_fetch_predictions") as mock_fetch,
        ):
            system._handle_special_cases(
                period=0, prepare_next_day=True, is_first_run=False
            )
            mock_fetch.assert_called_once()

    def test_prepare_next_day_does_not_save_daily_view_itself(self, system, tmp_path):
        """Saving today's file is now _persist_today_view()'s job (called every
        tick from _update_energy_data), not _handle_special_cases's. Regression
        guard against reintroducing a second, now-redundant write path."""
        from core.bess.daily_view_store import DailyViewStore

        system.daily_view_store = DailyViewStore(persist_dir=tmp_path)

        with (
            patch.object(system, "get_current_daily_view") as mock_get_view,
            patch.object(system.daily_view_store, "save_day") as mock_save,
            patch.object(system, "_fetch_predictions"),
        ):
            system._handle_special_cases(
                period=95, prepare_next_day=True, is_first_run=False
            )

        mock_get_view.assert_not_called()
        mock_save.assert_not_called()


class TestPersistTodayView:
    def test_no_op_when_no_schedule_exists_yet(self, system):
        with patch.object(system, "get_current_daily_view") as mock_get_view:
            system._persist_today_view()
        mock_get_view.assert_not_called()

    def test_saves_current_view_when_schedule_exists(self, system, tmp_path):
        from datetime import date as date_cls

        from core.bess.daily_view_builder import DailyView
        from core.bess.daily_view_store import DailyViewStore

        system.daily_view_store = DailyViewStore(persist_dir=tmp_path)
        fake_view = DailyView(
            date=date_cls(2026, 7, 27),
            periods=[],
            total_savings=4.0,
            actual_count=0,
            predicted_count=0,
        )

        with (
            patch.object(
                system.schedule_store, "get_latest_schedule", return_value=MagicMock()
            ),
            patch.object(system, "get_current_daily_view", return_value=fake_view),
        ):
            system._persist_today_view()

        saved = system.daily_view_store.load_day(date_cls(2026, 7, 27))
        assert saved is not None
        assert saved.total_savings == 4.0


class TestUpdateEnergyDataCallsPersist:
    def test_update_energy_data_calls_persist_today_view(self, system):
        with patch.object(system, "_persist_today_view") as mock_persist:
            system._update_energy_data(
                period=1, is_first_run=True, prepare_next_day=False
            )
        mock_persist.assert_called_once()


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

    def test_record_scheduler_misfire(self, system):
        system.record_scheduler_misfire(
            job_id="update_schedule_quarterly",
            scheduled_run_time=datetime(2026, 7, 27, 0, 30),
        )
        failures = system.get_runtime_failures()
        assert len(failures) == 1
        assert failures[0].category == "scheduler_misfire"
        assert "update_schedule_quarterly" in failures[0].operation
        assert "00:30" in failures[0].operation


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

    def test_degraded_message_does_not_blame_sensor_configuration(self, system, caplog):
        """Issue #583: a required component can fail because an upstream source
        is temporarily unavailable, not because anything is misconfigured. The
        degraded-mode banner must not tell the user to fix a configuration that
        is correct — it pointed a user at the Nordpool settings for a 77-second
        HA outage that healed itself.
        """
        failing_result = {
            "status": "ERROR",
            "checks": [
                {
                    "name": "Electricity Price Data",
                    "status": "ERROR",
                    "required": True,
                    "checks": [
                        {
                            "name": "Nordpool Service Call",
                            "status": "ERROR",
                            "error": "Nordpool price data is temporarily unavailable, "
                            "will retry on the next fetch",
                        }
                    ],
                }
            ],
        }
        with patch(
            "core.bess.battery_system_manager.run_system_health_checks",
            return_value=failing_result,
        ):
            with caplog.at_level(
                logging.INFO, logger="core.bess.battery_system_manager"
            ):
                system.refresh_health_check()

        logged = "\n".join(r.getMessage() for r in caplog.records)
        assert "fix sensor configuration" not in logged.lower()
        assert "Electricity Price Data" in logged

    def test_retries_schedule_build_when_no_schedule_and_sensors_healthy(self, system):
        """A health check that finds no critical failures but no schedule was
        ever built (e.g. the initial startup schedule build failed while
        sensors were unavailable) should trigger a retry. Otherwise the
        dashboard is stuck showing "initializing" until the next quarterly
        cron tick or a manual restart, even though the banner reports the
        system is healthy. See debug log 2026-07-25-220017.
        """
        assert system._current_schedule is None
        healthy_result = {
            "status": "OK",
            "checks": [{"name": "Battery SOC", "status": "OK", "required": True}],
        }
        with (
            patch(
                "core.bess.battery_system_manager.run_system_health_checks",
                return_value=healthy_result,
            ),
            patch.object(
                system, "update_battery_schedule", return_value=True
            ) as mock_update,
        ):
            system.refresh_health_check()

        mock_update.assert_called_once()

    def test_does_not_retry_schedule_build_when_schedule_already_exists(self, system):
        system._current_schedule = MagicMock()
        healthy_result = {
            "status": "OK",
            "checks": [{"name": "Battery SOC", "status": "OK", "required": True}],
        }
        with (
            patch(
                "core.bess.battery_system_manager.run_system_health_checks",
                return_value=healthy_result,
            ),
            patch.object(system, "update_battery_schedule") as mock_update,
        ):
            system.refresh_health_check()

        mock_update.assert_not_called()

    def test_internal_run_health_check_does_not_build_schedule(self, system):
        """Issue #399: ``start()`` calls the private ``_run_health_check``
        before ``_initialize_tou_schedule_from_inverter`` has read the
        inverter's current VPP/remote-control state. If ``_run_health_check``
        itself retries the schedule build (as it did when #394 added the
        retry directly to the private method), the very first
        ``update_battery_schedule`` of the process fires before the
        controller's write-skip guards are seeded from hardware, so Growatt
        VPP registers get written unconditionally on every restart even when
        the hardware is already in the desired state.

        The retry belongs only in the public ``refresh_health_check``
        wrapper, which is exclusively used by the periodic post-startup
        cron/manual-recheck path (see debug log 2026-07-27-075654 on #399,
        showing VPP writes at 07:40:19-21 before the hardware-read log at
        07:40:24). The private method must never trigger a schedule build.
        """
        assert system._current_schedule is None
        healthy_result = {
            "status": "OK",
            "checks": [{"name": "Battery SOC", "status": "OK", "required": True}],
        }
        with (
            patch(
                "core.bess.battery_system_manager.run_system_health_checks",
                return_value=healthy_result,
            ),
            patch.object(system, "update_battery_schedule") as mock_update,
        ):
            system._run_health_check()

        mock_update.assert_not_called()


class TestHealthRecoveryTracking:
    """A component that goes ERROR/WARNING -> OK between health checks should
    be recorded as a recovery, surviving even if nobody was watching the live
    banner when it happened. See #215.
    """

    def _run(self, system, result, device_maps=({}, {})):
        with (
            patch(
                "core.bess.battery_system_manager.run_system_health_checks",
                return_value=result,
            ),
            patch.object(
                system._controller, "get_device_maps", return_value=device_maps
            ),
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
        # Recoveries are per-device now; without a resolvable device the
        # component name is the group key, and detail names the recovered
        # component rather than its individual sensors.
        assert recoveries[0].detail == "Battery Control"

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

    def test_recovery_grouped_one_per_device(
        self, system: BatterySystemManager
    ) -> None:
        """Two components on the same device recovering together yield ONE
        recovery line naming both — the banner is per device, not per
        component."""
        device_maps = (
            {
                "sensor.device_a_sensor": "device-a",
                "sensor.device_b_sensor": "device-a",
            },
            {"device-a": "Power Inverter"},
        )
        outage = {
            "status": "ERROR",
            "checks": [
                {
                    "name": "Battery Control",
                    "status": "ERROR",
                    "required": True,
                    "checks": [
                        {
                            "name": "Power Setpoint",
                            "entity_id": "sensor.device_a_sensor",
                            "status": "ERROR",
                        }
                    ],
                },
                {
                    "name": "Battery Monitoring",
                    "status": "ERROR",
                    "required": True,
                    "checks": [
                        {
                            "name": "Battery SOC",
                            "entity_id": "sensor.device_b_sensor",
                            "status": "ERROR",
                        }
                    ],
                },
            ],
        }
        recovered = {
            "status": "OK",
            "checks": [
                {"name": "Battery Control", "status": "OK", "required": True},
                {"name": "Battery Monitoring", "status": "OK", "required": True},
            ],
        }
        self._run(system, outage, device_maps)
        self._run(system, recovered, device_maps)

        recoveries = system.get_health_recoveries()
        assert len(recoveries) == 1
        assert recoveries[0].component == "Power Inverter"
        assert recoveries[0].previous_status == "ERROR"
        assert recoveries[0].detail == "Battery Control, Battery Monitoring"

    def test_recovery_grouped_by_component_when_registry_unavailable(
        self, system: BatterySystemManager
    ) -> None:
        """A registry query failure must not drop the recovery — grouping
        degrades to component names, one recovery per recovered component."""
        outage = {
            "status": "ERROR",
            "checks": [
                {
                    "name": "Battery Control",
                    "status": "ERROR",
                    "required": True,
                    "checks": [],
                }
            ],
        }
        recovered = {
            "status": "OK",
            "checks": [{"name": "Battery Control", "status": "OK", "required": True}],
        }
        for result in (outage, recovered):
            with (
                patch(
                    "core.bess.battery_system_manager.run_system_health_checks",
                    return_value=result,
                ),
                patch.object(
                    system._controller,
                    "get_device_maps",
                    side_effect=SystemConfigurationError("registry down"),
                ),
            ):
                system.refresh_health_check()

        recoveries = system.get_health_recoveries()
        assert len(recoveries) == 1
        assert recoveries[0].component == "Battery Control"
        assert recoveries[0].previous_status == "ERROR"

    def test_recovery_cleared_when_any_component_still_failing(
        self, system: BatterySystemManager
    ) -> None:
        """If only part of a device's components recovered, the device is
        still failing — no recovery is recorded, and any stale one is
        cleared."""
        device_maps = (
            {
                "sensor.device_a_sensor": "device-a",
                "sensor.device_b_sensor": "device-a",
            },
            {"device-a": "Power Inverter"},
        )
        outage = {
            "status": "ERROR",
            "checks": [
                {
                    "name": "Battery Control",
                    "status": "ERROR",
                    "required": True,
                    "checks": [
                        {
                            "name": "Power Setpoint",
                            "entity_id": "sensor.device_a_sensor",
                            "status": "ERROR",
                        }
                    ],
                },
                {
                    "name": "Battery Monitoring",
                    "status": "ERROR",
                    "required": True,
                    "checks": [
                        {
                            "name": "Battery SOC",
                            "entity_id": "sensor.device_b_sensor",
                            "status": "ERROR",
                        }
                    ],
                },
            ],
        }
        still_failing = {
            "status": "ERROR",
            "checks": [
                {"name": "Battery Control", "status": "OK", "required": True},
                {
                    "name": "Battery Monitoring",
                    "status": "ERROR",
                    "required": True,
                    "checks": [
                        {
                            "name": "Battery SOC",
                            "entity_id": "sensor.device_b_sensor",
                            "status": "ERROR",
                        }
                    ],
                },
            ],
        }
        self._run(system, outage, device_maps)
        self._run(system, still_failing, device_maps)

        # The device never fully recovered: B is still down, so the (would-be)
        # A recovery must not be recorded and nothing stale lingers.
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


class TestConsumptionForecastFreshness:
    """Issue #395: the quarterly job (every 15 min) never refreshed the
    consumption forecast after startup/23:55 - _gather_optimization_data
    cached it forever (truthiness check, no expiry), so it could go stale
    for up to ~24h. Solar is unaffected: it's fetched live every call via
    controller.get_solar_forecast().

    The refresh policy is strategy-aware, not a blanket timer: 'sensor' and
    'fixed' read a cheap, continuously-updating source, so they refetch
    every quarterly cycle (matching solar). 'load_power_7d_avg' and
    'ha_statistics' average a window of full calendar days ending at
    today's midnight, so their value is provably unchanged intraday - they
    only need to refetch once the date rolls over.
    """

    def test_sensor_strategy_refetches_every_call(self, system):
        system.home_settings.consumption_strategy = "sensor"
        # Pre-populate the cache as if a fetch just happened - it must not
        # be reused, since 'sensor' has no intraday cache.
        system._consumption_predictions = [1.0] * 96
        system._consumption_predictions_date = date(2026, 7, 27)

        with (
            patch.object(
                system, "_get_consumption_forecast", return_value=[2.0] * 96
            ) as mock_fetch,
            patch("core.bess.time_utils.datetime") as mock_datetime,
        ):
            mock_datetime.now.return_value = datetime(
                2026, 7, 27, 8, 0, tzinfo=TIMEZONE
            )
            _, data = system._gather_optimization_data(
                period=32, current_soc=50.0, prepare_next_day=False, period_count=96
            )
            assert data["full_consumption"][40] == 2.0
            assert mock_fetch.call_count == 1

            # Next quarterly tick, same day: still refetches.
            _, data = system._gather_optimization_data(
                period=33, current_soc=50.0, prepare_next_day=False, period_count=96
            )
            assert mock_fetch.call_count == 2

    def test_load_power_7d_avg_strategy_caches_until_date_rollover(self, system):
        system.home_settings.consumption_strategy = "load_power_7d_avg"
        system._consumption_predictions = [1.0] * 96
        system._consumption_predictions_date = date(2026, 7, 27)

        with (
            patch.object(
                system, "_get_consumption_forecast", return_value=[2.0] * 96
            ) as mock_fetch,
            patch("core.bess.time_utils.datetime") as mock_datetime,
        ):
            # Same day, later quarterly tick: the 7-day window can't have
            # changed, so the cache must be reused.
            mock_datetime.now.return_value = datetime(
                2026, 7, 27, 20, 0, tzinfo=TIMEZONE
            )
            _, data = system._gather_optimization_data(
                period=80, current_soc=50.0, prepare_next_day=False, period_count=96
            )
            assert data["full_consumption"][85] == 1.0
            assert mock_fetch.call_count == 0

            # Past midnight: the 7-day window has shifted, must refetch.
            mock_datetime.now.return_value = datetime(
                2026, 7, 28, 0, 0, tzinfo=TIMEZONE
            )
            _, data = system._gather_optimization_data(
                period=0, current_soc=50.0, prepare_next_day=False, period_count=96
            )
            assert data["full_consumption"][5] == 2.0
            assert mock_fetch.call_count == 1


class TestLoadPower7dAvgStrategy:
    """PR 3 of #722: the 7-day load-power average strategy is renamed
    ``influxdb_7d_avg`` -> ``load_power_7d_avg`` and sourced from HA Recorder."""

    def test_legacy_influxdb_7d_avg_config_value_is_canonicalized(self) -> None:
        from core.bess.settings import HomeSettings

        settings = HomeSettings().from_ha_config(
            {
                "home": {
                    "consumption_strategy": "influxdb_7d_avg",
                    "power_monitoring_enabled": False,
                }
            }
        )
        assert settings.consumption_strategy == "load_power_7d_avg"

    def test_new_name_and_unrelated_values_pass_through(self) -> None:
        from core.bess.settings import HomeSettings

        for value in ("load_power_7d_avg", "fixed", "sensor", "ha_statistics"):
            settings = HomeSettings().from_ha_config(
                {
                    "home": {
                        "consumption_strategy": value,
                        "power_monitoring_enabled": False,
                    }
                }
            )
            assert settings.consumption_strategy == value

    def test_forecast_reads_recorder_and_threads_the_controller(
        self, system: BatterySystemManager
    ) -> None:
        import core.bess.battery_system_manager as bsm

        # The InfluxDB gate is gone from this module entirely.
        assert "is_influxdb_configured" not in vars(bsm)

        assert system._controller is not None
        system._controller.sensors = {"local_load_power": "sensor.house_load"}
        recorder_result = {
            "status": "success",
            "data": {p: {"sensor.house_load": 0.2} for p in range(96)},
        }
        with patch(
            "core.bess.battery_system_manager.get_power_sensor_data_batch",
            return_value=recorder_result,
        ) as mock_batch:
            forecast = system._get_load_power_7d_avg_forecast()

        assert len(forecast) == 96
        assert all(v == pytest.approx(0.2) for v in forecast)
        # controller threaded as the first positional arg
        assert mock_batch.call_args.args[0] is system._controller


class TestNotApplyBranchRefreshesCurrentSchedule:
    """Regression for issue #369 finding 1.

    _apply_period_schedule (called every cycle, apply or not) reads
    self._inverter_controller.current_schedule.actions to compute the
    hardware battery_action_kw for the current period. Before the
    InverterController-recreation refactor, the not-apply branch swapped in
    a whole new controller object whose current_schedule had already been
    set by create_schedule(); that refresh was lost when the branch was
    rewritten to update fields individually. If current_schedule isn't
    explicitly refreshed on the not-apply path, every not-apply cycle writes
    hardware commands computed from a stale, previously-applied schedule's
    action values instead of the freshly computed ones.
    """

    def test_current_schedule_refreshed_when_schedule_not_applied(self, system):
        first_schedule = MagicMock(actions=[1.0, 2.0], strategic_intents=["IDLE"])
        second_schedule = MagicMock(actions=[5.0, 6.0], strategic_intents=["IDLE"])

        with (
            patch.object(system, "_handle_special_cases"),
            patch.object(
                system, "_get_price_data", return_value=([1.0], [MagicMock()])
            ),
            patch.object(system, "_update_energy_data"),
            patch.object(system, "_get_current_battery_soc", return_value=50.0),
            patch.object(
                system, "_gather_optimization_data", return_value=(0, MagicMock())
            ),
            patch.object(system, "_run_optimization", return_value=MagicMock()),
            # The apply path now prints the DP results table from the caller;
            # the optimization result is a MagicMock here, so intercept it.
            patch("core.bess.battery_system_manager.print_optimization_results"),
            patch.object(
                system,
                "_create_updated_schedule",
                side_effect=[first_schedule, second_schedule],
            ),
            patch.object(
                system,
                "_should_apply_schedule",
                side_effect=[(True, "first: applied"), (False, "second: no change")],
            ),
            patch.object(system, "_apply_schedule") as mock_apply_schedule,
            patch.object(system, "_apply_period_schedule"),
            patch.object(system, "_capture_prediction_snapshot"),
            patch.object(system, "log_battery_schedule"),
        ):
            # First cycle: should_apply=True. _apply_schedule is mocked out
            # (its internals are not under test here), so emulate the one
            # side effect this test cares about: it sets current_schedule.
            def fake_apply_schedule(*_args, **_kwargs):
                system._inverter_controller.current_schedule = first_schedule

            mock_apply_schedule.side_effect = fake_apply_schedule

            assert system.update_battery_schedule(0, prepare_next_day=False) is True
            assert system._inverter_controller.current_schedule is first_schedule

            # Second cycle: should_apply=False (TOU/VPP intents unchanged),
            # but the DP produced different action magnitudes. The not-apply
            # branch must still refresh current_schedule so the next
            # _apply_period_schedule call reads the fresh actions.
            assert system.update_battery_schedule(1, prepare_next_day=False) is True

        assert system._inverter_controller.current_schedule is second_schedule
        assert system._inverter_controller.current_schedule.actions == [5.0, 6.0]

    def test_apply_cycle_logs_schedule_and_results(
        self, system: BatterySystemManager
    ) -> None:
        """An apply cycle logs both the DP results table and the schedule tables."""
        schedule = MagicMock(actions=[1.0], strategic_intents=["IDLE"])
        optimization_result = MagicMock()

        with (
            patch.object(system, "_handle_special_cases"),
            patch.object(
                system, "_get_price_data", return_value=([1.0], [MagicMock()])
            ),
            patch.object(system, "_update_energy_data"),
            patch.object(system, "_get_current_battery_soc", return_value=50.0),
            patch.object(
                system, "_gather_optimization_data", return_value=(0, MagicMock())
            ),
            patch.object(system, "_run_optimization", return_value=optimization_result),
            patch.object(system, "_create_updated_schedule", return_value=schedule),
            patch.object(
                system, "_should_apply_schedule", return_value=(True, "changed")
            ),
            patch.object(system, "_apply_schedule"),
            patch.object(system, "_apply_period_schedule"),
            patch.object(system, "_capture_prediction_snapshot"),
            patch.object(system, "log_battery_schedule") as mock_log,
            patch(
                "core.bess.battery_system_manager.print_optimization_results"
            ) as mock_print,
        ):
            assert system.update_battery_schedule(0, prepare_next_day=False) is True

        mock_log.assert_called_once_with(0)
        mock_print.assert_called_once()
        # print_optimization_results receives the optimization result plus the
        # buy/sell price lists derived from the mocked price entry.
        assert mock_print.call_args.args[0] is optimization_result
        assert len(mock_print.call_args.args[1]) == 1
        assert len(mock_print.call_args.args[2]) == 1

    def test_apply_cycle_logs_full_horizon_summary_not_rescoped(
        self, system: BatterySystemManager
    ) -> None:
        """An apply cycle must log the full-horizon Summary, not the today-only
        rescope _create_updated_schedule leaves on the result.

        _create_updated_schedule rescopes result.economic_summary in place
        (battery_system_manager.py, ``not prepare_next_day`` branch), but
        print_optimization_results prints the full extended-horizon table. The
        Summary block must come from the full-horizon summary captured before
        that mutation, or table and Summary silently disagree in the same log
        block.
        """
        schedule = MagicMock(actions=[1.0], strategic_intents=["IDLE"])

        full_horizon_summary = EconomicSummary(
            grid_only_cost=100.0,
            solar_only_cost=90.0,
            battery_solar_cost=80.0,
            grid_to_solar_savings=10.0,
            grid_to_battery_solar_savings=20.0,
            solar_to_battery_solar_savings=10.0,
            grid_to_battery_solar_savings_pct=20.0,
            total_charged=1.0,
            total_discharged=1.0,
        )
        today_rescoped_summary = EconomicSummary(
            grid_only_cost=50.0,
            solar_only_cost=45.0,
            battery_solar_cost=40.0,
            grid_to_solar_savings=5.0,
            grid_to_battery_solar_savings=10.0,
            solar_to_battery_solar_savings=5.0,
            grid_to_battery_solar_savings_pct=20.0,
            total_charged=0.5,
            total_discharged=0.5,
        )

        optimization_result = MagicMock()
        optimization_result.economic_summary = full_horizon_summary

        def _create_updated_schedule_side_effect(
            *_args: object, **_kwargs: object
        ) -> MagicMock:
            # Emulate the real _create_updated_schedule: rescope the result's
            # economic_summary to today-only in place, then return the schedule.
            optimization_result.economic_summary = today_rescoped_summary
            return schedule

        with (
            patch.object(system, "_handle_special_cases"),
            patch.object(
                system, "_get_price_data", return_value=([1.0], [MagicMock()])
            ),
            patch.object(system, "_update_energy_data"),
            patch.object(system, "_get_current_battery_soc", return_value=50.0),
            patch.object(
                system, "_gather_optimization_data", return_value=(0, MagicMock())
            ),
            patch.object(system, "_run_optimization", return_value=optimization_result),
            patch.object(
                system,
                "_create_updated_schedule",
                side_effect=_create_updated_schedule_side_effect,
            ),
            patch.object(
                system, "_should_apply_schedule", return_value=(True, "changed")
            ),
            patch.object(system, "_apply_schedule"),
            patch.object(system, "_apply_period_schedule"),
            patch.object(system, "_capture_prediction_snapshot"),
            patch.object(system, "log_battery_schedule") as mock_log,
            patch(
                "core.bess.battery_system_manager.print_optimization_results"
            ) as mock_print,
        ):
            assert system.update_battery_schedule(0, prepare_next_day=False) is True

        mock_log.assert_called_once_with(0)
        mock_print.assert_called_once()
        # The Summary block must come from the full-horizon summary captured
        # before _create_updated_schedule rescoped it — never the today-only
        # value left on the result.
        assert mock_print.call_args.kwargs["economic_summary"] is full_horizon_summary

    def test_keep_cycle_logs_neither(self, system: BatterySystemManager) -> None:
        """A quiet keep cycle must not re-dump the schedule or results tables."""
        schedule = MagicMock(actions=[1.0], strategic_intents=["IDLE"])

        with (
            patch.object(system, "_handle_special_cases"),
            patch.object(
                system, "_get_price_data", return_value=([1.0], [MagicMock()])
            ),
            patch.object(system, "_update_energy_data"),
            patch.object(system, "_get_current_battery_soc", return_value=50.0),
            patch.object(
                system, "_gather_optimization_data", return_value=(0, MagicMock())
            ),
            patch.object(system, "_run_optimization", return_value=MagicMock()),
            patch.object(system, "_create_updated_schedule", return_value=schedule),
            patch.object(
                system, "_should_apply_schedule", return_value=(False, "no change")
            ),
            patch.object(system, "_apply_period_schedule"),
            patch.object(system, "_capture_prediction_snapshot"),
            patch.object(system, "log_battery_schedule") as mock_log,
            patch(
                "core.bess.battery_system_manager.print_optimization_results"
            ) as mock_print,
        ):
            assert system.update_battery_schedule(0, prepare_next_day=False) is True

        mock_log.assert_not_called()
        mock_print.assert_not_called()


class TestLoadTodayFromDisk:
    def test_seeds_only_actual_periods_within_range(self, system, tmp_path):
        from datetime import date as date_cls
        from datetime import datetime

        from core.bess.daily_view_builder import DailyView
        from core.bess.daily_view_store import DailyViewStore
        from core.bess.models import DecisionData, EnergyData, PeriodData

        system.daily_view_store = DailyViewStore(persist_dir=tmp_path)

        def _period(index, data_source):
            return PeriodData(
                period=index,
                energy=EnergyData(
                    solar_production=0.0,
                    home_consumption=0.5,
                    battery_charged=0.0,
                    battery_discharged=0.0,
                    grid_imported=0.5,
                    grid_exported=0.0,
                    battery_soe_start=10.0,
                    battery_soe_end=10.0,
                ),
                timestamp=datetime(2026, 7, 27, index // 4, (index % 4) * 15),
                data_source=data_source,
                decision=DecisionData(),
            )

        view = DailyView(
            date=date_cls(2026, 7, 27),
            periods=[
                _period(0, "actual"),
                _period(1, "actual"),
                _period(2, "missing"),
                _period(3, "actual"),  # out of range: current_period will be 2
            ],
            total_savings=0.0,
            actual_count=2,
            predicted_count=0,
        )
        system.daily_view_store.save_day(view)

        with patch("core.bess.battery_system_manager.time_utils.now") as mock_now:
            mock_now.return_value = datetime(2026, 7, 27, 0, 30)
            system._load_today_from_disk(current_period=2)

        assert system.historical_store.get_period(0) is not None
        assert system.historical_store.get_period(1) is not None
        assert (
            system.historical_store.get_period(2) is None
        )  # was "missing", not seeded
        assert system.historical_store.get_period(3) is None  # out of range, not seeded

    def test_no_op_when_no_file_saved(self, system, tmp_path):
        from core.bess.daily_view_store import DailyViewStore

        system.daily_view_store = DailyViewStore(persist_dir=tmp_path)
        system._load_today_from_disk(current_period=4)
        assert system.historical_store.get_stored_count() == 0


class TestBackfillSkipsDiskSeededPeriods:
    def test_infludb_backfill_does_not_recollect_seeded_period(self, system, tmp_path):
        from datetime import date as date_cls
        from datetime import datetime

        from core.bess.daily_view_builder import DailyView
        from core.bess.daily_view_store import DailyViewStore
        from core.bess.models import DecisionData, EnergyData, PeriodData

        system.daily_view_store = DailyViewStore(persist_dir=tmp_path)
        seeded_period = PeriodData(
            period=0,
            energy=EnergyData(
                solar_production=0.0,
                home_consumption=0.5,
                battery_charged=0.0,
                battery_discharged=0.0,
                grid_imported=0.5,
                grid_exported=0.0,
                battery_soe_start=10.0,
                battery_soe_end=10.0,
            ),
            timestamp=datetime(2026, 7, 27, 0, 0),
            data_source="actual",
            decision=DecisionData(),
        )
        # Pre-seed disk with today's view (rather than calling
        # historical_store.record_period directly) so this test also proves
        # _load_today_from_disk (invoked by _fetch_and_initialize_historical_data
        # below) is what performs the seeding.
        view = DailyView(
            date=date_cls(2026, 7, 27),
            periods=[seeded_period],
            total_savings=0.0,
            actual_count=1,
            predicted_count=0,
        )
        system.daily_view_store.save_day(view)

        with (
            patch.object(
                system.sensor_collector, "collect_energy_data"
            ) as mock_collect,
            patch.object(
                system.price_manager,
                "get_available_prices",
                return_value=([1.0] * 96, [0.5] * 96),
            ),
            patch("core.bess.battery_system_manager.time_utils.now") as mock_now,
        ):
            mock_now.return_value = datetime(2026, 7, 27, 0, 30)
            system._fetch_and_initialize_historical_data()

        # Period 0 was already seeded (from disk, in this test's setup) —
        # the backfill loop must not re-collect it.
        collected_periods = [call.args[0] for call in mock_collect.call_args_list]
        assert 0 not in collected_periods
        assert 1 in collected_periods


class TestBackfillNotGatedOnInfluxDB:
    """PR 2 of #722: cold-start backfill now reads HA Recorder, so it must run
    even when the legacy ``influxdb`` add-on is not configured — previously
    ``_fetch_and_initialize_historical_data`` early-returned in that case."""

    def test_backfill_runs_and_never_consults_influxdb_config(
        self, system: BatterySystemManager
    ) -> None:
        import core.bess.battery_system_manager as bsm

        # The InfluxDB config gate is gone from this module entirely.
        assert "is_influxdb_configured" not in vars(bsm)

        with (
            patch.object(
                system.sensor_collector, "collect_energy_data"
            ) as mock_collect,
            patch.object(
                system.price_manager,
                "get_available_prices",
                return_value=([1.0] * 96, [0.5] * 96),
            ),
            patch("core.bess.battery_system_manager.time_utils.now") as mock_now,
        ):
            mock_now.return_value = datetime(2026, 7, 27, 1, 0)  # current_period = 4
            system._fetch_and_initialize_historical_data()

        collected_periods = [call.args[0] for call in mock_collect.call_args_list]
        assert collected_periods, "backfill must attempt periods via HA Recorder"
        assert 0 in collected_periods

    def test_cold_start_gap_logs_at_debug_not_warning(
        self,
        system: BatterySystemManager,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A fresh install part-way through the day has no recorder history for
        earlier periods — that gap is expected and must not spam WARNING once
        per period (the un-gated loop now reaches every period)."""
        with (
            patch.object(
                system.sensor_collector,
                "collect_energy_data",
                side_effect=HistoricalDataUnavailableError("no recorder history"),
            ),
            patch.object(
                system.price_manager,
                "get_available_prices",
                return_value=([1.0] * 96, [0.5] * 96),
            ),
            patch("core.bess.battery_system_manager.time_utils.now") as mock_now,
        ):
            mock_now.return_value = datetime(2026, 7, 27, 1, 0)  # current_period = 4
            with caplog.at_level(
                logging.DEBUG, logger="core.bess.battery_system_manager"
            ):
                system._fetch_and_initialize_historical_data()

        period_warnings = [
            r.message
            for r in caplog.records
            if r.levelno >= logging.WARNING and "period" in r.message.lower()
        ]
        assert not period_warnings, f"cold-start gap should not warn: {period_warnings}"
        assert any(
            "No recorder history yet for period" in r.message for r in caplog.records
        )


class TestQuietCycleReconcilesHardware:
    """A cycle that changes nothing must still re-assert the plan.

    Since #554 the write path is skipped when the plan is unchanged, so this
    is the only thing that looks at the inverter on a quiet cycle. Issue #551
    established that the segment table drifts on its own.
    """

    @pytest.fixture(autouse=True)
    def _pin_time_of_day(self, system: BatterySystemManager) -> Iterator[None]:
        """Pin the clock past period 10, keeping today's date.

        Both tests drive `update_battery_schedule(current_period=10)` while the
        rest of the system reads the real clock. Before 02:30 local, period 9 is
        still in the future, so data collection raises ("Period 9 is still in
        progress or in the future") and the cycle aborts before reaching
        reconcile_hardware — the assertion then fails for a reason that has
        nothing to do with reconciliation. The window is real: this fails every
        day between local midnight and 02:30, which is why it passed in CI on
        the way in (21:49 UTC = 23:49 local) and failed on the next PR
        (22:30 UTC = 00:30 local).

        The cache warm-up mirrors what BatterySystemManager.start() now does
        before the first optimization: since #709 the quarterly cycle reads
        prices cache-only and never fetches, so a cold cache would abort the
        cycle at "No price data available" before reconcile_hardware.
        """
        pinned = time_utils.now().replace(hour=15, minute=0, second=0, microsecond=0)
        with patch("core.bess.time_utils.now", return_value=pinned):
            system._price_manager.refresh_cache()
            yield

    def test_quiet_cycle_reconciles(self, system):
        system._current_schedule = MagicMock()
        with patch.object(
            system._inverter_controller, "reconcile_hardware", return_value=(0, 0)
        ) as reconcile:
            system.update_battery_schedule(current_period=10)
            system.update_battery_schedule(current_period=10)

        assert (
            reconcile.called
        ), "Nothing looked at the inverter on a cycle that changed nothing"

    def test_failed_reconciliation_is_retried_not_fatal(self, system):
        """The optimization needs no inverter — a failed re-assert must not
        end the cycle, and must not be forgotten either.

        Checked immediately after the failing cycle: leave it any longer and
        the next cycle has already retried and cleared the flag, which is the
        mechanism working rather than the failure being lost.
        """
        system.update_battery_schedule(current_period=10)  # first cycle applies

        with patch.object(
            system._inverter_controller,
            "reconcile_hardware",
            side_effect=Exception("Growatt device_id not configured"),
        ):
            system.update_battery_schedule(current_period=10)  # quiet cycle

        assert (
            system._hardware_write_pending is True
        ), "A failed re-assert was swallowed with nothing scheduled to retry it"


class TestOptimizerReadsPriceCacheOnly:
    """Issue #709: the quarterly optimizer must never fetch prices itself.

    _get_price_data used to call get_today_prices()/get_tomorrow_prices(),
    which fetch on a cache miss. Before tomorrow's prices publish (~13:00 CET)
    that ran a full synchronous retry loop every 15-minute cycle on the
    scheduler thread — the source of ridax67's late/skipped period switches
    when the HA Nordpool integration 500'd at the top of the hour. Fetching is
    now the dedicated refresh job's job; the optimizer reads cache-only.
    """

    @pytest.fixture(autouse=True)
    def _pin_afternoon(self) -> Iterator[None]:
        pinned = time_utils.now().replace(hour=15, minute=0, second=0, microsecond=0)
        with patch("core.bess.time_utils.now", return_value=pinned):
            yield

    def test_quarterly_cycle_does_not_fetch_when_tomorrow_is_uncached(
        self, system: BatterySystemManager
    ) -> None:
        # Today warm, tomorrow deliberately cold (pre-publication state).
        system._price_manager.get_price_data(time_utils.today())
        assert system._price_manager.get_cached_tomorrow_prices() == []
        system._current_schedule = MagicMock()  # type: ignore[assignment]

        with patch.object(
            system._price_manager.price_source, "get_prices_for_date"
        ) as fetch:
            system.update_battery_schedule(current_period=60)

        assert not fetch.called, "optimizer fetched prices instead of reading the cache"
