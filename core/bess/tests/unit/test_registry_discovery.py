"""Unit tests for registry-based sensor discovery.

Tests cover:
- _map_registry_entities: unique_id-based suffix matching
- discover_sensors_from_registry: single suffix map per platform
- Robustness against user entity renaming (unique_id is immutable)
- Derived lifetime sensor fallbacks (GEN3/GEN4)
"""

from typing import ClassVar
from unittest.mock import patch

from core.bess.ha_api_controller import HomeAssistantAPIController


def _make_controller() -> HomeAssistantAPIController:
    """Create a minimal controller instance without a real HA connection."""
    return HomeAssistantAPIController.__new__(HomeAssistantAPIController)


def _entity(entity_id: str, platform: str, unique_id: str) -> dict:
    """Build a minimal entity registry entry."""
    return {
        "entity_id": entity_id,
        "platform": platform,
        "unique_id": unique_id,
    }


# ---------------------------------------------------------------------------
# Growatt entity registry: growatt_server platform
# ---------------------------------------------------------------------------


def _growatt_registry() -> list[dict]:
    """Entity registry for a typical Growatt MIN inverter via growatt_server."""
    sn = "rkm0d7n04x"
    return [
        _entity(
            f"sensor.{sn}_state_of_charge_soc",
            "growatt_server",
            f"{sn}_state_of_charge_soc",
        ),
        _entity(
            f"sensor.{sn}_battery_1_charging_w",
            "growatt_server",
            f"{sn}_battery_1_charging_w",
        ),
        _entity(
            f"sensor.{sn}_battery_1_discharging_w",
            "growatt_server",
            f"{sn}_battery_1_discharging_w",
        ),
        _entity(f"sensor.{sn}_import_power", "growatt_server", f"{sn}_import_power"),
        _entity(f"sensor.{sn}_export_power", "growatt_server", f"{sn}_export_power"),
        _entity(
            f"sensor.{sn}_local_load_power", "growatt_server", f"{sn}_local_load_power"
        ),
        _entity(
            f"sensor.{sn}_internal_wattage", "growatt_server", f"{sn}_internal_wattage"
        ),
        _entity(
            f"switch.{sn}_charge_from_grid", "growatt_server", f"{sn}_charge_from_grid"
        ),
        _entity(
            f"number.{sn}_battery_charge_power_limit",
            "growatt_server",
            f"{sn}_battery_charge_power_limit",
        ),
        _entity(
            f"number.{sn}_battery_discharge_power_limit",
            "growatt_server",
            f"{sn}_battery_discharge_power_limit",
        ),
        _entity(
            f"number.{sn}_battery_charge_soc_limit",
            "growatt_server",
            f"{sn}_battery_charge_soc_limit",
        ),
        # Off-grid discharge-stop-SOC: real installs always have this
        # entity too, but it must NOT be matched — see #270.
        _entity(
            f"number.{sn}_battery_discharge_soc_limit",
            "growatt_server",
            f"{sn}_battery_discharge_soc_limit",
        ),
        _entity(
            f"number.{sn}_battery_discharge_soc_limit_on_grid",
            "growatt_server",
            f"{sn}_battery_discharge_soc_limit_on_grid",
        ),
        _entity(
            f"sensor.{sn}_lifetime_total_all_batteries_charged",
            "growatt_server",
            f"{sn}_lifetime_total_all_batteries_charged",
        ),
        _entity(
            f"sensor.{sn}_lifetime_total_all_batteries_discharged",
            "growatt_server",
            f"{sn}_lifetime_total_all_batteries_discharged",
        ),
        _entity(
            f"sensor.{sn}_lifetime_total_solar_energy",
            "growatt_server",
            f"{sn}_lifetime_total_solar_energy",
        ),
        _entity(
            f"sensor.{sn}_lifetime_total_export_to_grid",
            "growatt_server",
            f"{sn}_lifetime_total_export_to_grid",
        ),
        _entity(
            f"sensor.{sn}_lifetime_import_from_grid",
            "growatt_server",
            f"{sn}_lifetime_import_from_grid",
        ),
        _entity(
            f"sensor.{sn}_lifetime_total_load_consumption",
            "growatt_server",
            f"{sn}_lifetime_total_load_consumption",
        ),
        _entity(
            f"sensor.{sn}_lifetime_system_production",
            "growatt_server",
            f"{sn}_lifetime_system_production",
        ),
        _entity(
            f"sensor.{sn}_lifetime_self_consumption",
            "growatt_server",
            f"{sn}_lifetime_self_consumption",
        ),
        # Unrelated integration — should be ignored
        _entity("sensor.nordpool_kwh_se4_sek", "nordpool", "nordpool_kwh_se4_sek"),
    ]


# ---------------------------------------------------------------------------
# Growatt SPH entity registry: growatt_server platform (DC-coupled, mix_ keys)
# Based on real entity registry from issue #60 (GraemeDBlue, EGM2H4L0G0).
# SPH has NO number/switch entities — battery control is via service calls.
# unique_id format: "{SN}-{sensor_key}" (hyphen separator, mix_ prefix).
# ---------------------------------------------------------------------------


def _growatt_sph_registry() -> list[dict]:
    """Entity registry for a Growatt SPH inverter via growatt_server."""
    sn = "egm2h4l0g0"
    return [
        # ── SOC ──────────────────────────────────────────────────────
        _entity(
            f"sensor.{sn}_state_of_charge",
            "growatt_server",
            f"{sn}-mix_statement_of_charge",
        ),
        # ── Real-time power sensors ──────────────────────────────────
        _entity(
            f"sensor.{sn}_battery_charging",
            "growatt_server",
            f"{sn}-mix_battery_charge",
        ),
        _entity(
            f"sensor.{sn}_battery_discharging_w",
            "growatt_server",
            f"{sn}-mix_battery_discharge_w",
        ),
        _entity(
            f"sensor.{sn}_import_from_grid",
            "growatt_server",
            f"{sn}-mix_import_from_grid",
        ),
        _entity(
            f"sensor.{sn}_export_to_grid",
            "growatt_server",
            f"{sn}-mix_export_to_grid",
        ),
        _entity(
            f"sensor.{sn}_all_pv_wattage",
            "growatt_server",
            f"{sn}-mix_wattage_pv_all",
        ),
        # ── Lifetime energy sensors ──────────────────────────────────
        _entity(
            f"sensor.{sn}_lifetime_battery_charged",
            "growatt_server",
            f"{sn}-mix_battery_charge_lifetime",
        ),
        _entity(
            f"sensor.{sn}_lifetime_battery_discharged",
            "growatt_server",
            f"{sn}-mix_battery_discharge_lifetime",
        ),
        _entity(
            f"sensor.{sn}_lifetime_solar_energy",
            "growatt_server",
            f"{sn}-mix_solar_generation_lifetime",
        ),
        _entity(
            f"sensor.{sn}_lifetime_export_to_grid",
            "growatt_server",
            f"{sn}-mix_export_to_grid_lifetime",
        ),
        _entity(
            f"sensor.{sn}_lifetime_import_from_grid",
            "growatt_server",
            f"{sn}-mix_import_from_grid_total",
        ),
        _entity(
            f"sensor.{sn}_lifetime_load_consumption",
            "growatt_server",
            f"{sn}-mix_load_consumption_lifetime",
        ),
        # Unrelated integration — should be ignored
        _entity("sensor.nordpool_kwh_se4_sek", "nordpool", "nordpool_kwh_se4_sek"),
    ]


