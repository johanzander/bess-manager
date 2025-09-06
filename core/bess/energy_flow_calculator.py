"""
EnergyFlowCalculator - Extract and preserve the sophisticated energy flow logic.

This preserves the excellent energy flow calculation logic from energy_manager.py
while separating it from sensor collection and predictions.
"""

import logging

logger = logging.getLogger(__name__)


class EnergyFlowCalculator:
    """Calculates all energy flows in the systemand validates energy balance."""

    def __init__(self, battery_capacity_kwh: float, ha_controller):
        """Initialize energy flow calculator.

        Args:
            battery_capacity_kwh: Total battery capacity for SOC calculations
            ha_controller: HA controller for sensor resolution (required)
        """
        self.battery_capacity = battery_capacity_kwh
        self.ha_controller = ha_controller
        self.sensor_to_flow_map = self._build_sensor_flow_mapping()

    def _build_sensor_flow_mapping(self) -> dict[str, str]:
        """Build sensor to flow mapping using the abstraction layer.

        Returns mapping of entity IDs (without 'sensor.' prefix) to flow field names.
        """
        # Define mapping using sensor keys
        sensor_key_to_flow = {
            "lifetime_battery_charged": "battery_charged",
            "lifetime_battery_discharged": "battery_discharged",
            "lifetime_solar_energy": "solar_production",
            "lifetime_import_from_grid": "import_from_grid",
            "lifetime_export_to_grid": "export_to_grid",
            "lifetime_load_consumption": "load_consumption",
            "lifetime_system_production": "system_production",
            "lifetime_self_consumption": "self_consumption",
            "ev_energy_meter": "aux_load",
        }
        # Resolve to actual entity IDs
        resolved_mapping = {}
        for sensor_key, flow_name in sensor_key_to_flow.items():
            entity_id = self.ha_controller.resolve_sensor_for_influxdb(sensor_key)
            if entity_id:
                resolved_mapping[entity_id] = flow_name
            else:
                # Sensor not configured - skip
                logger.debug(f"Sensor key '{sensor_key}' not configured, skipping")
        return resolved_mapping

    def calculate_hourly_flows(
        self,
        current_readings: dict[str, float],
        previous_readings: dict[str, float],
        hour_of_day: int | None = None,
    ) -> dict[str, float] | None:
        """Calculate energy flows between two sensor readings.

        Args:
            current_readings: Current hour sensor readings
            previous_readings: Previous hour sensor readings
            hour_of_day: Hour for time-based validation (0-23)

        Returns:
            Dict of calculated energy flows or None if calculation fails
        """
        if not current_readings or not previous_readings:
            logger.warning("Missing readings - cannot calculate flows")
            return None

        # Initialize flows with zeros
        flows = {
            "battery_charged": 0.0,
            "battery_discharged": 0.0,
            "solar_production": 0.0,
            "self_consumption": 0.0,
            "export_to_grid": 0.0,
            "load_consumption": 0.0,
            "import_from_grid": 0.0,
            "grid_to_battery": 0.0,
            "solar_to_battery": 0.0,
            "system_production": 0.0,
            "aux_load": 0.0,
        }

        # Use pre-built sensor to flow mapping
        sensor_to_flow = self.sensor_to_flow_map

        # Calculate differences for each sensor
        for sensor_name, flow_key in sensor_to_flow.items():
            current_value = current_readings.get(sensor_name)
            previous_value = previous_readings.get(sensor_name)

            if current_value is None or previous_value is None:
                logger.debug(
                    "Missing value for %s in hour %s", sensor_name, hour_of_day
                )
                continue

            try:
                current_value = float(current_value)
                previous_value = float(previous_value)

                # Handle day rollover (when value decreases)
                if current_value < previous_value:
                    logger.info(
                        "Detected rollover for %s: %s → %s",
                        sensor_name,
                        previous_value,
                        current_value,
                    )
                    flows[flow_key] = current_value
                else:
                    flows[flow_key] = current_value - previous_value

            except (ValueError, TypeError) as e:
                logger.warning("Error calculating flow for %s: %s", sensor_name, e)

        # Calculate derived flows
        return self._calculate_derived_flows(flows, hour_of_day)

    def _calculate_derived_flows(
        self, flows: dict[str, float], hour_of_day: int | None = None
    ) -> dict[str, float]:
        """Calculate derived flows"""

        solar_production = flows.get("solar_production", 0)
        battery_charged = flows.get("battery_charged", 0)
        battery_discharged = flows.get("battery_discharged", 0)
        export_to_grid = flows.get("export_to_grid", 0)
        self_consumption = flows.get("self_consumption", 0)

        solar_to_battery = max(
            0,
            solar_production - export_to_grid - self_consumption + battery_discharged,
        )
        solar_to_battery = min(solar_to_battery, battery_charged, solar_production)

        flows["solar_to_battery"] = solar_to_battery
        flows["grid_to_battery"] = max(0, battery_charged - solar_to_battery)

        logger.debug(
            "Hour %s: Solar to battery = %.2f kWh (from new sensors)",
            hour_of_day,
            flows["solar_to_battery"],
        )
        logger.debug(
            "Hour %s: Grid to battery = %.2f kWh (from new sensors)",
            hour_of_day,
            flows["grid_to_battery"],
        )

        flows["aux_load"] = flows.get("aux_load", 0.0)
        return flows
