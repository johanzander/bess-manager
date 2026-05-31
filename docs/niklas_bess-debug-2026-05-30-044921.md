# BESS Manager Debug Export

**Export Date**: 2026-05-30T04:49:14.936824+02:00

**BESS Version**: unknown

## System Information

```json
{
  "bess_version": "unknown",
  "python_version": "3.11.14 (main, Oct 10 2025, 13:38:24) [GCC 13.2.1 20231014]",
  "system_uptime_hours": 0.0,
  "export_timestamp": "2026-05-30T04:49:14.936824+02:00",
  "timezone": "Europe/Stockholm"
}
```

## System Health Status

**Overall Status**: UNKNOWN

**Component Summary**:
- Critical Issues: 0
- Warnings: 0
- OK: 0
<details>
<summary>Full Health Check Results (click to expand)</summary>

```json
{
  "timestamp": "2026-05-30T04:49:16.068196",
  "system_mode": "normal",
  "checks": [
    {
      "name": "Electricity Price Data",
      "description": "Retrieves electricity prices for optimization",
      "required": true,
      "status": "OK",
      "checks": [
        {
          "name": "Nordpool Service Call",
          "status": "OK",
          "error": null,
          "value": "96 hourly prices available"
        },
        {
          "name": "Configuration Entry",
          "status": "OK",
          "error": null,
          "value": "ID: 01KMK417SVDTN466Q0SFA2WFVX"
        }
      ],
      "last_run": "2026-05-30T04:49:14.937142"
    },
    {
      "name": "Battery Control",
      "description": "Controls battery charging and discharging schedule",
      "required": true,
      "status": "OK",
      "checks": [
        {
          "name": "Battery Charging Power Rate",
          "key": "battery_charging_power_rate",
          "method_name": "get_charging_power_rate",
          "entity_id": "number.growatt_inverter_solax_inverter_ems_charging_rate",
          "status": "OK",
          "rawValue": 0.0,
          "displayValue": "0.0 %",
          "error": null
        },
        {
          "name": "Battery Discharging Power Rate",
          "key": "battery_discharging_power_rate",
          "method_name": "get_discharging_power_rate",
          "entity_id": "number.growatt_inverter_solax_inverter_ems_discharging_rate",
          "status": "OK",
          "rawValue": 100.0,
          "displayValue": "100.0 %",
          "error": null
        },
        {
          "name": "Grid Charge Enabled",
          "key": "grid_charge",
          "method_name": "grid_charge_enabled",
          "entity_id": "select.growatt_inverter_solax_inverter_allow_grid_charge",
          "status": "OK",
          "rawValue": false,
          "displayValue": "Disabled",
          "error": null
        },
        {
          "name": "Battery Charge Stop SOC",
          "key": "battery_charge_stop_soc",
          "method_name": "get_charge_stop_soc",
          "entity_id": "number.growatt_inverter_solax_inverter_ems_charging_stop_soc",
          "status": "OK",
          "rawValue": 100.0,
          "displayValue": "100.0 %",
          "error": null
        },
        {
          "name": "Battery Discharge Stop SOC",
          "key": "battery_discharge_stop_soc",
          "method_name": "get_discharge_stop_soc",
          "entity_id": "number.growatt_inverter_solax_inverter_ems_discharging_stop_soc_off_grid",
          "status": "OK",
          "rawValue": 10.0,
          "displayValue": "10.0 %",
          "error": null
        },
        {
          "name": "TOU Entity: tou_time_1_enabled",
          "key": "tou_time_1_enabled",
          "method_name": null,
          "entity_id": "select.growatt_inverter_solax_inverter_time_1_active",
          "status": "OK",
          "rawValue": null,
          "displayValue": "select.growatt_inverter_solax_inverter_time_1_active",
          "error": null
        },
        {
          "name": "TOU Entity: tou_time_1_begin",
          "key": "tou_time_1_begin",
          "method_name": null,
          "entity_id": "select.growatt_inverter_solax_inverter_time_1_begin",
          "status": "OK",
          "rawValue": null,
          "displayValue": "select.growatt_inverter_solax_inverter_time_1_begin",
          "error": null
        },
        {
          "name": "TOU Entity: tou_time_1_end",
          "key": "tou_time_1_end",
          "method_name": null,
          "entity_id": "select.growatt_inverter_solax_inverter_time_1_end",
          "status": "OK",
          "rawValue": null,
          "displayValue": "select.growatt_inverter_solax_inverter_time_1_end",
          "error": null
        },
        {
          "name": "TOU Entity: tou_time_1_mode",
          "key": "tou_time_1_mode",
          "method_name": null,
          "entity_id": "select.growatt_inverter_solax_inverter_time_1_mode",
          "status": "OK",
          "rawValue": null,
          "displayValue": "select.growatt_inverter_solax_inverter_time_1_mode",
          "error": null
        },
        {
          "name": "TOU Entity: tou_time_1_update",
          "key": "tou_time_1_update",
          "method_name": null,
          "entity_id": "button.growatt_inverter_solax_inverter_time_1_update",
          "status": "OK",
          "rawValue": null,
          "displayValue": "button.growatt_inverter_solax_inverter_time_1_update",
          "error": null
        }
      ],
      "last_run": "2026-05-30T04:49:15.044062"
    },
    {
      "name": "Battery Monitoring",
      "description": "Real-time battery state and power monitoring",
      "required": true,
      "status": "OK",
      "checks": [
        {
          "name": "Battery State of Charge",
          "key": "battery_soc",
          "method_name": "get_battery_soc",
          "entity_id": "sensor.growatt_inverter_solax_battery_soc",
          "status": "OK",
          "rawValue": 16.0,
          "displayValue": "16.0 %",
          "error": null
        },
        {
          "name": "Battery Charging Power",
          "key": "battery_charge_power",
          "method_name": "get_battery_charge_power",
          "entity_id": "sensor.growatt_inverter_solax_battery_charge_power",
          "status": "OK",
          "rawValue": 0.0,
          "displayValue": "0 W",
          "error": null
        },
        {
          "name": "Battery Discharging Power",
          "key": "battery_discharge_power",
          "method_name": "get_battery_discharge_power",
          "entity_id": "sensor.growatt_inverter_solax_battery_discharge_power",
          "status": "OK",
          "rawValue": 6560.0,
          "displayValue": "6,560 W",
          "error": null
        }
      ],
      "last_run": "2026-05-30T04:49:15.258982"
    },
    {
      "name": "Energy Monitoring",
      "description": "Tracks energy flows and consumption patterns",
      "required": true,
      "status": "OK",
      "checks": [
        {
          "name": "Lifetime Import from Grid",
          "key": "lifetime_import_from_grid",
          "method_name": "get_grid_import_lifetime",
          "entity_id": "sensor.growatt_inverter_solax_total_grid_import",
          "status": "OK",
          "rawValue": 15014.4,
          "displayValue": "15,014.4 kWh",
          "error": null
        },
        {
          "name": "Lifetime Total Export to Grid",
          "key": "lifetime_export_to_grid",
          "method_name": "get_grid_export_lifetime",
          "entity_id": "sensor.growatt_inverter_solax_total_grid_export",
          "status": "OK",
          "rawValue": 542.9,
          "displayValue": "542.9 kWh",
          "error": null
        },
        {
          "name": "Lifetime Total Solar Energy",
          "key": "lifetime_solar_energy",
          "method_name": "get_solar_production_lifetime",
          "entity_id": "sensor.growatt_inverter_solax_total_solar_energy",
          "status": "OK",
          "rawValue": 3055.3,
          "displayValue": "3,055.3 kWh",
          "error": null
        },
        {
          "name": "Lifetime Total Load Consumption",
          "key": "lifetime_load_consumption",
          "method_name": "get_load_consumption_lifetime",
          "entity_id": "sensor.growatt_inverter_solax_total_load_energy",
          "status": "OK",
          "rawValue": 17533.7,
          "displayValue": "17,533.7 kWh",
          "error": null
        },
        {
          "name": "Lifetime Total Battery Charged",
          "key": "lifetime_battery_charged",
          "method_name": "get_battery_charged_lifetime",
          "entity_id": "sensor.growatt_inverter_solax_total_battery_input_energy",
          "status": "OK",
          "rawValue": 4580.0,
          "displayValue": "4,580.0 kWh",
          "error": null
        },
        {
          "name": "Lifetime Total Battery Discharged",
          "key": "lifetime_battery_discharged",
          "method_name": "get_battery_discharged_lifetime",
          "entity_id": "sensor.growatt_inverter_solax_total_battery_output_energy",
          "status": "OK",
          "rawValue": 4586.9,
          "displayValue": "4,586.9 kWh",
          "error": null
        }
      ],
      "last_run": "2026-05-30T04:49:15.381982"
    },
    {
      "name": "Energy Prediction",
      "description": "Solar and consumption forecasting for optimization",
      "required": false,
      "status": "OK",
      "checks": [
        {
          "name": "Average Hourly Power Consumption",
          "key": "48h_avg_grid_import",
          "method_name": "get_estimated_consumption",
          "entity_id": "sensor.48h_average_grid_import_power",
          "status": "OK",
          "rawValue": [
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325,
            0.5575325
          ],
          "displayValue": "List with 96 values",
          "error": null
        },
        {
          "name": "Solar Forecast",
          "key": "solar_forecast_today",
          "method_name": "get_solar_forecast",
          "entity_id": "sensor.solcast_pv_forecast_forecast_today",
          "status": "OK",
          "rawValue": [
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0049,
            0.0049,
            0.0049,
            0.0049,
            0.042975,
            0.042975,
            0.042975,
            0.042975,
            0.1351,
            0.1351,
            0.1351,
            0.1351,
            0.25945,
            0.25945,
            0.25945,
            0.25945,
            0.428925,
            0.428925,
            0.428925,
            0.428925,
            0.651175,
            0.651175,
            0.651175,
            0.651175,
            0.8888,
            0.8888,
            0.8888,
            0.8888,
            1.0959,
            1.0959,
            1.0959,
            1.0959,
            1.23075,
            1.23075,
            1.23075,
            1.23075,
            1.20485,
            1.20485,
            1.20485,
            1.20485,
            1.0616,
            1.0616,
            1.0616,
            1.0616,
            0.8476,
            0.8476,
            0.8476,
            0.8476,
            0.602875,
            0.602875,
            0.602875,
            0.602875,
            0.367525,
            0.367525,
            0.367525,
            0.367525,
            0.189075,
            0.189075,
            0.189075,
            0.189075,
            0.069175,
            0.069175,
            0.069175,
            0.069175,
            0.019625,
            0.019625,
            0.019625,
            0.019625,
            0.00215,
            0.00215,
            0.00215,
            0.00215,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0
          ],
          "displayValue": "List with 96 values",
          "error": null
        }
      ],
      "last_run": "2026-05-30T04:49:15.631072"
    },
    {
      "name": "Power Monitoring",
      "description": "Monitors home power consumption and adapts battery charging",
      "required": false,
      "status": "OK",
      "checks": [
        {
          "name": "Current L1",
          "key": "current_l1",
          "method_name": "get_l1_current",
          "entity_id": "sensor.growatt_inverter_solax_grid_current_l1",
          "status": "OK",
          "rawValue": 16.2,
          "displayValue": "16.2 A",
          "error": null
        },
        {
          "name": "Current L2",
          "key": "current_l2",
          "method_name": "get_l2_current",
          "entity_id": "sensor.growatt_inverter_solax_grid_current_l2",
          "status": "OK",
          "rawValue": 17.2,
          "displayValue": "17.2 A",
          "error": null
        },
        {
          "name": "Current L3",
          "key": "current_l3",
          "method_name": "get_l3_current",
          "entity_id": "sensor.growatt_inverter_solax_grid_current_l3",
          "status": "OK",
          "rawValue": 17.4,
          "displayValue": "17.4 A",
          "error": null
        },
        {
          "name": "Battery Charging Power Rate",
          "key": "battery_charging_power_rate",
          "method_name": "get_charging_power_rate",
          "entity_id": "number.growatt_inverter_solax_inverter_ems_charging_rate",
          "status": "OK",
          "rawValue": 0.0,
          "displayValue": "0.0 %",
          "error": null
        }
      ],
      "last_run": "2026-05-30T04:49:15.720500"
    },
    {
      "name": "Discharge Control",
      "description": "Prevents battery discharge while EV is charging",
      "required": false,
      "status": "OK",
      "checks": [
        {
          "name": "Discharge Inhibit",
          "key": "discharge_inhibit",
          "method_name": "get_discharge_inhibit_active",
          "entity_id": "input_boolean.bess_discharge_inhibit",
          "status": "OK",
          "rawValue": false,
          "displayValue": "Disabled",
          "error": null
        }
      ],
      "last_run": "2026-05-30T04:49:15.899936"
    },
    {
      "name": "Historical Data Access",
      "description": "Provides past energy flow data for analysis and optimization",
      "required": false,
      "status": "OK",
      "checks": [
        {
          "name": "InfluxDB Configuration",
          "key": null,
          "entity_id": null,
          "status": "OK",
          "value": "URL: http://192.168.11.20:8086/api/v2/query",
          "formatted_value": "URL: http://192.168.11.20:8086/api/v2/query",
          "error": null
        },
        {
          "name": "Data Retrieval",
          "key": null,
          "entity_id": null,
          "status": "OK",
          "value": "InfluxDB connection successful",
          "formatted_value": "InfluxDB connection successful",
          "error": null
        }
      ],
      "last_run": "2026-05-30T04:49:15.948500"
    }
  ]
}
```

</details>

## Settings

### Battery Settings

```json
{
  "total_capacity": 50.0,
  "min_soc": 10.0,
  "max_soc": 100.0,
  "max_charge_power_kw": 15.0,
  "max_discharge_power_kw": 15.0,
  "charging_power_rate": 40,
  "cycle_cost_per_kwh": 0.4,
  "min_action_profit_threshold": 0.0,
  "efficiency_charge": 0.97,
  "efficiency_discharge": 0.95,
  "reserved_capacity": 5.0,
  "min_soe_kwh": 5.0,
  "max_soe_kwh": 50.0
}
```

### Price Settings

```json
{
  "area": "SE4",
  "markup_rate": 0.08,
  "vat_multiplier": 1.25,
  "additional_costs": 0.773,
  "tax_reduction": 0.1988,
  "min_profit": 0.2,
  "use_actual_price": false
}
```

### Price Data

```json
{
  "today": [
    1.4294,
    1.37373,
    1.32937,
    1.26368,
    1.27014,
    1.26153,
    1.28931,
    1.27219,
    1.24204,
    1.24527,
    1.24979,
    1.21695,
    1.17227,
    1.18088,
    1.20672,
    1.18756,
    1.25701,
    1.25109,
    1.23483,
    1.16904,
    1.27348,
    1.23073,
    0.99385,
    0.98125,
    1.25776,
    0.89931,
    0.93883,
    0.96165,
    0.89069,
    0.90921,
    0.91524,
    0.92063,
    0.94755,
    0.90545,
    0.82307,
    0.64789,
    0.83363,
    0.51437,
    0.1866,
    0.08442,
    0.25368,
    0.2315,
    0.21546,
    0.23107,
    0.26671,
    0.24173,
    0.21546,
    0.21524,
    0.26682,
    0.25778,
    0.22547,
    0.21944,
    0.25821,
    0.23301,
    0.22601,
    0.22763,
    0.21535,
    0.21944,
    0.23689,
    0.25659,
    0.24033,
    0.21546,
    0.22472,
    0.26908,
    0.19866,
    0.21718,
    0.28017,
    0.37439,
    0.09088,
    0.5415,
    0.91934,
    1.0311,
    0.82975,
    0.99966,
    1.18659,
    1.31343,
    1.24635,
    1.36371,
    1.50186,
    1.58305,
    1.44199,
    1.5865,
    1.70935,
    1.77816,
    1.72303,
    1.74112,
    1.81606,
    1.7423,
    1.75005,
    1.64733,
    1.60437,
    1.51231,
    1.51575,
    1.45492,
    1.45039,
    1.4252
  ],
  "tomorrow": []
}
```

### Home Settings

```json
{
  "max_fuse_current": 20,
  "voltage": 230,
  "safety_margin": 1.0,
  "phase_count": 3,
  "default_hourly": 4.6,
  "min_valid": 0.1,
  "currency": "SEK",
  "consumption_strategy": "influxdb_7d_avg",
  "power_monitoring_enabled": true
}
```

### Energy Provider Configuration

```json
{
  "provider": "nordpool_official",
  "nordpool_official": {
    "config_entry_id": "01KMK417SVDTN466Q0SFA2WFVX"
  },
  "nordpool_hacs": {
    "entity": ""
  },
  "octopus": {
    "import_today_entity": "",
    "import_tomorrow_entity": "",
    "export_today_entity": "",
    "export_tomorrow_entity": ""
  }
}
```

## HA Discovery (raw WebSocket)

**Nordpool config entries**: 1
**Growatt config entries**: 1
**SolaX config entries**: 1
**Devices**: 4
**Entity registry entries**: 542

### Resolved by BESS

```json
{
  "growatt_device_id": "6a8cefdea05328bcf655cd9768d95b31",
  "nordpool_config_entry_id": "01KMK417SVDTN466Q0SFA2WFVX",
  "nordpool_area": "SE3",
  "growatt_inverter_type": "growatt_server_min",
  "octopus_found": false
}
```

### Raw config entries (scrubbed)

```json
[
  {
    "entry_id": "01KEPB3J6XSMQ0F5QNCS640KGW",
    "domain": "template",
    "title": "***",
    "state": "loaded",
    "version": null,
    "options": {
      "<filtered>": "0 keys (domain not allowlisted)"
    },
    "data": {
      "<filtered>": "0 keys (domain not allowlisted)"
    }
  },
  {
    "entry_id": "01KEPB9W841JPQQFN913M5CFR2",
    "domain": "template",
    "title": "***",
    "state": "loaded",
    "version": null,
    "options": {
      "<filtered>": "0 keys (domain not allowlisted)"
    },
    "data": {
      "<filtered>": "0 keys (domain not allowlisted)"
    }
  },
  {
    "entry_id": "01KMK417SVDTN466Q0SFA2WFVX",
    "domain": "nordpool",
    "title": "***",
    "state": "loaded",
    "version": null,
    "options": {},
    "data": {}
  },
  {
    "entry_id": "01KNBGE806X4NRQPHFQPCA8YZ5",
    "domain": "growatt_server",
    "title": "***",
    "state": "loaded",
    "version": null,
    "options": {},
    "data": {}
  },
  {
    "entry_id": "01KNHGHP1WHTZMMCZ7BC9XF2AM",
    "domain": "solax_modbus",
    "title": "***",
    "state": "loaded",
    "version": null,
    "options": {},
    "data": {}
  }
]
```

<details>
<summary>Entity registry (542 entities, click to expand)</summary>