# ---------------------------------------------------------------------------
# SolaX entity registry: native SolaX inverter via solax_modbus
# ---------------------------------------------------------------------------


def _solax_native_registry() -> list[dict]:
    """Entity registry for a native SolaX inverter via solax_modbus."""
    return [
        _entity(
            "sensor.solax_battery_capacity", "solax_modbus", "solax_battery_capacity"
        ),
        _entity(
            "sensor.solax_battery_power_charge",
            "solax_modbus",
            "solax_battery_power_charge",
        ),
        _entity(
            "sensor.solax_battery_power_discharge",
            "solax_modbus",
            "solax_battery_power_discharge",
        ),
        _entity("sensor.solax_measured_power", "solax_modbus", "solax_measured_power"),
        _entity("sensor.solax_grid_export", "solax_modbus", "solax_grid_export"),
        _entity("sensor.solax_pv_power_1", "solax_modbus", "solax_pv_power_1"),
        _entity("sensor.solax_house_load", "solax_modbus", "solax_house_load"),
        _entity(
            "select.solax_remotecontrol_power_control",
            "solax_modbus",
            "solax_remotecontrol_power_control",
        ),
        _entity(
            "number.solax_remotecontrol_active_power",
            "solax_modbus",
            "solax_remotecontrol_active_power",
        ),
        _entity(
            "number.solax_remotecontrol_autorepeat_duration",
            "solax_modbus",
            "solax_remotecontrol_autorepeat_duration",
        ),
        _entity(
            "button.solax_remotecontrol_trigger",
            "solax_modbus",
            "solax_remotecontrol_trigger",
        ),
        # Off-grid/general minimum capacity: real installs always have this
        # entity too, but it must NOT be matched — see #270.
        _entity(
            "number.solax_battery_minimum_capacity",
            "solax_modbus",
            "solax_battery_minimum_capacity",
        ),
        _entity(
            "number.solax_battery_minimum_capacity_gridtied",
            "solax_modbus",
            "solax_battery_minimum_capacity_gridtied",
        ),
    ]


# ---------------------------------------------------------------------------
# SolaX entity registry: Growatt inverter connected via solax_modbus
#
# solax_modbus creates entities with its own naming regardless of inverter
# brand (e.g. battery_soc, total_forward_power).  unique_ids use the
# solax_ prefix.  Entity IDs may be renamed by the user.
# ---------------------------------------------------------------------------


def _solax_growatt_registry() -> list[dict]:
    """Entity registry for a Growatt inverter connected via solax_modbus.

    unique_ids use solax_modbus naming: solax_<suffix>.
    Entity IDs may differ from unique_ids if the user renamed the device.
    """
    return [
        # SOC
        _entity(
            "sensor.growatt_inverter_solax_battery_soc",
            "solax_modbus",
            "solax_battery_soc",
        ),
        # Battery power
        _entity(
            "sensor.growatt_inverter_solax_battery_charge_power",
            "solax_modbus",
            "solax_battery_charge_power",
        ),
        _entity(
            "sensor.growatt_inverter_solax_battery_discharge_power",
            "solax_modbus",
            "solax_battery_discharge_power",
        ),
        # Grid power
        _entity(
            "sensor.growatt_inverter_solax_total_forward_power",
            "solax_modbus",
            "solax_total_forward_power",
        ),
        _entity(
            "sensor.growatt_inverter_solax_total_reverse_power",
            "solax_modbus",
            "solax_total_reverse_power",
        ),
        # Load power
        _entity(
            "sensor.growatt_inverter_solax_total_load_power",
            "solax_modbus",
            "solax_total_load_power",
        ),
        # Solar
        _entity(
            "sensor.growatt_inverter_solax_pv_power_total",
            "solax_modbus",
            "solax_pv_power_total",
        ),
        # Lifetime energy
        _entity(
            "sensor.growatt_inverter_solax_total_battery_input_energy",
            "solax_modbus",
            "solax_total_battery_input_energy",
        ),
        _entity(
            "sensor.growatt_inverter_solax_total_battery_output_energy",
            "solax_modbus",
            "solax_total_battery_output_energy",
        ),
        _entity(
            "sensor.growatt_inverter_solax_total_solar_energy",
            "solax_modbus",
            "solax_total_solar_energy",
        ),
        _entity(
            "sensor.growatt_inverter_solax_total_grid_import",
            "solax_modbus",
            "solax_total_grid_import",
        ),
        _entity(
            "sensor.growatt_inverter_solax_total_grid_export",
            "solax_modbus",
            "solax_total_grid_export",
        ),
        _entity(
            "sensor.growatt_inverter_solax_total_yield",
            "solax_modbus",
            "solax_total_yield",
        ),
        # EMS control entities (Growatt inverter via solax_modbus)
        _entity(
            "number.growatt_inverter_solax_ems_charging_rate",
            "solax_modbus",
            "solax_ems_charging_rate",
        ),
        _entity(
            "number.growatt_inverter_solax_ems_discharging_rate",
            "solax_modbus",
            "solax_ems_discharging_rate",
        ),
        _entity(
            "number.growatt_inverter_solax_ems_charging_stop_soc",
            "solax_modbus",
            "solax_ems_charging_stop_soc",
        ),
        # Off-grid discharge-stop-SOC: real installs always have this
        # descriptor too, but it must NOT be matched — see #270.
        _entity(
            "number.growatt_inverter_solax_ems_discharging_stop_soc",
            "solax_modbus",
            "solax_ems_discharging_stop_soc",
        ),
        _entity(
            "number.growatt_inverter_solax_ems_discharging_stop_soc_on_grid",
            "solax_modbus",
            "solax_ems_discharging_stop_soc_on_grid",
        ),
        _entity(
            "switch.growatt_inverter_solax_charger_switch",
            "solax_modbus",
            "solax_charger_switch",
        ),
    ]


def _solax_growatt_tou_registry() -> list[dict]:
    """Entity registry for a Growatt inverter via solax_modbus with TOU time slots.

    Extends the base Growatt-via-solax entities with TOU time slot entities,
    which are the definitive marker for the solax_modbus_growatt_min platform (GEN4).
    """
    base = _solax_growatt_registry()
    tou_entities = []
    for slot in range(1, 10):
        for suffix in ("enabled", "begin", "end", "mode"):
            tou_entities.append(
                _entity(
                    f"select.growatt_inverter_solax_time_{slot}_{suffix}",
                    "solax_modbus",
                    f"solax_time_{slot}_{suffix}",
                )
            )
        tou_entities.append(
            _entity(
                f"button.growatt_inverter_solax_time_{slot}_update",
                "solax_modbus",
                f"solax_time_{slot}_update",
            )
        )
    return base + tou_entities


