import appdaemon.plugins.hass.hassapi as hass
import datetime

class BatteryManager(hass.Hass):

    def initialize(self):
        # Schedule the app to run every 5 minutes
        self.run_every(self.manage_battery, self.datetime(), 5 * 60)
        self.log("BatteryManager initialized")

    def manage_battery(self, kwargs):
        current_hour = datetime.datetime.now().hour
        self.log(f"Current hour: {current_hour}")

        try:
            # Fetch current value from the inverter
            current_battery_soh = self.get_state("sensor.rkm0d7n04x_statement_of_charge_soc")
            self.log(f"Current battery SOH: {current_battery_soh}")

            # Fetch target value for current hour
            target_discharge_stop_soc = self.get_state(f"input_number.discharge_stop_soc_{current_hour}")
            self.log(f"Target discharge stop SOC for hour {current_hour}: {target_discharge_stop_soc}")
            assert 0 <= float(target_discharge_stop_soc) <= 100, "target_discharge_stop_soc must be between 0 and 100"
            
            # Do we want to discharge?    
            if target_discharge_stop_soc < current_battery_soh:
                # Yes
                discharge_power_rate = self.get_state("input_number.default_discharge_power_rate")
                self.log(f"Target discharge power rate for hour {current_hour}: {discharge_power_rate}")
                assert 0 <= float(discharge_power_rate) <= 100, "target_discharge_power_rate must be between 0 and 100"

                self.log("Discharging battery")
                self.call_service("input_number/set_value", entity_id="number.rkm0d7n04x_discharge_stop_soc", value=target_discharge_stop_soc)
                self.call_service("input_number/set_value", entity_id="number.rkm0d7n04x_discharging_power_rate", value=discharge_power_rate)
            else:
                # No
                self.log("Not discharging battery")
                if 6 <= current_hour < 23:
                    self.call_service("input_number/set_value", entity_id="number.rkm0d7n04x_discharging_power_rate", value=1)
                    self.log("Slow discharge, to prevent battery from going to sleep")
                else:
                    self.call_service("input_number/set_value", entity_id="number.rkm0d7n04x_discharging_power_rate", value=discharge_power_rate)
        
        except Exception as e:
            self.log(f"Error in manage_battery: {e}", level="ERROR")