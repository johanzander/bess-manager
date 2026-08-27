"""Tests for health_check.describe_failing_checks — shared by the health
recovery tracker and the dashboard health summary API to name the specific
sensor(s)/entity behind a component's ERROR/WARNING status (#215).

Also covers resolve_component_device, the sibling helper that resolves the
underlying device a component reports about, reused by the same two callers.
"""

from core.bess.health_check import describe_failing_checks, resolve_component_device


def test_names_the_single_failing_check():
    component = {
        "name": "Battery Control",
        "status": "ERROR",
        "checks": [
            {
                "name": "Battery Charging Power Rate",
                "entity_id": "number.growatt_battery_charging_power_rate",
                "status": "WARNING",
                "error": "Entity state is 'unavailable'",
            },
            {
                "name": "Grid Charge Enabled",
                "entity_id": "switch.growatt_grid_charge",
                "status": "OK",
                "error": None,
            },
        ],
    }

    assert (
        describe_failing_checks(component)
        == "Battery Charging Power Rate (number.growatt_battery_charging_power_rate)"
    )


def test_joins_multiple_failing_checks():
    component = {
        "name": "Battery Control",
        "status": "ERROR",
        "checks": [
            {
                "name": "Battery Charging Power Rate",
                "entity_id": "number.growatt_battery_charging_power_rate",
                "status": "ERROR",
                "error": "unavailable",
            },
            {
                "name": "Grid Charge Enabled",
                "entity_id": "switch.growatt_grid_charge",
                "status": "WARNING",
                "error": "unavailable",
            },
        ],
    }

    assert describe_failing_checks(component) == (
        "Battery Charging Power Rate (number.growatt_battery_charging_power_rate); "
        "Grid Charge Enabled (switch.growatt_grid_charge)"
    )


def test_falls_back_to_name_without_entity_id():
    component = {
        "name": "Historical Data Access",
        "status": "WARNING",
        "checks": [
            {
                "name": "Data Retrieval",
                "entity_id": None,
                "status": "WARNING",
                "error": "x",
            }
        ],
    }

    assert describe_failing_checks(component) == "Data Retrieval"


def test_empty_when_no_checks_present():
    assert describe_failing_checks({"name": "X", "status": "ERROR", "checks": []}) == ""


def test_empty_when_checks_key_missing():
    assert describe_failing_checks({"name": "X", "status": "ERROR"}) == ""


def test_resolve_component_device_prefers_failing_check_over_healthy_first() -> None:
    """A component's device is the failing sub-check's device, not the first
    resolvable entry. A mixed-status component (e.g. Energy Monitoring reads
    smart-meter and PV-inverter sensors) must not attribute its failure to a
    healthy device that happens to be listed first."""
    component = {
        "name": "Energy Monitoring",
        "status": "ERROR",
        "checks": [
            {
                "name": "Grid Import",
                "entity_id": "sensor.meter_import",
                "status": "OK",
            },
            {
                "name": "Solar Production",
                "entity_id": "sensor.inverter_solar",
                "status": "ERROR",
                "error": "Method call failed",
            },
        ],
    }
    entity_to_device = {
        "sensor.meter_import": "dev-meter",
        "sensor.inverter_solar": "dev-inverter",
    }
    device_names = {"dev-meter": "Smart Meter", "dev-inverter": "Solar Inverter"}

    assert (
        resolve_component_device(component, entity_to_device, device_names)
        == "Solar Inverter"
    )


def test_resolve_component_device_falls_back_to_resolvable_check() -> None:
    """When no failing sub-check carries a resolvable entity, fall back to any
    resolvable sub-check before giving up on the component's own name."""
    component = {
        "name": "Battery Control",
        "status": "ERROR",
        "checks": [
            {
                "name": "Grid Charge Enabled",
                "entity_id": None,
                "status": "ERROR",
            },
            {
                "name": "Battery Charging Power Rate",
                "entity_id": "number.growatt_battery_charging_power_rate",
                "status": "OK",
            },
        ],
    }
    entity_to_device = {"number.growatt_battery_charging_power_rate": "dev-inverter"}
    device_names = {"dev-inverter": "Growatt Inverter"}

    assert (
        resolve_component_device(component, entity_to_device, device_names)
        == "Growatt Inverter"
    )


def test_resolve_component_device_unmapped_falls_back_to_component_name() -> None:
    component = {
        "name": "Historical Data Access",
        "status": "ERROR",
        "checks": [
            {
                "name": "Data Retrieval",
                "entity_id": "Not mapped",
                "status": "ERROR",
            }
        ],
    }

    assert resolve_component_device(component, {}, {}) == "Historical Data Access"
