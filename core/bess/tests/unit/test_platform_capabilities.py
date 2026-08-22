"""Tests for platform capability declarations and their effect on BSM behavior.

Verifies that each InverterController subclass declares the correct
capabilities and that BatterySystemManager respects them (e.g. not
initializing the power monitor on platforms without charge rate control).
"""

from typing import Any

import pytest

from core.bess.growatt_min_controller import GrowattMinController
from core.bess.growatt_sph_controller import GrowattSphController
from core.bess.inverter_controller import InverterController
from core.bess.settings import BatterySettings
from core.bess.solax_controller import SolaxController
from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController
from core.bess.tests.conftest import MockHomeAssistantController, MockSensorCollector

# ── Capability declarations ──────────────────────────────────────────────────


class TestChargeRateControlCapability:
    """Verify supports_charge_rate_control is declared correctly per platform."""

    def test_base_class_defaults_to_true(self):
        assert InverterController.supports_charge_rate_control is True

    def test_growatt_min_supports_charge_rate(self):
        assert GrowattMinController.supports_charge_rate_control is True

    def test_growatt_sph_does_not_support_charge_rate(self):
        assert GrowattSphController.supports_charge_rate_control is False

    def test_solax_native_does_not_support_charge_rate(self):
        assert SolaxController.supports_charge_rate_control is False

    def test_solax_modbus_growatt_tou_mode_supports_charge_rate(self):
        # TOU mode uses the EMS charge/discharge-rate registers directly.
        controller = SolaxModbusGrowattController(
            BatterySettings(
                total_capacity=50.0,
                max_charge_power_kw=5.0,
                max_discharge_power_kw=5.0,
                min_soc=10.0,
                max_soc=95.0,
                cycle_cost_per_kwh=0.05,
            ),
            control_mode="tou",
        )
        assert controller.supports_charge_rate_control is True

    def test_solax_modbus_growatt_vpp_mode_does_not_support_charge_rate(self):
        # VPP mode drives power via vpp_power (RAM) — EMS registers unused.
        controller = SolaxModbusGrowattController(
            BatterySettings(
                total_capacity=50.0,
                max_charge_power_kw=5.0,
                max_discharge_power_kw=5.0,
                min_soc=10.0,
                max_soc=95.0,
                cycle_cost_per_kwh=0.05,
            ),
            control_mode="vpp",
        )
        assert controller.supports_charge_rate_control is False


class TestExportLimitControlCapability:
    """Verify supports_export_limit_control is declared correctly per platform (#269)."""

    def test_base_class_defaults_to_false(self):
        assert InverterController.supports_export_limit_control is False

    def test_growatt_sph_cloud_does_not_support_export_limit(self):
        # growatt_server exposes no export-limit service/entity — see #269.
        assert GrowattSphController.supports_export_limit_control is False

    def test_solax_native_does_not_support_export_limit(self):
        assert SolaxController.supports_export_limit_control is False

    def test_solax_modbus_growatt_supports_export_limit(self):
        # Registers 122/123 exist independent of control_mode (tou vs vpp).
        controller = SolaxModbusGrowattController(
            BatterySettings(
                total_capacity=50.0,
                max_charge_power_kw=5.0,
                max_discharge_power_kw=5.0,
                min_soc=10.0,
                max_soc=95.0,
                cycle_cost_per_kwh=0.05,
            ),
            control_mode="tou",
        )
        assert controller.supports_export_limit_control is True


class TestApplyExportLimit:
    """Verify apply_export_limit dispatches (or no-ops) correctly (#269)."""

    def test_base_class_is_a_noop(self):
        controller = GrowattSphController(
            BatterySettings(
                total_capacity=50.0,
                max_charge_power_kw=5.0,
                max_discharge_power_kw=5.0,
                min_soc=10.0,
                max_soc=95.0,
                cycle_cost_per_kwh=0.05,
            )
        )
        ha = MockHomeAssistantController()
        controller.apply_export_limit(ha, curtail=True)
        assert ha.calls["growatt_export_limit"] == []

    def test_solax_modbus_growatt_curtails(self):
        controller = SolaxModbusGrowattController(
            BatterySettings(
                total_capacity=50.0,
                max_charge_power_kw=5.0,
                max_discharge_power_kw=5.0,
                min_soc=10.0,
                max_soc=95.0,
                cycle_cost_per_kwh=0.05,
            ),
            control_mode="tou",
        )
        ha = MockHomeAssistantController()
        controller.apply_export_limit(ha, curtail=True)
        assert ha.calls["growatt_export_limit"] == [True]

        controller.apply_export_limit(ha, curtail=False)
        assert ha.calls["growatt_export_limit"] == [True, False]


