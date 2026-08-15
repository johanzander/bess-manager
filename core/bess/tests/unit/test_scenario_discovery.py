"""Scenario-driven discovery regression tests.

Loads scenario JSON files from scripts/mock_ha/scenarios/ and runs them
through the real discovery pipeline (discover_integrations +
discover_sensors_from_registry), mocking only the transport layer
(_ws_query + _api_request).

Any scenario file that contains an ``expected_discovery`` section is
automatically included.  Adding a new regression test is just adding
that section to a scenario JSON.
"""

import json
from pathlib import Path

import pytest

from core.bess.ha_api_controller import HomeAssistantAPIController
from core.bess.tests.unit.test_registry_discovery import _huawei_registry

# ---------------------------------------------------------------------------
# Scenario loading
# ---------------------------------------------------------------------------

SCENARIO_DIR = Path(__file__).resolve().parents[4] / "scripts" / "mock_ha" / "scenarios"


def _load_scenario(name: str) -> dict:
    path = SCENARIO_DIR / f"{name}.json"
    with open(path) as f:
        return json.load(f)


def _has_expected_discovery(path: Path) -> bool:
    with open(path) as f:
        data = json.load(f)
    return "expected_discovery" in data


def _get_discovery_scenarios() -> list[str]:
    """Return scenario names that have an expected_discovery section."""
    return sorted(
        p.stem for p in SCENARIO_DIR.glob("*.json") if _has_expected_discovery(p)
    )


# ---------------------------------------------------------------------------
# Transport stubs
# ---------------------------------------------------------------------------


def _ws_stub(scenario: dict):
    """Replace _ws_query: routes each WS command to the matching scenario data."""

    def handler(commands: list[dict]) -> list:
        results = []
        for cmd in commands:
            t = cmd.get("type", "")
            if t == "config_entries/get":
                results.append(scenario.get("config_entries", []))
            elif t == "config/device_registry/list":
                results.append(scenario.get("devices", []))
            elif t == "get_services":
                results.append(scenario.get("services", {}))
            elif t == "config/entity_registry/list":
                results.append(scenario.get("entity_registry", []))
            else:
                results.append([])
        return results

    return handler


def _api_stub(scenario: dict):
    """Replace _api_request: returns sensor states for GET /api/states."""

    def handler(method: str, path: str, **kwargs):
        if method == "get" and path == "/api/states":
            return [
                {"entity_id": eid, **data}
                for eid, data in scenario.get("sensors", {}).items()
            ]
        return []

    return handler


# ---------------------------------------------------------------------------
# Parameterised test
# ---------------------------------------------------------------------------

_INTEGRATION_KEYS = (
    "growatt_found",
    "solax_found",
    "solis_found",
    "solax_has_growatt_tou",
    "solax_has_growatt_gen3",
    "nordpool_found",
    "nordpool_area",
    "nordpool_custom_area",
    "nordpool_config_entry_id",
    "octopus_found",
    "entsoe_found",
    "entsoe_entity",
    "detected_inverter_platforms",
    "currency",
    "vat_multiplier",
    "detected_phase_count",
)


