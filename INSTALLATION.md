# BESS Manager Installation Guide

Complete guide for installing and configuring BESS Battery Manager for Home Assistant.

## Prerequisites

- Home Assistant OS, Container, or Supervised
- Growatt battery system with Home Assistant integration
- Electricity price integration: **Nordpool** (Nordic markets) or **Octopus Energy** (UK market)

## Step 1: Install the Add-on

### Method 1: From Repository (Recommended)

1. Add the repository to Home Assistant:
   - Go to Settings → Add-ons → Add-on Store
   - Click menu (⋮) → Repositories
   - Add: `https://github.com/johanzander/bess-manager`

2. Install BESS Manager:
   - Find "BESS Battery Manager" in the add-on store
   - Click "Install"

### Method 2: Local Installation

1. Build the add-on:

   ```bash
   git clone https://github.com/johanzander/bess-manager.git
   cd bess-manager
   chmod +x package-addon.sh
   ./package-addon.sh
   ```

2. Transfer files to Home Assistant:
   - Copy `build/bess_manager` contents to `/addons/bess_manager`
   - Via SSH, Samba, or File Editor add-on

3. Install:
   - Configuration → Add-ons → Reload
   - Find "BESS Battery Manager" in Local add-ons
   - Click "Install"

## Step 2: Choose a Consumption Strategy

BESS needs a consumption forecast to optimize battery scheduling. Four strategies are available, configured via `consumption_strategy` in the `home` section. Start with the simplest approach and graduate to smarter options as data accumulates.

### Strategy Overview

| Strategy | Description | Requirements |
|---|---|---|
| `sensor` | Reads a 48h-average HA sensor, returns a flat forecast | HA template sensor (see below) |
| `fixed` | Uses the `home.consumption` config value as a flat forecast | Nothing extra |
| `influxdb_profile` | Queries InfluxDB for a 7-day weekly average profile with daily shape | InfluxDB with sensor history |
| `ml_prediction` | Runs an ML model with weather forecast for a shaped prediction | Trained model + HA weather entity |

Set your chosen strategy in `config.yaml`:

```yaml
home:
  consumption: 3.5
  consumption_strategy: "sensor"   # "sensor" | "fixed" | "influxdb_profile" | "ml_prediction"
```

### Strategy: `sensor` (default)

This is the default and works out of the box for existing users. It reads a 48h-average sensor from Home Assistant and returns a flat consumption value for all 96 quarter-hourly periods.

Create a template sensor in `configuration.yaml`:

```yaml
template:
  - sensor:
      - name: "Filtered Grid Import Power"
        unique_id: filtered_grid_import_power
        unit_of_measurement: "W"
        state: >
          {% if states('sensor.rkm0d7n04x_battery_1_charging_w') | float < 400 and
                states('sensor.rkm0d7n04x_battery_1_discharging_w') | float < 400 %}
            {{ states('sensor.rkm0d7n04x_import_power') | float }}
          {% else %}
            {{ states('sensor.filtered_grid_import_power') | float(0) }}
          {% endif %}

sensor:
  - platform: statistics
    name: "48h Average Grid Import Power"
    unique_id: grid_import_power_48h_avg
    entity_id: sensor.filtered_grid_import_power
    state_characteristic: mean
    max_age:
      hours: 48
```

> **Note:** Replace `rkm0d7n04x_battery_1_charging_w`, `rkm0d7n04x_battery_1_discharging_w`, and `rkm0d7n04x_import_power` with your actual sensor entity IDs from your Growatt integration.

**Why filter?** When battery is active (>400W), the sensor holds its previous value instead of updating. This ensures the 48h average only includes periods of pure home consumption, excluding battery operations.

**EV charging:** Exclude if managed separately. Include if you want BESS to optimize around it.

### Strategy: `fixed`

The simplest strategy. Uses the `home.consumption` value from config as a flat forecast. No sensors or integrations required.

```yaml
home:
  consumption: 3.5                 # kWh per hour — used as the fixed forecast value
  consumption_strategy: "fixed"
```