class TestDischargeRateLoadFollowingCapability:
    """Verify discharge_rate_is_load_following is declared correctly per platform.

    True means discharge_rate acts as a ceiling under native load-following
    firmware (only draws what's needed to cover an actual deficit) — the
    assumption intra_period_discharge_gate's SOLAR_EXPORT/SOLAR_STORAGE
    override relies on (#187/#318). False means discharge_rate is executed
    as an immediate forced power command regardless of actual load (VPP-style
    control), where that override would force a full-power discharge instead
    of gently covering a dip (#324).
    """

    def test_base_class_defaults_to_true(self):
        assert InverterController.discharge_rate_is_load_following is True

    def test_growatt_min_is_load_following(self):
        assert GrowattMinController.discharge_rate_is_load_following is True

    def test_growatt_sph_is_not_load_following(self):
        # Currently inert (SPH's per-period write is a no-op and its batch
        # grouping excludes SOLAR_EXPORT/SOLAR_STORAGE) -- explicit False
        # guards against a future per-period write silently defaulting to
        # load-following semantics.
        assert GrowattSphController.discharge_rate_is_load_following is False

    def test_solax_native_is_not_load_following(self):
        assert SolaxController.discharge_rate_is_load_following is False

    def test_solax_modbus_growatt_tou_mode_is_load_following(self):
        controller = SolaxModbusGrowattController(
            BatterySettings(
                total_capacity=50.0,
                max_charge_power_kw=5.0,
                max_discharge_power_kw=5.0,
                min_soc=10.0,
                max_soc=95.0,
                cycle_cost_per_kwh=0.05,
            ),
            control_mode="tou",
        )
        assert controller.discharge_rate_is_load_following is True

    def test_solax_modbus_growatt_vpp_mode_is_not_load_following(self):
        controller = SolaxModbusGrowattController(
            BatterySettings(
                total_capacity=50.0,
                max_charge_power_kw=5.0,
                max_discharge_power_kw=5.0,
                min_soc=10.0,
                max_soc=95.0,
                cycle_cost_per_kwh=0.05,
            ),
            control_mode="vpp",
        )
        assert controller.discharge_rate_is_load_following is False


# ── BSM capability property ─────────────────────────────────────────────────


class TestBSMCapabilityProperty:
    """Verify BSM._supports_charge_rate_control reflects the active controller."""

    def test_sph_reports_no_charge_rate_control(self, platform_system):
        if platform_system.inverter_platform == "growatt_server_sph":
            assert platform_system._supports_charge_rate_control is False

    def test_solax_native_reports_no_charge_rate_control(self, platform_system):
        if platform_system.inverter_platform == "solax_modbus_native":
            assert platform_system._supports_charge_rate_control is False

    def test_min_platforms_report_charge_rate_control(self, platform_system):
        if platform_system.inverter_platform in (
            "growatt_server_min",
            "solax_modbus_growatt_min",
        ):
            assert platform_system._supports_charge_rate_control is True


# ── adjust_charging_power gating ─────────────────────────────────────────────


