# BESS Manager User Guide

Welcome to the BESS Manager! This guide will help you understand the interface, interpret optimization results, and get the most out of your battery storage system.

## Getting Started

Once installed and configured, access your BESS Manager dashboard through:

- **Home Assistant**: Add-ons → BESS Manager → Open Web UI
- **Direct URL**: `http://your-home-assistant:8080` (if configured for external access)

## Dashboard Overview

### Main Dashboard

The main dashboard provides a real-time overview of your energy system:

#### System Status Card

- **Current SOC**: Battery charge percentage and energy (kWh)
- **Power Flows**: Real-time power in/out of battery, solar, and grid
- **System Health**: Green/Yellow/Red indicators for all components
- **Active Strategy**: Current optimization strategy (Grid Charging, Solar Storage, etc.)

#### Today's Energy Flows

- **Solar Production**: Total solar energy generated today
- **Home Consumption**: Energy consumed by your home
- **Battery Activity**: Energy charged/discharged
- **Grid Interaction**: Energy imported/exported
- **Savings**: Estimated cost savings vs. no optimization

### Understanding the Charts

#### 1. Energy Flow Chart (Sankey Diagram)

This beautiful flowing chart shows how energy moves through your system:

- **🌞 Solar → Home**: Direct solar consumption (best case)
- **🌞 Solar → Battery**: Solar energy stored for later
- **🌞 Solar → Grid**: Excess solar sold to grid
- **🔋 Battery → Home**: Stored energy powering your home
- **🔋 Battery → Grid**: Stored energy sold during peak prices
- **⚡ Grid → Home**: Direct grid consumption
- **⚡ Grid → Battery**: Grid energy stored during cheap periods

**Tip**: Thicker flows = more energy. Green flows = good (saving money), red flows = expensive.

#### 2. Battery Level Chart

Shows battery charge level throughout the day with strategic context:

- **Purple periods**: Grid charging (storing cheap electricity)
- **Yellow periods**: Solar storage (storing free solar energy)
- **Blue periods**: Load support (using battery to power home)
- **Green periods**: Export arbitrage (selling stored energy for profit)
- **Gray periods**: Idle (no significant battery activity)

**Reading the strategy**:

- **GRID_CHARGING**: Buying cheap electricity to store
- **SOLAR_STORAGE**: Storing excess solar production
- **LOAD_SUPPORT**: Using battery to power your home
- **EXPORT_ARBITRAGE**: Selling stored energy at high prices

#### 3. Detailed Savings Analysis

Comprehensive breakdown of your savings:

- **Grid-Only Cost**: What you would pay without optimization
- **Optimized Cost**: Actual cost with BESS Manager
- **Total Savings**: Money saved (can be negative during investment periods)
- **ROI Tracking**: Progress toward return on investment

### Detailed System Status

The system status card provides key metrics and health information:

- **Battery SOC**: Current charge level (percentage and kWh)
- **Real-time Power**: Current power flows (solar, battery, grid, consumption)
- **System Health**: Component status indicators (sensors, integrations)
- **Today's Totals**: Energy flows and estimated savings for today
- **Strategic Intent**: Current optimization strategy being executed

## Understanding Optimization Strategies

### Strategic Intents Explained

#### 🔋 GRID_CHARGING

- **What**: Charging battery from grid during low-price periods
- **Why**: Store cheap energy to use/sell later
- **When**: Typically night hours with low electricity prices
- **Indicator**: Battery charging, grid import high

#### ☀️ SOLAR_STORAGE

- **What**: Charging battery with excess solar production
- **Why**: Store free solar energy for evening/night use
- **When**: Sunny midday hours with solar surplus
- **Indicator**: Battery charging, minimal grid activity

#### 🏠 LOAD_SUPPORT

- **What**: Using battery to power home consumption
- **Why**: Avoid purchasing expensive grid electricity
- **When**: Evening hours with high prices and home consumption
- **Indicator**: Battery discharging, minimal grid import

