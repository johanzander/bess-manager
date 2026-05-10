# Inverter Platforms

BESS Manager supports four inverter platform configurations. Each combines a
specific inverter hardware family with a Home Assistant integration for
communication.

## Supported Platforms

| Platform | Inverter | HA Integration | Connection | Control Method |
|----------|----------|----------------|------------|----------------|
| Growatt MIN (Cloud) | Growatt MIC/MIN/MOD/MID | [Growatt Server](https://www.home-assistant.io/integrations/growatt_server/) | Cloud API | TOU service calls |
| Growatt MIN (Local) | Growatt MIC/MIN/MOD/MID | [solax_modbus](https://github.com/wills106/homeassistant-solax-modbus) Growatt plugin | Local Modbus | TOU entity writes |
| Growatt SPH | Growatt SPH | [Growatt Server](https://www.home-assistant.io/integrations/growatt_server/) | Cloud API | AC charge/discharge periods |
| SolaX | SolaX hybrid | [solax_modbus](https://github.com/wills106/homeassistant-solax-modbus) | Local Modbus | VPP active-power commands |

## How BESS Controls Each Platform

### Growatt MIN (Cloud) — `growatt_min`

BESS writes a 24-hour TOU (Time of Use) schedule to the inverter using up to
9 time slots. Each slot specifies a time range and battery mode (battery_first
or grid_first). Periods not covered by a slot default to load_first.

**Schedule writes:** Single HA service call per slot:
```
growatt_server.update_time_segment(segment_id, start_time, end_time, mode, enabled)
```

**Per-period control:** Generic HA entity service calls:
- Grid charge enable/disable: `switch.turn_on` / `switch.turn_off`
- Charge/discharge rate: `number.set_value`

### Growatt MIN (Local) — `growatt_solax_modbus`

Identical scheduling algorithm to Growatt MIN (Cloud) — same 9-slot TOU
management with differential updates and corruption recovery. Only the
hardware I/O layer differs.

**Schedule writes:** 5 HA service calls per slot:
```
select.select_option(entity: time_N_enabled, option: "Enabled"/"Disabled")
select.select_option(entity: time_N_begin, option: "HH:MM")
select.select_option(entity: time_N_end, option: "HH:MM")
select.select_option(entity: time_N_mode, option: "Battery First"/"Load First"/"Grid First")
button.press(entity: time_N_update)
```

**Per-period control:** Same generic calls as cloud variant:
- Grid charge: `switch.turn_on` / `switch.turn_off` on charger_switch entity
- Charge/discharge rate: `number.set_value` on EMS rate entities

### Growatt SPH — `growatt_sph`

SPH inverters use separate charge and discharge period lists (max 3 each)
rather than TOU slots. Each write sets all periods at once with global power
and SOC targets.

**Schedule writes:** HA service calls:
```
growatt_server.write_ac_charge_times(periods, power, stop_soc, mains_enabled)
growatt_server.write_ac_discharge_times(periods, power, stop_soc)
```

**Per-period control:** Same generic switch/number calls.

### SolaX — `solax`

SolaX inverters have no persistent TOU schedule. BESS issues VPP (Virtual
Power Plant) commands at each 15-minute period boundary. Commands auto-expire
after 1200 seconds, providing a safe fallback to self-use mode.

**Per-period control (VPP):**
```
select.select_option(power_control_mode: "Enabled Battery Control")
number.set_value(active_power: <watts>)       # positive=charge, negative=discharge
number.set_value(autorepeat_duration: 1200)
button.press(trigger)
```

**Idle/solar mode:** Disables VPP, inverter reverts to self-use.

---

## Required Entities by Platform

### Growatt MIN (Cloud) — `growatt_server` integration

| BESS Sensor Key | Entity Type | Growatt Server Suffix | Purpose |
|-----------------|-------------|----------------------|---------|
| `battery_soc` | sensor | `state_of_charge_soc` | Current battery level |
| `battery_charge_power` | sensor | `battery_1_charging_w` | Charge power (W) |
| `battery_discharge_power` | sensor | `battery_1_discharging_w` | Discharge power (W) |
| `import_power` | sensor | `import_power` | Grid import (W) |
| `export_power` | sensor | `export_power` | Grid export (W) |
| `pv_power` | sensor | `internal_wattage` | Solar production (W) |
| `local_load_power` | sensor | `local_load_power` | Home consumption (W) |
| `grid_charge` | switch | `charge_from_grid` | Grid charge enable |
| `battery_charging_power_rate` | number | `battery_charge_power_limit` | Charge rate (%) |
| `battery_discharging_power_rate` | number | `battery_discharge_power_limit` | Discharge rate (%) |
| `battery_charge_stop_soc` | number | `battery_charge_soc_limit` | Max SOC target |
| `battery_discharge_stop_soc` | number | `battery_discharge_soc_limit` | Min SOC target |

**Lifetime energy (optional but recommended):**

| BESS Sensor Key | Growatt Server Suffix |
|-----------------|---------------------|
| `lifetime_battery_charged` | `lifetime_total_all_batteries_charged` |
| `lifetime_battery_discharged` | `lifetime_total_all_batteries_discharged` |
| `lifetime_solar_energy` | `lifetime_total_solar_energy` |
| `lifetime_export_to_grid` | `lifetime_total_export_to_grid` |
| `lifetime_import_from_grid` | `lifetime_import_from_grid` |
| `lifetime_load_consumption` | `lifetime_total_load_consumption` |

### Growatt MIN (Local) — `solax_modbus` Growatt plugin

**Monitoring and EMS control:**

| BESS Sensor Key | Entity Type | solax_modbus Suffix | Purpose |
|-----------------|-------------|---------------------|---------|
| `battery_soc` | sensor | `battery_soc` | Current battery level |
| `battery_charge_power` | sensor | `battery_charge_power` | Charge power (W) |
| `battery_discharge_power` | sensor | `battery_discharge_power` | Discharge power (W) |
| `import_power` | sensor | `total_forward_power` | Grid import (W) |
| `export_power` | sensor | `total_reverse_power` | Grid export (W) |
| `pv_power` | sensor | `pv_power_1` | Solar production (W) |
| `local_load_power` | sensor | `total_load_power` | Home consumption (W) |
| `grid_charge` | switch | `charger_switch` | Grid charge enable |
| `battery_charging_power_rate` | number | `ems_charging_rate` | Charge rate (%) |
| `battery_discharging_power_rate` | number | `ems_discharging_rate` | Discharge rate (%) |
| `battery_charge_stop_soc` | number | `ems_charging_stop_soc` | Max SOC target |
| `battery_discharge_stop_soc` | number | `ems_discharging_stop_soc` | Min SOC target |

**TOU time slot control (9 slots x 5 entities = 45 entities):**

| BESS Sensor Key | Entity Type | solax_modbus Suffix | Purpose |
|-----------------|-------------|---------------------|---------|
| `tou_time_N_enabled` | select | `time_N_enabled` | Slot active (Enabled/Disabled) |
| `tou_time_N_begin` | select | `time_N_begin` | Start time (HH:MM) |
| `tou_time_N_end` | select | `time_N_end` | End time (HH:MM) |
| `tou_time_N_mode` | select | `time_N_mode` | Battery First/Load First/Grid First |
| `tou_time_N_update` | button | `time_N_update` | Commit slot changes |

Where N = 1 through 9.

**Lifetime energy (optional):**

| BESS Sensor Key | solax_modbus Suffix |
|-----------------|---------------------|
| `lifetime_battery_charged` | `total_battery_input_energy` |
| `lifetime_battery_discharged` | `total_battery_output_energy` |
| `lifetime_solar_energy` | `total_solar_energy` |
| `lifetime_import_from_grid` | `total_grid_import` |
| `lifetime_export_to_grid` | `total_grid_export` |
| `lifetime_load_consumption` | `home_consumption_energy` |

### SolaX — `solax_modbus` integration (native)

**Monitoring:**

| BESS Sensor Key | Entity Type | solax_modbus Suffix | Purpose |
|-----------------|-------------|---------------------|---------|
| `battery_soc` | sensor | `battery_capacity` or `battery_soc` | Current battery level |
| `battery_charge_power` | sensor | `battery_power_charge` or `battery_charge_power` | Charge power (W) |
| `battery_discharge_power` | sensor | `battery_power_discharge` or `battery_discharge_power` | Discharge power (W) |
| `import_power` | sensor | `measured_power` or `total_forward_power` | Grid import (W) |
| `export_power` | sensor | `grid_export` or `total_reverse_power` | Grid export (W) |
| `pv_power` | sensor | `pv_power_1` | Solar production (W) |
| `local_load_power` | sensor | `house_load` or `total_load_power` | Home consumption (W) |

**VPP control (required for SolaX):**

| BESS Sensor Key | Entity Type | solax_modbus Suffix | Purpose |
|-----------------|-------------|---------------------|---------|
| `solax_power_control_mode` | select | `remotecontrol_power_control` | Enable/disable VPP |
| `solax_active_power` | number | `remotecontrol_active_power` | Power target (W) |
| `solax_autorepeat_duration` | number | `remotecontrol_autorepeat_duration` | Command timeout (s) |
| `solax_power_control_trigger` | button | `remotecontrol_trigger` | Execute command |
| `solax_battery_min_soc` | number | `battery_minimum_capacity` | Min battery SOC (%) |

---

## Auto-Detection

BESS auto-detects the inverter platform during setup by scanning the HA entity
registry:

1. **Growatt Server detected** (`platform: growatt_server`):
   - If `growatt_server.update_time_segment` service exists → **Growatt MIN (Cloud)**
   - If `growatt_server.write_ac_charge_times` service exists → **Growatt SPH**

2. **solax_modbus detected** (`platform: solax_modbus`):
   - If TOU entities present (`time_1_enabled` suffix) → **Growatt MIN (Local)**
   - If VPP entities present (`remotecontrol_power_control` suffix) → **SolaX**

If multiple platforms are detected (e.g. both Growatt and SolaX entities
exist), the Settings page under Integrations & Sensors → Inverter Platform
allows selecting between the detected options. Only platforms with matching
entities in the HA registry are available for selection.

---

## Choosing Between Cloud and Local (Growatt MIN)

| | Growatt Server (Cloud) | solax_modbus (Local) |
|---|---|---|
| **Connection** | Internet → Growatt cloud → inverter | LAN → Modbus TCP/RTU → inverter |
| **Latency** | 5-30 seconds | < 1 second |
| **Reliability** | Depends on Growatt cloud availability | Independent of internet |
| **Setup** | Built-in HA integration, token auth | HACS integration, Modbus config |


Both options provide identical BESS functionality (9-slot TOU scheduling,
per-period grid charge control, SOC limits).