def _solax_growatt_gen3_registry() -> list[dict]:
    """Entity registry for a GEN3 Growatt (MIX/SPA/SPH) via solax_modbus.

    Contains the GEN3 marker entity (load_first_battery_minimum_soc) and
    GEN3-specific EMS entities instead of GEN4 numbered TOU slots.
    """
    return [
        # Monitoring sensors (same suffixes as GEN4)
        _entity(
            "sensor.growatt_sph_solax_battery_soc",
            "solax_modbus",
            "solax_battery_soc",
        ),
        _entity(
            "sensor.growatt_sph_solax_battery_charge_power",
            "solax_modbus",
            "solax_battery_charge_power",
        ),
        _entity(
            "sensor.growatt_sph_solax_battery_discharge_power",
            "solax_modbus",
            "solax_battery_discharge_power",
        ),
        _entity(
            "sensor.growatt_sph_solax_ac_power_to_user",
            "solax_modbus",
            "solax_ac_power_to_user",
        ),
        _entity(
            "sensor.growatt_sph_solax_ac_power_to_grid",
            "solax_modbus",
            "solax_ac_power_to_grid",
        ),
        _entity(
            "sensor.growatt_sph_solax_pv_power_total",
            "solax_modbus",
            "solax_pv_power_total",
        ),
        _entity(
            "sensor.growatt_sph_solax_total_load_power",
            "solax_modbus",
            "solax_total_load_power",
        ),
        # Lifetime energy (GEN3 has total_load, not total_yield)
        _entity(
            "sensor.growatt_sph_solax_total_battery_input_energy",
            "solax_modbus",
            "solax_total_battery_input_energy",
        ),
        _entity(
            "sensor.growatt_sph_solax_total_battery_output_energy",
            "solax_modbus",
            "solax_total_battery_output_energy",
        ),
        _entity(
            "sensor.growatt_sph_solax_total_solar_energy",
            "solax_modbus",
            "solax_total_solar_energy",
        ),
        _entity(
            "sensor.growatt_sph_solax_total_grid_import",
            "solax_modbus",
            "solax_total_grid_import",
        ),
        _entity(
            "sensor.growatt_sph_solax_total_grid_export",
            "solax_modbus",
            "solax_total_grid_export",
        ),
        _entity(
            "sensor.growatt_sph_solax_total_load",
            "solax_modbus",
            "solax_total_load",
        ),
        # GEN3 EMS control entities
        _entity(
            "number.growatt_sph_solax_battery_first_charge_rate",
            "solax_modbus",
            "solax_battery_first_charge_rate",
        ),
        _entity(
            "number.growatt_sph_solax_grid_first_discharge_rate",
            "solax_modbus",
            "solax_grid_first_discharge_rate",
        ),
        _entity(
            "number.growatt_sph_solax_battery_first_maximum_soc",
            "solax_modbus",
            "solax_battery_first_maximum_soc",
        ),
        # GEN3 marker entity
        _entity(
            "number.growatt_sph_solax_load_first_battery_minimum_soc",
            "solax_modbus",
            "solax_load_first_battery_minimum_soc",
        ),
        _entity(
            "switch.growatt_sph_solax_charger_switch",
            "solax_modbus",
            "solax_charger_switch",
        ),
    ]


# ---------------------------------------------------------------------------
# User-renamed entities: entity_id changed, unique_id unchanged
# ---------------------------------------------------------------------------


def _growatt_renamed_registry() -> list[dict]:
    """Growatt entities where the user renamed entity IDs in HA."""
    sn = "rkm0d7n04x"
    return [
        _entity("sensor.my_battery_soc", "growatt_server", f"{sn}_state_of_charge_soc"),
        _entity(
            "sensor.battery_charging", "growatt_server", f"{sn}_battery_1_charging_w"
        ),
        _entity(
            "sensor.battery_discharging",
            "growatt_server",
            f"{sn}_battery_1_discharging_w",
        ),
        _entity("sensor.grid_import", "growatt_server", f"{sn}_import_power"),
        _entity("sensor.grid_export", "growatt_server", f"{sn}_export_power"),
        _entity("sensor.home_load", "growatt_server", f"{sn}_local_load_power"),
        _entity("sensor.solar_production", "growatt_server", f"{sn}_internal_wattage"),
    ]


# ---------------------------------------------------------------------------
# Tests: _map_registry_entities
# ---------------------------------------------------------------------------


