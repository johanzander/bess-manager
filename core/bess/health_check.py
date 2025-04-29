import logging
from datetime import datetime, timedelta

from .influxdb_helper import get_influxdb_config, get_sensor_data

logger = logging.getLogger(__name__)


def run_system_health_checks(system_manager):
    """Run all health checks across the system.

    Args:
        system_manager: BatterySystemManager instance

    Returns:
        dict: Complete health check results
    """
    all_component_checks = []

    # Collect health check results from each component
    # These can return multiple checks per component

    # 1. Energy Manager components
    if hasattr(system_manager._energy_manager, "check_health"):
        all_component_checks.extend(system_manager._energy_manager.check_health())

    # 2. Price Manager components
    if hasattr(system_manager._price_manager, "check_health"):
        all_component_checks.extend(system_manager._price_manager.check_health())

    # 3. Growatt Schedule Manager
    if hasattr(system_manager._schedule_manager, "check_health"):
        growatt_check = system_manager._schedule_manager.check_health(
            system_manager._controller
        )
        # Ensure this is formatted as a list for consistency
        if isinstance(growatt_check, dict):
            all_component_checks.append(growatt_check)
        else:
            all_component_checks.extend(growatt_check)

    # 4. Power Monitor
    if hasattr(system_manager._power_monitor, "check_health"):
        power_check = system_manager._power_monitor.check_health()
        # Ensure this is formatted as a list for consistency
        if isinstance(power_check, dict):
            all_component_checks.append(power_check)
        else:
            all_component_checks.extend(power_check)

    # 5. Historic data access
    if hasattr(system_manager, "_check_historical_data_access"):
        history_check = system_manager._check_historical_data_access()
        if history_check:
            all_component_checks.append(history_check)

    # Wrap results with metadata
    return {
        "timestamp": datetime.now().isoformat(),
        "system_mode": "demo" if system_manager._controller.test_mode else "normal",
        "checks": all_component_checks,
    }


def check_historical_data_access():
    """Check if the system can access historical data from InfluxDB.

    Returns:
        dict: Health check result for historical data access
    """

    result = {
        "name": "Historical Data Access",
        "description": "Provides past energy flow data for analysis and optimization",
        "required": False,
        "status": "UNKNOWN",
        "checks": [],
        "last_run": datetime.now().isoformat(),
    }

    # Check InfluxDB configuration
    config_check = {
        "name": "InfluxDB Configuration",
        "key": None,
        "entity_id": None,
        "status": "UNKNOWN",
        "value": None,
        "error": None,
    }

    try:
        config = get_influxdb_config()

        if config["url"] and config["username"] and config["password"]:
            config_check["status"] = "OK"
            config_check["value"] = f"URL: {config['url']}"
        else:
            config_check["status"] = "ERROR"
            missing = []
            if not config["url"]:
                missing.append("URL")
            if not config["username"]:
                missing.append("Username")
            if not config["password"]:
                missing.append("Password")
            config_check["error"] = f"Missing configuration: {', '.join(missing)}"
    except Exception as e:
        config_check["status"] = "ERROR"
        config_check["error"] = f"Failed to load InfluxDB configuration: {e}"

    result["checks"].append(config_check)

    # Test data retrieval if configuration is OK
    if config_check["status"] == "OK":
        data_check = {
            "name": "Data Retrieval",
            "key": None,
            "entity_id": None,
            "status": "UNKNOWN",
            "value": None,
            "error": None,
        }

        try:
            # Try to get data from one hour ago
            one_hour_ago = datetime.now() - timedelta(hours=1)
            test_sensors = ["rkm0d7n04x_statement_of_charge_soc"]

            response = get_sensor_data(test_sensors, one_hour_ago)

            if response["status"] == "success" and response["data"]:
                data_check["status"] = "OK"
                data_check["value"] = "Successfully retrieved historical data"
            else:
                data_check["status"] = "WARNING"
                data_check["error"] = "No historical data available"
        except Exception as e:
            data_check["status"] = "ERROR"
            data_check["error"] = f"Failed to retrieve historical data: {e}"

        result["checks"].append(data_check)

    # Determine overall status
    if all(check["status"] == "OK" for check in result["checks"]):
        result["status"] = "OK"
    elif any(check["status"] == "ERROR" for check in result["checks"]):
        result["status"] = "ERROR"
    else:
        result["status"] = "WARNING"

    return result
