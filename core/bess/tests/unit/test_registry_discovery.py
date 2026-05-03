"""Unit tests for registry-based sensor discovery.

Tests cover:
- _map_registry_entities: unique_id-based suffix matching
- discover_sensors_from_registry: single suffix map per platform
- Robustness against user entity renaming (unique_id is immutable)
"""

from core.bess.ha_api_controller import HomeAssistantAPIController


def _make_controller() -> HomeAssistantAPIController:
    """Create a minimal controller instance without a real HA connection."""
    return HomeAssistantAPIController.__new__(HomeAssistantAPIController)


def _entity(
    entity_id: str, platform: str, unique_id: str
) -> dict:
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
        _entity(f"sensor.{sn}_state_of_charge_soc", "growatt_server", f"{sn}_state_of_charge_soc"),
        _entity(f"sensor.{sn}_battery_1_charging_w", "growatt_server", f"{sn}_battery_1_charging_w"),
        _entity(f"sensor.{sn}_battery_1_discharging_w", "growatt_server", f"{sn}_battery_1_discharging_w"),
        _entity(f"sensor.{sn}_import_power", "growatt_server", f"{sn}_import_power"),
        _entity(f"sensor.{sn}_export_power", "growatt_server", f"{sn}_export_power"),
        _entity(f"sensor.{sn}_local_load_power", "growatt_server", f"{sn}_local_load_power"),
        _entity(f"sensor.{sn}_internal_wattage", "growatt_server", f"{sn}_internal_wattage"),
        _entity(f"switch.{sn}_charge_from_grid", "growatt_server", f"{sn}_charge_from_grid"),
        _entity(f"number.{sn}_battery_charge_power_limit", "growatt_server", f"{sn}_battery_charge_power_limit"),
        _entity(f"number.{sn}_battery_discharge_power_limit", "growatt_server", f"{sn}_battery_discharge_power_limit"),
        _entity(f"number.{sn}_battery_charge_soc_limit", "growatt_server", f"{sn}_battery_charge_soc_limit"),
        _entity(f"number.{sn}_battery_discharge_soc_limit", "growatt_server", f"{sn}_battery_discharge_soc_limit"),
        _entity(f"sensor.{sn}_lifetime_total_all_batteries_charged", "growatt_server", f"{sn}_lifetime_total_all_batteries_charged"),
        _entity(f"sensor.{sn}_lifetime_total_all_batteries_discharged", "growatt_server", f"{sn}_lifetime_total_all_batteries_discharged"),
        _entity(f"sensor.{sn}_lifetime_total_solar_energy", "growatt_server", f"{sn}_lifetime_total_solar_energy"),
        _entity(f"sensor.{sn}_lifetime_total_export_to_grid", "growatt_server", f"{sn}_lifetime_total_export_to_grid"),
        _entity(f"sensor.{sn}_lifetime_import_from_grid", "growatt_server", f"{sn}_lifetime_import_from_grid"),
        _entity(f"sensor.{sn}_lifetime_total_load_consumption", "growatt_server", f"{sn}_lifetime_total_load_consumption"),
        _entity(f"sensor.{sn}_lifetime_system_production", "growatt_server", f"{sn}_lifetime_system_production"),
        _entity(f"sensor.{sn}_lifetime_self_consumption", "growatt_server", f"{sn}_lifetime_self_consumption"),
        # Unrelated integration — should be ignored
        _entity("sensor.nordpool_kwh_se4_sek", "nordpool", "nordpool_kwh_se4_sek"),
    ]


# ---------------------------------------------------------------------------
# SolaX entity registry: native SolaX inverter via solax_modbus
# ---------------------------------------------------------------------------

