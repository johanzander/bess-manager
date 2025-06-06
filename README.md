# BESS Battery Manager Add-on for Home Assistant

Battery Energy Storage System (BESS) management and optimization add-on for Home Assistant.

## Overview

The BESS Battery Manager optimizes your battery storage system to maximize savings by:

- Charging the battery during low-price periods
- Discharging the battery during high-price periods
- Maximizing solar charging when available
- Respecting technical constraints of the battery and home electrical system
- Adaptively updating schedule hourly based on real-time measurements

## Features

- Price-Based Optimization: Uses Nordpool electricity prices to optimize charging/discharging

- Solar Integration: Prioritizes solar charging and detects solar energy flows

- Adaptive Scheduling: Updates schedules hourly based on current conditions

- Consumption Prediction: Uses historical data to predict future consumption

- Battery Lifecycle Management: Accounts for battery wear costs in optimization

- Real-time Monitoring: Tracks energy flows and battery state

### Web Interface Features

The BESS Manager includes a comprehensive web interface with:

- Daily Production View: Visualize electricity production patterns including grid sales, self-consumption, and battery charging

- Consumption Analytics: Track power usage from grid, solar, and battery sources throughout the day

- Battery Usage Dashboard: Monitor detailed battery charge/discharge patterns and energy flows

- Interactive Controls: Date-based visualization controls for historical analysis

## Requirements

- Home Assistant OS, Home Assistant Container, or Home Assistant Supervised

- Growatt battery storage system with Home Assistant integration

- Nordpool electricity price sensor in Home Assistant

## Quick Start

1. Add our repository to your Home Assistant add-on store:

   ```text
   https://github.com/johanzander/bess-manager
   ```

2. Install the "BESS Manager" add-on from the add-on store

3. Configure the basic settings:

   ```yaml
   battery:
     total_capacity: 30.0    # Battery total capacity in kWh
     min_soc: 10.0          # Minimum state of charge (%)
   price:
     area: "SE4"            # Your Nordpool price area
   ```

4. Start the add-on

For detailed setup instructions, see [DEPLOYMENT.md](DEPLOYMENT.md).

For development information, see [DEVELOPMENT.md](DEVELOPMENT.md).

## Support

For issues and feature requests, please [open an issue](https://github.com/johanzander/bess-manager/issues) on GitHub.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
