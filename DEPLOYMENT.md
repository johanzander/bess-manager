# BESS Manager Production Deployment Guide

This guide provides step-by-step instructions for deploying the BESS Battery Manager add-on to a production Home Assistant instance.

## Prerequisites

- Home Assistant OS, Home Assistant Container, or Home Assistant Supervised
- Growatt battery system with Home Assistant integration
- Nordpool integration configured in Home Assistant
- Administrative access to your Home Assistant instance

## Deployment Methods

### Method 1: Local Add-on Installation

1. Build the Add-on:

   ```bash
   # Clone the repository
   git clone https://github.com/yourusername/bess-manager.git
   cd bess-manager

   # Make the package script executable
   chmod +x package-addon.sh

   # Run the packaging script
   ./package-addon.sh
   ```

2. Transfer Files:

   - Copy contents of `build/bess_manager` to your Home Assistant
   - For Home Assistant OS/Supervised:
     1. Connect via SSH/Samba
     2. Navigate to `/addons`
     3. Create directory `bess_manager`
     4. Copy files there

3. Install the Add-on:

   1. Go to Configuration → Add-ons
   2. Click "Reload"
   3. Find "BESS Battery Manager" in Local add-ons
   4. Click "Install"

### Method 2: Custom Repository

1. Build and Host:

   - Follow build steps from Method 1
   - Host `build/repository` content on:
     - GitHub repository (recommended)
     - Web server accessible to Home Assistant

2. Add Repository:

   1. Go to Settings → Add-ons → Add-on Store
   2. Click menu (⋮) → Repositories
   3. Add your repository URL:
      - GitHub: [`https://github.com/yourusername/your-repo-name`](https://github.com/yourusername/your-repo-name)
      - Web server: [`http://your-server.com/path-to-repository`](http://your-server.com/path-to-repository)

3. Install Add-on:

   1. Find "BESS Battery Manager" in the Add-on Store
   2. Click "Install"

## Configuration

### Basic Settings

```yaml
battery:
  total_capacity: 30.0          # Battery total capacity in kWh
  min_soc: 10.0                 # Minimum state of charge (%)
  cycle_cost: 0.40              # Battery wear cost per cycle (SEK/kWh)
  charging_power_rate: 40       # Charging power rate (%)

consumption:
  default_hourly: 4.5           # Default hourly consumption (kWh)

price:
  area: "SE4"                   # Nordpool price area
  markup_rate: 0.08             # Electricity markup rate (SEK/kWh)
  vat_multiplier: 1.25          # VAT multiplier (1.25 = 25%)
  additional_costs: 1.03        # Additional costs (SEK/kWh)
  tax_reduction: 0.6518         # Tax reduction (SEK/kWh)
  use_actual_price: false       # Use actual price with all costs
```

### Required Sensors

Configure these in the add-on settings:

```yaml
sensors:
  # Battery sensors
  battery_soc: "sensor.growatt_battery_soc"
  battery_charge_power: "sensor.growatt_battery_charge_power"
  battery_discharge_power: "sensor.growatt_battery_discharge_power"
  battery_status: "sensor.growatt_battery_status"

  # Solar sensors
  solar_power: "sensor.growatt_solar_power"
  solar_energy_today: "sensor.growatt_solar_energy_today"

  # Grid sensors
  grid_power: "sensor.growatt_grid_power"
  export_power: "sensor.growatt_export_power"

  # Price sensor
  electricity_price: "sensor.nordpool_kwh_se4"
```

## Automation

Create these automations in Home Assistant:

### 1. Start System at Startup

```yaml
alias: Start BESS System at Startup
description: Start the BESS system when Home Assistant starts up
trigger:
  - platform: homeassistant
    event: start
action:
  - service: hassio.addon_stdin
    data:
      addon: local_bess_manager
      input: {"command": "start"}
```

### 2. Hourly Schedule Update

```yaml
alias: Update BESS Schedule Hourly
description: Update the battery schedule every hour
trigger:
  - platform: time_pattern
    minutes: "0"
action:
  - service: hassio.addon_stdin
    data:
      addon: local_bess_manager
      input: {"command": "update"}
```

### 3. Prepare Next Day's Schedule

```yaml
alias: Prepare Next Day BESS Schedule
description: Prepare the battery schedule for the next day
trigger:
  - platform: time
    at: "23:55:00"
action:
  - service: hassio.addon_stdin
    data:
      addon: local_bess_manager
      input: {"command": "prepare_next_day"}
```

## Troubleshooting

### Check Add-on Logs

1. Go to the add-on's Logs tab
2. Examine logs for error messages
3. Increase log level if needed

### Common Issues

1. No Schedule Created:

   - Check Nordpool integration
   - Verify price data availability

2. Battery Not Responding:

   - Check Growatt integration
   - Verify battery control in Home Assistant

3. Server Error in Web UI:

   - Check add-on logs
   - Verify required integrations

## Updates and Maintenance

### Updating the Add-on

1. For local installation:

   - Transfer new files to Home Assistant

2. For custom repository:

   - Pull latest changes

3. In Home Assistant:

   - Go to Add-on Store
   - Click "Reload"
   - Update when prompted

### Backup and Restore

The add-on stores configuration in:

- Add-on configuration (Home Assistant database)
- `/data` directory (add-on container)

To backup:

1. Include add-on in Home Assistant backup
2. All settings and data will be preserved

To restore:

1. Restore your Home Assistant backup
2. Add-on will be restored with settings
