"""Tests for platform capability declarations and their effect on BSM behavior.

Verifies that each InverterController subclass declares the correct
capabilities and that BatterySystemManager respects them (e.g. not
initializing the power monitor on platforms without charge rate control).
"""

from core.bess.growatt_min_controller import GrowattMinController
from core.bess.growatt_sph_controller import GrowattSphController
from core.bess.inverter_controller import InverterController
from core.bess.solax_controller import SolaxController
from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController

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

    def test_solax_modbus_growatt_inherits_charge_rate_support(self):
        # SolaxModbusGrowattController extends GrowattMinController and
        # has charge rate registers available via Modbus
        assert SolaxModbusGrowattController.supports_charge_rate_control is True


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
