import logging
from datetime import datetime, timedelta

from .influxdb_helper import get_influxdb_config, get_sensor_data

logger = logging.getLogger(__name__)


def format_sensor_value_with_unit(value, method_name: str, controller) -> str:
    """Format sensor value with appropriate unit based on METHOD_SENSOR_MAP.

    Args:
        value: Raw sensor value
        method_name: Method name to look up unit info
        controller: Controller with METHOD_SENSOR_MAP

    Returns:
        Formatted string with unit (e.g., "20.0 %", "3.5 kWh")
    """
    if value is None:
        return "N/A"

    # Handle string values (like "List with 24 values")
    if isinstance(value, str):
        return value

    # Handle boolean values
    if isinstance(value, bool):
        return "Enabled" if value else "Disabled"

    # For numeric values, get unit from METHOD_SENSOR_MAP
    try:
        sensor_info = controller.METHOD_SENSOR_MAP.get(method_name, {})
        unit = sensor_info.get("unit", "")

        if isinstance(value, int | float):
            # Get precision from METHOD_SENSOR_MAP (centralized formatting rules)
            precision = sensor_info.get("precision", 2)  # Default to 2 decimal places

            # Use precision from sensor map with thousands separators
            formatted = f"{value:,.{precision}f}"
        else:
            formatted = str(value)

        return f"{formatted} {unit}" if unit else formatted

    except Exception:
        # Fallback if unit lookup fails
        return str(value)


def determine_health_status(
    health_check_results: list,
    working_sensors: int,
    required_methods: list | None = None,
) -> str:
    """Generic method to determine health check status based on required vs optional sensors.

    Args:
        health_check_results: List of health check results (after method calls)
        working_sensors: Count of working sensors (unused, kept for compatibility)
        required_methods: List of method names that are required (optional sensors are non-required)

    Returns:
        Status string: "OK", "WARNING", or "ERROR"
    """
    if not required_methods:
        # If no required methods specified, all methods are optional
        required_methods = []

    # Count required vs optional sensors that are actually working
    required_working = 0
    required_total = 0
    optional_working = 0
    optional_total = 0

    for check_result in health_check_results:
        method_name = check_result.get("method_name", "unknown")
        # A sensor is working if it has status "OK" after method call testing
        is_working = check_result.get("status") == "OK"

        if method_name in required_methods:
            required_total += 1
            if is_working:
                required_working += 1
        else:
            optional_total += 1
            if is_working:
                optional_working += 1

    # ERROR if not all required sensors are working
    # WARNING if any optional sensor is not working
    # OK if all sensors are working
    if required_working < required_total:
        return "ERROR"
    elif optional_working < optional_total:
        return "WARNING"
    else:
        return "OK"


def perform_health_check(
    component_name: str,
    description: str,
    is_required: bool,
    controller,
    all_methods: list[str],
    required_methods: list[str] | None = None,
) -> dict:
    """Generic health check function that can be used by any component.

    Args:
        component_name: Name of the component being checked
        description: Description of what the component does
        is_required: Whether this component is required for system operation
        controller: The controller instance with validate_methods_sensors method
        all_methods: List of all method names this component uses
        required_methods: List of method names that are required (None = all required)

    Returns:
        Health check result dictionary
    """
    health_check = {
        "name": component_name,
        "description": description,
        "required": is_required,
        "status": "UNKNOWN",
        "checks": [],
        "last_run": datetime.now().isoformat(),
    }

    # Get sensor diagnostics for all methods
    sensor_diagnostics = controller.validate_methods_sensors(all_methods)
    working_sensors = 0

    for method_info in sensor_diagnostics:
        check_result = {
            "name": method_info.get("name", method_info.get("method_name", "Unknown")),
            "key": method_info.get("sensor_key", method_info.get("method_name")),
            "method_name": method_info.get("method_name"),
            "entity_id": method_info.get("entity_id", "Not mapped"),
            "status": "UNKNOWN",
            "rawValue": None,
            "displayValue": "N/A",
            "error": None,
        }

        if method_info["status"] == "ok":
            # Test the actual method
            try:
                method = getattr(controller, method_info["method_name"])
                value = method()

                # Handle different return types
                if isinstance(value, list):
                    # Handle list values (like predictions)
                    import math

                    if len(value) == 0:
                        check_result.update(
                            {
                                "status": "WARNING",
                                "error": "Empty list returned",
                                "rawValue": value,
                                "displayValue": "Empty list",
                            }
                        )
                    else:
                        nan_count = sum(
                            1 for v in value if isinstance(v, float) and math.isnan(v)
                        )
                        if nan_count == 0:
                            display_value = f"List with {len(value)} values"
                            check_result.update(
                                {
                                    "status": "OK",
                                    "rawValue": value,
                                    "displayValue": display_value,
                                }
                            )
                            working_sensors += 1
                        else:
                            check_result.update(
                                {
                                    "status": "WARNING",
                                    "error": f"List contains {nan_count}/{len(value)} NaN values",
                                    "rawValue": value,
                                    "displayValue": "Contains NaN",
                                }
                            )
                elif value is not None:
                    import math

                    if isinstance(value, int | float) and math.isnan(value):
                        check_result.update(
                            {
                                "status": "WARNING",
                                "error": "Sensor returns NaN value",
                                "rawValue": value,
                                "displayValue": "NaN",
                            }
                        )
                    elif value >= 0:
                        display_value = format_sensor_value_with_unit(
                            value, method_info.get("method_name"), controller
                        )
                        check_result.update(
                            {
                                "status": "OK",
                                "rawValue": value,
                                "displayValue": display_value,
                            }
                        )
                        working_sensors += 1
                    else:
                        # Negative values might be valid for some sensors (e.g., discharge power)
                        display_value = format_sensor_value_with_unit(
                            value, method_info.get("method_name"), controller
                        )
                        check_result.update(
                            {
                                "status": "OK",
                                "rawValue": value,
                                "displayValue": display_value,
                            }
                        )
                        working_sensors += 1
                else:
                    check_result.update(
                        {
                            "status": "WARNING",
                            "error": "Method returned None",
                            "rawValue": None,
                            "displayValue": "N/A",
                        }
                    )
            except Exception as e:
                check_result.update(
                    {
                        "status": "ERROR",
                        "error": f"Method call failed: {e!s}",
                        "rawValue": None,
                        "displayValue": "N/A",
                    }
                )
        else:
            check_result.update(
                {
                    "status": "ERROR",
                    "error": method_info.get("error", "Unknown error"),
                    "rawValue": None,
                    "displayValue": "N/A",
                }
            )
        health_check["checks"].append(check_result)

    # Determine overall status using the generic method
    status = determine_health_status(
        health_check["checks"], working_sensors, required_methods
    )
    health_check["status"] = status

    return health_check


