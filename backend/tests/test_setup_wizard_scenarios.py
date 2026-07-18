"""Scenario-driven wizard completion tests.

Loads scenario JSON files from scripts/mock_ha/scenarios/ and runs each
wizard variant through POST /api/setup/complete, asserting that the
correct settings are persisted and live system calls are made.

Any scenario file that contains an ``expected_wizard`` section is
automatically included.  Each key under ``expected_wizard`` is a wizard
variant (e.g. "solax_modbus_growatt_min", "growatt_server_min") that is tested
independently.  Adding a new regression test is just adding a variant
to the scenario JSON.
"""

import json
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from api import router
from fastapi import FastAPI
from fastapi.testclient import TestClient

_test_app = FastAPI()
_test_app.include_router(router)
_client = TestClient(_test_app, raise_server_exceptions=False)

# ---------------------------------------------------------------------------
# Scenario loading
# ---------------------------------------------------------------------------

SCENARIO_DIR = Path(__file__).resolve().parents[2] / "scripts" / "mock_ha" / "scenarios"


def _load_scenario(name: str) -> dict:
    path = SCENARIO_DIR / f"{name}.json"
    with open(path) as f:
        return json.load(f)


def _get_wizard_scenarios() -> list[tuple[str, str]]:
    """Return (scenario_name, variant_name) pairs for parameterization."""
    pairs = []
    for path in sorted(SCENARIO_DIR.glob("*.json")):
        with open(path) as f:
            data = json.load(f)
        for variant in data.get("expected_wizard", {}):
            pairs.append((path.stem, variant))
    return pairs


# ---------------------------------------------------------------------------
# Parameterized tests
# ---------------------------------------------------------------------------

_WIZARD_SCENARIOS = _get_wizard_scenarios()
_IDS = [f"{s}-{v}" for s, v in _WIZARD_SCENARIOS]


def _get_variant(scenario_name: str, variant_name: str) -> dict:
    scenario = _load_scenario(scenario_name)
    return scenario["expected_wizard"][variant_name]


@pytest.mark.parametrize(
    "scenario_name, variant_name",
    _WIZARD_SCENARIOS,
    ids=_IDS,
)
class TestWizardComplete:
    """Run POST /api/setup/complete for each scenario wizard variant."""

    @pytest.fixture(autouse=True)
    def _setup(self, scenario_name, variant_name, request):
        """Inject scenario_controller and run the wizard."""
        scenario = _load_scenario(scenario_name)
        bess_config = scenario.get("bess_config", {})
        variant = scenario["expected_wizard"][variant_name]

        # Build mock controller from scenario bess_config
        ctrl = MagicMock()
        store_data = deepcopy(bess_config)
        ctrl.settings_store.data = store_data
        ctrl.ha_controller.sensors = {}

        def _get_section(name: str) -> dict:
            return dict(store_data.get(name, {}))

        def _save_all(data: dict) -> None:
            for key, val in data.items():
                store_data[key] = dict(val)

        def _get_active_sensors() -> dict:
            sensors = store_data.get("sensors", {})
            if "platform" not in sensors:
                return {k: v for k, v in sensors.items() if isinstance(v, str)}
            platform = sensors.get("platform", "")
            platform_sensors = sensors.get(platform, {})
            shared_sensors = sensors.get("shared", {})
            result = {}
            if isinstance(shared_sensors, dict):
                result.update(shared_sensors)
            if isinstance(platform_sensors, dict):
                result.update(platform_sensors)
            return result

        def _refresh_active_sensors() -> None:
            active = _get_active_sensors()
            ctrl.ha_controller.sensors = {k: v for k, v in active.items() if v}

        ctrl.settings_store.get_section.side_effect = _get_section
        ctrl.settings_store.save_all.side_effect = _save_all
        ctrl.settings_store.get_active_sensors.side_effect = _get_active_sensors
        ctrl.refresh_active_sensors.side_effect = _refresh_active_sensors
        sys.modules["app"].bess_controller = ctrl

        # POST the wizard payload
        self.response = _client.post("/api/setup/complete", json=variant["payload"])
        self.ctrl = ctrl
        self.variant = variant
        self.scenario_name = scenario_name
        self.variant_name = variant_name

    def _saved_sections(self) -> dict:
        return self.ctrl.settings_store.save_all.call_args[0][0]

    # -- Basic success -------------------------------------------------------

    def test_returns_200(self, scenario_name, variant_name):
        assert self.response.status_code == 200
        assert self.response.json()["success"] is True

    # -- Persisted sections --------------------------------------------------

    def test_expected_saved_sections(self, scenario_name, variant_name):
        """All key/value pairs in expected_saved are present in save_all."""
        saved = self._saved_sections()
        for section, expected_fields in self.variant["expected_saved"].items():
            assert section in saved, (
                f"{self.scenario_name}/{self.variant_name}: "
                f"section {section!r} not in saved sections"
            )
            for key, expected_val in expected_fields.items():
                actual_val = saved[section].get(key)
                assert actual_val == expected_val, (
                    f"{self.scenario_name}/{self.variant_name}: "
                    f"saved[{section!r}][{key!r}] = {actual_val!r}, "
                    f"expected {expected_val!r}"
                )

    def test_absent_sections(self, scenario_name, variant_name):
        """Sections listed in expected_absent_sections must not be saved."""
        saved = self._saved_sections()
        for section in self.variant.get("expected_absent_sections", []):
            assert section not in saved, (
                f"{self.scenario_name}/{self.variant_name}: "
                f"section {section!r} should not be in saved sections"
            )

    # -- Live system calls ---------------------------------------------------

    def test_live_effects(self, scenario_name, variant_name):
        """Verify live system calls (platform switch, device_id, ha_sensors)."""
        expected_live = self.variant.get("expected_live", {})

        if "switch_inverter_platform" in expected_live:
            self.ctrl.system.switch_inverter_platform.assert_called_once_with(
                expected_live["switch_inverter_platform"]
            )

        if "growatt_device_id" in expected_live:
            assert (
                self.ctrl.ha_controller.growatt_device_id
                == expected_live["growatt_device_id"]
            )

        for key, entity_id in expected_live.get("ha_sensors", {}).items():
            assert self.ctrl.ha_controller.sensors.get(key) == entity_id, (
                f"{self.scenario_name}/{self.variant_name}: "
                f"ha_controller.sensors[{key!r}] = "
                f"{self.ctrl.ha_controller.sensors.get(key)!r}, "
                f"expected {entity_id!r}"
            )

    def test_scheduler_started(self, scenario_name, variant_name):
        self.ctrl.start_scheduler.assert_called_once()

    # -- TOU slot assertions -------------------------------------------------

    def test_tou_slots(self, scenario_name, variant_name):
        """Verify TOU slot presence/absence in the payload sensors."""
        sensors = self.variant["payload"]["sensors"]

        for slot in self.variant.get("tou_slots_present", []):
            assert f"tou_time_{slot}_enabled" in sensors, (
                f"{self.scenario_name}/{self.variant_name}: "
                f"tou_time_{slot}_enabled missing from payload"
            )

        for slot in self.variant.get("tou_slots_absent", []):
            assert f"tou_time_{slot}_enabled" not in sensors, (
                f"{self.scenario_name}/{self.variant_name}: "
                f"tou_time_{slot}_enabled should not be in payload"
            )

        if self.variant.get("no_tou_slots"):
            for key in sensors:
                assert not key.startswith("tou_time_"), (
                    f"{self.scenario_name}/{self.variant_name}: "
                    f"unexpected TOU sensor {key!r} in payload"
                )