```json
[
  {
    "entity_id": "number.growatt_tl_x_xh_tl3_xh_battery_absorption_charge_voltage",
    "unique_id": "***tage",
    "unique_id_suffix": "***_inverter_1_battery_absorption_charge_voltage",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Battery absorption charge voltage"
  },
  {
    "entity_id": "number.growatt_tl_x_xh_tl3_xh_grid_first_stop_discharge",
    "unique_id": "***arge",
    "unique_id_suffix": "***_inverter_1_grid_first_stop_discharge",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Grid first stop discharge"
  },
  {
    "entity_id": "number.growatt_tl_x_xh_tl3_xh_grid_voltage_high",
    "unique_id": "***high",
    "unique_id_suffix": "***_inverter_1_grid_voltage_high",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Grid voltage high"
  },
  {
    "entity_id": "number.growatt_tl_x_xh_tl3_xh_grid_first_discharge_rate",
    "unique_id": "***rate",
    "unique_id_suffix": "***_inverter_1_grid_first_discharge_rate",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Grid first discharge rate"
  },
  {
    "entity_id": "number.growatt_tl_x_xh_tl3_xh_battery_first_charge_rate",
    "unique_id": "***rate",
    "unique_id_suffix": "***_inverter_1_battery_first_charge_rate",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Battery first charge rate"
  },
  {
    "entity_id": "number.growatt_tl_x_xh_tl3_xh_grid_voltage_low",
    "unique_id": "***_low",
    "unique_id_suffix": "***_inverter_1_grid_voltage_low",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Grid voltage low"
  },
  {
    "entity_id": "number.growatt_tl_x_xh_tl3_xh_battery_first_stop_charge",
    "unique_id": "***arge",
    "unique_id_suffix": "***_inverter_1_battery_first_stop_charge",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Battery first stop charge"
  },
  {
    "entity_id": "number.growatt_tl_x_xh_tl3_xh_grid_frequency_high",
    "unique_id": "***high",
    "unique_id_suffix": "***_inverter_1_grid_frequency_high",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Grid frequency high"
  },
  {
    "entity_id": "number.growatt_tl_x_xh_tl3_xh_export_power_rate",
    "unique_id": "***rate",
    "unique_id_suffix": "***_inverter_1_export_power_rate",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Export power rate"
  },
  {
    "entity_id": "number.growatt_tl_x_xh_tl3_xh_grid_frequency_low",
    "unique_id": "***_low",
    "unique_id_suffix": "***_inverter_1_grid_frequency_low",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Grid frequency low"
  },
  {
    "entity_id": "select.growatt_tl_x_xh_tl3_xh_export_limiter",
    "unique_id": "***iter",
    "unique_id_suffix": "***_inverter_1_export_limiter",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Export limiter"
  },
  {
    "entity_id": "select.growatt_tl_x_xh_tl3_xh_work_mode_slot_3_end",
    "unique_id": "***_end",
    "unique_id_suffix": "***_inverter_1_work_mode_slot_3_end",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Work mode slot 3 end"
  },
  {
    "entity_id": "select.growatt_tl_x_xh_tl3_xh_work_mode_slot_3_start",
    "unique_id": "***tart",
    "unique_id_suffix": "***_inverter_1_work_mode_slot_3_start",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Work mode slot 3 start"
  },
  {
    "entity_id": "select.growatt_tl_x_xh_tl3_xh_work_mode_slot_1_end",
    "unique_id": "***_end",
    "unique_id_suffix": "***_inverter_1_work_mode_slot_1_end",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Work mode slot 1 end"
  },
  {
    "entity_id": "select.growatt_tl_x_xh_tl3_xh_work_mode_slot_4_end",
    "unique_id": "***_end",
    "unique_id_suffix": "***_inverter_1_work_mode_slot_4_end",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Work mode slot 4 end"
  },
  {
    "entity_id": "select.growatt_tl_x_xh_tl3_xh_work_mode_slot_1_start",
    "unique_id": "***tart",
    "unique_id_suffix": "***_inverter_1_work_mode_slot_1_start",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Work mode slot 1 start"
  },
  {
    "entity_id": "select.growatt_tl_x_xh_tl3_xh_work_mode_slot_4_start",
    "unique_id": "***tart",
    "unique_id_suffix": "***_inverter_1_work_mode_slot_4_start",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Work mode slot 4 start"
  },
  {
    "entity_id": "select.growatt_tl_x_xh_tl3_xh_battery_first_grid_charge",
    "unique_id": "***arge",
    "unique_id_suffix": "***_inverter_1_battery_first_grid_charge",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Battery first grid charge"
  },
  {
    "entity_id": "select.growatt_tl_x_xh_tl3_xh_work_mode_slot_2_end",
    "unique_id": "***_end",
    "unique_id_suffix": "***_inverter_1_work_mode_slot_2_end",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Work mode slot 2 end"
  },
  {
    "entity_id": "select.growatt_tl_x_xh_tl3_xh_work_mode_slot_2_start",
    "unique_id": "***tart",
    "unique_id_suffix": "***_inverter_1_work_mode_slot_2_start",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Work mode slot 2 start"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_grid_frequency",
    "unique_id": "***ency",
    "unique_id_suffix": "***_inverter_1_grid_frequency",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Grid frequency"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_pv_current_1",
    "unique_id": "***nt_1",
    "unique_id_suffix": "***_inverter_1_pv_current_1",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "PV current 1"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_pv_current_4",
    "unique_id": "***nt_4",
    "unique_id_suffix": "***_inverter_1_pv_current_4",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "PV current 4"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_pv_power",
    "unique_id": "***ower",
    "unique_id_suffix": "***_inverter_1_pv_power",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "PV power"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_battery_voltage",
    "unique_id": "***tage",
    "unique_id_suffix": "***_inverter_1_battery_voltage",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Battery voltage"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_pv_power_3",
    "unique_id": "***er_3",
    "unique_id_suffix": "***_inverter_1_pv_power_3",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "PV power 3"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_pv_current_2",
    "unique_id": "***nt_2",
    "unique_id_suffix": "***_inverter_1_pv_current_2",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "PV current 2"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_serial_number",
    "unique_id": "***mber",
    "unique_id_suffix": "***_inverter_1_serial_number",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Serial number"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_temperature",
    "unique_id": "***ture",
    "unique_id_suffix": "***_inverter_1_temperature",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Temperature"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_load_percentage",
    "unique_id": "***tage",
    "unique_id_suffix": "***_inverter_1_load_percentage",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Load percentage"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_battery_current",
    "unique_id": "***rent",
    "unique_id_suffix": "***_inverter_1_battery_current",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Battery current"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_pv_voltage_4",
    "unique_id": "***ge_4",
    "unique_id_suffix": "***_inverter_1_pv_voltage_4",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "PV voltage 4"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_grid_power",
    "unique_id": "***ower",
    "unique_id_suffix": "***_inverter_1_grid_power",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Grid power"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_pv_voltage_1",
    "unique_id": "***ge_1",
    "unique_id_suffix": "***_inverter_1_pv_voltage_1",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "PV voltage 1"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_pv_voltage_2",
    "unique_id": "***ge_2",
    "unique_id_suffix": "***_inverter_1_pv_voltage_2",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "PV voltage 2"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_pv_power_1",
    "unique_id": "***er_1",
    "unique_id_suffix": "***_inverter_1_pv_power_1",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "PV power 1"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_pv_current_3",
    "unique_id": "***nt_3",
    "unique_id_suffix": "***_inverter_1_pv_current_3",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "PV current 3"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_pv_power_4",
    "unique_id": "***er_4",
    "unique_id_suffix": "***_inverter_1_pv_power_4",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "PV power 4"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_device_mode",
    "unique_id": "***mode",
    "unique_id_suffix": "***_inverter_1_device_mode",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Device mode"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_grid_voltage",
    "unique_id": "***tage",
    "unique_id_suffix": "***_inverter_1_grid_voltage",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Grid voltage"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_pv_voltage_3",
    "unique_id": "***ge_3",
    "unique_id_suffix": "***_inverter_1_pv_voltage_3",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "PV voltage 3"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_load_power",
    "unique_id": "***ower",
    "unique_id_suffix": "***_inverter_1_load_power",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Load power"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_pv_power_2",
    "unique_id": "***er_2",
    "unique_id_suffix": "***_inverter_1_pv_power_2",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "PV power 2"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_battery_power",
    "unique_id": "***ower",
    "unique_id_suffix": "***_total_battery_power",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Battery power"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_battery_state_of_charge",
    "unique_id": "***arge",
    "unique_id_suffix": "***_total_battery_state_of_charge",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Battery state of charge"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_battery_temperature",
    "unique_id": "***ture",
    "unique_id_suffix": "***_total_battery_temperature",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Battery temperature"
  },
  {
    "entity_id": "sensor.growatt_tl_x_xh_tl3_xh_bus_voltage",
    "unique_id": "***tage",
    "unique_id_suffix": "***_total_bus_voltage",
    "platform": "mqtt",
    "device_id": "82f74826b64c197f52928f6c0926a3b5",
    "original_name": "Bus voltage"
  },
  {
    "entity_id": "sensor.growatt_total_pv_energy",
    "unique_id": "***d53d",
    "unique_id_suffix": "7b634b3e-bb21-4152-8d3f-83c8b725d53d",
    "platform": "template",
    "original_name": "Growatt total PV Energy"
  },
  {
    "entity_id": "sensor.growatt_solceller_producerat",
    "unique_id": "***92ff",
    "unique_id_suffix": "b52d108e-f058-43e9-9ec1-b2192eaa92ff",
    "platform": "template",
    "original_name": "Growatt solceller producerat"
  },
  {
    "entity_id": "sensor.pv1_voltage",
    "unique_id": "***tage",
    "unique_id_suffix": "growatt_pv1_voltage",
    "platform": "modbus",
    "original_name": "PV1 Voltage"
  },
  {
    "entity_id": "sensor.pv1_current",
    "unique_id": "***rent",
    "unique_id_suffix": "growatt_pv1_current",
    "platform": "modbus",
    "original_name": "PV1 Current"
  },
  {
    "entity_id": "sensor.pv1_power",
    "unique_id": "***ower",
    "unique_id_suffix": "growatt_pv1_power",
    "platform": "modbus",
    "original_name": "PV1 Power"
  },
  {
    "entity_id": "automation.initiera_och_synk_growatt_tider",
    "unique_id": "***synk",
    "unique_id_suffix": "tou_init_och_synk",
    "platform": "automation",
    "original_name": "Initiera och synk Growatt-tider"
  },
  {
    "entity_id": "sensor.nordpool_raw_combined",
    "unique_id": "***4e43",
    "unique_id_suffix": "1161a965-fcf3-4758-a13f-730cc22a4e43",
    "platform": "template",
    "original_name": "Nordpool Raw Combined"
  },
  {
    "entity_id": "sensor.nordpool_10_day_average",
    "unique_id": "***68a2",
    "unique_id_suffix": "1b42533a-ba84-4739-9e83-fd71854368a2",
    "platform": "statistics",
    "original_name": "Nordpool 10 Day Average"
  },
  {
    "entity_id": "sensor.growatt_inverter_total_grid_import_cost",
    "unique_id": "***cost",
    "unique_id_suffix": "adbf31f32d12c7ff4068555f3eba3c5b_grid_cost",
    "platform": "energy",
    "hidden_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_total_grid_export_compensation",
    "unique_id": "***tion",
    "unique_id_suffix": "01372929dfb3c7d84440d6ce8a53063d_grid_compensation",
    "platform": "energy",
    "hidden_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_battery_discharge_power",
    "unique_id": "***0KGW",
    "unique_id_suffix": "01KEPB3J6XSMQ0F5QNCS640KGW",
    "platform": "template",
    "original_name": "Growatt battery discharge power"
  },
  {
    "entity_id": "sensor.growatt_grid_power",
    "unique_id": "***CFR2",
    "unique_id_suffix": "01KEPB9W841JPQQFN913M5CFR2",
    "platform": "template",
    "original_name": "Growatt grid power"
  },
  {
    "entity_id": "input_select.growatt_tou_radnr",
    "unique_id": "***adnr",
    "unique_id_suffix": "growatt_tou_radnr",
    "platform": "input_select",
    "original_name": "Growatt TOU Radnr"
  },
  {
    "entity_id": "script.growatt_sync_tou_slot",
    "unique_id": "***slot",
    "unique_id_suffix": "growatt_sync_tou_slot",
    "platform": "script",
    "original_name": "Growatt Sync TOU Slot"
  },
  {
    "entity_id": "automation.growatt_tou_sync",
    "unique_id": "***sync",
    "unique_id_suffix": "growatt_tou_sync",
    "platform": "automation",
    "original_name": "Growatt TOU Sync"
  },
  {
    "entity_id": "sensor.nord_pool_se3_last_updated",
    "unique_id": "***d_at",
    "unique_id_suffix": "SE3-updated_at",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Last updated",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.nord_pool_se3_currency",
    "unique_id": "***ency",
    "unique_id_suffix": "SE3-currency",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Currency",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.nord_pool_se3_exchange_rate",
    "unique_id": "***rate",
    "unique_id_suffix": "SE3-exchange_rate",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Exchange rate",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.nord_pool_se3_current_price",
    "unique_id": "***rice",
    "unique_id_suffix": "SE3-current_price",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Current price"
  },
  {
    "entity_id": "sensor.nord_pool_se3_previous_price",
    "unique_id": "***rice",
    "unique_id_suffix": "SE3-last_price",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Previous price"
  },
  {
    "entity_id": "sensor.nord_pool_se3_next_price",
    "unique_id": "***rice",
    "unique_id_suffix": "SE3-next_price",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Next price"
  },
  {
    "entity_id": "sensor.nord_pool_se3_lowest_price",
    "unique_id": "***rice",
    "unique_id_suffix": "SE3-lowest_price",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Lowest price"
  },
  {
    "entity_id": "sensor.nord_pool_se3_highest_price",
    "unique_id": "***rice",
    "unique_id_suffix": "SE3-highest_price",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Highest price"
  },
  {
    "entity_id": "sensor.nord_pool_se3_daily_average",
    "unique_id": "***rage",
    "unique_id_suffix": "SE3-daily_average",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Daily average"
  },
  {
    "entity_id": "sensor.nord_pool_se3_off_peak_1_average",
    "unique_id": "***rage",
    "unique_id_suffix": "off_peak_1-SE3-block_average",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Off-peak 1 average",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.nord_pool_se3_off_peak_1_lowest_price",
    "unique_id": "***_min",
    "unique_id_suffix": "off_peak_1-SE3-block_min",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Off-peak 1 lowest price",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.nord_pool_se3_off_peak_1_highest_price",
    "unique_id": "***_max",
    "unique_id_suffix": "off_peak_1-SE3-block_max",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Off-peak 1 highest price",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.nord_pool_se3_off_peak_1_time_from",
    "unique_id": "***time",
    "unique_id_suffix": "off_peak_1-SE3-block_start_time",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Off-peak 1 time from",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.nord_pool_se3_off_peak_1_time_until",
    "unique_id": "***time",
    "unique_id_suffix": "off_peak_1-SE3-block_end_time",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Off-peak 1 time until",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.nord_pool_se3_peak_average",
    "unique_id": "***rage",
    "unique_id_suffix": "peak-SE3-block_average",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Peak average",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.nord_pool_se3_peak_lowest_price",
    "unique_id": "***_min",
    "unique_id_suffix": "peak-SE3-block_min",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Peak lowest price",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.nord_pool_se3_peak_highest_price",
    "unique_id": "***_max",
    "unique_id_suffix": "peak-SE3-block_max",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Peak highest price",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.nord_pool_se3_peak_time_from",
    "unique_id": "***time",
    "unique_id_suffix": "peak-SE3-block_start_time",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Peak time from",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.nord_pool_se3_peak_time_until",
    "unique_id": "***time",
    "unique_id_suffix": "peak-SE3-block_end_time",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Peak time until",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.nord_pool_se3_off_peak_2_average",
    "unique_id": "***rage",
    "unique_id_suffix": "off_peak_2-SE3-block_average",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Off-peak 2 average",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.nord_pool_se3_off_peak_2_lowest_price",
    "unique_id": "***_min",
    "unique_id_suffix": "off_peak_2-SE3-block_min",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Off-peak 2 lowest price",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.nord_pool_se3_off_peak_2_highest_price",
    "unique_id": "***_max",
    "unique_id_suffix": "off_peak_2-SE3-block_max",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Off-peak 2 highest price",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.nord_pool_se3_off_peak_2_time_from",
    "unique_id": "***time",
    "unique_id_suffix": "off_peak_2-SE3-block_start_time",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Off-peak 2 time from",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.nord_pool_se3_off_peak_2_time_until",
    "unique_id": "***time",
    "unique_id_suffix": "off_peak_2-SE3-block_end_time",
    "platform": "nordpool",
    "device_id": "e06991bbe2ace9db68a2cb1a0d6a3044",
    "original_name": "Off-peak 2 time until",
    "disabled_by": "integration"
  },
  {
    "entity_id": "number.growatt_vaxelriktare_battery_charge_power_limit",
    "unique_id": "***imit",
    "unique_id_suffix": "***_battery_charge_power_limit",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Battery charge power limit",
    "entity_category": "config"
  },
  {
    "entity_id": "number.growatt_vaxelriktare_battery_charge_soc_limit",
    "unique_id": "***imit",
    "unique_id_suffix": "***_battery_charge_soc_limit",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Battery charge SOC limit",
    "entity_category": "config"
  },
  {
    "entity_id": "number.growatt_vaxelriktare_battery_discharge_power_limit",
    "unique_id": "***imit",
    "unique_id_suffix": "***_battery_discharge_power_limit",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Battery discharge power limit",
    "entity_category": "config"
  },
  {
    "entity_id": "number.growatt_vaxelriktare_battery_discharge_soc_limit_off_grid",
    "unique_id": "***imit",
    "unique_id_suffix": "***_battery_discharge_soc_limit",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Battery discharge SOC limit (off-grid)",
    "entity_category": "config"
  },
  {
    "entity_id": "number.growatt_vaxelriktare_battery_discharge_soc_limit_on_grid",
    "unique_id": "***grid",
    "unique_id_suffix": "***_battery_discharge_soc_limit_on_grid",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Battery discharge SOC limit (on-grid)",
    "entity_category": "config"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_total_total_money_today",
    "unique_id": "***oday",
    "unique_id_suffix": "***-total_money_today",
    "platform": "growatt_server",
    "device_id": "e9d1be8318691e9d0ebfcf49ec95e7ce",
    "original_name": "Total money today"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_total_money_lifetime",
    "unique_id": "***otal",
    "unique_id_suffix": "***-total_money_total",
    "platform": "growatt_server",
    "device_id": "e9d1be8318691e9d0ebfcf49ec95e7ce",
    "original_name": "Money lifetime"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_total_energy_today",
    "unique_id": "***oday",
    "unique_id_suffix": "***-total_energy_today",
    "platform": "growatt_server",
    "device_id": "e9d1be8318691e9d0ebfcf49ec95e7ce",
    "original_name": "Energy today"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_total_output_power",
    "unique_id": "***ower",
    "unique_id_suffix": "***-total_output_power",
    "platform": "growatt_server",
    "device_id": "e9d1be8318691e9d0ebfcf49ec95e7ce",
    "original_name": "Output power"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_total_lifetime_energy_output",
    "unique_id": "***tput",
    "unique_id_suffix": "***-total_energy_output",
    "platform": "growatt_server",
    "device_id": "e9d1be8318691e9d0ebfcf49ec95e7ce",
    "original_name": "Lifetime energy output"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_total_maximum_power",
    "unique_id": "***tput",
    "unique_id_suffix": "***-total_maximum_output",
    "platform": "growatt_server",
    "device_id": "e9d1be8318691e9d0ebfcf49ec95e7ce",
    "original_name": "Maximum power"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_energy_today",
    "unique_id": "***oday",
    "unique_id_suffix": "***-tlx_energy_today",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Energy today"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_lifetime_energy_output",
    "unique_id": "***otal",
    "unique_id_suffix": "***-tlx_energy_total",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Lifetime energy output"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_lifetime_total_energy_input_1",
    "unique_id": "***ut_1",
    "unique_id_suffix": "***-tlx_energy_total_input_1",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Lifetime total energy input 1"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_energy_today_input_1",
    "unique_id": "***ut_1",
    "unique_id_suffix": "***-tlx_energy_today_input_1",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Energy today input 1"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_input_1_voltage",
    "unique_id": "***ut_1",
    "unique_id_suffix": "***-tlx_voltage_input_1",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Input 1 voltage"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_input_1_amperage",
    "unique_id": "***ut_1",
    "unique_id_suffix": "***-tlx_amperage_input_1",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Input 1 amperage"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_input_1_wattage",
    "unique_id": "***ut_1",
    "unique_id_suffix": "***-tlx_wattage_input_1",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Input 1 wattage"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_lifetime_total_energy_input_2",
    "unique_id": "***ut_2",
    "unique_id_suffix": "***-tlx_energy_total_input_2",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Lifetime total energy input 2"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_energy_today_input_2",
    "unique_id": "***ut_2",
    "unique_id_suffix": "***-tlx_energy_today_input_2",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Energy today input 2"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_input_2_voltage",
    "unique_id": "***ut_2",
    "unique_id_suffix": "***-tlx_voltage_input_2",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Input 2 voltage"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_input_2_amperage",
    "unique_id": "***ut_2",
    "unique_id_suffix": "***-tlx_amperage_input_2",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Input 2 amperage"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_input_2_wattage",
    "unique_id": "***ut_2",
    "unique_id_suffix": "***-tlx_wattage_input_2",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Input 2 wattage"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_lifetime_total_energy_input_3",
    "unique_id": "***ut_3",
    "unique_id_suffix": "***-tlx_energy_total_input_3",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Lifetime total energy input 3"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_energy_today_input_3",
    "unique_id": "***ut_3",
    "unique_id_suffix": "***-tlx_energy_today_input_3",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Energy today input 3"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_input_3_voltage",
    "unique_id": "***ut_3",
    "unique_id_suffix": "***-tlx_voltage_input_3",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Input 3 voltage"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_input_3_amperage",
    "unique_id": "***ut_3",
    "unique_id_suffix": "***-tlx_amperage_input_3",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Input 3 amperage"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_input_3_wattage",
    "unique_id": "***ut_3",
    "unique_id_suffix": "***-tlx_wattage_input_3",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Input 3 wattage"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_lifetime_total_energy_input_4",
    "unique_id": "***ut_4",
    "unique_id_suffix": "***-tlx_energy_total_input_4",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Lifetime total energy input 4"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_energy_today_input_4",
    "unique_id": "***ut_4",
    "unique_id_suffix": "***-tlx_energy_today_input_4",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Energy today input 4"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_input_4_voltage",
    "unique_id": "***ut_4",
    "unique_id_suffix": "***-tlx_voltage_input_4",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Input 4 voltage"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_input_4_amperage",
    "unique_id": "***ut_4",
    "unique_id_suffix": "***-tlx_amperage_input_4",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Input 4 amperage"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_input_4_wattage",
    "unique_id": "***ut_4",
    "unique_id_suffix": "***-tlx_wattage_input_4",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Input 4 wattage"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_solar_energy_today",
    "unique_id": "***oday",
    "unique_id_suffix": "***-tlx_solar_generation_today",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Solar energy today"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_lifetime_total_solar_energy",
    "unique_id": "***otal",
    "unique_id_suffix": "***-tlx_solar_generation_total",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Lifetime total solar energy"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_internal_wattage",
    "unique_id": "***tage",
    "unique_id_suffix": "***-tlx_internal_wattage",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Internal wattage"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_reactive_voltage",
    "unique_id": "***tage",
    "unique_id_suffix": "***-tlx_reactive_voltage",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Reactive voltage",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_ac_frequency",
    "unique_id": "***ency",
    "unique_id_suffix": "***-tlx_frequency",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "AC frequency",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_output_power",
    "unique_id": "***tage",
    "unique_id_suffix": "***-tlx_current_wattage",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Output power"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_temperature_1",
    "unique_id": "***re_1",
    "unique_id_suffix": "***-tlx_temperature_1",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Temperature 1",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_temperature_2",
    "unique_id": "***re_2",
    "unique_id_suffix": "***-tlx_temperature_2",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Temperature 2",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_temperature_3",
    "unique_id": "***re_3",
    "unique_id_suffix": "***-tlx_temperature_3",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Temperature 3",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_temperature_4",
    "unique_id": "***re_4",
    "unique_id_suffix": "***-tlx_temperature_4",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Temperature 4",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_temperature_5",
    "unique_id": "***re_5",
    "unique_id_suffix": "***-tlx_temperature_5",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Temperature 5",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_all_batteries_discharged_today",
    "unique_id": "***oday",
    "unique_id_suffix": "***-tlx_all_batteries_discharge_today",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "All batteries discharged today"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_lifetime_total_all_batteries_discharged",
    "unique_id": "***otal",
    "unique_id_suffix": "***-tlx_all_batteries_discharge_total",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Lifetime total all batteries discharged"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_battery_1_discharging_w",
    "unique_id": "***ge_w",
    "unique_id_suffix": "***-tlx_battery_1_discharge_w",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Battery 1 discharging W"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_lifetime_total_battery_1_discharged",
    "unique_id": "***otal",
    "unique_id_suffix": "***-tlx_battery_1_discharge_total",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Lifetime total battery 1 discharged"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_battery_2_discharging_w",
    "unique_id": "***ge_w",
    "unique_id_suffix": "***-tlx_battery_2_discharge_w",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Battery 2 discharging W"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_lifetime_total_battery_2_discharged",
    "unique_id": "***otal",
    "unique_id_suffix": "***-tlx_battery_2_discharge_total",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Lifetime total battery 2 discharged"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_all_batteries_charged_today",
    "unique_id": "***oday",
    "unique_id_suffix": "***-tlx_all_batteries_charge_today",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "All batteries charged today"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_lifetime_total_all_batteries_charged",
    "unique_id": "***otal",
    "unique_id_suffix": "***-tlx_all_batteries_charge_total",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Lifetime total all batteries charged"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_battery_1_charging_w",
    "unique_id": "***ge_w",
    "unique_id_suffix": "***-tlx_battery_1_charge_w",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Battery 1 charging W"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_lifetime_total_battery_1_charged",
    "unique_id": "***otal",
    "unique_id_suffix": "***-tlx_battery_1_charge_total",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Lifetime total battery 1 charged"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_battery_2_charging_w",
    "unique_id": "***ge_w",
    "unique_id_suffix": "***-tlx_battery_2_charge_w",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Battery 2 charging W"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_lifetime_total_battery_2_charged",
    "unique_id": "***otal",
    "unique_id_suffix": "***-tlx_battery_2_charge_total",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Lifetime total battery 2 charged"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_export_to_grid_today",
    "unique_id": "***oday",
    "unique_id_suffix": "***-tlx_export_to_grid_today",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Export to grid today"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_lifetime_total_export_to_grid",
    "unique_id": "***otal",
    "unique_id_suffix": "***-tlx_export_to_grid_total",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Lifetime total export to grid"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_load_consumption_today",
    "unique_id": "***oday",
    "unique_id_suffix": "***-tlx_load_consumption_today",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Load consumption today"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_lifetime_total_load_consumption",
    "unique_id": "***otal",
    "unique_id_suffix": "***-mix_load_consumption_total",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Lifetime total load consumption"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_state_of_charge_soc",
    "unique_id": "***arge",
    "unique_id_suffix": "***-tlx_statement_of_charge",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "State of charge (SoC)"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_local_load_power",
    "unique_id": "***load",
    "unique_id_suffix": "***-tlx_pac_to_local_load",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Local load power"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_import_power",
    "unique_id": "***otal",
    "unique_id_suffix": "***-tlx_pac_to_user_total",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Import power"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_export_power",
    "unique_id": "***otal",
    "unique_id_suffix": "***-tlx_pac_to_grid_total",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Export power"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_system_production_today",
    "unique_id": "***oday",
    "unique_id_suffix": "***-tlx_system_production_today",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "System production today"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_lifetime_system_production",
    "unique_id": "***otal",
    "unique_id_suffix": "***-tlx_system_production_total",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Lifetime system production"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_self_consumption_today",
    "unique_id": "***oday",
    "unique_id_suffix": "***-tlx_self_consumption_today",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Self consumption today"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_lifetime_self_consumption",
    "unique_id": "***otal",
    "unique_id_suffix": "***-tlx_self_consumption_total",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Lifetime self consumption"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_import_from_grid_today",
    "unique_id": "***oday",
    "unique_id_suffix": "***-tlx_import_from_grid_today",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Import from grid today"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_lifetime_import_from_grid",
    "unique_id": "***otal",
    "unique_id_suffix": "***-tlx_import_from_grid_total",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Lifetime import from grid"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_batteries_charged_from_grid_today",
    "unique_id": "***oday",
    "unique_id_suffix": "***-tlx_batteries_charged_from_grid_today",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Batteries charged from grid today"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_lifetime_batteries_charged_from_grid",
    "unique_id": "***otal",
    "unique_id_suffix": "***-tlx_batteries_charged_from_grid_total",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Lifetime batteries charged from grid"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_system_power",
    "unique_id": "***stem",
    "unique_id_suffix": "***-tlx_p_system",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "System power"
  },
  {
    "entity_id": "sensor.growatt_vaxelriktare_self_power",
    "unique_id": "***self",
    "unique_id_suffix": "***-tlx_p_self",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Self power"
  },
  {
    "entity_id": "switch.growatt_vaxelriktare_charge_from_grid",
    "unique_id": "***arge",
    "unique_id_suffix": "***_ac_charge",
    "platform": "growatt_server",
    "device_id": "6a8cefdea05328bcf655cd9768d95b31",
    "original_name": "Charge from grid",
    "entity_category": "config"
  },
  {
    "entity_id": "update.solax_inverter_modbus_update",
    "unique_id": "***4821",
    "unique_id_suffix": "***",
    "platform": "hacs",
    "device_id": "d55346a42b54a2cd99d133062da2c6ea",
    "original_name": "Update",
    "entity_category": "config"
  },
  {
    "entity_id": "switch.solax_inverter_modbus_pre_release",
    "unique_id": "***4821",
    "unique_id_suffix": "***",
    "platform": "hacs",
    "device_id": "d55346a42b54a2cd99d133062da2c6ea",
    "original_name": "Pre-release",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "button.growatt_inverter_solax_inverter_active_power_not_limited",
    "unique_id": "***ited",
    "unique_id_suffix": "solax_active_power_not_limited",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Active Power Not Limited"
  },
  {
    "entity_id": "button.growatt_inverter_solax_inverter_reactive_power_not_limited",
    "unique_id": "***ited",
    "unique_id_suffix": "solax_reactive_power_not_limited",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Reactive Power Not Limited"
  },
  {
    "entity_id": "button.growatt_inverter_solax_inverter_sync_rtc",
    "unique_id": "***_rtc",
    "unique_id_suffix": "solax_sync_rtc",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Sync RTC"
  },
  {
    "entity_id": "button.growatt_inverter_solax_inverter_time_1_update",
    "unique_id": "***date",
    "unique_id_suffix": "solax_time_1_update",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 1 Update"
  },
  {
    "entity_id": "button.growatt_inverter_solax_inverter_time_2_update",
    "unique_id": "***date",
    "unique_id_suffix": "solax_time_2_update",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 2 Update"
  },
  {
    "entity_id": "button.growatt_inverter_solax_inverter_time_3_update",
    "unique_id": "***date",
    "unique_id_suffix": "solax_time_3_update",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 3 Update"
  },
  {
    "entity_id": "button.growatt_inverter_solax_inverter_time_4_update",
    "unique_id": "***date",
    "unique_id_suffix": "solax_time_4_update",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 4 Update"
  },
  {
    "entity_id": "button.growatt_inverter_solax_inverter_time_5_update",
    "unique_id": "***date",
    "unique_id_suffix": "solax_time_5_update",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 5 Update"
  },
  {
    "entity_id": "button.growatt_inverter_solax_inverter_time_6_update",
    "unique_id": "***date",
    "unique_id_suffix": "solax_time_6_update",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 6 Update"
  },
  {
    "entity_id": "button.growatt_inverter_solax_inverter_time_7_update",
    "unique_id": "***date",
    "unique_id_suffix": "solax_time_7_update",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 7 Update"
  },
  {
    "entity_id": "button.growatt_inverter_solax_inverter_time_8_update",
    "unique_id": "***date",
    "unique_id_suffix": "solax_time_8_update",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 8 Update"
  },
  {
    "entity_id": "button.growatt_inverter_solax_inverter_time_9_update",
    "unique_id": "***date",
    "unique_id_suffix": "solax_time_9_update",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 9 Update"
  },
  {
    "entity_id": "button.growatt_inverter_solax_inverter_time_1_clear",
    "unique_id": "***lear",
    "unique_id_suffix": "solax_time_1_clear",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 1 Clear"
  },
  {
    "entity_id": "button.growatt_inverter_solax_inverter_time_2_clear",
    "unique_id": "***lear",
    "unique_id_suffix": "solax_time_2_clear",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 2 Clear"
  },
  {
    "entity_id": "button.growatt_inverter_solax_inverter_time_3_clear",
    "unique_id": "***lear",
    "unique_id_suffix": "solax_time_3_clear",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 3 Clear"
  },
  {
    "entity_id": "button.growatt_inverter_solax_inverter_time_4_clear",
    "unique_id": "***lear",
    "unique_id_suffix": "solax_time_4_clear",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 4 Clear"
  },
  {
    "entity_id": "button.growatt_inverter_solax_inverter_time_5_clear",
    "unique_id": "***lear",
    "unique_id_suffix": "solax_time_5_clear",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 5 Clear"
  },
  {
    "entity_id": "button.growatt_inverter_solax_inverter_time_6_clear",
    "unique_id": "***lear",
    "unique_id_suffix": "solax_time_6_clear",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 6 Clear"
  },
  {
    "entity_id": "button.growatt_inverter_solax_inverter_time_7_clear",
    "unique_id": "***lear",
    "unique_id_suffix": "solax_time_7_clear",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 7 Clear"
  },
  {
    "entity_id": "button.growatt_inverter_solax_inverter_time_8_clear",
    "unique_id": "***lear",
    "unique_id_suffix": "solax_time_8_clear",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 8 Clear"
  },
  {
    "entity_id": "button.growatt_inverter_solax_inverter_time_9_clear",
    "unique_id": "***lear",
    "unique_id_suffix": "solax_time_9_clear",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 9 Clear"
  },
  {
    "entity_id": "number.growatt_inverter_solax_inverter_vpp_time",
    "unique_id": "***time",
    "unique_id_suffix": "solax_vpp_time",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter VPP Time",
    "entity_category": "config"
  },
  {
    "entity_id": "number.growatt_inverter_solax_inverter_vpp_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_vpp_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter VPP Power",
    "entity_category": "config"
  },
  {
    "entity_id": "number.growatt_inverter_solax_inverter_active_power_limit",
    "unique_id": "***imit",
    "unique_id_suffix": "solax_active_power_limit",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Active Power Limit"
  },
  {
    "entity_id": "number.growatt_inverter_solax_inverter_reactive_power_limit",
    "unique_id": "***imit",
    "unique_id_suffix": "solax_reactive_power_limit",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Reactive Power Limit"
  },
  {
    "entity_id": "number.growatt_inverter_solax_inverter_grid_export_limit",
    "unique_id": "***imit",
    "unique_id_suffix": "solax_grid_export_limit",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Grid Export Limit"
  },
  {
    "entity_id": "number.growatt_inverter_solax_inverter_ems_discharging_rate",
    "unique_id": "***rate",
    "unique_id_suffix": "solax_ems_discharging_rate",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter EMS Discharging Rate",
    "entity_category": "config"
  },
  {
    "entity_id": "number.growatt_inverter_solax_inverter_ems_discharging_stop_soc_off_grid",
    "unique_id": "***_soc",
    "unique_id_suffix": "solax_ems_discharging_stop_soc",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter EMS Discharging Stop SOC (off grid)",
    "entity_category": "config"
  },
  {
    "entity_id": "number.growatt_inverter_solax_inverter_ems_charging_rate",
    "unique_id": "***rate",
    "unique_id_suffix": "solax_ems_charging_rate",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter EMS Charging Rate",
    "entity_category": "config"
  },
  {
    "entity_id": "number.growatt_inverter_solax_inverter_ems_charging_stop_soc",
    "unique_id": "***_soc",
    "unique_id_suffix": "solax_ems_charging_stop_soc",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter EMS Charging Stop SOC",
    "entity_category": "config"
  },
  {
    "entity_id": "number.growatt_inverter_solax_inverter_ems_discharging_stop_soc_on_grid",
    "unique_id": "***grid",
    "unique_id_suffix": "solax_ems_discharging_stop_soc_on_grid",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter EMS Discharging Stop SOC (on grid)",
    "entity_category": "config"
  },
  {
    "entity_id": "number.growatt_inverter_solax_inverter_peak_import_limit",
    "unique_id": "***imit",
    "unique_id_suffix": "solax_peak_import_limit",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Peak Import Limit",
    "entity_category": "config"
  },
  {
    "entity_id": "number.growatt_inverter_solax_inverter_peak_export_limit",
    "unique_id": "***imit",
    "unique_id_suffix": "solax_peak_export_limit",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Peak Export Limit",
    "entity_category": "config"
  },
  {
    "entity_id": "number.growatt_inverter_solax_inverter_reserved_soc_for_peak_shaving",
    "unique_id": "***ving",
    "unique_id_suffix": "solax_reserved_soc_peak_shaving",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Reserved SoC for Peak Shaving",
    "entity_category": "config"
  },
  {
    "entity_id": "number.growatt_inverter_solax_inverter_max_charge_power_from_grid",
    "unique_id": "***grid",
    "unique_id_suffix": "solax_max_charge_power_from_grid",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Max charge power from grid",
    "entity_category": "config"
  },
  {
    "entity_id": "number.growatt_inverter_solax_inverter_charge_stop_soc_from_grid",
    "unique_id": "***grid",
    "unique_id_suffix": "solax_charge_stop_soc_from_grid",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Charge Stop SOC from Grid",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_vpp_status",
    "unique_id": "***atus",
    "unique_id_suffix": "solax_vpp_status",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter VPP Status",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_vpp_remote_control",
    "unique_id": "***trol",
    "unique_id_suffix": "solax_vpp_remote_control",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter VPP Remote Control",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_switch",
    "unique_id": "***itch",
    "unique_id_suffix": "solax_inverter_switch",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Switch"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_select_baud_rate",
    "unique_id": "***rate",
    "unique_id_suffix": "solax_select_baud_rate",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Select baud rate",
    "disabled_by": "integration",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_limit_grid_export",
    "unique_id": "***port",
    "unique_id_suffix": "solax_limit_grid_export",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Limit Grid Export"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_peak_shaving_active",
    "unique_id": "***able",
    "unique_id_suffix": "solax_peak_shaving_enable",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Peak Shaving Active"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_reserved_soc_for_peak_shaving_active",
    "unique_id": "***able",
    "unique_id_suffix": "solax_reserved_soc_peak_shaving_enable",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Reserved SoC for Peak Shaving Active"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_allow_grid_charge",
    "unique_id": "***itch",
    "unique_id_suffix": "solax_charger_switch",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Allow Grid Charge"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_1_begin",
    "unique_id": "***egin",
    "unique_id_suffix": "solax_time_1_begin",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 1 Begin",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_1_end",
    "unique_id": "***_end",
    "unique_id_suffix": "solax_time_1_end",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 1 End",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_1_mode",
    "unique_id": "***mode",
    "unique_id_suffix": "solax_time_1_mode",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 1 Mode",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_1_active",
    "unique_id": "***bled",
    "unique_id_suffix": "solax_time_1_enabled",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 1 Active",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_2_begin",
    "unique_id": "***egin",
    "unique_id_suffix": "solax_time_2_begin",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 2 Begin",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_2_end",
    "unique_id": "***_end",
    "unique_id_suffix": "solax_time_2_end",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 2 End",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_2_mode",
    "unique_id": "***mode",
    "unique_id_suffix": "solax_time_2_mode",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 2 Mode",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_2_active",
    "unique_id": "***bled",
    "unique_id_suffix": "solax_time_2_enabled",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 2 Active",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_3_begin",
    "unique_id": "***egin",
    "unique_id_suffix": "solax_time_3_begin",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 3 Begin",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_3_end",
    "unique_id": "***_end",
    "unique_id_suffix": "solax_time_3_end",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 3 End",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_3_mode",
    "unique_id": "***mode",
    "unique_id_suffix": "solax_time_3_mode",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 3 Mode",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_3_active",
    "unique_id": "***bled",
    "unique_id_suffix": "solax_time_3_enabled",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 3 Active",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_4_begin",
    "unique_id": "***egin",
    "unique_id_suffix": "solax_time_4_begin",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 4 Begin",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_4_end",
    "unique_id": "***_end",
    "unique_id_suffix": "solax_time_4_end",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 4 End",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_4_mode",
    "unique_id": "***mode",
    "unique_id_suffix": "solax_time_4_mode",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 4 Mode",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_4_active",
    "unique_id": "***bled",
    "unique_id_suffix": "solax_time_4_enabled",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 4 Active",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_5_begin",
    "unique_id": "***egin",
    "unique_id_suffix": "solax_time_5_begin",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 5 Begin",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_5_end",
    "unique_id": "***_end",
    "unique_id_suffix": "solax_time_5_end",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 5 End",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_5_mode",
    "unique_id": "***mode",
    "unique_id_suffix": "solax_time_5_mode",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 5 Mode",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_5_active",
    "unique_id": "***bled",
    "unique_id_suffix": "solax_time_5_enabled",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 5 Active",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_6_begin",
    "unique_id": "***egin",
    "unique_id_suffix": "solax_time_6_begin",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 6 Begin",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_6_end",
    "unique_id": "***_end",
    "unique_id_suffix": "solax_time_6_end",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 6 End",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_6_mode",
    "unique_id": "***mode",
    "unique_id_suffix": "solax_time_6_mode",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 6 Mode",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_6_active",
    "unique_id": "***bled",
    "unique_id_suffix": "solax_time_6_enabled",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 6 Active",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_7_begin",
    "unique_id": "***egin",
    "unique_id_suffix": "solax_time_7_begin",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 7 Begin",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_7_end",
    "unique_id": "***_end",
    "unique_id_suffix": "solax_time_7_end",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 7 End",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_7_mode",
    "unique_id": "***mode",
    "unique_id_suffix": "solax_time_7_mode",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 7 Mode",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_7_active",
    "unique_id": "***bled",
    "unique_id_suffix": "solax_time_7_enabled",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 7 Active",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_8_begin",
    "unique_id": "***egin",
    "unique_id_suffix": "solax_time_8_begin",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 8 Begin",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_8_end",
    "unique_id": "***_end",
    "unique_id_suffix": "solax_time_8_end",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 8 End",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_8_mode",
    "unique_id": "***mode",
    "unique_id_suffix": "solax_time_8_mode",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 8 Mode",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_8_active",
    "unique_id": "***bled",
    "unique_id_suffix": "solax_time_8_enabled",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 8 Active",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_9_begin",
    "unique_id": "***egin",
    "unique_id_suffix": "solax_time_9_begin",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 9 Begin",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_9_end",
    "unique_id": "***_end",
    "unique_id_suffix": "solax_time_9_end",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 9 End",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_9_mode",
    "unique_id": "***mode",
    "unique_id_suffix": "solax_time_9_mode",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 9 Mode",
    "entity_category": "config"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_time_9_active",
    "unique_id": "***bled",
    "unique_id_suffix": "solax_time_9_enabled",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Time 9 Active",
    "entity_category": "config"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_firmware_version",
    "unique_id": "***sion",
    "unique_id_suffix": "solax_firmware_version",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Firmware Version",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_firmware_control_version",
    "unique_id": "***sion",
    "unique_id_suffix": "solax_firmware_control_version",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Firmware Control Version",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_language",
    "unique_id": "***uage",
    "unique_id_suffix": "solax_language",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Language",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_rtc",
    "unique_id": "***_rtc",
    "unique_id_suffix": "solax_rtc",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax RTC",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_pv_isolation_resistance",
    "unique_id": "***ance",
    "unique_id_suffix": "solax_pv_isolation_resistance",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax PV Isolation Resistance",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_type",
    "unique_id": "***type",
    "unique_id_suffix": "solax_bms_type",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS Type",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_grid_status",
    "unique_id": "***atus",
    "unique_id_suffix": "solax_grid_status",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Grid Status",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_serial_number",
    "unique_id": "***mber",
    "unique_id_suffix": "solax_serialnumber",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Serial Number",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_battery_type",
    "unique_id": "***type",
    "unique_id_suffix": "solax_battery_type",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Battery Type",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_pv_power_total",
    "unique_id": "***otal",
    "unique_id_suffix": "solax_pv_power_total",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax PV Power Total"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_output_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_output_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Output Power"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_total_work_time_hours",
    "unique_id": "***ours",
    "unique_id_suffix": "solax_total_work_time_hours",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Total Work Time Hours",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_priority",
    "unique_id": "***rity",
    "unique_id_suffix": "solax_priority",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Priority"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_battery_combined_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_battery_combined_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Battery Combined Power"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_inverter_state",
    "unique_id": "***tate",
    "unique_id_suffix": "solax_inverter_state",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Run State",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_run_mode",
    "unique_id": "***mode",
    "unique_id_suffix": "solax_run_mode",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Machine Status",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_total_pv_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_total_pv_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Total PV Power",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_pv_voltage_1",
    "unique_id": "***ge_1",
    "unique_id_suffix": "solax_pv_voltage_1",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax PV Voltage 1"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_pv_current_1",
    "unique_id": "***nt_1",
    "unique_id_suffix": "solax_pv_current_1",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax PV Current 1"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_pv_power_1",
    "unique_id": "***er_1",
    "unique_id_suffix": "solax_pv_power_1",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax PV Power 1"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_pv_voltage_2",
    "unique_id": "***ge_2",
    "unique_id_suffix": "solax_pv_voltage_2",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax PV Voltage 2"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_pv_current_2",
    "unique_id": "***nt_2",
    "unique_id_suffix": "solax_pv_current_2",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax PV Current 2"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_pv_power_2",
    "unique_id": "***er_2",
    "unique_id_suffix": "solax_pv_power_2",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax PV Power 2"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_grid_power_total",
    "unique_id": "***r_va",
    "unique_id_suffix": "solax_total_grid_power_va",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Grid Power Total"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_total_grid_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_total_grid_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Total Grid Power",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_grid_frequency",
    "unique_id": "***ency",
    "unique_id_suffix": "solax_grid_frequency",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Grid Frequency"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_grid_voltage_l1",
    "unique_id": "***e_l1",
    "unique_id_suffix": "solax_grid_voltage_l1",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Grid Voltage L1"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_grid_current_l1",
    "unique_id": "***t_l1",
    "unique_id_suffix": "solax_grid_current_l1",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Grid Current L1"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_grid_power_l1",
    "unique_id": "***r_l1",
    "unique_id_suffix": "solax_grid_power_l1",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Grid Power L1"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_grid_voltage_l2",
    "unique_id": "***e_l2",
    "unique_id_suffix": "solax_grid_voltage_l2",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Grid Voltage L2"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_grid_current_l2",
    "unique_id": "***t_l2",
    "unique_id_suffix": "solax_grid_current_l2",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Grid Current L2"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_grid_power_l2",
    "unique_id": "***r_l2",
    "unique_id_suffix": "solax_grid_power_l2",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Grid Power L2"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_grid_voltage_l3",
    "unique_id": "***e_l3",
    "unique_id_suffix": "solax_grid_voltage_l3",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Grid Voltage L3"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_grid_current_l3",
    "unique_id": "***t_l3",
    "unique_id_suffix": "solax_grid_current_l3",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Grid Current L3"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_grid_power_l3",
    "unique_id": "***r_l3",
    "unique_id_suffix": "solax_grid_power_l3",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Grid Power L3"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_total_import_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_total_forward_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Total Import Power"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_total_export_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_total_reverse_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Total Export Power"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_total_load_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_total_load_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Total Load Power"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_today_s_power_generation",
    "unique_id": "***tion",
    "unique_id_suffix": "solax_today_s_power_generation",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Today's Power Generation"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_total_power_generation",
    "unique_id": "***tion",
    "unique_id_suffix": "solax_total_power_generation",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Total Power Generation"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_total_solar_energy",
    "unique_id": "***ergy",
    "unique_id_suffix": "solax_total_solar_energy",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Total Solar Energy"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_today_s_pv1_solar_energy",
    "unique_id": "***ergy",
    "unique_id_suffix": "solax_today_s_pv1_solar_energy",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Today's PV1 Solar Energy",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_total_pv1_solar_energy",
    "unique_id": "***ergy",
    "unique_id_suffix": "solax_total_pv1_solar_energy",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Total PV1 Solar Energy",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_today_s_pv2_solar_energy",
    "unique_id": "***ergy",
    "unique_id_suffix": "solax_today_s_pv2_solar_energy",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Today's PV2 Solar Energy",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_total_pv2_solar_energy",
    "unique_id": "***ergy",
    "unique_id_suffix": "solax_total_pv2_solar_energy",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Total PV2 Solar Energy",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_today_s_grid_import",
    "unique_id": "***port",
    "unique_id_suffix": "solax_today_s_grid_import",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Today's Grid Import"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_total_grid_import",
    "unique_id": "***port",
    "unique_id_suffix": "solax_total_grid_import",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Total Grid Import"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_today_s_grid_export",
    "unique_id": "***port",
    "unique_id_suffix": "solax_today_s_grid_export",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Today's Grid Export"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_total_grid_export",
    "unique_id": "***port",
    "unique_id_suffix": "solax_total_grid_export",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Total Grid Export"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_today_s_load_energy",
    "unique_id": "***ield",
    "unique_id_suffix": "solax_today_s_yield",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Today's Load Energy"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_total_load_energy",
    "unique_id": "***ield",
    "unique_id_suffix": "solax_total_yield",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Total Load Energy"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_today_s_solar_energy",
    "unique_id": "***ergy",
    "unique_id_suffix": "solax_today_s_solar_energy",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Today's Solar Energy"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_inverter_temperature",
    "unique_id": "***ture",
    "unique_id_suffix": "solax_inverter_temperature",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Temperature",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_ipm_inverter_temperature",
    "unique_id": "***ture",
    "unique_id_suffix": "solax_ipm_inverter_temperature",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax IPM Inverter Temperature",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_boost_temperature",
    "unique_id": "***ture",
    "unique_id_suffix": "solax_boost_temperature",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Boost Temperature",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_communication_board_temperature",
    "unique_id": "***ture",
    "unique_id_suffix": "solax_communication_board_temperature",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Communication Board Temperature",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_today_s_battery_output_energy",
    "unique_id": "***ergy",
    "unique_id_suffix": "solax_today_s_battery_output_energy",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Today's Battery Output Energy"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_total_battery_output_energy",
    "unique_id": "***ergy",
    "unique_id_suffix": "solax_total_battery_output_energy",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Total Battery Output Energy"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_today_s_battery_input_energy",
    "unique_id": "***ergy",
    "unique_id_suffix": "solax_today_s_battery_input_energy",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Today's Battery Input Energy"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_total_battery_input_energy",
    "unique_id": "***ergy",
    "unique_id_suffix": "solax_total_battery_input_energy",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Total Battery Input Energy"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_work_mode_priority",
    "unique_id": "***rity",
    "unique_id_suffix": "solax_work_mode_priority",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Work Mode - Priority"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_battery_voltage",
    "unique_id": "***tage",
    "unique_id_suffix": "solax_battery_voltage",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Battery Voltage"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_battery_current",
    "unique_id": "***rent",
    "unique_id_suffix": "solax_battery_current",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Battery Current"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_battery_soc",
    "unique_id": "***_soc",
    "unique_id_suffix": "solax_battery_soc",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Battery SOC"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_battery_discharge_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_battery_discharge_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Battery Discharge Power"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_battery_charge_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_battery_charge_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Battery Charge Power"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_1_begin_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_1_begin_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 1 Begin (read)",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_1_mode_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_1_mode_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 1 Mode (read)",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_1_active_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_1_enabled_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 1 Active (read)",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_1_end_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_1_end_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 1 End (read)",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_2_begin_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_2_begin_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 2 Begin (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_2_mode_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_2_mode_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 2 Mode (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_2_active_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_2_enabled_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 2 Active (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_2_end_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_2_end_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 2 End (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_3_begin_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_3_begin_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 3 Begin (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_3_mode_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_3_mode_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 3 Mode (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_3_active_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_3_enabled_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 3 Active (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_3_end_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_3_end_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 3 End (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_4_begin_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_4_begin_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 4 Begin (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_4_mode_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_4_mode_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 4 Mode (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_4_active_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_4_enabled_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 4 Active (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_4_end_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_4_end_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 4 End (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_5_begin_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_5_begin_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 5 Begin (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_5_mode_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_5_mode_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 5 Mode (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_5_active_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_5_enabled_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 5 Active (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_5_end_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_5_end_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 5 End (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_6_begin_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_6_begin_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 6 Begin (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_6_mode_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_6_mode_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 6 Mode (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_6_active_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_6_enabled_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 6 Active (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_6_end_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_6_end_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 6 End (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_7_begin_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_7_begin_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 7 Begin (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_7_mode_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_7_mode_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 7 Mode (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_7_active_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_7_enabled_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 7 Active (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_7_end_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_7_end_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 7 End (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_8_begin_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_8_begin_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 8 Begin (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_8_mode_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_8_mode_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 8 Mode (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_8_active_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_8_enabled_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 8 Active (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_8_end_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_8_end_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 8 End (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_9_begin_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_9_begin_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 9 Begin (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_9_mode_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_9_mode_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 9 Mode (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_9_active_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_9_enabled_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 9 Active (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_time_9_end_read",
    "unique_id": "***read",
    "unique_id_suffix": "solax_time_9_end_read",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Time 9 End (read)",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_inverter_warning_text",
    "unique_id": "***text",
    "unique_id_suffix": "solax_inverter_warning_text",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Warning Text"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_inverter_fault_text",
    "unique_id": "***text",
    "unique_id_suffix": "solax_inverter_fault_text",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Fault Text"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_backup_status",
    "unique_id": "***atus",
    "unique_id_suffix": "solax_backup_status",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Backup Status",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_inverter_total_module_count",
    "unique_id": "***ount",
    "unique_id_suffix": "solax_inverter_total_module_count",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter Total Module Count"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_s_connected",
    "unique_id": "***eted",
    "unique_id_suffix": "solax_bmss_connceted",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS's Connected"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_serial_number",
    "unique_id": "***mber",
    "unique_id_suffix": "solax_bms_1_serialnumber",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Serial Number",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_charge_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_bms_1_charge_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Charge Power",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_discharge_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_bms_1_discharge_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Discharge Power",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_temp_a",
    "unique_id": "***mp_a",
    "unique_id_suffix": "solax_bms_1_temp_a",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Temp A"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_temp_b",
    "unique_id": "***mp_b",
    "unique_id_suffix": "solax_bms_1_temp_b",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Temp B"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_count",
    "unique_id": "***ount",
    "unique_id_suffix": "solax_bms_1_module_count",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module Count"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_status",
    "unique_id": "***atus",
    "unique_id_suffix": "solax_bms_1_status",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Status"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_awake_modules",
    "unique_id": "***ules",
    "unique_id_suffix": "solax_bms_1_awake_modules",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Awake Modules"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_monitoring_version",
    "unique_id": "***sion",
    "unique_id_suffix": "solax_bms_1_monitoring_version",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Monitoring Version",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_total_output_energy",
    "unique_id": "***_toe",
    "unique_id_suffix": "solax_bms_1_toe",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Total Output Energy",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_soc",
    "unique_id": "***_soc",
    "unique_id_suffix": "solax_bms_1_soc",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 SoC",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_soh",
    "unique_id": "***_soh",
    "unique_id_suffix": "solax_bms_1_soh",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 SoH",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_1_status",
    "unique_id": "***atus",
    "unique_id_suffix": "solax_bms_1_module_1_status",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 1 Status",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_1_soc",
    "unique_id": "***_soc",
    "unique_id_suffix": "solax_bms_1_module_1_soc",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 1 SoC",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_1_soh",
    "unique_id": "***_soh",
    "unique_id_suffix": "solax_bms_1_module_1_soh",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 1 SoH",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_1_volt",
    "unique_id": "***volt",
    "unique_id_suffix": "solax_bms_1_module_1_volt",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 1 Volt",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_1_combined_current",
    "unique_id": "***rent",
    "unique_id_suffix": "solax_bms_1_module_1_combined_current",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 1 Combined Current",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_1_combined_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_bms_1_module_1_combined_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 1 Combined Power"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_1_total_output_energy",
    "unique_id": "***_toe",
    "unique_id_suffix": "solax_bms_1_module_1_toe",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 1 Total Output Energy",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_1_max_cell_temp",
    "unique_id": "***temp",
    "unique_id_suffix": "solax_bms_1_module_1_max_cell_temp",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 1 Max Cell Temp",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_1_min_cell_temp",
    "unique_id": "***temp",
    "unique_id_suffix": "solax_bms_1_module_1_min_cell_temp",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 1 Min Cell Temp",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_1_warning_text",
    "unique_id": "***text",
    "unique_id_suffix": "solax_bms_1_module_1_warning_text",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 1 Warning Text",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_1_charge_cycles",
    "unique_id": "***cles",
    "unique_id_suffix": "solax_bms_1_module_1_charge_cycles",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 1 Charge Cycles",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_1_serial_number",
    "unique_id": "***mber",
    "unique_id_suffix": "solax_bms_1_module_1_serialnumber",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 1 Serial Number",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_2_status",
    "unique_id": "***atus",
    "unique_id_suffix": "solax_bms_1_module_2_status",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 2 Status",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_2_soc",
    "unique_id": "***_soc",
    "unique_id_suffix": "solax_bms_1_module_2_soc",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 2 SoC",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_2_soh",
    "unique_id": "***_soh",
    "unique_id_suffix": "solax_bms_1_module_2_soh",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 2 SoH",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_2_volt",
    "unique_id": "***volt",
    "unique_id_suffix": "solax_bms_1_module_2_volt",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 2 Volt",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_2_combined_current",
    "unique_id": "***rent",
    "unique_id_suffix": "solax_bms_1_module_2_combined_current",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 2 Combined Current",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_2_combined_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_bms_1_module_2_combined_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 2 Combined Power",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_2_total_output_energy",
    "unique_id": "***_toe",
    "unique_id_suffix": "solax_bms_1_module_2_toe",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 2 Total Output Energy",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_2_max_cell_temp",
    "unique_id": "***temp",
    "unique_id_suffix": "solax_bms_1_module_2_max_cell_temp",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 2 Max Cell Temp",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_2_min_cell_temp",
    "unique_id": "***temp",
    "unique_id_suffix": "solax_bms_1_module_2_min_cell_temp",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 2 Min Cell Temp",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_2_warning_text",
    "unique_id": "***text",
    "unique_id_suffix": "solax_bms_1_module_2_warning_text",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 2 Warning Text",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_2_charge_cycles",
    "unique_id": "***cles",
    "unique_id_suffix": "solax_bms_1_module_2_charge_cycles",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 2 Charge Cycles",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_2_serial_number",
    "unique_id": "***mber",
    "unique_id_suffix": "solax_bms_1_module_2_serialnumber",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 2 Serial Number",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_3_status",
    "unique_id": "***atus",
    "unique_id_suffix": "solax_bms_1_module_3_status",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 3 Status",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_3_soc",
    "unique_id": "***_soc",
    "unique_id_suffix": "solax_bms_1_module_3_soc",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 3 SoC",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_3_soh",
    "unique_id": "***_soh",
    "unique_id_suffix": "solax_bms_1_module_3_soh",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 3 SoH",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_3_volt",
    "unique_id": "***volt",
    "unique_id_suffix": "solax_bms_1_module_3_volt",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 3 Volt",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_3_combined_current",
    "unique_id": "***rent",
    "unique_id_suffix": "solax_bms_1_module_3_combined_current",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 3 Combined Current",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_3_combined_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_bms_1_module_3_combined_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 3 Combined Power",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_3_total_output_energy",
    "unique_id": "***_toe",
    "unique_id_suffix": "solax_bms_1_module_3_toe",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 3 Total Output Energy",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_3_max_cell_temp",
    "unique_id": "***temp",
    "unique_id_suffix": "solax_bms_1_module_3_max_cell_temp",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 3 Max Cell Temp",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_3_min_cell_temp",
    "unique_id": "***temp",
    "unique_id_suffix": "solax_bms_1_module_3_min_cell_temp",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 3 Min Cell Temp",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_3_warning_text",
    "unique_id": "***text",
    "unique_id_suffix": "solax_bms_1_module_3_warning_text",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 3 Warning Text",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_3_charge_cycles",
    "unique_id": "***cles",
    "unique_id_suffix": "solax_bms_1_module_3_charge_cycles",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 3 Charge Cycles",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_3_serial_number",
    "unique_id": "***mber",
    "unique_id_suffix": "solax_bms_1_module_3_serialnumber",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 3 Serial Number",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_4_status",
    "unique_id": "***atus",
    "unique_id_suffix": "solax_bms_1_module_4_status",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 4 Status",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_4_soc",
    "unique_id": "***_soc",
    "unique_id_suffix": "solax_bms_1_module_4_soc",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 4 SoC",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_4_soh",
    "unique_id": "***_soh",
    "unique_id_suffix": "solax_bms_1_module_4_soh",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 4 SoH",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_4_volt",
    "unique_id": "***volt",
    "unique_id_suffix": "solax_bms_1_module_4_volt",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 4 Volt",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_4_combined_current",
    "unique_id": "***rent",
    "unique_id_suffix": "solax_bms_1_module_4_combined_current",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 4 Combined Current",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_4_combined_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_bms_1_module_4_combined_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 4 Combined Power",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_4_total_output_energy",
    "unique_id": "***_toe",
    "unique_id_suffix": "solax_bms_1_module_4_toe",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 4 Total Output Energy",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_4_max_cell_temp",
    "unique_id": "***temp",
    "unique_id_suffix": "solax_bms_1_module_4_max_cell_temp",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 4 Max Cell Temp",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_4_min_cell_temp",
    "unique_id": "***temp",
    "unique_id_suffix": "solax_bms_1_module_4_min_cell_temp",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 4 Min Cell Temp",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_4_warning_text",
    "unique_id": "***text",
    "unique_id_suffix": "solax_bms_1_module_4_warning_text",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 4 Warning Text",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_4_charge_cycles",
    "unique_id": "***cles",
    "unique_id_suffix": "solax_bms_1_module_4_charge_cycles",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 4 Charge Cycles",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_4_serial_number",
    "unique_id": "***mber",
    "unique_id_suffix": "solax_bms_1_module_4_serialnumber",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 4 Serial Number",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_5_status",
    "unique_id": "***atus",
    "unique_id_suffix": "solax_bms_1_module_5_status",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 5 Status",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_5_soc",
    "unique_id": "***_soc",
    "unique_id_suffix": "solax_bms_1_module_5_soc",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 5 SoC",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_5_soh",
    "unique_id": "***_soh",
    "unique_id_suffix": "solax_bms_1_module_5_soh",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 5 SoH",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_5_volt",
    "unique_id": "***volt",
    "unique_id_suffix": "solax_bms_1_module_5_volt",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 5 Volt",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_5_combined_current",
    "unique_id": "***rent",
    "unique_id_suffix": "solax_bms_1_module_5_combined_current",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 5 Combined Current",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_5_combined_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_bms_1_module_5_combined_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 5 Combined Power",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_5_total_output_energy",
    "unique_id": "***_toe",
    "unique_id_suffix": "solax_bms_1_module_5_toe",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 5 Total Output Energy",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_5_max_cell_temp",
    "unique_id": "***temp",
    "unique_id_suffix": "solax_bms_1_module_5_max_cell_temp",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 5 Max Cell Temp",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_5_min_cell_temp",
    "unique_id": "***temp",
    "unique_id_suffix": "solax_bms_1_module_5_min_cell_temp",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 5 Min Cell Temp",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_5_warning_text",
    "unique_id": "***text",
    "unique_id_suffix": "solax_bms_1_module_5_warning_text",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 5 Warning Text",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_5_charge_cycles",
    "unique_id": "***cles",
    "unique_id_suffix": "solax_bms_1_module_5_charge_cycles",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 5 Charge Cycles",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_5_serial_number",
    "unique_id": "***mber",
    "unique_id_suffix": "solax_bms_1_module_5_serialnumber",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 5 Serial Number",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_6_status",
    "unique_id": "***atus",
    "unique_id_suffix": "solax_bms_1_module_6_status",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 6 Status",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_6_soc",
    "unique_id": "***_soc",
    "unique_id_suffix": "solax_bms_1_module_6_soc",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 6 SoC",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_6_soh",
    "unique_id": "***_soh",
    "unique_id_suffix": "solax_bms_1_module_6_soh",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 6 SoH",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_6_volt",
    "unique_id": "***volt",
    "unique_id_suffix": "solax_bms_1_module_6_volt",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 6 Volt",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_6_combined_current",
    "unique_id": "***rent",
    "unique_id_suffix": "solax_bms_1_module_6_combined_current",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 6 Combined Current",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_6_combined_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_bms_1_module_6_combined_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 6 Combined Power",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_6_total_output_energy",
    "unique_id": "***_toe",
    "unique_id_suffix": "solax_bms_1_module_6_toe",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 6 Total Output Energy",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_6_max_cell_temp",
    "unique_id": "***temp",
    "unique_id_suffix": "solax_bms_1_module_6_max_cell_temp",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 6 Max Cell Temp",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_6_min_cell_temp",
    "unique_id": "***temp",
    "unique_id_suffix": "solax_bms_1_module_6_min_cell_temp",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 6 Min Cell Temp",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_6_warning_text",
    "unique_id": "***text",
    "unique_id_suffix": "solax_bms_1_module_6_warning_text",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 6 Warning Text",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_6_charge_cycles",
    "unique_id": "***cles",
    "unique_id_suffix": "solax_bms_1_module_6_charge_cycles",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 6 Charge Cycles",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_1_module_6_serial_number",
    "unique_id": "***mber",
    "unique_id_suffix": "solax_bms_1_module_6_serialnumber",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 1 Module 6 Serial Number",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_charge_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_bms_2_charge_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Charge Power",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_discharge_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_bms_2_discharge_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Discharge Power",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_temp_a",
    "unique_id": "***mp_a",
    "unique_id_suffix": "solax_bms_2_temp_a",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Temp A",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_temp_b",
    "unique_id": "***mp_b",
    "unique_id_suffix": "solax_bms_2_temp_b",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Temp B",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_count",
    "unique_id": "***ount",
    "unique_id_suffix": "solax_bms_2_module_count",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module Count",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_status",
    "unique_id": "***atus",
    "unique_id_suffix": "solax_bms_2_status",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Status",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_awake_modules",
    "unique_id": "***ules",
    "unique_id_suffix": "solax_bms_2_awake_modules",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Awake Modules"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_serial_number",
    "unique_id": "***mber",
    "unique_id_suffix": "solax_bms_2_serialnumber",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Serial Number",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_monitoring_version",
    "unique_id": "***sion",
    "unique_id_suffix": "solax_bms_2_monitoring_version",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Monitoring Version",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_total_output_energy",
    "unique_id": "***_toe",
    "unique_id_suffix": "solax_bms_2_toe",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Total Output Energy",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_soc",
    "unique_id": "***_soc",
    "unique_id_suffix": "solax_bms_2_soc",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 SoC",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_soh",
    "unique_id": "***_soh",
    "unique_id_suffix": "solax_bms_2_soh",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 SoH",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_1_status",
    "unique_id": "***atus",
    "unique_id_suffix": "solax_bms_2_module_1_status",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 1 Status",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_1_soc",
    "unique_id": "***_soc",
    "unique_id_suffix": "solax_bms_2_module_1_soc",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 1 SoC",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_1_soh",
    "unique_id": "***_soh",
    "unique_id_suffix": "solax_bms_2_module_1_soh",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 1 SoH",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_1_volt",
    "unique_id": "***volt",
    "unique_id_suffix": "solax_bms_2_module_1_volt",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 1 Volt",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_1_combined_current",
    "unique_id": "***rent",
    "unique_id_suffix": "solax_bms_2_module_1_combined_current",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 1 Combined Current",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_1_combined_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_bms_2_module_1_combined_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 1 Combined Power",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_1_total_output_energy",
    "unique_id": "***_toe",
    "unique_id_suffix": "solax_bms_2_module_1_toe",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 1 Total Output Energy",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_1_max_cell_temp",
    "unique_id": "***temp",
    "unique_id_suffix": "solax_bms_2_module_1_max_cell_temp",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 1 Max Cell Temp",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_1_min_cell_temp",
    "unique_id": "***temp",
    "unique_id_suffix": "solax_bms_2_module_1_min_cell_temp",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 1 Min Cell Temp",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_1_warning_text",
    "unique_id": "***text",
    "unique_id_suffix": "solax_bms_2_module_1_warning_text",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 1 Warning Text",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_1_charge_cycles",
    "unique_id": "***cles",
    "unique_id_suffix": "solax_bms_2_module_1_charge_cycles",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 1 Charge Cycles",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_1_serial_number",
    "unique_id": "***mber",
    "unique_id_suffix": "solax_bms_2_module_1_serialnumber",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 1 Serial Number",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_2_status",
    "unique_id": "***atus",
    "unique_id_suffix": "solax_bms_2_module_2_status",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 2 Status",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_2_soc",
    "unique_id": "***_soc",
    "unique_id_suffix": "solax_bms_2_module_2_soc",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 2 SoC",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_2_soh",
    "unique_id": "***_soh",
    "unique_id_suffix": "solax_bms_2_module_2_soh",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 2 SoH",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_2_volt",
    "unique_id": "***volt",
    "unique_id_suffix": "solax_bms_2_module_2_volt",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 2 Volt",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_2_combined_current",
    "unique_id": "***rent",
    "unique_id_suffix": "solax_bms_2_module_2_combined_current",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 2 Combined Current",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_2_combined_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_bms_2_module_2_combined_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 2 Combined Power",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_2_total_output_energy",
    "unique_id": "***_toe",
    "unique_id_suffix": "solax_bms_2_module_2_toe",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 2 Total Output Energy",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_2_warning_text",
    "unique_id": "***text",
    "unique_id_suffix": "solax_bms_2_module_2_warning_text",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 2 Warning Text",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_2_charge_cycles",
    "unique_id": "***cles",
    "unique_id_suffix": "solax_bms_2_module_2_charge_cycles",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 2 Charge Cycles",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_2_serial_number",
    "unique_id": "***mber",
    "unique_id_suffix": "solax_bms_2_module_2_serialnumber",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 2 Serial Number",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_3_status",
    "unique_id": "***atus",
    "unique_id_suffix": "solax_bms_2_module_3_status",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 3 Status",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_3_soc",
    "unique_id": "***_soc",
    "unique_id_suffix": "solax_bms_2_module_3_soc",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 3 SoC",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_3_soh",
    "unique_id": "***_soh",
    "unique_id_suffix": "solax_bms_2_module_3_soh",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 3 SoH",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_3_volt",
    "unique_id": "***volt",
    "unique_id_suffix": "solax_bms_2_module_3_volt",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 3 Volt",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_3_combined_current",
    "unique_id": "***rent",
    "unique_id_suffix": "solax_bms_2_module_3_combined_current",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 3 Combined Current",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_3_combined_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_bms_2_module_3_combined_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 3 Combined Power",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_3_total_output_energy",
    "unique_id": "***_toe",
    "unique_id_suffix": "solax_bms_2_module_3_toe",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 3 Total Output Energy",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_3_warning_text",
    "unique_id": "***text",
    "unique_id_suffix": "solax_bms_2_module_3_warning_text",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 3 Warning Text",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_3_charge_cycles",
    "unique_id": "***cles",
    "unique_id_suffix": "solax_bms_2_module_3_charge_cycles",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 3 Charge Cycles",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_3_serial_number",
    "unique_id": "***mber",
    "unique_id_suffix": "solax_bms_2_module_3_serialnumber",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 3 Serial Number",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_4_status",
    "unique_id": "***atus",
    "unique_id_suffix": "solax_bms_2_module_4_status",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 4 Status",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_4_soc",
    "unique_id": "***_soc",
    "unique_id_suffix": "solax_bms_2_module_4_soc",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 4 SoC",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_4_soh",
    "unique_id": "***_soh",
    "unique_id_suffix": "solax_bms_2_module_4_soh",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 4 SoH",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_4_volt",
    "unique_id": "***volt",
    "unique_id_suffix": "solax_bms_2_module_4_volt",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 4 Volt",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_4_combined_current",
    "unique_id": "***rent",
    "unique_id_suffix": "solax_bms_2_module_4_combined_current",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 4 Combined Current",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_4_combined_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_bms_2_module_4_combined_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 4 Combined Power",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_4_total_output_energy",
    "unique_id": "***_toe",
    "unique_id_suffix": "solax_bms_2_module_4_toe",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 4 Total Output Energy",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_4_warning_text",
    "unique_id": "***text",
    "unique_id_suffix": "solax_bms_2_module_4_warning_text",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 4 Warning Text",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_4_charge_cycles",
    "unique_id": "***cles",
    "unique_id_suffix": "solax_bms_2_module_4_charge_cycles",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 4 Charge Cycles",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_4_serial_number",
    "unique_id": "***mber",
    "unique_id_suffix": "solax_bms_2_module_4_serialnumber",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 4 Serial Number",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_5_status",
    "unique_id": "***atus",
    "unique_id_suffix": "solax_bms_2_module_5_status",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 5 Status",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_5_soc",
    "unique_id": "***_soc",
    "unique_id_suffix": "solax_bms_2_module_5_soc",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 5 SoC",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_5_soh",
    "unique_id": "***_soh",
    "unique_id_suffix": "solax_bms_2_module_5_soh",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 5 SoH",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_5_volt",
    "unique_id": "***volt",
    "unique_id_suffix": "solax_bms_2_module_5_volt",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 5 Volt",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_5_combined_current",
    "unique_id": "***rent",
    "unique_id_suffix": "solax_bms_2_module_5_combined_current",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 5 Combined Current",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_5_combined_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_bms_2_module_5_combined_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 5 Combined Power",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_5_total_output_energy",
    "unique_id": "***_toe",
    "unique_id_suffix": "solax_bms_2_module_5_toe",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 5 Total Output Energy",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_5_warning_text",
    "unique_id": "***text",
    "unique_id_suffix": "solax_bms_2_module_5_warning_text",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 5 Warning Text",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_5_charge_cycles",
    "unique_id": "***cles",
    "unique_id_suffix": "solax_bms_2_module_5_charge_cycles",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 5 Charge Cycles",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_5_serial_number",
    "unique_id": "***mber",
    "unique_id_suffix": "solax_bms_2_module_5_serialnumber",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 5 Serial Number",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_6_status",
    "unique_id": "***atus",
    "unique_id_suffix": "solax_bms_2_module_6_status",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 6 Status",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_6_soc",
    "unique_id": "***_soc",
    "unique_id_suffix": "solax_bms_2_module_6_soc",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 6 SoC",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_6_soh",
    "unique_id": "***_soh",
    "unique_id_suffix": "solax_bms_2_module_6_soh",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 6 SoH",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_6_volt",
    "unique_id": "***volt",
    "unique_id_suffix": "solax_bms_2_module_6_volt",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 6 Volt",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_6_combined_current",
    "unique_id": "***rent",
    "unique_id_suffix": "solax_bms_2_module_6_combined_current",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 6 Combined Current",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_6_combined_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_bms_2_module_6_combined_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 6 Combined Power",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_6_total_output_energy",
    "unique_id": "***_toe",
    "unique_id_suffix": "solax_bms_2_module_6_toe",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 6 Total Output Energy",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_6_warning_text",
    "unique_id": "***text",
    "unique_id_suffix": "solax_bms_2_module_6_warning_text",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 6 Warning Text",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_6_charge_cycles",
    "unique_id": "***cles",
    "unique_id_suffix": "solax_bms_2_module_6_charge_cycles",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 6 Charge Cycles",
    "disabled_by": "integration"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_bms_2_module_6_serial_number",
    "unique_id": "***mber",
    "unique_id_suffix": "solax_bms_2_module_6_serialnumber",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax BMS 2 Module 6 Serial Number",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "switch.solax_energy_dashboard_enable_pv_variant_detail_sensors",
    "unique_id": "***bled",
    "unique_id_suffix": "solax Energy Dashboard_energy_dashboard_pv_variants_enabled",
    "platform": "solax_modbus",
    "device_id": "c1dc5e0a5da618569cb424992d4f8466",
    "original_name": "Enable PV Variant Detail Sensors",
    "entity_category": "config"
  },
  {
    "entity_id": "switch.solax_energy_dashboard_enable_home_consumption_sensor",
    "unique_id": "***bled",
    "unique_id_suffix": "solax Energy Dashboard_energy_dashboard_home_consumption_enabled",
    "platform": "solax_modbus",
    "device_id": "c1dc5e0a5da618569cb424992d4f8466",
    "original_name": "Enable Home Consumption Sensor",
    "entity_category": "config"
  },
  {
    "entity_id": "switch.solax_energy_dashboard_enable_grid_to_battery_sensors",
    "unique_id": "***bled",
    "unique_id_suffix": "solax Energy Dashboard_energy_dashboard_grid_to_battery_enabled",
    "platform": "solax_modbus",
    "device_id": "c1dc5e0a5da618569cb424992d4f8466",
    "original_name": "Enable Grid to Battery Sensors",
    "entity_category": "config"
  },
  {
    "entity_id": "sensor.energy_grid_growatt_inverter_solax_total_import_power_growatt_inverter_solax_total_export_power_net_power",
    "unique_id": "***ower",
    "unique_id_suffix": "energy_power_grid_combined_sensor_growatt_inverter_solax_total_import_power_sensor_growatt_inverter_solax_total_export_power",
    "platform": "energy",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "Grid Power"
  },
  {
    "entity_id": "sensor.solax_self_consumed_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_self_consumed_power",
    "platform": "template",
    "original_name": "Solax Self Consumed Power"
  },
  {
    "entity_id": "sensor.solax_self_consumed_energy",
    "unique_id": "***ergy",
    "unique_id_suffix": "solax_self_consumed_energy",
    "platform": "template",
    "original_name": "Solax Self Consumed Energy"
  },
  {
    "entity_id": "sensor.growatt_inverter_inverter_lifttime_load_energy",
    "unique_id": "***RWF4",
    "unique_id_suffix": "01KNKZ8CQ25ARSFYM26JV1RWF4",
    "platform": "utility_meter",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "Inverter lifttime load energy"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_total_grid_export_compensation",
    "unique_id": "***tion",
    "unique_id_suffix": "9fa8d8b4545700174311def376245988_grid_compensation",
    "platform": "energy",
    "original_name": "sensor Compensation",
    "hidden_by": "integration"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_vpp_allow_ac_charging",
    "unique_id": "***ging",
    "unique_id_suffix": "solax_vpp_allow_ac_charging",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter VPP Allow AC charging",
    "entity_category": "config"
  },
  {
    "entity_id": "sensor.energy_battery_growatt_inverter_solax_battery_discharge_power_growatt_inverter_solax_battery_charge_power_net_power",
    "unique_id": "***ower",
    "unique_id_suffix": "energy_power_battery_combined_sensor_growatt_inverter_solax_battery_discharge_power_sensor_growatt_inverter_solax_battery_charge_power",
    "platform": "energy",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "Battery Power"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_total_grid_import_cost",
    "unique_id": "***cost",
    "unique_id_suffix": "ee42c57f05ff53bb489a33e2b3f0aefe_grid_cost",
    "platform": "energy",
    "original_name": "sensor Cost",
    "hidden_by": "integration"
  },
  {
    "entity_id": "select.growatt_inverter_solax_inverter_eps_switch",
    "unique_id": "***itch",
    "unique_id_suffix": "solax_eps_switch",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax Inverter EPS Switch",
    "entity_category": "config"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_eps_set_voltage",
    "unique_id": "***tage",
    "unique_id_suffix": "solax_eps_set_voltage",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax EPS Set Voltage"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_eps_set_frequency",
    "unique_id": "***ency",
    "unique_id_suffix": "solax_eps_set_frequency",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax EPS Set Frequency"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_eps_frequency",
    "unique_id": "***ency",
    "unique_id_suffix": "solax_eps_frequency",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax EPS Frequency"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_eps_voltage_l1",
    "unique_id": "***e_l1",
    "unique_id_suffix": "solax_eps_voltage_l1",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax EPS Voltage L1"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_eps_current_l1",
    "unique_id": "***t_l1",
    "unique_id_suffix": "solax_eps_current_l1",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax EPS Current L1"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_eps_power_l1",
    "unique_id": "***r_l1",
    "unique_id_suffix": "solax_eps_power_l1",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax EPS Power L1"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_eps_voltage_l2",
    "unique_id": "***e_l2",
    "unique_id_suffix": "solax_eps_voltage_l2",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax EPS Voltage L2"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_eps_current_l2",
    "unique_id": "***t_l2",
    "unique_id_suffix": "solax_eps_current_l2",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax EPS Current L2"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_eps_power_l2",
    "unique_id": "***r_l2",
    "unique_id_suffix": "solax_eps_power_l2",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax EPS Power L2"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_eps_voltage_l3",
    "unique_id": "***e_l3",
    "unique_id_suffix": "solax_eps_voltage_l3",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax EPS Voltage L3"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_eps_current_l3",
    "unique_id": "***t_l3",
    "unique_id_suffix": "solax_eps_current_l3",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax EPS Current L3"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_eps_power_l3",
    "unique_id": "***r_l3",
    "unique_id_suffix": "solax_eps_power_l3",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax EPS Power L3"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_eps_total_power",
    "unique_id": "***ower",
    "unique_id_suffix": "solax_eps_total_power",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax EPS Total Power"
  },
  {
    "entity_id": "sensor.growatt_inverter_solax_eps_loading",
    "unique_id": "***ding",
    "unique_id_suffix": "solax_eps_loading",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "solax EPS Loading"
  },
  {
    "entity_id": "sensor.solax_energy_dashboard_mode",
    "unique_id": "***mode",
    "unique_id_suffix": "solax Energy Dashboard_energy_dashboard_mode",
    "platform": "solax_modbus",
    "device_id": "c1dc5e0a5da618569cb424992d4f8466",
    "original_name": "Mode",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.solax_energy_dashboard_inverter_count",
    "unique_id": "***ount",
    "unique_id_suffix": "solax Energy Dashboard_energy_dashboard_inverter_count",
    "platform": "solax_modbus",
    "device_id": "c1dc5e0a5da618569cb424992d4f8466",
    "original_name": "Inverter Count",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.solax_energy_dashboard_last_total_inverter_count",
    "unique_id": "***ount",
    "unique_id_suffix": "solax Energy Dashboard_energy_dashboard_last_total_inverter_count",
    "platform": "solax_modbus",
    "device_id": "c1dc5e0a5da618569cb424992d4f8466",
    "original_name": "Last Total Inverter Count",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.solax_energy_dashboard_parallel_setting",
    "unique_id": "***ting",
    "unique_id_suffix": "solax Energy Dashboard_energy_dashboard_parallel_setting",
    "platform": "solax_modbus",
    "device_id": "c1dc5e0a5da618569cb424992d4f8466",
    "original_name": "Parallel Setting",
    "disabled_by": "integration",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.solax_energy_dashboard_mapping_summary",
    "unique_id": "***mary",
    "unique_id_suffix": "solax Energy Dashboard_energy_dashboard_mapping_summary",
    "platform": "solax_modbus",
    "device_id": "c1dc5e0a5da618569cb424992d4f8466",
    "original_name": "Mapping Summary",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_communication_health",
    "unique_id": "***alth",
    "unique_id_suffix": "solax_communication_health",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "Communication Health",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_communication_success_rate",
    "unique_id": "***rate",
    "unique_id_suffix": "solax_communication_success_rate",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "Communication Success Rate",
    "entity_category": "diagnostic"
  },
  {
    "entity_id": "sensor.growatt_inverter_communication_quarantined_registers",
    "unique_id": "***ters",
    "unique_id_suffix": "solax_communication_quarantined_registers",
    "platform": "solax_modbus",
    "device_id": "5e8d92c2bc5ab692baa4d7c812d320cf",
    "original_name": "Communication Quarantined Registers",
    "entity_category": "diagnostic"
  }
]
```

