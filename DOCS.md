# BESS Battery Manager

Battery Energy Storage System optimization and management for Home Assistant.

## About

BESS Battery Manager is a comprehensive solution for optimizing battery energy storage systems. It uses dynamic programming algorithms to minimize electricity costs by intelligently scheduling battery charge/discharge cycles based on:

- Nordpool electricity spot prices
- Solar production forecasts
- Home consumption patterns
- Battery capacity and efficiency

## Features

- **Intelligent Optimization**: Dynamic programming algorithm for cost-optimal battery scheduling
- **Price-Based Control**: Automatic charge/discharge based on electricity price spreads
- **Solar Integration**: Optimizes for solar self-consumption and grid export
- **Real-Time Monitoring**: Live dashboard with energy flow visualization
- **Decision Intelligence**: Detailed hourly strategy analysis and economic reasoning
- **Savings Analysis**: Historical financial reports and performance tracking
- **System Health**: Comprehensive diagnostics and sensor validation

## Installation

For detailed installation instructions, see the [Installation Guide](https://github.com/johanzander/bess-manager/blob/main/INSTALLATION.md).

### Quick Start

1. Add this repository to Home Assistant:
   - Settings → Add-ons → Add-on Store → ⋮ → Repositories
   - Add: `https://github.com/johanzander/bess-manager`

2. Install BESS Manager from the add-on store

3. Configure your battery settings, sensors, and pricing parameters

4. Start the add-on and access the web interface

## Configuration

### Battery Settings

```yaml
battery:
  total_capacity: 30.0              # Battery capacity in kWh
  max_charge_discharge_power: 15.0  # Max power in kW
  cycle_cost: 0.50                  # Battery wear cost per kWh (in your currency)
  min_action_profit_threshold: 1.5  # Minimum profit for battery actions
```

### Price Settings

```yaml
electricity_price:
  area: "SE4"                       # Nordpool area
  markup_rate: 0.08                 # Electricity markup per kWh
  vat_multiplier: 1.25              # 25% VAT
  additional_costs: 1.03            # Additional costs per kWh
  tax_reduction: 0.6518             # Tax reduction for sold energy
```

### Required Sensors

The add-on requires sensors for:

- Battery: SOC, charge/discharge power, control switches
- Solar: Production, consumption, grid import/export
- Pricing: Nordpool spot prices (today and tomorrow)
- Consumption: 48-hour average forecast

See the [Installation Guide](https://github.com/johanzander/bess-manager/blob/main/INSTALLATION.md) for complete sensor configuration examples.

## Usage

### Web Interface

Access the BESS Manager dashboard via:

- **Ingress**: Settings → Add-ons → BESS Manager → Open Web UI
- **Direct**: `http://homeassistant.local:8080`

### Dashboard Pages

1. **Dashboard**: Live monitoring and daily overview
2. **Savings**: Financial analysis and historical reports
3. **Inverter**: Battery schedule management and status
4. **Insights**: Decision intelligence and strategy analysis
5. **System Health**: Component diagnostics and sensor validation

## How It Works

1. **Data Collection**: Gathers real-time data from Home Assistant sensors
2. **Price Optimization**: Analyzes Nordpool electricity prices (today + tomorrow)
3. **Solar Forecast**: Integrates solar production predictions
4. **Battery Optimization**: Dynamic programming algorithm generates optimal 24-hour schedule
5. **Schedule Deployment**: Converts optimization results to Growatt TOU intervals
6. **Continuous Monitoring**: Hourly updates adapt to changing conditions

## Troubleshooting

### Check System Health

Go to the System Health page in the web interface to verify all sensors are working correctly.

### View Logs

Check add-on logs for detailed information:

Settings → Add-ons → BESS Manager → Log

### Common Issues

**Problem**: Battery charges during expensive hours

**Solution**: Verify `cycle_cost` is set in the correct currency and matches your battery's actual degradation cost

**Problem**: Missing sensor data

**Solution**: Check all required sensors are configured and returning valid data in System Health page

## Support

- **Documentation**: [Full documentation](https://github.com/johanzander/bess-manager)
- **Issues**: [Report bugs](https://github.com/johanzander/bess-manager/issues)
- **User Guide**: [Detailed user guide](https://github.com/johanzander/bess-manager/blob/main/USER_GUIDE.md)

## License

MIT License - see [LICENSE](https://github.com/johanzander/bess-manager/blob/main/LICENSE)