class TestMapRegistryEntities:
    def setup_method(self):
        self.ctrl = _make_controller()

    def test_growatt_standard_entities(self):
        """Standard Growatt entities match via unique_id suffix."""
        result = self.ctrl._map_registry_entities(
            _growatt_registry(),
            ["growatt_server"],
            self.ctrl.GROWATT_MIN_SUFFIX_MAP,
        )
        assert result["battery_soc"] == "sensor.rkm0d7n04x_state_of_charge_soc"
        assert (
            result["battery_charge_power"] == "sensor.rkm0d7n04x_battery_1_charging_w"
        )
        assert (
            result["battery_discharge_power"]
            == "sensor.rkm0d7n04x_battery_1_discharging_w"
        )
        assert result["import_power"] == "sensor.rkm0d7n04x_import_power"
        assert result["export_power"] == "sensor.rkm0d7n04x_export_power"
        assert result["pv_power"] == "sensor.rkm0d7n04x_internal_wattage"
        assert result["grid_charge"] == "switch.rkm0d7n04x_charge_from_grid"
        assert (
            result["battery_discharge_stop_soc"]
            == "number.rkm0d7n04x_battery_discharge_soc_limit_on_grid"
        )
        assert len(result) == 20  # all Growatt MIN entities mapped

    def test_growatt_ignores_off_grid_discharge_stop_soc(self):
        """The off-grid discharge-stop-SOC entity must never be matched:
        BESS only operates grid-tied, so that control has no effect and
        matching it would silently bind a control that does nothing (#270)."""
        off_grid_entity = _entity(
            "number.rkm0d7n04x_battery_discharge_soc_limit",
            "growatt_server",
            "rkm0d7n04x_battery_discharge_soc_limit",
        )
        result = self.ctrl._map_registry_entities(
            [off_grid_entity],
            ["growatt_server"],
            self.ctrl.GROWATT_MIN_SUFFIX_MAP,
        )
        assert "battery_discharge_stop_soc" not in result

    def test_growatt_sph_entities(self):
        """SPH entities match via mix_* unique_id sensor keys."""
        result = self.ctrl._map_registry_entities(
            _growatt_sph_registry(),
            ["growatt_server"],
            self.ctrl.GROWATT_SPH_SUFFIX_MAP,
        )
        sn = "egm2h4l0g0"
        assert result["battery_soc"] == f"sensor.{sn}_state_of_charge"
        assert result["battery_charge_power"] == f"sensor.{sn}_battery_charging"
        assert result["battery_discharge_power"] == f"sensor.{sn}_battery_discharging_w"
        assert result["import_power"] == f"sensor.{sn}_import_from_grid"
        assert result["export_power"] == f"sensor.{sn}_export_to_grid"
        assert result["pv_power"] == f"sensor.{sn}_all_pv_wattage"
        assert (
            result["lifetime_battery_charged"]
            == f"sensor.{sn}_lifetime_battery_charged"
        )
        assert (
            result["lifetime_battery_discharged"]
            == f"sensor.{sn}_lifetime_battery_discharged"
        )
        assert result["lifetime_solar_energy"] == f"sensor.{sn}_lifetime_solar_energy"
        assert (
            result["lifetime_export_to_grid"] == f"sensor.{sn}_lifetime_export_to_grid"
        )
        assert (
            result["lifetime_import_from_grid"]
            == f"sensor.{sn}_lifetime_import_from_grid"
        )
        assert (
            result["lifetime_load_consumption"]
            == f"sensor.{sn}_lifetime_load_consumption"
        )
        # SPH has no number/switch entities
        assert "grid_charge" not in result
        assert "battery_charging_power_rate" not in result
        assert len(result) == 12  # all SPH sensors, no number/switch

    def test_min_map_does_not_match_sph_entities(self):
        """MIN suffix map should not match SPH mix_* unique_ids."""
        result = self.ctrl._map_registry_entities(
            _growatt_sph_registry(),
            ["growatt_server"],
            self.ctrl.GROWATT_MIN_SUFFIX_MAP,
        )
        # entity_id-based suffixes might get partial matches, but the key
        # sensors mapped via mix_* unique_ids should not appear
        assert (
            "battery_soc" not in result
            or result.get("battery_soc") != "sensor.egm2h4l0g0_state_of_charge"
        )

    def test_sph_map_does_not_match_min_entities(self):
        """SPH suffix map should not match MIN tlx_* unique_ids."""
        result = self.ctrl._map_registry_entities(
            _growatt_registry(),
            ["growatt_server"],
            self.ctrl.GROWATT_SPH_SUFFIX_MAP,
        )
        # MIN entities use tlx_* keys and entity_id patterns that don't
        # exist in the SPH map — most sensors should not match
        assert "grid_charge" not in result
        assert "battery_charging_power_rate" not in result

    def test_growatt_renamed_entities_still_match(self):
        """User-renamed entity IDs still match via unique_id."""
        result = self.ctrl._map_registry_entities(
            _growatt_renamed_registry(),
            ["growatt_server"],
            self.ctrl.GROWATT_MIN_SUFFIX_MAP,
        )
        # entity_id is the renamed version, but discovery found it via unique_id
        assert result["battery_soc"] == "sensor.my_battery_soc"
        assert result["battery_charge_power"] == "sensor.battery_charging"
        assert result["import_power"] == "sensor.grid_import"
        assert result["pv_power"] == "sensor.solar_production"
        assert len(result) == 7

    def test_solax_native_entities(self):
        """Native SolaX entities match via SOLAX_NATIVE_SUFFIX_MAP."""
        result = self.ctrl._map_registry_entities(
            _solax_native_registry(),
            ["solax_modbus", "solax"],
            self.ctrl.SOLAX_NATIVE_SUFFIX_MAP,
        )
        assert result["battery_soc"] == "sensor.solax_battery_capacity"
        assert result["battery_charge_power"] == "sensor.solax_battery_power_charge"
        assert (
            result["solax_power_control_mode"]
            == "select.solax_remotecontrol_power_control"
        )
        assert result["solax_active_power"] == "number.solax_remotecontrol_active_power"
        assert (
            result["solax_battery_min_soc"]
            == "number.solax_battery_minimum_capacity_gridtied"
        )
        assert len(result) >= 10

    def test_solax_native_ignores_off_grid_minimum_capacity(self):
        """The general/off-grid minimum-capacity entity must never be
        matched: BESS only operates grid-tied, so that control has no
        effect and matching it would silently bind a control that does
        nothing (#270)."""
        off_grid_entity = _entity(
            "number.solax_battery_minimum_capacity",
            "solax_modbus",
            "solax_battery_minimum_capacity",
        )
        result = self.ctrl._map_registry_entities(
            [off_grid_entity],
            ["solax_modbus", "solax"],
            self.ctrl.SOLAX_NATIVE_SUFFIX_MAP,
        )
        assert "solax_battery_min_soc" not in result

    def test_solax_growatt_entities(self):
        """Growatt GEN4 inverter via solax_modbus matches via SOLAX_GROWATT_MIN_SUFFIX_MAP."""
        result = self.ctrl._map_registry_entities(
            _solax_growatt_registry(),
            ["solax_modbus", "solax"],
            self.ctrl.SOLAX_GROWATT_MIN_SUFFIX_MAP,
        )
        assert result["battery_soc"] == "sensor.growatt_inverter_solax_battery_soc"
        assert (
            result["battery_charge_power"]
            == "sensor.growatt_inverter_solax_battery_charge_power"
        )
        assert (
            result["battery_discharge_power"]
            == "sensor.growatt_inverter_solax_battery_discharge_power"
        )
        assert (
            result["import_power"]
            == "sensor.growatt_inverter_solax_total_forward_power"
        )
        assert (
            result["export_power"]
            == "sensor.growatt_inverter_solax_total_reverse_power"
        )
        assert (
            result["local_load_power"]
            == "sensor.growatt_inverter_solax_total_load_power"
        )
        assert result["pv_power"] == "sensor.growatt_inverter_solax_pv_power_total"
        assert (
            result["battery_charging_power_rate"]
            == "number.growatt_inverter_solax_ems_charging_rate"
        )
        assert result["grid_charge"] == "switch.growatt_inverter_solax_charger_switch"
        assert (
            result["battery_discharge_stop_soc"]
            == "number.growatt_inverter_solax_ems_discharging_stop_soc_on_grid"
        )
        assert len(result) == 18

    def test_solax_growatt_ignores_off_grid_discharge_stop_soc(self):
        """The off-grid EMS discharge-stop-SOC entity must never be matched:
        BESS only operates grid-tied, so that register has no effect and
        matching it would silently bind a control that does nothing (#270).
        If only the off-grid entity is present (e.g. an outdated solax_modbus
        integration lacking the on-grid descriptor), the key stays
        unmapped rather than falling back to a non-functional control."""
        off_grid_entity = _entity(
            "number.growatt_inverter_solax_ems_discharging_stop_soc",
            "solax_modbus",
            "solax_ems_discharging_stop_soc",
        )
        result = self.ctrl._map_registry_entities(
            [off_grid_entity],
            ["solax_modbus", "solax"],
            self.ctrl.SOLAX_GROWATT_MIN_SUFFIX_MAP,
        )
        assert "battery_discharge_stop_soc" not in result

    def test_platform_filter_excludes_other_integrations(self):
        """Entities from non-matching platforms are excluded."""
        result = self.ctrl._map_registry_entities(
            _growatt_registry(),
            ["solax_modbus"],
            self.ctrl.GROWATT_MIN_SUFFIX_MAP,
        )
        assert len(result) == 0

    def test_nordpool_entity_not_matched(self):
        """Nordpool entities are excluded by platform filter."""
        result = self.ctrl._map_registry_entities(
            _growatt_registry(),
            ["growatt_server"],
            self.ctrl.GROWATT_MIN_SUFFIX_MAP,
        )
        assert "nordpool_kwh_se4_sek" not in result.values()

    def test_empty_registry(self):
        result = self.ctrl._map_registry_entities(
            [],
            ["growatt_server"],
            self.ctrl.GROWATT_MIN_SUFFIX_MAP,
        )
        assert result == {}

    def test_export_limiter_select_does_not_steal_export_power(self):
        """Regression: select.limit_grid_export must not match export_power.

        The solax_modbus integration has both:
        - sensor with unique_id suffix "solax_total_reverse_power" (export power sensor)
        - select with unique_id suffix "solax_limit_grid_export" (export limiter config)

        The old short suffix "grid_export" matched the select entity because
        "solax_limit_grid_export" ends with "_grid_export".  With exact
        "solax_" prefixed suffixes, only the correct sensor should match.
        """
        # Place the select BEFORE the sensor to reproduce the original bug
        # (first-writer-wins with old short suffixes)
        entities = [
            _entity(
                "select.growatt_inverter_solax_inverter_limit_grid_export",
                "solax_modbus",
                "solax_limit_grid_export",
            ),
            _entity(
                "sensor.growatt_inverter_solax_total_export_power",
                "solax_modbus",
                "solax_total_reverse_power",
            ),
        ]
        result = self.ctrl._map_registry_entities(
            entities,
            ["solax_modbus"],
            self.ctrl.SOLAX_GROWATT_MIN_SUFFIX_MAP,
        )
        assert result["export_power"] == (
            "sensor.growatt_inverter_solax_total_export_power"
        )
        # The select entity must NOT appear anywhere in the result
        assert (
            "select.growatt_inverter_solax_inverter_limit_grid_export"
            not in result.values()
        )


