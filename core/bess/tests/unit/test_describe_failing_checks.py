"""Tests for health_check.describe_failing_checks — shared by the health
recovery tracker and the dashboard health summary API to name the specific
sensor(s)/entity behind a component's ERROR/WARNING status (#215).
"""

from core.bess.health_check import describe_failing_checks


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
