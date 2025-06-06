"""
EnergyFlowCalculator - Extract and preserve the sophisticated energy flow logic.

This preserves the excellent energy flow calculation logic from energy_manager.py
while separating it from sensor collection and predictions.
"""

import logging

logger = logging.getLogger(__name__)


class EnergyFlowCalculator:
    """Calculates complex energy flows and validates energy balance.

    This class contains the sophisticated energy flow logic extracted from
    energy_manager.py, preserving all the edge cases and validation logic.
    """

    def __init__(self, battery_capacity_kwh: float):
        """Initialize energy flow calculator.

        Args:
            battery_capacity_kwh: Total battery capacity for SOC calculations
        """
        self.battery_capacity = battery_capacity_kwh

    def calculate_hourly_flows(
        self,
        current_readings: dict[str, float],
        previous_readings: dict[str, float],
        hour_of_day: int | None = None,
    ) -> dict[str, float] | None:
        """Calculate energy flows between two sensor readings.

        This preserves the exact logic from energy_manager._calculate_hourly_energy_flows()

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
            "system_production": 0.0,
            "self_consumption": 0.0,
            "export_to_grid": 0.0,
            "load_consumption": 0.0,
            "import_from_grid": 0.0,
            "grid_to_battery": 0.0,
            "solar_to_battery": 0.0,
            "aux_load": 0.0,
            "system_production_total": 0.0,
            "self_consumption_total": 0.0,
        }

        # Extract flows from cumulative sensors - PRESERVE EXACT LOGIC
        sensor_to_flow = {
            "rkm0d7n04x_lifetime_total_all_batteries_charged": "battery_charged",
            "rkm0d7n04x_lifetime_total_all_batteries_discharged": "battery_discharged",
            "rkm0d7n04x_lifetime_total_solar_energy": "system_production",
            "rkm0d7n04x_lifetime_total_export_to_grid": "export_to_grid",
            "rkm0d7n04x_lifetime_total_load_consumption": "load_consumption",
            "rkm0d7n04x_lifetime_import_from_grid": "import_from_grid",
            "zap263668_energy_meter": "aux_load",
            "rkm0d7n04x_lifetime_system_production": "system_production_total",
            "rkm0d7n04x_lifetime_self_consumption": "self_consumption_total",
        }

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
        """Calculate derived flows - EXACT COPY from energy_manager._calculate_derived_flows()"""

        solar_production = flows.get("system_production", 0)
        battery_charged = flows.get("battery_charged", 0)
        battery_discharge = flows.get("battery_discharged", 0)
        grid_export = flows.get("export_to_grid", 0)

        # Check if we have the new sensors
        has_system_production = "system_production_total" in flows
        has_self_consumption = "self_consumption_total" in flows

        # Calculate self-consumption if not directly measured
        if not has_self_consumption:
            flows["self_consumption"] = max(0, solar_production - grid_export)
            logger.debug(
                "Hour %s: Self consumption = %.2f kWh (calculated)",
                hour_of_day,
                flows["self_consumption"],
            )
        else:
            flows["self_consumption"] = flows["self_consumption_total"]
            logger.debug(
                "Hour %s: Self consumption = %.2f kWh (from sensor)",
                hour_of_day,
                flows["self_consumption"],
            )

        # Calculate solar_to_battery and grid_to_battery
        if has_system_production and has_self_consumption:
            # More accurate method with new sensors
            self_consumption_total = flows.get("self_consumption_total", 0)

            solar_to_battery = max(
                0,
                solar_production
                - grid_export
                - self_consumption_total
                + battery_discharge,
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
        else:
            # Fallback method using time-of-day assumptions
            is_night = hour_of_day is not None and (
                hour_of_day < 6 or hour_of_day >= 20
            )

            if is_night and battery_charged > 0:
                flows["grid_to_battery"] = battery_charged
                flows["solar_to_battery"] = 0.0
                logger.debug(
                    "Hour %s: Using night-time assumption - all charging (%.2f kWh) from grid",
                    hour_of_day,
                    battery_charged,
                )
            else:
                solar_to_battery = max(0, min(solar_production, battery_charged))
                flows["solar_to_battery"] = solar_to_battery
                flows["grid_to_battery"] = max(0, battery_charged - solar_to_battery)
                logger.debug(
                    "Hour %s: Solar to battery = %.2f kWh (based on solar availability)",
                    hour_of_day,
                    flows["solar_to_battery"],
                )
                logger.debug(
                    "Hour %s: Grid to battery = %.2f kWh (remaining charge)",
                    hour_of_day,
                    flows["grid_to_battery"],
                )

        flows["aux_load"] = flows.get("aux_load", 0.0)
        return flows

    def validate_energy_flows(
        self, flows: dict[str, float], hour_of_day: int | None = None
    ) -> dict[str, float]:
        """Validate and correct energy flows - PRESERVE EXACT LOGIC from energy_manager."""

        validated = flows.copy() if flows else {}
        if not validated:
            return validated

        # Check if we have new sensors
        has_system_production = "system_production_total" in validated
        has_self_consumption = "self_consumption_total" in validated

        # 1. Night hours validation (6pm-6am) - PRESERVE EXACT LOGIC
        is_night = hour_of_day is not None and (hour_of_day < 6 or hour_of_day >= 20)
        if is_night:
            if validated.get("system_production", 0) > 0.1:
                logger.warning(
                    "Hour %s: Zeroing incorrect solar production (%.2f kWh) during night hours",
                    hour_of_day,
                    validated.get("system_production", 0),
                )
                validated["system_production"] = 0.0
                validated["self_consumption"] = 0.0
                validated["export_to_grid"] = 0.0
                validated["solar_to_battery"] = 0.0

            if (
                validated.get("battery_charged", 0) > 0.1
                and abs(
                    validated.get("grid_to_battery", 0)
                    - validated.get("battery_charged", 0)
                )
                > 0.5
            ):
                logger.warning(
                    "Hour %s: Correcting grid-to-battery (%.2f kWh) to match battery charge (%.2f kWh) at night",
                    hour_of_day,
                    validated.get("grid_to_battery", 0),
                    validated.get("battery_charged", 0),
                )
                validated["grid_to_battery"] = validated.get("battery_charged", 0)
                validated["solar_to_battery"] = 0.0

        # 2. Physical constraints - PRESERVE EXACT LOGIC
        if (
            validated.get("grid_to_battery", 0)
            > validated.get("battery_charged", 0) + 0.5
        ):
            logger.warning(
                "Hour %s: Grid-to-battery (%.2f kWh) exceeds battery charge (%.2f kWh) - correcting",
                hour_of_day,
                validated.get("grid_to_battery", 0),
                validated.get("battery_charged", 0),
            )
            validated["grid_to_battery"] = validated.get("battery_charged", 0)

        if (
            validated.get("solar_to_battery", 0)
            > validated.get("system_production", 0) + 0.5
        ):
            logger.warning(
                "Hour %s: Solar-to-battery (%.2f kWh) exceeds solar production (%.2f kWh) - correcting",
                hour_of_day,
                validated.get("solar_to_battery", 0),
                validated.get("system_production", 0),
            )
            validated["solar_to_battery"] = validated.get("system_production", 0)

        # 3. Energy balance verification - PRESERVE EXACT LOGIC
        if has_system_production and has_self_consumption:
            energy_in = validated.get("import_from_grid", 0) + validated.get(
                "system_production_total", 0
            )
            energy_out = validated.get("load_consumption", 0) + validated.get(
                "export_to_grid", 0
            )
            logger.debug(
                "Hour %s: Energy balance with new sensors: In=%.2f kWh, Out=%.2f kWh",
                hour_of_day,
                energy_in,
                energy_out,
            )
        else:
            energy_in = validated.get("import_from_grid", 0) + validated.get(
                "system_production", 0
            )
            battery_charged = validated.get("battery_charged", 0)
            battery_discharge = validated.get("battery_discharged", 0)
            energy_out = (
                validated.get("load_consumption", 0)
                + validated.get("export_to_grid", 0)
                + validated.get("aux_load", 0)
                + battery_charged
                - battery_discharge
            )
            logger.debug(
                "Hour %s: Energy balance: In=%.2f kWh, Out=%.2f kWh, Battery net=%.2f kWh",
                hour_of_day,
                energy_in,
                energy_out,
                battery_charged - battery_discharge,
            )

        # Check balance with tolerance
        balance_tolerance = max(0.5, energy_in * 0.05)
        if abs(energy_in - energy_out) > balance_tolerance:
            logger.warning(
                "Hour %s: Energy balance discrepancy - Input=%.2f kWh, Output=%.2f kWh, Difference=%.2f kWh",
                hour_of_day,
                energy_in,
                energy_out,
                abs(energy_in - energy_out),
            )

        return validated

    def calculate_soc_from_energy_delta(
        self,
        previous_soc: float,
        battery_charged: float,
        battery_discharge: float,
        min_soc_percent: float,
    ) -> float:
        """Calculate new SOC from previous SOC and energy changes.

        Args:
            previous_soc: Previous SOC percentage (0-100)
            battery_charged: Energy charged this hour (kWh)
            battery_discharge: Energy discharged this hour (kWh)
            min_soc_percent: Minimum SOC percentage (0-100)

        Returns:
            New SOC percentage (0-100)
        """
        # Convert SOC to energy
        previous_energy = (previous_soc / 100.0) * self.battery_capacity
        min_energy = (min_soc_percent / 100.0) * self.battery_capacity

        # Calculate net energy change
        net_change = battery_charged - battery_discharge
        new_energy = previous_energy + net_change

        # Apply constraints
        new_energy = min(new_energy, self.battery_capacity)
        new_energy = max(new_energy, min_energy)

        # Convert back to SOC
        return (new_energy / self.battery_capacity) * 100.0