# ---------------------------------------------------------------------------
# Tests: discover_sensors_from_registry
# ---------------------------------------------------------------------------


class TestDiscoverSensorsFromRegistry:
    def setup_method(self):
        self.ctrl = _make_controller()

    def test_growatt_min_only(self):
        """MIN registry → detected_platform is growatt_server_min, MIN has more sensors."""
        sensors, platform = self.ctrl.discover_sensors_from_registry(
            _growatt_registry()
        )
        assert platform == "growatt_server_min"
        assert "growatt_server_min" in sensors
        assert len(sensors["growatt_server_min"]) == 20
        # SPH map may partially match some entity_id-based lifetime suffixes,
        # but MIN must have strictly more matches
        assert len(sensors["growatt_server_min"]) > len(
            sensors.get("growatt_server_sph", {})
        )

    def test_growatt_sph_only(self):
        """SPH registry → detected_platform is growatt_server_sph, all 12 sensors mapped."""
        sensors, platform = self.ctrl.discover_sensors_from_registry(
            _growatt_sph_registry()
        )
        assert platform == "growatt_server_sph"
        assert "growatt_server_sph" in sensors
        assert len(sensors["growatt_server_sph"]) == 12
        # No number/switch entities for SPH
        assert "grid_charge" not in sensors["growatt_server_sph"]
        assert "battery_charging_power_rate" not in sensors["growatt_server_sph"]
        # SPH should have more matches than MIN map
        assert len(sensors["growatt_server_sph"]) > len(
            sensors.get("growatt_server_min", {})
        )

    def test_solax_native_only(self):
        """When only native SolaX entities exist, detected_platform is solax."""
        sensors, platform = self.ctrl.discover_sensors_from_registry(
            _solax_native_registry()
        )
        assert platform == "solax_modbus_native"
        assert "solax_modbus_native" in sensors
        assert len(sensors["solax_modbus_native"]) >= 10

    def test_solax_growatt_min(self):
        """Growatt GEN4 inverter via solax_modbus with TOU slots → solax_modbus_growatt_min."""
        sensors, platform = self.ctrl.discover_sensors_from_registry(
            _solax_growatt_tou_registry()
        )
        assert platform == "solax_modbus_growatt_min"
        assert "solax_modbus_growatt_min" in sensors
        growatt_min = sensors["solax_modbus_growatt_min"]
        assert growatt_min["battery_soc"] == "sensor.growatt_inverter_solax_battery_soc"
        assert (
            growatt_min["import_power"]
            == "sensor.growatt_inverter_solax_total_forward_power"
        )
        assert "tou_time_1_enabled" in growatt_min

    def test_solax_growatt_with_tou(self):
        """Growatt with TOU entities detected as solax_modbus_growatt_min platform."""
        sensors, platform = self.ctrl.discover_sensors_from_registry(
            _solax_growatt_tou_registry()
        )
        assert platform == "solax_modbus_growatt_min"
        assert "solax_modbus_growatt_min" in sensors
        # Base sensors (18) + TOU entities (9 slots x 5 = 45)
        assert len(sensors["solax_modbus_growatt_min"]) == 63
        assert (
            sensors["solax_modbus_growatt_min"]["battery_soc"]
            == "sensor.growatt_inverter_solax_battery_soc"
        )
        assert (
            sensors["solax_modbus_growatt_min"]["tou_time_1_enabled"]
            == "select.growatt_inverter_solax_time_1_enabled"
        )

    def test_both_growatt_and_solax_native_present(self):
        """When both integrations exist, both are mapped; growatt_server_min is primary."""
        combined = _growatt_registry() + _solax_native_registry()
        sensors, platform = self.ctrl.discover_sensors_from_registry(combined)
        assert platform == "growatt_server_min"
        assert "growatt_server_min" in sensors
        assert "solax_modbus_native" in sensors
        assert len(sensors["growatt_server_min"]) == 20

    def test_renamed_growatt_entities_discovered(self):
        """User-renamed entities still discovered via unique_id."""
        sensors, platform = self.ctrl.discover_sensors_from_registry(
            _growatt_renamed_registry()
        )
        assert platform == "growatt_server_min"
        assert sensors["growatt_server_min"]["battery_soc"] == "sensor.my_battery_soc"
        assert sensors["growatt_server_min"]["pv_power"] == "sensor.solar_production"

    def test_solax_growatt_gen3(self):
        """GEN3 Growatt (MIX/SPA/SPH) detected as solax_modbus_growatt_sph platform."""
        sensors, platform = self.ctrl.discover_sensors_from_registry(
            _solax_growatt_gen3_registry()
        )
        assert platform == "solax_modbus_growatt_sph"
        assert "solax_modbus_growatt_sph" in sensors
        assert (
            sensors["solax_modbus_growatt_sph"]["battery_soc"]
            == "sensor.growatt_sph_solax_battery_soc"
        )
        # GEN3-specific EMS mapping
        assert (
            sensors["solax_modbus_growatt_sph"]["battery_charging_power_rate"]
            == "number.growatt_sph_solax_battery_first_charge_rate"
        )
        assert (
            sensors["solax_modbus_growatt_sph"]["battery_discharging_power_rate"]
            == "number.growatt_sph_solax_grid_first_discharge_rate"
        )
        # GEN3 has total_load → lifetime_load_consumption
        assert (
            sensors["solax_modbus_growatt_sph"]["lifetime_load_consumption"]
            == "sensor.growatt_sph_solax_total_load"
        )

    def test_gen3_marker_not_detected_for_gen4(self):
        """GEN4 entities (TOU slots) do not trigger GEN3 detection."""
        entities = _solax_growatt_tou_registry()
        assert self.ctrl._has_growatt_gen3_entities(entities) is False

    def test_gen4_marker_not_detected_for_gen3(self):
        """GEN3 entities do not trigger GEN4 TOU detection."""
        entities = _solax_growatt_gen3_registry()
        assert self.ctrl._has_growatt_tou_entities(entities) is False

    def test_growatt_tou_not_detected_for_native_solax(self):
        """Native SolaX entities (no TOU) correctly return False."""
        entities = [
            _entity(
                "sensor.inv_battery_capacity", "solax_modbus", "inv_battery_capacity"
            ),
            _entity(
                "select.inv_remotecontrol_power_control",
                "solax_modbus",
                "inv_remotecontrol_power_control",
            ),
        ]
        assert self.ctrl._has_growatt_tou_entities(entities) is False