</details>

<details>
<summary>Devices and services (click to expand)</summary>

```json
{
  "devices": [
    {
      "id": "6a8cefdea05328bcf655cd9768d95b31",
      "name": "KMN0DYP037",
      "manufacturer": "Growatt",
      "model": null,
      "identifiers": [
        [
          "growatt_server",
          "***P037"
        ]
      ]
    },
    {
      "id": "e9d1be8318691e9d0ebfcf49ec95e7ce",
      "name": "Sk\u00e4rskind Byvallen Total",
      "manufacturer": "Growatt",
      "model": null,
      "identifiers": [
        [
          "growatt_server",
          "***4840"
        ]
      ]
    },
    {
      "id": "5e8d92c2bc5ab692baa4d7c812d320cf",
      "name": "Growatt Inverter",
      "manufacturer": "Growatt New Energy",
      "model": null,
      "identifiers": []
    },
    {
      "id": "c1dc5e0a5da618569cb424992d4f8466",
      "name": "solax Energy Dashboard",
      "manufacturer": "providing curated Grid, Solar, Battery power & energy sensors with parallel mode aggregation support for Home Assistant Energy Dashboard integration",
      "model": "Energy Dashboard Metrics",
      "identifiers": []
    }
  ],
  "services": {
    "growatt_server": [
      "read_ac_charge_times",
      "read_ac_discharge_times",
      "read_time_segments",
      "update_time_segment",
      "write_ac_charge_times",
      "write_ac_discharge_times"
    ],
    "nordpool": [
      "get_price_indices_for_date",
      "get_prices_for_date"
    ],
    "solax_modbus": [
      "stop_all",
      "stop_hub"
    ]
  }
}
```