class TestAdjustChargingPowerSkipsUnsupported:
    """Verify adjust_charging_power is a no-op on unsupported platforms."""

    def test_sph_adjust_charging_power_is_noop(self, platform_system):
        """On platforms without charge rate control, adjust_charging_power
        must return without touching the controller."""
        if not platform_system._supports_charge_rate_control:
            # Should not raise — just silently return
            platform_system.adjust_charging_power()

    def test_vpp_mode_adjust_charging_power_is_noop(
        self, mock_controller, arbitrage_prices, monkeypatch
    ):
        """VPP-mode BSM must skip EMS writes without any BSM-level change."""
        from core.bess.battery_system_manager import BatterySystemManager
        from core.bess.price_manager import MockSource

        monkeypatch.setattr(
            "core.bess.sensor_collector.SensorCollector", MockSensorCollector
        )
        system = BatterySystemManager(
            controller=mock_controller,
            price_source=MockSource(arbitrage_prices),
            addon_options={
                "inverter": {
                    "platform": "solax_modbus_growatt_min",
                    "control_mode": "vpp",
                }
            },
        )
        assert system._supports_charge_rate_control is False
        system.adjust_charging_power()  # must not raise

    def test_unavailable_phase_sensor_does_not_crash_adjust_charging_power(
        self, mock_controller, arbitrage_prices, monkeypatch
    ):
        """A phase-current sensor that becomes unavailable after being
        validated (HA restart, integration reload, deleted entity) must not
        crash the 5-minute adjust_charging_power cron job with a raw
        TypeError from `None * voltage` — HomePowerMonitor now raises
        ValueError, which adjust_charging_power's except clause catches."""
        from core.bess.battery_system_manager import BatterySystemManager
        from core.bess.price_manager import MockSource

        monkeypatch.setattr(
            "core.bess.sensor_collector.SensorCollector", MockSensorCollector
        )
        system = BatterySystemManager(
            controller=mock_controller,
            price_source=MockSource(arbitrage_prices),
            addon_options={"inverter": {"platform": "growatt_server_min"}},
        )
        assert system._supports_charge_rate_control is True

        # Enable power monitoring after construction so the lazy-init path in
        # update_settings() instantiates the HomePowerMonitor.
        system.update_settings({"home": {"power_monitoring_enabled": True}})
        assert system._power_monitor is not None

        # get_period_settings requires strategic intents to have been
        # computed by a prior schedule run; set directly rather than
        # driving a full optimization cycle.
        system._inverter_controller.strategic_intents = ["IDLE"] * 96

        # Force the grid-charging path (calculate_available_charging_power),
        # then simulate an unavailable phase-current sensor.
        mock_controller.settings["grid_charge"] = True
        mock_controller.settings["l1_current"] = None

        system.adjust_charging_power()  # must not raise

    def test_transient_ha_failure_does_not_crash_adjust_charging_power(
        self,
        mock_controller: Any,
        arbitrage_prices: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A transient HA connectivity failure while reading grid-charge state
        must not escape the 5-minute adjust_charging_power cron job (issue
        #643: a Supervisor 502 on `Check grid charge state`).

        `grid_charge_enabled()` reads through `_api_request`, which re-raises
        `requests.RequestException` after its retries are exhausted, but
        `adjust_charging_power`'s except clause did not name that class -- so
        the exception escaped to APScheduler instead of being logged and the
        tick skipped.

        Asserted at the call level rather than against an execution model on
        purpose: the outcome under test *is* whether the scheduled tick
        survives the exception, and no charging-power write happens on this
        path at all once the read fails.
        """
        import requests

        from core.bess.battery_system_manager import BatterySystemManager
        from core.bess.price_manager import MockSource

        monkeypatch.setattr(
            "core.bess.sensor_collector.SensorCollector", MockSensorCollector
        )
        system = BatterySystemManager(
            controller=mock_controller,
            price_source=MockSource(arbitrage_prices),
            addon_options={"inverter": {"platform": "growatt_server_min"}},
        )
        assert system._supports_charge_rate_control is True

        system.update_settings({"home": {"power_monitoring_enabled": True}})
        assert system._power_monitor is not None

        system._inverter_controller.strategic_intents = ["IDLE"] * 96

        def _raise_502(*_args, **_kwargs):
            raise requests.RequestException(
                "502 Server Error: Bad Gateway for url: "
                "http://supervisor/core/api/states/select.allow_grid_charge"
            )

        monkeypatch.setattr(mock_controller, "grid_charge_enabled", _raise_502)

        system.adjust_charging_power()  # must not raise

    def test_unreadable_charge_rate_does_not_crash_adjust_charging_power(
        self,
        mock_controller: Any,
        arbitrage_prices: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The same transient HA failure hitting the *second* read must not
        crash the cron job either (issue #643).

        `adjust_battery_charging` makes two HA reads. `get_charging_power_rate`
        goes through `_get_raw_state`, which already degrades a
        `RequestException` to `None` -- and `None` then reached
        `abs(target_power - current_power)` as a `TypeError`, escaping the
        5-minute job exactly as the unguarded first read did. A Supervisor
        outage hits both entities, so covering only the first read would leave
        which read the outage lands on deciding whether the tick survives.
        """
        from core.bess.battery_system_manager import BatterySystemManager
        from core.bess.price_manager import MockSource

        monkeypatch.setattr(
            "core.bess.sensor_collector.SensorCollector", MockSensorCollector
        )
        system = BatterySystemManager(
            controller=mock_controller,
            price_source=MockSource(arbitrage_prices),
            addon_options={"inverter": {"platform": "growatt_server_min"}},
        )
        system.update_settings({"home": {"power_monitoring_enabled": True}})
        assert system._power_monitor is not None
        system._inverter_controller.strategic_intents = ["IDLE"] * 96

        # First read succeeds; the charge-rate read degrades to None.
        monkeypatch.setattr(
            mock_controller, "get_charging_power_rate", lambda *a, **k: None
        )

        system.adjust_charging_power()  # must not raise
