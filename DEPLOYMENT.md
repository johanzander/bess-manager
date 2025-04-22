# BESS Manager Production Deployment Guide

This guide provides step-by-step instructions for deploying the BESS Battery Manager add-on to a production Home Assistant instance.

## Prerequisites

- Home Assistant OS, Home Assistant Container, or Home Assistant Supervised
- Growatt battery system with Home Assistant integration
- Nordpool integration configured in Home Assistant
- Administrative access to your Home Assistant instance

## Deployment Methods

There are two ways to deploy the BESS Manager add-on:

1. **Local Add-on Installation**: Install directly on your Home Assistant instance
2. **Custom Repository**: Add a custom repository to your Home Assistant add-on store

## Method 1: Local Add-on Installation

### Step 1: Build the Add-on

On your development machine:

```bash
# Clone the repository
git clone https://github.com/johanzander/bess-manager.git
cd bess-manager

# Make the package script executable
chmod +x package-addon.sh

# Run the packaging script
./package-addon.sh
```

This will create a build in the `build/bess_manager` directory.

### Step 2: Transfer Files to Home Assistant

Transfer the contents of the `build/bess_manager` directory to your Home Assistant machine.

If using Home Assistant OS or Supervised:

1. Connect to your Home Assistant via SSH or Samba
2. Navigate to the `/addons` directory
3. Create a new directory named `bess_manager`
4. Copy all files from `build/bess_manager` to the new directory

### Step 3: Install the Add-on

1. In Home Assistant, go to Configuration → Add-ons
2. Click the "Reload" button to refresh the add-on list
3. You should see "BESS Battery Manager" in the Local add-ons section
4. Click on it and then click "Install"

## Method 2: Custom Repository

### Step 1: Build and Host the Repository

On your development machine:

```bash
# Clone the repository
git clone https://github.com/johanzander/bess-manager.git
cd bess-manager

# Make the package script executable
chmod +x package-addon.sh

# Run the packaging script
./package-addon.sh
```

This will create a repository structure in the `build/repository` directory.

Next, you need to host this directory on:
- A GitHub repository (easiest)
- A web server accessible from your Home Assistant instance

If using GitHub:

1. Create a new GitHub repository
2. Push the contents of the `build/repository` directory to the repository

### Step 2: Add the Repository to Home Assistant

1. In Home Assistant, go to Settings → Add-ons → Add-on Store
2. Click the menu in the top-right corner
3. Select "Repositories"
4. Add your repository URL:
   - If using GitHub: `https://github.com/yourusername/bess-manager`
   - If using a web server: `http://your-server.com/path-to-repository`

### Step 3: Install the Add-on

1. After adding the repository, a new section will appear in the Add-on Store
2. Find "BESS Battery Manager" and click on it
3. Click "Install"

## Configuration

After installation, you need to configure the add-on:

1. Go to the add-on's Configuration tab
2. Adjust the settings according to your battery system:

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

3. Click "Save"
4. Toggle "Show in sidebar" if you want the add-on UI to appear in the Home Assistant sidebar

## Starting the Add-on

1. Go to the add-on's Info tab
2. Click "Start"
3. Check the logs for any errors

## Using the Add-on

### Web Interface

The add-on provides a web interface for managing the battery system:

1. Click "Open Web UI" on the add-on's Info tab
2. You should see the BESS Manager dashboard with:
   - Battery status
   - Today's schedule
   - Settings configuration

### API Endpoints

You can access the API endpoints directly:

- `/api/settings/battery` - Get/update battery settings
- `/api/schedule/today` - Get today's optimization schedule
- `/api/system/status` - Get current system status
- `/api/system/update` - Update system with current hour
- `/api/system/start` - Start the BESS system

## Automation

To fully automate the BESS Manager, create the following automations in Home Assistant:

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
description: Prepare the battery schedule for the next day at 11:55 PM
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

If you encounter issues:

1. Go to the add-on's Logs tab
2. Examine the logs for error messages
3. Increase log level if needed

### Common Issues

#### No Schedule Created

- Check if Nordpool integration is working correctly
- Verify price data is available in Home Assistant

#### Battery Not Responding

- Check if Growatt integration is working correctly
- Verify you can control the battery directly in Home Assistant

#### Server Error in Web UI

- Check add-on logs for Python errors
- Make sure all required Home Assistant integrations are available

## Updating the Add-on

When a new version is available:

1. If using a local installation, transfer the new files to your Home Assistant
2. If using a custom repository, pull the latest changes
3. In Home Assistant, go to the Add-on Store
4. Click "Reload" to check for updates
5. Update the add-on when prompted

## Backup and Restore

The add-on stores its configuration in:
- Add-on configuration (in the Home Assistant database)
- `/data` directory within the add-on container

To backup:
1. Include the add-on in your Home Assistant backup
2. This will preserve all settings and data

To restore:
1. Restore your Home Assistant backup
2. The add-on will be restored with all its settings

## Support

If you encounter issues or have questions:

1. Check the troubleshooting section above
2. Check the [GitHub issues](https://github.com/yourusername/bess-manager/issues)
3. Open a new issue if you can't find a solution