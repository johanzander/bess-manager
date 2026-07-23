# Huawei Inverter Platform (Issue #120) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Huawei LUNA2000 inverter support (Phase 1, source-derived fixture) per the `add-inverter-platform` skill and `docs/superpowers/specs/2026-07-22-issue-120-huawei-inverter-platform-design.md`: a new `HuaweiController` writing persistent TOU periods via `huawei_solar.set_tou_periods`, detection via the `huawei_solar` HA integration's entity registry, and full wizard/settings wiring.

**Architecture:** New `TX-Vendor-service × SM-Period-lists` platform, modeled on `GrowattSphController` (period-list shape) crossed with `SolaxController` (vendor-service plumbing) — the pattern established in `core/bess/inverter_controller.py`. Platform ID `huawei_solar_luna2000` (matches the existing `{integration_domain}_{variant}` naming convention: `growatt_server_min`, `solax_modbus_native`).

**Tech Stack:** Python (backend/core), TypeScript/React (frontend), pytest, Vitest/Playwright.

## Global Constraints

- Platform ID: `huawei_solar_luna2000` (not the design doc's shorthand `"huawei"` — aligned to existing naming convention during planning; update the design doc's shorthand mentally, no doc edit needed since it never hardcoded the literal string in code).
- LUNA2000 battery only. LG RESU is out of scope. Detection uses the `huawei_solar` integration's own signal, not a guessed device-info field: the working-mode select entity's `options` attribute omits `time_of_use_luna2000` on LG RESU installs and `time_of_use_lg` on LUNA2000 installs (verified in `select.py`'s `StorageModeSelectEntity.__init__`). Task 1 adds `get_huawei_working_mode_options()`; Task 3's `write_schedule_to_hardware` checks it and raises `SystemConfigurationError` before writing LUNA2000-format periods against an LG RESU battery, per `docs/agents/rules.md` no-silent-fallbacks.
- Device ID: Huawei needs its own `huawei_device_id` (HA device-registry ID of the **battery** device) — kept as a separate field end-to-end (settings, API payload, `HomeAssistantAPIController` constructor), not overloaded onto the existing `growatt_device_id` field, since they're different vendors' concepts stored under different config sections.
- No silent fallbacks anywhere (`docs/agents/rules.md`): every write path raises clearly on missing entities/config rather than no-op.
- Run `.venv/bin/pytest -m "not slow"` after every backend task; run `cd frontend && npx tsc --noEmit && npm run lint:fix` after every frontend task.
- **Explicitly out of scope for this plan** (tracked as a required follow-up per the `add-inverter-platform` skill checklist, not silently dropped): the Playwright wizard E2E scenario (`scripts/mock_ha/scenarios/ci-wizard-huawei.json`, `e2e/tests/wizard-expectations.ts`, `e2e/tests/setup-wizard.spec.ts`, `e2e/run-e2e.sh`, `.github/workflows/ci.yml`). The backend discovery regression test (Task 8) is the Phase-1 substitute; add E2E wizard coverage in a fast-follow task once this core lands, using real `POST /api/setup/discover` output to build accurate fixture data rather than hand-guessing a 350-line JSON scenario file.

---

### Task 1: `HomeAssistantAPIController` — Huawei device ID, suffix map, service-call helpers

**Files:**
- Modify: `core/bess/ha_api_controller.py`
- Test: `core/bess/tests/unit/test_ha_api_controller.py` (or nearest existing controller-method test file — check for one before creating; if none exists for this class's service-call methods, create `core/bess/tests/unit/test_huawei_ha_controller.py`)

**Interfaces:**
- Produces: `HomeAssistantAPIController.huawei_device_id: str | None` (constructor param, mirrors `growatt_device_id`), `HUAWEI_SUFFIX_MAP: ClassVar[dict[str, str]]`, `set_huawei_working_mode(option: str) -> None`, `get_huawei_working_mode() -> str | None`, `get_huawei_working_mode_options() -> list[str]`, `write_huawei_tou_periods(periods_text: str) -> None`.

- [ ] **Step 1: Add `huawei_device_id` constructor param**

In `core/bess/ha_api_controller.py`, modify `__init__` (around line 72-102):

```python
    def __init__(
        self,
        ha_url: str,
        token: str,
        sensor_config: dict | None = None,
        growatt_device_id: str | None = None,
        huawei_device_id: str | None = None,
    ):
        """Initialize the Controller with Home Assistant API access.

        Args:
            ha_url: Base URL of Home Assistant (default: "http://supervisor/core")
            token: Long-lived access token for Home Assistant
            sensor_config: Sensor configuration mapping from options.json
            growatt_device_id: Growatt device ID for TOU segment operations
            huawei_device_id: Huawei battery device ID for TOU period operations

        """
```

And after the existing `self.growatt_device_id = growatt_device_id` line, add:

```python
        # Store Huawei battery device ID for TOU period operations
        self.huawei_device_id = huawei_device_id
```

- [ ] **Step 2: Add `HUAWEI_SUFFIX_MAP` and marker suffix**

Add after `SOLAX_NATIVE_SUFFIX_MAP` (ends around line 681):

```python
    # Huawei LUNA2000 via the huawei_solar integration. unique_id format is
    # f"{device.serial_number}_{register_key}" — verified against
    # wlcrs/huawei_solar select.py:204, number.py:358, switch.py:200.
    HUAWEI_SUFFIX_MAP: ClassVar[dict[str, str]] = {
        "storage_state_of_capacity": "battery_soc",
        "storage_charge_discharge_power": "battery_charge_power",
        "storage_maximum_charging_power": "battery_charging_power_rate",
        "storage_maximum_discharging_power": "battery_discharging_power_rate",
        "storage_charging_cutoff_capacity": "battery_charge_stop_soc",
        "storage_grid_charge_cutoff_state_of_charge": "battery_discharge_stop_soc",
        "storage_charge_from_grid_function": "grid_charge",
        "storage_working_mode_settings": "huawei_working_mode",
        "active_power": "local_load_power",
    }
```

And add the marker suffix next to `_SOLAX_NATIVE_MARKER_SUFFIX` (around line 2864):

```python
    _HUAWEI_BATTERY_MARKER_SUFFIX: ClassVar[str] = (
        "storage_working_mode_settings"  # only present on battery-equipped Huawei installs
    )
```

- [ ] **Step 3: Add Huawei service-call helpers**

Add near `set_grid_charge`/`grid_charge_enabled` (after line ~1234):

```python
    def get_huawei_working_mode(self) -> str | None:
        """Get the current Huawei battery working mode (e.g. 'time_of_use_luna2000')."""
        return self._get_raw_state("huawei_working_mode")

    def get_huawei_working_mode_options(self) -> list[str]:
        """Get the working-mode select entity's available options.

        The huawei_solar integration removes 'time_of_use_luna2000' from
        this list on LG RESU installs and 'time_of_use_lg' on LUNA2000
        installs (select.py: StorageModeSelectEntity.__init__) — this is
        the integration itself telling us which battery family is
        connected, rather than BESS inferring it from an undocumented
        device-info field. Used by HuaweiController to refuse LG RESU
        installs with a clear error instead of writing LUNA2000-format
        TOU periods against them.

        Returns:
            List of option strings, or [] if the entity is unavailable.

        Raises:
            SystemConfigurationError: If the working-mode sensor isn't configured.
        """
        entity_id = self._get_entity_for_service("huawei_working_mode")
        response = self._api_request(
            "get",
            f"/api/states/{entity_id}",
            operation="Read Huawei working mode options",
            category="config",
        )
        if not response:
            return []
        return list(response.get("attributes", {}).get("options", []))

    def set_huawei_working_mode(self, option: str) -> None:
        """Set the Huawei battery working mode via the standard select entity.

        Args:
            option: One of the StorageWorkingModesC option strings, lowercased
                (e.g. "time_of_use_luna2000").
        """
        entity_id = self._get_entity_for_service("huawei_working_mode")
        self._service_call_with_retry(
            "select",
            "select_option",
            operation=f"Set Huawei working mode to {option}",
            entity_id=entity_id,
            option=option,
        )

    def write_huawei_tou_periods(self, periods_text: str) -> None:
        """Write the Huawei battery's TOU period list via huawei_solar.set_tou_periods.

        Args:
            periods_text: Newline-joined period lines, each
                "HH:MM-HH:MM/<days>/<+|->" (+ = charge, - = discharge).

        Raises:
            SystemConfigurationError: If huawei_device_id is not configured.
        """
        if not self.huawei_device_id:
            raise SystemConfigurationError(
                "Huawei battery device_id not configured. Run the setup wizard "
                "to configure the inverter."
            )
        self._service_call_with_retry(
            "huawei_solar",
            "set_tou_periods",
            operation="Write Huawei TOU periods",
            device_id=self.huawei_device_id,
            periods=periods_text,
        )
```

- [ ] **Step 4: Write failing tests**

Create `core/bess/tests/unit/test_huawei_ha_controller.py`:

```python
"""Tests for Huawei service-call helpers on HomeAssistantAPIController."""

from unittest.mock import MagicMock, patch

import pytest

from core.bess.exceptions import SystemConfigurationError
from core.bess.ha_api_controller import HomeAssistantAPIController


@pytest.fixture
def controller() -> HomeAssistantAPIController:
    ctrl = HomeAssistantAPIController(
        ha_url="http://ha.local",
        token="tok",
        sensor_config={"huawei_working_mode": "select.huawei_working_mode"},
        huawei_device_id="dev-123",
    )
    ctrl.test_mode = False
    return ctrl


class TestHuaweiServiceCalls:
    def test_set_huawei_working_mode_calls_select_select_option(
        self, controller: HomeAssistantAPIController
    ) -> None:
        with patch.object(controller, "_api_request") as mock_request:
            mock_request.return_value = {}
            controller.set_huawei_working_mode("time_of_use_luna2000")
            args, kwargs = mock_request.call_args
            assert args[0] == "post"
            assert args[1] == "/api/services/select/select_option"
            assert kwargs["json"]["entity_id"] == "select.huawei_working_mode"
            assert kwargs["json"]["option"] == "time_of_use_luna2000"

    def test_write_huawei_tou_periods_includes_device_id(
        self, controller: HomeAssistantAPIController
    ) -> None:
        with patch.object(controller, "_api_request") as mock_request:
            mock_request.return_value = {}
            controller.write_huawei_tou_periods("06:00-08:00/1234567/+")
            args, kwargs = mock_request.call_args
            assert args[1] == "/api/services/huawei_solar/set_tou_periods"
            assert kwargs["json"]["device_id"] == "dev-123"
            assert kwargs["json"]["periods"] == "06:00-08:00/1234567/+"

    def test_write_huawei_tou_periods_raises_without_device_id(self) -> None:
        ctrl = HomeAssistantAPIController(
            ha_url="http://ha.local", token="tok", sensor_config={}
        )
        with pytest.raises(SystemConfigurationError):
            ctrl.write_huawei_tou_periods("06:00-08:00/1234567/+")

    def test_get_huawei_working_mode_options_returns_attribute_list(
        self, controller: HomeAssistantAPIController
    ) -> None:
        with patch.object(controller, "_api_request") as mock_request:
            mock_request.return_value = {
                "state": "maximise_self_consumption",
                "attributes": {
                    "options": [
                        "adaptive",
                        "fixed_charge_discharge",
                        "maximise_self_consumption",
                        "time_of_use_luna2000",
                        "fully_fed_to_grid",
                    ]
                },
            }
            options = controller.get_huawei_working_mode_options()
            assert "time_of_use_luna2000" in options
            assert "time_of_use_lg" not in options

    def test_get_huawei_working_mode_options_empty_when_no_response(
        self, controller: HomeAssistantAPIController
    ) -> None:
        with patch.object(controller, "_api_request") as mock_request:
            mock_request.return_value = None
            assert controller.get_huawei_working_mode_options() == []
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `.venv/bin/pytest core/bess/tests/unit/test_huawei_ha_controller.py -v`
Expected: FAIL — `set_huawei_working_mode`/`write_huawei_tou_periods` don't exist yet.

- [ ] **Step 6: Verify tests pass after Steps 1-3**

Run: `.venv/bin/pytest core/bess/tests/unit/test_huawei_ha_controller.py -v`
Expected: PASS (5 tests).

- [ ] **Step 7: Commit**

```bash
git add core/bess/ha_api_controller.py core/bess/tests/unit/test_huawei_ha_controller.py
git commit -m "feat: add Huawei service-call helpers to HomeAssistantAPIController"
```

---

### Task 2: Detection wiring — `_INVERTER_PLATFORMS`, `discover_integrations`, `huawei_device_id` resolution

**Files:**
- Modify: `core/bess/ha_api_controller.py`
- Test: `core/bess/tests/unit/test_registry_discovery.py`

**Interfaces:**
- Consumes: Task 1's `HUAWEI_SUFFIX_MAP`, `_HUAWEI_BATTERY_MARKER_SUFFIX`.
- Produces: `discover_integrations()` result keys `huawei_found: bool`, `huawei_device_id: str | None`; `"huawei_solar_luna2000"` appended to `detected_inverter_platforms` when found.

- [ ] **Step 1: Write failing detection tests**

In `core/bess/tests/unit/test_registry_discovery.py`, add near the existing `_entity()` helper and `_solax_native_registry()`-style fixtures (top of file):

```python
def _huawei_registry(serial: str = "HW2024ABCDEF") -> list[dict]:
    """Source-derived Huawei LUNA2000 registry (verified unique_id shapes,
    see docs/superpowers/specs/2026-07-22-issue-120-huawei-inverter-platform-design.md)."""
    return [
        _entity(
            "sensor.huawei_battery_state_of_capacity",
            "huawei_solar",
            f"{serial}_storage_state_of_capacity",
        ),
        _entity(
            "sensor.huawei_battery_charge_discharge_power",
            "huawei_solar",
            f"{serial}_storage_charge_discharge_power",
        ),
        _entity(
            "number.huawei_battery_maximum_charging_power",
            "huawei_solar",
            f"{serial}_storage_maximum_charging_power",
        ),
        _entity(
            "number.huawei_battery_maximum_discharging_power",
            "huawei_solar",
            f"{serial}_storage_maximum_discharging_power",
        ),
        _entity(
            "number.huawei_battery_charging_cutoff_capacity",
            "huawei_solar",
            f"{serial}_storage_charging_cutoff_capacity",
        ),
        _entity(
            "number.huawei_battery_grid_charge_cutoff_state_of_charge",
            "huawei_solar",
            f"{serial}_storage_grid_charge_cutoff_state_of_charge",
        ),
        _entity(
            "switch.huawei_battery_charge_from_grid_function",
            "huawei_solar",
            f"{serial}_storage_charge_from_grid_function",
        ),
        _entity(
            "select.huawei_battery_working_mode",
            "huawei_solar",
            f"{serial}_storage_working_mode_settings",
        ),
        _entity(
            "sensor.huawei_inverter_active_power",
            "huawei_solar",
            f"{serial}_active_power",
        ),
    ]
```

Add a test class:

```python
class TestHuaweiDiscovery:
    def setup_method(self):
        self.ctrl = HomeAssistantAPIController(
            ha_url="http://ha.local", token="tok", sensor_config={}
        )

    def test_huawei_entities_detected(self):
        detected = self.ctrl._detect_platforms(
            _huawei_registry(), {"huawei": ["huawei_solar"]}
        )
        assert detected["huawei"] is True

    def test_huawei_map_matches_registry(self):
        result = self.ctrl._map_registry_entities(
            _huawei_registry(), ["huawei_solar"], self.ctrl.HUAWEI_SUFFIX_MAP
        )
        assert result["battery_soc"] == "sensor.huawei_battery_state_of_capacity"
        assert (
            result["huawei_working_mode"] == "select.huawei_battery_working_mode"
        )
        assert len(result) == 9
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest core/bess/tests/unit/test_registry_discovery.py -k Huawei -v`
Expected: FAIL — `HUAWEI_SUFFIX_MAP` not found on controller (or `_detect_platforms` returns `False` since `"huawei"` isn't in `_INVERTER_PLATFORMS` yet).

- [ ] **Step 3: Add `_INVERTER_PLATFORMS` entry**

In `core/bess/ha_api_controller.py`, modify (around line 2819-2822):

```python
    _INVERTER_PLATFORMS: ClassVar[dict[str, list[str]]] = {
        "growatt": ["growatt_server"],
        "solax": ["solax_modbus", "solax"],
        "huawei": ["huawei_solar"],
    }
```

- [ ] **Step 4: Wire `discover_integrations()`**

In `discover_integrations()` (around line 2421-2439), add to the initial `result` dict:

```python
        result: dict = {
            "growatt_found": False,
            "device_sn": None,
            "growatt_device_id": None,
            "solax_found": False,
            "huawei_found": False,
            "huawei_device_id": None,
            "nordpool_found": False,
            ...
```

Around line 2460-2462, add:

```python
        inverter_detected = self.detect_inverter_integrations(registry)
        result["growatt_found"] = inverter_detected.get("growatt", False)
        result["solax_found"] = inverter_detected.get("solax", False)
        result["huawei_found"] = inverter_detected.get("huawei", False)
```

Around line 2510-2528 (the `detected` list construction), add after the existing `solax_found` block:

```python
        if result["huawei_found"]:
            detected.append("huawei_solar_luna2000")
        result["detected_inverter_platforms"] = detected
```

- [ ] **Step 5: Resolve `huawei_device_id` in `_parse_ha_metadata`**

In `_parse_ha_metadata` (around line 2217-2304), after the existing `growatt_device_id` resolution block, add:

```python
        # Find huawei_solar config_entry_id, then the *battery* device
        # within it (huawei_solar creates multiple devices per config entry —
        # inverter, battery, power meter, optional EMMA — so device_id must
        # be filtered to the one whose entities include the working-mode
        # marker, not just "any device on this config entry").
        huawei_config_entry_id: str | None = None
        for entry in config_entries_result:
            if entry.get("domain") == "huawei_solar" and entry.get("state") == "loaded":
                huawei_config_entry_id = entry["entry_id"]
                break

        huawei_device_id: str | None = None
        if huawei_config_entry_id:
            battery_entity_device_ids = {
                e.get("device_id")
                for e in entity_registry_result
                if e.get("platform") == "huawei_solar"
                and str(e.get("unique_id", "")).endswith(
                    f"_{self._HUAWEI_BATTERY_MARKER_SUFFIX}"
                )
            }
            for device in devices_result:
                if (
                    huawei_config_entry_id in device.get("config_entries", [])
                    and device.get("id") in battery_entity_device_ids
                ):
                    huawei_device_id = device["id"]
                    break
```

And add `"huawei_device_id": huawei_device_id,` to the returned dict at the end of `_parse_ha_metadata`, and thread it through in `discover_ha_metadata`'s docstring/return and in `discover_integrations()` next to the existing `result["growatt_device_id"] = metadata["growatt_device_id"]` line:

```python
            result["growatt_device_id"] = metadata["growatt_device_id"]
            result["huawei_device_id"] = metadata.get("huawei_device_id")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest core/bess/tests/unit/test_registry_discovery.py -k Huawei -v`
Expected: PASS (2 tests).

- [ ] **Step 7: Run full fast suite**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS, no regressions.

- [ ] **Step 8: Commit**

```bash
git add core/bess/ha_api_controller.py core/bess/tests/unit/test_registry_discovery.py
git commit -m "feat: detect Huawei LUNA2000 via huawei_solar entity registry"
```

---

### Task 3: `HuaweiController` class

**Files:**
- Create: `core/bess/huawei_controller.py`
- Test: `core/bess/tests/unit/test_huawei_controller.py`

**Interfaces:**
- Consumes: `InverterController` ABC (`core/bess/inverter_controller.py`), `HomeAssistantAPIController.get_huawei_working_mode/set_huawei_working_mode/write_huawei_tou_periods` (Task 1).
- Produces: `HuaweiController(battery_settings: BatterySettings)` implementing all `InverterController` abstract methods.

- [ ] **Step 1: Write failing tests for period grouping**

Create `core/bess/tests/unit/test_huawei_controller.py`:

```python
"""Behavioral tests for the Huawei LUNA2000 inverter controller."""

from unittest.mock import MagicMock

import pytest

from core.bess.exceptions import SystemConfigurationError
from core.bess.huawei_controller import HuaweiController
from core.bess.settings import BatterySettings


def make_intents(hourly: dict[int, str], default: str = "IDLE") -> list[str]:
    quarterly = [default] * 96
    for hour, intent in hourly.items():
        for p in range(hour * 4, (hour + 1) * 4):
            quarterly[p] = intent
    return quarterly


def make_schedule_mock(intents: list[str]) -> MagicMock:
    schedule = MagicMock()
    schedule.original_dp_results = {"strategic_intent": intents}
    schedule.actions = [0.0] * len(intents)
    return schedule


@pytest.fixture
def battery_settings() -> BatterySettings:
    return BatterySettings(
        total_capacity=10.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        min_soc=15.0,
        max_soc=95.0,
    )


@pytest.fixture
def controller(battery_settings: BatterySettings) -> HuaweiController:
    return HuaweiController(battery_settings=battery_settings)


class TestScheduleBuilding:
    def test_charge_period_produces_plus_flag(self, controller: HuaweiController) -> None:
        intents = make_intents({2: "GRID_CHARGING"})
        controller.create_schedule(make_schedule_mock(intents))
        assert len(controller._periods) == 1
        assert controller._periods[0]["flag"] == "+"
        assert controller._periods[0]["start_time"] == "02:00"
        assert controller._periods[0]["end_time"] == "02:59"

    def test_discharge_period_produces_minus_flag(
        self, controller: HuaweiController
    ) -> None:
        intents = make_intents({18: "BATTERY_EXPORT"})
        controller.create_schedule(make_schedule_mock(intents))
        assert controller._periods[0]["flag"] == "-"

    def test_idle_periods_produce_no_entry(self, controller: HuaweiController) -> None:
        intents = make_intents({})  # all IDLE
        controller.create_schedule(make_schedule_mock(intents))
        assert controller._periods == []

    def test_period_limit_enforced_at_14(self, controller: HuaweiController) -> None:
        # 20 separated single-quarter charge blocks (non-adjacent so they
        # don't merge), exceeding MAX_TOU_PERIODS=14.
        hourly = {h: "GRID_CHARGING" for h in range(0, 40, 2)}
        intents = make_intents(hourly)
        controller.create_schedule(make_schedule_mock(intents))
        assert len(controller._periods) <= HuaweiController.MAX_TOU_PERIODS


class TestWriteSchedule:
    def test_write_schedule_sets_working_mode_when_drifted(
        self, controller: HuaweiController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING"})
        controller.create_schedule(make_schedule_mock(intents))
        ha = MagicMock()
        ha.get_huawei_working_mode_options.return_value = [
            "maximise_self_consumption",
            "time_of_use_luna2000",
        ]
        ha.get_huawei_working_mode.return_value = "maximise_self_consumption"
        controller.write_schedule_to_hardware(ha, 0, [])
        ha.set_huawei_working_mode.assert_called_once_with("time_of_use_luna2000")

    def test_write_schedule_skips_mode_write_when_already_set(
        self, controller: HuaweiController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING"})
        controller.create_schedule(make_schedule_mock(intents))
        ha = MagicMock()
        ha.get_huawei_working_mode_options.return_value = []
        ha.get_huawei_working_mode.return_value = "time_of_use_luna2000"
        controller.write_schedule_to_hardware(ha, 0, [])
        ha.set_huawei_working_mode.assert_not_called()

    def test_write_schedule_calls_write_tou_periods_with_joined_text(
        self, controller: HuaweiController
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING", 18: "LOAD_SUPPORT"})
        controller.create_schedule(make_schedule_mock(intents))
        ha = MagicMock()
        ha.get_huawei_working_mode_options.return_value = []
        ha.get_huawei_working_mode.return_value = "time_of_use_luna2000"
        controller.write_schedule_to_hardware(ha, 0, [])
        ha.write_huawei_tou_periods.assert_called_once()
        text = ha.write_huawei_tou_periods.call_args[0][0]
        assert "02:00-02:59/1234567/+" in text
        assert "18:00-18:59/1234567/-" in text

    def test_write_schedule_no_periods_writes_empty_string(
        self, controller: HuaweiController
    ) -> None:
        intents = make_intents({})
        controller.create_schedule(make_schedule_mock(intents))
        ha = MagicMock()
        ha.get_huawei_working_mode_options.return_value = []
        ha.get_huawei_working_mode.return_value = "time_of_use_luna2000"
        controller.write_schedule_to_hardware(ha, 0, [])
        ha.write_huawei_tou_periods.assert_called_once_with("")

    def test_write_schedule_raises_for_lg_resu_battery(
        self, controller: HuaweiController
    ) -> None:
        """LG RESU installs never expose 'time_of_use_luna2000' as an option
        (select.py removes it in StorageModeSelectEntity.__init__) —
        writing LUNA2000-format periods against one would be silently wrong."""
        intents = make_intents({2: "GRID_CHARGING"})
        controller.create_schedule(make_schedule_mock(intents))
        ha = MagicMock()
        ha.get_huawei_working_mode_options.return_value = [
            "adaptive",
            "fixed_charge_discharge",
            "maximise_self_consumption",
            "time_of_use_lg",
            "fully_fed_to_grid",
        ]
        with pytest.raises(SystemConfigurationError):
            controller.write_schedule_to_hardware(ha, 0, [])
        ha.write_huawei_tou_periods.assert_not_called()

    def test_write_schedule_proceeds_when_options_unavailable(
        self, controller: HuaweiController
    ) -> None:
        """An empty options list (entity unreadable) doesn't block the
        write — only a confirmed non-LUNA2000 option list does."""
        intents = make_intents({2: "GRID_CHARGING"})
        controller.create_schedule(make_schedule_mock(intents))
        ha = MagicMock()
        ha.get_huawei_working_mode_options.return_value = []
        ha.get_huawei_working_mode.return_value = "time_of_use_luna2000"
        controller.write_schedule_to_hardware(ha, 0, [])
        ha.write_huawei_tou_periods.assert_called_once()


class TestActiveTouIntervals:
    def test_active_tou_intervals_returns_all(self, controller: HuaweiController) -> None:
        intents = make_intents({2: "GRID_CHARGING"})
        controller.create_schedule(make_schedule_mock(intents))
        assert controller.active_tou_intervals == controller.tou_intervals


class TestCompareSchedules:
    def test_identical_periods_do_not_differ(
        self, controller: HuaweiController, battery_settings: BatterySettings
    ) -> None:
        intents = make_intents({2: "GRID_CHARGING"})
        controller.create_schedule(make_schedule_mock(intents))
        other = HuaweiController(battery_settings=battery_settings)
        other.create_schedule(make_schedule_mock(intents))
        differ, _ = controller.compare_schedules(other)
        assert differ is False

    def test_different_periods_differ(
        self, controller: HuaweiController, battery_settings: BatterySettings
    ) -> None:
        controller.create_schedule(make_schedule_mock(make_intents({2: "GRID_CHARGING"})))
        other = HuaweiController(battery_settings=battery_settings)
        other.create_schedule(make_schedule_mock(make_intents({18: "BATTERY_EXPORT"})))
        differ, _ = controller.compare_schedules(other)
        assert differ is True
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest core/bess/tests/unit/test_huawei_controller.py -v`
Expected: FAIL — `core.bess.huawei_controller` doesn't exist.

- [ ] **Step 3: Implement `HuaweiController`**

Create `core/bess/huawei_controller.py`:

```python
"""Huawei LUNA2000 inverter controller.

Huawei LUNA2000 batteries use a persistent, multi-period charge/discharge
list (huawei_solar.set_tou_periods, max 14 periods) gated behind the
battery's working-mode select entity. This is BESS's SM-Period-lists model
(like Growatt SPH), not SolaX's ephemeral per-period VPP commands — see
docs/superpowers/specs/2026-07-22-issue-120-huawei-inverter-platform-design.md
for the write-path and flash-wear rationale.

LUNA2000-only: LG RESU batteries use a price-bidding TOU format where the
inverter decides charge/discharge itself, incompatible with BESS owning the
optimization decision. Not built here.

Huawei Intent Mapping:
- GRID_CHARGING              → charge period (+)
- LOAD_SUPPORT/BATTERY_EXPORT → discharge period (-)
- SOLAR_STORAGE/SOLAR_EXPORT/IDLE → no period (self-consumption default)
"""

import logging
from datetime import datetime
from typing import ClassVar

from . import time_utils
from .dp_schedule import DPSchedule
from .exceptions import SystemConfigurationError
from .inverter_controller import InverterController
from .settings import BatterySettings

logger = logging.getLogger(__name__)

WORKING_MODE_TOU = "time_of_use_luna2000"

# "1234567" sets all seven day-slots via _parse_days_effective's
# `int(day) % 7` indexing (order-independent, presence-only) — verified
# against wlcrs/huawei_solar services.py. BESS always schedules every day
# the same way, so a fixed all-days string is sufficient; see open item #1
# in the design doc for live-hardware confirmation of this convention.
ALL_DAYS = "1234567"


class HuaweiController(InverterController):
    """Creates Huawei LUNA2000 inverter schedules from strategic intents.

    Writes a single combined charge/discharge period list (max 14 periods)
    via huawei_solar.set_tou_periods, gated behind the working-mode select.
    """

    supports_charge_rate_control: ClassVar[bool] = False
    discharge_rate_is_load_following: ClassVar[bool] = False

    MAX_TOU_PERIODS = 14

    CHARGE_INTENTS: ClassVar[frozenset[str]] = frozenset({"GRID_CHARGING"})
    DISCHARGE_INTENTS: ClassVar[frozenset[str]] = frozenset(
        {"LOAD_SUPPORT", "BATTERY_EXPORT"}
    )

    def __init__(self, battery_settings: BatterySettings) -> None:
        """Initialize the Huawei controller."""
        super().__init__(battery_settings)
        self._periods: list[dict] = []

    def _write_period_to_hardware(
        self,
        controller,
        grid_charge: bool,
        discharge_rate: int,
        block_passive_charging: bool = False,
    ) -> tuple[bool, str]:
        """No-op: Huawei deploys the full schedule atomically via set_tou_periods."""
        return True, ""

    @property
    def active_tou_intervals(self) -> list[dict]:
        """All TOU intervals are active — no per-slot hardware constraint."""
        return self.tou_intervals

    # ── Period grouping ───────────────────────────────────────────────────

    def _group_huawei_periods(self) -> list[dict]:
        """Group consecutive charge/discharge periods into flagged blocks."""
        if not self.strategic_intents:
            return []

        blocks: list[dict] = []
        current: dict | None = None

        for period, intent in enumerate(self.strategic_intents):
            if intent in self.CHARGE_INTENTS:
                flag = "+"
            elif intent in self.DISCHARGE_INTENTS:
                flag = "-"
            else:
                flag = None

            if flag is None:
                if current is not None:
                    blocks.append(current)
                    current = None
                continue

            if current is not None and current["flag"] == flag:
                current["end_period"] = period
            else:
                if current is not None:
                    blocks.append(current)
                current = {"start_period": period, "end_period": period, "flag": flag}

        if current is not None:
            blocks.append(current)

        return blocks

    def _enforce_period_limit(self, blocks: list[dict]) -> list[dict]:
        """Enforce MAX_TOU_PERIODS by dropping shortest blocks."""
        if len(blocks) <= self.MAX_TOU_PERIODS:
            return blocks

        logger.warning(
            "HUAWEI PERIOD LIMIT EXCEEDED: %d blocks, maximum is %d — dropping shortest",
            len(blocks),
            self.MAX_TOU_PERIODS,
        )

        def block_duration(b: dict) -> int:
            return b["end_period"] - b["start_period"] + 1

        sorted_by_duration = sorted(blocks, key=block_duration, reverse=True)
        kept = sorted_by_duration[: self.MAX_TOU_PERIODS]
        return sorted(kept, key=lambda b: b["start_period"])

    def _blocks_to_period_dicts(self, blocks: list[dict]) -> list[dict]:
        """Convert period blocks to time-string dicts with charge/discharge flag."""
        result = []
        for block in blocks:
            sh, sm = self._period_to_time(block["start_period"])
            eh, em = self._period_to_time(block["end_period"])

            if sh >= 24:
                continue  # Skip DST fall-back periods beyond 23:59
            if eh >= 24:
                eh, em = 23, 59
            else:
                em += 14

            result.append(
                {
                    "start_time": f"{sh:02d}:{sm:02d}",
                    "end_time": f"{eh:02d}:{em:02d}",
                    "flag": block["flag"],
                }
            )
        return result

    def _build_huawei_periods(self) -> None:
        """Build the combined charge/discharge period list from strategic intents."""
        blocks = self._group_huawei_periods()
        blocks = self._enforce_period_limit(blocks)
        self._periods = self._blocks_to_period_dicts(blocks)

        self.tou_intervals = []
        for idx, p in enumerate(self._periods):
            self.tou_intervals.append(
                {
                    "start_time": p["start_time"],
                    "end_time": p["end_time"],
                    "batt_mode": "battery_first" if p["flag"] == "+" else "grid_first",
                    "enabled": True,
                    "is_default": False,
                    "strategic_intent": (
                        "GRID_CHARGING" if p["flag"] == "+" else "LOAD_SUPPORT/BATTERY_EXPORT"
                    ),
                    "segment_id": idx + 1,
                }
            )

        logger.info("Huawei periods built: %d period(s)", len(self._periods))
        for p in self._periods:
            logger.info("  %s: %s-%s", p["flag"], p["start_time"], p["end_time"])

    def create_schedule(
        self,
        schedule: DPSchedule,
        current_period: int = 0,
        previous_tou_intervals: list[dict] | None = None,
    ) -> None:
        """Process DPSchedule with strategic intents into Huawei TOU periods."""
        logger.info("Creating Huawei schedule from strategic intents")

        self.strategic_intents = schedule.original_dp_results["strategic_intent"]
        self.current_schedule = schedule

        self._build_huawei_periods()

    # ── Hardware interface ────────────────────────────────────────────────

    def _periods_to_text(self) -> str:
        """Join periods into huawei_solar.set_tou_periods text format."""
        lines = [
            f"{p['start_time']}-{p['end_time']}/{ALL_DAYS}/{p['flag']}"
            for p in self._periods
        ]
        return "\n".join(lines)

    def write_schedule_to_hardware(
        self,
        controller,
        effective_period: int,
        current_tou: list,
    ) -> tuple[int, int]:
        """Write Huawei TOU periods to hardware.

        First confirms the connected battery is LUNA2000 (via the
        integration-exposed working-mode option list — see
        HomeAssistantAPIController.get_huawei_working_mode_options), then
        gates the write behind the working-mode select: sets it to
        time_of_use_luna2000 only when drifted, then writes the full
        period list (always a full rewrite — no differential update).

        Raises:
            SystemConfigurationError: If the connected battery does not
                expose 'time_of_use_luna2000' as a working-mode option
                (i.e. it's an LG RESU battery, not supported).
        """
        available_modes = controller.get_huawei_working_mode_options()
        if available_modes and WORKING_MODE_TOU not in available_modes:
            raise SystemConfigurationError(
                "Connected Huawei battery does not support "
                f"'{WORKING_MODE_TOU}' (available modes: {available_modes}). "
                "Only LUNA2000 batteries are supported — LG RESU is not."
            )

        writes = 0

        current_mode = controller.get_huawei_working_mode()
        if current_mode != WORKING_MODE_TOU:
            logger.info(
                "HUAWEI HARDWARE: working mode is %r, setting to %r",
                current_mode,
                WORKING_MODE_TOU,
            )
            try:
                controller.set_huawei_working_mode(WORKING_MODE_TOU)
                writes += 1
            except Exception as e:
                logger.error("FAILED: set_huawei_working_mode: %s", e)

        periods_text = self._periods_to_text()
        logger.info(
            "HUAWEI HARDWARE: Writing %d TOU period(s)", len(self._periods)
        )
        try:
            controller.write_huawei_tou_periods(periods_text)
            writes += 1
        except Exception as e:
            logger.error("FAILED: write_huawei_tou_periods: %s", e)

        return writes, 0

    def sync_soc_limits(self, controller) -> None:
        """Sync SOC limits from config to inverter hardware.

        Writes storage_charging_cutoff_capacity / storage_grid_charge_cutoff_state_of_charge
        directly via number.set_value — no read-then-compare, since the
        underlying HA entities already report their own state via the
        entity registry and a mismatched write is idempotent.
        """
        configured_max_soc = int(self.battery_settings.max_soc)
        configured_min_soc = int(self.battery_settings.min_soc)

        controller.set_charge_stop_soc(configured_max_soc)
        controller.set_discharge_stop_soc(configured_min_soc)
        logger.info(
            "Huawei SOC limits synced: charge_stop=%d%%, discharge_stop=%d%%",
            configured_max_soc,
            configured_min_soc,
        )

    def initialize_hardware(self, controller) -> None:
        self.sync_soc_limits(controller)

    def read_and_initialize_from_hardware(self, controller, current_hour: int) -> None:
        """Huawei has no readback API for TOU periods in this Phase 1 pass.

        huawei_solar exposes no read_tou_periods service — the periods are
        only visible via the (undocumented) coordinator state, not a public
        service call. Leaves strategic_intents empty; the next
        create_schedule() call populates it, matching the pattern used
        when hardware state genuinely can't be read back.
        """
        logger.info(
            "Huawei: no TOU readback available — starting with empty schedule"
        )

    # ── Schedule comparison ───────────────────────────────────────────────

    def compare_schedules(
        self, other_schedule: "HuaweiController", from_period: int = 0
    ) -> tuple[bool, str]:
        """Compare Huawei period lists with another schedule controller."""
        current = self._periods
        new = other_schedule._periods

        if len(current) != len(new):
            logger.info(
                "DECISION: Huawei period count differs — current=%d new=%d",
                len(current),
                len(new),
            )
            return True, "Huawei period count differs"

        for pa, pb in zip(current, new, strict=False):
            if (
                pa.get("start_time") != pb.get("start_time")
                or pa.get("end_time") != pb.get("end_time")
                or pa.get("flag") != pb.get("flag")
            ):
                logger.info(
                    "DECISION: Huawei periods differ — current=%s new=%s",
                    current,
                    new,
                )
                return True, "Huawei periods differ"

        logger.info("DECISION: Huawei schedules match")
        return False, ""

    # ── TOU display ──────────────────────────────────────────────────────

    def get_daily_TOU_settings(self) -> list[dict]:
        return list(self.tou_intervals)

    def get_all_tou_segments(self) -> list[dict]:
        if not self.tou_intervals:
            return [
                {
                    "segment_id": 0,
                    "start_time": "00:00",
                    "end_time": "23:59",
                    "batt_mode": "load_first",
                    "enabled": False,
                    "is_default": True,
                }
            ]
        return list(self.tou_intervals)

    def log_current_TOU_schedule(self, header: str = "") -> None:
        if header:
            logger.info(header)
        if not self._periods:
            logger.info("Huawei: No active TOU periods")
            return
        logger.info(" -= Huawei TOU Schedule =-")
        for i, p in enumerate(self._periods, 1):
            logger.info(
                "  Period %d: %s-%s (%s)",
                i,
                p["start_time"],
                p["end_time"],
                "charge" if p["flag"] == "+" else "discharge",
            )

    def log_detailed_schedule(self, header: str = "") -> None:
        if header:
            logger.info(header)
        if not self.strategic_intents:
            logger.info("Huawei: No schedule data available")
            return

        now = time_utils.now()
        current_period = now.hour * 4 + now.minute // 15

        lines = [
            "\n╔═══════════════╦══════════════════╦═══════════════╗",
            "║  Time Period  ║ Strategic Intent ║ Huawei Action ║",
            "╠═══════════════╬══════════════════╬═══════════════╣",
        ]

        num_periods = len(self.strategic_intents)
        period = 0
        while period < num_periods:
            intent = self.strategic_intents[period]
            run_start = period
            while (
                period + 1 < num_periods
                and self.strategic_intents[period + 1] == intent
            ):
                period += 1
            run_end = period

            sh, sm = run_start // 4, (run_start % 4) * 15
            eh, em = run_end // 4, (run_end % 4) * 15
            em += 14

            time_range = f"{sh:02d}:{sm:02d}-{eh:02d}:{em:02d}"
            marker = "*" if run_start <= current_period <= run_end else " "

            if intent in self.CHARGE_INTENTS:
                action = "charge"
            elif intent in self.DISCHARGE_INTENTS:
                action = "discharge"
            else:
                action = "idle"

            lines.append(f"║{marker}{time_range:13} ║ {intent:16} ║ {action:13} ║")
            period += 1

        lines.append("╚═══════════════╩══════════════════╩═══════════════╝")
        lines.append("* indicates current period")
        logger.info("\n".join(lines))

    # ── Health check ─────────────────────────────────────────────────────

    def check_health(self, controller) -> list:
        """Check Huawei battery control capabilities via the working-mode entity."""
        try:
            mode = controller.get_huawei_working_mode()
            if mode is not None:
                check = {
                    "component": "Huawei working mode (select)",
                    "status": "OK",
                    "message": f"Connected — current mode={mode}",
                }
                overall_status = "OK"
            else:
                check = {
                    "component": "Huawei working mode (select)",
                    "status": "ERROR",
                    "message": "Entity returned no state — check sensor config",
                }
                overall_status = "ERROR"
        except Exception as e:
            check = {
                "component": "Huawei working mode (select)",
                "status": "ERROR",
                "message": f"Read failed: {e}",
            }
            overall_status = "ERROR"

        return [
            {
                "name": "Battery Control (Huawei LUNA2000)",
                "description": "Controls Huawei battery TOU schedule via set_tou_periods",
                "required": True,
                "status": overall_status,
                "checks": [check],
                "last_run": datetime.now().isoformat(),
            }
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest core/bess/tests/unit/test_huawei_controller.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Run full fast suite**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add core/bess/huawei_controller.py core/bess/tests/unit/test_huawei_controller.py
git commit -m "feat: add HuaweiController for LUNA2000 TOU period scheduling"
```

---

### Task 4: `BatterySystemManager` wiring

**Files:**
- Modify: `core/bess/battery_system_manager.py`
- Test: `core/bess/tests/unit/test_battery_system_manager.py` (add cases; check the file exists and its fixture pattern before writing — mirror the existing `solax_modbus_native` case)

**Interfaces:**
- Consumes: Task 3's `HuaweiController`.
- Produces: `"huawei_solar_luna2000"` in `VALID_PLATFORMS`; `_create_inverter_controller()` returns `HuaweiController` for that platform.

- [ ] **Step 1: Add platform to `VALID_PLATFORMS` and `_INVERTER_TYPE_TO_PLATFORM`**

In `core/bess/battery_system_manager.py`, modify (around line 221-227):

```python
    VALID_PLATFORMS: ClassVar[set[str]] = {
        "growatt_server_min",
        "growatt_server_sph",
        "solax_modbus_growatt_min",
        "solax_modbus_growatt_sph",
        "solax_modbus_native",
        "huawei_solar_luna2000",
    }
```

And (around line 229-238):

```python
    _INVERTER_TYPE_TO_PLATFORM: ClassVar[dict[str, str]] = {
        "growatt_server_min": "growatt_server_min",
        "solax_modbus_growatt_min": "solax_modbus_growatt_min",
        "solax_modbus_growatt_sph": "solax_modbus_growatt_sph",
        "growatt_server_sph": "growatt_server_sph",
        "solax_modbus_native": "solax_modbus_native",
        "huawei_solar_luna2000": "huawei_solar_luna2000",
        # Legacy values stored in growatt.inverter_type
        "MIN": "growatt_server_min",
        "SPH": "growatt_server_sph",
    }
```

- [ ] **Step 2: Add import and `_create_inverter_controller` branch**

Add the import near the other controller imports at the top of the file:

```python
from .huawei_controller import HuaweiController
```

Modify `_create_inverter_controller()` (around line 297-317):

```python
        if self.inverter_platform == "growatt_server_sph":
            return GrowattSphController(battery_settings=self.battery_settings)
        if self.inverter_platform == "solax_modbus_native":
            return SolaxController(battery_settings=self.battery_settings)
        if self.inverter_platform == "huawei_solar_luna2000":
            return HuaweiController(battery_settings=self.battery_settings)
        if self.inverter_platform in (
            "solax_modbus_growatt_min",
            "solax_modbus_growatt_sph",
        ):
            return SolaxModbusGrowattController(
                battery_settings=self.battery_settings,
                control_mode=self.control_mode,
            )
        return GrowattMinController(battery_settings=self.battery_settings)
```

- [ ] **Step 3: Write a test verifying the wiring**

In `core/bess/tests/unit/test_battery_system_manager.py`, find the existing test that asserts `_create_inverter_controller()` returns a `SolaxController` for `"solax_modbus_native"` and add an analogous case:

```python
def test_create_inverter_controller_huawei(self):
    manager = make_manager(inverter_platform="huawei_solar_luna2000")
    controller = manager._create_inverter_controller()
    assert isinstance(controller, HuaweiController)
```

(Use whatever the file's existing `manager`/settings fixture helper is named — match its exact signature rather than inventing `make_manager`; read the file's existing SolaX-equivalent test first and copy its setup exactly.)

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest core/bess/tests/unit/test_battery_system_manager.py -v`
Expected: PASS.

- [ ] **Step 5: Run full fast suite**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add core/bess/battery_system_manager.py core/bess/tests/unit/test_battery_system_manager.py
git commit -m "feat: wire HuaweiController into BatterySystemManager platform factory"
```

---

### Task 5: `settings_store.py` VALID_PLATFORMS

**Files:**
- Modify: `core/bess/settings_store.py`
- Test: check for an existing `test_settings_store.py` covering `VALID_PLATFORMS`; add a case if one exists, otherwise this task's correctness is covered by Task 4/6's integration tests.

**Interfaces:**
- Produces: `"huawei_solar_luna2000"` in both `VALID_PLATFORMS` tuples.

- [ ] **Step 1: Update both duplicated tuples**

In `core/bess/settings_store.py`, update **both** occurrences (lines 36-42 and 65-71 — verified duplicate, not backend/settings_store.py per the skill doc's stale path):

```python
VALID_PLATFORMS = (
    "growatt_server_min",
    "growatt_server_sph",
    "solax_modbus_growatt_min",
    "solax_modbus_growatt_sph",
    "solax_modbus_native",
    "huawei_solar_luna2000",
)
```

Apply this identical change at both line 36 and line 65.

- [ ] **Step 2: Verify no other module reads a stale copy**

Run: `grep -n "VALID_PLATFORMS" core/bess/settings_store.py`
Expected: both tuples now include `"huawei_solar_luna2000"`.

- [ ] **Step 3: Run full fast suite**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add core/bess/settings_store.py
git commit -m "feat: add huawei_solar_luna2000 to settings_store VALID_PLATFORMS"
```

---

### Task 6: `debug_data_exporter.py` entity capture

**Files:**
- Modify: `core/bess/debug_data_exporter.py`
- Test: check for an existing test asserting `_ENTITY_REGISTRY_DOMAINS` coverage (e.g. a parametrized test over known domains); add a `"huawei_solar"` case if one exists.

**Interfaces:**
- Produces: `huawei_solar` entities included in debug export bundles.

- [ ] **Step 1: Add domain and keyword**

In `core/bess/debug_data_exporter.py`, modify `_WS_TARGET_DOMAINS` (around line 94-96):

```python
_WS_TARGET_DOMAINS = frozenset(
    {"nordpool", "growatt", "growatt_server", "solax_modbus", "solax", "huawei_solar", "entsoe"}
)
```

Modify `_ENTITY_REGISTRY_DOMAINS` (around line 99-109):

```python
_ENTITY_REGISTRY_DOMAINS = frozenset(
    {
        "growatt_server",
        "solax_modbus",
        "solax",
        "huawei_solar",
        "nordpool",
        "octopus_energy",
        "entsoe",
        "solcast_solar",
    }
)
```

Modify `_ENTITY_REGISTRY_KEYWORDS` (around line 114-121):

```python
_ENTITY_REGISTRY_KEYWORDS = (
    "growatt",
    "solax",
    "huawei",
    "nordpool",
    "octopus",
    "entsoe",
    "solcast",
)
```

And `_CONFIG_ENTRY_SUMMARY_FIELDS`-style dict near line 85-91 (the one keyed by domain for config-entry field allowlisting) — add:

```python
    "huawei_solar": frozenset({"name"}),
```

- [ ] **Step 2: Run full fast suite**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS, no regressions (this task is additive-only, no new assertions required unless an existing domain-coverage test needs updating — check output for any parametrized test failures and add the new domain to its parameter list if so).

- [ ] **Step 3: Commit**

```bash
git add core/bess/debug_data_exporter.py
git commit -m "feat: capture huawei_solar entities in debug export bundles"
```

---

### Task 7: Backend API — `huaweiDeviceId` end-to-end

**Files:**
- Modify: `backend/api_dataclasses.py`
- Modify: `backend/api.py`
- Test: `backend/tests/test_inverter_api.py` (mirror the existing `growattDeviceId` round-trip test)

**Interfaces:**
- Produces: `SetupCompletePayload.huaweiDeviceId: str | None` (or whichever payload dataclass holds `growattDeviceId` — confirm the exact class name at `backend/api_dataclasses.py:1100` before editing), persisted to `huawei.device_id` in settings, assigned to `ha_controller.huawei_device_id` on save.

- [ ] **Step 1: Read the exact payload dataclass and surrounding wiring**

Run: `grep -n -B5 "growattDeviceId: str | None = None" backend/api_dataclasses.py` to get the exact class name, then `sed -n '3380,3410p;3500,3550p' backend/api.py` to see the full read/persist/assign flow around the four call sites found during planning (lines 3392, 3398, 3506-3508, 3543-3544).

- [ ] **Step 2: Add the field**

In `backend/api_dataclasses.py`, add next to `growattDeviceId: str | None = None` (around line 1100):

```python
    huaweiDeviceId: str | None = None
```

- [ ] **Step 3: Thread it through `backend/api.py`**

At each of the four Growatt-device-id call sites identified in Step 1, add a parallel Huawei branch. Concretely:

- Where `growatt_device_id=payload.growattDeviceId` is passed to the `HomeAssistantAPIController`/manager constructor (~line 3398), add `huawei_device_id=payload.huaweiDeviceId,`.
- Where `growatt_section["device_id"] = payload.growattDeviceId` persists to settings (~line 3506-3508), add an equivalent `huawei_section["device_id"] = payload.huaweiDeviceId` block (create/reuse a `"huawei"` settings section the same way the `"growatt"` section is created — check `SettingsStore.OWNED_SECTIONS` in `core/bess/settings_store.py:23-33` and add `"huawei"` there too if a new top-level section is needed, following the existing `"growatt"` entry's shape).
- Where `bess_controller.ha_controller.growatt_device_id = payload.growattDeviceId` assigns at runtime (~line 3543-3544), add `bess_controller.ha_controller.huawei_device_id = payload.huaweiDeviceId`.
- Where `integrations["growatt_device_id"]` is read back for the discover response (~line 3329), add `"huawei_device_id": integrations["huawei_device_id"],` (sourced from Task 2's `discover_integrations()` result).

- [ ] **Step 4: Write a round-trip test**

In `backend/tests/test_inverter_api.py`, find the existing `growattDeviceId` setup-complete round-trip test and add an analogous `huaweiDeviceId` case following its exact structure (payload in, settings/controller assignment asserted out).

- [ ] **Step 5: Run tests**

Run: `.venv/bin/pytest backend/tests/test_inverter_api.py -v`
Expected: PASS.

- [ ] **Step 6: Run full fast suite**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS, no regressions.

- [ ] **Step 7: Commit**

```bash
git add backend/api_dataclasses.py backend/api.py backend/tests/test_inverter_api.py core/bess/settings_store.py
git commit -m "feat: thread huaweiDeviceId through setup-complete API and settings"
```

---

### Task 8: Source-derived discovery regression fixture (Phase 1 substitute for the wizard E2E)

**Files:**
- Modify: `core/bess/tests/unit/test_scenario_discovery.py`

**Interfaces:**
- Consumes: `_huawei_registry()` fixture from Task 2.

- [ ] **Step 1: Add a Huawei scenario case**

Find the existing `solax_modbus_native` case in `test_scenario_discovery.py` (a full `discover_integrations()`-level test, not just `_detect_platforms`) and add an analogous case using Task 2's `_huawei_registry()` fixture, asserting `result["huawei_found"] is True` and `"huawei_solar_luna2000" in result["detected_inverter_platforms"]`. Match the existing case's exact mocking pattern (likely mocks `_ws_query` and `_fetch_all_states`) rather than inventing a new one.

- [ ] **Step 2: Run to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_scenario_discovery.py -v`
Expected: PASS.

- [ ] **Step 3: Run full fast suite**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add core/bess/tests/unit/test_scenario_discovery.py
git commit -m "test: add Huawei end-to-end discovery scenario"
```

---

### Task 9: Frontend — `sensorDefinitions.ts`

**Files:**
- Modify: `frontend/src/lib/sensorDefinitions.ts`

**Interfaces:**
- Produces: `'huawei_solar_luna2000'` as a valid `PlatformId`, with its own `IntegrationDef` sensor groups.

- [ ] **Step 1: Add to `INVERTER_INTEGRATION_IDS` and `VALID_PLATFORMS`**

Modify (around line 24-41):

```typescript
export const INVERTER_INTEGRATION_IDS: Record<string, string> = {
  growatt_server_min: 'growatt_server_min',
  growatt_server_sph: 'growatt_server_sph',
  solax_modbus_growatt_min: 'solax_modbus_growatt_min',
  solax_modbus_growatt_sph: 'solax_modbus_growatt_sph',
  solax_modbus_native: 'solax_modbus_native',
  huawei_solar_luna2000: 'huawei_solar_luna2000',
};

export const VALID_PLATFORMS = [
  'growatt_server_min',
  'growatt_server_sph',
  'solax_modbus_growatt_min',
  'solax_modbus_growatt_sph',
  'solax_modbus_native',
  'huawei_solar_luna2000',
] as const;
```

- [ ] **Step 2: Add to `PerPlatformSensors` interface and `emptyPerPlatformSensors`**

Modify (around line 50-59):

```typescript
export interface PerPlatformSensors {
  [key: string]: string | Record<string, string>;
  platform: string;
  growatt_server_min: Record<string, string>;
  growatt_server_sph: Record<string, string>;
  solax_modbus_growatt_min: Record<string, string>;
  solax_modbus_growatt_sph: Record<string, string>;
  solax_modbus_native: Record<string, string>;
  huawei_solar_luna2000: Record<string, string>;
  shared: Record<string, string>;
}
```

Modify (around line 68-78):

```typescript
export function emptyPerPlatformSensors(platform = ''): PerPlatformSensors {
  return {
    platform,
    growatt_server_min: {},
    growatt_server_sph: {},
    solax_modbus_growatt_min: {},
    solax_modbus_growatt_sph: {},
    solax_modbus_native: {},
    huawei_solar_luna2000: {},
    shared: {},
  };
}
```

- [ ] **Step 3: Add `IntegrationDef` entry**

Add to `INTEGRATIONS` (around line 174-189, after the `solax_modbus_native` entry — or wherever in the array; order doesn't matter functionally):

```typescript
  {
    id: 'huawei_solar_luna2000',
    name: 'Huawei LUNA2000',
    required: true,
    description: 'Huawei LUNA2000 battery controlled via the huawei_solar integration (local Modbus)',
    sensorGroups: [
      {
        name: 'Battery Monitoring',
        sensors: [
          { key: 'battery_soc', label: 'State of Capacity', required: true },
          { key: 'battery_charge_power', label: 'Charge/Discharge Power', required: true },
        ],
      },
      {
        name: 'Battery Control',
        sensors: [
          { key: 'huawei_working_mode', label: 'Working Mode (select)', required: true },
          { key: 'battery_charging_power_rate', label: 'Maximum Charging Power', required: false },
          { key: 'battery_discharging_power_rate', label: 'Maximum Discharging Power', required: false },
          { key: 'battery_charge_stop_soc', label: 'Charging Cutoff Capacity', required: true },
          { key: 'battery_discharge_stop_soc', label: 'Grid-Charge Cutoff SOC', required: true },
          { key: 'grid_charge', label: 'Charge From Grid Function', required: false },
        ],
      },
      {
        name: 'Power Monitoring',
        sensors: [
          { key: 'local_load_power', label: 'Inverter Active Power', required: false },
        ],
      },
    ],
  },
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: No new errors from `sensorDefinitions.ts` (other files consuming `PerPlatformSensors`/`VALID_PLATFORMS` are fixed in Tasks 10-11; some errors here are expected until those land — proceed to Task 10 immediately).

- [ ] **Step 5: Commit** (after Task 10 makes the build green — see Task 10 Step 6)

---

### Task 10: Frontend — `SensorConfigSection.tsx` three-way platform tabs

**Files:**
- Modify: `frontend/src/components/settings/SensorConfigSection.tsx`

**Interfaces:**
- Consumes: Task 9's `huawei_solar_luna2000` `IntegrationDef`.
- Produces: `DiscoveryResult.huaweiFound: boolean`; a third top-level "Huawei" tab alongside "Growatt Cloud" / "SolaX Modbus".

- [ ] **Step 1: Add `huaweiFound` to `DiscoveryResult`**

Modify the interface (around line 24-53):

```typescript
export interface DiscoveryResult {
  growattFound: boolean;
  deviceSn: string | null;
  growattDeviceId: string | null;
  solaxFound: boolean;
  solaxHasGrowattTou: boolean;
  solaxHasGrowattGen3: boolean;
  huaweiFound: boolean;
  huaweiDeviceId: string | null;
  nordpoolFound: boolean;
  ...
```

- [ ] **Step 2: Add detection branch in `isIntegrationFound`**

Modify (around line 71-93):

```typescript
  if (id === 'solax_modbus_native') return discovery.solaxFound;
  if (id === 'huawei_solar_luna2000') return discovery.huaweiFound;
```

- [ ] **Step 3: Add to `INVERTER_IDS`**

Modify (around line 152):

```typescript
const INVERTER_IDS = new Set(['growatt_server_min', 'growatt_server_sph', 'solax_modbus_growatt_min', 'solax_modbus_growatt_sph', 'solax_modbus_native', 'huawei_solar_luna2000']);
```

- [ ] **Step 4: Add third top-level tab**

This is a real structural change — the existing component hardcodes a two-way `'cloud' | 'modbus'` integration split. Modify as follows.

Change the `handleIntegrationChange` signature and `isCloudActive`/`isModbusActive` derivation (around line 220-239):

```typescript
  const isCloudActive = inverterForm.inverterPlatform === 'growatt_server_min' || inverterForm.inverterPlatform === 'growatt_server_sph';
  const isModbusActive = inverterForm.inverterPlatform === 'solax_modbus_growatt_min'
    || inverterForm.inverterPlatform === 'solax_modbus_growatt_sph'
    || inverterForm.inverterPlatform === 'solax_modbus_native';
  const isHuaweiActive = inverterForm.inverterPlatform === 'huawei_solar_luna2000';

  const huaweiDetected = wizardMode
    ? discovery.huaweiFound
    : Boolean((sensors.huawei_solar_luna2000 ?? {})['huawei_working_mode']);

  const handleIntegrationChange = (integration: 'cloud' | 'modbus' | 'huawei') => {
    if (integration === 'cloud') {
      const newType = 'growatt_server_min';
      onInverterChange({ ...inverterForm, inverterPlatform: newType });
      onChange({ ...sensors, platform: newType });
    } else if (integration === 'modbus') {
      const newType = growattModbusDetected ? 'solax_modbus_growatt_min'
        : growattModbusGen3Detected ? 'solax_modbus_growatt_sph'
        : 'solax_modbus_native';
      onInverterChange({ ...inverterForm, inverterPlatform: newType });
      onChange({ ...sensors, platform: newType });
    } else {
      const newType = 'huawei_solar_luna2000';
      onInverterChange({ ...inverterForm, inverterPlatform: newType });
      onChange({ ...sensors, platform: newType });
    }
  };
```

Modify the `activeTab` derivation and `Tabs`/`TabsList` block (around line 267-299) to add a third trigger:

```typescript
        {(() => {
          const cloudDetected = growattDetected;
          const modbusDetected = growattModbusDetected || growattModbusGen3Detected || solaxDetected;
          const activeTab = isCloudActive ? 'cloud' : isHuaweiActive ? 'huawei' : 'modbus';

          return (
            <Tabs value={activeTab} onValueChange={(v) => handleIntegrationChange(v as 'cloud' | 'modbus' | 'huawei')}>
              <TabsList className="bg-gray-100 dark:bg-gray-700/60">
                <TabsTrigger
                  value="cloud"
                  disabled={wizardMode && !cloudDetected}
                  className="data-[state=active]:bg-white dark:data-[state=active]:bg-gray-600 dark:text-gray-300 dark:data-[state=active]:text-white"
                >
                  <span className="flex items-center gap-1.5">
                    {wizardMode && (
                      <span className={`h-2 w-2 rounded-full flex-shrink-0 ${cloudDetected ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-500'}`} />
                    )}
                    Growatt Cloud
                  </span>
                </TabsTrigger>
                <TabsTrigger
                  value="modbus"
                  disabled={wizardMode && !modbusDetected}
                  className="data-[state=active]:bg-white dark:data-[state=active]:bg-gray-600 dark:text-gray-300 dark:data-[state=active]:text-white"
                >
                  <span className="flex items-center gap-1.5">
                    {wizardMode && (
                      <span className={`h-2 w-2 rounded-full flex-shrink-0 ${modbusDetected ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-500'}`} />
                    )}
                    SolaX Modbus
                  </span>
                </TabsTrigger>
                <TabsTrigger
                  value="huawei"
                  disabled={wizardMode && !huaweiDetected}
                  className="data-[state=active]:bg-white dark:data-[state=active]:bg-gray-600 dark:text-gray-300 dark:data-[state=active]:text-white"
                >
                  <span className="flex items-center gap-1.5">
                    {wizardMode && (
                      <span className={`h-2 w-2 rounded-full flex-shrink-0 ${huaweiDetected ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-500'}`} />
                    )}
                    Huawei
                  </span>
                </TabsTrigger>
              </TabsList>
```

Add a third `TabsContent` after the existing `modbus` one (after its closing `</TabsContent>`, matching the `cloud` tab's single-option + device-ID-field shape since Huawei currently has exactly one supported variant):

```typescript
              <TabsContent value="huawei">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="px-3 py-1 rounded-full text-xs font-medium border bg-blue-50 dark:bg-blue-900/30 border-blue-300 dark:border-blue-600 text-blue-700 dark:text-blue-300">
                    LUNA2000
                  </span>
                  <span className="text-[9px] text-orange-500 dark:text-orange-400 font-medium">experimental</span>
                </div>

                <label className="block mt-3">
                  <span className="text-xs font-medium text-gray-500 dark:text-gray-400">Device ID</span>
                  <input
                    type="text"
                    value={inverterForm.deviceId}
                    placeholder="Huawei battery device ID"
                    onChange={e => onInverterChange({ ...inverterForm, deviceId: e.target.value })}
                    className="mt-0.5 block w-full sm:w-72 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 px-3 py-1.5 text-sm font-mono text-gray-800 dark:text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-400"
                  />
                </label>
              </TabsContent>
```

- [ ] **Step 5: Verify `sharedIntegrations` filter still excludes the new inverter tab**

The existing filter (around line 245-249) already excludes anything in `INVERTER_IDS`, which Step 3 extended — no further change needed here; just confirm by inspection that `huawei_solar_luna2000` won't double-render as a "shared" integration.

- [ ] **Step 6: Typecheck and build**

Run: `cd frontend && npx tsc --noEmit && npm run lint:fix`
Expected: No errors.

- [ ] **Step 7: Commit both Task 9 and Task 10**

```bash
git add frontend/src/lib/sensorDefinitions.ts frontend/src/components/settings/SensorConfigSection.tsx
git commit -m "feat: add Huawei LUNA2000 platform to sensor config UI"
```

---

### Task 11: Frontend — `SetupWizardPage.tsx` device-ID autofill

**Files:**
- Modify: `frontend/src/pages/SetupWizardPage.tsx`

**Interfaces:**
- Consumes: Task 7's `huaweiDeviceId` API field, Task 10's `DiscoveryResult.huaweiDeviceId`.

- [ ] **Step 1: Autofill `deviceId` from `huaweiDeviceId`**

Modify the discovery-response handler (around line 158-159, right after the existing `growattDeviceId` autofill):

```typescript
      if (d.growattDeviceId) {
        setInverterForm(f => ({ ...f, deviceId: d.growattDeviceId! }));
      }
      if (d.huaweiDeviceId) {
        setInverterForm(f => ({ ...f, deviceId: d.huaweiDeviceId! }));
      }
```

- [ ] **Step 2: Send `huaweiDeviceId` in the setup-complete payload**

Modify the payload construction (around line 307, next to the existing `growattDeviceId: inverterForm.deviceId || discovery.growattDeviceId,`):

```typescript
        growattDeviceId: inverterForm.deviceId || discovery.growattDeviceId,
        huaweiDeviceId: inverterForm.deviceId || discovery.huaweiDeviceId,
```

(Both fields are sent; the backend only persists the one matching the selected platform — verify this is true by re-reading Task 7's Step 3 backend wiring, and if the backend instead persists whichever is non-null unconditionally, gate this on `inverterForm.inverterPlatform === 'huawei_solar_luna2000'` here instead to avoid cross-writing a stale Growatt id.)

- [ ] **Step 3: Typecheck and build**

Run: `cd frontend && npx tsc --noEmit && npm run lint:fix && npm run build`
Expected: No errors, build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/SetupWizardPage.tsx
git commit -m "feat: autofill and persist Huawei battery device ID in setup wizard"
```

---

### Task 12: Docs

**Files:**
- Modify: `docs/INVERTER_PLATFORMS.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify/Create: a maturity memory entry per existing convention in `docs/agents/memory/`

**Interfaces:** None (documentation only).

- [ ] **Step 1: Update `INVERTER_PLATFORMS.md`**

Add a row to the "Supported Platforms" table and the "five platforms" coordinate table (mirror the existing `solax_modbus_native` row's format exactly):

```markdown
| Huawei LUNA2000 (Local) | Huawei LUNA2000 | [huawei_solar](https://github.com/wlcrs/huawei_solar) | Local Modbus | TOU period-list writes | — |
```

```markdown
| `huawei_solar_luna2000` | TX-Vendor-service | SM-Period-lists | `HuaweiController` | `_HUAWEI_BATTERY_MARKER_SUFFIX` (`storage_working_mode_settings`) | `HUAWEI_SUFFIX_MAP` |
```

Update the "Worked examples for new inverters" Huawei bullet to reflect the shipped design (persistent `set_tou_periods`, not the originally-sketched `forcible_charge` ephemeral path) — replace the existing bullet with a short "How BESS Controls" section mirroring the Growatt SPH section's structure: schedule-write mechanism (`huawei_solar.set_tou_periods` + working-mode select gate), a Required Entities table from Task 1's `HUAWEI_SUFFIX_MAP`, and an Auto-Detection entry (marker suffix).

- [ ] **Step 2: Update `README.md`**

Add Huawei LUNA2000 to the supported-platforms list, marked experimental (mirror the existing SolaX/GEN3 experimental-marker convention).

- [ ] **Step 3: Update `CHANGELOG.md`**

Add an `## [Unreleased]` heading at the top of the file (it doesn't currently exist — check first in case a prior PR already added it since this plan was written) with an `### Added` entry:

```markdown
## [Unreleased]

### Added

- **Huawei LUNA2000 inverter platform (experimental)** — new `HuaweiController` writes a persistent charge/discharge TOU period list via `huawei_solar.set_tou_periods`, gated behind the battery's working-mode select entity. Detection via the `huawei_solar` HA integration's entity registry. LUNA2000 batteries only; LG RESU is not supported. Not yet real-world tested — see [docs/superpowers/specs/2026-07-22-issue-120-huawei-inverter-platform-design.md](docs/superpowers/specs/2026-07-22-issue-120-huawei-inverter-platform-design.md). ([#120](https://github.com/johanzander/bess-manager/issues/120))
```

- [ ] **Step 4: Documentation check (per `implement-issue`/release conventions)**

Grep `docs/agents/bess-knowledge.md` and `docs/SOFTWARE_DESIGN.md` for any mention of inverter platform lists or control mechanisms that this change touches:

Run: `grep -n -i "growatt\|solax\|inverter platform" docs/agents/bess-knowledge.md docs/SOFTWARE_DESIGN.md`

If either references a closed/enumerated platform list, add Huawei to it. If neither mentions platform enumeration (likely, since these files describe algorithm behavior, not platform wiring), note in the PR description that this was checked and found not applicable.

- [ ] **Step 5: Add maturity memory entry**

Following the existing convention referenced by `project_platform_maturity.md` in the auto-memory system (not a repo file — a `~/.claude` memory file), update it to record Huawei LUNA2000 as experimental/not real-world tested, alongside the existing GEN3/SolaX VPP entries. This is a memory-system update, not a repo commit.

- [ ] **Step 6: Commit**

```bash
git add docs/INVERTER_PLATFORMS.md README.md CHANGELOG.md
git commit -m "docs: document Huawei LUNA2000 inverter platform"
```

---

## Final verification

- [ ] Run the full fast suite: `.venv/bin/pytest -m "not slow"` — expect PASS.
- [ ] Run the slow suite: `.venv/bin/pytest -m slow` — expect PASS, no regressions in other platforms' discovery/controller tests.
- [ ] Run `./scripts/quality-check.sh` — expect PASS (black/ruff clean).
- [ ] Run `cd frontend && npx tsc --noEmit && npm run lint:fix && npm run build` — expect PASS.
- [ ] Manually exercise the setup wizard against Task 8's fixture data (or a local mock) to confirm the "Huawei" tab renders, auto-selects when detected, and the Device ID field populates from discovery — this is the one thing automated tests won't catch given Task 11's E2E gap; do this before opening a PR even though the formal Playwright scenario is deferred.
- [ ] Confirm `docs/superpowers/specs/2026-07-22-issue-120-huawei-inverter-platform-design.md`'s open items are either resolved by this implementation or explicitly still open in the PR description (the `days_effective` digit convention and out-of-period default behavior remain unverifiable until the reporter's real hardware confirms them — call this out explicitly, don't claim more certainty than exists).
