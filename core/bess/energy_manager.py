"""EnergyManager: Comprehensive energy flow tracking and prediction for BESS.

This module provides centralized management of all energy-related data for a battery
energy storage system. The EnergyManager collects readings from battery system sensors,
tracks historical values using a FluxDataProvider, validates energy balance, and
provides forecasts for system optimization.

Key Responsibilities:
1. Collect energy measurements directly from Home Assistant sensors or database
2. Track energy flows with hourly granularity
3. Validate energy balance and detect inconsistencies
4. Provide combined historical/forecast data for optimization
5. Log energy balance reports and statistics

Energy Flow Model:
    The system tracks the following energy flows (all in kWh):

    Directly Measured Flows:
    - Battery SOC/SOE: Battery state of charge/energy
    - Solar Production: Total solar energy generated
    - Self-Consumption: Solar energy consumed by home
    - Export To Grid: Solar energy exported to grid
    - Load Consumption: Total home energy consumption
    - Imported From Grid: Energy imported from grid
    - Battery Charge: Energy charged to battery
    - Battery Discharge: Energy discharged from battery
    - System Production: Total energy produced (solar + battery discharge)
    - Self Consumption: Energy consumed directly from own production

    Calculated Flows:
    - Solar To Battery: Solar energy directed to battery charging
    - Grid To Battery: Grid energy directed to battery charging

    Complete energy flows including auxiliary loads:
    - EV Charging: Energy consumed by electric vehicle (optional)
    - Other auxiliary loads as configured

Energy Balance Equation:
    The system maintains and validates the following energy balance:

    Input = Output
    (Imported From Grid + System Production) =
    (Load Consumption + Export To Grid)

    Where Battery Net Change = Battery Charge - Battery Discharge
    And Battery Charge = Grid To Battery + Solar To Battery

Required Sensors:
    Primary Energy Sensors (lifetime cumulative values):
    - rkm0d7n04x_statement_of_charge_soc: Battery SOC (%)
    - rkm0d7n04x_lifetime_total_all_batteries_charged: Battery charging (kWh)
    - rkm0d7n04x_lifetime_total_all_batteries_discharged: Battery discharging (kWh)
    - rkm0d7n04x_lifetime_total_solar_energy: Solar production (kWh)
    - rkm0d7n04x_lifetime_import_from_grid: Import from grid (kWh)
    - rkm0d7n04x_lifetime_total_export_to_grid: Export to grid (kWh)
    - rkm0d7n04x_lifetime_total_load_consumption: Load consumption (kWh)
    - rkm0d7n04x_lifetime_system_production: System production (solar + battery) (kWh)
    - rkm0d7n04x_lifetime_self_consumption: Self consumption (load - grid import) (kWh)

    Optional Auxiliary Load Sensors:
    - zap263668_energy_meter: EV charging energy (kWh)

Usage:
    # Initialize with Home Assistant controller and battery parameters
    energy_manager = EnergyManager(
        ha_controller=ha_controller,
        total_capacity=30.0,
        min_soc=10.0,
        default_consumption=4.5
    )

    # Set initial predictions for the day
    energy_manager.set_consumption_predictions([3.2, 3.0, 2.8, ...])  # 24 values
    energy_manager.set_solar_predictions([0.0, 0.0, 0.0, ...])        # 24 values

    # Update data at the end of each hour (HH:59 or HH:00)
    await energy_manager.update_hour_data(hour=3)  # Updates data for 02:00-03:00

    # Get full day combined historical/forecast data for optimization
    energy_profile = energy_manager.get_full_day_energy_profile()

    # Reset daily data. Should be called before starting a new day.
    energy_manager.reset_daily_data()

    # Log energy balance report
    energy_manager.log_energy_balance()
"""

import logging
from datetime import datetime, time

from .influxdb_helper import get_sensor_data

_LOGGER = logging.getLogger(__name__)
# _LOGGER.setLevel(logging.DEBUG)