Every 15-minute period gets `consumption / 4` (e.g., 3.5 kWh/h becomes 0.875 kWh per period). Useful when you have no consumption sensor set up or want a stable baseline.

### Strategy: `influxdb_profile`

Queries InfluxDB for the past 7 days of your `local_load_power` sensor and computes a weekly average profile. Unlike `sensor` and `fixed`, this produces a **shaped** 96-value forecast that reflects your actual daily usage pattern (low at night, peaks during morning/evening).

**Requirements:**

- InfluxDB configured in the `influxdb` section of `config.yaml`
- The `local_load_power` sensor configured in the `sensors` section

```yaml
home:
  consumption_strategy: "influxdb_profile"

influxdb:
  url: "http://homeassistant.local:8086/api/v2/query"
  bucket: "home_assistant/autogen"
  username: "your_db_username"
  password: "your_db_password"

sensors:
  local_load_power: "sensor.your_home_consumption"
```

### Strategy: `ml_prediction`

Uses a trained XGBoost ML model to generate weather-aware consumption predictions. This produces the most accurate shaped forecast by combining historical patterns with weather forecast data (temperature, cloud coverage, wind speed).

**Requirements:**

- A trained ML model (see [ML README](ml/README.md) for training instructions)
- Weather forecast entity in Home Assistant
- InfluxDB with historical sensor data (for training and history context)

```yaml
home:
  consumption_strategy: "ml_prediction"
```

The ML model is configured separately in `ml_config.yaml`. See the [ML Energy Consumption Predictor](ml/README.md) documentation for setup and training.

### Which Strategy Should I Choose?

- **New installation, no InfluxDB**: Start with `fixed` or `sensor`
- **Have InfluxDB with 1+ week of history**: Use `influxdb_profile` for a shaped profile with no ML setup
- **Have InfluxDB with 30+ days of history**: Use `ml_prediction` for the best accuracy
- **Want the simplest setup**: Use `fixed` with a reasonable consumption estimate

## Step 3: Configure BESS Manager

Edit the add-on configuration:

