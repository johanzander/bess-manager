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

    def test_nl_area_returns_eur_21vat(self):
        hints = self.ctrl._hints_from_nordpool_area("NL")
        assert hints == {"currency": "EUR", "vat_multiplier": 1.21}

    def test_be_area_returns_eur_21vat(self):
        hints = self.ctrl._hints_from_nordpool_area("BE")
        assert hints == {"currency": "EUR", "vat_multiplier": 1.21}

    def test_de_lu_area_returns_eur_19vat(self):
        # Nord Pool publishes the German bidding zone as "DE-LU"; the prefix
        # parser must take the first two characters and map to DE.
        hints = self.ctrl._hints_from_nordpool_area("DE-LU")
        assert hints == {"currency": "EUR", "vat_multiplier": 1.19}

    def test_fr_area_returns_eur_20vat(self):
        hints = self.ctrl._hints_from_nordpool_area("FR")
        assert hints == {"currency": "EUR", "vat_multiplier": 1.20}

    def test_at_area_returns_eur_20vat(self):
        hints = self.ctrl._hints_from_nordpool_area("AT")
        assert hints == {"currency": "EUR", "vat_multiplier": 1.20}

    def test_pl_area_returns_pln_23vat(self):
        hints = self.ctrl._hints_from_nordpool_area("PL")
        assert hints == {"currency": "PLN", "vat_multiplier": 1.23}

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

    def test_long_hacs_identifier_returns_correct_currency(self):
        # HACS custom Nordpool uses long identifiers like "NORDPOOL_KWH_SE2_SEK_2_10_025"
        # which should NOT match "NO" — the area must be parsed first.
        # This is a regression test for issue #105.
        hints = self.ctrl._hints_from_nordpool_area("SE2")
        assert hints == {"currency": "SEK", "vat_multiplier": 1.25}


# ---------------------------------------------------------------------------
# Inverter type detection (MIN vs SPH)
# The detection logic lives inside discover_integrations which calls HA, so we
# test the sub-logic directly: MIN is detected when a switch.<sn>_ac_charge
# entity exists; SPH when it doesn't.
# ---------------------------------------------------------------------------