# ---------------------------------------------------------------------------
# Tests: Derived lifetime sensor fallbacks
# ---------------------------------------------------------------------------


class TestDerivedLifetimeSensors:
    """Test that lifetime sensors are derived when no direct sensor exists."""

    def setup_method(self):
        self.ctrl = _make_controller()
        self.ctrl.sensors = {}

    def _mock_sensor(self, values: dict):
        """Return a patcher that makes _get_sensor_value return from the dict."""

        def fake_get(key):
            return values.get(key)

        return patch.object(self.ctrl, "_get_sensor_value", side_effect=fake_get)

    def test_load_consumption_direct_sensor(self):
        """Direct sensor is returned when available."""
        with self._mock_sensor({"lifetime_load_consumption": 1234.5}):
            assert self.ctrl.get_load_consumption_lifetime() == 1234.5

    def test_load_consumption_derived_for_gen4(self):
        """When no direct sensor, derive from solar + import - export."""
        with self._mock_sensor(
            {
                "lifetime_solar_energy": 5000.0,
                "lifetime_import_from_grid": 3000.0,
                "lifetime_export_to_grid": 1500.0,
            }
        ):
            assert self.ctrl.get_load_consumption_lifetime() == 6500.0

    def test_load_consumption_none_when_missing_sources(self):
        """Returns None when derivation sources are incomplete."""
        with self._mock_sensor({"lifetime_solar_energy": 5000.0}):
            assert self.ctrl.get_load_consumption_lifetime() is None

    def test_load_consumption_clamps_negative(self):
        """Derived value is clamped to 0 to guard against rounding."""
        with self._mock_sensor(
            {
                "lifetime_solar_energy": 100.0,
                "lifetime_import_from_grid": 50.0,
                "lifetime_export_to_grid": 200.0,
            }
        ):
            assert self.ctrl.get_load_consumption_lifetime() == 0.0

    def test_system_production_direct_sensor(self):
        """Direct sensor is returned when available."""
        with self._mock_sensor({"lifetime_system_production": 9999.0}):
            assert self.ctrl.get_system_production_lifetime() == 9999.0

    def test_system_production_falls_back_to_solar(self):
        """When no direct sensor (GEN3), falls back to solar energy."""
        with self._mock_sensor({"lifetime_solar_energy": 7777.0}):
            assert self.ctrl.get_system_production_lifetime() == 7777.0

    def test_system_production_none_when_nothing_available(self):
        """Returns None when neither direct nor fallback is available."""
        with self._mock_sensor({}):
            assert self.ctrl.get_system_production_lifetime() is None


# ---------------------------------------------------------------------------
# Octopus Energy entity discovery from registry
# ---------------------------------------------------------------------------