```yaml
battery:
  total_capacity: 30.0              # Battery capacity in kWh
  max_charge_discharge_power: 15.0  # Max power in kW
  cycle_cost: 0.08                  # Battery wear cost per kWh charged (excl. VAT)
                                    # Use your local currency
                                    # Typical range: EUR: 0.05-0.09, SEK: 0.50-0.90, NOK: 0.45-0.85
                                    # Start with calculated value (~0.08 EUR) and adjust
  min_action_profit_threshold: 1.5  # Minimum profit threshold (in your currency)
                                    # The algorithm will NOT charge/discharge the battery
                                    # if the expected profit is below this value
                                    # Prevents unnecessary battery cycles for small gains
                                    # Recommended: 1.0-2.0 for SEK/NOK, 0.10-0.20 for EUR

home:
  consumption: 3.5                  # Default hourly consumption (kWh)
  consumption_strategy: "sensor"    # How to forecast consumption (see below)
  currency: "EUR"                   # Your currency (SEK, EUR, NOK)
  max_fuse_current: 25              # Maximum fuse current (A)
  voltage: 230                      # Line voltage (V)
  safety_margin_factor: 0.95        # Safety margin (95%)

electricity_price:
  area: "SE4"                       # Nordpool area (or "UK" for Octopus)
  markup_rate: 0.08                 # Markup (per kWh, in your currency)
  vat_multiplier: 1.25              # VAT (1.25 = 25%)
  additional_costs: 1.03            # Additional costs (per kWh)
  tax_reduction: 0.6518             # Tax reduction for sold energy (per kWh)

# Price provider selection (choose one)
nordpool:
  price_provider: "nordpool"        # "nordpool", "nordpool_official", or "octopus"
  use_official_integration: false   # Set true for official HA Nordpool integration
  config_entry_id: ""               # Required when use_official_integration is true

# Octopus Energy configuration (only needed when price_provider is "octopus")
# See "Octopus Energy Setup" section below for details
octopus:
  import_today_entity: ""
  import_tomorrow_entity: ""
  export_today_entity: ""
  export_tomorrow_entity: ""

sensors:
  # Battery sensors (required)
  battery_soc: "sensor.your_battery_soc"
  battery_charge_stop_soc: "number.your_battery_charge_stop_soc"
  battery_discharge_stop_soc: "number.your_battery_discharge_stop_soc"
  battery_charge_power: "sensor.your_battery_charge_w"
  battery_discharge_power: "sensor.your_battery_discharge_w"
  battery_charging_power_rate: "number.your_charge_power_rate"
  battery_discharging_power_rate: "number.your_discharge_power_rate"
  grid_charge: "switch.your_grid_charge_switch"

  # Power sensors (required)
  pv_power: "sensor.your_solar_power"
  local_load_power: "sensor.your_home_consumption"
  import_power: "sensor.your_grid_import"
  export_power: "sensor.your_grid_export"

  # Consumption forecast (required for "sensor" strategy, see Step 2)
  48h_avg_grid_import: "sensor.48h_average_grid_import_power"

  # Price sensors (required for Nordpool, not needed for Octopus)
  nordpool_kwh_today: "sensor.nordpool_kwh_your_area"
  nordpool_kwh_tomorrow: "sensor.nordpool_kwh_your_area"

  # Solar forecast (required)
  solar_forecast_today: "sensor.solcast_pv_forecast_forecast_today"

  # Optional: Advanced power monitoring
  # output_power: "sensor.your_output_power"
  # self_power: "sensor.your_self_power"
  # system_power: "sensor.your_system_power"

  # Optional: Grid current monitoring (for multi-phase systems)
  # current_l1: "sensor.your_current_l1"
  # current_l2: "sensor.your_current_l2"
  # current_l3: "sensor.your_current_l3"

  # Optional: Lifetime energy statistics
  # lifetime_solar_energy: "sensor.your_lifetime_solar_energy"
  # lifetime_load_consumption: "sensor.your_lifetime_load_consumption"
  # lifetime_import_from_grid: "sensor.your_lifetime_import_from_grid"
  # lifetime_export_to_grid: "sensor.your_lifetime_export_to_grid"
  # ev_energy_meter: "sensor.your_ev_energy_meter"
```

### Octopus Energy Setup

If you're using Octopus Energy (UK), set `price_provider: "octopus"` and configure the entity IDs.

**1. Find your entity IDs** in Developer Tools > States, search for `octopus_energy_electricity`:

```yaml
octopus:
  import_today_entity: "event.octopus_energy_electricity_<MPAN>_<SERIAL>_current_day_rates"
  import_tomorrow_entity: "event.octopus_energy_electricity_<MPAN>_<SERIAL>_next_day_rates"
  export_today_entity: "event.octopus_energy_electricity_<MPAN>_<SERIAL>_export_current_day_rates"
  export_tomorrow_entity: "event.octopus_energy_electricity_<MPAN>_<SERIAL>_export_next_day_rates"
```

**2. Adjust electricity_price settings** - Octopus prices are already VAT-inclusive in GBP/kWh:

```yaml
home:
  currency: "GBP"

electricity_price:
  area: "UK"
  markup_rate: 0.0
  vat_multiplier: 1.0
  additional_costs: 0.0
  tax_reduction: 0.0           # Adjust if you receive SEG payments
```

**3. Set cycle_cost and min_action_profit_threshold in GBP** (see notes below).

### ⚠️ Important Configuration Notes

> **CRITICAL:** Set `cycle_cost` and `min_action_profit_threshold` in **your local currency** for correct operation.

**Understanding `cycle_cost`:**

This represents the battery wear/degradation cost **per kWh charged** (excluding VAT). Every time the battery charges 1 kWh, this cost is added to account for battery degradation.

- **Purpose:** Accounts for battery degradation in optimization calculations
- **Impact:** Higher values = more conservative battery usage (battery used less frequently)
- **Typical range:** 0.05-0.09 EUR/kWh (0.50-0.90 SEK/kWh)

**How to calculate your cycle_cost:**

The formula is simple: **Battery Cost ÷ Total Lifetime Throughput = Cost per kWh**

