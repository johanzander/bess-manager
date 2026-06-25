import logging
import math
from datetime import datetime

from .influxdb_helper import (
    get_influxdb_config,
    is_influxdb_configured,
    test_influxdb_connection,
)

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
    required_methods: list[str],
) -> str:
    """Determine health check status based on required vs optional sensors.

    Args:
        health_check_results: List of health check results (after method calls)
        working_sensors: Count of working sensors (unused, kept for compatibility)
        required_methods: List of method names that are required.
            Methods not in this list are treated as optional.

    Returns:
        Status string: "OK", "WARNING", or "ERROR"
    """

    # Count required vs optional sensors that are actually working
    required_working = 0
    required_total = 0
    optional_working = 0
    optional_total = 0

    for check_result in health_check_results:
        # Intentionally unconfigured sensors don't count toward health
        if check_result.get("status") == "SKIPPED":
            continue

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

    # ERROR if required methods were specified but none are configured at all
    if required_methods and required_total == 0:
        return "ERROR"

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
) -> dict:
    """Generic health check function that can be used by any component.

    Severity is derived from ``is_required``:
    - ``is_required=True``  → all methods are required → failure → ERROR
    - ``is_required=False`` → all methods are optional  → failure → WARNING

    Args:
        component_name: Name of the component being checked
        description: Description of what the component does
        is_required: Whether this component is required for system operation.
            Also controls severity: required components show ERROR on failure,
            optional components show WARNING.
        controller: The controller instance with validate_methods_sensors method
        all_methods: List of all method names this component uses

    Returns:
        Health check result dictionary
    """
    required_methods = all_methods if is_required else []
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

        if method_info["status"] == "not_configured":
            # Sensor intentionally not configured by user — skip silently
            check_result.update(
                {
                    "status": "SKIPPED",
                    "error": "Not configured",
                    "displayValue": "Not configured",
                }
            )
            health_check["checks"].append(check_result)
            continue

        if method_info["status"] == "ok":
            # Test the actual method
            try:
                method = getattr(controller, method_info["method_name"])
                value = method()

                # Handle different return types
                if isinstance(value, list):
                    # Handle list values (like predictions)
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
            # Distinguish between temporarily unavailable and truly broken
            if method_info["status"] in ("entity_unavailable",):
                check_result.update(
                    {
                        "status": "WARNING",
                        "error": method_info.get("error", "Entity unavailable"),
                        "rawValue": None,
                        "displayValue": "Unavailable",
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

    # 2. Inverter Controller (Battery Control) - core control system
    inverter_checks = system_manager._inverter_controller.check_health(
        system_manager._controller
    )
    all_component_checks.extend(inverter_checks)

    # 3. & 4. SensorCollector (Battery Monitoring + Energy Monitoring) - operational sensors
    active_consumption_strategy = system_manager.home_settings.consumption_strategy
    sensor_collector_health = system_manager.sensor_collector.check_health(
        active_consumption_strategy
    )
    all_component_checks.extend(sensor_collector_health)

    # 5. Power Monitor (Power Monitoring) - real-time power flow tracking
    if system_manager._power_monitor is not None:
        power_checks = system_manager._power_monitor.check_health()
    else:
        power_checks = [
            {
                "name": "Power Monitoring",
                "description": "Monitors home power consumption and adapts battery charging",
                "required": False,
                "status": "OK",
                "checks": [
                    {
                        "name": "Power Monitor Status",
                        "entity_id": None,
                        "status": "OK",
                        "error": "Disabled — enable power monitoring in Settings → Home",
                    }
                ],
                "last_run": datetime.now().isoformat(),
            }
        ]
    all_component_checks.extend(power_checks)

    # 6. Discharge Control (EV charger integration) — optional, only checked when configured
    if system_manager._controller.sensors.get("discharge_inhibit"):
        discharge_check = perform_health_check(
            component_name="Discharge Control",
            description="Prevents battery discharge while EV is charging",
            is_required=False,
            controller=system_manager._controller,
            all_methods=["get_discharge_inhibit_active"],
        )
        all_component_checks.append(discharge_check)

    # 7. Historic data access
    history_checks = check_historical_data_access()
    all_component_checks.extend(history_checks)

    # Failure statistics from runtime tracker
    failure_stats = system_manager._runtime_failure_tracker.get_failure_stats()

    # Wrap results with metadata
    return {
        "timestamp": datetime.now().isoformat(),
        "system_mode": "demo" if system_manager._controller.test_mode else "normal",
        "checks": all_component_checks,
        "failure_stats": failure_stats,
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

    if not is_influxdb_configured():
        config_check["status"] = "NOT_CONFIGURED"
        config_check["formatted_value"] = "Not configured (optional)"
        logger.info("InfluxDB is not configured — skipping (optional component)")
        result["checks"].append(config_check)
        result["status"] = "NOT_CONFIGURED"
        return [result]

    try:
        config = get_influxdb_config()
        config_check["status"] = "OK"
        config_check["value"] = f"URL: {config['url']}"
        config_check["formatted_value"] = f"URL: {config['url']}"
        logger.info("InfluxDB credentials configured")
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
            connection_result = test_influxdb_connection()

            if connection_result["status"] == "ok":
                data_check["status"] = "OK"
                data_check["value"] = connection_result["message"]
                data_check["formatted_value"] = connection_result["message"]
            elif connection_result["status"] == "misconfigured":
                data_check["status"] = "WARNING"
                data_check["error"] = connection_result["message"]
            else:
                data_check["status"] = "WARNING"
                data_check["error"] = connection_result["message"]
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
