"""Unit tests for auto-detection hints in HomeAssistantAPIController.

Tests cover:
- _hints_from_nordpool_area: currency and VAT derivation from Nordpool area
- Inverter type detection (MIN vs SPH) from discovered entity states
- Phase count derivation in the discover endpoint (tested at the controller level)
"""

from core.bess.ha_api_controller import HomeAssistantAPIController

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_controller() -> HomeAssistantAPIController:
    """Create a minimal controller instance without a real HA connection."""
    return HomeAssistantAPIController.__new__(HomeAssistantAPIController)


def _state(entity_id: str) -> dict:
    return {"entity_id": entity_id, "state": "0", "attributes": {}}


# ---------------------------------------------------------------------------
# _hints_from_nordpool_area
# ---------------------------------------------------------------------------


class TestHintsFromNordpoolArea:
    def setup_method(self):
        self.ctrl = _make_controller()

    def test_se_area_returns_sek_25vat(self):
        hints = self.ctrl._hints_from_nordpool_area("SE4")
        assert hints == {"currency": "SEK", "vat_multiplier": 1.25}

    def test_se1_also_works(self):
        hints = self.ctrl._hints_from_nordpool_area("SE1")
        assert hints["currency"] == "SEK"
        assert hints["vat_multiplier"] == 1.25

    def test_no_area_returns_nok_25vat(self):
        hints = self.ctrl._hints_from_nordpool_area("NO1")
        assert hints == {"currency": "NOK", "vat_multiplier": 1.25}

    def test_dk_area_returns_dkk_25vat(self):
        hints = self.ctrl._hints_from_nordpool_area("DK1")
        assert hints == {"currency": "DKK", "vat_multiplier": 1.25}

    def test_fi_area_returns_eur_24vat(self):
        hints = self.ctrl._hints_from_nordpool_area("FI")
        assert hints == {"currency": "EUR", "vat_multiplier": 1.24}

    def test_ee_area_returns_eur_22vat(self):
        hints = self.ctrl._hints_from_nordpool_area("EE")
        assert hints == {"currency": "EUR", "vat_multiplier": 1.22}

    def test_gb_area_returns_gbp_no_vat(self):
        hints = self.ctrl._hints_from_nordpool_area("GB")
        assert hints == {"currency": "GBP", "vat_multiplier": 1.0}

    def test_unknown_area_returns_empty(self):
        hints = self.ctrl._hints_from_nordpool_area("XX99")
        assert hints == {}

    def test_none_area_returns_empty(self):
        hints = self.ctrl._hints_from_nordpool_area(None)
        assert hints == {}

    def test_empty_string_returns_empty(self):
        hints = self.ctrl._hints_from_nordpool_area("")
        assert hints == {}

    def test_case_insensitive_prefix(self):
        # Area codes come back uppercase from discovery but test lowercase too
        hints = self.ctrl._hints_from_nordpool_area("se4")
        # prefix is uppercased inside the method
        assert hints.get("currency") == "SEK"


# ---------------------------------------------------------------------------
# Inverter type detection (MIN vs SPH)
# The detection logic lives inside discover_integrations which calls HA, so we
# test the sub-logic directly: MIN is detected when a switch.<sn>_ac_charge
# entity exists; SPH when it doesn't.
# ---------------------------------------------------------------------------


class TestInverterTypeDetection:
    """Tests for the MIN/SPH heuristic in discover_ha_metadata.

    Detection uses the entity registry: MIN creates a switch entity with
    unique_id ending in '-ac_charge' on platform 'growatt_server'.  SPH does
    not create this entity (SPH controls charging via service calls only).
    """

    def _run_detection(self, entity_registry: list[dict]) -> str | None:
        """Mirror the detection logic in discover_ha_metadata."""
        has_ac_charge = any(
            entry.get("platform") == "growatt_server"
            and str(entry.get("unique_id", "")).endswith("-ac_charge")
            for entry in entity_registry
        )
        return "MIN" if has_ac_charge else "SPH"

    def test_min_detected_when_ac_charge_present(self):
        registry = [
            {
                "entity_id": "sensor.abc123_soc",
                "platform": "growatt_server",
                "unique_id": "abc123-tlx_statement_of_charge",
            },
            {
                "entity_id": "switch.abc123_ac_charge",
                "platform": "growatt_server",
                "unique_id": "abc123-ac_charge",
            },
        ]
        assert self._run_detection(registry) == "MIN"

    def test_sph_detected_when_ac_charge_absent(self):
        registry = [
            {
                "entity_id": "sensor.egm2h4l0g0_soc",
                "platform": "growatt_server",
                "unique_id": "EGM2H4L0G0-mix_statement_of_charge",
            },
            {
                "entity_id": "sensor.egm2h4l0g0_battery_charge",
                "platform": "growatt_server",
                "unique_id": "EGM2H4L0G0-mix_battery_charge",
            },
        ]
        assert self._run_detection(registry) == "SPH"

    def test_ac_charge_from_different_platform_does_not_match(self):
        registry = [
            {
                "entity_id": "switch.other_ac_charge",
                "platform": "solax_modbus",
                "unique_id": "other-ac_charge",
            },
        ]
        assert self._run_detection(registry) == "SPH"

    def test_partial_suffix_does_not_match(self):
        # unique_id "abc123-no_ac_charge_enabled" ends differently
        registry = [
            {
                "entity_id": "switch.abc123_charge",
                "platform": "growatt_server",
                "unique_id": "abc123-no_ac_charge_enabled",
            },
        ]
        assert self._run_detection(registry) == "SPH"

    def test_empty_registry_gives_sph(self):
        assert self._run_detection([]) == "SPH"