#### 💰 EXPORT_ARBITRAGE

- **What**: Selling stored energy to grid during peak prices
- **Why**: Maximize revenue from stored energy
- **When**: Peak price hours when selling is more profitable
- **Indicator**: Battery discharging, high grid export

#### 😴 IDLE

- **What**: Minimal battery activity
- **Why**: No profitable charging/discharging opportunity
- **When**: Price differences too small to justify battery wear
- **Indicator**: Low battery activity, direct solar consumption

## Monitoring Performance

### Health Indicators

- **🟢 Green**: System operating normally
- **🟡 Yellow**: Minor issues or suboptimal conditions
- **🔴 Red**: Attention required (sensor offline, communication issues)

### Key Metrics to Watch

#### Daily Performance

- **Total Savings**: Daily cost reduction
- **Energy Efficiency**: How much energy was optimized vs. total consumption
- **Battery Utilization**: Percentage of battery capacity used effectively

#### Weekly/Monthly Trends

- **Savings Rate**: Percentage of electricity costs saved
- **ROI Progress**: Time to recover optimization system investment
- **Seasonal Variations**: How performance changes with weather patterns

## Troubleshooting Common Issues

### View Logs for Troubleshooting

When reporting issues or debugging problems, check the add-on logs for detailed information:

1. Go to **Home Assistant** → **Settings** → **Add-ons** → **BESS Manager**
2. Click on the **Log** tab
3. Review the logs for errors or warnings

The logs show:

- Sensor data collection and validation
- Optimization algorithm decisions and reasoning
- Schedule creation and inverter communication
- Price data fetching and processing
- Component health checks and errors

**Tip**: Use the **Refresh** button to see the latest log entries. For historical logs, you can use the Home Assistant system log viewer.

### "No optimization happening"

**Symptoms**: Battery stays at same level, no strategic intents
**Causes**:

- Price differences too small to justify battery wear
- Battery already at optimal level
- System in learning mode (first few days)

**Solutions**:

- Check electricity price integration is working (Nordpool or Octopus Energy)
- Verify price spread is significant enough to justify battery wear
- Wait for price volatility periods

### "Savings are negative"

**Symptoms**: Dashboard shows negative savings
**Causes**:

- System is investing in battery charge for future savings
- Battery wear costs temporarily exceed immediate benefits
- Learning period with suboptimal decisions

**Solutions**:

- Look at weekly/monthly totals instead of daily
- Check if system is building charge for upcoming peak prices
- Verify battery wear cost settings are reasonable

### "Energy flows don't balance"

**Symptoms**: Energy in ≠ energy out in charts
**Causes**:

- Sensor timing differences
- InfluxDB data gaps
- Battery efficiency losses

**Solutions**:

- Check all sensors are reporting correctly
- Verify InfluxDB integration is working
- Small imbalances (<5%) are normal due to efficiency losses

### "Battery not following schedule"

**Symptoms**: Battery behavior doesn't match predicted schedule
**Causes**:

- Home consumption higher/lower than predicted
- Solar production different than forecast
- Grid power limitations
- Inverter safety overrides

**Solutions**:

- Check if actual consumption matches predictions
- Verify solar forecast accuracy
- Review inverter settings and error logs
- System will auto-adapt within 1-2 hours

## Optimizing Your Settings

### Battery Settings

- **Total Capacity**: Match your actual battery capacity exactly
- **Min SOC**: Set safety margin (10-20% recommended)
- **Cycle Cost**: Balance between battery wear and optimization aggressiveness

### Electricity Price Settings

BESS needs hourly spot prices to decide when to charge and discharge. Three price providers are supported — pick the one that matches the integration you have installed in Home Assistant.

#### Provider: Nord Pool (official HA integration)

Recommended for most European users. This is the official Nord Pool integration built into Home Assistant (available since HA 2024.10).

