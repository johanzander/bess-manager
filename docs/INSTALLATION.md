# BESS Manager Installation Guide

Complete guide for installing and configuring BESS Battery Manager for Home Assistant.

## Prerequisites

### Home Assistant

- Home Assistant OS, Container, or Supervised

### Growatt Inverter (Required)

- A Growatt inverter with battery storage
  - **MIN inverter**: fully supported
  - **SPH inverter**: experimental support
- The [Growatt Server integration](https://www.home-assistant.io/integrations/growatt_server/) installed in Home Assistant
- **⚠️ Token authentication is required.** The integration supports both username/password and token-based auth, but BESS needs the `number.*` and `switch.*` entities and service calls that are only available with token auth. Username/password auth will not expose these, and BESS will not work correctly without them.

### Electricity Price Integration (Required)

One of:

- **Nordpool** integration — for Nordic and European spot price markets
- **Octopus Energy** integration — for UK market (via HACS)

### Solar Forecast (Optional)

BESS works without solar panels or a solar forecast. If you have PV and want solar-aware optimization:

- Only **Solcast** (available via HACS) is supported
- The built-in Home Assistant solar forecast integration is **not supported** — it does not provide hourly predictions for today and tomorrow, which BESS requires

## Step 1: Install the Add-on

1. Add the repository to Home Assistant:
   - Go to Settings → Add-ons → Add-on Store
   - Click menu (⋮) → Repositories
   - Add: `https://github.com/johanzander/bess-manager`

2. Install BESS Manager:
   - Find "BESS Battery Manager" in the add-on store
   - Click "Install"

## Step 2: Set Up InfluxDB (Optional but Recommended)

BESS uses InfluxDB to store and retrieve historical energy sensor data. Without it, the system loses
all historical context when restarted and cannot backfill the energy balance chart after startup.
It is not required for optimization to work, but strongly recommended.

### 2a: Install InfluxDB

1. Go to **Settings → Add-ons → Add-on Store**
2. Search for **InfluxDB** and install it
3. Start the add-on and open the web UI

### 2b: Create an InfluxDB Write User for Home Assistant

Home Assistant needs its own user with **WRITE** access to push sensor data into InfluxDB.

1. Open the **InfluxDB web UI** (from the add-on page, click **Open Web UI**)
2. Go to **Settings → Users**
3. Create a user, for example `homeassistant`, with a password
4. Grant it **WRITE** access to the `homeassistant` database

> **Note:** This is a separate user from the BESS read-only user created in step 2d below.
> HA writes data; BESS reads it. Keep them separate so BESS cannot accidentally modify data.

### 2c: Configure Home Assistant to Write to InfluxDB

Add the following to your `configuration.yaml`:

```yaml
influxdb:
  host: localhost
  port: 8086
  database: !secret influxdb_database
  username: !secret influxdb_username
  password: !secret influxdb_password
  max_retries: 3
  include:
    domains:
      - sensor
```

And add the corresponding entries to `secrets.yaml`:

```yaml
influxdb_database: homeassistant
influxdb_username: homeassistant
influxdb_password: your_ha_writer_password
```

After restarting Home Assistant, sensor states will start being written to InfluxDB.

> **Note:** In the InfluxDB UI under **Configuration**, you should see the connection listed as
> `http://localhost:8086` — **CONNECTED**. The database `homeassistant` appears under **Explore**.

### 2d: Create a Read-Only InfluxDB User for BESS

BESS only needs read access to InfluxDB. Create a dedicated user:

1. Open the **InfluxDB web UI** (from the add-on page, click **Open Web UI**)
2. Go to **Settings → Users** (InfluxDB 1.x admin UI at `http://homeassistant.local:8086`)
3. Create a new user, for example `bess`, with a password
4. Grant it **READ** access to the `homeassistant` database

### 2e: Configure BESS to Connect to InfluxDB

Add the following to your BESS add-on configuration:

```yaml
influxdb:
  url: "http://homeassistant.local:8086/api/v2/query"
  bucket: "homeassistant/autogen"
  username: "bess"
  password: "your_password_here"
```

> **⚠️ The bucket name is not just the database name.**
> InfluxDB 1.x organises data as `<database>/<retention_policy>`. The default retention policy is
> `autogen`, so the bucket must be set to `homeassistant/autogen` — not just `homeassistant`.
> This is the most common misconfiguration.

> **URL note:** Use `http://homeassistant.local:8086/api/v2/query` if BESS runs on the same machine
> as Home Assistant. If InfluxDB is on a separate host, replace the hostname with the IP address,
> e.g. `http://192.168.1.100:8086/api/v2/query`.

### 2f: Verify the Connection

After starting BESS, go to the **System Health** page in the web interface. The
**Historical Data Access** component should show **OK**. If it shows a warning like
*"returned no valid data"*, the most likely cause is an incorrect bucket name — double-check
that you have used `homeassistant/autogen` and not just `homeassistant`.

## Step 3: Create Home Consumption Sensor

BESS needs a consumption sensor. How to predict home energy consumption is outside the scope of this AddOn.
Here is an example of a template sensor that predicts the future consumption based on last 48h consumption average. This approach is sufficient for good optimization perfomrance.

### Example sensor

Add to `configuration.yaml`:

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

## Step 4: Configure BESS Manager

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
  currency: "EUR"                   # Your currency (SEK, EUR, NOK)
  max_fuse_current: 25              # Maximum fuse current (A)
  voltage: 230                      # Line voltage (V)
  safety_margin_factor: 0.95        # Safety margin (95%)

electricity_price:
  area: "SE4"                       # Nordpool area (or "UK" for Octopus)
  markup_rate: 0.08                 # Markup (per kWh, in your currency)
  vat_multiplier: 1.25              # VAT (1.25 = 25%)
  additional_costs: 1.03            # Additional costs (per kWh)
  tax_reduction: 0.0                # Tax reduction for sold energy (per kWh)

# Energy provider configuration
energy_provider:
  provider: "nordpool"              # "nordpool", "nordpool_official", or "octopus"
  nordpool:
    today_entity: "sensor.nordpool_kwh_your_area"
    tomorrow_entity: "sensor.nordpool_kwh_your_area"
  nordpool_official:
    config_entry_id: ""             # Required when provider is "nordpool_official"
  octopus:                          # Only needed when provider is "octopus"
    import_today_entity: ""         # See "Octopus Energy Setup" section below
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

  # Consumption forecast (required)
  48h_avg_grid_import: "sensor.48h_average_grid_import_power"  # From Step 3

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

  # Optional: Discharge inhibit — binary sensor that prevents BESS discharge when active.
  # Leave empty (discharge_inhibit: "") to disable this feature.
  # Discharge resumes automatically within ~1 minute once the sensor turns off.
  #
  # Ready-made binary sensors (created automatically by their HA integrations):
  #   Tibber: binary_sensor.<id>_charging   (e.g. binary_sensor.ex90_charging)
  #   Zaptec: binary_sensor.<id>_charging (e.g. binary_sensor.zap123456_charging)
  #
  # If neither integration provides a suitable sensor, create a Helper → Toggle in HA and
  # automate it via your own rules (e.g. turn on when charger current > 0 A).
  #
  # discharge_inhibit: ""                              # disabled
  # discharge_inhibit: "binary_sensor.ex90_charging"  # enabled

  # Optional: Lifetime energy statistics
  # lifetime_solar_energy: "sensor.your_lifetime_solar_energy"
  # lifetime_load_consumption: "sensor.your_lifetime_load_consumption"
  # lifetime_import_from_grid: "sensor.your_lifetime_import_from_grid"
  # lifetime_export_to_grid: "sensor.your_lifetime_export_to_grid"
  # ev_energy_meter: "sensor.your_ev_energy_meter"
```

### Nordpool Electricity Price Setup

Nordpool prices are **VAT-exclusive** spot prices. The buy price is calculated as:

```
buy_price = (spot_price + markup_rate) × vat_multiplier + additional_costs
```

Set `vat_multiplier` to your country's VAT rate and `additional_costs` to your fixed per-kWh
charges (grid fee, energy tax, etc.) already including VAT:

| Country | VAT | `vat_multiplier` |
|---------|-----|-----------------|
| Sweden, Norway, Denmark, Finland | 25% | `1.25` |
| Netherlands | 21% | `1.21` |
| Germany | 19% | `1.19` |

**Example for Sweden:**

```yaml
electricity_price:
  area: "SE3"
  markup_rate: 0.08        # Supplier markup in SEK/kWh (ex-VAT) — e.g. Tibber charges 8 öre/kWh
  vat_multiplier: 1.25     # 25% VAT applied to spot + markup
  additional_costs: 1.03   # Grid fee + energy tax in SEK/kWh (VAT-inclusive total)
  tax_reduction: 0.0       # Swedish skattereduktion removed as of Jan 1 2026
```

> **`additional_costs`** covers fixed per-kWh charges such as grid tariff and energy tax.
> These are added **after** VAT is applied to the spot price, so specify them as the
> final consumer amount (VAT already included where applicable).
>
> **Typical Swedish breakdown (SEK/kWh):**
>
> | Component | Swedish term | Amount |
> |-----------|-------------|--------|
> | Grid transfer fee (ex. VAT) | Överföringsavgift | ~0.45 |
> | VAT on grid fee (25%) | Moms på nätavgift | ~0.11 |
> | Energy tax | Energiskatt | ~0.46 |
> | **Total `additional_costs`** | | **~1.02** |
>
> The grid transfer fee (överföringsavgift) varies by network operator and region.
> Check your electricity bill for the exact amounts.

> **`tax_reduction`** is the per-kWh credit you receive when selling energy back to the grid.
> The Swedish *skattereduktion* was removed as of Jan 1 2026, so Swedish users should set this to `0.0`.
> Users in other markets should check whether their tariff includes a sell-back credit.

### Octopus Energy Setup

If you're using Octopus Energy (UK), set `provider: "octopus"` under `energy_provider:` and configure the entity IDs.

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

## Step 5: Start the Add-on

1. Save configuration
2. Start BESS Manager
3. Check logs for any errors
4. Access web interface via Ingress or `http://homeassistant.local:8080`

## Troubleshooting

**Problem:** Optimization not working

**Solution:** Verify all required sensors are configured and returning valid data

**Problem:** Missing consumption data

**Solution:** Check 48h average sensor is working (Step 3)

**Problem:** Battery charges during expensive hours, discharges during cheap hours

**Solution:** Check `cycle_cost` is in correct currency (see Step 4)

### Troubleshooting InfluxDB

If the **Historical Data Access** health check shows WARNING or the energy balance chart is empty,
follow these steps in order.

#### Step 1: Verify HA is writing data to InfluxDB

Open the **InfluxDB web UI** and go to **Explore**. Navigate as follows:

1. Set the database to **homeassistant/autogen**
2. In the **Measurement** dropdown you should see entries like `%`, `W`, `kWh` (sensor units)
3. Select one, then pick a **Field** — you should see sensor names and recent values

If you can browse sensors here, HA is writing correctly and the data is ready for BESS to read.

Alternatively, check the **Home Assistant logs** for any InfluxDB write errors:

1. Go to **Settings → System → Logs**
2. Search for `influxdb`
3. Errors here mean HA cannot reach InfluxDB or the writer credentials are wrong

If no data appears in InfluxDB at all, check:

- The `influxdb:` block is present in `configuration.yaml` and HA has been restarted
- The writer username and password in `secrets.yaml` are correct
- The writer user has **WRITE** access to the `homeassistant` database

#### Step 2: Verify the BESS user can read data

Run the following `curl` command from the machine running Home Assistant (or any machine that can
reach InfluxDB). Replace `<password>` with the BESS user's password:

```bash
curl -G "http://homeassistant.local:8086/query" \
  --data-urlencode "db=homeassistant" \
  --data-urlencode "q=SELECT last(value) FROM /sensor.*/ LIMIT 5" \
  -u "bess:<password>"
```

A working response looks like:

```json
{"results":[{"statement_id":0,"series":[{"name":"sensor.growatt_...","columns":["time","last"],...}]}]}
```

If you get `{"results":[{"statement_id":0}]}` (empty series), no sensor data exists yet — wait
a few minutes for HA to write some, then retry.

If you get a `401 Unauthorized` error, the username or password is wrong, or the user does not
have read access to the `homeassistant` database.

If you get a connection error, replace `homeassistant.local` with the IP address of your Home
Assistant instance (e.g. `192.168.1.100`).

#### Step 3: Verify the bucket name in the BESS config

The most common misconfiguration is the bucket name. In the BESS add-on configuration, it must be:

```yaml
bucket: "homeassistant/autogen"
```

Not `homeassistant`, not `home_assistant` — it must include `/autogen`.

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