</details>

## BESS Configuration

```json
{
  "influxdb": {
    "url": "http://192.168.11.20:8086/api/v2/query",
    "bucket": "homeassistant/autogen"
  },
  "battery": {
    "total_capacity": 50.0,
    "min_soc": 10.0,
    "max_soc": 100.0,
    "max_charge_power_kw": 15.0,
    "max_discharge_power_kw": 15.0,
    "cycle_cost_per_kwh": 0.4,
    "min_action_profit_threshold": 0.0,
    "charging_power_rate": 40,
    "efficiency_charge": 0.97,
    "efficiency_discharge": 0.95
  },
  "home": {
    "default_hourly": 4.6,
    "currency": "SEK",
    "consumption_strategy": "influxdb_7d_avg",
    "max_fuse_current": 20,
    "voltage": 230,
    "safety_margin": 1.0,
    "phase_count": 3,
    "power_monitoring_enabled": true
  },
  "electricity_price": {
    "markup_rate": 0.08,
    "vat_multiplier": 1.25,
    "additional_costs": 0.773,
    "tax_reduction": 0.1988,
    "area": "SE4",
    "use_actual_price": false
  },
  "energy_provider": {
    "provider": "nordpool_official",
    "nordpool_official": {
      "config_entry_id": "01KMK417SVDTN466Q0SFA2WFVX"
    },
    "nordpool_hacs": {
      "entity": ""
    },
    "octopus": {
      "import_today_entity": "",
      "import_tomorrow_entity": "",
      "export_today_entity": "",
      "export_tomorrow_entity": ""
    }
  },
  "growatt": {
    "inverter_type": "",
    "device_id": ""
  },
  "inverter": {
    "platform": "solax_modbus_growatt_min",
    "device_id": ""
  },
  "sensors": {
    "platform": "solax_modbus_growatt_min",
    "solax_modbus_growatt_min": {
      "battery_soc": "sensor.growatt_inverter_solax_battery_soc",
      "battery_charge_power": "sensor.growatt_inverter_solax_battery_charge_power",
      "battery_discharge_power": "sensor.growatt_inverter_solax_battery_discharge_power",
      "battery_charge_stop_soc": "number.growatt_inverter_solax_inverter_ems_charging_stop_soc",
      "battery_discharge_stop_soc": "number.growatt_inverter_solax_inverter_ems_discharging_stop_soc_off_grid",
      "battery_charging_power_rate": "number.growatt_inverter_solax_inverter_ems_charging_rate",
      "battery_discharging_power_rate": "number.growatt_inverter_solax_inverter_ems_discharging_rate",
      "grid_charge": "select.growatt_inverter_solax_inverter_allow_grid_charge",
      "pv_power": "sensor.growatt_inverter_solax_pv_power_total",
      "local_load_power": "sensor.growatt_inverter_solax_total_load_power",
      "import_power": "sensor.growatt_inverter_solax_total_import_power",
      "export_power": "sensor.growatt_inverter_solax_total_export_power",
      "lifetime_battery_charged": "sensor.growatt_inverter_solax_total_battery_input_energy",
      "lifetime_battery_discharged": "sensor.growatt_inverter_solax_total_battery_output_energy",
      "lifetime_solar_energy": "sensor.growatt_inverter_solax_total_solar_energy",
      "lifetime_export_to_grid": "sensor.growatt_inverter_solax_total_grid_export",
      "lifetime_import_from_grid": "sensor.growatt_inverter_solax_total_grid_import",
      "lifetime_load_consumption": "sensor.growatt_inverter_solax_total_load_energy",
      "lifetime_system_production": "sensor.growatt_inverter_solax_total_power_generation",
      "lifetime_self_consumption": "",
      "solax_power_control_mode": "",
      "solax_active_power": "",
      "solax_autorepeat_duration": "",
      "solax_power_control_trigger": "",
      "solax_battery_min_soc": "",
      "solax_charger_use_mode": "",
      "tou_time_1_enabled": "select.growatt_inverter_solax_inverter_time_1_active",
      "tou_time_1_begin": "select.growatt_inverter_solax_inverter_time_1_begin",
      "tou_time_1_end": "select.growatt_inverter_solax_inverter_time_1_end",
      "tou_time_1_mode": "select.growatt_inverter_solax_inverter_time_1_mode",
      "tou_time_1_update": "button.growatt_inverter_solax_inverter_time_1_update"
    },
    "shared": {
      "solar_forecast_today": "sensor.solcast_pv_forecast_forecast_today",
      "solar_forecast_tomorrow": "sensor.solcast_pv_forecast_forecast_tomorrow",
      "48h_avg_grid_import": "sensor.48h_average_grid_import_power",
      "current_l1": "sensor.growatt_inverter_solax_grid_current_l1",
      "current_l2": "sensor.growatt_inverter_solax_grid_current_l2",
      "current_l3": "sensor.growatt_inverter_solax_grid_current_l3",
      "discharge_inhibit": "input_boolean.bess_discharge_inhibit",
      "weather_entity": "weather.byvallen"
    }
  }
}
```