class TestDiscoverOctopusEntities:
    """discover_octopus_entities uses platform field, not entity_id substring."""

    def setup_method(self):
        self.ctrl = _make_controller()

    def _octopus_registry(self) -> list[dict]:
        """Typical Octopus Energy registry with all 4 rate entities.

        Uses realistic unique_ids matching the BottlecapDave integration format:
          octopus_energy_electricity_{serial}_{mpan}[_export]_{suffix}
          octopus_energy_gas_{serial}_{mprn}_{suffix}
        """
        return [
            _entity(
                "event.octopus_energy_electricity_current_day_rates",
                "octopus_energy",
                "octopus_energy_electricity_21L4726831_2000023585834_current_day_rates",
            ),
            _entity(
                "event.octopus_energy_electricity_next_day_rates",
                "octopus_energy",
                "octopus_energy_electricity_21L4726831_2000023585834_next_day_rates",
            ),
            _entity(
                "event.octopus_energy_electricity_export_current_day_rates",
                "octopus_energy",
                "octopus_energy_electricity_21L4726831_2000023585834_export_current_day_rates",
            ),
            _entity(
                "event.octopus_energy_electricity_export_next_day_rates",
                "octopus_energy",
                "octopus_energy_electricity_21L4726831_2000023585834_export_next_day_rates",
            ),
            # Non-Octopus entity should be ignored
            _entity(
                "sensor.growatt_battery_soc",
                "growatt_server",
                "growatt_battery_soc",
            ),
        ]

    def test_all_four_fields_discovered(self):
        result = self.ctrl.discover_octopus_entities(self._octopus_registry())
        assert result == {
            "importToday": "event.octopus_energy_electricity_current_day_rates",
            "importTomorrow": "event.octopus_energy_electricity_next_day_rates",
            "exportToday": "event.octopus_energy_electricity_export_current_day_rates",
            "exportTomorrow": "event.octopus_energy_electricity_export_next_day_rates",
        }

    def test_empty_registry(self):
        assert self.ctrl.discover_octopus_entities([]) == {}

    def test_no_octopus_entities(self):
        registry = [
            _entity("sensor.growatt_battery_soc", "growatt_server", "soc"),
        ]
        assert self.ctrl.discover_octopus_entities(registry) == {}

    def test_renamed_entities_still_matched(self):
        """Platform field is immutable — renamed entity_ids are still found."""
        registry = [
            _entity(
                "event.my_custom_name_current_day_rates",
                "octopus_energy",
                "octopus_energy_electricity_21L4726831_2000023585834_current_day_rates",
            ),
        ]
        result = self.ctrl.discover_octopus_entities(registry)
        assert result == {
            "importToday": "event.my_custom_name_current_day_rates",
        }

    def test_partial_discovery(self):
        """Only import entities present — export keys absent."""
        registry = [
            _entity(
                "event.octopus_energy_electricity_current_day_rates",
                "octopus_energy",
                "octopus_energy_electricity_21L4726831_2000023585834_current_day_rates",
            ),
            _entity(
                "event.octopus_energy_electricity_next_day_rates",
                "octopus_energy",
                "octopus_energy_electricity_21L4726831_2000023585834_next_day_rates",
            ),
        ]
        result = self.ctrl.discover_octopus_entities(registry)
        assert result == {
            "importToday": "event.octopus_energy_electricity_current_day_rates",
            "importTomorrow": "event.octopus_energy_electricity_next_day_rates",
        }
        assert "exportToday" not in result
        assert "exportTomorrow" not in result

    def test_gas_entities_excluded(self):
        """Gas rate entities must not be matched as electricity import."""
        registry = [
            _entity(
                "event.current_day_rates_gas_E6S20077472161_3948152604",
                "octopus_energy",
                "octopus_energy_gas_E6S20077472161_3948152604_current_day_rates",
            ),
            _entity(
                "event.next_day_rates_gas_E6S20077472161_3948152604",
                "octopus_energy",
                "octopus_energy_gas_E6S20077472161_3948152604_next_day_rates",
            ),
        ]
        result = self.ctrl.discover_octopus_entities(registry)
        assert result == {}

    def test_gas_entities_excluded_electricity_still_matched(self):
        """When both gas and electricity entities exist, only electricity is matched."""
        registry = [
            # Gas entities (should be excluded)
            _entity(
                "event.current_day_rates_gas_E6S20077472161_3948152604",
                "octopus_energy",
                "octopus_energy_gas_E6S20077472161_3948152604_current_day_rates",
            ),
            _entity(
                "event.next_day_rates_gas_E6S20077472161_3948152604",
                "octopus_energy",
                "octopus_energy_gas_E6S20077472161_3948152604_next_day_rates",
            ),
            # Electricity export entities
            _entity(
                "event.current_day_rates_export_electricity_21L4726831_2000060563359",
                "octopus_energy",
                "octopus_energy_electricity_21L4726831_2000060563359_export_current_day_rates",
            ),
            _entity(
                "event.next_day_rates_export_electricity_21L4726831_2000060563359",
                "octopus_energy",
                "octopus_energy_electricity_21L4726831_2000060563359_export_next_day_rates",
            ),
            # Electricity import entities
            _entity(
                "event.current_day_rates_electricity_21L4726831_2000023585834",
                "octopus_energy",
                "octopus_energy_electricity_21L4726831_2000023585834_current_day_rates",
            ),
            _entity(
                "event.next_day_rates_electricity_21L4726831_2000023585834",
                "octopus_energy",
                "octopus_energy_electricity_21L4726831_2000023585834_next_day_rates",
            ),
        ]
        result = self.ctrl.discover_octopus_entities(registry)
        assert result == {
            "importToday": "event.current_day_rates_electricity_21L4726831_2000023585834",
            "importTomorrow": "event.next_day_rates_electricity_21L4726831_2000023585834",
            "exportToday": "event.current_day_rates_export_electricity_21L4726831_2000060563359",
            "exportTomorrow": "event.next_day_rates_export_electricity_21L4726831_2000060563359",
        }


# ---------------------------------------------------------------------------
# ENTSO-e Transparency Platform discovery
# ---------------------------------------------------------------------------
#
# Registry shape verified against github.com/JaccoR/hass-entso-e sensor.py:
#   _attr_unique_id = f"entsoe.{name}_{description.key}"   (key="avg_price")
#   entity_id       = f"{DOMAIN}.{slugify(name)}_{slugify(description.name)}"
# Only the avg_price sensor carries prices_today / prices_tomorrow attributes.
# This mirrors issue #126 (user "Belpex H").


def _entsoe_registry() -> list[dict]:
    """Entity registry for the ENTSO-e integration with custom name 'Belpex H'."""
    return [
        _entity(
            "sensor.belpex_h_current_electricity_market_price",
            "entsoe",
            "entsoe.Belpex H_current_price",
        ),
        _entity(
            "sensor.belpex_h_average_electricity_price",
            "entsoe",
            "entsoe.Belpex H_avg_price",
        ),
        _entity(
            "sensor.belpex_h_highest_energy_price",
            "entsoe",
            "entsoe.Belpex H_max_price",
        ),
    ]


class TestDiscoverEntsoeEntity:
    """Tests for ENTSO-e price sensor discovery."""

    def setup_method(self):
        self.ctrl = _make_controller()

    def test_matches_avg_price_via_unique_id(self):
        result = self.ctrl.discover_entsoe_entity(_entsoe_registry(), states=[])
        assert result == "sensor.belpex_h_average_electricity_price"

    def test_matches_default_unique_id_without_custom_name(self):
        registry = [
            _entity(
                "sensor.current_electricity_market_price",
                "entsoe",
                "entsoe.current_price",
            ),
            _entity("sensor.average_electricity_price", "entsoe", "entsoe.avg_price"),
        ]
        result = self.ctrl.discover_entsoe_entity(registry, states=[])
        assert result == "sensor.average_electricity_price"

    def test_ignores_non_entsoe_platforms(self):
        registry = [
            _entity("sensor.something_avg_price", "other_platform", "other.avg_price"),
        ]
        assert self.ctrl.discover_entsoe_entity(registry, states=[]) is None

    def test_attribute_shape_fallback_when_unique_id_absent(self):
        """Detect by prices_today shape if the registry doesn't match (renamed/version drift)."""
        states = [
            {
                "entity_id": "sensor.renamed_price_sensor",
                "attributes": {
                    "prices_today": [
                        {"time": "2026-06-12T00:00:00", "price": 0.08555},
                        {"time": "2026-06-12T01:00:00", "price": 0.08123},
                    ]
                },
            }
        ]
        result = self.ctrl.discover_entsoe_entity(entity_registry=[], states=states)
        assert result == "sensor.renamed_price_sensor"

    def test_returns_none_when_nothing_matches(self):
        states = [{"entity_id": "sensor.unrelated", "attributes": {"foo": "bar"}}]
        assert self.ctrl.discover_entsoe_entity([], states) is None


# ---------------------------------------------------------------------------
# Frontend ↔ backend sensor key consistency
# ---------------------------------------------------------------------------