def run_system_health_checks(system_manager):
    """Run all health checks across the system.

    Args:
        system_manager: BatterySystemManager instance

    Returns:
        dict: Complete health check results
    """
    all_component_checks = []

    # Collect health check results from each component in priority order
    # All health check methods consistently return lists

    # 1. Price Manager (Electricity Price) - fundamental input for optimization
    price_checks = system_manager._price_manager.check_health()
    all_component_checks.extend(price_checks)

    # 2. Growatt Schedule Manager (Battery Control) - core control system
    growatt_checks = system_manager._schedule_manager.check_health(
        system_manager._controller
    )
    all_component_checks.extend(growatt_checks)

    # 3. & 4. SensorCollector (Battery Monitoring + Energy Monitoring) - operational sensors
    sensor_collector_health = system_manager.sensor_collector.check_health()
    all_component_checks.extend(sensor_collector_health)

    # 5. Power Monitor (Power Monitoring) - real-time power flow tracking
    power_checks = system_manager._power_monitor.check_health()
    all_component_checks.extend(power_checks)

    # 6. Historic data access
    history_checks = check_historical_data_access()
    all_component_checks.extend(history_checks)

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
        "formatted_value": "N/A",
        "error": None,
    }

    try:
        config = get_influxdb_config()

        if config["url"] and config["username"] and config["password"]:
            config_check["status"] = "OK"
            config_check["value"] = f"URL: {config['url']}"
            config_check["formatted_value"] = f"URL: {config['url']}"
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

    if isinstance(config_check, dict):
        result["checks"].append(config_check)
    else:
        logger.error(
            f"Non-dict config_check encountered in historical data access: {config_check} (type: {type(config_check)})"
        )

    # Test data retrieval if configuration is OK
    if config_check["status"] == "OK":
        data_check = {
            "name": "Data Retrieval",
            "key": None,
            "entity_id": None,
            "status": "UNKNOWN",
            "value": None,
            "formatted_value": "N/A",
            "error": None,
        }

        try:
            # Try to get data from one hour ago
            one_hour_ago = datetime.now() - timedelta(hours=1)
            # Test with any available sensor - InfluxDB connectivity is what matters
            # The actual sensor data availability will be tested by the sensor collector
            test_sensors = [
                "battery_soc"
            ]  # Use generic key, let the system handle mapping

            response = get_sensor_data(test_sensors, stop_time=one_hour_ago)

            if response["status"] == "success":
                data_check["status"] = "OK"
                data_check["value"] = "InfluxDB connection successful"
                data_check["formatted_value"] = "InfluxDB connection successful"
            else:
                data_check["status"] = "WARNING"
                data_check["error"] = (
                    f"InfluxDB connectivity issue: {response.get('message', 'Unknown error')}"
                )
        except Exception as e:
            data_check["status"] = "ERROR"
            data_check["error"] = f"Failed to connect to InfluxDB: {e}"

        result["checks"].append(data_check)

    # Determine overall status
    if all(check["status"] == "OK" for check in result["checks"]):
        result["status"] = "OK"
    elif any(check["status"] == "ERROR" for check in result["checks"]):
        result["status"] = "ERROR"
    else:
        result["status"] = "WARNING"

    return [result]