## Entity Snapshot

**Entities captured**: 26

| Entity ID | State | Unit |
|---|---|---|
| `input_boolean.bess_discharge_inhibit` | off |  |
| `number.growatt_inverter_solax_inverter_ems_charging_rate` | 0 | % |
| `number.growatt_inverter_solax_inverter_ems_charging_stop_soc` | 100 | % |
| `number.growatt_inverter_solax_inverter_ems_discharging_rate` | 100 | % |
| `number.growatt_inverter_solax_inverter_ems_discharging_stop_soc_off_grid` | 10 | % |
| `select.growatt_inverter_solax_inverter_allow_grid_charge` | Disabled |  |
| `sensor.48h_average_grid_import_power` | 2230.13 | W |
| `sensor.growatt_inverter_solax_battery_charge_power` | 0.0 | W |
| `sensor.growatt_inverter_solax_battery_discharge_power` | 6560.0 | W |
| `sensor.growatt_inverter_solax_battery_soc` | 16 | % |
| `sensor.growatt_inverter_solax_grid_current_l1` | 16.2 | A |
| `sensor.growatt_inverter_solax_grid_current_l2` | 17.2 | A |
| `sensor.growatt_inverter_solax_grid_current_l3` | 17.4 | A |
| `sensor.growatt_inverter_solax_pv_power_total` | 0.0 | W |
| `sensor.growatt_inverter_solax_total_battery_input_energy` | 4580.0 | kWh |
| `sensor.growatt_inverter_solax_total_battery_output_energy` | 4586.9 | kWh |
| `sensor.growatt_inverter_solax_total_export_power` | 0.0 | W |
| `sensor.growatt_inverter_solax_total_grid_export` | 542.9 | kWh |
| `sensor.growatt_inverter_solax_total_grid_import` | 15014.4 | kWh |
| `sensor.growatt_inverter_solax_total_import_power` | 0.0 | W |
| `sensor.growatt_inverter_solax_total_load_energy` | 17533.7 | kWh |
| `sensor.growatt_inverter_solax_total_load_power` | 12777.0 | W |
| `sensor.growatt_inverter_solax_total_power_generation` | 3934.3 | kWh |
| `sensor.growatt_inverter_solax_total_solar_energy` | 3055.3 | kWh |
| `sensor.solcast_pv_forecast_forecast_today` | 36.4096 | kWh |
| `sensor.solcast_pv_forecast_forecast_tomorrow` | 43.504 | kWh |

<details>
<summary>Full HA entity states (JSON — needed for mock HA replay)</summary>

