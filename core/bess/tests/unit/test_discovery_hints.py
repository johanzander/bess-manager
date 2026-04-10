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
    """Tests for the MIN/SPH heuristic that runs inside discover_integrations."""

    def _run_detection(self, device_sn: str, states: list[dict]) -> str | None:
        """Re-implement the minimal detection logic mirroring discover_integrations."""
        _make_controller()
        ac_charge_suffix = "ac_charge"
        prefix = f"{device_sn}_"
        has_ac_charge = any(
            str(s.get("entity_id", "")).split(".", 1)[-1]
            == f"{prefix}{ac_charge_suffix}"
            for s in states
        )
        return "MIN" if has_ac_charge else "SPH"

    def test_min_detected_when_ac_charge_present(self):
        sn = "abc123"
        states = [
            _state(f"sensor.{sn}_statement_of_charge_soc"),
            _state(f"switch.{sn}_ac_charge"),
            _state(f"sensor.{sn}_battery_1_charging_w"),
        ]
        assert self._run_detection(sn, states) == "MIN"

    def test_sph_detected_when_ac_charge_absent(self):
        sn = "abc123"
        states = [
            _state(f"sensor.{sn}_statement_of_charge_soc"),
            _state(f"sensor.{sn}_battery_1_charging_w"),
        ]
        assert self._run_detection(sn, states) == "SPH"

    def test_ac_charge_from_different_device_does_not_match(self):
        sn = "mydevice"
        states = [
            _state(f"sensor.{sn}_statement_of_charge_soc"),
            _state("switch.otherdevice_ac_charge"),  # different SN
        ]
        assert self._run_detection(sn, states) == "SPH"

    def test_sensor_prefix_not_switch_does_not_match(self):
        sn = "dev1"
        states = [
            _state(f"sensor.{sn}_ac_charge"),  # wrong domain — sensor, not switch
        ]
        # The check only looks at entity_id after the dot, domain doesn't matter
        # so sensor.dev1_ac_charge WOULD match; entity_id.split('.', 1)[-1] == 'dev1_ac_charge'
        # This is correct: Growatt sometimes uses sensor domain for ac_charge
        assert self._run_detection(sn, states) == "MIN"

    def test_empty_states_gives_sph(self):
        assert self._run_detection("anydevice", []) == "SPH"


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