@pytest.mark.parametrize("scenario_name", _get_discovery_scenarios())
class TestScenarioDiscovery:
    """Run the full discovery pipeline against each scenario file."""

    def _run(self, scenario_name: str, monkeypatch):
        scenario = _load_scenario(scenario_name)
        expected = scenario["expected_discovery"]

        ctrl = HomeAssistantAPIController.__new__(HomeAssistantAPIController)
        monkeypatch.setattr(ctrl, "_ws_query", _ws_stub(scenario))
        monkeypatch.setattr(ctrl, "_api_request", _api_stub(scenario))

        integrations, states = ctrl.discover_integrations()
        registry = ctrl.fetch_entity_registry()
        (
            platform_sensors,
            detected_platform,
            platform_disabled,
        ) = ctrl.discover_sensors_from_registry(registry)

        self._platform_disabled = platform_disabled
        return expected, integrations, platform_sensors, detected_platform, states

    # -- Integration detection -----------------------------------------------

    def test_integration_flags(self, scenario_name, monkeypatch):
        """All expected integration flags match."""
        expected, integrations, *_ = self._run(scenario_name, monkeypatch)
        for key in _INTEGRATION_KEYS:
            if key in expected:
                assert integrations[key] == expected[key], (
                    f"{scenario_name}: integrations[{key!r}] = "
                    f"{integrations[key]!r}, expected {expected[key]!r}"
                )

    # -- Detected platform ---------------------------------------------------

    def test_detected_platform(self, scenario_name, monkeypatch):
        """The auto-detected platform matches."""
        expected, _, _, detected_platform, _ = self._run(scenario_name, monkeypatch)
        if "detected_platform" in expected:
            assert detected_platform == expected["detected_platform"], (
                f"{scenario_name}: detected_platform = "
                f"{detected_platform!r}, expected {expected['detected_platform']!r}"
            )

    # -- Required sensors (primary platform) ---------------------------------

    def test_required_sensors_discovered(self, scenario_name, monkeypatch):
        """All required sensors for the primary platform are discovered."""
        expected, _, platform_sensors, detected_platform, _ = self._run(
            scenario_name, monkeypatch
        )
        required = expected.get("required_sensors", [])
        if not required:
            pytest.skip("no required_sensors defined")
        sensors = platform_sensors.get(detected_platform, {})
        missing = [k for k in required if k not in sensors]
        assert not missing, (
            f"{scenario_name}: sensors not discovered for "
            f"{detected_platform!r}: {missing}"
        )

    # -- Disabled entities (#549) --------------------------------------------

    def test_disabled_sensors_reported_and_not_mapped(self, scenario_name, monkeypatch):
        """Keys whose only entity is disabled are reported, never mapped.

        A disabled entity has no state, so mapping it guarantees a runtime
        404 — the failure the reporter of #549 saw as SYSTEM DEGRADED.
        """
        expected, _, platform_sensors, detected_platform, _ = self._run(
            scenario_name, monkeypatch
        )
        if "disabled_sensors" not in expected:
            pytest.skip("no disabled_sensors defined")

        disabled = self._platform_disabled.get(detected_platform, {})
        sensors = platform_sensors.get(detected_platform, {})

        assert sorted(disabled) == expected["disabled_sensors"], (
            f"{scenario_name}: disabled sensors for {detected_platform!r} = "
            f"{sorted(disabled)}, expected {expected['disabled_sensors']}"
        )
        still_mapped = [k for k in expected["disabled_sensors"] if k in sensors]
        assert not still_mapped, (
            f"{scenario_name}: disabled entities were mapped anyway "
            f"(guaranteed 404 at runtime): {still_mapped}"
        )

    # -- Platform-specific sensor lists ----------------------------------------

    def test_platform_specific_sensors(self, scenario_name, monkeypatch):
        """Check required_sensors_<platform> lists against their platform."""
        expected, _, platform_sensors, _, _ = self._run(scenario_name, monkeypatch)
        prefix = "required_sensors_"
        found_any = False
        for key, required in expected.items():
            if not key.startswith(prefix) or not isinstance(required, list):
                continue
            platform = key[len(prefix) :]
            found_any = True
            sensors = platform_sensors.get(platform, {})
            missing = [k for k in required if k not in sensors]
            assert not missing, (
                f"{scenario_name}: sensors not discovered for "
                f"{platform!r}: {missing}"
            )
        if not found_any:
            pytest.skip("no required_sensors_<platform> lists defined")

    # -- Sensor entity IDs are valid -----------------------------------------

    def test_sensor_entity_ids_are_valid(self, scenario_name, monkeypatch):
        """All discovered sensor entity IDs have a domain.name format."""
        _, _, platform_sensors, detected_platform, _ = self._run(
            scenario_name, monkeypatch
        )
        sensors = platform_sensors.get(detected_platform, {})
        for key, entity_id in sensors.items():
            assert "." in entity_id, (
                f"{scenario_name}: sensor {key!r} has invalid "
                f"entity_id {entity_id!r}"
            )

    # -- Phase current sensors (states-based, not registry-based) -------------

    def test_phase_currents_discovered(self, scenario_name, monkeypatch):
        """Household phase currents resolve exactly as the scenario declares.

        Opt-in via an ``expected_discovery.phase_currents`` map. Equality, not
        containment: a scenario whose states also carry the *inverter's* own
        output currents (huawei_solar gives both the identical display name)
        must not pick those up for grid-fuse protection — issue #120.
        """
        expected, _, _, _, states = self._run(scenario_name, monkeypatch)
        if "phase_currents" not in expected:
            pytest.skip("no phase_currents defined")

        ctrl = HomeAssistantAPIController.__new__(HomeAssistantAPIController)
        assert ctrl.discover_current_sensors(states) == expected["phase_currents"]


# ---------------------------------------------------------------------------
# Huawei LUNA2000: full discover_integrations() end-to-end test
#
# Task 2 added `_huawei_registry()` (a source-derived entity registry
# fixture) plus primitive-level tests for `_detect_platforms` and
# `_map_registry_entities`, but nothing exercised `discover_integrations()`
# itself. This closes that gap by mocking the transport layer exactly like
# the scenario-driven tests above (`_ws_query` + `_api_request`) and
# reusing Task 2's fixture directly, rather than a JSON scenario file.
# ---------------------------------------------------------------------------


def test_huawei_discover_integrations_end_to_end(monkeypatch):
    """discover_integrations() detects Huawei LUNA2000 from the entity registry."""
    registry = _huawei_registry()

    def ws_handler(commands: list[dict]) -> list:
        results = []
        for cmd in commands:
            t = cmd.get("type", "")
            if t == "config/entity_registry/list":
                results.append(registry)
            elif t == "config_entries/get":
                results.append([])
            elif t == "config/device_registry/list":
                results.append([])
            else:
                results.append([])
        return results

    def api_handler(method: str, path: str, **kwargs):
        if method == "get" and path == "/api/states":
            return []
        return []

    ctrl = HomeAssistantAPIController.__new__(HomeAssistantAPIController)
    monkeypatch.setattr(ctrl, "_ws_query", ws_handler)
    monkeypatch.setattr(ctrl, "_api_request", api_handler)

    result, _states = ctrl.discover_integrations()

    assert result["huawei_found"] is True
    assert "huawei_solar_luna2000" in result["detected_inverter_platforms"]