- **Prerequisites**: Add Nord Pool under Settings → Devices & Services → Add Integration → Nord Pool. Configure your market area (e.g. SE4, NO1, DK1, FI) and currency there.
- **How it works**: BESS calls the `nordpool.get_prices_for_date` service using the Config Entry ID to fetch today's and tomorrow's hourly spot prices.
- **Config Entry ID**: A unique identifier for your Nord Pool integration instance. Auto-detected by Auto-Configure. You can also find it in the HA URL when viewing the integration (the long hex string).
- **Area & Currency**: Determined by the integration's own configuration and shown read-only in BESS. These are not configurable in BESS — change them in the HA Nord Pool integration settings if needed.

#### Provider: Nord Pool (HACS custom sensor)

For users with the Nord Pool HACS custom integration (installed from [github.com/custom-components/nordpool](https://github.com/custom-components/nordpool)).

- **Prerequisites**: Nord Pool installed via HACS. The integration creates a single sensor entity whose name encodes the area and currency, e.g. `sensor.nordpool_kwh_se4_sek_3`.
- **How it works**: BESS reads the `raw_today` and `raw_tomorrow` attributes from your Nord Pool sensor to get hourly spot prices. Both today's and tomorrow's prices live on the same sensor entity.
- **Sensor**: The entity ID of your Nord Pool sensor. Auto-detected by Auto-Configure, or enter it manually.
- **Area & Currency**: Inferred from the sensor name and shown read-only in BESS.

#### Provider: Octopus Energy

For UK users on the Octopus Energy Agile tariff.

- **Prerequisites**: The Octopus Energy HACS integration installed and configured. It creates event entities that update with upcoming half-hourly rates.
- **How it works**: BESS reads four event entities — today's and tomorrow's import rates, and today's and tomorrow's export rates. Prices are already VAT-inclusive in GBP/kWh.
- **Entities**: Four event entity IDs for import/export today/tomorrow. All are auto-detected by Auto-Configure.

#### Price Calculation

Once BESS has the raw spot price from your provider, it applies your configured fees and taxes to compute the actual buy and sell prices used for optimization:

- **Markup Rate**: Your energy provider's margin fee, applied before VAT. E.g. Tibber charges ~0.08 SEK/kWh, Ellevio ~0.15.
- **VAT Multiplier**: The VAT factor. 1.25 = 25% (Sweden/Norway), 1.24 = 24% (Finland), 1.22 = 22% (Estonia), 1.20 = 20% (UK).
- **Additional Costs**: Grid transfer fee + energy tax, summed as a single per-kWh value including VAT. E.g. E.ON: (0.2584 + 0.3600) × 1.25 = 0.773 SEK/kWh.
- **Export Compensation**: Per-kWh payment from your grid operator when you sell surplus electricity. Check your energy bill, e.g. E.ON under "Producent/Självfaktura": 0.1988 SEK/kWh.

The formulas:

- **Buy price** = (spot + markup) × VAT multiplier + additional costs
- **Sell price** = spot + export compensation

For Octopus Energy, prices are already final (VAT-inclusive, GBP/kWh). Markup, VAT, and Additional Costs are not applied — only Export Compensation is used.

### Consumption Prediction

BESS needs a forecast of your home consumption to plan the battery schedule. Three strategies are available, configured via `home.consumption_strategy` in your add-on settings:

#### Strategy 1: `sensor` (default)

BESS reads a Home Assistant sensor named `*48h_avg*grid_import*` (the exact entity ID is auto-discovered by name pattern). This sensor should be a 48-hour rolling average of your grid import power, filtered to exclude periods when the battery is active. See [INSTALLATION.md](INSTALLATION.md), Step 3 for how to create it.

The same flat value is used as the predicted consumption for all 96 periods of the day — it is an average, not a time-of-day profile.

**Why filter out battery activity?** When the battery discharges, it reduces grid import. Without the filter, battery-active periods would lower the average and cause the optimizer to under-predict consumption.

**EV charging — include or exclude?**

- **Exclude** (recommended for most users): The average reflects pure home consumption. The optimizer does not plan for EV charging load, but the discharge inhibit sensor (see below) prevents the battery from discharging while the car charges. This is the more robust choice when EV charging is irregular.
- **Include**: The optimizer sees the total actual load and may hold back battery capacity in anticipation. This works well only if you charge the car on a very predictable schedule (same time, same amount every night).

The 48h window is a sensible default. If your consumption varies strongly with season (e.g. heat pump), you can create the sensor with a shorter window (12–24h) so it adapts faster — just keep the `48h_avg_grid_import` naming so BESS discovers it correctly.

#### Strategy 2: `fixed`

Uses a single fixed kWh/hour value set in `home.default_hourly`. No sensor required. Useful as a fallback or for very predictable consumption, but does not adapt to actual usage.

#### Strategy 3: `influxdb_7d_avg`

Queries InfluxDB for the past 7 days of your local load power sensor and builds a 96-period average profile (one value per 15-minute slot, averaged across the same slot for the last 7 days). This gives a time-of-day shaped forecast — higher during evening peaks, lower overnight — rather than a flat value.

Requires `local_load_power` sensor configured in your add-on sensor settings and InfluxDB access.

This should give the best prediction of the three options, but require an influxdb to be set up.

### EV Charging and Discharge Inhibit

BESS does not control EV charging — it is designed to work alongside it. Under normal circumstances there is no conflict: when electricity is cheap, both the car and the battery charge at the same time.

The exception is grid reward programs such as **Tibber grid rewards**. These programs can start EV charging for grid balancing reasons, even when the spot price is not at its lowest. If BESS were to discharge the battery at the same time, that energy would flow toward the car instead of from the grid — you would miss the grid reward income and also lose the battery capacity you would otherwise have had available for the home.

To prevent this, BESS auto-detects any `binary_sensor` whose entity ID ends with `_charging` (for example `binary_sensor.zap263668_charging`) and treats it as a **discharge inhibit** signal. When the sensor is `on`, battery discharging is paused regardless of what the schedule says.

The discharge inhibit only affects discharging — it does not change the TOU schedule, trigger battery charging, or interfere with the EV charging session in any way.

## Advanced Features

### Decision Intelligence

Access detailed explanations of optimization decisions:

- Why specific charging/discharging was chosen
- Alternative options considered
- Profit calculations and risk assessment

### Historical Analysis

- Compare different time periods
- Analyze seasonal patterns
- Track long-term ROI progress
- Export data for external analysis

### Integration with Home Assistant

- Create automations based on BESS strategies
- Display key metrics on your HA dashboard
- Set up notifications for significant savings or issues

## Getting the Most Value

### Best Practices

1. **Monitor weekly trends** rather than daily fluctuations
2. **Adjust settings seasonally** as usage patterns change
3. **Keep sensors updated** for accurate optimization
4. **Review monthly reports** to track ROI progress

### Maximizing Savings

1. **Ensure price integration is working** - this is critical
2. **Verify all sensors are accurate** - garbage in, garbage out
3. **Let the system learn** - performance improves over first month
4. **Consider larger battery** if consistently hitting capacity limits

## Support and Community

### Getting Help

1. **Check this guide** for common issues
2. **Review logs** in Home Assistant for specific error messages
3. **Check GitHub issues** for known problems and solutions
4. **Post in Home Assistant Community** with specific symptoms

### Contributing

- **Share your results** - help others understand benefits
- **Report bugs** with detailed logs and system configuration
- **Request features** based on your usage patterns
- **Help others** in the community forums

---

*For installation and configuration details, see [DEPLOYMENT.md](DEPLOYMENT.md)*

*For developers interested in contributing, see [DEVELOPMENT.md](DEVELOPMENT.md)*