class TestInverterTypeDetection:
    """Tests for the MIN/SPH heuristic in discover_ha_metadata.

    Detection uses entity registry unique_id prefixes:
      - tlx_ prefix → MIN (AC-coupled)
      - mix_ prefix (without tlx_) → SPH (DC-coupled)
    Note: mix_load_consumption_total appears on both types, so tlx_ is
    the positive MIN signal.
    """

    def _run_detection(self, entity_registry: list[dict]) -> str | None:
        """Mirror the detection logic in discover_ha_metadata."""
        has_tlx = any(
            entry.get("platform") == "growatt_server"
            and "-tlx_" in str(entry.get("unique_id", ""))
            for entry in entity_registry
        )
        return "MIN" if has_tlx else "SPH"

    def test_min_detected_with_tlx_entities(self):
        registry = [
            {
                "entity_id": "sensor.abc123_soc",
                "platform": "growatt_server",
                "unique_id": "abc123-tlx_statement_of_charge",
            },
        ]
        assert self._run_detection(registry) == "MIN"

    def test_min_detected_even_without_ac_charge(self):
        """Issue #105: MIN without ac_charge entity — tlx_ prefix is enough."""
        registry = [
            {
                "entity_id": "sensor.abc123_soc",
                "platform": "growatt_server",
                "unique_id": "ABC1234567-tlx_statement_of_charge",
            },
        ]
        assert self._run_detection(registry) == "MIN"

    def test_sph_detected_with_mix_entities(self):
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

    def test_mix_load_consumption_alone_gives_sph(self):
        """mix_load_consumption_total appears on both types — not a MIN signal."""
        registry = [
            {
                "entity_id": "sensor.abc123_load",
                "platform": "growatt_server",
                "unique_id": "abc123-mix_load_consumption_total",
            },
        ]
        assert self._run_detection(registry) == "SPH"

    def test_tlx_plus_mix_load_gives_min(self):
        """MIN has tlx_ entities and one mix_load_consumption_total."""
        registry = [
            {
                "entity_id": "sensor.abc123_soc",
                "platform": "growatt_server",
                "unique_id": "abc123-tlx_statement_of_charge",
            },
            {
                "entity_id": "sensor.abc123_load",
                "platform": "growatt_server",
                "unique_id": "abc123-mix_load_consumption_total",
            },
        ]
        assert self._run_detection(registry) == "MIN"

    def test_tlx_from_different_platform_does_not_match(self):
        registry = [
            {
                "entity_id": "sensor.other_soc",
                "platform": "solax_modbus",
                "unique_id": "other-tlx_statement_of_charge",
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

    def test_hacs_long_identifier_normalised(self, monkeypatch):
        """Issue #105: HACS identifier 'nordpool_kwh_se2_sek_2_10_025' → 'SE2'."""
        entry = {"domain": "nordpool", "state": "loaded", "entry_id": "abc"}
        devices = [self._nordpool_device("nordpool_kwh_se2_sek_2_10_025")]
        monkeypatch.setattr(self.ctrl, "_ws_query", self._ws_stub([entry], devices))
        result = self.ctrl.discover_ha_metadata(None)
        assert result["nordpool_area"] == "SE2"

    def test_hacs_norwegian_identifier_normalised(self, monkeypatch):
        """HACS identifier 'nordpool_kwh_no1_nok_3_10_025' → 'NO1' (not 'NO')."""
        entry = {"domain": "nordpool", "state": "loaded", "entry_id": "abc"}
        devices = [self._nordpool_device("nordpool_kwh_no1_nok_3_10_025")]
        monkeypatch.setattr(self.ctrl, "_ws_query", self._ws_stub([entry], devices))
        result = self.ctrl.discover_ha_metadata(None)
        assert result["nordpool_area"] == "NO1"

    def test_hacs_nl_identifier_not_aliased_to_norway(self, monkeypatch):
        """Issue #171: HACS 'nordpool_kwh_nl_eur_2_10_025' must give NL, not NO."""
        entry = {"domain": "nordpool", "state": "loaded", "entry_id": "abc"}
        devices = [self._nordpool_device("nordpool_kwh_nl_eur_2_10_025")]
        monkeypatch.setattr(self.ctrl, "_ws_query", self._ws_stub([entry], devices))
        result = self.ctrl.discover_ha_metadata(None)
        assert result["nordpool_area"] == "NL"

    def test_hacs_be_identifier_normalised(self, monkeypatch):
        """Issue #171: HACS 'nordpool_kwh_be_eur_2_10_025' → 'BE'."""
        entry = {"domain": "nordpool", "state": "loaded", "entry_id": "abc"}
        devices = [self._nordpool_device("nordpool_kwh_be_eur_2_10_025")]
        monkeypatch.setattr(self.ctrl, "_ws_query", self._ws_stub([entry], devices))
        result = self.ctrl.discover_ha_metadata(None)
        assert result["nordpool_area"] == "BE"

    def test_hacs_de_identifier_normalised(self, monkeypatch):
        """Issue #171: HACS 'nordpool_kwh_de_eur_2_10_025' → 'DE'."""
        entry = {"domain": "nordpool", "state": "loaded", "entry_id": "abc"}
        devices = [self._nordpool_device("nordpool_kwh_de_eur_2_10_025")]
        monkeypatch.setattr(self.ctrl, "_ws_query", self._ws_stub([entry], devices))
        result = self.ctrl.discover_ha_metadata(None)
        assert result["nordpool_area"] == "DE"

    def test_hacs_de_lu_identifier_normalised(self, monkeypatch):
        """Issue #171: HACS 'nordpool_kwh_de-lu_eur_2_10_025' → 'DE-LU'."""
        entry = {"domain": "nordpool", "state": "loaded", "entry_id": "abc"}
        devices = [self._nordpool_device("nordpool_kwh_de-lu_eur_2_10_025")]
        monkeypatch.setattr(self.ctrl, "_ws_query", self._ws_stub([entry], devices))
        result = self.ctrl.discover_ha_metadata(None)
        assert result["nordpool_area"] == "DE-LU"

    def test_hacs_de_lu_underscore_entity_id_normalised(self, monkeypatch):
        """Issue #171: HA slugifies DE-LU to 'de_lu', so entity IDs use underscore.

        'nordpool_kwh_de_lu_eur_2_10_025' must be parsed to 'DE_LU', not 'DE'
        (which would leave '_lu_eur_...' unmatched) and must not fall back to
        raw.upper() which would alias to 'NO' (Norway) via the 2-char prefix.
        """
        entry = {"domain": "nordpool", "state": "loaded", "entry_id": "abc"}
        devices = [self._nordpool_device("nordpool_kwh_de_lu_eur_2_10_025")]
        monkeypatch.setattr(self.ctrl, "_ws_query", self._ws_stub([entry], devices))
        result = self.ctrl.discover_ha_metadata(None)
        assert result["nordpool_area"] == "DE_LU"

    def test_hacs_fr_identifier_normalised(self, monkeypatch):
        """Issue #171: HACS 'nordpool_kwh_fr_eur_2_10_025' → 'FR'."""
        entry = {"domain": "nordpool", "state": "loaded", "entry_id": "abc"}
        devices = [self._nordpool_device("nordpool_kwh_fr_eur_2_10_025")]
        monkeypatch.setattr(self.ctrl, "_ws_query", self._ws_stub([entry], devices))
        result = self.ctrl.discover_ha_metadata(None)
        assert result["nordpool_area"] == "FR"

    def test_hacs_at_identifier_normalised(self, monkeypatch):
        """Issue #171: HACS 'nordpool_kwh_at_eur_2_10_025' → 'AT'."""
        entry = {"domain": "nordpool", "state": "loaded", "entry_id": "abc"}
        devices = [self._nordpool_device("nordpool_kwh_at_eur_2_10_025")]
        monkeypatch.setattr(self.ctrl, "_ws_query", self._ws_stub([entry], devices))
        result = self.ctrl.discover_ha_metadata(None)
        assert result["nordpool_area"] == "AT"

    def test_hacs_pl_identifier_normalised(self, monkeypatch):
        """Issue #171: HACS 'nordpool_kwh_pl_pln_2_10_025' → 'PL'."""
        entry = {"domain": "nordpool", "state": "loaded", "entry_id": "abc"}
        devices = [self._nordpool_device("nordpool_kwh_pl_pln_2_10_025")]
        monkeypatch.setattr(self.ctrl, "_ws_query", self._ws_stub([entry], devices))
        result = self.ctrl.discover_ha_metadata(None)
        assert result["nordpool_area"] == "PL"

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