```json
{
  "sensor.growatt_inverter_solax_battery_soc": {
    "entity_id": "sensor.growatt_inverter_solax_battery_soc",
    "state": "16",
    "attributes": {
      "ed_mapping_present": false,
      "unit_of_measurement": "%",
      "device_class": "battery",
      "friendly_name": "Growatt Inverter solax Battery SOC"
    }
  },
  "number.growatt_inverter_solax_inverter_ems_charging_rate": {
    "entity_id": "number.growatt_inverter_solax_inverter_ems_charging_rate",
    "state": "0",
    "attributes": {
      "min": 0,
      "max": 100,
      "step": 1,
      "mode": "auto",
      "unit_of_measurement": "%",
      "icon": "mdi:battery-arrow-up",
      "friendly_name": "Growatt Inverter solax Inverter EMS Charging Rate"
    }
  },
  "number.growatt_inverter_solax_inverter_ems_discharging_rate": {
    "entity_id": "number.growatt_inverter_solax_inverter_ems_discharging_rate",
    "state": "100",
    "attributes": {
      "min": 0,
      "max": 100,
      "step": 1,
      "mode": "auto",
      "unit_of_measurement": "%",
      "icon": "mdi:battery-arrow-down",
      "friendly_name": "Growatt Inverter solax Inverter EMS Discharging Rate"
    }
  },
  "number.growatt_inverter_solax_inverter_ems_charging_stop_soc": {
    "entity_id": "number.growatt_inverter_solax_inverter_ems_charging_stop_soc",
    "state": "100",
    "attributes": {
      "min": 11,
      "max": 100,
      "step": 1,
      "mode": "auto",
      "unit_of_measurement": "%",
      "icon": "mdi:battery",
      "friendly_name": "Growatt Inverter solax Inverter EMS Charging Stop SOC"
    }
  },
  "number.growatt_inverter_solax_inverter_ems_discharging_stop_soc_off_grid": {
    "entity_id": "number.growatt_inverter_solax_inverter_ems_discharging_stop_soc_off_grid",
    "state": "10",
    "attributes": {
      "min": 10,
      "max": 100,
      "step": 1,
      "mode": "auto",
      "unit_of_measurement": "%",
      "icon": "mdi:battery-10",
      "friendly_name": "Growatt Inverter solax Inverter EMS Discharging Stop SOC (off grid)"
    }
  },
  "select.growatt_inverter_solax_inverter_allow_grid_charge": {
    "entity_id": "select.growatt_inverter_solax_inverter_allow_grid_charge",
    "state": "Disabled",
    "attributes": {
      "options": [
        "Disabled",
        "Enabled"
      ],
      "icon": "mdi:battery-charging",
      "friendly_name": "Growatt Inverter solax Inverter Allow Grid Charge"
    }
  },
  "sensor.growatt_inverter_solax_pv_power_total": {
    "entity_id": "sensor.growatt_inverter_solax_pv_power_total",
    "state": "0.0",
    "attributes": {
      "state_class": "measurement",
      "ed_mapping_present": false,
      "unit_of_measurement": "W",
      "device_class": "power",
      "icon": "mdi:solar-power-variant",
      "friendly_name": "Growatt Inverter solax PV Power Total"
    }
  },
  "sensor.growatt_inverter_solax_total_import_power": {
    "entity_id": "sensor.growatt_inverter_solax_total_import_power",
    "state": "0.0",
    "attributes": {
      "state_class": "measurement",
      "ed_mapping_present": false,
      "unit_of_measurement": "W",
      "device_class": "power",
      "friendly_name": "Growatt Inverter solax Total Import Power"
    }
  },
  "sensor.growatt_inverter_solax_total_export_power": {
    "entity_id": "sensor.growatt_inverter_solax_total_export_power",
    "state": "0.0",
    "attributes": {
      "state_class": "measurement",
      "ed_mapping_present": false,
      "unit_of_measurement": "W",
      "device_class": "power",
      "friendly_name": "Growatt Inverter solax Total Export Power"
    }
  },
  "sensor.growatt_inverter_solax_total_load_power": {
    "entity_id": "sensor.growatt_inverter_solax_total_load_power",
    "state": "12777.0",
    "attributes": {
      "state_class": "measurement",
      "ed_mapping_present": false,
      "unit_of_measurement": "W",
      "device_class": "power",
      "friendly_name": "Growatt Inverter solax Total Load Power"
    }
  },
  "sensor.growatt_inverter_solax_battery_charge_power": {
    "entity_id": "sensor.growatt_inverter_solax_battery_charge_power",
    "state": "0.0",
    "attributes": {
      "state_class": "measurement",
      "ed_mapping_present": false,
      "unit_of_measurement": "W",
      "device_class": "power",
      "friendly_name": "Growatt Inverter solax Battery Charge Power"
    }
  },
  "sensor.growatt_inverter_solax_battery_discharge_power": {
    "entity_id": "sensor.growatt_inverter_solax_battery_discharge_power",
    "state": "6560.0",
    "attributes": {
      "state_class": "measurement",
      "ed_mapping_present": false,
      "unit_of_measurement": "W",
      "device_class": "power",
      "friendly_name": "Growatt Inverter solax Battery Discharge Power"
    }
  },
  "sensor.growatt_inverter_solax_grid_current_l1": {
    "entity_id": "sensor.growatt_inverter_solax_grid_current_l1",
    "state": "16.2",
    "attributes": {
      "ed_mapping_present": false,
      "unit_of_measurement": "A",
      "device_class": "current",
      "friendly_name": "Growatt Inverter solax Grid Current L1"
    }
  },
  "sensor.growatt_inverter_solax_grid_current_l2": {
    "entity_id": "sensor.growatt_inverter_solax_grid_current_l2",
    "state": "17.2",
    "attributes": {
      "ed_mapping_present": false,
      "unit_of_measurement": "A",
      "device_class": "current",
      "friendly_name": "Growatt Inverter solax Grid Current L2"
    }
  },
  "sensor.growatt_inverter_solax_grid_current_l3": {
    "entity_id": "sensor.growatt_inverter_solax_grid_current_l3",
    "state": "17.4",
    "attributes": {
      "ed_mapping_present": false,
      "unit_of_measurement": "A",
      "device_class": "current",
      "friendly_name": "Growatt Inverter solax Grid Current L3"
    }
  },
  "sensor.48h_average_grid_import_power": {
    "entity_id": "sensor.48h_average_grid_import_power",
    "state": "2230.13",
    "attributes": {
      "state_class": "measurement",
      "age_coverage_ratio": 0.77,
      "source_value_valid": true,
      "unit_of_measurement": "W",
      "device_class": "power",
      "icon": "mdi:calculator",
      "friendly_name": "48h Average Grid Import Power"
    }
  },
  "sensor.solcast_pv_forecast_forecast_today": {
    "entity_id": "sensor.solcast_pv_forecast_forecast_today",
    "state": "36.4096",
    "attributes": {
      "state_class": "total",
      "52dc_bd8b_3e19_71fc": 36.4096,
      "estimate_52dc_bd8b_3e19_71fc": 36.4096,
      "estimate10_52dc_bd8b_3e19_71fc": 15.4657,
      "estimate90_52dc_bd8b_3e19_71fc": 46.4348,
      "estimate": 36.4096,
      "estimate10": 15.4657,
      "estimate90": 46.4348,
      "dayname": "Saturday",
      "dataCorrect": true,
      "analysis": {
        "estimate10_kwh": 15.4657,
        "estimate90_kwh": 46.4348,
        "spread_kwh": 30.9691,
        "confidence": 0.3331,
        "intervals": [
          {
            "period_start": "2026-05-30T00:00:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-30T00:30:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-30T01:00:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-30T01:30:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-30T02:00:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-30T02:30:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-30T03:00:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-30T03:30:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-30T04:00:00+02:00",
            "spread_kwh": 0.0018,
            "confidence": 0.507
          },
          {
            "period_start": "2026-05-30T04:30:00+02:00",
            "spread_kwh": 0.0196,
            "confidence": 0.3531
          },
          {
            "period_start": "2026-05-30T05:00:00+02:00",
            "spread_kwh": 0.0362,
            "confidence": 0.4799
          },
          {
            "period_start": "2026-05-30T05:30:00+02:00",
            "spread_kwh": 0.0611,
            "confidence": 0.4719
          },
          {
            "period_start": "2026-05-30T06:00:00+02:00",
            "spread_kwh": 0.1517,
            "confidence": 0.3458
          },
          {
            "period_start": "2026-05-30T06:30:00+02:00",
            "spread_kwh": 0.2506,
            "confidence": 0.2814
          },
          {
            "period_start": "2026-05-30T07:00:00+02:00",
            "spread_kwh": 0.4482,
            "confidence": 0.2391
          },
          {
            "period_start": "2026-05-30T07:30:00+02:00",
            "spread_kwh": 0.6408,
            "confidence": 0.2565
          },
          {
            "period_start": "2026-05-30T08:00:00+02:00",
            "spread_kwh": 0.8655,
            "confidence": 0.2594
          },
          {
            "period_start": "2026-05-30T08:30:00+02:00",
            "spread_kwh": 1.0706,
            "confidence": 0.264
          },
          {
            "period_start": "2026-05-30T09:00:00+02:00",
            "spread_kwh": 1.243,
            "confidence": 0.2822
          },
          {
            "period_start": "2026-05-30T09:30:00+02:00",
            "spread_kwh": 1.3735,
            "confidence": 0.3138
          },
          {
            "period_start": "2026-05-30T10:00:00+02:00",
            "spread_kwh": 1.4724,
            "confidence": 0.3374
          },
          {
            "period_start": "2026-05-30T10:30:00+02:00",
            "spread_kwh": 1.553,
            "confidence": 0.3556
          },
          {
            "period_start": "2026-05-30T11:00:00+02:00",
            "spread_kwh": 1.5696,
            "confidence": 0.3846
          },
          {
            "period_start": "2026-05-30T11:30:00+02:00",
            "spread_kwh": 1.5259,
            "confidence": 0.428
          },
          {
            "period_start": "2026-05-30T12:00:00+02:00",
            "spread_kwh": 1.508,
            "confidence": 0.4502
          },
          {
            "period_start": "2026-05-30T12:30:00+02:00",
            "spread_kwh": 1.4775,
            "confidence": 0.4627
          },
          {
            "period_start": "2026-05-30T13:00:00+02:00",
            "spread_kwh": 1.5202,
            "confidence": 0.4472
          },
          {
            "period_start": "2026-05-30T13:30:00+02:00",
            "spread_kwh": 1.5994,
            "confidence": 0.4085
          },
          {
            "period_start": "2026-05-30T14:00:00+02:00",
            "spread_kwh": 1.6455,
            "confidence": 0.3718
          },
          {
            "period_start": "2026-05-30T14:30:00+02:00",
            "spread_kwh": 1.6275,
            "confidence": 0.3434
          },
          {
            "period_start": "2026-05-30T15:00:00+02:00",
            "spread_kwh": 1.5911,
            "confidence": 0.3136
          },
          {
            "period_start": "2026-05-30T15:30:00+02:00",
            "spread_kwh": 1.5133,
            "confidence": 0.2812
          },
          {
            "period_start": "2026-05-30T16:00:00+02:00",
            "spread_kwh": 1.4128,
            "confidence": 0.2485
          },
          {
            "period_start": "2026-05-30T16:30:00+02:00",
            "spread_kwh": 1.2624,
            "confidence": 0.2172
          },
          {
            "period_start": "2026-05-30T17:00:00+02:00",
            "spread_kwh": 1.1022,
            "confidence": 0.1707
          },
          {
            "period_start": "2026-05-30T17:30:00+02:00",
            "spread_kwh": 0.93,
            "confidence": 0.1072
          },
          {
            "period_start": "2026-05-30T18:00:00+02:00",
            "spread_kwh": 0.6643,
            "confidence": 0.0856
          },
          {
            "period_start": "2026-05-30T18:30:00+02:00",
            "spread_kwh": 0.4153,
            "confidence": 0.0846
          },
          {
            "period_start": "2026-05-30T19:00:00+02:00",
            "spread_kwh": 0.2107,
            "confidence": 0.1009
          },
          {
            "period_start": "2026-05-30T19:30:00+02:00",
            "spread_kwh": 0.0825,
            "confidence": 0.1406
          },
          {
            "period_start": "2026-05-30T20:00:00+02:00",
            "spread_kwh": 0.0646,
            "confidence": 0.0952
          },
          {
            "period_start": "2026-05-30T20:30:00+02:00",
            "spread_kwh": 0.0417,
            "confidence": 0.0754
          },
          {
            "period_start": "2026-05-30T21:00:00+02:00",
            "spread_kwh": 0.0167,
            "confidence": 0.0924
          },
          {
            "period_start": "2026-05-30T21:30:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-30T22:00:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-30T22:30:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-30T23:00:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-30T23:30:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          }
        ]
      },
      "detailedForecast": [
        {
          "period_start": "2026-05-30T00:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-30T00:30:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-30T01:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-30T01:30:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-30T02:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-30T02:30:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-30T03:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-30T03:30:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-30T04:00:00+02:00",
          "pv_estimate": 0.0036,
          "pv_estimate10": 0.0036,
          "pv_estimate90": 0.0071
        },
        {
          "period_start": "2026-05-30T04:30:00+02:00",
          "pv_estimate": 0.0356,
          "pv_estimate10": 0.0214,
          "pv_estimate90": 0.0606
        },
        {
          "period_start": "2026-05-30T05:00:00+02:00",
          "pv_estimate": 0.1233,
          "pv_estimate10": 0.0669,
          "pv_estimate90": 0.1394
        },
        {
          "period_start": "2026-05-30T05:30:00+02:00",
          "pv_estimate": 0.2204,
          "pv_estimate10": 0.1092,
          "pv_estimate90": 0.2314
        },
        {
          "period_start": "2026-05-30T06:00:00+02:00",
          "pv_estimate": 0.4415,
          "pv_estimate10": 0.1603,
          "pv_estimate90": 0.4636
        },
        {
          "period_start": "2026-05-30T06:30:00+02:00",
          "pv_estimate": 0.6394,
          "pv_estimate10": 0.1963,
          "pv_estimate90": 0.6975
        },
        {
          "period_start": "2026-05-30T07:00:00+02:00",
          "pv_estimate": 0.8832,
          "pv_estimate10": 0.2817,
          "pv_estimate90": 1.1781
        },
        {
          "period_start": "2026-05-30T07:30:00+02:00",
          "pv_estimate": 1.1925,
          "pv_estimate10": 0.442,
          "pv_estimate90": 1.7235
        },
        {
          "period_start": "2026-05-30T08:00:00+02:00",
          "pv_estimate": 1.5303,
          "pv_estimate10": 0.6063,
          "pv_estimate90": 2.3372
        },
        {
          "period_start": "2026-05-30T08:30:00+02:00",
          "pv_estimate": 1.901,
          "pv_estimate10": 0.7681,
          "pv_estimate90": 2.9093
        },
        {
          "period_start": "2026-05-30T09:00:00+02:00",
          "pv_estimate": 2.3431,
          "pv_estimate10": 0.9772,
          "pv_estimate90": 3.4632
        },
        {
          "period_start": "2026-05-30T09:30:00+02:00",
          "pv_estimate": 2.8663,
          "pv_estimate10": 1.2561,
          "pv_estimate90": 4.0031
        },
        {
          "period_start": "2026-05-30T10:00:00+02:00",
          "pv_estimate": 3.3411,
          "pv_estimate10": 1.4997,
          "pv_estimate90": 4.4444
        },
        {
          "period_start": "2026-05-30T10:30:00+02:00",
          "pv_estimate": 3.7692,
          "pv_estimate10": 1.7142,
          "pv_estimate90": 4.8201
        },
        {
          "period_start": "2026-05-30T11:00:00+02:00",
          "pv_estimate": 4.1739,
          "pv_estimate10": 1.962,
          "pv_estimate90": 5.1012
        },
        {
          "period_start": "2026-05-30T11:30:00+02:00",
          "pv_estimate": 4.5933,
          "pv_estimate10": 2.2837,
          "pv_estimate90": 5.3355
        },
        {
          "period_start": "2026-05-30T12:00:00+02:00",
          "pv_estimate": 4.8649,
          "pv_estimate10": 2.4702,
          "pv_estimate90": 5.4863
        },
        {
          "period_start": "2026-05-30T12:30:00+02:00",
          "pv_estimate": 4.9811,
          "pv_estimate10": 2.5449,
          "pv_estimate90": 5.5
        },
        {
          "period_start": "2026-05-30T13:00:00+02:00",
          "pv_estimate": 4.9328,
          "pv_estimate10": 2.4596,
          "pv_estimate90": 5.5
        },
        {
          "period_start": "2026-05-30T13:30:00+02:00",
          "pv_estimate": 4.7059,
          "pv_estimate10": 2.2094,
          "pv_estimate90": 5.4082
        },
        {
          "period_start": "2026-05-30T14:00:00+02:00",
          "pv_estimate": 4.4317,
          "pv_estimate10": 1.9475,
          "pv_estimate90": 5.2384
        },
        {
          "period_start": "2026-05-30T14:30:00+02:00",
          "pv_estimate": 4.0611,
          "pv_estimate10": 1.7021,
          "pv_estimate90": 4.957
        },
        {
          "period_start": "2026-05-30T15:00:00+02:00",
          "pv_estimate": 3.6404,
          "pv_estimate10": 1.4537,
          "pv_estimate90": 4.6359
        },
        {
          "period_start": "2026-05-30T15:30:00+02:00",
          "pv_estimate": 3.1405,
          "pv_estimate10": 1.1837,
          "pv_estimate90": 4.2102
        },
        {
          "period_start": "2026-05-30T16:00:00+02:00",
          "pv_estimate": 2.6546,
          "pv_estimate10": 0.9344,
          "pv_estimate90": 3.7601
        },
        {
          "period_start": "2026-05-30T16:30:00+02:00",
          "pv_estimate": 2.1684,
          "pv_estimate10": 0.7005,
          "pv_estimate90": 3.2253
        },
        {
          "period_start": "2026-05-30T17:00:00+02:00",
          "pv_estimate": 1.6883,
          "pv_estimate10": 0.4539,
          "pv_estimate90": 2.6583
        },
        {
          "period_start": "2026-05-30T17:30:00+02:00",
          "pv_estimate": 1.2518,
          "pv_estimate10": 0.2234,
          "pv_estimate90": 2.0835
        },
        {
          "period_start": "2026-05-30T18:00:00+02:00",
          "pv_estimate": 0.9035,
          "pv_estimate10": 0.1244,
          "pv_estimate90": 1.453
        },
        {
          "period_start": "2026-05-30T18:30:00+02:00",
          "pv_estimate": 0.6091,
          "pv_estimate10": 0.0768,
          "pv_estimate90": 0.9075
        },
        {
          "period_start": "2026-05-30T19:00:00+02:00",
          "pv_estimate": 0.3744,
          "pv_estimate10": 0.0473,
          "pv_estimate90": 0.4687
        },
        {
          "period_start": "2026-05-30T19:30:00+02:00",
          "pv_estimate": 0.1789,
          "pv_estimate10": 0.027,
          "pv_estimate90": 0.1921
        },
        {
          "period_start": "2026-05-30T20:00:00+02:00",
          "pv_estimate": 0.1023,
          "pv_estimate10": 0.0136,
          "pv_estimate90": 0.1429
        },
        {
          "period_start": "2026-05-30T20:30:00+02:00",
          "pv_estimate": 0.0546,
          "pv_estimate10": 0.0068,
          "pv_estimate90": 0.0902
        },
        {
          "period_start": "2026-05-30T21:00:00+02:00",
          "pv_estimate": 0.0172,
          "pv_estimate10": 0.0034,
          "pv_estimate90": 0.0368
        },
        {
          "period_start": "2026-05-30T21:30:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-30T22:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-30T22:30:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-30T23:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-30T23:30:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        }
      ],
      "detailedHourly": [
        {
          "period_start": "2026-05-30T00:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-30T01:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-30T02:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-30T03:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-30T04:00:00+02:00",
          "pv_estimate": 0.0196,
          "pv_estimate10": 0.0125,
          "pv_estimate90": 0.0338
        },
        {
          "period_start": "2026-05-30T05:00:00+02:00",
          "pv_estimate": 0.1719,
          "pv_estimate10": 0.0881,
          "pv_estimate90": 0.1854
        },
        {
          "period_start": "2026-05-30T06:00:00+02:00",
          "pv_estimate": 0.5404,
          "pv_estimate10": 0.1783,
          "pv_estimate90": 0.5806
        },
        {
          "period_start": "2026-05-30T07:00:00+02:00",
          "pv_estimate": 1.0378,
          "pv_estimate10": 0.3619,
          "pv_estimate90": 1.4508
        },
        {
          "period_start": "2026-05-30T08:00:00+02:00",
          "pv_estimate": 1.7157,
          "pv_estimate10": 0.6872,
          "pv_estimate90": 2.6233
        },
        {
          "period_start": "2026-05-30T09:00:00+02:00",
          "pv_estimate": 2.6047,
          "pv_estimate10": 1.1166,
          "pv_estimate90": 3.7332
        },
        {
          "period_start": "2026-05-30T10:00:00+02:00",
          "pv_estimate": 3.5552,
          "pv_estimate10": 1.6069,
          "pv_estimate90": 4.6322
        },
        {
          "period_start": "2026-05-30T11:00:00+02:00",
          "pv_estimate": 4.3836,
          "pv_estimate10": 2.1229,
          "pv_estimate90": 5.2184
        },
        {
          "period_start": "2026-05-30T12:00:00+02:00",
          "pv_estimate": 4.923,
          "pv_estimate10": 2.5076,
          "pv_estimate90": 5.4931
        },
        {
          "period_start": "2026-05-30T13:00:00+02:00",
          "pv_estimate": 4.8194,
          "pv_estimate10": 2.3345,
          "pv_estimate90": 5.4541
        },
        {
          "period_start": "2026-05-30T14:00:00+02:00",
          "pv_estimate": 4.2464,
          "pv_estimate10": 1.8248,
          "pv_estimate90": 5.0977
        },
        {
          "period_start": "2026-05-30T15:00:00+02:00",
          "pv_estimate": 3.3904,
          "pv_estimate10": 1.3187,
          "pv_estimate90": 4.423
        },
        {
          "period_start": "2026-05-30T16:00:00+02:00",
          "pv_estimate": 2.4115,
          "pv_estimate10": 0.8175,
          "pv_estimate90": 3.4927
        },
        {
          "period_start": "2026-05-30T17:00:00+02:00",
          "pv_estimate": 1.4701,
          "pv_estimate10": 0.3387,
          "pv_estimate90": 2.3709
        },
        {
          "period_start": "2026-05-30T18:00:00+02:00",
          "pv_estimate": 0.7563,
          "pv_estimate10": 0.1006,
          "pv_estimate90": 1.1803
        },
        {
          "period_start": "2026-05-30T19:00:00+02:00",
          "pv_estimate": 0.2767,
          "pv_estimate10": 0.0372,
          "pv_estimate90": 0.3304
        },
        {
          "period_start": "2026-05-30T20:00:00+02:00",
          "pv_estimate": 0.0785,
          "pv_estimate10": 0.0102,
          "pv_estimate90": 0.1166
        },
        {
          "period_start": "2026-05-30T21:00:00+02:00",
          "pv_estimate": 0.0086,
          "pv_estimate10": 0.0017,
          "pv_estimate90": 0.0184
        },
        {
          "period_start": "2026-05-30T22:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-30T23:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        }
      ],
      "unit_of_measurement": "kWh",
      "attribution": "Data retrieved from Solcast",
      "device_class": "energy",
      "friendly_name": "Solcast PV Forecast Forecast Today"
    }
  },
  "sensor.solcast_pv_forecast_forecast_tomorrow": {
    "entity_id": "sensor.solcast_pv_forecast_forecast_tomorrow",
    "state": "43.504",
    "attributes": {
      "state_class": "total",
      "52dc_bd8b_3e19_71fc": 43.504,
      "estimate_52dc_bd8b_3e19_71fc": 43.504,
      "estimate10_52dc_bd8b_3e19_71fc": 21.0083,
      "estimate90_52dc_bd8b_3e19_71fc": 47.3469,
      "estimate": 43.504,
      "estimate10": 21.0083,
      "estimate90": 47.3469,
      "dayname": "Sunday",
      "dataCorrect": true,
      "analysis": {
        "estimate10_kwh": 21.0083,
        "estimate90_kwh": 47.3469,
        "spread_kwh": 26.3386,
        "confidence": 0.4437,
        "intervals": [
          {
            "period_start": "2026-05-31T00:00:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-31T00:30:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-31T01:00:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-31T01:30:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-31T02:00:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-31T02:30:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-31T03:00:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-31T03:30:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-31T04:00:00+02:00",
            "spread_kwh": 0.0036,
            "confidence": 0.3333
          },
          {
            "period_start": "2026-05-31T04:30:00+02:00",
            "spread_kwh": 0.027,
            "confidence": 0.2503
          },
          {
            "period_start": "2026-05-31T05:00:00+02:00",
            "spread_kwh": 0.0629,
            "confidence": 0.2711
          },
          {
            "period_start": "2026-05-31T05:30:00+02:00",
            "spread_kwh": 0.1011,
            "confidence": 0.3223
          },
          {
            "period_start": "2026-05-31T06:00:00+02:00",
            "spread_kwh": 0.1366,
            "confidence": 0.3824
          },
          {
            "period_start": "2026-05-31T06:30:00+02:00",
            "spread_kwh": 0.2407,
            "confidence": 0.3838
          },
          {
            "period_start": "2026-05-31T07:00:00+02:00",
            "spread_kwh": 0.3737,
            "confidence": 0.3979
          },
          {
            "period_start": "2026-05-31T07:30:00+02:00",
            "spread_kwh": 0.5427,
            "confidence": 0.4103
          },
          {
            "period_start": "2026-05-31T08:00:00+02:00",
            "spread_kwh": 0.6996,
            "confidence": 0.4241
          },
          {
            "period_start": "2026-05-31T08:30:00+02:00",
            "spread_kwh": 0.8493,
            "confidence": 0.4381
          },
          {
            "period_start": "2026-05-31T09:00:00+02:00",
            "spread_kwh": 0.9706,
            "confidence": 0.4543
          },
          {
            "period_start": "2026-05-31T09:30:00+02:00",
            "spread_kwh": 1.0841,
            "confidence": 0.467
          },
          {
            "period_start": "2026-05-31T10:00:00+02:00",
            "spread_kwh": 1.1454,
            "confidence": 0.4857
          },
          {
            "period_start": "2026-05-31T10:30:00+02:00",
            "spread_kwh": 1.2055,
            "confidence": 0.5002
          },
          {
            "period_start": "2026-05-31T11:00:00+02:00",
            "spread_kwh": 1.2721,
            "confidence": 0.5025
          },
          {
            "period_start": "2026-05-31T11:30:00+02:00",
            "spread_kwh": 1.3354,
            "confidence": 0.4978
          },
          {
            "period_start": "2026-05-31T12:00:00+02:00",
            "spread_kwh": 1.3569,
            "confidence": 0.4968
          },
          {
            "period_start": "2026-05-31T12:30:00+02:00",
            "spread_kwh": 1.3876,
            "confidence": 0.4946
          },
          {
            "period_start": "2026-05-31T13:00:00+02:00",
            "spread_kwh": 1.3824,
            "confidence": 0.4971
          },
          {
            "period_start": "2026-05-31T13:30:00+02:00",
            "spread_kwh": 1.3479,
            "confidence": 0.5038
          },
          {
            "period_start": "2026-05-31T14:00:00+02:00",
            "spread_kwh": 1.3872,
            "confidence": 0.4743
          },
          {
            "period_start": "2026-05-31T14:30:00+02:00",
            "spread_kwh": 1.4888,
            "confidence": 0.4097
          },
          {
            "period_start": "2026-05-31T15:00:00+02:00",
            "spread_kwh": 1.495,
            "confidence": 0.3686
          },
          {
            "period_start": "2026-05-31T15:30:00+02:00",
            "spread_kwh": 1.3982,
            "confidence": 0.3538
          },
          {
            "period_start": "2026-05-31T16:00:00+02:00",
            "spread_kwh": 1.2531,
            "confidence": 0.3498
          },
          {
            "period_start": "2026-05-31T16:30:00+02:00",
            "spread_kwh": 1.0886,
            "confidence": 0.3519
          },
          {
            "period_start": "2026-05-31T17:00:00+02:00",
            "spread_kwh": 0.9007,
            "confidence": 0.3532
          },
          {
            "period_start": "2026-05-31T17:30:00+02:00",
            "spread_kwh": 0.7066,
            "confidence": 0.3565
          },
          {
            "period_start": "2026-05-31T18:00:00+02:00",
            "spread_kwh": 0.4786,
            "confidence": 0.3774
          },
          {
            "period_start": "2026-05-31T18:30:00+02:00",
            "spread_kwh": 0.2637,
            "confidence": 0.4241
          },
          {
            "period_start": "2026-05-31T19:00:00+02:00",
            "spread_kwh": 0.1646,
            "confidence": 0.4106
          },
          {
            "period_start": "2026-05-31T19:30:00+02:00",
            "spread_kwh": 0.0764,
            "confidence": 0.4689
          },
          {
            "period_start": "2026-05-31T20:00:00+02:00",
            "spread_kwh": 0.0553,
            "confidence": 0.4043
          },
          {
            "period_start": "2026-05-31T20:30:00+02:00",
            "spread_kwh": 0.0401,
            "confidence": 0.3206
          },
          {
            "period_start": "2026-05-31T21:00:00+02:00",
            "spread_kwh": 0.0169,
            "confidence": 0.292
          },
          {
            "period_start": "2026-05-31T21:30:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-31T22:00:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-31T22:30:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-31T23:00:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          },
          {
            "period_start": "2026-05-31T23:30:00+02:00",
            "spread_kwh": 0.0,
            "confidence": 1.0
          }
        ]
      },
      "detailedForecast": [
        {
          "period_start": "2026-05-31T00:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-31T00:30:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-31T01:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-31T01:30:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-31T02:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-31T02:30:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-31T03:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-31T03:30:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-31T04:00:00+02:00",
          "pv_estimate": 0.0072,
          "pv_estimate10": 0.0036,
          "pv_estimate90": 0.0108
        },
        {
          "period_start": "2026-05-31T04:30:00+02:00",
          "pv_estimate": 0.0685,
          "pv_estimate10": 0.018,
          "pv_estimate90": 0.0719
        },
        {
          "period_start": "2026-05-31T05:00:00+02:00",
          "pv_estimate": 0.1644,
          "pv_estimate10": 0.0468,
          "pv_estimate90": 0.1726
        },
        {
          "period_start": "2026-05-31T05:30:00+02:00",
          "pv_estimate": 0.2843,
          "pv_estimate10": 0.0962,
          "pv_estimate90": 0.2985
        },
        {
          "period_start": "2026-05-31T06:00:00+02:00",
          "pv_estimate": 0.4211,
          "pv_estimate10": 0.1691,
          "pv_estimate90": 0.4422
        },
        {
          "period_start": "2026-05-31T06:30:00+02:00",
          "pv_estimate": 0.7439,
          "pv_estimate10": 0.2998,
          "pv_estimate90": 0.7811
        },
        {
          "period_start": "2026-05-31T07:00:00+02:00",
          "pv_estimate": 1.1395,
          "pv_estimate10": 0.4938,
          "pv_estimate90": 1.2411
        },
        {
          "period_start": "2026-05-31T07:30:00+02:00",
          "pv_estimate": 1.626,
          "pv_estimate10": 0.7552,
          "pv_estimate90": 1.8406
        },
        {
          "period_start": "2026-05-31T08:00:00+02:00",
          "pv_estimate": 2.1557,
          "pv_estimate10": 1.0304,
          "pv_estimate90": 2.4296
        },
        {
          "period_start": "2026-05-31T08:30:00+02:00",
          "pv_estimate": 2.7216,
          "pv_estimate10": 1.3243,
          "pv_estimate90": 3.0228
        },
        {
          "period_start": "2026-05-31T09:00:00+02:00",
          "pv_estimate": 3.2726,
          "pv_estimate10": 1.616,
          "pv_estimate90": 3.5571
        },
        {
          "period_start": "2026-05-31T09:30:00+02:00",
          "pv_estimate": 3.8221,
          "pv_estimate10": 1.8995,
          "pv_estimate90": 4.0677
        },
        {
          "period_start": "2026-05-31T10:00:00+02:00",
          "pv_estimate": 4.2559,
          "pv_estimate10": 2.1639,
          "pv_estimate90": 4.4548
        },
        {
          "period_start": "2026-05-31T10:30:00+02:00",
          "pv_estimate": 4.6687,
          "pv_estimate10": 2.413,
          "pv_estimate90": 4.8239
        },
        {
          "period_start": "2026-05-31T11:00:00+02:00",
          "pv_estimate": 4.9641,
          "pv_estimate10": 2.5697,
          "pv_estimate90": 5.1139
        },
        {
          "period_start": "2026-05-31T11:30:00+02:00",
          "pv_estimate": 5.1299,
          "pv_estimate10": 2.6478,
          "pv_estimate90": 5.3185
        },
        {
          "period_start": "2026-05-31T12:00:00+02:00",
          "pv_estimate": 5.1949,
          "pv_estimate10": 2.6799,
          "pv_estimate90": 5.3938
        },
        {
          "period_start": "2026-05-31T12:30:00+02:00",
          "pv_estimate": 5.2804,
          "pv_estimate10": 2.7161,
          "pv_estimate90": 5.4912
        },
        {
          "period_start": "2026-05-31T13:00:00+02:00",
          "pv_estimate": 5.3015,
          "pv_estimate10": 2.7334,
          "pv_estimate90": 5.4982
        },
        {
          "period_start": "2026-05-31T13:30:00+02:00",
          "pv_estimate": 5.2738,
          "pv_estimate10": 2.7372,
          "pv_estimate90": 5.433
        },
        {
          "period_start": "2026-05-31T14:00:00+02:00",
          "pv_estimate": 4.9731,
          "pv_estimate10": 2.5034,
          "pv_estimate90": 5.2779
        },
        {
          "period_start": "2026-05-31T14:30:00+02:00",
          "pv_estimate": 4.4663,
          "pv_estimate10": 2.0667,
          "pv_estimate90": 5.0443
        },
        {
          "period_start": "2026-05-31T15:00:00+02:00",
          "pv_estimate": 4.0179,
          "pv_estimate10": 1.7452,
          "pv_estimate90": 4.7353
        },
        {
          "period_start": "2026-05-31T15:30:00+02:00",
          "pv_estimate": 3.5782,
          "pv_estimate10": 1.5312,
          "pv_estimate90": 4.3276
        },
        {
          "period_start": "2026-05-31T16:00:00+02:00",
          "pv_estimate": 3.1595,
          "pv_estimate10": 1.3483,
          "pv_estimate90": 3.8545
        },
        {
          "period_start": "2026-05-31T16:30:00+02:00",
          "pv_estimate": 2.7662,
          "pv_estimate10": 1.1821,
          "pv_estimate90": 3.3593
        },
        {
          "period_start": "2026-05-31T17:00:00+02:00",
          "pv_estimate": 2.3102,
          "pv_estimate10": 0.9835,
          "pv_estimate90": 2.7849
        },
        {
          "period_start": "2026-05-31T17:30:00+02:00",
          "pv_estimate": 1.8488,
          "pv_estimate10": 0.7828,
          "pv_estimate90": 2.1959
        },
        {
          "period_start": "2026-05-31T18:00:00+02:00",
          "pv_estimate": 1.349,
          "pv_estimate10": 0.5802,
          "pv_estimate90": 1.5374
        },
        {
          "period_start": "2026-05-31T18:30:00+02:00",
          "pv_estimate": 0.9022,
          "pv_estimate10": 0.3884,
          "pv_estimate90": 0.9158
        },
        {
          "period_start": "2026-05-31T19:00:00+02:00",
          "pv_estimate": 0.5318,
          "pv_estimate10": 0.2293,
          "pv_estimate90": 0.5584
        },
        {
          "period_start": "2026-05-31T19:30:00+02:00",
          "pv_estimate": 0.2742,
          "pv_estimate10": 0.135,
          "pv_estimate90": 0.2879
        },
        {
          "period_start": "2026-05-31T20:00:00+02:00",
          "pv_estimate": 0.1767,
          "pv_estimate10": 0.075,
          "pv_estimate90": 0.1855
        },
        {
          "period_start": "2026-05-31T20:30:00+02:00",
          "pv_estimate": 0.1126,
          "pv_estimate10": 0.0379,
          "pv_estimate90": 0.1182
        },
        {
          "period_start": "2026-05-31T21:00:00+02:00",
          "pv_estimate": 0.0453,
          "pv_estimate10": 0.0139,
          "pv_estimate90": 0.0476
        },
        {
          "period_start": "2026-05-31T21:30:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-31T22:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-31T22:30:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-31T23:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-31T23:30:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        }
      ],
      "detailedHourly": [
        {
          "period_start": "2026-05-31T00:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-31T01:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-31T02:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-31T03:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-31T04:00:00+02:00",
          "pv_estimate": 0.0379,
          "pv_estimate10": 0.0108,
          "pv_estimate90": 0.0414
        },
        {
          "period_start": "2026-05-31T05:00:00+02:00",
          "pv_estimate": 0.2243,
          "pv_estimate10": 0.0715,
          "pv_estimate90": 0.2355
        },
        {
          "period_start": "2026-05-31T06:00:00+02:00",
          "pv_estimate": 0.5825,
          "pv_estimate10": 0.2344,
          "pv_estimate90": 0.6117
        },
        {
          "period_start": "2026-05-31T07:00:00+02:00",
          "pv_estimate": 1.3827,
          "pv_estimate10": 0.6245,
          "pv_estimate90": 1.5409
        },
        {
          "period_start": "2026-05-31T08:00:00+02:00",
          "pv_estimate": 2.4386,
          "pv_estimate10": 1.1774,
          "pv_estimate90": 2.7262
        },
        {
          "period_start": "2026-05-31T09:00:00+02:00",
          "pv_estimate": 3.5473,
          "pv_estimate10": 1.7578,
          "pv_estimate90": 3.8124
        },
        {
          "period_start": "2026-05-31T10:00:00+02:00",
          "pv_estimate": 4.4623,
          "pv_estimate10": 2.2885,
          "pv_estimate90": 4.6394
        },
        {
          "period_start": "2026-05-31T11:00:00+02:00",
          "pv_estimate": 5.047,
          "pv_estimate10": 2.6088,
          "pv_estimate90": 5.2162
        },
        {
          "period_start": "2026-05-31T12:00:00+02:00",
          "pv_estimate": 5.2377,
          "pv_estimate10": 2.698,
          "pv_estimate90": 5.4425
        },
        {
          "period_start": "2026-05-31T13:00:00+02:00",
          "pv_estimate": 5.2876,
          "pv_estimate10": 2.7353,
          "pv_estimate90": 5.4656
        },
        {
          "period_start": "2026-05-31T14:00:00+02:00",
          "pv_estimate": 4.7197,
          "pv_estimate10": 2.2851,
          "pv_estimate90": 5.1611
        },
        {
          "period_start": "2026-05-31T15:00:00+02:00",
          "pv_estimate": 3.798,
          "pv_estimate10": 1.6382,
          "pv_estimate90": 4.5314
        },
        {
          "period_start": "2026-05-31T16:00:00+02:00",
          "pv_estimate": 2.9628,
          "pv_estimate10": 1.2652,
          "pv_estimate90": 3.6069
        },
        {
          "period_start": "2026-05-31T17:00:00+02:00",
          "pv_estimate": 2.0795,
          "pv_estimate10": 0.8832,
          "pv_estimate90": 2.4904
        },
        {
          "period_start": "2026-05-31T18:00:00+02:00",
          "pv_estimate": 1.1256,
          "pv_estimate10": 0.4843,
          "pv_estimate90": 1.2266
        },
        {
          "period_start": "2026-05-31T19:00:00+02:00",
          "pv_estimate": 0.403,
          "pv_estimate10": 0.1822,
          "pv_estimate90": 0.4232
        },
        {
          "period_start": "2026-05-31T20:00:00+02:00",
          "pv_estimate": 0.1447,
          "pv_estimate10": 0.0565,
          "pv_estimate90": 0.1518
        },
        {
          "period_start": "2026-05-31T21:00:00+02:00",
          "pv_estimate": 0.0226,
          "pv_estimate10": 0.0069,
          "pv_estimate90": 0.0238
        },
        {
          "period_start": "2026-05-31T22:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        },
        {
          "period_start": "2026-05-31T23:00:00+02:00",
          "pv_estimate": 0.0,
          "pv_estimate10": 0.0,
          "pv_estimate90": 0.0
        }
      ],
      "unit_of_measurement": "kWh",
      "attribution": "Data retrieved from Solcast",
      "device_class": "energy",
      "friendly_name": "Solcast PV Forecast Forecast Tomorrow"
    }
  },
  "sensor.growatt_inverter_solax_total_battery_input_energy": {
    "entity_id": "sensor.growatt_inverter_solax_total_battery_input_energy",
    "state": "4580.0",
    "attributes": {
      "state_class": "total_increasing",
      "ed_mapping_present": false,
      "unit_of_measurement": "kWh",
      "device_class": "energy",
      "icon": "mdi:battery-arrow-up",
      "friendly_name": "Growatt Inverter solax Total Battery Input Energy"
    }
  },
  "sensor.growatt_inverter_solax_total_battery_output_energy": {
    "entity_id": "sensor.growatt_inverter_solax_total_battery_output_energy",
    "state": "4586.9",
    "attributes": {
      "state_class": "total_increasing",
      "ed_mapping_present": false,
      "unit_of_measurement": "kWh",
      "device_class": "energy",
      "icon": "mdi:battery-arrow-down",
      "friendly_name": "Growatt Inverter solax Total Battery Output Energy"
    }
  },
  "sensor.growatt_inverter_solax_total_solar_energy": {
    "entity_id": "sensor.growatt_inverter_solax_total_solar_energy",
    "state": "3055.3",
    "attributes": {
      "state_class": "total_increasing",
      "ed_mapping_present": false,
      "unit_of_measurement": "kWh",
      "device_class": "energy",
      "icon": "mdi:solar-power",
      "friendly_name": "Growatt Inverter solax Total Solar Energy"
    }
  },
  "sensor.growatt_inverter_solax_total_grid_import": {
    "entity_id": "sensor.growatt_inverter_solax_total_grid_import",
    "state": "15014.4",
    "attributes": {
      "state_class": "total_increasing",
      "ed_mapping_present": false,
      "unit_of_measurement": "kWh",
      "device_class": "energy",
      "icon": "mdi:home-import-outline",
      "friendly_name": "Growatt Inverter solax Total Grid Import"
    }
  },
  "sensor.growatt_inverter_solax_total_grid_export": {
    "entity_id": "sensor.growatt_inverter_solax_total_grid_export",
    "state": "542.9",
    "attributes": {
      "state_class": "total_increasing",
      "ed_mapping_present": false,
      "unit_of_measurement": "kWh",
      "device_class": "energy",
      "icon": "mdi:home-export-outline",
      "friendly_name": "Growatt Inverter solax Total Grid Export"
    }
  },
  "sensor.growatt_inverter_solax_total_load_energy": {
    "entity_id": "sensor.growatt_inverter_solax_total_load_energy",
    "state": "17533.7",
    "attributes": {
      "state_class": "total_increasing",
      "ed_mapping_present": false,
      "unit_of_measurement": "kWh",
      "device_class": "energy",
      "friendly_name": "Growatt Inverter solax Total Load Energy"
    }
  },
  "sensor.growatt_inverter_solax_total_power_generation": {
    "entity_id": "sensor.growatt_inverter_solax_total_power_generation",
    "state": "3934.3",
    "attributes": {
      "state_class": "total_increasing",
      "ed_mapping_present": false,
      "unit_of_measurement": "kWh",
      "device_class": "energy",
      "icon": "mdi:solar-power",
      "friendly_name": "Growatt Inverter solax Total Power Generation"
    }
  },
  "input_boolean.bess_discharge_inhibit": {
    "entity_id": "input_boolean.bess_discharge_inhibit",
    "state": "off",
    "attributes": {
      "editable": true,
      "icon": "mdi:battery-charging-outline",
      "friendly_name": "BESS Discharge Inhibit is charging"
    }
  }
}
```

