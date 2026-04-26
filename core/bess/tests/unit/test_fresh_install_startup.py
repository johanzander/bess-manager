"""Tests for fresh-install startup behaviour.

A fresh install has no inverter platform configured.  The system must start
successfully in an unconfigured state so the web UI is reachable and the
user can complete the setup wizard.  These tests act as a regression guard
against the crash reported in docs/bess log.log.
"""

import os
import sys

import pytest

# Add the project root to Python path BEFORE any other imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from core.bess.battery_system_manager import BatterySystemManager
from core.bess.price_manager import MockSource
from core.bess.tests.conftest import MockHomeAssistantController


class TestFreshInstallStartup:
    """Verify the system survives startup with no inverter configuration."""

    def _make_system(self, addon_options: dict | None = None) -> BatterySystemManager:
        controller = MockHomeAssistantController()
        return BatterySystemManager(
            controller=controller,
            price_source=MockSource([1.0] * 96),
            addon_options=addon_options or {},
        )

    # --- Core requirement: system must not crash on fresh install ---

    def test_empty_options_creates_unconfigured_system(self):
        """Fresh install with empty options must not crash."""
        system = self._make_system(addon_options={})
        assert not system.is_configured
        assert system._inverter_controller is None
        assert system.inverter_platform is None

    def test_empty_growatt_section_does_not_crash(self):
        """Reproduces the exact crash from the bug report: growatt section
        exists but inverter_type is an empty string."""
        system = self._make_system(
            addon_options={"growatt": {"inverter_type": ""}}
        )
        assert not system.is_configured

    def test_missing_growatt_section_does_not_crash(self):
        """No growatt section at all — fresh install with no legacy config."""
        system = self._make_system(addon_options={})
        assert not system.is_configured

    def test_empty_inverter_section_does_not_crash(self):
        """Inverter section exists but platform is empty."""
        system = self._make_system(addon_options={"inverter": {}})
        assert not system.is_configured

    def test_empty_platform_string_does_not_crash(self):
        """Inverter section with empty platform string."""
        system = self._make_system(addon_options={"inverter": {"platform": ""}})
        assert not system.is_configured

    # --- start() must be safe in unconfigured state ---

    def test_start_unconfigured_does_not_crash(self):
        """start() must be a no-op when system is unconfigured."""
        system = self._make_system(addon_options={})
        system.start()  # Must not raise

    # --- Configured systems still work ---

    def test_valid_platform_creates_configured_system(self):
        """A valid inverter.platform produces a configured system."""
        system = self._make_system(
            addon_options={"inverter": {"platform": "growatt_min"}}
        )
        assert system.is_configured
        assert system.inverter_platform == "growatt_min"
        assert system._inverter_controller is not None

    def test_legacy_inverter_type_creates_configured_system(self):
        """Legacy growatt.inverter_type still works for existing users."""
        system = self._make_system(
            addon_options={"growatt": {"inverter_type": "SPH"}}
        )
        assert system.is_configured
        assert system.inverter_platform == "growatt_sph"

    # --- Transition from unconfigured to configured ---

    def test_switch_platform_activates_unconfigured_system(self):
        """switch_inverter_platform() must transition from unconfigured to
        configured — this is the path the setup wizard takes."""
        system = self._make_system(addon_options={})
        assert not system.is_configured

        system.switch_inverter_platform("solax")
        assert system.is_configured
        assert system.inverter_platform == "solax"
        assert system._inverter_controller is not None

    # --- Invalid config still fails explicitly ---

    def test_invalid_inverter_type_raises(self):
        """A non-empty but invalid inverter_type must still raise."""
        with pytest.raises(AssertionError, match="Unknown inverter_type"):
            self._make_system(
                addon_options={"growatt": {"inverter_type": "BOGUS"}}
            )

    def test_invalid_platform_raises(self):
        """A non-empty but invalid platform must still raise."""
        with pytest.raises(AssertionError, match="Unknown inverter platform"):
            self._make_system(
                addon_options={"inverter": {"platform": "bogus"}}
            )
