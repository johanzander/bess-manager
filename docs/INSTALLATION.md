# BESS Manager Installation Guide

Complete guide for installing and configuring BESS Battery Manager for Home Assistant.

## Prerequisites

### Home Assistant

- Home Assistant OS, Container, or Supervised

### Inverter (Required — one of the following)

**Growatt MIC/MIN/MOD/MID via Growatt Server (cloud)**

- A Growatt AC-coupled inverter with battery storage
- The [Growatt Server integration](https://www.home-assistant.io/integrations/growatt_server/) installed in Home Assistant
- **⚠️ Token authentication is required.** The integration supports both username/password and token-based auth, but BESS needs the `number.*` and `switch.*` entities and service calls that are only available with token auth. Username/password auth will not expose these, and BESS will not work correctly without them.

**Growatt SPH via Growatt Server (cloud)**

- A Growatt SPH (DC-coupled) inverter with battery storage
- The [Growatt Server integration](https://www.home-assistant.io/integrations/growatt_server/) with token auth

**Growatt MIC/MIN/MOD/MID via solax_modbus (local Modbus)**

- A Growatt AC-coupled inverter with battery storage
- The [homeassistant-solax-modbus](https://github.com/wills106/homeassistant-solax-modbus) HACS integration with the **Growatt plugin** enabled
- Provides local Modbus control — no cloud dependency
- Requires Growatt plugin with TOU time slot entities (entity_id: `select.*_time_1_active`, unique_id suffix: `time_1_enabled`). Slots 4-9 are disabled by default in HA and must be enabled manually.

**SolaX via solax_modbus (local Modbus)**

- A SolaX inverter with battery storage
- The [homeassistant-solax-modbus](https://github.com/wills106/homeassistant-solax-modbus) integration (available via HACS) installed in Home Assistant
- BESS controls the inverter via VPP active-power commands
- Auto-detection uses the HA entity registry (`platform` and `unique_id` fields), which are immutable and unaffected by entity renaming. If you have renamed entity IDs and removed the original suffixes, use the setup wizard to map them manually

For detailed entity requirements per platform, see [docs/INVERTER_PLATFORMS.md](INVERTER_PLATFORMS.md).

### Electricity Price Integration (Required)

One of:

- **Nordpool** integration — for Nordic and European spot price markets
- **Octopus Energy** integration — for UK market (via HACS)

### Solar Forecast (Optional)

BESS works without solar panels or a solar forecast. If you have PV and want solar-aware optimization:

- Only **Solcast** (available via HACS) is supported
- The built-in Home Assistant solar forecast integration is **not supported** — it does not provide hourly predictions for today and tomorrow, which BESS requires

## Step 1: Install the Add-on

1. Open your Home Assistant web interface
2. Go to **Settings → Add-ons** (in the left sidebar, click Settings, then Add-ons)
3. Click the **Add-on Store** button (bottom-right)
4. Click the overflow menu (**⋮**) in the top-right corner, then **Repositories**
5. Paste the repository URL and click Add:
   ```
   https://github.com/johanzander/bess-manager
   ```
6. Close the dialog — **BESS Battery Manager** now appears in the store
7. Click it, then click **Install**

## Step 2: Historical Data (Automatic)

Nothing to set up here. BESS reads historical energy data from **Home Assistant's
built-in recorder** — the same history HA keeps for its own dashboards. On a
restart, or on a fresh install part-way through the day, it backfills today's
actual energy flows from the recorder automatically.

The only requirement is that HA's recorder keeps recent history for the sensors
BESS uses. The default (10 days, all entities) is plenty. If you have a custom
`recorder:` configuration, make sure it does **not** `exclude` your BESS
sensors and keeps at least **2 days** of history (`purge_keep_days: 2` or more).

### Migrating from the InfluxDB add-on

Earlier versions of BESS read history from an InfluxDB instance. That is no
longer used — the recorder covers it. If you set BESS up that way:

- **You usually need to do nothing.** The recorder path takes over on its own.
- Check your `recorder:` config as above — an `exclude:` block that drops the
  BESS sensors, or a very short `purge_keep_days`, is the one thing that leaves
  gaps now.
- The `influxdb` block in the BESS add-on configuration is ignored and can be
  removed. It will stop being a valid option in an update about a month after
  this one; while BESS still sees configured InfluxDB credentials it shows a
  one-time dashboard banner as a reminder.
- Your **InfluxDB database** and the Home Assistant `influxdb:` integration that
  writes to it are unaffected — remove them at your own pace if nothing else
  uses them.

## Step 3: Choose a Home Consumption Forecast

BESS needs a forecast of your home consumption to plan the battery schedule.
This is selected with the `consumption_strategy` setting in the BESS Manager
web interface (**Settings → Home**). Four strategies are available.

**Recommended: `ha_statistics`.** It is the most accurate option that needs no
manual sensor setup — see below.

### Strategy comparison

| Strategy | Accuracy | What you must configure |
|----------|----------|-------------------------|
| **`ha_statistics`** ✅ recommended | High — real home consumption (incl. solar self-use), time-of-day shaped | Nothing beyond selecting it. Needs the inverter's lifetime load-consumption sensor (auto-discovered) and ~7 days of HA history |
| `load_power_7d_avg` | High — 15-min resolution, works without a lifetime load-energy entity | Requires the `local_load_power` sensor and ~7 days of HA recorder history |
| `fixed` | Low — a single flat number, does not adapt | Manually enter a kWh/hour value (`home.default_hourly`) |
| `sensor` (legacy) | Low — grid-import proxy that ignores solar self-consumption, so it under-estimates load on sunny days | Requires a hand-written template sensor in `configuration.yaml` (see below) |

#### `ha_statistics` (recommended)

Builds a 24-hour consumption profile from Home Assistant's built-in Recorder
long-term statistics for the inverter's load-consumption sensor, averaged over
the past 7 days (with outlier trimming to absorb occasional EV/heat-pump
spikes). This reflects **actual** household consumption — including the part
covered by your own solar — and varies by time of day (e.g. higher in the evening,
lower overnight).

To enable it, just set `consumption_strategy` to `ha_statistics` in the web
interface. No template sensor, no `configuration.yaml` edits, no InfluxDB. Until
HA has accumulated enough statistics, BESS temporarily falls back to the fixed
`home.default_hourly` value and tells you so in the UI.

> **Requirement:** the inverter's load-consumption sensor must be set up
> correctly in Home Assistant's **Energy** dashboard (**Settings → Dashboards →
> Energy**), so HA records the long-term statistics this strategy reads. If
> consumption is not configured there, no statistics exist to query and BESS
> stays on the fixed fallback. Allow ~7 days after setup for enough history to
> accumulate.

#### `load_power_7d_avg`

Same idea, but reads the `local_load_power` sensor from Home Assistant's
recorder at 15-minute resolution. Equally accurate, and the only history-based
option on platforms that have no lifetime load-consumption entity for
`ha_statistics` to read (e.g. SolaX Native, Solis). Requires the
`local_load_power` sensor configured and ~7 days of recorder history. (Formerly
`influxdb_7d_avg`; the old id is still accepted in settings.)

#### `fixed`

Uses a single flat kWh/hour value (`home.default_hourly`). Simple fallback for
very predictable homes; does not adapt to actual usage.

#### `sensor` (legacy)

> **Not recommended.** This is the original strategy. It approximates
> consumption from *grid import power* and therefore **does not account for
> solar self-consumption** — on sunny days it under-estimates real consumption.
> It also requires a hand-written template sensor. Prefer `ha_statistics`.
> Note that it produces a **flat** 24-hour profile like `fixed`: BESS reads the
> single current value of the 48h-average sensor and applies it to every period
> in the horizon, so it has no time-of-day shape.

If you still want it, BESS reads a sensor named `*48h_avg*grid_import*`
(auto-discovered by name). Create it in `configuration.yaml`:

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

> **Note:** Replace `rkm0d7n04x_battery_1_charging_w`, `rkm0d7n04x_battery_1_discharging_w`, and `rkm0d7n04x_import_power` with your actual sensor entity IDs from your inverter integration. The filter holds the previous value while the battery is active (>400 W) so the 48h average reflects pure home consumption.

> **Tip — average measured home load instead of grid import.** If you want to
> stay on the `sensor` strategy but avoid the solar blind spot, point the 48h
> statistics average directly at your inverter's home **load power** sensor
> (e.g. `local_load_power`) rather than the grid-import template. That value is
> already true home consumption (solar self-use included) and needs no battery
> filter — drop the `template:` block entirely and set
> `entity_id: sensor.<your_local_load_power>` on the statistics sensor. Keep the
> friendly name containing `48h` and `grid import` so BESS still auto-discovers
> it. This is the cleaner way to do it if you must use `sensor`.

### Adjusting the forecast: Managed Loads and Planned Consumption Changes

The strategy you pick above describes your *normal* consumption. Two optional
settings adjust it — neither is needed for a working install:

- **Managed Loads** (`ha_statistics` only) — name a metered recurring load (in
  practice, an EV charger) and BESS subtracts its history before building the
  profile. Use it when a load you run most days would otherwise be averaged
  into *every* day's forecast.
- **Planned Consumption Changes** — a template sensor that declares what
  deviates from normal on a given day ("the EV needs 40 kWh by 06:00", "away
  all week", "skip the pool pump today"). It is not a fifth strategy; it
  applies on top of whichever one you use, and does nothing until you
  configure it.

The recommended EV setup combines both: exclude the charger under Managed
Loads, then announce each session under Planned Consumption Changes, so the
only EV energy in the plan is the amount you declared. Both are configured in
the web interface (**Settings → Home** and **Settings → Sensors**); see the
[User Guide](USER_GUIDE.md#managed-loads--excluding-a-regular-habit-from-the-baseline)
for the template sensor format and worked examples.

## Step 4: Configure BESS Manager

Battery, pricing, home, and sensor settings are all configured through the **web interface**.
The only add-on configuration setting is `influxdb` (see Step 2).

### 4a: First-Time Setup Wizard

When you open the web interface for the first time, a **Setup Wizard** will launch automatically.
It scans Home Assistant for connected integrations and fills in sensor entity IDs automatically.
Walk through the wizard to:

1. Auto-discover your inverter (Growatt or SolaX), Nordpool, Solcast and other integrations
2. Review and adjust any detected sensor entity IDs
3. Confirm the configuration — BESS applies it immediately without a restart

If you need to re-run the wizard later, click **Auto-Configure** on the **Settings → Sensors** tab.

### 4b: Configure Settings

All settings are available under the **Settings** page in the top navigation. There are five tabs:

- **Integrations** — Inverter platform selection and sensor entity IDs for each integration
- **Electricity Pricing** — Nordpool/Octopus provider, price area, VAT, markup, additional costs, tax reduction
- **Battery** — Capacity, power limits, SOC range, cycle cost
- **Home** — Consumption, currency, fuse size, voltage, phase count, safety margin
- **System** — Demo mode, AI analyst, diagnostics and debug export

The sections below describe the key values you need to fill in.

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

**How the raw spot price is converted to your buy and sell prices:**

```
Buy price  = (raw spot + markup) × VAT multiplier + additional costs
Sell price = raw spot + tax reduction
```

**Note:** The markup is applied *before* VAT (it's ex-VAT), but the additional costs are already VAT-inclusive.

**Explaining each field:**

> **`markup_rate`** — Energy provider's margin/management fee charged per kWh (ex-VAT before VAT is applied).
> Example: Tibber 0.08 (8 öre/kWh), Ellevio ~0.15.

> **`vat_multiplier`** — The VAT tax factor. Set to 1.25 for 25% VAT (Sweden, Norway, Denmark, Finland), 1.20 for 20% (UK, some EU), etc.

> **`additional_costs`** covers fixed per-kWh charges such as grid tariff and energy tax.
> The code adds this value directly to the buy price, so you must configure it as your **final total additional cost per kWh** (VAT included).
>
> **How to calculate `additional_costs` from your E.ON bill (or similar Swedish invoice):**
>
> Your invoice shows charges ex-VAT, then applies 25% VAT to the total. Calculate as follows:
>
> | Component | From your bill | Amount per kWh |
> |-----------|-----------------|---|
> | Grid transfer fee (Elöverföring) | ex-VAT | 0.2584 |
> | Energy tax (Energiskatt) | ex-VAT | 0.3600 |
> | **Subtotal ex-VAT** | | **0.6184** |
> | **VAT 25%** | 25% of 0.6184 | **0.1546** |
> | **Total `additional_costs` (inc. VAT)** | | **0.7730** |
>
> Then configure `additional_costs: 0.77` in your settings (round as needed).
>
> Your grid transfer fee and energy tax amounts vary by network operator and region.
> Find these values on your electricity bill and recalculate as shown above.

> **`tax_reduction`** (labeled as "Export Compensation" in the UI) is the per-kWh payment you receive from the grid operator when selling energy back to the grid.
> The Swedish *skattereduktion* (tax reduction) was removed Jan 1 2026. What remains is **Nätnytta** (grid export benefit).
>
> Check your E.ON or other network operator invoice under "Producent/Självfaktura" (Producer/Self-invoice).
> The section shows what you're paid for exported electricity (typically ex-VAT, no tax on exports).
>
> **Example from E.ON invoice:**
> - Nätnytta (Grid export benefit): -19.88 öre/kWh → set `tax_reduction: 0.1988`
> - This is the per-kWh payment E.ON provides for exporting surplus solar/battery electricity to the grid.

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

**3. Set cycle_cost in GBP** (see notes below).

### ⚠️ Important Configuration Notes

> **CRITICAL:** Set `cycle_cost` in **your local currency** for correct operation.

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

The Min/Max SOC limits you set in **Settings → Battery** are the master values. BESS syncs them to the inverter on startup and the optimizer stays within this range.

- **You configure in Settings → Battery**: Set min/max SOC (e.g. 10–100% = 90% usable capacity)
- **BESS syncs to inverter**: Limits are written to the inverter automatically
- **Optional adjustment**: Use more conservative limits if you want to reduce battery wear (e.g. 15–90% = 75% DoD)

The DoD is already factored into the warranty cycle count, so you don't need to manually adjust the `cycle_cost` calculation based on DoD.

## Step 5: Start the Add-on

1. Start BESS Manager
2. Open the web interface via Ingress (Settings → Add-ons → BESS Manager → Open Web UI)
3. The Setup Wizard launches automatically on first boot — follow it to configure sensors
4. Check add-on logs for any errors if the wizard does not appear

## Troubleshooting

**Problem:** Optimization not working

**Solution:** Verify all required sensors are configured and returning valid data

**Problem:** Missing consumption data

**Solution:** Check your consumption forecast strategy (Step 3). For `ha_statistics`, allow ~7 days for HA to accumulate statistics; for the legacy `sensor` strategy, check the `48h_avg_grid_import` template sensor is working.

**Problem:** Battery charges during expensive hours, discharges during cheap hours

**Solution:** Check `cycle_cost` is in correct currency (see Step 4)

### Troubleshooting InfluxDB (legacy)

> BESS no longer reads InfluxDB — see [Step 2](#step-2-historical-data-automatic). This section
> only applies to older setups still pointing BESS at an InfluxDB instance, and is removed once
> the `influxdb` option is.

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
reach InfluxDB). Replace `<influxdb-host>`, `<db>`, and `<password>` with your values:

```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST "http://<influxdb-host>:8086/api/v2/query" -u "bess:<password>" -H "Content-type: application/vnd.flux" -H "Accept: application/csv" --data 'from(bucket: "<db>/autogen") |> range(start: -1h) |> limit(n: 1)'
```

This uses the same endpoint and query language as BESS, so it is an exact connectivity test.

Expected responses:

- `HTTP 200` — working correctly
- `HTTP 401` — wrong username or password
- `HTTP 403` — Flux query language is not enabled in your InfluxDB configuration

If you get a connection error, replace `homeassistant.local` with the IP address of your Home
Assistant instance (e.g. `192.168.1.100`).

#### Step 3: Verify the bucket name in the BESS config

The most common misconfiguration is the bucket name. In the BESS add-on configuration, it must be:

```yaml
bucket: "homeassistant/autogen"
```

Not `homeassistant`, not `home_assistant` — it must include `/autogen`.

### Check Sensor Health

Go to **Settings → System** in the BESS web interface to verify all sensors are working correctly.
The health tab shows OK / WARNING / ERROR for each integration and lets you export debug data.

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