def _solax_native_registry() -> list[dict]:
    """Entity registry for a native SolaX inverter via solax_modbus."""
    return [
        _entity("sensor.solax_battery_capacity", "solax_modbus", "solax_battery_capacity"),
        _entity("sensor.solax_battery_power_charge", "solax_modbus", "solax_battery_power_charge"),
        _entity("sensor.solax_battery_power_discharge", "solax_modbus", "solax_battery_power_discharge"),
        _entity("sensor.solax_measured_power", "solax_modbus", "solax_measured_power"),
        _entity("sensor.solax_grid_export", "solax_modbus", "solax_grid_export"),
        _entity("sensor.solax_pv_power_1", "solax_modbus", "solax_pv_power_1"),
        _entity("sensor.solax_house_load", "solax_modbus", "solax_house_load"),
        _entity("select.solax_remotecontrol_power_control", "solax_modbus", "solax_remotecontrol_power_control"),
        _entity("number.solax_remotecontrol_active_power", "solax_modbus", "solax_remotecontrol_active_power"),
        _entity("number.solax_remotecontrol_autorepeat_duration", "solax_modbus", "solax_remotecontrol_autorepeat_duration"),
        _entity("button.solax_remotecontrol_trigger", "solax_modbus", "solax_remotecontrol_trigger"),
        _entity("number.solax_battery_minimum_capacity", "solax_modbus", "solax_battery_minimum_capacity"),
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
        _entity("sensor.growatt_inverter_solax_battery_soc", "solax_modbus", "solax_battery_soc"),
        # Battery power
        _entity("sensor.growatt_inverter_solax_battery_charge_power", "solax_modbus", "solax_battery_charge_power"),
        _entity("sensor.growatt_inverter_solax_battery_discharge_power", "solax_modbus", "solax_battery_discharge_power"),
        # Grid power
        _entity("sensor.growatt_inverter_solax_total_forward_power", "solax_modbus", "solax_total_forward_power"),
        _entity("sensor.growatt_inverter_solax_total_reverse_power", "solax_modbus", "solax_total_reverse_power"),
        # Load power
        _entity("sensor.growatt_inverter_solax_total_load_power", "solax_modbus", "solax_total_load_power"),
        # Solar
        _entity("sensor.growatt_inverter_solax_pv_power_1", "solax_modbus", "solax_pv_power_1"),
        # Lifetime energy
        _entity("sensor.growatt_inverter_solax_total_battery_input_energy", "solax_modbus", "solax_total_battery_input_energy"),
        _entity("sensor.growatt_inverter_solax_total_battery_output_energy", "solax_modbus", "solax_total_battery_output_energy"),
        _entity("sensor.growatt_inverter_solax_total_solar_energy", "solax_modbus", "solax_total_solar_energy"),
        _entity("sensor.growatt_inverter_solax_total_grid_import", "solax_modbus", "solax_total_grid_import"),
        _entity("sensor.growatt_inverter_solax_total_grid_export", "solax_modbus", "solax_total_grid_export"),
        _entity("sensor.growatt_inverter_solax_total_yield", "solax_modbus", "solax_total_yield"),
        # EMS control entities (Growatt inverter via solax_modbus)
        _entity("number.growatt_inverter_solax_ems_charging_rate", "solax_modbus", "solax_ems_charging_rate"),
        _entity("number.growatt_inverter_solax_ems_discharging_rate", "solax_modbus", "solax_ems_discharging_rate"),
        _entity("number.growatt_inverter_solax_ems_charging_stop_soc", "solax_modbus", "solax_ems_charging_stop_soc"),
        _entity("number.growatt_inverter_solax_ems_discharging_stop_soc", "solax_modbus", "solax_ems_discharging_stop_soc"),
        _entity("switch.growatt_inverter_solax_charger_switch", "solax_modbus", "solax_charger_switch"),
    ]


# ---------------------------------------------------------------------------
# User-renamed entities: entity_id changed, unique_id unchanged
# ---------------------------------------------------------------------------