</details>

## Inverter TOU Segments

**Segments in Hardware**: 1

```json
[
  {
    "segment_id": 1,
    "batt_mode": "battery_first",
    "start_time": "00:00",
    "end_time": "23:59",
    "enabled": true
  }
]
```

## Historical Sensor Data

**Total Periods**: 96

**Periods with Data**: 18

| Per | Time  | Src    | Intent           | Observed         | SOE kWh | Solar | Import | Savings |
|-----|-------|--------|------------------|------------------|---------|-------|--------|---------|
|   0 | 04:32 | actual | IDLE             | LOAD_SUPPORT     | 29.0→29.0 |  0.00 |   0.00 |  1.0639 |
|   1 | 04:32 | actual | IDLE             | LOAD_SUPPORT     | 29.0→28.5 |  0.00 |   0.00 |  1.2951 |
|   2 | 04:32 | actual | IDLE             | IDLE             | 28.5→28.5 |  0.00 |   0.00 |  0.2535 |
|   3 | 04:32 | actual | IDLE             | LOAD_SUPPORT     | 28.5→28.0 |  0.00 |   0.00 |  0.7358 |
|   4 | 04:32 | actual | IDLE             | LOAD_SUPPORT     | 28.0→27.5 |  0.00 |   0.00 |  1.1312 |
|   5 | 04:32 | actual | IDLE             | LOAD_SUPPORT     | 27.5→27.5 |  0.00 |   0.00 |  0.7350 |
|   6 | 04:32 | actual | IDLE             | LOAD_SUPPORT     | 27.5→27.0 |  0.00 |   0.00 |  0.2485 |
|   7 | 04:32 | actual | IDLE             | LOAD_SUPPORT     | 27.0→27.0 |  0.00 |   0.00 |  1.2316 |
|   8 | 04:32 | actual | IDLE             | LOAD_SUPPORT     | 27.0→26.5 |  0.00 |   0.00 |  0.7277 |
|   9 | 04:32 | actual | IDLE             | LOAD_SUPPORT     | 26.5→26.0 |  0.00 |   0.00 |  0.2430 |
|  10 | 04:32 | actual | IDLE             | LOAD_SUPPORT     | 26.0→26.0 |  0.00 |   0.00 |  1.4611 |
|  11 | 04:32 | actual | IDLE             | LOAD_SUPPORT     | 26.0→26.0 |  0.00 |   0.00 |  0.4788 |
|  12 | 04:32 | actual | IDLE             | LOAD_SUPPORT     | 26.0→25.5 |  0.00 |   0.00 |  0.4677 |
|  13 | 04:32 | actual | IDLE             | LOAD_SUPPORT     | 25.5→25.0 |  0.00 |   0.00 |  1.1746 |
|  14 | 04:32 | actual | IDLE             | LOAD_SUPPORT     | 25.0→22.0 |  0.00 |   0.00 |  6.9061 |
|  15 | 04:32 | actual | IDLE             | LOAD_SUPPORT     | 22.0→19.0 |  0.00 |   0.00 |  7.3081 |
|  16 | 04:32 | actual | IDLE             | LOAD_SUPPORT     | 19.0→15.5 |  0.00 |   0.00 |  9.0438 |
|  17 | 04:32 | actual | IDLE             | LOAD_SUPPORT     | 15.5→11.5 |  0.00 |   0.00 |  9.9911 |
<details>
<summary>Full Historical Data JSON (needed for mock HA replay)</summary>

```json
[
  {
    "period": 0,
    "energy": {
      "solar_production": 0.0,
      "home_consumption": 0.4000000000005457,
      "battery_charged": 0.0,
      "battery_discharged": 0.4000000000005457,
      "grid_imported": 0.0,
      "grid_exported": 0.0,
      "battery_soe_start": 28.999999999999996,
      "battery_soe_end": 28.999999999999996,
      "solar_to_home": 0.0,
      "solar_to_battery": 0.0,
      "solar_to_grid": 0,
      "grid_to_home": 0.0,
      "grid_to_battery": 0,
      "battery_to_home": 0.4000000000005457,
      "battery_to_grid": 0.0
    },
    "timestamp": "2026-05-30 04:32:17.927074+02:00",
    "data_source": "actual",
    "economic": {
      "buy_price": 2.6597500000000003,
      "sell_price": 1.6282,
      "grid_cost": 0.0,
      "battery_cycle_cost": 0.0,
      "hourly_cost": 0.0,
      "grid_only_cost": 1.0639000000014516,
      "solar_only_cost": 1.0639000000014516,
      "hourly_savings": 1.0639000000014516,
      "solar_savings": 0.0
    },
    "decision": {
      "strategic_intent": "IDLE",
      "observed_intent": "LOAD_SUPPORT",
      "battery_action": null,
      "cost_basis": 0.0,
      "pattern_name": "",
      "description": "",
      "economic_chain": "",
      "immediate_value": 0.0,
      "future_value": 0.0,
      "net_strategy_value": 0.0,
      "advanced_flow_pattern": "",
      "detailed_flow_values": {},
      "future_target_hours": []
    }
  },
  {
    "period": 1,
    "energy": {
      "solar_production": 0.0,
      "home_consumption": 0.5,
      "battery_charged": 0.0,
      "battery_discharged": 0.5,
      "grid_imported": 0.0,
      "grid_exported": 0.0,
      "battery_soe_start": 28.999999999999996,
      "battery_soe_end": 28.499999999999996,
      "solar_to_home": 0.0,
      "solar_to_battery": 0.0,
      "solar_to_grid": 0,
      "grid_to_home": 0.0,
      "grid_to_battery": 0,
      "battery_to_home": 0.5,
      "battery_to_grid": 0.0
    },
    "timestamp": "2026-05-30 04:32:17.928265+02:00",
    "data_source": "actual",
    "economic": {
      "buy_price": 2.5901625000000004,
      "sell_price": 1.5725300000000002,
      "grid_cost": 0.0,
      "battery_cycle_cost": 0.0,
      "hourly_cost": 0.0,
      "grid_only_cost": 1.2950812500000002,
      "solar_only_cost": 1.2950812500000002,
      "hourly_savings": 1.2950812500000002,
      "solar_savings": 0.0
    },
    "decision": {
      "strategic_intent": "IDLE",
      "observed_intent": "LOAD_SUPPORT",
      "battery_action": null,
      "cost_basis": 0.0,
      "pattern_name": "",
      "description": "",
      "economic_chain": "",
      "immediate_value": 0.0,
      "future_value": 0.0,
      "net_strategy_value": 0.0,
      "advanced_flow_pattern": "",
      "detailed_flow_values": {},
      "future_target_hours": []
    }
  },
  {
    "period": 2,
    "energy": {
      "solar_production": 0.0,
      "home_consumption": 0.0999999999994543,
      "battery_charged": 0.0,
      "battery_discharged": 0.0999999999994543,
      "grid_imported": 0.0,
      "grid_exported": 0.0,
      "battery_soe_start": 28.499999999999996,
      "battery_soe_end": 28.499999999999996,
      "solar_to_home": 0.0,
      "solar_to_battery": 0.0,
      "solar_to_grid": 0,
      "grid_to_home": 0.0,
      "grid_to_battery": 0,
      "battery_to_home": 0.0999999999994543,
      "battery_to_grid": 0.0
    },
    "timestamp": "2026-05-30 04:32:17.928751+02:00",
    "data_source": "actual",
    "economic": {
      "buy_price": 2.5347125,
      "sell_price": 1.52817,
      "grid_cost": 0.0,
      "battery_cycle_cost": 0.0,
      "hourly_cost": 0.0,
      "grid_only_cost": 0.2534712499986168,
      "solar_only_cost": 0.2534712499986168,
      "hourly_savings": 0.2534712499986168,
      "solar_savings": 0.0
    },
    "decision": {
      "strategic_intent": "IDLE",
      "observed_intent": "IDLE",
      "battery_action": null,
      "cost_basis": 0.0,
      "pattern_name": "",
      "description": "",
      "economic_chain": "",
      "immediate_value": 0.0,
      "future_value": 0.0,
      "net_strategy_value": 0.0,
      "advanced_flow_pattern": "",
      "detailed_flow_values": {},
      "future_target_hours": []
    }
  },
  {
    "period": 3,
    "energy": {
      "solar_production": 0.0,
      "home_consumption": 0.3000000000001819,
      "battery_charged": 0.0,
      "battery_discharged": 0.3000000000001819,
      "grid_imported": 0.0,
      "grid_exported": 0.0,
      "battery_soe_start": 28.499999999999996,
      "battery_soe_end": 28.000000000000004,
      "solar_to_home": 0.0,
      "solar_to_battery": 0.0,
      "solar_to_grid": 0,
      "grid_to_home": 0.0,
      "grid_to_battery": 0,
      "battery_to_home": 0.3000000000001819,
      "battery_to_grid": 0.0
    },
    "timestamp": "2026-05-30 04:32:17.929204+02:00",
    "data_source": "actual",
    "economic": {
      "buy_price": 2.4526000000000003,
      "sell_price": 1.4624800000000002,
      "grid_cost": 0.0,
      "battery_cycle_cost": 0.0,
      "hourly_cost": 0.0,
      "grid_only_cost": 0.7357800000004462,
      "solar_only_cost": 0.7357800000004462,
      "hourly_savings": 0.7357800000004462,
      "solar_savings": 0.0
    },
    "decision": {
      "strategic_intent": "IDLE",
      "observed_intent": "LOAD_SUPPORT",
      "battery_action": null,
      "cost_basis": 0.0,
      "pattern_name": "",
      "description": "",
      "economic_chain": "",
      "immediate_value": 0.0,
      "future_value": 0.0,
      "net_strategy_value": 0.0,
      "advanced_flow_pattern": "",
      "detailed_flow_values": {},
      "future_target_hours": []
    }
  },
  {
    "period": 4,
    "energy": {
      "solar_production": 0.0,
      "home_consumption": 0.40000000000009095,
      "battery_charged": 0.0,
      "battery_discharged": 0.5,
      "grid_imported": 0.0,
      "grid_exported": 0.09999999999990905,
      "battery_soe_start": 28.000000000000004,
      "battery_soe_end": 27.500000000000004,
      "solar_to_home": 0.0,
      "solar_to_battery": 0.0,
      "solar_to_grid": 0,
      "grid_to_home": 0.0,
      "grid_to_battery": 0,
      "battery_to_home": 0.40000000000009095,
      "battery_to_grid": 0.09999999999990905
    },
    "timestamp": "2026-05-30 04:32:17.929649+02:00",
    "data_source": "actual",
    "economic": {
      "buy_price": 2.460675,
      "sell_price": 1.4689400000000001,
      "grid_cost": -0.1468939999998664,
      "battery_cycle_cost": 0.0,
      "hourly_cost": -0.1468939999998664,
      "grid_only_cost": 0.9842700000002239,
      "solar_only_cost": 0.9842700000002239,
      "hourly_savings": 1.1311640000000902,
      "solar_savings": 0.0
    },
    "decision": {
      "strategic_intent": "IDLE",
      "observed_intent": "LOAD_SUPPORT",
      "battery_action": null,
      "cost_basis": 0.0,
      "pattern_name": "",
      "description": "",
      "economic_chain": "",
      "immediate_value": 0.0,
      "future_value": 0.0,
      "net_strategy_value": 0.0,
      "advanced_flow_pattern": "",
      "detailed_flow_values": {},
      "future_target_hours": []
    }
  },
  {
    "period": 5,
    "energy": {
      "solar_production": 0.0,
      "home_consumption": 0.3000000000001819,
      "battery_charged": 0.0,
      "battery_discharged": 0.3000000000001819,
      "grid_imported": 0.0,
      "grid_exported": 0.0,
      "battery_soe_start": 27.500000000000004,
      "battery_soe_end": 27.500000000000004,
      "solar_to_home": 0.0,
      "solar_to_battery": 0.0,
      "solar_to_grid": 0,
      "grid_to_home": 0.0,
      "grid_to_battery": 0,
      "battery_to_home": 0.3000000000001819,
      "battery_to_grid": 0.0
    },
    "timestamp": "2026-05-30 04:32:17.930088+02:00",
    "data_source": "actual",
    "economic": {
      "buy_price": 2.4499125000000004,
      "sell_price": 1.4603300000000001,
      "grid_cost": 0.0,
      "battery_cycle_cost": 0.0,
      "hourly_cost": 0.0,
      "grid_only_cost": 0.7349737500004457,
      "solar_only_cost": 0.7349737500004457,
      "hourly_savings": 0.7349737500004457,
      "solar_savings": 0.0
    },
    "decision": {
      "strategic_intent": "IDLE",
      "observed_intent": "LOAD_SUPPORT",
      "battery_action": null,
      "cost_basis": 0.0,
      "pattern_name": "",
      "description": "",
      "economic_chain": "",
      "immediate_value": 0.0,
      "future_value": 0.0,
      "net_strategy_value": 0.0,
      "advanced_flow_pattern": "",
      "detailed_flow_values": {},
      "future_target_hours": []
    }
  },
  {
    "period": 6,
    "energy": {
      "solar_production": 0.0,
      "home_consumption": 0.1000000000003638,
      "battery_charged": 0.0,
      "battery_discharged": 0.1000000000003638,
      "grid_imported": 0.0,
      "grid_exported": 0.0,
      "battery_soe_start": 27.500000000000004,
      "battery_soe_end": 27.0,
      "solar_to_home": 0.0,
      "solar_to_battery": 0.0,
      "solar_to_grid": 0,
      "grid_to_home": 0.0,
      "grid_to_battery": 0,
      "battery_to_home": 0.1000000000003638,
      "battery_to_grid": 0.0
    },
    "timestamp": "2026-05-30 04:32:17.930530+02:00",
    "data_source": "actual",
    "economic": {
      "buy_price": 2.4846375000000003,
      "sell_price": 1.48811,
      "grid_cost": 0.0,
      "battery_cycle_cost": 0.0,
      "hourly_cost": 0.0,
      "grid_only_cost": 0.24846375000090393,
      "solar_only_cost": 0.24846375000090393,
      "hourly_savings": 0.24846375000090393,
      "solar_savings": 0.0
    },
    "decision": {
      "strategic_intent": "IDLE",
      "observed_intent": "LOAD_SUPPORT",
      "battery_action": null,
      "cost_basis": 0.0,
      "pattern_name": "",
      "description": "",
      "economic_chain": "",
      "immediate_value": 0.0,
      "future_value": 0.0,
      "net_strategy_value": 0.0,
      "advanced_flow_pattern": "",
      "detailed_flow_values": {},
      "future_target_hours": []
    }
  },
  {
    "period": 7,
    "energy": {
      "solar_production": 0.0,
      "home_consumption": 0.5,
      "battery_charged": 0.0,
      "battery_discharged": 0.5,
      "grid_imported": 0.0,
      "grid_exported": 0.0,
      "battery_soe_start": 27.0,
      "battery_soe_end": 27.0,
      "solar_to_home": 0.0,
      "solar_to_battery": 0.0,
      "solar_to_grid": 0,
      "grid_to_home": 0.0,
      "grid_to_battery": 0,
      "battery_to_home": 0.5,
      "battery_to_grid": 0.0
    },
    "timestamp": "2026-05-30 04:32:17.930967+02:00",
    "data_source": "actual",
    "economic": {
      "buy_price": 2.4632375000000004,
      "sell_price": 1.4709900000000002,
      "grid_cost": 0.0,
      "battery_cycle_cost": 0.0,
      "hourly_cost": 0.0,
      "grid_only_cost": 1.2316187500000002,
      "solar_only_cost": 1.2316187500000002,
      "hourly_savings": 1.2316187500000002,
      "solar_savings": 0.0
    },
    "decision": {
      "strategic_intent": "IDLE",
      "observed_intent": "LOAD_SUPPORT",
      "battery_action": null,
      "cost_basis": 0.0,
      "pattern_name": "",
      "description": "",
      "economic_chain": "",
      "immediate_value": 0.0,
      "future_value": 0.0,
      "net_strategy_value": 0.0,
      "advanced_flow_pattern": "",
      "detailed_flow_values": {},
      "future_target_hours": []
    }
  },
  {
    "period": 8,
    "energy": {
      "solar_production": 0.0,
      "home_consumption": 0.2999999999992724,
      "battery_charged": 0.0,
      "battery_discharged": 0.2999999999992724,
      "grid_imported": 0.0,
      "grid_exported": 0.0,
      "battery_soe_start": 27.0,
      "battery_soe_end": 26.5,
      "solar_to_home": 0.0,
      "solar_to_battery": 0.0,
      "solar_to_grid": 0,
      "grid_to_home": 0.0,
      "grid_to_battery": 0,
      "battery_to_home": 0.2999999999992724,
      "battery_to_grid": 0.0
    },
    "timestamp": "2026-05-30 04:32:17.931404+02:00",
    "data_source": "actual",
    "economic": {
      "buy_price": 2.4255500000000003,
      "sell_price": 1.4408400000000001,
      "grid_cost": 0.0,
      "battery_cycle_cost": 0.0,
      "hourly_cost": 0.0,
      "grid_only_cost": 0.7276649999982353,
      "solar_only_cost": 0.7276649999982353,
      "hourly_savings": 0.7276649999982353,
      "solar_savings": 0.0
    },
    "decision": {
      "strategic_intent": "IDLE",
      "observed_intent": "LOAD_SUPPORT",
      "battery_action": null,
      "cost_basis": 0.0,
      "pattern_name": "",
      "description": "",
      "economic_chain": "",
      "immediate_value": 0.0,
      "future_value": 0.0,
      "net_strategy_value": 0.0,
      "advanced_flow_pattern": "",
      "detailed_flow_values": {},
      "future_target_hours": []
    }
  },
  {
    "period": 9,
    "energy": {
      "solar_production": 0.0,
      "home_consumption": 0.1000000000003638,
      "battery_charged": 0.0,
      "battery_discharged": 0.1000000000003638,
      "grid_imported": 0.0,
      "grid_exported": 0.0,
      "battery_soe_start": 26.5,
      "battery_soe_end": 26.0,
      "solar_to_home": 0.0,
      "solar_to_battery": 0.0,
      "solar_to_grid": 0,
      "grid_to_home": 0.0,
      "grid_to_battery": 0,
      "battery_to_home": 0.1000000000003638,
      "battery_to_grid": 0.0
    },
    "timestamp": "2026-05-30 04:32:17.931842+02:00",
    "data_source": "actual",
    "economic": {
      "buy_price": 2.4295875,
      "sell_price": 1.44407,
      "grid_cost": 0.0,
      "battery_cycle_cost": 0.0,
      "hourly_cost": 0.0,
      "grid_only_cost": 0.24295875000088385,
      "solar_only_cost": 0.24295875000088385,
      "hourly_savings": 0.24295875000088385,
      "solar_savings": 0.0
    },
    "decision": {
      "strategic_intent": "IDLE",
      "observed_intent": "LOAD_SUPPORT",
      "battery_action": null,
      "cost_basis": 0.0,
      "pattern_name": "",
      "description": "",
      "economic_chain": "",
      "immediate_value": 0.0,
      "future_value": 0.0,
      "net_strategy_value": 0.0,
      "advanced_flow_pattern": "",
      "detailed_flow_values": {},
      "future_target_hours": []
    }
  },
  {
    "period": 10,
    "energy": {
      "solar_production": 0.0,
      "home_consumption": 0.6000000000003638,
      "battery_charged": 0.0,
      "battery_discharged": 0.6000000000003638,
      "grid_imported": 0.0,
      "grid_exported": 0.0,
      "battery_soe_start": 26.0,
      "battery_soe_end": 26.0,
      "solar_to_home": 0.0,
      "solar_to_battery": 0.0,
      "solar_to_grid": 0,
      "grid_to_home": 0.0,
      "grid_to_battery": 0,
      "battery_to_home": 0.6000000000003638,
      "battery_to_grid": 0.0
    },
    "timestamp": "2026-05-30 04:32:17.932281+02:00",
    "data_source": "actual",
    "economic": {
      "buy_price": 2.4352375,
      "sell_price": 1.44859,
      "grid_cost": 0.0,
      "battery_cycle_cost": 0.0,
      "hourly_cost": 0.0,
      "grid_only_cost": 1.461142500000886,
      "solar_only_cost": 1.461142500000886,
      "hourly_savings": 1.461142500000886,
      "solar_savings": 0.0
    },
    "decision": {
      "strategic_intent": "IDLE",
      "observed_intent": "LOAD_SUPPORT",
      "battery_action": null,
      "cost_basis": 0.0,
      "pattern_name": "",
      "description": "",
      "economic_chain": "",
      "immediate_value": 0.0,
      "future_value": 0.0,
      "net_strategy_value": 0.0,
      "advanced_flow_pattern": "",
      "detailed_flow_values": {},
      "future_target_hours": []
    }
  },
  {
    "period": 11,
    "energy": {
      "solar_production": 0.0,
      "home_consumption": 0.1999999999998181,
      "battery_charged": 0.0,
      "battery_discharged": 0.1999999999998181,
      "grid_imported": 0.0,
      "grid_exported": 0.0,
      "battery_soe_start": 26.0,
      "battery_soe_end": 26.0,
      "solar_to_home": 0.0,
      "solar_to_battery": 0.0,
      "solar_to_grid": 0,
      "grid_to_home": 0.0,
      "grid_to_battery": 0,
      "battery_to_home": 0.1999999999998181,
      "battery_to_grid": 0.0
    },
    "timestamp": "2026-05-30 04:32:17.932736+02:00",
    "data_source": "actual",
    "economic": {
      "buy_price": 2.3941875,
      "sell_price": 1.41575,
      "grid_cost": 0.0,
      "battery_cycle_cost": 0.0,
      "hourly_cost": 0.0,
      "grid_only_cost": 0.47883749999956454,
      "solar_only_cost": 0.47883749999956454,
      "hourly_savings": 0.47883749999956454,
      "solar_savings": 0.0
    },
    "decision": {
      "strategic_intent": "IDLE",
      "observed_intent": "LOAD_SUPPORT",
      "battery_action": null,
      "cost_basis": 0.0,
      "pattern_name": "",
      "description": "",
      "economic_chain": "",
      "immediate_value": 0.0,
      "future_value": 0.0,
      "net_strategy_value": 0.0,
      "advanced_flow_pattern": "",
      "detailed_flow_values": {},
      "future_target_hours": []
    }
  },
  {
    "period": 12,
    "energy": {
      "solar_production": 0.0,
      "home_consumption": 0.1999999999998181,
      "battery_charged": 0.0,
      "battery_discharged": 0.1999999999998181,
      "grid_imported": 0.0,
      "grid_exported": 0.0,
      "battery_soe_start": 26.0,
      "battery_soe_end": 25.5,
      "solar_to_home": 0.0,
      "solar_to_battery": 0.0,
      "solar_to_grid": 0,
      "grid_to_home": 0.0,
      "grid_to_battery": 0,
      "battery_to_home": 0.1999999999998181,
      "battery_to_grid": 0.0
    },
    "timestamp": "2026-05-30 04:32:17.933277+02:00",
    "data_source": "actual",
    "economic": {
      "buy_price": 2.3383375,
      "sell_price": 1.37107,
      "grid_cost": 0.0,
      "battery_cycle_cost": 0.0,
      "hourly_cost": 0.0,
      "grid_only_cost": 0.4676674999995747,
      "solar_only_cost": 0.4676674999995747,
      "hourly_savings": 0.4676674999995747,
      "solar_savings": 0.0
    },
    "decision": {
      "strategic_intent": "IDLE",
      "observed_intent": "LOAD_SUPPORT",
      "battery_action": null,
      "cost_basis": 0.0,
      "pattern_name": "",
      "description": "",
      "economic_chain": "",
      "immediate_value": 0.0,
      "future_value": 0.0,
      "net_strategy_value": 0.0,
      "advanced_flow_pattern": "",
      "detailed_flow_values": {},
      "future_target_hours": []
    }
  },
  {
    "period": 13,
    "energy": {
      "solar_production": 0.0,
      "home_consumption": 0.5,
      "battery_charged": 0.0,
      "battery_discharged": 0.5,
      "grid_imported": 0.0,
      "grid_exported": 0.0,
      "battery_soe_start": 25.5,
      "battery_soe_end": 25.0,
      "solar_to_home": 0.0,
      "solar_to_battery": 0.0,
      "solar_to_grid": 0,
      "grid_to_home": 0.0,
      "grid_to_battery": 0,
      "battery_to_home": 0.5,
      "battery_to_grid": 0.0
    },
    "timestamp": "2026-05-30 04:32:17.933718+02:00",
    "data_source": "actual",
    "economic": {
      "buy_price": 2.3491000000000004,
      "sell_price": 1.3796800000000002,
      "grid_cost": 0.0,
      "battery_cycle_cost": 0.0,
      "hourly_cost": 0.0,
      "grid_only_cost": 1.1745500000000002,
      "solar_only_cost": 1.1745500000000002,
      "hourly_savings": 1.1745500000000002,
      "solar_savings": 0.0
    },
    "decision": {
      "strategic_intent": "IDLE",
      "observed_intent": "LOAD_SUPPORT",
      "battery_action": null,
      "cost_basis": 0.0,
      "pattern_name": "",
      "description": "",
      "economic_chain": "",
      "immediate_value": 0.0,
      "future_value": 0.0,
      "net_strategy_value": 0.0,
      "advanced_flow_pattern": "",
      "detailed_flow_values": {},
      "future_target_hours": []
    }
  },
  {
    "period": 14,
    "energy": {
      "solar_production": 0.0,
      "home_consumption": 2.899999999999636,
      "battery_charged": 0.0,
      "battery_discharged": 2.899999999999636,
      "grid_imported": 0.0,
      "grid_exported": 0.0,
      "battery_soe_start": 25.0,
      "battery_soe_end": 22.0,
      "solar_to_home": 0.0,
      "solar_to_battery": 0.0,
      "solar_to_grid": 0,
      "grid_to_home": 0.0,
      "grid_to_battery": 0,
      "battery_to_home": 2.899999999999636,
      "battery_to_grid": 0.0
    },
    "timestamp": "2026-05-30 04:32:17.934157+02:00",
    "data_source": "actual",
    "economic": {
      "buy_price": 2.3814,
      "sell_price": 1.40552,
      "grid_cost": 0.0,
      "battery_cycle_cost": 0.0,
      "hourly_cost": 0.0,
      "grid_only_cost": 6.906059999999134,
      "solar_only_cost": 6.906059999999134,
      "hourly_savings": 6.906059999999134,
      "solar_savings": 0.0
    },
    "decision": {
      "strategic_intent": "IDLE",
      "observed_intent": "LOAD_SUPPORT",
      "battery_action": null,
      "cost_basis": 0.0,
      "pattern_name": "",
      "description": "",
      "economic_chain": "",
      "immediate_value": 0.0,
      "future_value": 0.0,
      "net_strategy_value": 0.0,
      "advanced_flow_pattern": "",
      "detailed_flow_values": {},
      "future_target_hours": []
    }
  },
  {
    "period": 15,
    "energy": {
      "solar_production": 0.0,
      "home_consumption": 3.100000000000364,
      "battery_charged": 0.0,
      "battery_discharged": 3.100000000000364,
      "grid_imported": 0.0,
      "grid_exported": 0.0,
      "battery_soe_start": 22.0,
      "battery_soe_end": 19.0,
      "solar_to_home": 0.0,
      "solar_to_battery": 0.0,
      "solar_to_grid": 0,
      "grid_to_home": 0.0,
      "grid_to_battery": 0,
      "battery_to_home": 3.100000000000364,
      "battery_to_grid": 0.0
    },
    "timestamp": "2026-05-30 04:32:17.934596+02:00",
    "data_source": "actual",
    "economic": {
      "buy_price": 2.35745,
      "sell_price": 1.38636,
      "grid_cost": 0.0,
      "battery_cycle_cost": 0.0,
      "hourly_cost": 0.0,
      "grid_only_cost": 7.308095000000858,
      "solar_only_cost": 7.308095000000858,
      "hourly_savings": 7.308095000000858,
      "solar_savings": 0.0
    },
    "decision": {
      "strategic_intent": "IDLE",
      "observed_intent": "LOAD_SUPPORT",
      "battery_action": null,
      "cost_basis": 0.0,
      "pattern_name": "",
      "description": "",
      "economic_chain": "",
      "immediate_value": 0.0,
      "future_value": 0.0,
      "net_strategy_value": 0.0,
      "advanced_flow_pattern": "",
      "detailed_flow_values": {},
      "future_target_hours": []
    }
  },
  {
    "period": 16,
    "energy": {
      "solar_production": 0.0,
      "home_consumption": 3.699999999999818,
      "battery_charged": 0.0,
      "battery_discharged": 3.699999999999818,
      "grid_imported": 0.0,
      "grid_exported": 0.0,
      "battery_soe_start": 19.0,
      "battery_soe_end": 15.5,
      "solar_to_home": 0.0,
      "solar_to_battery": 0.0,
      "solar_to_grid": 0,
      "grid_to_home": 0.0,
      "grid_to_battery": 0,
      "battery_to_home": 3.699999999999818,
      "battery_to_grid": 0.0
    },
    "timestamp": "2026-05-30 04:32:17.935038+02:00",
    "data_source": "actual",
    "economic": {
      "buy_price": 2.4442625000000002,
      "sell_price": 1.45581,
      "grid_cost": 0.0,
      "battery_cycle_cost": 0.0,
      "hourly_cost": 0.0,
      "grid_only_cost": 9.043771249999557,
      "solar_only_cost": 9.043771249999557,
      "hourly_savings": 9.043771249999557,
      "solar_savings": 0.0
    },
    "decision": {
      "strategic_intent": "IDLE",
      "observed_intent": "LOAD_SUPPORT",
      "battery_action": null,
      "cost_basis": 0.0,
      "pattern_name": "",
      "description": "",
      "economic_chain": "",
      "immediate_value": 0.0,
      "future_value": 0.0,
      "net_strategy_value": 0.0,
      "advanced_flow_pattern": "",
      "detailed_flow_values": {},
      "future_target_hours": []
    }
  },
  {
    "period": 17,
    "energy": {
      "solar_production": 0.0,
      "home_consumption": 4.100000000000364,
      "battery_charged": 0.0,
      "battery_discharged": 4.100000000000364,
      "grid_imported": 0.0,
      "grid_exported": 0.0,
      "battery_soe_start": 15.5,
      "battery_soe_end": 11.5,
      "solar_to_home": 0.0,
      "solar_to_battery": 0.0,
      "solar_to_grid": 0,
      "grid_to_home": 0.0,
      "grid_to_battery": 0,
      "battery_to_home": 4.100000000000364,
      "battery_to_grid": 0.0
    },
    "timestamp": "2026-05-30 04:32:18.084836+02:00",
    "data_source": "actual",
    "economic": {
      "buy_price": 2.4368624999999997,
      "sell_price": 1.44989,
      "grid_cost": 0.0,
      "battery_cycle_cost": 0.0,
      "hourly_cost": 0.0,
      "grid_only_cost": 9.991136250000885,
      "solar_only_cost": 9.991136250000885,
      "hourly_savings": 9.991136250000885,
      "solar_savings": 0.0
    },
    "decision": {
      "strategic_intent": "IDLE",
      "observed_intent": "LOAD_SUPPORT",
      "battery_action": null,
      "cost_basis": 0.0,
      "pattern_name": "",
      "description": "",
      "economic_chain": "",
      "immediate_value": 0.0,
      "future_value": 0.0,
      "net_strategy_value": 0.0,
      "advanced_flow_pattern": "",
      "detailed_flow_values": {},
      "future_target_hours": []
    }
  },
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null
]
```

