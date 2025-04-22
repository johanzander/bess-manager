# BESS Battery Manager Add-on for Home Assistant

Battery Energy Storage System (BESS) management and optimization add-on for Home Assistant.

## Overview

The BESS Battery Manager optimizes your battery storage system to maximize savings by:

- **Charging** the battery during low-price periods
- **Discharging** the battery during high-price periods
- **Maximizing** solar charging when available
- **Respecting** technical constraints of the battery and home electrical system
- **Adaptively updating** schedule hourly based on real-time measurements

## Features

- **Price-Based Optimization**: Uses Nordpool electricity prices to optimize charging/discharging
- **Solar Integration**: Prioritizes solar charging and detects solar energy flows
- **Adaptive Scheduling**: Updates schedules hourly based on current conditions
- **Consumption Prediction**: Uses historical data to predict future consumption
- **Battery Lifecycle Management**: Accounts for battery wear costs in optimization
- **Real-time Monitoring**: Tracks energy flows and battery state

## Requirements

- Growatt battery storage system with Home Assistant integration
- Nordpool electricity price sensor in Home Assistant

## Installation

1. Add this repository to your Home Assistant add-on store:
   - In Home Assistant, go to Settings → Add-ons → Add-on Store
   - Click the menu in the top right
   - Choose "Repositories"
   - Add the URL: `https://github.com/johanzander/bess-manager`

2. Find and install the "BESS Manager" add-on
3. Configure the add-on (see Configuration section)
4. Start the add-on

## Configuration

The add-on uses the following configuration options:

```yaml
battery:
  total_capacity: 30.0         # Battery total capacity in kWh
  min_soc: 10.0                # Minimum state of charge (%)
  cycle_cost: 0.40             # Battery wear cost per cycle (SEK/kWh)
  charging_power_rate: 40      # Charging power rate (%)
consumption:
  default_hourly: 4.5          # Default hourly consumption (kWh)
price:
  area: "SE4"                  # Nordpool price area
  markup_rate: 0.08            # Electricity markup rate (SEK/kWh)
  vat_multiplier: 1.25         # VAT multiplier (1.25 = 25%)
  additional_costs: 1.03       # Additional electricity costs (SEK/kWh)
  tax_reduction: 0.6518        # Tax reduction for selling electricity (SEK/kWh)
  use_actual_price: false      # Use actual price (with VAT, markup, etc.)
```

## Sensor Configuration

The BESS Manager uses specific sensor entity IDs to interact with your Home Assistant instance. If your sensors have different names than the Growatt defaults, you can configure them through the add-on configuration.

### Configuring Sensors

1. Navigate to your Home Assistant **Settings** → **Add-ons** → **BESS Manager**
2. Click on the **Configuration** tab
3. Find the `sensors` section and modify it to match your Home Assistant entity IDs:

```yaml
sensors:
  battery_soc: "sensor.my_battery_soc" 
  battery_charge_power: "sensor.my_charging_power"
```

To run the add-on in development mode:

1. Clone the repository
2. Create a `.env` file with your configuration
3. Run `./dev-run.sh` from terminal

## Support

For issues and feature requests, please [open an issue](https://github.com/johanzander/bess-manager/issues) on GitHub.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