**Example with Growatt batteries (30 kWh system, EUR):**

| Battery Model | Warranty Cycles | DoD | Throughput | Battery Cost | Calculated cycle_cost |
|--------------|----------------|-----|------------|--------------|---------------------|
| **ARK LV** | 6,000+ | 90% | 180,000 kWh | 15,000 EUR | **0.083 EUR/kWh** |
| **APX** | 6,000+ | 90% | 180,000 kWh | 15,000 EUR | **0.083 EUR/kWh** |

**Calculation:** 6,000 cycles × 30 kWh = 180,000 kWh total throughput → 15,000 EUR ÷ 180,000 kWh = 0.083 EUR/kWh

**Choosing your cycle_cost value:**

The calculated value (0.083 EUR/kWh) is a good starting point, but you may want to adjust based on your preferences:

- **Conservative (0.07-0.09 EUR):** Use calculated warranty value or slightly lower
  - Accounts for full battery replacement cost
  - Suitable if you want to preserve battery life
  - Battery cycled only when clearly profitable

- **Moderate (0.05-0.07 EUR):** Assumes battery exceeds warranty
  - Modern LFP batteries often achieve 8,000+ cycles
  - Accounts for residual battery value
  - Balanced approach for most users

- **Aggressive (0.04-0.05 EUR):** Maximum utilization
  - Assumes best-case battery longevity
  - Maximum system ROI but more battery wear
  - Only if you're confident in long battery life

**About Depth of Discharge (DoD):**

BESS reads your SOC limits from the Growatt inverter but **does NOT modify them**. You configure these limits directly on your inverter (default: 10% min, 100% max = 90% DoD).

- **You configure on inverter**: Set min/max SOC limits (e.g., 10-100% = 90% usable capacity)
- **BESS reads and respects**: Optimization works within your configured SOC range
- **Optional adjustment**: Set more conservative limits on inverter if desired (e.g., 20-90% = 70% DoD)

The DoD is already factored into the warranty cycle count, so you don't need to manually adjust the `cycle_cost` calculation based on DoD.

**Understanding `min_action_profit_threshold`:**

This setting controls when the battery should be used. The optimization algorithm will **NOT** charge or discharge the battery if the expected profit is below this threshold.

- **Purpose:** Prevents unnecessary battery wear for small gains
- **Impact:** Higher values = fewer but more profitable battery actions
- **Recommended values:**
  - 0.10-0.20 EUR
- **Too low:** Battery cycles frequently for minimal benefit, increases wear
- **Too high:** Battery rarely used, missing optimization opportunities

## Step 4: Start the Add-on

1. Save configuration
2. Start BESS Manager
3. Check logs for any errors
4. Access web interface via Ingress or `http://homeassistant.local:8080`

## Troubleshooting

**Problem:** Optimization not working

**Solution:** Verify all required sensors are configured and returning valid data

**Problem:** Missing consumption data

**Solution:** Check your `consumption_strategy` setting and its requirements (Step 2). For `sensor`, verify the 48h average sensor is returning data. For `influxdb_profile`, check InfluxDB connectivity. For `ml_prediction`, ensure the model is trained.

**Problem:** Battery charges during expensive hours, discharges during cheap hours

**Solution:** Check `cycle_cost` is in correct currency (see Step 3)

### Check Sensor Health

Go to System Health page in BESS web interface to verify all sensors are working.

### View Add-on Logs

For troubleshooting, check the add-on logs:

1. Go to **Settings** → **Add-ons** → **BESS Manager**
2. Click on the **Log** tab
3. Review logs for errors or warnings

Logs provide detailed information about sensor data, optimization decisions, and system operations.

### Reporting Issues

When reporting issues on GitHub:

1. Check the add-on logs (see above)
2. Include relevant log excerpts showing the error
3. Provide your configuration (sensors, battery specs, price settings)
4. Describe expected vs actual behavior

Report issues at: <https://github.com/johanzander/bess-manager/issues>

## Next Steps

- Review [User Guide](USER_GUIDE.md) to understand the interface