</details>

## Optimization Schedules

**Total Schedules**: 0

*No optimization schedules available*

## Prediction Snapshots

**Total Snapshots**: 0

*No prediction snapshots available*

## System Logs (Today)

**Log File**: /data/logs/bess-2026-05-30.log

**Size**: 64.6 KB

**Last Modified**: 2026-05-30T04:49:17.278782
<details>
<summary>Full Log Content (82 lines - click to expand)</summary>

```
[Compact log: 17 key events from 498 total lines + last 50 lines. Use compact=false for full log.]
  Max charging power: 15000.0W
[... 6 lines skipped ...]
  Max charging power: 15000.0W
[... 55 lines skipped ...]
2026-05-30 04:25:57 | WARNING | core.bess.battery_system_manager:813 - Failed to fetch predictions: influxdb_7d_avg strategy requires 'local_load_power' sensor configured
2026-05-30 04:25:57 | ERROR | core.bess.battery_system_manager:2673 - Failed to log battery system config: 
[... 74 lines skipped ...]
2026-05-30 04:25:57 | ERROR | core.bess.battery_system_manager:561 - Failed to update battery schedule: influxdb_7d_avg strategy requires 'local_load_power' sensor configured
[... 1 lines skipped ...]
2026-05-30 04:25:57 | INFO  | uvicorn.error:92 - Started server process [94]
2026-05-30 04:25:57 | INFO  | uvicorn.error:48 - Waiting for application startup.
[... 1 lines skipped ...]
2026-05-30 04:25:57 | INFO  | uvicorn.error:62 - Application startup complete.
2026-05-30 04:25:57 | INFO  | uvicorn.error:224 - Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
[... 23 lines skipped ...]
2026-05-30 04:28:48 | WARNING | core.bess.ha_api_controller:2248 - Failed to parse config entries / device registry: too many values to unpack (expected 2)
[... 11 lines skipped ...]
2026-05-30 04:30:00 | ERROR | core.bess.battery_system_manager:2549 - Failed to adjust charging power: No strategic intents available
[... 38 lines skipped ...]
2026-05-30 04:30:00 | ERROR | core.bess.battery_system_manager:561 - Failed to update battery schedule: influxdb_7d_avg strategy requires 'local_load_power' sensor configured
[... 62 lines skipped ...]
2026-05-30 04:32:18 | ERROR | core.bess.battery_system_manager:561 - Failed to update battery schedule: influxdb_7d_avg strategy requires 'local_load_power' sensor configured
[... 38 lines skipped ...]
2026-05-30 04:35:00 | ERROR | core.bess.battery_system_manager:2549 - Failed to adjust charging power: No strategic intents available
[... 30 lines skipped ...]
2026-05-30 04:40:00 | ERROR | core.bess.battery_system_manager:2549 - Failed to adjust charging power: No strategic intents available
[... 31 lines skipped ...]
2026-05-30 04:45:00 | ERROR | core.bess.battery_system_manager:2549 - Failed to adjust charging power: No strategic intents available
[... 39 lines skipped ...]
2026-05-30 04:45:00 | ERROR | core.bess.battery_system_manager:561 - Failed to update battery schedule: influxdb_7d_avg strategy requires 'local_load_power' sensor configured
[... 7 lines skipped ...]
2026-05-30 04:46:24 | INFO  | uvicorn.access:481 - 172.30.32.2:53558 - "GET /api/dashboard?resolution=quarter-hourly HTTP/1.1" 200
2026-05-30 04:46:24 | INFO  | uvicorn.access:481 - 172.30.32.2:53560 - "GET /api/dashboard-health-summary HTTP/1.1" 200
2026-05-30 04:46:24 | INFO  | uvicorn.access:481 - 172.30.32.2:53570 - "GET /api/historical-data-status HTTP/1.1" 200
2026-05-30 04:46:24 | INFO  | uvicorn.access:481 - 172.30.32.2:53576 - "GET /api/runtime-failures HTTP/1.1" 200
2026-05-30 04:46:54 | INFO  | uvicorn.access:481 - 172.30.32.2:38884 - "GET /api/runtime-failures HTTP/1.1" 200
2026-05-30 04:47:25 | INFO  | log_config:118 - Dashboard requested before schedule is ready — returning initializing state
2026-05-30 04:47:25 | INFO  | uvicorn.access:481 - 172.30.32.2:44032 - "GET /api/dashboard?resolution=quarter-hourly HTTP/1.1" 200
2026-05-30 04:47:25 | INFO  | uvicorn.access:481 - 172.30.32.2:44044 - "GET /api/dashboard-health-summary HTTP/1.1" 200
2026-05-30 04:47:25 | INFO  | uvicorn.access:481 - 172.30.32.2:44060 - "GET /api/historical-data-status HTTP/1.1" 200
2026-05-30 04:47:25 | INFO  | uvicorn.access:481 - 172.30.32.2:44064 - "GET /api/runtime-failures HTTP/1.1" 200
2026-05-30 04:47:35 | INFO  | log_config:118 - Dashboard requested before schedule is ready — returning initializing state
2026-05-30 04:47:35 | INFO  | uvicorn.access:481 - 172.30.32.2:37562 - "GET /api/dashboard?resolution=quarter-hourly HTTP/1.1" 200
2026-05-30 04:47:35 | INFO  | uvicorn.access:481 - 172.30.32.2:37566 - "GET /api/settings HTTP/1.1" 200
2026-05-30 04:47:37 | INFO  | uvicorn.access:481 - 172.30.32.2:51834 - "GET /api/runtime-failures HTTP/1.1" 200
2026-05-30 04:47:37 | INFO  | log_config:118 - Dashboard requested before schedule is ready — returning initializing state
2026-05-30 04:47:37 | INFO  | uvicorn.access:481 - 172.30.32.2:51836 - "GET /api/dashboard?resolution=quarter-hourly HTTP/1.1" 200
2026-05-30 04:47:37 | INFO  | uvicorn.access:481 - 172.30.32.2:51846 - "GET /api/dashboard-health-summary HTTP/1.1" 200
2026-05-30 04:47:37 | INFO  | uvicorn.access:481 - 172.30.32.2:51862 - "GET /api/historical-data-status HTTP/1.1" 200
2026-05-30 04:47:37 | INFO  | log_config:118 - Dashboard requested before schedule is ready — returning initializing state
2026-05-30 04:47:37 | INFO  | uvicorn.access:481 - 172.30.32.2:51868 - "GET /api/dashboard?resolution=quarter-hourly HTTP/1.1" 200
2026-05-30 04:47:37 | INFO  | uvicorn.access:481 - 172.30.32.2:51874 - "GET /api/dashboard-health-summary HTTP/1.1" 200
2026-05-30 04:47:37 | INFO  | uvicorn.access:481 - 172.30.32.2:51878 - "GET /api/historical-data-status HTTP/1.1" 200
2026-05-30 04:47:42 | INFO  | log_config:118 - Root path requested
2026-05-30 04:47:42 | INFO  | uvicorn.access:481 - 172.30.32.2:51894 - "GET / HTTP/1.1" 200
2026-05-30 04:47:42 | INFO  | uvicorn.access:481 - 172.30.32.2:51910 - "GET /assets/main-CS8O7VmD.css HTTP/1.1" 304
2026-05-30 04:47:42 | INFO  | uvicorn.access:481 - 172.30.32.2:51920 - "GET /assets/main-BzyWHtMg.js HTTP/1.1" 304
2026-05-30 04:47:42 | INFO  | uvicorn.access:481 - 172.30.32.2:51922 - "GET /api/settings HTTP/1.1" 200
2026-05-30 04:47:42 | INFO  | uvicorn.access:481 - 172.30.32.2:51926 - "GET /api/setup/status HTTP/1.1" 200
2026-05-30 04:47:42 | INFO  | uvicorn.access:481 - 172.30.32.2:51936 - "GET /api/runtime-failures HTTP/1.1" 200
2026-05-30 04:47:42 | INFO  | log_config:118 - Dashboard requested before schedule is ready — returning initializing state
2026-05-30 04:47:42 | INFO  | uvicorn.access:481 - 172.30.32.2:51950 - "GET /api/dashboard?resolution=quarter-hourly HTTP/1.1" 200
2026-05-30 04:47:42 | INFO  | uvicorn.access:481 - 172.30.32.2:51966 - "GET /api/dashboard-health-summary HTTP/1.1" 200
2026-05-30 04:47:42 | INFO  | uvicorn.access:481 - 172.30.32.2:51976 - "GET /api/historical-data-status HTTP/1.1" 200
2026-05-30 04:47:42 | INFO  | log_config:118 - Dashboard requested before schedule is ready — returning initializing state
2026-05-30 04:47:42 | INFO  | uvicorn.access:481 - 172.30.32.2:51980 - "GET /api/dashboard?resolution=quarter-hourly HTTP/1.1" 200
2026-05-30 04:47:42 | INFO  | uvicorn.access:481 - 172.30.32.2:51990 - "GET /api/dashboard-health-summary HTTP/1.1" 200
2026-05-30 04:47:43 | INFO  | uvicorn.access:481 - 172.30.32.2:51996 - "GET /api/historical-data-status HTTP/1.1" 200
2026-05-30 04:48:12 | INFO  | uvicorn.access:481 - 172.30.32.2:48584 - "GET /api/runtime-failures HTTP/1.1" 200
2026-05-30 04:48:42 | INFO  | uvicorn.access:481 - 172.30.32.2:34394 - "GET /api/runtime-failures HTTP/1.1" 200
2026-05-30 04:48:42 | INFO  | log_config:118 - Dashboard requested before schedule is ready — returning initializing state
2026-05-30 04:48:42 | INFO  | uvicorn.access:481 - 172.30.32.2:34402 - "GET /api/dashboard?resolution=quarter-hourly HTTP/1.1" 200
2026-05-30 04:48:42 | INFO  | uvicorn.access:481 - 172.30.32.2:34416 - "GET /api/dashboard-health-summary HTTP/1.1" 200
2026-05-30 04:48:43 | INFO  | uvicorn.access:481 - 172.30.32.2:34418 - "GET /api/historical-data-status HTTP/1.1" 200
2026-05-30 04:49:12 | INFO  | uvicorn.access:481 - 172.30.32.2:50774 - "GET /api/runtime-failures HTTP/1.1" 200
2026-05-30 04:49:14 | INFO  | core.bess.debug_data_exporter:348 - Starting debug data aggregation (compact=True)
2026-05-30 04:49:14 | INFO  | core.bess.official_nordpool_source:62 - Fetching Nordpool prices for 2026-05-30 using official integration
2026-05-30 04:49:15 | INFO  | core.bess.official_nordpool_source:133 - Successfully fetched 96 prices from official Nordpool integration
2026-05-30 04:49:15 | INFO  | core.bess.health_check:424 - InfluxDB credentials configured
2026-05-30 04:49:16 | INFO  | core.bess.official_nordpool_source:62 - Fetching Nordpool prices for 2026-05-31 using official integration
2026-05-30 04:49:17 | INFO  | core.bess.debug_data_exporter:714 - Entity snapshot captured: 26 entities

```

</details>