class TestFrontendSensorKeysMatchBackend:
    """Every sensor key shown in the frontend UI must exist in the backend suffix map.

    Prevents showing "Not detected" fields for sensors that don't exist on a
    platform (e.g. local_load_power on SPH cloud).
    """

    # Map frontend platform IDs to backend suffix map class attributes.
    PLATFORM_TO_SUFFIX_MAP: ClassVar[dict[str, str]] = {
        "growatt_server_min": "GROWATT_MIN_SUFFIX_MAP",
        "growatt_server_sph": "GROWATT_SPH_SUFFIX_MAP",
        "solax_modbus_native": "SOLAX_NATIVE_SUFFIX_MAP",
        "solax_modbus_growatt_min": "SOLAX_GROWATT_MIN_SUFFIX_MAP",
        "solax_modbus_growatt_sph": "SOLAX_GROWATT_SPH_SUFFIX_MAP",
    }

    @staticmethod
    def _parse_frontend_sensor_keys() -> dict[str, set[str]]:
        """Parse sensorDefinitions.ts to extract sensor keys per platform.

        Returns dict mapping platform_id -> set of sensor keys shown in the UI.
        """
        import re
        from pathlib import Path

        ts_path = (
            Path(__file__).parents[4]
            / "frontend"
            / "src"
            / "lib"
            / "sensorDefinitions.ts"
        )
        source = ts_path.read_text()

        result: dict[str, set[str]] = {}

        # Find all { id: 'xxx', ... sensorGroups: ... } blocks
        # and extract key: 'yyy' from each.
        blocks = re.split(r"\{\s*\n\s*id:\s*'", source)
        for block in blocks[1:]:  # skip preamble before first id
            platform_match = re.match(r"([^']+)'", block)
            if not platform_match:
                continue
            platform_id = platform_match.group(1)

            # Skip non-inverter integrations
            if platform_id in (
                "nordpool",
                "solar_forecast",
                "consumption_forecast",
                "phase_current",
                "discharge_inhibit",
                "weather",
            ):
                continue

            # Check if sensorGroups references a named constant
            groups_ref = re.search(r"sensorGroups:\s*(\w+)", block)
            if groups_ref:
                const_name = groups_ref.group(1)
                # Find the constant definition in the full source
                const_match = re.search(
                    rf"const\s+{const_name}.*?=\s*\[(.*?)\];",
                    source,
                    re.DOTALL,
                )
                if const_match:
                    search_text = const_match.group(1)
                    # The constant may reference other constants — expand them
                    for ref in re.findall(
                        r"\b([A-Z_]+(?:_MONITORING|_LIFETIME))\b", search_text
                    ):
                        ref_match = re.search(
                            rf"const\s+{ref}.*?sensors:\s*\[(.*?)\]",
                            source,
                            re.DOTALL,
                        )
                        if ref_match:
                            search_text += ref_match.group(1)
                else:
                    search_text = block
            else:
                search_text = block

            keys = set(re.findall(r"key:\s*'([^']+)'", search_text))
            if keys:
                result[platform_id] = keys

        return result

    # Sensor keys that exist in backend suffix maps but are intentionally
    # NOT shown in the frontend wizard UI.  Every entry needs a reason.
    #
    # - lifetime_system_production: discoverable but BESS derives it from
    #   lifetime_solar_energy via EnergyFlowCalculator — no config needed.
    # - lifetime_self_consumption: Growatt cloud only, always derived.
    # - TOU time slots 2-9: managed by backend, only slot 1 shown in UI.
    BACKEND_ONLY_KEYS: ClassVar[dict[str, set[str]]] = {
        "growatt_server_min": {
            "lifetime_system_production",
            "lifetime_self_consumption",
        },
        "solax_modbus_growatt_min": {
            "lifetime_system_production",
            *(
                f"tou_time_{n}_{f}"
                for n in range(2, 10)
                for f in ("enabled", "begin", "end", "mode", "update")
            ),
        },
        "solax_modbus_native": {"lifetime_system_production"},
    }

    def test_all_frontend_keys_exist_in_suffix_map(self):
        """For each platform, every frontend sensor key must be discoverable."""
        frontend_keys = self._parse_frontend_sensor_keys()

        for platform_id, suffix_map_attr in self.PLATFORM_TO_SUFFIX_MAP.items():
            suffix_map = getattr(HomeAssistantAPIController, suffix_map_attr)
            backend_keys = set(suffix_map.values())

            ui_keys = frontend_keys.get(platform_id, set())
            assert ui_keys, f"No frontend keys found for {platform_id} — parser broken?"

            extra = ui_keys - backend_keys
            assert not extra, (
                f"{platform_id}: frontend shows sensors that the backend "
                f"suffix map ({suffix_map_attr}) cannot discover: {sorted(extra)}"
            )

    def test_no_undeclared_backend_only_keys(self):
        """Backend suffix map values not in the frontend must be in BACKEND_ONLY_KEYS.

        Prevents "Not detected" phantom fields: if a new sensor is added to a
        suffix map but not to the frontend, this test forces an explicit decision
        — either add it to the UI or add it to BACKEND_ONLY_KEYS with a reason.
        """
        frontend_keys = self._parse_frontend_sensor_keys()

        for platform_id, suffix_map_attr in self.PLATFORM_TO_SUFFIX_MAP.items():
            suffix_map = getattr(HomeAssistantAPIController, suffix_map_attr)
            backend_keys = set(suffix_map.values())

            ui_keys = frontend_keys.get(platform_id, set())
            allowed = self.BACKEND_ONLY_KEYS.get(platform_id, set())

            backend_not_in_ui = backend_keys - ui_keys
            undeclared = backend_not_in_ui - allowed
            assert not undeclared, (
                f"{platform_id}: backend suffix map ({suffix_map_attr}) has keys "
                f"not shown in the frontend and not in BACKEND_ONLY_KEYS: "
                f"{sorted(undeclared)}. Either add them to the frontend "
                f"sensorDefinitions.ts or to BACKEND_ONLY_KEYS with a reason."
            )


# ---------------------------------------------------------------------------
# Solcast entity-registry discovery (#218): unique_id matching instead of
# entity_id substrings, so detection survives non-English HA locale renames.
# ---------------------------------------------------------------------------


class TestSolcastEntityRegistryDiscovery:
    def test_detects_solcast_via_unique_id_with_localized_entity_id(self):
        """A renamed (non-English) entity_id must still be found via unique_id."""
        controller = _make_controller()
        registry = [
            _entity(
                "sensor.solpanel_prognos_idag",
                "solcast_solar",
                "abc123_total_kwh_forecast_today",
            ),
            _entity(
                "sensor.solpanel_prognos_imorgon",
                "solcast_solar",
                "abc123_total_kwh_forecast_tomorrow",
            ),
        ]

        result = controller.discover_optional_sensors([], registry)

        assert result["solar_forecast_today"] == "sensor.solpanel_prognos_idag"
        assert result["solar_forecast_tomorrow"] == "sensor.solpanel_prognos_imorgon"

    def test_no_solcast_detection_without_entity_registry(self):
        """English-locale entity_id substrings alone no longer detect Solcast.

        Registry-based unique_id matching is the only path now (matches the
        beta reference implementation) — states-only substring matching was
        removed because it broke on non-English HA installs.
        """
        controller = _make_controller()
        states = [
            {"entity_id": "sensor.solcast_pv_forecast_forecast_today"},
            {"entity_id": "sensor.solcast_pv_forecast_forecast_tomorrow"},
        ]

        result = controller.discover_optional_sensors(states, None)

        assert "solar_forecast_today" not in result
        assert "solar_forecast_tomorrow" not in result