def _growatt_renamed_registry() -> list[dict]:
    """Growatt entities where the user renamed entity IDs in HA."""
    sn = "rkm0d7n04x"
    return [
        _entity("sensor.my_battery_soc", "growatt_server", f"{sn}_state_of_charge_soc"),
        _entity("sensor.battery_charging", "growatt_server", f"{sn}_battery_1_charging_w"),
        _entity("sensor.battery_discharging", "growatt_server", f"{sn}_battery_1_discharging_w"),
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
            _growatt_registry(), ["growatt_server"],
            self.ctrl.ENTITY_SUFFIX_MAP,
        )
        assert result["battery_soc"] == "sensor.rkm0d7n04x_state_of_charge_soc"
        assert result["battery_charge_power"] == "sensor.rkm0d7n04x_battery_1_charging_w"
        assert result["battery_discharge_power"] == "sensor.rkm0d7n04x_battery_1_discharging_w"
        assert result["import_power"] == "sensor.rkm0d7n04x_import_power"
        assert result["export_power"] == "sensor.rkm0d7n04x_export_power"
        assert result["pv_power"] == "sensor.rkm0d7n04x_internal_wattage"
        assert result["grid_charge"] == "switch.rkm0d7n04x_charge_from_grid"
        assert len(result) == 20  # all Growatt entities mapped

    def test_growatt_renamed_entities_still_match(self):
        """User-renamed entity IDs still match via unique_id."""
        result = self.ctrl._map_registry_entities(
            _growatt_renamed_registry(), ["growatt_server"],
            self.ctrl.ENTITY_SUFFIX_MAP,
        )
        # entity_id is the renamed version, but discovery found it via unique_id
        assert result["battery_soc"] == "sensor.my_battery_soc"
        assert result["battery_charge_power"] == "sensor.battery_charging"
        assert result["import_power"] == "sensor.grid_import"
        assert result["pv_power"] == "sensor.solar_production"
        assert len(result) == 7

    def test_solax_native_entities(self):
        """Native SolaX entities match via SOLAX_ENTITY_SUFFIX_MAP."""
        result = self.ctrl._map_registry_entities(
            _solax_native_registry(), ["solax_modbus", "solax"],
            self.ctrl.SOLAX_ENTITY_SUFFIX_MAP,
        )
        assert result["battery_soc"] == "sensor.solax_battery_capacity"
        assert result["battery_charge_power"] == "sensor.solax_battery_power_charge"
        assert result["solax_power_control_mode"] == "select.solax_remotecontrol_power_control"
        assert result["solax_active_power"] == "number.solax_remotecontrol_active_power"
        assert result["solax_battery_min_soc"] == "number.solax_battery_minimum_capacity"
        assert len(result) >= 10

    def test_solax_growatt_entities(self):
        """Growatt inverter via solax_modbus matches via SOLAX_ENTITY_SUFFIX_MAP."""
        result = self.ctrl._map_registry_entities(
            _solax_growatt_registry(), ["solax_modbus", "solax"],
            self.ctrl.SOLAX_ENTITY_SUFFIX_MAP,
        )
        assert result["battery_soc"] == "sensor.growatt_inverter_solax_battery_soc"
        assert result["battery_charge_power"] == "sensor.growatt_inverter_solax_battery_charge_power"
        assert result["battery_discharge_power"] == "sensor.growatt_inverter_solax_battery_discharge_power"
        assert result["import_power"] == "sensor.growatt_inverter_solax_total_forward_power"
        assert result["export_power"] == "sensor.growatt_inverter_solax_total_reverse_power"
        assert result["local_load_power"] == "sensor.growatt_inverter_solax_total_load_power"
        assert result["pv_power"] == "sensor.growatt_inverter_solax_pv_power_1"
        assert result["battery_charging_power_rate"] == "number.growatt_inverter_solax_ems_charging_rate"
        assert result["grid_charge"] == "switch.growatt_inverter_solax_charger_switch"
        assert len(result) == 18

    def test_platform_filter_excludes_other_integrations(self):
        """Entities from non-matching platforms are excluded."""
        result = self.ctrl._map_registry_entities(
            _growatt_registry(), ["solax_modbus"],
            self.ctrl.ENTITY_SUFFIX_MAP,
        )
        assert len(result) == 0

    def test_nordpool_entity_not_matched(self):
        """Nordpool entities are excluded by platform filter."""
        result = self.ctrl._map_registry_entities(
            _growatt_registry(), ["growatt_server"],
            self.ctrl.ENTITY_SUFFIX_MAP,
        )
        assert "nordpool_kwh_se4_sek" not in result.values()

    def test_empty_registry(self):
        result = self.ctrl._map_registry_entities(
            [], ["growatt_server"], self.ctrl.ENTITY_SUFFIX_MAP,
        )
        assert result == {}


# ---------------------------------------------------------------------------
# Tests: discover_sensors_from_registry
# ---------------------------------------------------------------------------


class TestDiscoverSensorsFromRegistry:
    def setup_method(self):
        self.ctrl = _make_controller()

    def test_growatt_only(self):
        """When only growatt_server entities exist, detected_platform is growatt."""
        sensors, platform = self.ctrl.discover_sensors_from_registry(
            _growatt_registry()
        )
        assert platform == "growatt"
        assert "growatt" in sensors
        assert len(sensors["growatt"]) == 20

    def test_solax_native_only(self):
        """When only native SolaX entities exist, detected_platform is solax."""
        sensors, platform = self.ctrl.discover_sensors_from_registry(
            _solax_native_registry()
        )
        assert platform == "solax"
        assert "solax" in sensors
        assert len(sensors["solax"]) >= 10

    def test_solax_growatt(self):
        """Growatt inverter via solax_modbus maps all sensors via SOLAX_ENTITY_SUFFIX_MAP."""
        sensors, platform = self.ctrl.discover_sensors_from_registry(
            _solax_growatt_registry()
        )
        assert platform == "solax"
        assert "solax" in sensors
        assert len(sensors["solax"]) == 18
        assert sensors["solax"]["battery_soc"] == "sensor.growatt_inverter_solax_battery_soc"
        assert sensors["solax"]["import_power"] == "sensor.growatt_inverter_solax_total_forward_power"

    def test_both_growatt_and_solax_present(self):
        """When both integrations exist, both are mapped; growatt is primary."""
        combined = _growatt_registry() + _solax_growatt_registry()
        sensors, platform = self.ctrl.discover_sensors_from_registry(combined)
        assert platform == "growatt"
        assert "growatt" in sensors
        assert "solax" in sensors
        assert len(sensors["growatt"]) == 20
        assert len(sensors["solax"]) == 18

    def test_renamed_growatt_entities_discovered(self):
        """User-renamed entities still discovered via unique_id."""
        sensors, platform = self.ctrl.discover_sensors_from_registry(
            _growatt_renamed_registry()
        )
        assert platform == "growatt"
        assert sensors["growatt"]["battery_soc"] == "sensor.my_battery_soc"
        assert sensors["growatt"]["pv_power"] == "sensor.solar_production"
