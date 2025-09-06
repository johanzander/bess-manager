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

### "No optimization happening"

**Symptoms**: Battery stays at same level, no strategic intents
**Causes**:

- Price differences too small to justify battery wear
- Battery already at optimal level
- System in learning mode (first few days)

**Solutions**:

- Check electricity price sensor is working
- Verify price spread is significant (>0.50 SEK/kWh difference)
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

### Price Settings

- **Area**: Must match your actual Nordpool pricing area
- **Additional Costs**: Include all taxes, fees, and markup for accurate calculations

### Consumption Prediction

- System learns your patterns automatically
- Manually adjust if you have predictable high-usage periods
- Consider seasonal variations (heating/cooling)

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
