"""Home Assistant pyscript Controller."""


class HomeAssistantController:
    """A class for interacting with Inverter controls via Home Assistant."""

    def __init__(self) -> None:
        """Initialize the Controller with default values."""
        self.df_batt_schedule = None
        self.max_attempts = 4
        self.retry_delay = 4  # seconds
        self.test_mode = False

    def service_call_with_retry(self, service_domain, service_name, **kwargs):
        """Call the service and retry upon failure."""
        # List of operations that modify state (write operations)
        write_operations = [
            ("growatt_server", "update_tlx_inverter_time_segment"),
            ("switch", "turn_on"),
            ("switch", "turn_off"),
            ("number", "set_value"),
        ]

        # List of operations that return data
        read_operations = [("growatt_server", "read_tlx_inverter_time_segments")]

        # Only block write operations in test mode
        is_write_operation = (service_domain, service_name) in write_operations
        is_read_operation = (service_domain, service_name) in read_operations

        # Test mode only blocks write operations, never read operations
        if self.test_mode and is_write_operation:
            log.info(
                "[TEST MODE] Would call service %s.%s with args: %s",
                service_domain,
                service_name,
                kwargs,
            )
            return None

        for attempt in range(self.max_attempts):
            try:
                # Handle service calls that return data
                if is_read_operation:
                    # For services that return data, we need to use return_response=True
                    result = service.call(
                        service_domain, service_name, return_response=True, **kwargs
                    )
                    log.debug(
                        "Service call %s.%s succeeded on attempt %d/%d",
                        service_domain,
                        service_name,
                        attempt + 1,
                        self.max_attempts,
                    )
                    return result
                # Regular service call with no return value
                service.call(service_domain, service_name, **kwargs)
                log.debug(
                    "Service call %s.%s succeeded on attempt %d/%d",
                    service_domain,
                    service_name,
                    attempt + 1,
                    self.max_attempts,
                )
                return None  # Success, exit function
            except Exception as e:
                if attempt < self.max_attempts - 1:  # Not the last attempt
                    log.warning(
                        "Service call %s.%s failed on attempt %d/%d: %s. Retrying in %d seconds...",
                        service_domain,
                        service_name,
                        attempt + 1,
                        self.max_attempts,
                        str(e),
                        self.retry_delay,
                    )
                    task.sleep(self.retry_delay)
                else:  # Last attempt failed
                    log.error(
                        "Service call %s.%s failed on final attempt %d/%d: %s",
                        service_domain,
                        service_name,
                        attempt + 1,
                        self.max_attempts,
                        str(e),
                    )
                    raise  # Re-raise the last exception

    def get_sensor_value(self, sensor_name):
        """Get value from any sensor by name."""
        try:
            return float(state.get(f"sensor.{sensor_name}"))
        except (ValueError, TypeError, NameError):
            log.warning("Could not get value for sensor.%s", sensor_name)
            return 0.0

    def get_estimated_consumption(self) -> list:
        """Get estimated hourly consumption for 24 hours."""
        avg_consumption = self.get_sensor_value("48h_average_grid_import_power") / 1000
        return [avg_consumption] * 24

    def get_solar_generation_today(self) -> float:
        """Get the current solar generation reading (cumulative for today)."""
        return self.get_sensor_value("rkm0d7n04x_solar_production_today")  # noqa: F821

    def get_current_consumption(self) -> float:
        # Note: This is not grid import power, but home consumption (i.e. excl. battery, BEV, including solar production)
        """Get the current hour's home consumption in kWh."""
        return self.get_sensor_value("1h_average_grid_import_power")

    def get_battery_charge_today(self) -> float:
        """Get total battery charging for today in kWh."""
        return self.get_sensor_value("rkm0d7n04x_all_batteries_charged_today")

    def get_battery_discharge_today(self) -> float:
        """Get total battery discharging for today in kWh."""
        return self.get_sensor_value("rkm0d7n04x_all_batteries_discharged_today")

    def get_self_consumption_today(self) -> float:
        """Get total solar self-consumption for today in kWh."""
        return self.get_sensor_value("rkm0d7n04x_self_consumption_today")

    def get_export_to_grid_today(self) -> float:
        """Get total export to grid for today in kWh."""
        return self.get_sensor_value("rkm0d7n04x_export_to_grid_today")

    def get_load_consumption_today(self) -> float:
        """Get total home load consumption for today in kWh."""
        return self.get_sensor_value("rkm0d7n04x_load_consumption_today")

    def get_import_from_grid_today(self) -> float:
        """Get total import from grid for today in kWh."""
        return self.get_sensor_value("rkm0d7n04x_import_from_grid_today")

    def get_grid_to_battery_today(self) -> float:
        """Get total grid to battery charging for today in kWh."""
        return self.get_sensor_value("rkm0d7n04x_batteries_charged_from_grid_today")

    # Optional auxiliary load sensors
    def get_ev_energy_today(self) -> float:
        """Get total EV charging energy for today in kWh."""
        return self.get_sensor_value("zap263668_energy_today")

    def get_battery_soc(self) -> float:
        """Get the battery state of charge (SOC)."""
        return self.get_sensor_value("rkm0d7n04x_statement_of_charge_soc")

    def get_charge_stop_soc(self) -> float:
        """Get the charge stop state of charge (SOC)."""
        return float(state.get("number.rkm0d7n04x_charge_stop_soc"))

    def set_charge_stop_soc(self, charge_stop_soc: int):
        """Set the charge stop state of charge (SOC)."""

        self.service_call_with_retry(
            "number",
            "set_value",
            entity_id="number.rkm0d7n04x_charge_stop_soc",
            value=charge_stop_soc,
            blocking=True,
        )

    def get_discharge_stop_soc(self) -> int:
        """Get the discharge stop state of charge (SOC)."""
        return float(state.get("number.rkm0d7n04x_discharge_stop_soc"))

    def set_discharge_stop_soc(self, discharge_stop_soc: int):
        """Set the charge stop state of charge (SOC)."""

        self.service_call_with_retry(
            "number",
            "set_value",
            entity_id="number.rkm0d7n04x_discharge_stop_soc",
            value=discharge_stop_soc,
            blocking=True,
        )

    def get_charging_power_rate(self) -> int:
        """Get the charging power rate."""
        return float(state.get("number.rkm0d7n04x_charging_power_rate"))

    def set_charging_power_rate(self, rate: int):
        """Set the charging power rate."""

        self.service_call_with_retry(
            "number",
            "set_value",
            entity_id="number.rkm0d7n04x_charging_power_rate",
            value=rate,
            blocking=True,
        )

    def get_discharging_power_rate(self) -> int:
        """Get the discharging power rate."""
        return float(state.get("number.rkm0d7n04x_discharging_power_rate"))

    def set_discharging_power_rate(self, rate: int):
        """Set the discharging power rate."""

        self.service_call_with_retry(
            "number",
            "set_value",
            entity_id="number.rkm0d7n04x_discharging_power_rate",
            value=rate,
            blocking=True,
        )

    def get_battery_charge_power(self) -> float:
        """Get current battery charging power in watts."""
        return self.get_sensor_value("rkm0d7n04x_all_batteries_charge_power")

    def get_battery_discharge_power(self) -> float:
        """Get current battery discharging power in watts."""
        return self.get_sensor_value("rkm0d7n04x_all_batteries_discharged_power")

    def set_grid_charge(self, enable: bool):
        """Enable or disable grid charging."""
        if enable:
            log.info("Enabling grid charge")
            self.service_call_with_retry(
                "switch",
                "turn_on",
                entity_id="switch.rkm0d7n04x_charge_from_grid",
                blocking=True,
            )
        else:
            log.info("Disabling grid charge")
            self.service_call_with_retry(
                "switch",
                "turn_off",
                entity_id="switch.rkm0d7n04x_charge_from_grid",
                blocking=True,
            )

    def grid_charge_enabled(self) -> bool:
        """Return True if grid charging is enabled."""
        return state.get("switch.rkm0d7n04x_charge_from_grid") == "on"

    def set_inverter_time_segment(
        self,
        segment_id: int,
        batt_mode: str,
        start_time: int,
        end_time: int,
        enabled: bool,
    ):
        """Set the inverter time segment with retry logic."""

        self.service_call_with_retry(
            "growatt_server",
            "update_tlx_inverter_time_segment",
            segment_id=segment_id,
            batt_mode=batt_mode,
            start_time=start_time,
            end_time=end_time,
            enabled=enabled,
            blocking=True,
        )

    def read_inverter_time_segments(self):
        """Read all time segments from the inverter with retry logic."""
        try:
            # Call the service and get the response
            result = self.service_call_with_retry(
                "growatt_server",
                "read_tlx_inverter_time_segments",
                blocking=True,
                return_response=True,
            )

            if result and "time_segments" in result:
                return result["time_segments"]

            # If no segments were returned, try again later
            log.warning("No time segments available yet, will try again later")
            return []

        except Exception as e:
            log.warning("Failed to read time segments: %s", str(e))
            return []  # Return empty list instead of failing

    def print_inverter_status(self):
        """Print the battery settings and consumption prediction."""
        test_mode_str = "[TEST MODE] " if self.test_mode else ""
        (
            "\n\n===================================\n"
            "%sInverter Settings\n"
            "===================================\n"
            "Charge from Grid Enabled:     %5s\n"
            "State of Charge (SOC):       %5d%%\n"
            "Charge Stop SOC:             %5d%%\n"
            "Charging Power Rate:         %5d%%\n"
            "Discharging Power Rate:      %5d%%\n"
            "Discharge Stop SOC:          %5d%%\n",
            test_mode_str,
            self.grid_charge_enabled(),
            self.get_battery_soc(),
            self.get_charge_stop_soc(),
            self.get_charging_power_rate(),
            self.get_discharging_power_rate(),
            self.get_discharge_stop_soc(),
        )

    def set_test_mode(self, enabled: bool):
        """Enable or disable test mode."""
        self.test_mode = enabled
        ("%s test mode", "Enabled" if enabled else "Disabled")

    def disable_all_TOU_settings(self):
        """Clear the Time of Use (TOU) settings."""

        for segment_id in range(1, 9):
            self.set_inverter_time_segment(
                segment_id=segment_id,
                batt_mode="battery-first",
                start_time="00:00",
                end_time="23:59",
                enabled=False,
            )

    def get_nordpool_prices_today(self) -> list[float]:
        """Get today's Nordpool prices from Home Assistant sensor.

        Properly handles DST transitions by ensuring 24 hour values are returned.

        Returns:
            List of hourly prices for today (24 values)

        """
        try:
            # First check raw data availability
            raw_today = state.get("sensor.nordpool_kwh_se4_sek_2_10_025.raw_today")

            if not raw_today:
                # Fallback to regular prices array if raw data not available
                prices = state.get("sensor.nordpool_kwh_se4_sek_2_10_025.today")
                if not prices:
                    raise ValueError("No prices available from Nordpool sensor")
                return prices

            # Process raw data to handle DST transitions
            processed_prices = []

            for hour_data in raw_today:
                # Extract value directly - we don't need to parse the timestamps
                # since we know there are 23 hours during spring forward
                processed_prices.append(hour_data["value"])

            # Ensure we have exactly 24 hours
            if len(processed_prices) == 23:
                # This is a spring forward DST day (we're missing one hour)
                log.info("Detected spring forward DST transition - adding extra hour")
                # Add an extra hour (duplicate middle hour to avoid affecting peaks)
                middle_idx = len(processed_prices) // 2
                processed_prices.insert(middle_idx, processed_prices[middle_idx])
            elif len(processed_prices) == 25:
                # This is a fall back DST day (we have an extra hour)
                log.info("Detected fall back DST transition - removing extra hour")
                # Remove the duplicate hour
                middle_idx = len(processed_prices) // 2
                processed_prices.pop(middle_idx)

            # Final validation
            if len(processed_prices) != 24:
                log.warning(
                    "Unexpected number of hours: %d, adjusting to 24",
                    len(processed_prices),
                )
                if len(processed_prices) < 24:
                    processed_prices.extend(
                        [processed_prices[-1]] * (24 - len(processed_prices))
                    )
                else:
                    processed_prices = processed_prices[:24]

            return processed_prices

        except (ValueError, AttributeError, KeyError) as e:
            log.warning("Failed to get Nordpool prices: %s", str(e))
            # Return default values as fallback
            return [0.5] * 24

    def get_nordpool_prices_tomorrow(self) -> list[float]:
        """Get tomorrow's Nordpool prices from Home Assistant sensor.

        Properly handles DST transitions by ensuring 24 hour values are returned.

        Returns:
            List of hourly prices for tomorrow (24 values)

        """
        try:
            # First check raw data availability
            raw_tomorrow = state.get(
                "sensor.nordpool_kwh_se4_sek_2_10_025.raw_tomorrow"
            )

            if not raw_tomorrow:
                # Fallback to regular prices array if raw data not available
                prices = state.get("sensor.nordpool_kwh_se4_sek_2_10_025.tomorrow")
                if not prices:
                    raise ValueError("No prices available for tomorrow yet")
                return prices

            # Process raw data to handle DST transitions
            processed_prices = []

            for hour_data in raw_tomorrow:
                # Extract value directly
                processed_prices.append(hour_data["value"])

            # Ensure we have exactly 24 hours
            if len(processed_prices) == 23:
                # This is a spring forward DST day (we're missing one hour)
                log.info(
                    "Detected spring forward DST transition for tomorrow - adding extra hour"
                )
                # Add an extra hour (duplicate middle hour to avoid affecting peaks)
                middle_idx = len(processed_prices) // 2
                processed_prices.insert(middle_idx, processed_prices[middle_idx])
            elif len(processed_prices) == 25:
                # This is a fall back DST day (we have an extra hour)
                log.info(
                    "Detected fall back DST transition for tomorrow - removing extra hour"
                )
                # Remove the duplicate hour
                middle_idx = len(processed_prices) // 2
                processed_prices.pop(middle_idx)

            # Final validation
            if len(processed_prices) != 24:
                log.warning(
                    "Unexpected number of hours for tomorrow: %d, adjusting to 24",
                    len(processed_prices),
                )
                if len(processed_prices) < 24:
                    processed_prices.extend(
                        [processed_prices[-1]] * (24 - len(processed_prices))
                    )
                else:
                    processed_prices = processed_prices[:24]

            return processed_prices

        except (ValueError, AttributeError, KeyError) as e:
            log.warning("Failed to get Nordpool prices for tomorrow: %s", str(e))
            # Return default values as fallback
            return [0.5] * 24

    def get_l1_current(self) -> float:
        """Get the current load for L1."""
        try:
            return float(state.get("sensor.current_l1_gustavsgatan_32a"))
        except NameError:
            return float(state.get("sensor.tibber_pulse_gustavsgatan_32a_current_l1"))

    def get_l2_current(self) -> float:
        """Get the current load for L2."""
        try:
            return float(state.get("sensor.current_l2_gustavsgatan_32a"))
        except NameError:
            return float(state.get("sensor.tibber_pulse_gustavsgatan_32a_current_l2"))

    def get_l3_current(self) -> float:
        """Get the current load for L3."""
        try:
            return float(state.get("sensor.current_l3_gustavsgatan_32a"))
        except NameError:
            return float(state.get("sensor.tibber_pulse_gustavsgatan_32a_current_l3"))

    def get_solcast_forecast(self, day_offset=0, confidence_level="estimate"):
        """Get solar forecast data from Solcast integration."""
        entity_id = "sensor.solcast_pv_forecast_forecast_today"
        if day_offset == 1:
            entity_id = "sensor.solcast_pv_forecast_forecast_tomorrow"

        attributes = state.getattr(entity_id)
        if not attributes:
            logger.warning(
                "No attributes found for %s, using default values", entity_id
            )
            return [0.0] * 24  # Return zeros as fallback

        hourly_data = attributes.get("detailedHourly")
        if not hourly_data:
            logger.warning(
                "No hourly data found in %s, using default values", entity_id
            )
            return [0.0] * 24  # Return zeros as fallback

        hourly_values = [0.0] * 24
        pv_field = f"pv_{confidence_level}"

        for entry in hourly_data:
            # Handle both string and datetime objects for period_start
            period_start = entry["period_start"]
            hour = (
                period_start.hour
                if hasattr(period_start, "hour")
                else int(period_start.split("T")[1].split(":")[0])
            )
            hourly_values[hour] = float(entry[pv_field])

        return hourly_values
