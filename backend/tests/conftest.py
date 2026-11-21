"""Pytest configuration for backend tests.

Stubs out the ``app`` module before any test is collected so that importing
``api`` (which does ``from app import bess_controller`` inside endpoint
functions) does not trigger the full BESSController initialisation (which
requires a live Home Assistant connection).

Individual tests that need a specific bess_controller shape should set
``sys.modules["app"].bess_controller`` to a suitably configured MagicMock.
"""

import os
import sys
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

# Ensure project root is on sys.path so core.bess is importable
# regardless of whether core/bess/tests/ has already been collected.
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Must run before any test module is imported.
if "app" not in sys.modules:
    _stub = MagicMock()
    sys.modules["app"] = _stub

if "log_config" not in sys.modules:
    sys.modules["log_config"] = MagicMock()


@pytest.fixture()
def wire_real_settings_models() -> Callable[[MagicMock], tuple[Any, Any]]:
    """Return a function that gives a mocked bess_controller real settings
    models, applied the way BatterySystemManager.update_settings applies
    them, so the models' own __post_init__ invariants run as in production
    instead of a MagicMock accepting anything (#917)."""
    from core.bess.settings import BatterySettings, HomeSettings

    def _wire(ctrl: MagicMock) -> tuple[BatterySettings, HomeSettings]:
        battery, home = BatterySettings(), HomeSettings()
        ctrl.system.battery_settings = battery
        ctrl.system.home_settings = home

        def _update_settings(settings: dict) -> None:
            if "battery" in settings:
                battery.update(**settings["battery"])
            if "home" in settings:
                home.update(**settings["home"])

        ctrl.system.update_settings.side_effect = _update_settings
        return battery, home

    return _wire