class EnergyManager:
    """Manages all energy data and predictions for the battery system.

    This class is responsible for collecting, validating, and tracking all energy
    flows in the battery system. It combines historical measurements with
    predictions to provide a complete energy profile for battery optimization.

    With the addition of system_production and self_consumption sensors, it can
    accurately calculate energy flows without relying on time-of-day assumptions.
    """

    def __init__(
        self,
        ha_controller,
        total_capacity=30.0,
        min_soc=10.0,
        default_consumption=4.5,
    ) -> None:
        """Initialize the energy manager.

        Args:
            ha_controller: Home Assistant controller instance
            total_capacity: Maximum battery energy capacity in kWh
            min_soc: Minimum battery state of charge percentage
            default_consumption: Default hourly consumption in kWh

        Raises:
            ValueError: If parameters are invalid

        """
        if total_capacity <= 0:
            raise ValueError("Total capacity must be positive")
        if not 0 <= min_soc <= 100:
            raise ValueError("Min SOC must be between 0 and 100")
        if default_consumption <= 0:
            raise ValueError("Default consumption must be positive")

        # Store controller references
        self._ha_controller = ha_controller

        # Configuration values
        self.total_capacity = total_capacity
        self.min_soc = min_soc
        self.reserved_capacity = total_capacity * (min_soc / 100.0)
        self.default_consumption = default_consumption
        self._initialization_time = datetime.now()
        self._last_processed_hour = None
        self.ac_dc_efficiency = 0.9  # Assume 90% efficiency for AC-DC conversion
        self._consumption_predictions = [self.default_consumption] * 24
        self._solar_predictions = [0.0] * 24

        # Define the energy sensors we track
        self.energy_sensors = [
            "rkm0d7n04x_lifetime_total_all_batteries_charged",
            "rkm0d7n04x_lifetime_total_all_batteries_discharged",
            "rkm0d7n04x_lifetime_total_solar_energy",
            "rkm0d7n04x_lifetime_total_export_to_grid",
            "rkm0d7n04x_lifetime_total_load_consumption",
            "rkm0d7n04x_lifetime_import_from_grid",
            "rkm0d7n04x_statement_of_charge_soc",
            "rkm0d7n04x_lifetime_system_production",  # Solar + battery discharge
            "rkm0d7n04x_lifetime_self_consumption",  # Load consumption - import from grid
            "zap263668_energy_meter",
        ]

        # Initialize energy flow storage dictionaries - indexed by hour (0-23)
        self._init_energy_storage_dicts()

    def _init_energy_storage_dicts(self):
        """Initialize all energy flow storage dictionaries."""
        self._battery_soc = {}  # Battery state of charge (%)
        self._battery_soe = {}  # Battery state of energy (kWh)
        self._battery_soe_measured = {}  # Raw measured SOE values (kWh)
        self._system_production = {}  # Solar generation (kWh)
        self._self_consumption = {}  # Solar self-consumption (kWh)
        self._export_to_grid = {}  # Solar export to grid (kWh)
        self._load_consumption = {}  # Home consumption (kWh)
        self._import_from_grid = {}  # Grid import (kWh)
        self._battery_charge = {}  # Battery charging (kWh)
        self._battery_discharge = {}  # Battery discharging (kWh)
        self._grid_to_battery = {}  # Grid charging battery (kWh)
        self._solar_to_battery = {}  # Solar charging battery (kWh)
        self._aux_loads = {}  # Auxiliary loads (e.g., EV) (kWh)
        # Total system production (solar + battery) (kWh)
        self._system_production_total = {}
        # Self consumption (load - grid import) (kWh)
        self._self_consumption_total = {}

    def reset_daily_data(self):
        """Reset daily predictions and clear accumulated data.

        This should be called at the start of each day (typically at midnight)
        to ensure the energy manager starts with fresh predictions and data.

        Returns:
            bool: True if reset was successful

        """
        try:
            # Reset predictions to default values
            self._consumption_predictions = [self.default_consumption] * 24
            self._solar_predictions = [0.0] * 24

            self._init_energy_storage_dicts()

            # Clear the last processed hour
            self._last_processed_hour = None

            _LOGGER.info("Daily energy data reset complete")
        except (ValueError, AttributeError, KeyError, TypeError) as e:
            _LOGGER.error("Failed to reset daily data: %s", str(e))
            return False
        else:
            return True

    def fetch_and_initialize_historical_data(self):
        """Fetch historical data and initialize energy flows.

        This method retrieves historical energy data from sensors and initializes
        the energy flow tracking dictionaries with the data.

        """
        try:
            current_hour, current_minute, today = self._get_current_time_info()

            _LOGGER.info("Fetching historical data for energy manager initialization")

            # Determine end hour for data collection
            end_hour = self._determine_historical_end_hour(current_hour, current_minute)
            end_time = datetime.combine(today, time(hour=end_hour))
            _LOGGER.info(
                "Fetching historical data up to %s",
                end_time.strftime("%Y-%m-%d %H:%M"),
            )

            # Initialize readings storage and SOC values
            readings_by_hour = {}
            self._initialize_soc_values(current_hour)

            # Process hour 0 first to establish baseline
            self._process_hour_zero_data(today, readings_by_hour)

            # Now process remaining hours (1 through end_hour)
            for hour in range(1, end_hour + 1):
                self._process_historical_hour_data(hour, today, readings_by_hour)

            # Set the last processed hour to the highest hour with data
            if readings_by_hour:
                self._last_processed_hour = max(readings_by_hour.keys())
                _LOGGER.info("Set last processed hour to %d", self._last_processed_hour)

            _LOGGER.info(
                "Successfully processed historical data for %d hours",
                len(readings_by_hour),
            )
        except (ValueError, KeyError, AttributeError) as e:
            _LOGGER.error("Failed to initialize historical data: %s", str(e))
            # Continue with empty data structures rather than failing completely

    def _get_current_time_info(self):
        """Get current hour, minute, and date."""
        now = datetime.now()
        return now.hour, now.minute, now.date()

    def _determine_historical_end_hour(self, current_hour, current_minute):
        """Determine the end hour for historical data collection."""
        # If we're close to the start of the hour, use the previous hour as end
        if current_minute < 5:
            return current_hour - 1 if current_hour > 0 else 0
        return current_hour

    def _initialize_soc_values(self, current_hour):
        """Initialize SOC values for all hours.

        Args:
            current_hour: Current hour of the day

        Note:
            This method tries to get the current SOC from the controller if
            available, otherwise uses the minimum SOC as a default.

        """
        try:
            # Get current SOC if available
            current_soc = None
            if self._ha_controller:
                current_soc = self._ha_controller.get_battery_soc()
                _LOGGER.info("Current SOC from controller: %.1f%%", current_soc)

            # Input validation
            if current_soc is not None and not 0 <= current_soc <= 100:
                _LOGGER.warning(
                    "Invalid SOC value: %.1f%%, clamping to valid range", current_soc
                )
                current_soc = max(0, min(100, current_soc))

            # Initialize SOC for all hours with the current SOC or a default value
            default_soc = current_soc if current_soc is not None else self.min_soc
            for hour in range(24):
                self._battery_soc[hour] = default_soc
                self._battery_soe[hour] = self._soc_to_energy(default_soc)

            # Store current SOC for current hour specifically
            if current_soc is not None:
                self._battery_soc[current_hour] = current_soc
                self._battery_soe[current_hour] = self._soc_to_energy(current_soc)
                _LOGGER.debug(
                    "Stored current SOC %.1f%% for hour %d",
                    current_soc,
                    current_hour,
                )
        except (AttributeError, ValueError) as e:
            _LOGGER.warning("Error initializing SOC values: %s", str(e))
            # Set default values for all hours
            for hour in range(24):
                self._battery_soc[hour] = self.min_soc
                self._battery_soe[hour] = self._soc_to_energy(self.min_soc)

    def _process_hour_zero_data(self, today, readings_by_hour):
        """Process hour 0 data as a special case.

        Hour 0 (midnight) is treated specially as it establishes the baseline
        for cumulative energy counters.

        Args:
            today: Current date
            readings_by_hour: Dictionary to store readings by hour

        """
        try:
            hour_zero_time = datetime.combine(today, time(hour=0))
            cumulative_sensors = self._get_cumulative_sensors()
            hour_zero_data = get_sensor_data(cumulative_sensors, hour_zero_time)

            if hour_zero_data and hour_zero_data.get("status") == "success":
                hour_zero_readings = hour_zero_data.get("data", {})

                if hour_zero_readings:
                    _LOGGER.info("Got hour 0 readings successfully")
                    readings_by_hour[0] = hour_zero_readings

                    # Store SOC if available
                    self._store_hour_zero_soc(hour_zero_readings)

                    # Initialize hour 0 flows with defaults
                    self._initialize_hour_zero_flows()
            else:
                _LOGGER.warning("Failed to fetch data for hour 0")
        except (ValueError, KeyError) as e:
            _LOGGER.warning("Error processing hour 0 data: %s", str(e))

    def _get_cumulative_sensors(self):
        """Get list of cumulative sensor names to fetch."""
        return [
            "rkm0d7n04x_lifetime_total_all_batteries_charged",
            "rkm0d7n04x_lifetime_total_all_batteries_discharged",
            "rkm0d7n04x_lifetime_total_solar_energy",
            "rkm0d7n04x_lifetime_total_export_to_grid",
            "rkm0d7n04x_lifetime_total_load_consumption",
            "rkm0d7n04x_lifetime_import_from_grid",
            "rkm0d7n04x_statement_of_charge_soc",
            "rkm0d7n04x_lifetime_system_production",
            "rkm0d7n04x_lifetime_self_consumption",
        ]

    def _store_hour_zero_soc(self, hour_zero_readings):
        """Store SOC from hour 0 readings if available."""
        if "rkm0d7n04x_statement_of_charge_soc" in hour_zero_readings:
            try:
                soc_value = float(
                    hour_zero_readings["rkm0d7n04x_statement_of_charge_soc"]
                )
                if not 0 <= soc_value <= 100:
                    _LOGGER.warning("Invalid SOC for hour 0: %.1f%%", soc_value)
                    return

                self._battery_soc[0] = soc_value
                self._battery_soe[0] = self._soc_to_energy(soc_value)
                _LOGGER.info(
                    "Hour 0: Stored historical SOC %.1f%%",
                    soc_value,
                )
            except (ValueError, TypeError) as e:
                _LOGGER.warning("Error converting hour 0 SOC: %s", str(e))

    def _initialize_hour_zero_flows(self):
        """Initialize hour 0 energy flows with default values."""
        # Set to 0 initially, will be updated with hour 1's processing
        self._system_production[0] = 0.0  # Usually no solar at midnight
        self._export_to_grid[0] = 0.0  # Usually no export at midnight
        self._load_consumption[0] = self._consumption_predictions[
            0
        ]  # Default consumption
        self._import_from_grid[0] = self._consumption_predictions[
            0
        ]  # Default from grid
        self._battery_charge[0] = 0.0  # Will be updated with hour 1
        self._battery_discharge[0] = 0.0
        self._grid_to_battery[0] = 0.0
        self._solar_to_battery[0] = 0.0
        self._aux_loads[0] = 0.0
        self._self_consumption[0] = 0.0
        self._system_production_total[0] = 0.0
        self._self_consumption_total[0] = 0.0

    def _process_historical_hour_data(self, hour, today, readings_by_hour):
        """Process historical data for a specific hour.

        Args:
            hour: Hour to process (0-23)
            today: Current date
            readings_by_hour: Dictionary to store readings by hour

        """
        try:
            hour_time = datetime.combine(today, time(hour=hour))
            cumulative_sensors = self._get_cumulative_sensors()
            hourly_data = get_sensor_data(cumulative_sensors, hour_time)

            if hourly_data and hourly_data.get("status") == "success":
                hour_readings = hourly_data.get("data", {})

                if hour_readings:
                    # Store readings for this hour
                    readings_by_hour[hour] = hour_readings

                    # Store SOC if available
                    self._store_hourly_soc(hour, hour_readings)

                    # Calculate energy flows between previous hour and this hour
                    self._calculate_hourly_flows(hour, hour_readings, readings_by_hour)
                else:
                    _LOGGER.warning("No readings for hour %d", hour)
            else:
                _LOGGER.warning("Failed to fetch data for hour %d", hour)
        except (ValueError, KeyError, AttributeError) as e:
            _LOGGER.warning("Error processing hour %d data: %s", hour, str(e))

    def _store_hourly_soc(self, hour, hour_readings):
        """Store SOC from hourly readings if available."""
        if "rkm0d7n04x_statement_of_charge_soc" in hour_readings:
            try:
                soc_value = float(hour_readings["rkm0d7n04x_statement_of_charge_soc"])
                if not 0 <= soc_value <= 100:
                    _LOGGER.warning("Invalid SOC for hour %d: %.1f%%", hour, soc_value)
                    return

                self._battery_soc[hour] = soc_value
                self._battery_soe[hour] = self._soc_to_energy(soc_value)
                _LOGGER.debug(
                    "Hour %d: Stored historical SOC %.1f%%",
                    hour,
                    soc_value,
                )
            except (ValueError, TypeError) as e:
                _LOGGER.warning("Error converting hour %d SOC: %s", hour, str(e))

    def _calculate_hourly_flows(self, hour, hour_readings, readings_by_hour):
        """Calculate energy flows between previous hour and current hour."""
        if hour - 1 not in readings_by_hour:
            _LOGGER.warning("Missing previous hour data for hour %d", hour)
            return

        try:
            prev_readings = readings_by_hour[hour - 1]
            _LOGGER.debug(
                "Processing hour %d with previous hour %d",
                hour,
                hour - 1,
            )

            # Calculate flows from sensor readings
            flows = self._extract_flows_from_readings(
                hour, hour_readings, prev_readings
            )

            if not flows:
                _LOGGER.warning("Failed to extract flows for hour %d", hour)
                return

            # Calculate derived flows
            flows = self._calculate_derived_flows(flows, hour)

            # Validate the flows
            validated_flows = self._validate_energy_flows(flows, hour)

            # Store the validated flows
            if validated_flows:
                self._store_energy_flows(hour, validated_flows, hour_readings)
                _LOGGER.info("Stored energy flows for hour %d", hour)

                # Update hour 0 flows if this is hour 1
                if hour == 1:
                    self._update_hour_zero_from_hour_one(validated_flows)
            else:
                _LOGGER.warning("No valid flows to store for hour %d", hour)
        except (ValueError, KeyError, TypeError) as e:
            _LOGGER.warning("Error calculating flows for hour %d: %s", hour, str(e))

    def _extract_flows_from_readings(self, hour, current_readings, previous_readings):
        """Extract energy flows by comparing current and previous readings.

        Args:
            hour: Hour to process (0-23)
            current_readings: Current hour sensor readings
            previous_readings: Previous hour sensor readings

        Returns:
            dict: Extracted energy flows or empty dict if extraction fails

        """
        flows = {}

        # Calculate differences for each cumulative sensor
        for sensor in self._get_cumulative_sensors():
            # Skip SOC sensor - it's not a cumulative meter
            if sensor == "rkm0d7n04x_statement_of_charge_soc":
                continue

            if sensor in current_readings and sensor in previous_readings:
                try:
                    curr_value = float(current_readings[sensor])
                    prev_value = float(previous_readings[sensor])

                    # Handle rollovers (decreasing values)
                    if curr_value < prev_value:
                        _LOGGER.info("Detected rollover for %s", sensor)
                        flow = curr_value
                    else:
                        flow = curr_value - prev_value

                    # Map sensor name to flow name
                    if sensor == "rkm0d7n04x_lifetime_total_all_batteries_charged":
                        flows["battery_charge"] = flow
                        _LOGGER.debug(
                            "Hour %d: Battery charge = %.2f kWh",
                            hour,
                            flow,
                        )
                    elif sensor == "rkm0d7n04x_lifetime_total_all_batteries_discharged":
                        flows["battery_discharge"] = flow
                        _LOGGER.debug(
                            "Hour %d: Battery discharge = %.2f kWh",
                            hour,
                            flow,
                        )
                    elif sensor == "rkm0d7n04x_lifetime_total_solar_energy":
                        flows["system_production"] = flow
                        _LOGGER.debug(
                            "Hour %d: Solar production = %.2f kWh",
                            hour,
                            flow,
                        )
                    elif sensor == "rkm0d7n04x_lifetime_total_export_to_grid":
                        flows["export_to_grid"] = flow
                        _LOGGER.debug(
                            "Hour %d: Export to grid = %.2f kWh",
                            hour,
                            flow,
                        )
                    elif sensor == "rkm0d7n04x_lifetime_total_load_consumption":
                        flows["load_consumption"] = flow
                        _LOGGER.debug(
                            "Hour %d: Load consumption = %.2f kWh",
                            hour,
                            flow,
                        )
                    elif sensor == "rkm0d7n04x_lifetime_import_from_grid":
                        flows["import_from_grid"] = flow
                        _LOGGER.debug(
                            "Hour %d: Import from grid = %.2f kWh",
                            hour,
                            flow,
                        )
                    elif sensor == "rkm0d7n04x_lifetime_system_production":
                        flows["system_production_total"] = flow
                        _LOGGER.debug(
                            "Hour %d: System production = %.2f kWh",
                            hour,
                            flow,
                        )
                    elif sensor == "rkm0d7n04x_lifetime_self_consumption":
                        flows["self_consumption_total"] = flow
                        _LOGGER.debug(
                            "Hour %d: Self consumption = %.2f kWh",
                            hour,
                            flow,
                        )
                except (ValueError, TypeError) as e:
                    _LOGGER.warning(
                        "Error calculating flow for %s: %s",
                        sensor,
                        e,
                    )
            else:
                _LOGGER.warning(
                    "Missing sensor data for %s in hour %d",
                    sensor,
                    hour,
                )

        # Initialize any missing flows to avoid KeyErrors
        required_flows = [
            "battery_charge",
            "battery_discharge",
            "system_production",
            "export_to_grid",
            "load_consumption",
            "import_from_grid",
        ]
        for flow in required_flows:
            if flow not in flows:
                flows[flow] = 0.0

        return flows

    def _calculate_derived_flows(self, flows, hour_of_day=None):
        """Calculate derived flows based on direct measurements.

        This method calculates energy flows that aren't directly measured,
        including solar-to-battery and grid-to-battery, using either the
        new system_production and self_consumption sensors (if available)
        or falling back to the time-of-day based heuristic.

        Args:
            flows: Dict of energy flow values
            hour_of_day: Current hour (0-23) if known

        Returns:
            dict: Flows with derived values added

        """
        # Calculate self-consumption
        solar_production = flows.get("system_production", 0)
        battery_charge = flows.get("battery_charge", 0)
        battery_discharge = flows.get("battery_discharge", 0)
        grid_export = flows.get("export_to_grid", 0)

        # Check if we have the new sensors
        has_system_production = "system_production_total" in flows
        has_self_consumption = "self_consumption_total" in flows

        # Calculate self-consumption if not directly measured
        if not has_self_consumption:
            # Traditional calculation: solar consumed locally
            flows["self_consumption"] = max(0, solar_production - grid_export)
            _LOGGER.debug(
                "Hour %s: Self consumption = %.2f kWh (calculated)",
                hour_of_day,
                flows["self_consumption"],
            )
        else:
            # We already have self_consumption from sensor
            flows["self_consumption"] = flows["self_consumption_total"]
            _LOGGER.debug(
                "Hour %s: Self consumption = %.2f kWh (from sensor)",
                hour_of_day,
                flows["self_consumption"],
            )

        # Calculate solar_to_battery and grid_to_battery
        if has_system_production and has_self_consumption:
            # We can calculate using the more accurate method with new sensors
            self_consumption_total = flows.get("self_consumption_total", 0)

            # Solar-to-Battery = System Production - Grid Export - Self Consumption
            # System Production = Solar + Battery Discharge
            # Thus: Solar-to-Battery = Solar + Battery Discharge - Grid Export - Self Consumption
            # Reorganizing: Solar-to-Battery = Solar - Grid Export - Self Consumption + Battery Discharge

            solar_to_battery = max(
                0,
                solar_production
                - grid_export
                - self_consumption_total
                + battery_discharge,
            )

            # Ensure solar_to_battery doesn't exceed battery_charge or solar_production
            solar_to_battery = min(solar_to_battery, battery_charge, solar_production)

            flows["solar_to_battery"] = solar_to_battery

            # Grid-to-Battery = Battery Charge - Solar-to-Battery
            flows["grid_to_battery"] = max(0, battery_charge - solar_to_battery)

            _LOGGER.debug(
                "Hour %s: Solar to battery = %.2f kWh (from new sensors)",
                hour_of_day,
                flows["solar_to_battery"],
            )
            _LOGGER.debug(
                "Hour %s: Grid to battery = %.2f kWh (from new sensors)",
                hour_of_day,
                flows["grid_to_battery"],
            )
        else:
            # Fallback to the original method using time-of-day assumptions
            is_night = hour_of_day is not None and (
                hour_of_day < 6 or hour_of_day >= 20
            )

            if is_night and battery_charge > 0:
                # At night, all battery charging is from grid
                flows["grid_to_battery"] = battery_charge
                flows["solar_to_battery"] = 0.0

                _LOGGER.debug(
                    "Hour %s: Using night-time assumption - all charging (%.2f kWh) from grid",
                    hour_of_day,
                    battery_charge,
                )
            else:
                # During day, calculate solar_to_battery based on flows
                # Solar charging is limited by both available solar and actual battery charging
                solar_to_battery = max(0, min(solar_production, battery_charge))
                flows["solar_to_battery"] = solar_to_battery

                # Grid charging is the remainder of battery charging not covered by solar
                flows["grid_to_battery"] = max(0, battery_charge - solar_to_battery)

                _LOGGER.debug(
                    "Hour %s: Solar to battery = %.2f kWh (based on solar availability)",
                    hour_of_day,
                    flows["solar_to_battery"],
                )
                _LOGGER.debug(
                    "Hour %s: Grid to battery = %.2f kWh (remaining charge)",
                    hour_of_day,
                    flows["grid_to_battery"],
                )

        # Ensure aux_load is initialized
        flows["aux_load"] = flows.get("aux_load", 0.0)

        return flows

    def _validate_energy_flows(self, flows, hour_of_day=None):
        """Validate energy flows against physical constraints.

        This method applies validation rules to ensure energy flows are physically
        possible and consistent with each other. It contains specific checks for:
        1. Night hours (no solar production expected)
        2. Physical constraints (e.g., grid-to-battery ≤ battery charge)
        3. Suspicious concurrent charge/discharge
        4. Energy balance (input = output)

        With new sensors available, the validation logic is enhanced to use more
        direct measurements rather than inferences.

        Args:
            flows: Dict of energy flow values
            hour_of_day: Current hour (0-23) if known

        Returns:
            dict: Validated/corrected energy flows

        """
        # Make a copy to avoid modifying the original
        validated = flows.copy() if flows else {}

        # Skip validation if flows is empty
        if not validated:
            return validated

        # Check if we have the new sensors to determine which validation approach to use
        has_system_production = "system_production_total" in validated
        has_self_consumption = "self_consumption_total" in validated

        # 1. Night hours validation (6pm-6am)
        is_night = hour_of_day is not None and (hour_of_day < 6 or hour_of_day >= 20)
        if is_night:
            # No solar at night
            if validated.get("system_production", 0) > 0.1:
                _LOGGER.warning(
                    "Hour %s: Zeroing incorrect solar production (%.2f kWh) during night hours",
                    hour_of_day,
                    validated.get("system_production", 0),
                )
                validated["system_production"] = 0.0
                validated["self_consumption"] = 0.0
                validated["export_to_grid"] = 0.0
                validated["solar_to_battery"] = 0.0

            # All battery charging must be from grid at night
            if (
                validated.get("battery_charge", 0) > 0.1
                and abs(
                    validated.get("grid_to_battery", 0)
                    - validated.get("battery_charge", 0)
                )
                > 0.5
            ):
                _LOGGER.warning(
                    "Hour %s: Correcting grid-to-battery (%.2f kWh) to match battery charge (%.2f kWh) at night",
                    hour_of_day,
                    validated.get("grid_to_battery", 0),
                    validated.get("battery_charge", 0),
                )
                validated["grid_to_battery"] = validated.get("battery_charge", 0)
                validated["solar_to_battery"] = 0.0

        # 2. Physical constraints for all hours
        if (
            validated.get("grid_to_battery", 0)
            > validated.get("battery_charge", 0) + 0.5
        ):
            _LOGGER.warning(
                "Hour %s: Grid-to-battery (%.2f kWh) exceeds battery charge (%.2f kWh) - correcting",
                hour_of_day,
                validated.get("grid_to_battery", 0),
                validated.get("battery_charge", 0),
            )
            validated["grid_to_battery"] = validated.get("battery_charge", 0)

        # Ensure solar-to-battery doesn't exceed total solar production
        if (
            validated.get("solar_to_battery", 0)
            > validated.get("system_production", 0) + 0.5
        ):
            _LOGGER.warning(
                "Hour %s: Solar-to-battery (%.2f kWh) exceeds solar production (%.2f kWh) - correcting",
                hour_of_day,
                validated.get("solar_to_battery", 0),
                validated.get("system_production", 0),
            )
            validated["solar_to_battery"] = validated.get("system_production", 0)

        # 3. Check for suspicious simultaneous charge/discharge
        if (
            validated.get("battery_charge", 0) > 2.0
            and validated.get("battery_discharge", 0) > 2.0
        ):
            _LOGGER.warning(
                "Hour %s: Unusual battery behavior - significant charge (%.2f kWh) AND discharge (%.2f kWh)",
                hour_of_day,
                validated.get("battery_charge", 0),
                validated.get("battery_discharge", 0),
            )

        # 4. Energy balance verification - FIXED
        # If we have the new sensors, use a more accurate energy balance check
        if has_system_production and has_self_consumption:
            # With new sensors, energy balance is:
            # (Grid Import + System Production) = (Load Consumption + Grid Export)
            # where System Production includes both solar and battery discharge
            energy_in = validated.get("import_from_grid", 0) + validated.get(
                "system_production_total", 0
            )
            energy_out = validated.get("load_consumption", 0) + validated.get(
                "export_to_grid", 0
            )

            _LOGGER.debug(
                "Hour %s: Energy balance check with new sensors: In=%.2f kWh, Out=%.2f kWh",
                hour_of_day,
                energy_in,
                energy_out,
            )
        else:
            # Fixed traditional energy balance check
            # Input = Home Consumption + Grid Export + Battery Net Change
            energy_in = validated.get("import_from_grid", 0) + validated.get(
                "system_production", 0
            )

            # Battery net change is charging - discharging
            battery_charge = validated.get("battery_charge", 0)
            battery_discharge = validated.get("battery_discharge", 0)

            # Output should include all consumption PLUS battery charging
            # We include battery charging as part of output because it's energy leaving the system
            energy_out = (
                validated.get("load_consumption", 0)
                + validated.get("export_to_grid", 0)
                + validated.get("aux_load", 0)
                + battery_charge
                - battery_discharge
            )

            _LOGGER.debug(
                "Hour %s: Energy balance check: In=%.2f kWh, Out=%.2f kWh, Battery net=%.2f kWh",
                hour_of_day,
                energy_in,
                energy_out,
                battery_charge - battery_discharge,
            )

        # Allow for reasonable tolerance (5% or 0.5 kWh, whichever is greater)
        balance_tolerance = max(0.5, energy_in * 0.05)

        if abs(energy_in - energy_out) > balance_tolerance:
            _LOGGER.warning(
                "Hour %s: Energy balance discrepancy - Input=%.2f kWh, Output=%.2f kWh, Difference=%.2f kWh",
                hour_of_day,
                energy_in,
                energy_out,
                abs(energy_in - energy_out),
            )

        return validated

    def _update_hour_zero_from_hour_one(self, validated_flows):
        """Update hour 0 values based on hour 1 actual values.

        Since hour 0 (midnight) often has incomplete data, this method
        uses data from hour 1 to better estimate energy flows for hour 0.

        Args:
            validated_flows: Validated flows from hour 1

        """
        try:
            # Update hour 0 based on hour 1 actual values
            # Hour 0 import should be similar to hour 1
            import_hour_1 = validated_flows.get("import_from_grid", 0.0)
            load_hour_1 = validated_flows.get("load_consumption", 0.0)
            battery_charge_hour_1 = validated_flows.get("battery_charge", 0.0)
            grid_to_battery_hour_1 = validated_flows.get("grid_to_battery", 0.0)
            solar_to_battery_hour_1 = validated_flows.get("solar_to_battery", 0.0)

            # Check for reasonable values before using
            if import_hour_1 > 10.0 or load_hour_1 > 10.0:
                _LOGGER.warning(
                    "Suspicious hour 1 values: import=%.2f, load=%.2f - skipping hour 0 update",
                    import_hour_1,
                    load_hour_1,
                )
                return

            # Use actual hour 1 values to set reasonable hour 0 values
            self._import_from_grid[0] = import_hour_1 * 0.9  # Slightly less than hour 1
            self._load_consumption[0] = load_hour_1 * 0.9  # Slightly less than hour 1
            self._battery_charge[0] = (
                battery_charge_hour_1 * 0.8
            )  # Somewhat less than hour 1
            self._grid_to_battery[0] = (
                grid_to_battery_hour_1 * 0.8
            )  # Somewhat less than hour 1
            self._solar_to_battery[0] = (
                solar_to_battery_hour_1 * 0.8
            )  # Somewhat less than hour 1

            # Add new sensor values if they exist
            if "system_production_total" in validated_flows:
                self._system_production_total[0] = (
                    validated_flows.get("system_production_total") * 0.8
                )
            if "self_consumption_total" in validated_flows:
                self._self_consumption_total[0] = (
                    validated_flows.get("self_consumption_total") * 0.8
                )

            _LOGGER.info("Updated hour 0 values based on hour 1 data")
        except (KeyError, TypeError) as e:
            _LOGGER.warning("Failed to update hour 0 from hour 1: %s", str(e))

    def fetch_predictions(self):
        """Fetch consumption and solar predictions from controller.

        This method retrieves the latest consumption and solar production
        predictions from the Home Assistant controller, if available.
        """
        if self._ha_controller:
            try:
                consumption_predictions = (
                    self._ha_controller.get_estimated_consumption()
                )
                if consumption_predictions and len(consumption_predictions) == 24:
                    self._consumption_predictions = consumption_predictions
                    _LOGGER.info(
                        "Fetched consumption predictions: %s",
                        [round(value, 1) for value in self._consumption_predictions],
                    )
                else:
                    _LOGGER.warning(
                        "Invalid consumption predictions format, keeping defaults"
                    )

                solar_predictions = self._ha_controller.get_solcast_forecast()
                if solar_predictions and len(solar_predictions) == 24:
                    self._solar_predictions = solar_predictions
                    _LOGGER.info(
                        "Fetched solar predictions: %s",
                        [round(value, 1) for value in self._solar_predictions],
                    )
                else:
                    _LOGGER.warning(
                        "Invalid solar predictions format, keeping defaults"
                    )

                self.log_energy_balance()
            except (AttributeError, ValueError) as e:
                _LOGGER.warning("Failed to fetch predictions: %s", str(e))

    def set_consumption_predictions(self, values):
        """Set hourly consumption predictions.

        Args:
            values: List of 24 hourly consumption values (kWh)

        Raises:
            ValueError: If values list doesn't contain 24 values

        """
        if len(values) != 24:
            raise ValueError("Consumption predictions must have 24 values")

        self._consumption_predictions = list(values)
        _LOGGER.info(
            "Updated consumption predictions: %s", self._consumption_predictions
        )

    def set_solar_predictions(self, values):
        """Set hourly solar production predictions.

        Args:
            values: List of 24 hourly solar production values (kWh)

        Raises:
            ValueError: If values list doesn't contain 24 values

        """
        if len(values) != 24:
            raise ValueError("Solar predictions must have 24 values")

        self._solar_predictions = list(values)
        _LOGGER.info("Updated solar predictions: %s", self._solar_predictions)

    def _get_previous_hour_readings(self, hour):
        """Get readings from the previous hour.

        This method tries to get the sensor readings for the hour preceding the given hour.

        Args:
            hour: Current hour (0-23)

        Returns:
            Dictionary of sensor readings for the previous hour

        """
        previous_hour = hour - 1
        if previous_hour < 0:
            # For hour 0, we need the previous day's data
            _LOGGER.warning("Previous hour would be from yesterday, using estimates")
            return self._get_initial_baseline_readings()

        # Try to get readings directly from InfluxDB
        today = datetime.now().date()
        previous_time = datetime.combine(today, time(hour=previous_hour))

        try:
            _LOGGER.debug("Fetching previous hour readings for hour %d", previous_hour)
            historical_data = get_sensor_data(self.energy_sensors, previous_time)

            if historical_data and historical_data.get("status") == "success":
                previous_readings = historical_data.get("data", {})
                if previous_readings:
                    _LOGGER.debug("Found previous hour data for hour %d", previous_hour)
                    # Check if SOC is available
                    if "rkm0d7n04x_statement_of_charge_soc" in previous_readings:
                        _LOGGER.debug(
                            "Hour %d has SOC: %s",
                            previous_hour,
                            previous_readings["rkm0d7n04x_statement_of_charge_soc"],
                        )
                    return previous_readings
                _LOGGER.warning("No data found for hour %d", previous_hour)
            else:
                _LOGGER.warning("Failed to get data for hour %d", previous_hour)
        except (ValueError, KeyError) as e:
            _LOGGER.error("Error getting previous hour readings: %s", e)

        # If we couldn't get data for previous hour, use initial baseline
        _LOGGER.warning("Falling back to baseline values for hour %d", previous_hour)
        return self._get_initial_baseline_readings()

    def _get_current_readings(self):
        """Get current sensor readings directly from controller.

        Returns:
            dict: Current sensor readings or None if unavailable

        """
        if not self._ha_controller:
            return None

        try:
            readings = {}
            for sensor in self.energy_sensors:
                value = self._ha_controller.get_sensor_value(sensor)
                readings[sensor] = value
        except (AttributeError, ValueError) as e:
            _LOGGER.warning("Failed to get current readings: %s", str(e))
            return None
        else:
            return readings

    def _get_initial_baseline_readings(self):
        """Create a baseline of initial readings (zeros or defaults).

        Used when we don't have actual previous readings.

        Returns:
            dict: Baseline readings with reasonable defaults

        """
        readings = {}
        # Initialize all flow sensors to zero
        flow_sensors = [
            "rkm0d7n04x_lifetime_total_all_batteries_charged",
            "rkm0d7n04x_lifetime_total_all_batteries_discharged",
            "rkm0d7n04x_lifetime_total_solar_energy",
            "rkm0d7n04x_lifetime_total_export_to_grid",
            "rkm0d7n04x_lifetime_total_load_consumption",
            "rkm0d7n04x_lifetime_import_from_grid",
            "zap263668_energy_meter",
            "rkm0d7n04x_lifetime_system_production",
            "rkm0d7n04x_lifetime_self_consumption",
        ]

        for sensor in flow_sensors:
            readings[sensor] = 0.0

        # For SOC, try to get current value if available, otherwise use a reasonable default
        if self._ha_controller:
            try:
                current_soc = self._ha_controller.get_battery_soc()
                readings["rkm0d7n04x_statement_of_charge_soc"] = current_soc
                _LOGGER.debug("Using current SOC for baseline: %.1f%%", current_soc)
            except (AttributeError, ValueError):
                # Use a reasonable default
                readings["rkm0d7n04x_statement_of_charge_soc"] = self.min_soc + 20.0
                _LOGGER.debug(
                    "Failed to get SOC, using default: %.1f%%",
                    readings["rkm0d7n04x_statement_of_charge_soc"],
                )
        else:
            # Use a reasonable default
            readings["rkm0d7n04x_statement_of_charge_soc"] = self.min_soc + 20.0

        return readings

    def _store_energy_flows(self, hour, flows, readings=None):
        """Store energy flows in class attributes.

        Args:
            hour: Hour to store data for (0-23)
            flows: Dictionary of calculated energy flows
            readings: Optional sensor readings including SOC

        """
        # Get previous hour's SOC/SOE
        prev_hour = hour - 1
        prev_soc = None
        prev_soe = None

        if prev_hour >= 0 and prev_hour in self._battery_soc:
            prev_soc = self._battery_soc[prev_hour]
            prev_soe = self._battery_soe[prev_hour]

        # Store battery SOC/SOE if available in readings
        if readings and "rkm0d7n04x_statement_of_charge_soc" in readings:
            # Use sensor reading directly
            measured_soc = float(readings["rkm0d7n04x_statement_of_charge_soc"])
            # Validate SOC value
            if not 0 <= measured_soc <= 100:
                _LOGGER.warning(
                    "Invalid SOC reading: %.1f%%, clamping to valid range",
                    measured_soc,
                )
                measured_soc = max(0, min(100, measured_soc))

            self._battery_soc[hour] = measured_soc
            self._battery_soe[hour] = self._soc_to_energy(measured_soc)
            self._battery_soe_measured[hour] = self._battery_soe[hour]

            _LOGGER.debug(
                "Hour %d: Using measured SOC value: %.1f%%", hour, measured_soc
            )
        else:
            # Calculate SOC based on previous SOC and battery actions
            battery_charge = flows.get("battery_charge", 0.0)
            battery_discharge = flows.get("battery_discharge", 0.0)
            net_battery_change = battery_charge - battery_discharge

            if prev_soe is not None:
                # Calculate new SOE
                new_soe = prev_soe + net_battery_change

                # Check if battery is full or empty
                if battery_charge > 0 and prev_soe >= self.total_capacity - 0.1:
                    # Battery already full, SOE stays at max
                    new_soe = self.total_capacity
                    _LOGGER.debug(
                        "Hour %d: Battery already full, SOE stays at max despite charge of %.2f kWh",
                        hour,
                        battery_charge,
                    )
                elif battery_discharge > 0 and prev_soe <= self.reserved_capacity + 0.1:
                    # Battery already empty, SOE stays at min
                    new_soe = self.reserved_capacity
                    _LOGGER.debug(
                        "Hour %d: Battery already empty, SOE stays at min despite discharge of %.2f kWh",
                        hour,
                        battery_discharge,
                    )
                else:
                    # Normal case - SOE changes with battery action
                    # Ensure SOE stays within valid range
                    new_soe = min(new_soe, self.total_capacity)
                    new_soe = max(new_soe, self.reserved_capacity)

                # Update SOC and SOE
                self._battery_soe[hour] = new_soe
                self._battery_soc[hour] = self._energy_to_soc(new_soe)
                self._battery_soe_expected[hour] = new_soe

                _LOGGER.debug(
                    "Hour %d: Calculated SOC %.1f%% from previous SOC %.1f%% "
                    "with net battery change %.2f kWh",
                    hour,
                    self._battery_soc[hour],
                    prev_soc,
                    net_battery_change,
                )
            # If no previous SOC available, use real-time reading or default
            elif self._ha_controller:
                current_soc = self._ha_controller.get_battery_soc()

                # For the very first hour, if battery actions indicate the battery
                # wasn't full/empty at the start, adjust the initial SOC accordingly
                if hour == 0 and battery_charge > 0 and current_soc >= 99.5:
                    # If we're charging at hour 0 and current SOC is 100%,
                    # the battery likely wasn't full at the beginning of hour 0
                    adjusted_soc = max(
                        90.0, current_soc - 5.0
                    )  # Adjust down by 5% or to 90% minimum
                    _LOGGER.info(
                        "Adjusting initial SOC from %.1f%% to %.1f%% "
                        "based on charging action of %.2f kWh",
                        current_soc,
                        adjusted_soc,
                        battery_charge,
                    )
                    current_soc = adjusted_soc

                # Validate SOC value
                if not 0 <= current_soc <= 100:
                    _LOGGER.warning(
                        "Invalid SOC from controller: %.1f%%, clamping to valid range",
                        current_soc,
                    )
                    current_soc = max(0, min(100, current_soc))

                self._battery_soc[hour] = current_soc
                self._battery_soe[hour] = self._soc_to_energy(current_soc)
                _LOGGER.debug(
                    "Hour %d: Using current SOC from controller: %.1f%%",
                    hour,
                    current_soc,
                )
            else:
                self._battery_soc[hour] = self.min_soc
                self._battery_soe[hour] = self.reserved_capacity

        # Store energy flows
        self._battery_charge[hour] = flows.get("battery_charge", 0.0)
        self._battery_discharge[hour] = flows.get("battery_discharge", 0.0)
        self._system_production[hour] = flows.get("system_production", 0.0)
        self._self_consumption[hour] = flows.get("self_consumption", 0.0)
        self._export_to_grid[hour] = flows.get("export_to_grid", 0.0)
        self._load_consumption[hour] = flows.get("load_consumption", 0.0)
        self._import_from_grid[hour] = flows.get("import_from_grid", 0.0)
        self._grid_to_battery[hour] = flows.get("grid_to_battery", 0.0)
        self._solar_to_battery[hour] = flows.get("solar_to_battery", 0.0)
        self._aux_loads[hour] = flows.get("aux_load", 0.0)

        # Store new sensor values if available
        if "system_production_total" in flows:
            self._system_production_total[hour] = flows.get(
                "system_production_total", 0.0
            )
        if "self_consumption_total" in flows:
            self._self_consumption_total[hour] = flows.get(
                "self_consumption_total", 0.0
            )

    def update_hour_data(self, hour):
        """Update energy data for the hour that just completed.

        Args:
            hour: Hour to update (0-23)

        Returns:
            dict: Hour data or None if update failed

        Raises:
            ValueError: If hour is invalid

        """
        # Validate input and check processing status
        if not 0 <= hour <= 23:
            _LOGGER.error("Invalid hour: %d (must be 0-23)", hour)
            raise ValueError(f"Invalid hour: {hour}")

        if self._last_processed_hour == hour:
            _LOGGER.warning("Hour %02d already processed, skipping", hour)
            return self._create_cached_result(hour)

        # Update predictions if controller is available
        self._update_predictions()

        # Handle special case for initialization hour
        initialization_result = self._handle_initialization_hour(hour)
        if initialization_result:
            return initialization_result

        # Get hourly data from sensors
        try:
            hourly_data, current_readings = self._fetch_hourly_sensor_data(hour)
            if not hourly_data:
                return self._create_fallback_result(hour)

            # Process the hourly data
            energy_data = self._process_hourly_sensor_data(
                hour, hourly_data, current_readings
            )
            if energy_data:
                return energy_data
        except (ValueError, KeyError, AttributeError) as e:
            _LOGGER.warning("Failed to process hour data: %s", str(e))

        # If data not available or processing failed, return fallback
        _LOGGER.warning("Could not get data for hour %02d", hour)
        return self._create_fallback_result(hour)

    def _update_predictions(self):
        """Update solar and consumption predictions from controller."""
        if self._ha_controller:
            try:
                solar_predictions = self._ha_controller.get_solcast_forecast()
                if solar_predictions and len(solar_predictions) == 24:
                    self._solar_predictions = solar_predictions

                consumption_predictions = (
                    self._ha_controller.get_estimated_consumption()
                )
                if consumption_predictions and len(consumption_predictions) == 24:
                    self._consumption_predictions = consumption_predictions
            except (AttributeError, ValueError, KeyError) as e:
                _LOGGER.warning("Failed to update predictions: %s", str(e))

    def _validate_hour_input(self, hour):
        """Validate hour input and check if already processed."""
        if not 0 <= hour <= 23:
            _LOGGER.error("Invalid hour: %d", hour)
            return False

        # Validate against current time
        current_time = datetime.now()
        expected_hour = (
            current_time.hour - 1
        ) % 24  # Previous hour should have just completed

        if hour != expected_hour:
            _LOGGER.warning(
                "Hour mismatch: Asked to process hour %d but current time is %d:00, "
                "Should be processing hour %d",
                hour,
                current_time.hour,
                expected_hour,
            )

        # Check if we've processed this hour already
        if self._last_processed_hour == hour:
            _LOGGER.warning("Hour %02d already processed, skipping", hour)
            return self._create_cached_result(hour)

        return True

    def _create_cached_result(self, hour):
        """Create a result using cached data for already processed hour."""
        return {
            "hour": hour,
            "source": "cached",
            "battery_soc": self._battery_soc.get(hour, self.min_soc),
            "battery_soe": self._battery_soe.get(hour, self.reserved_capacity),
            "system_production": self._system_production.get(hour, 0.0),
            "import_from_grid": self._import_from_grid.get(hour, 0.0),
            "load_consumption": self._load_consumption.get(hour, 0.0),
            "export_to_grid": self._export_to_grid.get(hour, 0.0),
            "battery_charge": self._battery_charge.get(hour, 0.0),
            "battery_discharge": self._battery_discharge.get(hour, 0.0),
            "solar_to_battery": self._solar_to_battery.get(hour, 0.0),
            "system_production_total": self._system_production_total.get(hour, 0.0),
            "self_consumption_total": self._self_consumption_total.get(hour, 0.0),
        }

    def _handle_initialization_hour(self, hour):
        """Handle the special case where system was initialized during this hour."""
        init_time = self._initialization_time
        current_time = datetime.now()

        # Check if we started in the middle of this hour
        same_hour_start = (
            init_time.hour == hour and init_time.date() == current_time.date()
        )

        if same_hour_start and self._last_processed_hour is None:
            _LOGGER.warning(
                "System initialized at %s - treating hour %02d:00 as partially observed",
                init_time.strftime("%H:%M"),
                hour,
            )

            # Get current SOC and store it
            if self._ha_controller:
                try:
                    current_soc = self._ha_controller.get_battery_soc()
                    self._battery_soc[hour] = current_soc
                    self._battery_soe[hour] = self._soc_to_energy(current_soc)
                    _LOGGER.info(
                        "Stored current SOC %.1f%% for hour %d",
                        current_soc,
                        hour,
                    )
                except (AttributeError, ValueError) as e:
                    _LOGGER.warning("Failed to get SOC: %s", str(e))

            # Mark this hour as processed
            self._last_processed_hour = hour

            # Return data with partial flag
            return {
                "hour": hour,
                "partial": True,
                "battery_soc": self._battery_soc.get(hour, 0),
            }

        return None

    def _fetch_hourly_sensor_data(self, hour):
        """Fetch sensor data for a specific hour."""
        try:
            today = datetime.now().date()
            hour_time = datetime.combine(today, time(hour=hour))

            # List of sensors to fetch
            hourly_sensors = self._get_cumulative_sensors()

            hourly_data = get_sensor_data(hourly_sensors, hour_time)

            # Check if data retrieval was successful
            if not hourly_data or hourly_data.get("status") != "success":
                _LOGGER.warning("Failed to fetch data for hour %d", hour)
                return None, None

            current_readings = hourly_data.get("data", {})

            # Ensure SOC is available
            current_readings = self._ensure_soc_in_readings(hour, current_readings)
        except (ValueError, KeyError) as e:
            _LOGGER.warning("Error fetching hourly sensor data: %s", str(e))
            return None, None
        else:
            return hourly_data, current_readings

    def _ensure_soc_in_readings(self, hour, current_readings):
        """Ensure SOC is present in readings, fetch from controller if needed."""
        if "rkm0d7n04x_statement_of_charge_soc" not in current_readings:
            _LOGGER.warning("Hour %d is missing SOC measurement", hour)

            # If SOC not in readings, try to get it from controller
            if self._ha_controller:
                try:
                    current_soc = self._ha_controller.get_battery_soc()
                    current_readings["rkm0d7n04x_statement_of_charge_soc"] = current_soc
                    _LOGGER.debug(
                        "Using current controller SOC instead: %.1f%%", current_soc
                    )
                except (AttributeError, ValueError) as e:
                    _LOGGER.warning("Failed to get SOC from controller: %s", str(e))
        else:
            soc_value = float(current_readings["rkm0d7n04x_statement_of_charge_soc"])
            _LOGGER.debug("Hour %d has measured SOC: %.1f%%", hour, soc_value)

        return current_readings

    def _process_hourly_sensor_data(self, hour, hourly_data, current_readings):
        """Process the hourly sensor data and calculate energy flows."""
        try:
            # Get previous hour readings
            previous_readings = self._get_previous_hour_readings_for_update(hour)

            if not current_readings or not previous_readings:
                return None

            # Calculate energy flows
            flows = self._calculate_hourly_energy_flows(
                current_readings, previous_readings, hour
            )

            # Validate and store flows
            if flows:
                validated_flows = self._validate_hourly_flows(flows, None, hour)
                self._store_energy_flows(hour, validated_flows, current_readings)

                # Update last processed hour
                self._last_processed_hour = hour

                # Create result with all data
                return self._create_energy_data_result(
                    hour, validated_flows, current_readings
                )

            _LOGGER.warning("No valid flows calculated for hour %d", hour)
            return self._create_soc_fallback_result(hour, current_readings)
        except (ValueError, KeyError, AttributeError) as e:
            _LOGGER.warning(
                "Error processing hourly sensor data for hour %d: %s", hour, str(e)
            )
            return None

    def _get_previous_hour_readings_for_update(self, hour):
        """Get previous hour readings for update_hour_data method."""
        if hour == 0:
            _LOGGER.info("Hour 0 - using initial values as baseline")
            return self._get_initial_baseline_readings()
        return self._get_previous_hour_readings(hour)

    def _create_energy_data_result(self, hour, validated_flows, current_readings):
        """Create a complete energy data result dictionary."""
        energy_data = {
            "hour": hour,
            "source": "direct_readings",
            "skipped": False,
        }

        # Add battery SOC/SOE if available
        if "rkm0d7n04x_statement_of_charge_soc" in current_readings:
            energy_data["battery_soc"] = float(
                current_readings["rkm0d7n04x_statement_of_charge_soc"]
            )
            energy_data["battery_soe"] = self._soc_to_energy(energy_data["battery_soc"])

        # Add energy flows
        for key, value in validated_flows.items():
            energy_data[key] = value

        _LOGGER.info(
            "Hour %02d updated: Solar=%.2f, Load=%.2f, Battery Δ=%.2f kWh, SOC=%.1f%%",
            hour,
            validated_flows.get("system_production", 0),
            validated_flows.get("load_consumption", 0),
            validated_flows.get("battery_charge", 0)
            - validated_flows.get("battery_discharge", 0),
            energy_data.get("battery_soc", 0),
        )

        return energy_data

    def _create_soc_fallback_result(self, hour, current_readings=None):
        """Create fallback result with SOC data if available."""
        if (
            current_readings
            and "rkm0d7n04x_statement_of_charge_soc" in current_readings
        ):
            return {
                "hour": hour,
                "source": "fallback",
                "skipped": True,
                "battery_soc": float(
                    current_readings["rkm0d7n04x_statement_of_charge_soc"]
                ),
                "battery_soe": self._soc_to_energy(
                    float(current_readings["rkm0d7n04x_statement_of_charge_soc"])
                ),
            }
        return self._create_fallback_result(hour)

    def _create_fallback_result(self, hour):
        """Create fallback result with current SOC from controller."""
        if self._ha_controller:
            try:
                current_soc = self._ha_controller.get_battery_soc()
                return {
                    "hour": hour,
                    "source": "fallback",
                    "skipped": True,
                    "battery_soc": current_soc,
                    "battery_soe": self._soc_to_energy(current_soc),
                }
            except (AttributeError, ValueError) as e:
                _LOGGER.warning("Failed to get SOC for fallback: %s", str(e))

        # Final fallback to minimum SOC
        return {
            "hour": hour,
            "source": "fallback",
            "skipped": True,
            "battery_soc": self.min_soc,
            "battery_soe": self.reserved_capacity,
        }

    def _validate_hourly_flows(self, flows, previous_flows, hour):
        """Apply additional validation to calculated flows to catch anomalies.

        Args:
            flows: Dictionary of calculated energy flows
            previous_flows: Dictionary of previous hour's flows (if available)
            hour: Hour of the day (0-23)

        Returns:
            Dictionary of validated/corrected flows

        """
        # Make a copy to avoid modifying the original
        validated = flows.copy() if flows else {}

        # Skip validation if flows is empty
        if not validated:
            return validated

        # 1. Cap unreasonably large values (more than 15 kWh per hour for any flow)
        for key, value in validated.items():
            if abs(value) > 15.0:
                _LOGGER.warning(
                    "Hour %d: Capping unreasonably large value for %s: %.2f kWh → 15.0 kWh",
                    hour,
                    key,
                    value,
                )
                validated[key] = 15.0 if value > 0 else -15.0

        # 2. Check for energy balance
        # Check if we have the new sensors to determine which validation approach to use
        has_system_production = "system_production_total" in validated
        has_self_consumption = "self_consumption_total" in validated

        if has_system_production and has_self_consumption:
            # More accurate energy balance with new sensors
            energy_in = validated.get("import_from_grid", 0) + validated.get(
                "system_production_total", 0
            )
            energy_out = validated.get("load_consumption", 0) + validated.get(
                "export_to_grid", 0
            )
        else:
            # Traditional energy balance
            energy_in = validated.get("import_from_grid", 0) + validated.get(
                "system_production", 0
            )
            battery_net = validated.get("battery_charge", 0) - validated.get(
                "battery_discharge", 0
            )
            energy_out = (
                validated.get("load_consumption", 0)
                + validated.get("export_to_grid", 0)
                + validated.get("aux_load", 0)
                + battery_net
            )

        # Only allow a reasonable tolerance (2 kWh or 20%, whichever is greater)
        balance_threshold = max(2.0, energy_in * 0.2)

        if abs(energy_in - energy_out) > balance_threshold:
            _LOGGER.warning(
                "Hour %d: Significant energy imbalance - Input=%.2f, Output=%.2f, Difference=%.2f",
                hour,
                energy_in,
                energy_out,
                energy_in - energy_out,
            )

            # Try to reconcile the balance by adjusting the most likely source of error
            if energy_in > energy_out:
                # Excess input - adjust to reasonable consumption
                deficit = energy_in - energy_out
                if validated.get("load_consumption", 0) < deficit:
                    _LOGGER.info(
                        "Hour %d: Adjusting load_consumption to maintain balance: %.2f → %.2f",
                        hour,
                        validated.get("load_consumption", 0),
                        validated.get("load_consumption", 0) + deficit,
                    )
                    validated["load_consumption"] = (
                        validated.get("load_consumption", 0) + deficit
                    )
            else:
                # Excess output - reduce to match input
                excess = energy_out - energy_in
                if validated.get("battery_discharge", 0) > excess:
                    # Reduce battery discharge
                    _LOGGER.info(
                        "Hour %d: Adjusting battery_discharge to maintain balance: %.2f → %.2f",
                        hour,
                        validated.get("battery_discharge", 0),
                        validated.get("battery_discharge", 0) - excess,
                    )
                    validated["battery_discharge"] = (
                        validated.get("battery_discharge", 0) - excess
                    )
                elif validated.get("load_consumption", 0) > excess:
                    # Reduce load consumption
                    _LOGGER.info(
                        "Hour %d: Adjusting load_consumption to maintain balance: %.2f → %.2f",
                        hour,
                        validated.get("load_consumption", 0),
                        validated.get("load_consumption", 0) - excess,
                    )
                    validated["load_consumption"] = (
                        validated.get("load_consumption", 0) - excess
                    )

        # 3. Consistency with previous hour
        if previous_flows:
            # Look for sudden, drastic changes in consumption
            prev_consumption = previous_flows.get("load_consumption", 0)
            curr_consumption = validated.get("load_consumption", 0)

            if (
                abs(curr_consumption - prev_consumption) > 5.0
                and curr_consumption > 2 * prev_consumption
            ):
                _LOGGER.warning(
                    "Hour %d: Suspicious load jump: %.2f → %.2f",
                    hour,
                    prev_consumption,
                    curr_consumption,
                )

                # Smooth the transition
                validated["load_consumption"] = (
                    curr_consumption + prev_consumption
                ) / 2
                _LOGGER.info(
                    "Hour %d: Smoothed load to %.2f",
                    hour,
                    validated["load_consumption"],
                )

        return validated

    def _calculate_hourly_energy_flows(
        self, current_readings, previous_readings, hour_of_day=None
    ):
        """Calculate energy flows from two consecutive hour readings.

        Args:
            current_readings: Dictionary with current hour's raw data
            previous_readings: Dictionary with previous hour's raw data
            hour_of_day: The hour (0-23) to validate time-based flows

        Returns:
            dict: Calculated energy flows

        """
        # Skip if either readings dict is empty
        if not current_readings or not previous_readings:
            _LOGGER.warning("Missing readings - cannot calculate flows")
            return None

        # Initialize flows with zeros
        flows = {
            "battery_charge": 0.0,
            "battery_discharge": 0.0,
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

        # Map of sensor names to flow names
        sensor_to_flow = {
            "rkm0d7n04x_lifetime_total_all_batteries_charged": "battery_charge",
            "rkm0d7n04x_lifetime_total_all_batteries_discharged": "battery_discharge",
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
            # Skip SOC sensor - it's not a cumulative meter
            if sensor_name == "rkm0d7n04x_statement_of_charge_soc":
                continue

            # Get current and previous values
            current_value = current_readings.get(sensor_name)
            previous_value = previous_readings.get(sensor_name)

            # Skip if either value is None or not a number
            if current_value is None or previous_value is None:
                _LOGGER.debug(
                    "Missing value for %s in hour %s", sensor_name, hour_of_day
                )
                continue

            try:
                # Convert to float to ensure numerical calculation
                current_value = float(current_value)
                previous_value = float(previous_value)

                # Handle day rollover (when value decreases)
                if current_value < previous_value:
                    _LOGGER.info(
                        "Detected rollover for %s: %s → %s",
                        sensor_name,
                        previous_value,
                        current_value,
                    )
                    flows[flow_key] = current_value
                else:
                    # Regular difference calculation
                    flows[flow_key] = current_value - previous_value
            except (ValueError, TypeError) as e:
                _LOGGER.warning("Error calculating flow for %s: %s", sensor_name, e)

        # Calculate derived flows using the more accurate method
        return self._calculate_derived_flows(flows, hour_of_day)

    def has_hour_data(self, hour):
        """Check if energy data exists for the specified hour.

        Args:
            hour: Hour to check (0-23)

        Returns:
            bool: True if data exists for this hour

        """
        return hour in self._load_consumption and hour in self._import_from_grid

    def get_processed_hours(self):
        """Get list of hours that have been processed.

        Returns:
            list: List of hours with processed data

        """
        return sorted(
            set(self._load_consumption.keys()).intersection(
                self._import_from_grid.keys()
            )
        )

    def get_consumption_predictions(self):
        """Get hourly consumption predictions.

        Returns:
            list: List of 24 hourly consumption predictions

        """
        return self._consumption_predictions

    def get_solar_predictions(self):
        """Get hourly solar production predictions.

        Returns:
            list: List of 24 hourly solar production predictions

        """
        return self._solar_predictions

    def get_energy_data(self, hour):
        """Get all energy data for a specific hour.

        Args:
            hour: Hour to get data for (0-23)

        Returns:
            dict: Dictionary with all energy flows for the hour or None if no data

        """
        if not self.has_hour_data(hour):
            return None

        return {
            "battery_soc": self._battery_soc.get(hour),
            "battery_soe": self._battery_soe.get(hour),
            "battery_charge": self._battery_charge.get(hour),
            "battery_discharge": self._battery_discharge.get(hour),
            "system_production": self._system_production.get(hour),
            "export_to_grid": self._export_to_grid.get(hour),
            "load_consumption": self._load_consumption.get(hour),
            "import_from_grid": self._import_from_grid.get(hour),
            "grid_to_battery": self._grid_to_battery.get(hour),
            "solar_to_battery": self._solar_to_battery.get(hour),
            "aux_loads": self._aux_loads.get(hour),
            "self_consumption": self._self_consumption.get(hour),
            "system_production_total": self._system_production_total.get(hour),
            "self_consumption_total": self._self_consumption_total.get(hour),
        }

    def get_energy_value(self, hour, key, default=0.0):
        """Get a specific energy value for an hour.

        This provides selective access to individual values without
        creating dozens of separate getter methods.

        Args:
            hour: Hour to get data for (0-23)
            key: Energy value key (e.g., 'solar_to_battery', 'battery_charge')
            default: Default value if data doesn't exist

        Returns:
            float: The requested energy value or default

        """
        # Map of public keys to internal attribute names
        attr_map = {
            "battery_soc": "_battery_soc",
            "battery_soe": "_battery_soe",
            "battery_charge": "_battery_charge",
            "battery_discharge": "_battery_discharge",
            "system_production": "_system_production",
            "export_to_grid": "_export_to_grid",
            "load_consumption": "_load_consumption",
            "import_from_grid": "_import_from_grid",
            "grid_to_battery": "_grid_to_battery",
            "solar_to_battery": "_solar_to_battery",
            "aux_loads": "_aux_loads",
            "self_consumption": "_self_consumption",
            "system_production_total": "_system_production_total",
            "self_consumption_total": "_self_consumption_total",
        }

        # Get the internal attribute name
        attr_name = attr_map.get(key)
        if not attr_name:
            _LOGGER.warning("Unknown energy data key: %s", key)
            return default

        # Get the attribute
        attr = getattr(self, attr_name, {})

        # Return the value for the hour or default
        return attr.get(hour, default)

    def get_full_day_energy_profile(self, current_hour=None):
        """Get combined actual/predicted energy data for all 24 hours.

        Returns a 24-hour energy profile automatically combining:
        - Actual measurements for hours that have already occurred
        - Predictions for current and future hours

        Args:
            current_hour: Optional override for current hour (0-23).
                        If not provided, uses system time.

        Returns:
            Dict with 24-hour arrays for 'consumption', 'solar', 'battery_soe', and 'battery_soc'

        """
        # Determine current hour if not provided
        if current_hour is None:
            now = datetime.now()
            current_hour = now.hour

        # Ensure valid hour
        if not 0 <= current_hour <= 23:
            _LOGGER.error("Invalid hour: %d", current_hour)
            current_hour = 0

        # Prepare result arrays
        consumption = []
        solar = []
        battery_soe = []
        battery_soc = []

        # Last completed hour is the previous hour
        last_actual_hour = current_hour - 1
        if last_actual_hour < 0:
            last_actual_hour = -1  # No historical data yet today

        _LOGGER.debug(
            "Current hour: %d, Last actual hour: %d",
            current_hour,
            last_actual_hour,
        )

        # Get scheduled actions for future hours if available
        future_actions = None
        if (
            hasattr(self, "_current_schedule")
            and self._current_schedule
            and hasattr(self._current_schedule, "actions")
        ):
            future_actions = self._current_schedule.actions
            _LOGGER.debug("Using future actions from current schedule")

        # Find the latest SOC/SOE from processed hours to use as baseline for future projections
        latest_soc = None
        latest_soe = None

        # First look for the last processed hour's data
        if last_actual_hour >= 0 and last_actual_hour in self._battery_soc:
            latest_soc = self._battery_soc[last_actual_hour]
            latest_soe = self._battery_soe[last_actual_hour]
            _LOGGER.debug(
                "Using latest historical SOC from hour %d: %.1f%%",
                last_actual_hour,
                latest_soc,
            )
        # If no historical data for the last hour, try current hour
        elif current_hour in self._battery_soc:
            latest_soc = self._battery_soc[current_hour]
            latest_soe = self._battery_soe[current_hour]
            _LOGGER.debug(
                "Using SOC from current hour %d: %.1f%%",
                current_hour,
                latest_soc,
            )
        # Fallback to default values if no historical data is available
        else:
            latest_soc = self.min_soc
            latest_soe = self.reserved_capacity
            _LOGGER.debug(
                "No historical SOC data available, using default: %.1f%%", latest_soc
            )

        # Initialize running SOE/SOC for future projections
        running_soc = latest_soc
        running_soe = latest_soe

        # Add data for all 24 hours
        for hour in range(24):
            # Hour is considered historical if it's complete (less than current hour)
            # and we have actual data for it
            is_historical_hour = hour < current_hour and hour in self._load_consumption

            if is_historical_hour:
                # Use actual data for past hours
                consumption.append(self._load_consumption[hour])
                solar.append(self._system_production[hour])

                # For past hours, use recorded SOE/SOC values
                if hour in self._battery_soe and hour in self._battery_soc:
                    battery_soe.append(self._battery_soe[hour])
                    battery_soc.append(self._battery_soc[hour])
                else:
                    # If missing for some reason, use running values
                    battery_soe.append(running_soe)
                    battery_soc.append(running_soc)

                # Update running values at the boundary hour
                if hour == last_actual_hour:
                    if hour in self._battery_soe and hour in self._battery_soc:
                        running_soe = self._battery_soe[hour]
                        running_soc = self._battery_soc[hour]
            else:
                # Use predictions for current and future hours
                consumption.append(
                    self._consumption_predictions[hour]
                    if hour < len(self._consumption_predictions)
                    else self.default_consumption
                )
                solar.append(
                    self._solar_predictions[hour]
                    if hour < len(self._solar_predictions)
                    else 0.0
                )

                # For future hours, simulate SOE/SOC based on previous hour and planned actions
                if future_actions and hour < len(future_actions):
                    action = future_actions[hour]

                    # Update running SOE based on scheduled action
                    # Only apply action if SOC allows (don't charge above 100%, don't discharge below min_soc)
                    if action > 0 and running_soc < 100.0:  # Charging
                        # Don't exceed total capacity
                        new_soe = min(self.total_capacity, running_soe + action)
                        running_soe = new_soe
                    elif action < 0 and running_soc > self.min_soc:  # Discharging
                        # Don't go below reserved capacity
                        new_soe = max(self.reserved_capacity, running_soe + action)
                        running_soe = new_soe

                    # Calculate SOC from SOE
                    running_soc = self._energy_to_soc(running_soe)

                    _LOGGER.debug(
                        "Hour %d: Future SOC updated to %.1f%% based on action %.2f kWh",
                        hour,
                        running_soc,
                        action,
                    )

                battery_soe.append(running_soe)
                battery_soc.append(running_soc)

        # Return combined data
        return {
            "consumption": consumption,
            "solar": solar,
            "battery_soe": battery_soe,
            "battery_soc": battery_soc,
            "actual_hours": last_actual_hour + 1,  # Number of hours with actual data
        }

    # Helper methods
    def _soc_to_energy(self, soc):
        """Convert battery SOC percentage to energy in kWh."""
        if soc is None:
            return self.reserved_capacity
        return (soc / 100.0) * self.total_capacity

    def _energy_to_soc(self, energy):
        """Convert energy in kWh to battery SOC percentage."""
        if energy is None:
            return self.min_soc
        return (energy / self.total_capacity) * 100.0

    def log_energy_balance(self):
        """Log hourly energy balance report in table format."""
        # Get current hour for determining which hours are historical vs predicted
        current_hour = datetime.now().hour

        # Get combined data with both historical and predicted values
        combined_data = self.get_full_day_energy_profile(current_hour)
        consumption_predictions = combined_data["consumption"]
        solar_predictions = combined_data["solar"]
        battery_soe_predictions = combined_data["battery_soe"]
        battery_soc_predictions = combined_data["battery_soc"]

        # Calculate hourly and total values for all 24 hours (historical + predictions)
        hourly_data = []

        # Initialize totals for all data (historical + projected)
        totals = {
            "system_production": 0.0,
            "import_from_grid": 0.0,
            "load_consumption": 0.0,
            "export_to_grid": 0.0,
            "battery_charge": 0.0,
            "battery_discharge": 0.0,
            "grid_to_battery": 0.0,
            "solar_to_battery": 0.0,
            "aux_load": 0.0,
        }

        # Process all 24 hours
        for hour in range(24):
            # CRITICAL FIX: Make sure current hour is always treated as a prediction
            # Hour is historical only if it's completed (less than current hour)
            is_historical = hour < current_hour

            # Additional verification for historical hours
            if is_historical:
                # Check if we actually have data for this hour
                has_flow_data = (
                    hour in self._import_from_grid and hour in self._load_consumption
                )
                is_historical = is_historical and has_flow_data

            # Get values - either historical or predicted
            if is_historical:
                # Use historical data for this hour
                solar_production = self._system_production.get(hour, 0.0)
                grid_to_battery = self._grid_to_battery.get(hour, 0.0)
                solar_to_battery = self._solar_to_battery.get(hour, 0.0)
                battery_charge = self._battery_charge.get(hour, 0.0)
                import_from_grid = self._import_from_grid.get(hour, 0.0)
                load_consumption = self._load_consumption.get(hour, 0.0)
                export_to_grid = self._export_to_grid.get(hour, 0.0)
                battery_discharge = self._battery_discharge.get(hour, 0.0)
                aux_load = self._aux_loads.get(hour, 0.0)

                # Get battery SOC - either from stored data or from calculation
                if hour in self._battery_soc:
                    battery_soc = self._battery_soc.get(hour, 0.0)
                    battery_soe = self._battery_soe.get(hour, 0.0)
                else:
                    # Use predicted values from combined data
                    battery_soc = battery_soc_predictions[hour]
                    battery_soe = battery_soe_predictions[hour]
            else:
                # Use predictions for this hour
                solar_production = solar_predictions[hour]
                load_consumption = consumption_predictions[hour]

                # Simple predictions for future hours
                # Assume no battery activity for now in predictions
                battery_charge = 0.0
                battery_discharge = 0.0
                grid_to_battery = 0.0
                solar_to_battery = 0.0
                aux_load = 0.0

                # Simplified prediction for import and export
                if solar_production > load_consumption:
                    import_from_grid = 0.0
                    export_to_grid = solar_production - load_consumption
                else:
                    import_from_grid = load_consumption - solar_production
                    export_to_grid = 0.0

                # Get predicted battery SOC/SOE from combined data
                battery_soc = battery_soc_predictions[hour]
                battery_soe = battery_soe_predictions[hour]

            # Calculate energy balance for this hour - FIXED CALCULATION
            energy_in = import_from_grid + solar_production

            # Include battery net change as part of output
            energy_out = (
                load_consumption
                + export_to_grid
                + aux_load
                + battery_charge
                - battery_discharge
            )

            balance = energy_in - energy_out

            # Compile hour data
            hour_data = {
                "hour": hour,
                "is_historical": is_historical,
                "battery_soc": battery_soc,
                "battery_soe": battery_soe,
                "system_production": solar_production,
                "import_from_grid": import_from_grid,
                "load_consumption": load_consumption,
                "export_to_grid": export_to_grid,
                "battery_charge": battery_charge,
                "battery_discharge": battery_discharge,
                "grid_to_battery": grid_to_battery,
                "solar_to_battery": solar_to_battery,
                "aux_load": aux_load,
                "energy_in": energy_in,
                "energy_out": energy_out,
                "balance": balance,
            }

            hourly_data.append(hour_data)

            # IMPORTANT FIX: Update totals for both historical and predicted hours
            totals["system_production"] += solar_production
            totals["import_from_grid"] += import_from_grid
            totals["load_consumption"] += load_consumption
            totals["export_to_grid"] += export_to_grid
            totals["battery_charge"] += battery_charge
            totals["battery_discharge"] += battery_discharge
            totals["grid_to_battery"] += grid_to_battery
            totals["solar_to_battery"] += solar_to_battery
            totals["aux_load"] += aux_load

        # Find all hours with actual energy data
        historical_hours = []
        for data in hourly_data:
            if data["is_historical"]:
                historical_hours.append(data["hour"])

        # Get first and last historical hours for reporting
        if historical_hours:
            first_hour = min(historical_hours)
            last_hour = max(historical_hours)
        else:
            first_hour = current_hour
            last_hour = current_hour

        # Calculate overall energy balance for historical data
        if historical_hours:
            # Calculate battery change from first to last hour
            if first_hour in self._battery_soe and last_hour in self._battery_soe:
                first_soe = self._battery_soe[first_hour]
                last_soe = self._battery_soe[last_hour]
                battery_net_change = last_soe - first_soe
            else:
                battery_net_change = 0.0
                first_soe = self.reserved_capacity
                last_soe = self.reserved_capacity

            # FIXED ENERGY BALANCE CALCULATION
            # Total energy flows
            total_energy_in = totals["import_from_grid"] + totals["system_production"]

            # Correctly account for battery in the total energy flows
            total_energy_out = (
                totals["load_consumption"]
                + totals["export_to_grid"]
                + totals["aux_load"]
                + totals["battery_charge"]  # Add battery charging to output
                # Subtract discharging from output
                - totals["battery_discharge"]
            )

            # Avoid division by zero
            if total_energy_in > 0:
                balance_difference = total_energy_in - total_energy_out
                balance_percent = (balance_difference / total_energy_in) * 100
            else:
                balance_difference = 0
                balance_percent = 0
        else:
            # No historical data, use predictions only
            first_hour = 0
            last_hour = 23
            battery_net_change = 0.0
            first_soe = self.reserved_capacity
            last_soe = self.reserved_capacity
            total_energy_in = 0.0
            total_energy_out = 0.0
            balance_difference = 0.0
            balance_percent = 0.0

        # Format the report table with proper period information
        period_display = f"{first_hour:02d}:00 - {last_hour:02d}:00"
        if first_hour == last_hour:
            period_display = f"{first_hour:02d}:00"

        self._format_and_log_report(
            hourly_data,
            totals,
            first_hour,
            last_hour,
            total_energy_in,
            total_energy_out,
            battery_net_change,
            balance_difference,
            balance_percent,
            period_display,
        )

        return hourly_data, totals

    def _format_and_log_report(
        self,
        hourly_data,
        totals,
        first_hour,
        last_hour,
        total_energy_in,
        total_energy_out,
        battery_net_change,
        balance_difference,
        balance_percent,
        period_display=None,
    ):
        """Format and log the energy balance report.

        Args:
            hourly_data: List of hourly data dictionaries
            totals: Dictionary of total values
            first_hour: First hour in the period
            last_hour: Last hour in the period
            total_energy_in: Total energy input
            total_energy_out: Total energy output
            battery_net_change: Net battery energy change
            balance_difference: Energy balance difference
            balance_percent: Energy balance percentage
            period_display: Optional formatted period string

        """
        # Enhanced table with solar_to_battery column
        lines = [
            "\n╔════════════════════════════════════════════════════════════════════════════════════════════════════════╗",
            "║                                          Energy Balance Report                                         ║",
            "╠════════╦══════════════════════════╦══════════════════════════╦══════════════════════════════════╦══════╣",
            "║        ║       Energy Input       ║       Energy Output      ║           Battery Flows          ║      ║",
            "║  Hour  ╠════════╦════════╦════════╬════════╦════════╦════════╬════════╦════════╦════════╦═══════╣ SOC  ║",
            "║        ║ Solar  ║ Grid   ║ Total  ║ Home   ║ Export ║ Aux.   ║ Charge ║Dischrge║Solar->B║ Grid  ║ (%)  ║",
            "║        ║ (kWh)  ║ (kWh)  ║ (kWh)  ║ (kWh)  ║ (kWh)  ║ (kWh)  ║ (kWh)  ║ (kWh)  ║ (kWh)  ║ ->Bat ║      ║",
            "╠════════╬════════╬════════╬════════╬════════╬════════╬════════╬════════╬════════╬════════╬═══════╬══════╣",
        ]

        # Determine current hour for prediction indicators
        current_hour = datetime.now().hour

        # Format hourly data rows
        for data in hourly_data:
            # Mark as prediction only if it's BOTH:
            # 1. Future hour (>= current hour), OR
            # 2. Not marked as historical in the data (no actual measurements)
            # This way, hour 00:00 won't be marked as prediction if it has actual data
            hour = data["hour"]
            is_historical = data.get("is_historical", False)

            # Use prediction indicator only for future hours or non-historical data points
            indicator = "★" if (hour >= current_hour or not is_historical) else " "

            # For values, use star only if the current row has the indicator
            value_indicator = indicator

            solar_star = value_indicator if not is_historical else " "
            grid_star = value_indicator if not is_historical else " "
            home_star = value_indicator if not is_historical else " "
            export_star = value_indicator if not is_historical else " "
            aux_star = value_indicator if not is_historical else " "
            charge_star = value_indicator if not is_historical else " "
            discharge_star = value_indicator if not is_historical else " "
            solar_to_bat_star = value_indicator if not is_historical else " "
            grid_to_bat_star = value_indicator if not is_historical else " "

            row = (
                f"║ {data['hour']:02d}:00{indicator} "
                f"║ {data['system_production']:>5.1f}{solar_star} "
                f"║ {data['import_from_grid']:>5.1f}{grid_star} "
                f"║ {data['energy_in']:>6.1f} "
                f"║ {data['load_consumption']:>5.1f}{home_star} "
                f"║ {data['export_to_grid']:>5.1f}{export_star} "
                f"║ {data['aux_load']:>5.1f}{aux_star} "
                f"║ {data['battery_charge']:>5.1f}{charge_star} "
                f"║ {data['battery_discharge']:>5.1f}{discharge_star} "
                f"║ {data.get('solar_to_battery', 0):>5.1f}{solar_to_bat_star} "
                f"║ {data.get('grid_to_battery', 0):>5.1f}{grid_to_bat_star}"
                f"║ {data['battery_soc']:>4.0f} ║"
            )
            lines.append(row)

        # Add separator before totals
        lines.append(
            "╠════════╬════════╬════════╬════════╬════════╬════════╬════════╬════════╬════════╬════════╬═══════╬══════╣"
        )

        # Add totals row with all totals
        totals_row = (
            "║ TOTAL  "
            f"║ {totals['system_production']:>5.1f}  "
            f"║ {totals['import_from_grid']:>5.1f}  "
            f"║ {total_energy_in:>6.1f} "
            f"║ {totals['load_consumption']:>5.1f}  "
            f"║ {totals['export_to_grid']:>5.1f}  "
            f"║ {totals['aux_load']:>5.1f}  "
            f"║ {totals['battery_charge']:>5.1f}  "
            f"║ {totals['battery_discharge']:>5.1f}  "
            f"║ {totals.get('solar_to_battery', 0):>5.1f}  "
            f"║ {totals.get('grid_to_battery', 0):>5.1f} "
            f"║      ║"
        )
        lines.append(totals_row)

        # Close the table
        lines.append(
            "╚════════╩════════╩════════╩════════╩════════╩════════╩════════╩════════╩════════╩════════╩═══════╩══════╝"
        )

        # Use provided period display or generate default
        if period_display is None:
            period_display = f"{first_hour:02d}:00 - {last_hour:02d}:00"

        # Add summary footer with exact formatting
        lines.append("\nEnergy Balance Summary:")
        lines.append("  Period: " + period_display + "  (★ indicates predicted values)")
        lines.append("  Total Energy In: " + str(round(total_energy_in, 2)) + " kWh")
        lines.append("  Total Energy Out: " + str(round(total_energy_out, 2)) + " kWh")

        balance_diff_str = str(round(balance_difference, 2))
        balance_pct_str = str(round(balance_percent, 1))
        lines.append(
            "  Balance Difference: "
            + balance_diff_str
            + " kWh ("
            + balance_pct_str
            + "%)"
        )

        # Add summary of battery flows
        if totals["battery_charge"] > 0 or totals["battery_discharge"] > 0:
            lines.append("\nBattery Energy Flows:")

            # Total battery charging line
            batt_charge_str = str(round(totals["battery_charge"], 2))
            lines.append("  Total battery charging: " + batt_charge_str + " kWh")

            # Solar to battery line
            solar_value = totals.get("solar_to_battery", 0)
            solar_value_str = str(round(solar_value, 2))

            if totals["battery_charge"] > 0:
                solar_percentage = (solar_value / totals["battery_charge"]) * 100
            else:
                solar_percentage = 0
            solar_percentage_str = str(round(solar_percentage, 1))

            lines.append(
                "  - From solar: "
                + solar_value_str
                + " kWh ("
                + solar_percentage_str
                + "%)"
            )

            # Grid to battery line
            grid_value = totals.get("grid_to_battery", 0)
            grid_value_str = str(round(grid_value, 2))

            if totals["battery_charge"] > 0:
                grid_percentage = (grid_value / totals["battery_charge"]) * 100
            else:
                grid_percentage = 0
            grid_percentage_str = str(round(grid_percentage, 1))

            lines.append(
                "  - From grid: "
                + grid_value_str
                + " kWh ("
                + grid_percentage_str
                + "%)"
            )

            # Battery discharge line
            discharge_value_str = str(round(totals["battery_discharge"], 2))
            lines.append("  Total battery discharging: " + discharge_value_str + " kWh")

        # Add warning if significant imbalance
        if abs(balance_percent) > 5:
            lines.append(
                f"\n⚠️  Significant energy imbalance detected: {balance_percent:.1f}%"
            )

        lines.append("\n")

        # Log the formatted report
        _LOGGER.info("\n".join(lines))
