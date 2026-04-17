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
from unittest.mock import MagicMock

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