# ---------------------------------------------------------------------------
# Phase count detection helper
# ---------------------------------------------------------------------------


class TestPhaseCountDetection:
    """Tests for the phase count derived from discovered current sensors."""

    def _phase_count(self, sensors: dict) -> int | None:
        """Mirror the api.py detected_phase_count calculation."""
        count = sum(
            1 for k in ("current_l1", "current_l2", "current_l3") if k in sensors
        )
        return count or None

    def test_three_phases_detected(self):
        sensors = {
            "current_l1": "sensor.l1",
            "current_l2": "sensor.l2",
            "current_l3": "sensor.l3",
        }
        assert self._phase_count(sensors) == 3

    def test_single_phase_detected(self):
        sensors = {"current_l1": "sensor.l1"}
        assert self._phase_count(sensors) == 1

    def test_no_current_sensors_returns_none(self):
        sensors = {"battery_soc": "sensor.soc"}
        assert self._phase_count(sensors) is None

    def test_partial_phases_counted(self):
        sensors = {"current_l1": "sensor.l1", "current_l2": "sensor.l2"}
        assert self._phase_count(sensors) == 2


# ---------------------------------------------------------------------------
# discover_ha_metadata — nordpool area extraction from entity registry
# ---------------------------------------------------------------------------


class TestDiscoverHaMetadataNordpoolArea:
    """Area is extracted from nordpool device identifiers in the device registry.

    The official HA nordpool integration creates a device with identifiers
    [["nordpool", "SE3"]].  The area is read from there, keyed by the
    config_entry_id.
    """

    def setup_method(self):
        self.ctrl = _make_controller()

    def _ws_stub(
        self,
        config_entries: list[dict],
        devices: list[dict] | None = None,
    ):
        """Return a _ws_query replacement with config entries and devices."""
        # _ws_query returns [config_entries, devices, services, entity_registry]
        return lambda cmds: [
            config_entries,
            devices or [],
            {},
            [],
        ]

    def _nordpool_device(self, area: str, config_entry_id: str = "abc"):
        return {
            "id": "dev-nordpool",
            "name": f"Nord Pool {area}",
            "manufacturer": "Nord Pool",
            "identifiers": [["nordpool", area]],
            "config_entries": [config_entry_id],
        }

    def test_area_extracted_from_device_identifiers(self, monkeypatch):
        """Area is parsed from the nordpool device identifiers."""
        entry = {"domain": "nordpool", "state": "loaded", "entry_id": "abc"}
        devices = [self._nordpool_device("SE3")]
        monkeypatch.setattr(self.ctrl, "_ws_query", self._ws_stub([entry], devices))
        result = self.ctrl.discover_ha_metadata(None)
        assert result["nordpool_area"] == "SE3"

    def test_area_is_uppercased(self, monkeypatch):
        """Area codes are normalised to upper case."""
        entry = {"domain": "nordpool", "state": "loaded", "entry_id": "abc"}
        devices = [self._nordpool_device("se3")]
        monkeypatch.setattr(self.ctrl, "_ws_query", self._ws_stub([entry], devices))
        result = self.ctrl.discover_ha_metadata(None)
        assert result["nordpool_area"] == "SE3"

    def test_non_matching_config_entry_ignored(self, monkeypatch):
        """Devices for a different config entry are not used."""
        entry = {"domain": "nordpool", "state": "loaded", "entry_id": "abc"}
        devices = [self._nordpool_device("SE3", config_entry_id="other")]
        monkeypatch.setattr(self.ctrl, "_ws_query", self._ws_stub([entry], devices))
        result = self.ctrl.discover_ha_metadata(None)
        assert result["nordpool_area"] is None

    def test_no_nordpool_devices_returns_none(self, monkeypatch):
        """nordpool_area is None when no matching devices exist."""
        entry = {"domain": "nordpool", "state": "loaded", "entry_id": "abc"}
        monkeypatch.setattr(self.ctrl, "_ws_query", self._ws_stub([entry], []))
        result = self.ctrl.discover_ha_metadata(None)
        assert result["nordpool_area"] is None

    def test_no_nordpool_config_entry_returns_none(self, monkeypatch):
        """nordpool_area is None when there is no loaded nordpool config entry."""
        monkeypatch.setattr(self.ctrl, "_ws_query", self._ws_stub([]))
        result = self.ctrl.discover_ha_metadata(None)
        assert result["nordpool_area"] is None

    def test_unloaded_entry_is_ignored(self, monkeypatch):
        """Config entries that are not in 'loaded' state are skipped."""
        entry = {"domain": "nordpool", "state": "not_loaded", "entry_id": "abc"}
        devices = [self._nordpool_device("SE3")]
        monkeypatch.setattr(self.ctrl, "_ws_query", self._ws_stub([entry], devices))
        result = self.ctrl.discover_ha_metadata(None)
        assert result["nordpool_area"] is None
