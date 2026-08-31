"""Unit tests for registry-based sensor discovery.

Tests cover:
- _map_registry_entities: unique_id-based suffix matching
- discover_sensors_from_registry: single suffix map per platform
- Robustness against user entity renaming (unique_id is immutable)
- Derived lifetime sensors (SolaX native/Solis/Huawei lack a load register;
  GEN3 lacks a system-production one)
"""

import logging
from typing import ClassVar
from unittest.mock import patch

import pytest

from core.bess.ha_api_controller import HomeAssistantAPIController
from core.bess.settings_store import SettingsStore


def _make_controller() -> HomeAssistantAPIController:
    """Create a minimal controller instance without a real HA connection."""
    ctrl = HomeAssistantAPIController.__new__(HomeAssistantAPIController)
    ctrl._settings_store = SettingsStore()
    return ctrl


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
        # The ONLY battery power entity solax_modbus publishes: a signed
        # register (plugin_solax.py, key="battery_power_charge", REGISTER_S16,
        # reg 0x16) that goes negative while discharging. There is no
        # "battery_power_discharge" key anywhere in the integration — an
        # earlier version of this fixture invented one, which is why #542
        # shipped with a discharge sensor that never resolved.
        _entity(
            "sensor.solax_battery_power_charge",
            "solax_modbus",
            "solax_battery_power_charge",
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


def _huawei_registry(serial: str = "HW2024ABCDEF") -> list[dict]:
    """Source-derived Huawei LUNA2000 registry (verified unique_id shapes,
    see docs/superpowers/specs/2026-07-22-issue-120-huawei-inverter-platform-design.md).
    """
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
            "number.huawei_battery_discharging_cutoff_capacity",
            "huawei_solar",
            f"{serial}_storage_discharging_cutoff_capacity",
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
        _entity(
            "sensor.huawei_inverter_accumulated_yield_energy",
            "huawei_solar",
            f"{serial}_accumulated_yield_energy",
        ),
        _entity(
            "sensor.huawei_battery_total_charge",
            "huawei_solar",
            f"{serial}_storage_total_charge",
        ),
        _entity(
            "sensor.huawei_battery_total_discharge",
            "huawei_solar",
            f"{serial}_storage_total_discharge",
        ),
        _entity(
            "sensor.huawei_meter_grid_exported_energy",
            "huawei_solar",
            f"{serial}_grid_exported_energy",
        ),
        _entity(
            "sensor.huawei_meter_grid_accumulated_energy",
            "huawei_solar",
            f"{serial}_grid_accumulated_energy",
        ),
        # Deliberately listed BEFORE input_power: "SN_total_dc_input_power"
        # also ends with "_input_power", so registry order alone would let
        # this entity claim pv_power.  Only _map_registry_entities' longest-
        # suffix-first ordering keeps the two apart (#569).
        _entity(
            "sensor.huawei_inverter_total_dc_input_energy",
            "huawei_solar",
            f"{serial}_total_dc_input_power",
        ),
        _entity(
            "sensor.huawei_inverter_input_power",
            "huawei_solar",
            f"{serial}_input_power",
        ),
        _entity(
            "sensor.huawei_meter_power_meter_active_power",
            "huawei_solar",
            f"{serial}_power_meter_active_power",
        ),
        # EMMA-only "Total Energy Consumption" register (#730). Present only on
        # installs with an EMMA energy manager; entity_registry_enabled_default
        # is False upstream, so a real registry often carries it disabled — see
        # test_huawei_emma_consumption_disabled_by_default_is_reported.
        _entity(
            "sensor.huawei_emma_total_energy_consumption",
            "huawei_solar",
            f"{serial}_total_energy_consumption",
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


def _solax_growatt_vpp_entities() -> list[dict]:
    """VPP remote-power-control entities (registers 30100/30407-30410).

    Present on both GEN3 and GEN4 hardware alongside their existing TOU/EMS
    entities — solax_modbus exposes all entities for the detected model
    regardless of which control mode BESS actually uses (see issue #118).
    """
    return [
        _entity(
            "select.growatt_inverter_solax_vpp_status",
            "solax_modbus",
            "solax_vpp_status",
        ),
        _entity(
            "select.growatt_inverter_solax_vpp_remote_control",
            "solax_modbus",
            "solax_vpp_remote_control",
        ),
        _entity(
            "select.growatt_inverter_solax_vpp_allow_ac_charging",
            "solax_modbus",
            "solax_vpp_allow_ac_charging",
        ),
        _entity(
            "number.growatt_inverter_solax_vpp_time",
            "solax_modbus",
            "solax_vpp_time",
        ),
        _entity(
            "number.growatt_inverter_solax_vpp_power",
            "solax_modbus",
            "solax_vpp_power",
        ),
    ]


def _solax_growatt_export_limit_entities() -> list[dict]:
    """Export-limit curtailment entities (registers 122/123, issue #269).

    Present on GEN2/GEN3/GEN4 Growatt hardware via solax_modbus — verified
    against plugin_growatt.py SELECT_TYPES/NUMBER_TYPES (allowedtypes=
    GEN2|GEN3|GEN4), same verification method as the VPP entities above.
    """
    return [
        _entity(
            "select.growatt_inverter_solax_limit_grid_export",
            "solax_modbus",
            "solax_limit_grid_export",
        ),
        _entity(
            "number.growatt_inverter_solax_grid_export_limit",
            "solax_modbus",
            "solax_grid_export_limit",
        ),
    ]


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
# Solis entity registry: solis_modbus platform (local Modbus)
# ---------------------------------------------------------------------------
#
# Source-derived from github.com/Pho3niX90/solis_modbus release v4.1.6 (Phase
# 1 fixture per the add-inverter-platform skill — will be replaced/augmented
# with a real beta-tester registry once one arrives). Two entity shapes:
#
# - Clean: entities built via the *correct* unique_id_generator(controller,
#   entity["unique"]) call path (hybrid_sensors_derived sensors, TOU time
#   entities, TOU enable switches) -> "solis_modbus_<serial>_<key>".
# - Dict-embedded: entities built via SolisSensorGroup.__init__'s verified
#   bug (sensors/solis_base_sensor.py:254 passes the whole entity dict, not
#   entity["unique"]) -> unique_id contains a Python dict repr fragment
#   ``'unique': '<key>'`` somewhere inside it. Simulated here with a minimal
#   dict-repr string (real ones also carry register/category/etc.) since only
#   the `'unique': '<key>'` substring is ever matched against.
_SOLIS_SERIAL = "SN2024ABCDEF"


def _solis_dict_embedded_unique_id(key: str) -> str:
    """Simulate the dict-embedded unique_id produced by the real bug."""
    return f"solis_modbus_{_SOLIS_SERIAL}_{{'name': 'x', 'unique': '{key}', 'register': ['0']}}"


def _solis_registry() -> list[dict]:
    """Entity registry for a Solis hybrid inverter via solis_modbus."""
    sn = _SOLIS_SERIAL
    entities = [
        # Clean, derived monitoring sensors
        _entity(
            "sensor.solis_battery_charge_power",
            "solis_modbus",
            f"solis_modbus_{sn}_solis_modbus_inverter_battery_charge_power",
        ),
        _entity(
            "sensor.solis_battery_discharge_power",
            "solis_modbus",
            f"solis_modbus_{sn}_solis_modbus_inverter_battery_discharge_power",
        ),
        _entity(
            "sensor.solis_grid_power_net",
            "solis_modbus",
            f"solis_modbus_{sn}_solis_modbus_inverter_grid_power_net",
        ),
        _entity(
            "sensor.solis_pv_power_1",
            "solis_modbus",
            f"solis_modbus_{sn}_solis_modbus_inverter_dc_power_1",
        ),
        # Dict-embedded monitoring sensors (verified integration bug)
        _entity(
            "sensor.solis_battery_soc",
            "solis_modbus",
            _solis_dict_embedded_unique_id("solis_modbus_inverter_battery_soc"),
        ),
        _entity(
            "sensor.solis_household_load_power",
            "solis_modbus",
            _solis_dict_embedded_unique_id(
                "solis_modbus_inverter_household_load_power"
            ),
        ),
        _entity(
            "sensor.solis_total_battery_charge_energy",
            "solis_modbus",
            _solis_dict_embedded_unique_id(
                "solis_modbus_inverter_total_battery_charge_energy"
            ),
        ),
        _entity(
            "sensor.solis_total_battery_discharge_energy",
            "solis_modbus",
            _solis_dict_embedded_unique_id(
                "solis_modbus_inverter_total_battery_discharge_energy"
            ),
        ),
        _entity(
            "sensor.solis_pv_total_generation",
            "solis_modbus",
            _solis_dict_embedded_unique_id("solis_modbus_inverter_pv_total_generation"),
        ),
        _entity(
            "sensor.solis_total_energy_imported_from_grid",
            "solis_modbus",
            _solis_dict_embedded_unique_id(
                "solis_modbus_inverter_total_energy_imported_from_grid"
            ),
        ),
        _entity(
            "sensor.solis_total_energy_fed_into_grid",
            "solis_modbus",
            _solis_dict_embedded_unique_id(
                "solis_modbus_inverter_total_energy_fed_into_grid"
            ),
        ),
        # Native meter-measured whole-home consumption counter (#730):
        # registers 33177/33178, kWh, TOTAL_INCREASING (solis_modbus
        # hybrid_sensors.py). Same dict-embedded unique_id bug as the other
        # lifetime totals above.
        _entity(
            "sensor.solis_total_energy_consumption",
            "solis_modbus",
            _solis_dict_embedded_unique_id(
                "solis_modbus_inverter_total_energy_consumption"
            ),
        ),
    ]

    # Grid TOU v2 charge/discharge time entities (6 slots), clean unique_id.
    charge_registers = [43711, 43718, 43725, 43732, 43739, 43746]
    charge_end_registers = [43713, 43720, 43727, 43734, 43741, 43748]
    discharge_registers = [43753, 43760, 43767, 43774, 43781, 43788]
    discharge_end_registers = [43755, 43762, 43769, 43776, 43783, 43790]
    for i in range(6):
        slot = i + 1
        entities.append(
            _entity(
                f"time.solis_charge_start_{slot}",
                "solis_modbus",
                f"solis_modbus_{sn}_time_entity_{charge_registers[i]}",
            )
        )
        entities.append(
            _entity(
                f"time.solis_charge_end_{slot}",
                "solis_modbus",
                f"solis_modbus_{sn}_time_entity_{charge_end_registers[i]}",
            )
        )
        entities.append(
            _entity(
                f"time.solis_discharge_start_{slot}",
                "solis_modbus",
                f"solis_modbus_{sn}_time_entity_{discharge_registers[i]}",
            )
        )
        entities.append(
            _entity(
                f"time.solis_discharge_end_{slot}",
                "solis_modbus",
                f"solis_modbus_{sn}_time_entity_{discharge_end_registers[i]}",
            )
        )

    # Grid TOU v2 per-slot enable switches (register 43707, bits 0-11).
    for bit in range(12):
        entities.append(
            _entity(
                f"switch.solis_tou_slot_bit_{bit}",
                "solis_modbus",
                f"solis_modbus_{sn}_43707_{bit}",
            )
        )

    return entities


# ---------------------------------------------------------------------------
# Tests: _map_registry_entities
# ---------------------------------------------------------------------------


class TestMapRegistryEntities:
    def setup_method(self):
        self.ctrl = _make_controller()

    def test_growatt_standard_entities(self):
        """Standard Growatt entities match via unique_id suffix."""
        result, _disabled = self.ctrl._map_registry_entities(
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
        result, _disabled = self.ctrl._map_registry_entities(
            [off_grid_entity],
            ["growatt_server"],
            self.ctrl.GROWATT_MIN_SUFFIX_MAP,
        )
        assert "battery_discharge_stop_soc" not in result

    def test_growatt_sph_entities(self):
        """SPH entities match via mix_* unique_id sensor keys."""
        result, _disabled = self.ctrl._map_registry_entities(
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
        result, _disabled = self.ctrl._map_registry_entities(
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
        result, _disabled = self.ctrl._map_registry_entities(
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
        result, _disabled = self.ctrl._map_registry_entities(
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
        result, _disabled = self.ctrl._map_registry_entities(
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
        result, _disabled = self.ctrl._map_registry_entities(
            [off_grid_entity],
            ["solax_modbus", "solax"],
            self.ctrl.SOLAX_NATIVE_SUFFIX_MAP,
        )
        assert "solax_battery_min_soc" not in result

    def test_solax_growatt_entities(self):
        """Growatt GEN4 inverter via solax_modbus matches via SOLAX_GROWATT_MIN_SUFFIX_MAP."""
        result, _disabled = self.ctrl._map_registry_entities(
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
        result, _disabled = self.ctrl._map_registry_entities(
            [off_grid_entity],
            ["solax_modbus", "solax"],
            self.ctrl.SOLAX_GROWATT_MIN_SUFFIX_MAP,
        )
        assert "battery_discharge_stop_soc" not in result

    def test_platform_filter_excludes_other_integrations(self):
        """Entities from non-matching platforms are excluded."""
        result, _disabled = self.ctrl._map_registry_entities(
            _growatt_registry(),
            ["solax_modbus"],
            self.ctrl.GROWATT_MIN_SUFFIX_MAP,
        )
        assert len(result) == 0

    def test_nordpool_entity_not_matched(self):
        """Nordpool entities are excluded by platform filter."""
        result, _disabled = self.ctrl._map_registry_entities(
            _growatt_registry(),
            ["growatt_server"],
            self.ctrl.GROWATT_MIN_SUFFIX_MAP,
        )
        assert "nordpool_kwh_se4_sek" not in result.values()

    def test_empty_registry(self):
        result, _disabled = self.ctrl._map_registry_entities(
            [],
            ["growatt_server"],
            self.ctrl.GROWATT_MIN_SUFFIX_MAP,
        )
        assert result == {}

    def test_export_limiter_select_does_not_steal_export_power(self):
        """Regression: select.limit_grid_export must not match export_power.

        The solax_modbus integration has both:
        - sensor with unique_id suffix "solax_total_reverse_power" (export power sensor)
        - select with unique_id suffix "solax_limit_grid_export" (export limiter config,
          now intentionally mapped to growatt_export_limit_mode — #269)

        The old short suffix "grid_export" matched the select entity because
        "solax_limit_grid_export" ends with "_grid_export".  With exact
        "solax_" prefixed suffixes, only the correct sensor should match
        export_power — the select entity should map to its own key instead.
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
        result, _disabled = self.ctrl._map_registry_entities(
            entities,
            ["solax_modbus"],
            self.ctrl.SOLAX_GROWATT_MIN_SUFFIX_MAP,
        )
        assert result["export_power"] == (
            "sensor.growatt_inverter_solax_total_export_power"
        )
        # The select entity must map to its own key, not steal export_power
        assert result["growatt_export_limit_mode"] == (
            "select.growatt_inverter_solax_inverter_limit_grid_export"
        )


# ---------------------------------------------------------------------------
# Tests: discover_sensors_from_registry
# ---------------------------------------------------------------------------


class TestDiscoverSensorsFromRegistry:
    def setup_method(self):
        self.ctrl = _make_controller()

    def test_growatt_min_only(self):
        """MIN registry → detected_platform is growatt_server_min, MIN has more sensors."""
        sensors, platform, _disabled = self.ctrl.discover_sensors_from_registry(
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
        sensors, platform, _disabled = self.ctrl.discover_sensors_from_registry(
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
        sensors, platform, _disabled = self.ctrl.discover_sensors_from_registry(
            _solax_native_registry()
        )
        assert platform == "solax_modbus_native"
        assert "solax_modbus_native" in sensors
        assert len(sensors["solax_modbus_native"]) >= 10

    def test_solax_native_pairs_discharge_to_the_signed_charge_sensor(self):
        """issue #542: solax_modbus has one signed battery power entity.

        Without the pairing, battery_discharge_power resolves to nothing —
        check_battery_health (is_required=True) errors on it, and the reporter
        has to hand-build two template sensors. Same fix as the Solis/Huawei
        grid pairing (#475/#438): point both keys at the one entity and let
        HAApiController split it via battery_power_polarity.
        """
        sensors, _, _disabled = self.ctrl.discover_sensors_from_registry(
            _solax_native_registry()
        )
        solax = sensors["solax_modbus_native"]
        assert solax["battery_charge_power"] == "sensor.solax_battery_power_charge"
        assert solax["battery_discharge_power"] == "sensor.solax_battery_power_charge"

    def test_solax_growatt_min(self):
        """Growatt GEN4 inverter via solax_modbus with TOU slots → solax_modbus_growatt_min."""
        sensors, platform, _disabled = self.ctrl.discover_sensors_from_registry(
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
        sensors, platform, _disabled = self.ctrl.discover_sensors_from_registry(
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
        sensors, platform, _disabled = self.ctrl.discover_sensors_from_registry(
            combined
        )
        assert platform == "growatt_server_min"
        assert "growatt_server_min" in sensors
        assert "solax_modbus_native" in sensors
        assert len(sensors["growatt_server_min"]) == 20

    def test_renamed_growatt_entities_discovered(self):
        """User-renamed entities still discovered via unique_id."""
        sensors, platform, _disabled = self.ctrl.discover_sensors_from_registry(
            _growatt_renamed_registry()
        )
        assert platform == "growatt_server_min"
        assert sensors["growatt_server_min"]["battery_soc"] == "sensor.my_battery_soc"
        assert sensors["growatt_server_min"]["pv_power"] == "sensor.solar_production"

    def test_solax_growatt_gen3(self):
        """GEN3 Growatt (MIX/SPA/SPH) detected as solax_modbus_growatt_sph platform."""
        sensors, platform, _disabled = self.ctrl.discover_sensors_from_registry(
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

    def test_solis_modbus_only(self):
        """Solis hybrid via solis_modbus → detected_platform is solis_modbus."""
        sensors, platform, _disabled = self.ctrl.discover_sensors_from_registry(
            _solis_registry()
        )
        assert platform == "solis_modbus"
        assert "solis_modbus" in sensors
        solis = sensors["solis_modbus"]

        # Clean, derived monitoring sensors matched by normal endswith suffix
        assert solis["battery_charge_power"] == "sensor.solis_battery_charge_power"
        assert (
            solis["battery_discharge_power"] == "sensor.solis_battery_discharge_power"
        )
        assert solis["import_power"] == "sensor.solis_grid_power_net"
        assert solis["pv_power"] == "sensor.solis_pv_power_1"
        # Single signed sensor backs both keys (issue #475) — HAApiController
        # splits it by sign at read time via grid_power_polarity.
        assert solis["export_power"] == "sensor.solis_grid_power_net"

        # Dict-embedded monitoring sensors matched via the Solis-scoped
        # substring matcher (verified integration bug, see
        # SOLIS_DICT_EMBEDDED_SUFFIX_MAP)
        assert solis["battery_soc"] == "sensor.solis_battery_soc"
        assert solis["local_load_power"] == "sensor.solis_household_load_power"
        assert (
            solis["lifetime_battery_charged"]
            == "sensor.solis_total_battery_charge_energy"
        )
        assert (
            solis["lifetime_battery_discharged"]
            == "sensor.solis_total_battery_discharge_energy"
        )
        assert solis["lifetime_solar_energy"] == "sensor.solis_pv_total_generation"
        assert (
            solis["lifetime_import_from_grid"]
            == "sensor.solis_total_energy_imported_from_grid"
        )
        assert (
            solis["lifetime_export_to_grid"]
            == "sensor.solis_total_energy_fed_into_grid"
        )
        assert (
            solis["lifetime_load_consumption"]
            == "sensor.solis_total_energy_consumption"
        )

        # TOU v2 charge/discharge time + enable entities (6 slots each)
        assert solis["solis_charge_start_1"] == "time.solis_charge_start_1"
        assert solis["solis_charge_end_6"] == "time.solis_charge_end_6"
        assert solis["solis_discharge_start_1"] == "time.solis_discharge_start_1"
        assert solis["solis_discharge_end_6"] == "time.solis_discharge_end_6"
        assert solis["solis_charge_enable_1"] == "switch.solis_tou_slot_bit_0"
        assert solis["solis_discharge_enable_6"] == "switch.solis_tou_slot_bit_11"

    def test_solis_modbus_detected_flag(self):
        """detect_inverter_integrations reports solis=True for a solis_modbus registry."""
        detected = self.ctrl.detect_inverter_integrations(_solis_registry())
        assert detected["solis"] is True

    def test_solis_without_tou_v2_entities_maps_sensors_but_not_detected(self):
        """Monitoring-only Solis (no Grid TOU v2 marker) must not be auto-selected.

        Without time_entity_43711 (or any TOU v2 entity), schedule writes
        would fail on every attempt — solis_modbus must still be populated
        in platform_sensors (so a user can select it manually) but must not
        silently become detected_platform like a fully-controllable Solis.
        """
        sn = _SOLIS_SERIAL
        monitoring_only = [
            _entity(
                "sensor.solis_battery_charge_power",
                "solis_modbus",
                f"solis_modbus_{sn}_solis_modbus_inverter_battery_charge_power",
            ),
            _entity(
                "sensor.solis_battery_soc",
                "solis_modbus",
                _solis_dict_embedded_unique_id("solis_modbus_inverter_battery_soc"),
            ),
        ]

        sensors, platform, _disabled = self.ctrl.discover_sensors_from_registry(
            monitoring_only
        )

        assert "solis_modbus" in sensors
        assert sensors["solis_modbus"]["battery_soc"] == "sensor.solis_battery_soc"
        assert platform is None

    def test_solis_dict_embedded_matcher_prefers_enabled_over_disabled(self):
        """A disabled dict-embedded entity must not shadow an enabled one."""
        disabled_entity = _entity(
            "sensor.solis_battery_soc_old",
            "solis_modbus",
            _solis_dict_embedded_unique_id("solis_modbus_inverter_battery_soc"),
        )
        disabled_entity["disabled_by"] = "user"
        enabled_entity = _entity(
            "sensor.solis_battery_soc",
            "solis_modbus",
            _solis_dict_embedded_unique_id("solis_modbus_inverter_battery_soc"),
        )

        mapped, disabled = self.ctrl._match_solis_dict_embedded_entities(
            [disabled_entity, enabled_entity]
        )

        assert mapped["battery_soc"] == "sensor.solis_battery_soc"
        assert "battery_soc" not in disabled

    def test_solis_dict_embedded_matcher_reports_disabled_only_match(self):
        """A disabled-only match is reported, never mapped (#549).

        Mapping it would persist an entity that has no state, so every
        later read 404s — the same failure this matcher's sibling
        ``_map_registry_entities`` used to produce.
        """
        disabled_entity = _entity(
            "sensor.solis_battery_soc_old",
            "solis_modbus",
            _solis_dict_embedded_unique_id("solis_modbus_inverter_battery_soc"),
        )
        disabled_entity["disabled_by"] = "user"

        mapped, disabled = self.ctrl._match_solis_dict_embedded_entities(
            [disabled_entity]
        )

        assert "battery_soc" not in mapped
        assert disabled["battery_soc"] == "sensor.solis_battery_soc_old"

    def test_solax_growatt_gen4_vpp_entities_discovered(self):
        """GEN4 VPP entities are mapped alongside TOU entities (issue #118).

        Real hardware exposes both TOU and VPP entities regardless of which
        control_mode BESS uses — detection still keys off the TOU marker.
        """
        registry = _solax_growatt_tou_registry() + _solax_growatt_vpp_entities()
        sensors, platform, _disabled = self.ctrl.discover_sensors_from_registry(
            registry
        )
        assert platform == "solax_modbus_growatt_min"
        growatt_min = sensors["solax_modbus_growatt_min"]
        assert (
            growatt_min["growatt_vpp_status"]
            == "select.growatt_inverter_solax_vpp_status"
        )
        assert (
            growatt_min["growatt_vpp_remote_control"]
            == "select.growatt_inverter_solax_vpp_remote_control"
        )
        assert (
            growatt_min["growatt_vpp_allow_ac_charging"]
            == "select.growatt_inverter_solax_vpp_allow_ac_charging"
        )
        assert (
            growatt_min["growatt_vpp_time"] == "number.growatt_inverter_solax_vpp_time"
        )
        assert (
            growatt_min["growatt_vpp_power"]
            == "number.growatt_inverter_solax_vpp_power"
        )
        # TOU entities still present — VPP is additive, not a replacement
        assert "tou_time_1_enabled" in growatt_min

    def test_solax_growatt_gen3_vpp_entities_discovered(self):
        """GEN3 VPP entities are mapped — GEN3's only working control path."""
        registry = _solax_growatt_gen3_registry() + _solax_growatt_vpp_entities()
        sensors, platform, _disabled = self.ctrl.discover_sensors_from_registry(
            registry
        )
        assert platform == "solax_modbus_growatt_sph"
        growatt_sph = sensors["solax_modbus_growatt_sph"]
        assert (
            growatt_sph["growatt_vpp_status"]
            == "select.growatt_inverter_solax_vpp_status"
        )
        assert (
            growatt_sph["growatt_vpp_power"]
            == "number.growatt_inverter_solax_vpp_power"
        )

    def test_solax_growatt_gen4_export_limit_entities_discovered(self):
        """GEN4 export-limit entities are mapped alongside TOU entities (#269)."""
        registry = (
            _solax_growatt_tou_registry() + _solax_growatt_export_limit_entities()
        )
        sensors, platform, _disabled = self.ctrl.discover_sensors_from_registry(
            registry
        )
        assert platform == "solax_modbus_growatt_min"
        growatt_min = sensors["solax_modbus_growatt_min"]
        assert (
            growatt_min["growatt_export_limit_mode"]
            == "select.growatt_inverter_solax_limit_grid_export"
        )
        assert (
            growatt_min["growatt_export_limit_value"]
            == "number.growatt_inverter_solax_grid_export_limit"
        )

    def test_solax_growatt_gen3_export_limit_entities_discovered(self):
        """GEN3 export-limit entities are mapped too — same registers, per
        plugin_growatt.py's allowedtypes=GEN2|GEN3|GEN4."""
        registry = (
            _solax_growatt_gen3_registry() + _solax_growatt_export_limit_entities()
        )
        sensors, platform, _disabled = self.ctrl.discover_sensors_from_registry(
            registry
        )
        assert platform == "solax_modbus_growatt_sph"
        growatt_sph = sensors["solax_modbus_growatt_sph"]
        assert (
            growatt_sph["growatt_export_limit_mode"]
            == "select.growatt_inverter_solax_limit_grid_export"
        )
        assert (
            growatt_sph["growatt_export_limit_value"]
            == "number.growatt_inverter_solax_grid_export_limit"
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
# Tests: Disabled entities are reported, never mapped (issue #549)
# ---------------------------------------------------------------------------


class TestDisabledEntitiesAreNotMapped:
    """A disabled entity has no state in HA, so mapping one guarantees a 404.

    Issue #549: solax_modbus ships its ``Total *`` lifetime counters
    disabled_by=integration.  The mapper used to map them anyway (warning
    only), which sailed through the wizard's non-empty check and surfaced
    at runtime as "Sensor not found (404)" plus SYSTEM DEGRADED.
    """

    SUFFIX_MAP: ClassVar[dict[str, str]] = {
        "total_grid_import": "lifetime_import_from_grid",
    }

    def setup_method(self):
        self.ctrl = _make_controller()

    def _disabled(self, entity_id: str, unique_id: str) -> dict:
        entity = _entity(entity_id, "solax_modbus", unique_id)
        entity["disabled_by"] = "integration"
        return entity

    def test_disabled_only_match_is_reported_not_mapped(self):
        entity = self._disabled(
            "sensor.solaxgrowatt_inverter_total_grid_import",
            "SolaxGrowatt_total_grid_import",
        )

        mapped, disabled = self.ctrl._map_registry_entities(
            [entity], ["solax_modbus"], self.SUFFIX_MAP
        )

        assert "lifetime_import_from_grid" not in mapped
        assert (
            disabled["lifetime_import_from_grid"]
            == "sensor.solaxgrowatt_inverter_total_grid_import"
        )

    def test_enabled_match_wins_and_is_not_reported_disabled(self):
        entities = [
            self._disabled("sensor.old_total_grid_import", "Old_total_grid_import"),
            _entity(
                "sensor.new_total_grid_import",
                "solax_modbus",
                "New_total_grid_import",
            ),
        ]

        mapped, disabled = self.ctrl._map_registry_entities(
            entities, ["solax_modbus"], self.SUFFIX_MAP
        )

        assert mapped["lifetime_import_from_grid"] == "sensor.new_total_grid_import"
        assert "lifetime_import_from_grid" not in disabled

    def test_discover_reports_disabled_sensors_per_platform(self):
        """The wizard needs the disabled keys per platform, not just a log line."""
        registry = _solax_growatt_tou_registry()
        for entity in registry:
            if entity["unique_id"].endswith("_total_grid_import"):
                entity["disabled_by"] = "integration"

        _sensors, _platform, disabled = self.ctrl.discover_sensors_from_registry(
            registry
        )

        assert "lifetime_import_from_grid" in disabled["solax_modbus_growatt_min"]


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

    @pytest.mark.parametrize(
        (
            "solar_to_home,solar_to_battery,solar_to_grid,"
            "grid_to_home,grid_to_battery,battery_to_home,battery_to_grid"
        ),
        [
            # Overnight discharge: battery serves the house.
            (0.0, 0.0, 0.0, 0.40, 0.0, 1.60, 0.0),
            # Midday charging from solar.
            (1.00, 2.00, 0.0, 0.0, 0.0, 0.0, 0.0),
            # Battery idle, house on grid only.
            (0.0, 0.0, 0.0, 2.00, 0.0, 0.0, 0.0),
            # Battery exporting to grid: the case the old clamp hid.
            (0.30, 0.0, 0.0, 0.50, 0.0, 0.0, 1.70),
            # Mixed: solar splits three ways while the grid also charges.
            (1.20, 0.80, 0.60, 0.40, 0.90, 0.0, 0.0),
        ],
        ids=["discharge", "charge", "idle", "export", "mixed"],
    )
    def test_derived_load_equals_actual_load_whatever_the_battery_does(
        self,
        solar_to_home,
        solar_to_battery,
        solar_to_grid,
        grid_to_home,
        grid_to_battery,
        battery_to_home,
        battery_to_grid,
    ):
        """Derived lifetime load must equal real house consumption (issue #528).

        The counters are built up from the seven physical flows rather than
        from the derivation formula, so this asserts the energy balance
        itself, not an arithmetic restatement of the implementation. The old
        ``solar + import - export`` formula returns ``actual + net battery
        charge`` and fails every case here except ``idle``.
        """
        counters = {
            "lifetime_solar_energy": solar_to_home + solar_to_battery + solar_to_grid,
            "lifetime_import_from_grid": grid_to_home + grid_to_battery,
            "lifetime_export_to_grid": solar_to_grid + battery_to_grid,
            "lifetime_battery_charged": solar_to_battery + grid_to_battery,
            "lifetime_battery_discharged": battery_to_home + battery_to_grid,
        }
        actual_load = solar_to_home + battery_to_home + grid_to_home

        with self._mock_sensor(counters):
            assert self.ctrl.get_load_consumption_lifetime() == pytest.approx(
                actual_load
            )

    def test_load_consumption_none_when_missing_sources(self):
        """Returns None when derivation sources are incomplete."""
        with self._mock_sensor({"lifetime_solar_energy": 5000.0}):
            assert self.ctrl.get_load_consumption_lifetime() is None

    def test_load_consumption_none_when_battery_counters_missing(self):
        """No battery counters means no honest answer, so return None.

        Per ``docs/agents/rules.md`` (no silent fallbacks): deriving without
        the battery terms would return a wrong-but-plausible number, which is
        exactly the defect in issue #528.
        """
        with self._mock_sensor(
            {
                "lifetime_solar_energy": 5000.0,
                "lifetime_import_from_grid": 3000.0,
                "lifetime_export_to_grid": 1500.0,
            }
        ):
            assert self.ctrl.get_load_consumption_lifetime() is None

    def test_load_consumption_names_the_missing_counter_in_the_log(self, caplog):
        """An N/A in the health check must be traceable to a specific sensor.

        Returning ``None`` silently would leave a user with a degraded
        Energy Monitoring component and nothing naming the cause.
        """
        with self._mock_sensor(
            {
                "lifetime_solar_energy": 5000.0,
                "lifetime_import_from_grid": 3000.0,
                "lifetime_export_to_grid": 1500.0,
                "lifetime_battery_charged": 2000.0,
                # lifetime_battery_discharged deliberately absent
            }
        ):
            with caplog.at_level(logging.WARNING):
                assert self.ctrl.get_load_consumption_lifetime() is None

        assert "lifetime_battery_discharged" in caplog.text
        assert "lifetime_solar_energy" not in caplog.text

    def test_load_consumption_none_when_balance_is_negative(self):
        """A negative balance means the counters disagree, so report nothing.

        Lifetime totals are large and monotonic, so the balance cannot go
        negative through rounding — only through a stalled or under-reporting
        counter. Returning the negative would surface as a healthy "OK"
        reading (``health_check.py`` treats any float as OK), which is the
        silent degradation ``docs/agents/rules.md`` forbids. ``None`` drives
        the Energy Monitoring check to WARNING instead.
        """
        with self._mock_sensor(
            {
                "lifetime_solar_energy": 100.0,
                "lifetime_import_from_grid": 50.0,
                "lifetime_export_to_grid": 200.0,
                "lifetime_battery_charged": 40.0,
                "lifetime_battery_discharged": 30.0,
            }
        ):
            assert self.ctrl.get_load_consumption_lifetime() is None

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

#: Frontend integration IDs in sensorDefinitions.ts that are inverter
#: platforms — everything else there is an auxiliary integration
#: (pricing, forecast, phase current, weather) with no suffix map.
_INVERTER_PLATFORM_IDS: frozenset[str] = frozenset(
    {
        "growatt_server_min",
        "growatt_server_sph",
        "solax_modbus_native",
        "solax_modbus_growatt_min",
        "solax_modbus_growatt_sph",
        "solis_modbus",
        "huawei_solar_luna2000",
    }
)


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


class TestEnergyFlowSensorsRequiredOnEveryPlatform:
    """The sensors that energy-flow calculation reads must be required
    everywhere the wizard offers them, and the derived one must not be.

    Issue #549: the flags were exactly inverted.  All five flow sensors
    were ``required: false`` on every modbus platform, so the wizard
    happily completed without them and the runtime then reported
    "Energy Monitoring [ERROR] — SYSTEM DEGRADED".  Meanwhile
    ``lifetime_load_consumption`` — which ``get_load_consumption_lifetime``
    derives from the five flow sensors when unmapped (issue #528:
    ``solar + import + discharged - charged - export``) — was
    ``required: true`` on both cloud platforms, demanding a sensor BESS
    can compute for itself.
    """

    #: Read directly by energy-flow calculation; no derivation exists.
    FLOW_SENSORS: ClassVar[set[str]] = {
        "lifetime_solar_energy",
        "lifetime_import_from_grid",
        "lifetime_export_to_grid",
        "lifetime_battery_charged",
        "lifetime_battery_discharged",
    }

    #: Derived from the three grid/solar flow sensors when unmapped.
    DERIVED_SENSORS: ClassVar[set[str]] = {"lifetime_load_consumption"}

    @staticmethod
    def _parse_required_flags() -> dict[str, dict[str, bool]]:
        """Parse sensorDefinitions.ts into platform_id -> {key: required}."""
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

        def _flags(text: str) -> dict[str, bool]:
            return {
                key: required == "true"
                for key, required in re.findall(
                    r"key:\s*'([^']+)'[^\n]*?required:\s*(true|false)", text
                )
            }

        result: dict[str, dict[str, bool]] = {}
        blocks = re.split(r"\{\s*\n\s*id:\s*'", source)
        for block in blocks[1:]:
            platform_match = re.match(r"([^']+)'", block)
            if not platform_match:
                continue
            platform_id = platform_match.group(1)
            if platform_id not in _INVERTER_PLATFORM_IDS:
                continue

            groups_ref = re.search(r"sensorGroups:\s*(\w+)", block)
            search_text = block
            if groups_ref:
                const_match = re.search(
                    rf"const\s+{groups_ref.group(1)}.*?=\s*\[(.*?)\];",
                    source,
                    re.DOTALL,
                )
                if const_match:
                    search_text = const_match.group(1)
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

            flags = _flags(search_text)
            if flags:
                result[platform_id] = flags
        return result

    def test_flow_sensors_are_required_on_every_platform_offering_them(self):
        flags = self._parse_required_flags()
        assert flags, "No platforms parsed — parser broken?"

        optional_anywhere = {
            f"{platform}.{key}"
            for platform, keys in flags.items()
            for key in self.FLOW_SENSORS & keys.keys()
            if not keys[key]
        }

        assert not optional_anywhere, (
            "Energy-flow sensors must be required — the optimizer cannot "
            "derive them and the runtime health check treats Energy "
            "Monitoring as a required component: "
            f"{sorted(optional_anywhere)}"
        )

    def test_derived_load_consumption_is_never_required(self):
        flags = self._parse_required_flags()

        required_anywhere = {
            f"{platform}.{key}"
            for platform, keys in flags.items()
            for key in self.DERIVED_SENSORS & keys.keys()
            if keys[key]
        }

        assert not required_anywhere, (
            "lifetime_load_consumption is derived from the five flow sensors "
            "when unmapped, so requiring it blocks the wizard on a sensor "
            f"BESS can compute itself: {sorted(required_anywhere)}"
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


# ---------------------------------------------------------------------------
# Huawei LUNA2000 detection: huawei_solar platform
# ---------------------------------------------------------------------------


class TestHuaweiDiscovery:
    def setup_method(self):
        self.ctrl = HomeAssistantAPIController(ha_url="http://ha.local", token="tok")

    def test_huawei_entities_detected(self):
        detected = self.ctrl._detect_platforms(
            _huawei_registry(), {"huawei": ["huawei_solar"]}
        )
        assert detected["huawei"] is True

    def test_huawei_map_matches_registry(self):
        result, _disabled = self.ctrl._map_registry_entities(
            _huawei_registry(), ["huawei_solar"], self.ctrl.HUAWEI_SUFFIX_MAP
        )
        assert result["battery_soc"] == "sensor.huawei_battery_state_of_capacity"
        assert result["huawei_working_mode"] == "select.huawei_battery_working_mode"
        assert (
            result["battery_discharge_stop_soc"]
            == "number.huawei_battery_discharging_cutoff_capacity"
        )
        assert len(result) == 17

    def test_huawei_power_monitoring_sensors_mapped(self):
        """issue #438: real-time PV power and signed grid power (single
        power-meter register, split by HAApiController.grid_power_polarity —
        see #475's mechanism, reused here with export_positive polarity)."""
        result, _disabled = self.ctrl._map_registry_entities(
            _huawei_registry(), ["huawei_solar"], self.ctrl.HUAWEI_SUFFIX_MAP
        )
        assert result["pv_power"] == "sensor.huawei_inverter_input_power"
        assert result["import_power"] == "sensor.huawei_meter_power_meter_active_power"

    def test_huawei_lifetime_energy_sensors_mapped(self):
        result, _disabled = self.ctrl._map_registry_entities(
            _huawei_registry(), ["huawei_solar"], self.ctrl.HUAWEI_SUFFIX_MAP
        )
        assert (
            result["lifetime_solar_energy"]
            == "sensor.huawei_inverter_total_dc_input_energy"
        )
        assert (
            result["lifetime_battery_charged"] == "sensor.huawei_battery_total_charge"
        )
        assert (
            result["lifetime_battery_discharged"]
            == "sensor.huawei_battery_total_discharge"
        )
        assert (
            result["lifetime_export_to_grid"]
            == "sensor.huawei_meter_grid_exported_energy"
        )
        assert (
            result["lifetime_import_from_grid"]
            == "sensor.huawei_meter_grid_accumulated_energy"
        )
        assert (
            result["lifetime_load_consumption"]
            == "sensor.huawei_emma_total_energy_consumption"
        )

    def test_huawei_emma_consumption_disabled_by_default_is_reported(self) -> None:
        """The EMMA 'Total Energy Consumption' entity is
        entity_registry_enabled_default=False upstream (wlcrs/huawei_solar
        sensor.py). When the user has not enabled it, discovery must surface it
        in the disabled bucket (#549) so the wizard prompts "enable it, then
        re-run discovery" — never persist a mapping to a stateless entity.
        """
        registry = [
            e
            for e in _huawei_registry()
            if not e["unique_id"].endswith("_total_energy_consumption")
        ]
        disabled = _entity(
            "sensor.huawei_emma_total_energy_consumption",
            "huawei_solar",
            "HW2024ABCDEF_total_energy_consumption",
        )
        disabled["disabled_by"] = "integration"
        registry.append(disabled)

        result, disabled_only = self.ctrl._map_registry_entities(
            registry, ["huawei_solar"], self.ctrl.HUAWEI_SUFFIX_MAP
        )

        assert "lifetime_load_consumption" not in result
        assert (
            disabled_only["lifetime_load_consumption"]
            == "sensor.huawei_emma_total_energy_consumption"
        )

    def test_huawei_solar_energy_is_pv_input_not_inverter_yield(self):
        """issue #569: lifetime_solar_energy must be PV production.

        accumulated_yield_energy is register 32106, the inverter's
        accumulated *AC output* yield.  On a LUNA2000 hybrid that counter
        rises while the battery discharges and misses everything used to
        charge it, which upstream states outright ("The Daily Yield/Total
        Yield is incorrect: it also goes up when the battery is
        discharging" -- wlcrs/huawei_solar README FAQ).

        Every consumer of lifetime_solar_energy treats it as PV
        production: both feed derive_load_consumption's five-term balance
        (ha_api_controller.get_load_consumption_lifetime and
        energy_flow_calculator._calculate_derived_flows), so mapping AC
        yield there reports home consumption inflated by
        (battery_discharged - solar_to_battery) -- silently, since the
        lifetime total stays positive and the health check passes.

        total_dc_input_power is register 32108, "Total DC input energy":
        the lifetime integral of register 32064, which this same map
        already points at pv_power.  It is DC-side, so it excludes
        inverter conversion losses -- but no Huawei register gives PV
        production on the AC side at all, and this is the counter
        upstream names as the panels' input.
        """
        result, _disabled = self.ctrl._map_registry_entities(
            _huawei_registry(), ["huawei_solar"], self.ctrl.HUAWEI_SUFFIX_MAP
        )
        assert "accumulated_yield_energy" not in self.ctrl.HUAWEI_SUFFIX_MAP
        # The AC-yield entity is still present in the registry -- a real
        # install exposes both.  It must simply never be chosen.
        assert "sensor.huawei_inverter_accumulated_yield_energy" not in result.values()
        assert (
            result["lifetime_solar_energy"]
            == "sensor.huawei_inverter_total_dc_input_energy"
        )

    def test_huawei_dc_input_energy_does_not_steal_pv_power(self):
        """issue #569: "_total_dc_input_power" also ends with "_input_power".

        Both suffixes are in HUAWEI_SUFFIX_MAP and the matcher is an
        endswith, so the two keys are separated only by
        _map_registry_entities sorting suffixes longest-first before
        breaking on the first hit.  The fixture lists the DC-energy entity
        first precisely so registry order cannot mask that.
        """
        result, _disabled = self.ctrl._map_registry_entities(
            _huawei_registry(), ["huawei_solar"], self.ctrl.HUAWEI_SUFFIX_MAP
        )
        assert result["pv_power"] == "sensor.huawei_inverter_input_power"
        assert (
            result["lifetime_solar_energy"]
            == "sensor.huawei_inverter_total_dc_input_energy"
        )

    def test_huawei_wired_into_discover_sensors_from_registry(self):
        """Huawei must be auto-discovered like every other platform.

        HUAWEI_SUFFIX_MAP previously had no caller in
        discover_sensors_from_registry — every Huawei sensor was manual-entry
        only. This is the production entry point the setup wizard actually
        calls (backend/api.py), not _map_registry_entities in isolation.
        """
        sensors, platform, _disabled = self.ctrl.discover_sensors_from_registry(
            _huawei_registry()
        )
        assert platform == "huawei_solar_luna2000"
        assert "huawei_solar_luna2000" in sensors
        huawei = sensors["huawei_solar_luna2000"]

        assert huawei["battery_soc"] == "sensor.huawei_battery_state_of_capacity"
        assert huawei["pv_power"] == "sensor.huawei_inverter_input_power"
        assert huawei["import_power"] == "sensor.huawei_meter_power_meter_active_power"
        # Single signed power-meter register backs both keys (same pattern
        # as Solis, #475) — HAApiController splits it via grid_power_polarity.
        assert huawei["export_power"] == "sensor.huawei_meter_power_meter_active_power"

    def test_huawei_pairs_discharge_to_the_signed_battery_sensor(self):
        """issue #542: storage_charge_discharge_power (I32Register, reg 37765)
        is Huawei's only battery power register — same one-signed-sensor shape
        as native SolaX, so battery_discharge_power must resolve to it too."""
        sensors, _, _disabled = self.ctrl.discover_sensors_from_registry(
            _huawei_registry()
        )
        huawei = sensors["huawei_solar_luna2000"]
        assert (
            huawei["battery_charge_power"]
            == "sensor.huawei_battery_charge_discharge_power"
        )
        assert (
            huawei["battery_discharge_power"]
            == "sensor.huawei_battery_charge_discharge_power"
        )
