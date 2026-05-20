# Inverter Platforms

BESS Manager supports four inverter platform configurations. Each combines a
specific inverter hardware family with a Home Assistant integration for
communication.

## Supported Platforms

| Platform | Inverter | HA Integration | Connection | Control Method | solax_modbus Gen |
|----------|----------|----------------|------------|----------------|-----------------|
| Growatt MIN (Cloud) | Growatt MIC/MIN/MOD/MID | [Growatt Server](https://www.home-assistant.io/integrations/growatt_server/) | Cloud API | TOU service calls | — |
| Growatt MIN (Local) | Growatt MIC/MIN/MOD/MID | [solax_modbus](https://github.com/wills106/homeassistant-solax-modbus) Growatt plugin | Local Modbus | TOU entity writes | GEN4 |
| Growatt SPH (Cloud) | Growatt SPH | [Growatt Server](https://www.home-assistant.io/integrations/growatt_server/) | Cloud API | AC charge/discharge periods | — |
| Growatt MIX/SPH (Local) | Growatt MIX/SPA/SPH | [solax_modbus](https://github.com/wills106/homeassistant-solax-modbus) Growatt plugin | Local Modbus | Mode-specific time slots | GEN3 |
| SolaX | SolaX hybrid | [solax_modbus](https://github.com/wills106/homeassistant-solax-modbus) | Local Modbus | VPP active-power commands | — |

> **solax_modbus generation mapping:** The `wills106/homeassistant-solax-modbus`
> Growatt plugin classifies inverters by generation. GEN4 = MIN/MOD/MID/TL-X
> (AC-coupled, numbered TOU slots). GEN3 = MIX/SPA/SPH (DC-coupled, mode-specific
> time slots). BESS detects the generation automatically from entity markers.

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

### Growatt MIN (Local) — `growatt_solax_modbus` (GEN4)

Uses a **single TOU segment** (slot 1) with a full-day time window
(`00:00-23:59`). The battery mode is updated per-period via `apply_period()`
— only when the mode actually changes — instead of pre-programming up to 9
slots. This reduces the required entity count from 45 (9 slots x 5 entities)
to just **5 entities** (slot 1 only). Uses **GEN4** entities from the
solax_modbus Growatt plugin (MIN/MOD/MID/TL-X models).

**Schedule writes:** 5 HA service calls when mode changes:
```
select.select_option(entity: time_1_enabled, option: "Enabled"/"Disabled")
select.select_option(entity: time_1_begin, option: "00:00")
select.select_option(entity: time_1_end, option: "23:59")
select.select_option(entity: time_1_mode, option: "Battery First"/"Load First"/"Grid First")
button.press(entity: time_1_update)
```

When the mode is `load_first` (inverter default), segment 1 is disabled.
When the mode is `battery_first` or `grid_first`, segment 1 is enabled with
that mode. Writes only occur on mode transitions, not every period.

> **Entity ID vs unique_id naming:** The solax_modbus Growatt plugin uses
> `key="time_N_enabled"` internally but `name="Time N Active"` for display.
> HA generates the `entity_id` from the name (e.g.
> `select.growatt_inverter_time_1_active`), while the `unique_id` uses the key
> (e.g. `growatt_inverter_time_1_enabled`). BESS auto-detection matches on
> `unique_id`, which is immutable.

> **Migration from 9-slot mode:** On startup, BESS reads all available TOU
> slots (1-9) and automatically disables any enabled slots 2-9. Users who
> previously had slots 2-9 enabled do not need to take manual action.

**Per-period control:** Same generic calls as cloud variant:
- Grid charge: `switch.turn_on` / `switch.turn_off` on charger_switch entity
- Charge/discharge rate: `number.set_value` on EMS rate entities

**Lifetime energy notes (GEN4):** GEN4 has no native load consumption
register (`total_load` is GEN3, `home_consumption_energy` is SPF). BESS
derives `lifetime_load_consumption` as `solar + grid_import − grid_export`.
`total_yield` maps to `lifetime_system_production`.

### Growatt MIX/SPH (Local) — `growatt_solax_modbus_gen3` (GEN3)

GEN3 models (MIX/SPA/SPH) connected via the solax_modbus Growatt plugin.
These use **mode-specific time slots** rather than numbered TOU slots:
`battery_first_time_N`, `grid_first_time_N`, `load_first_time_N`.

> **Status:** Monitoring and dashboards are fully supported. Schedule control
> requires a dedicated controller (not yet implemented — the GEN3 time slot
> architecture differs from GEN4).

**EMS entities (GEN3-specific):**
| Entity Key | BESS Sensor Key | Purpose |
|-----------|-----------------|---------|
| `battery_first_charge_rate` | `battery_charging_power_rate` | Charge rate in battery-first mode |
| `grid_first_discharge_rate` | `battery_discharging_power_rate` | Discharge rate in grid-first mode |
| `battery_first_maximum_soc` | `battery_charge_stop_soc` | Max SOC target |
| `load_first_battery_minimum_soc` | `battery_discharge_stop_soc` | Min SOC target |

**Lifetime energy notes (GEN3):** GEN3 has `total_load` (register 1062) for
load consumption but no `total_yield`. BESS derives
`lifetime_system_production` from `lifetime_solar_energy`.

### Growatt SPH (Cloud) — `growatt_sph`

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

### Growatt MIN (Local) — GEN4 — `solax_modbus` Growatt plugin

**Monitoring and EMS control (GEN4):**

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

**TOU time slot control (slot 1 only, 5 entities):**

| BESS Sensor Key | Entity Type | solax_modbus Key (unique_id) | HA Entity ID Contains | Purpose |
|-----------------|-------------|------------------------------|----------------------|---------|
| `tou_time_1_enabled` | select | `time_1_enabled` | `time_1_active` | Slot active (Enabled/Disabled) |
| `tou_time_1_begin` | select | `time_1_begin` | `time_1_begin` | Start time (HH:MM) |
| `tou_time_1_end` | select | `time_1_end` | `time_1_end` | End time (HH:MM) |
| `tou_time_1_mode` | select | `time_1_mode` | `time_1_mode` | Battery First/Load First/Grid First |
| `tou_time_1_update` | button | `time_1_update` | `time_1_update` | Commit slot changes |

Only slot 1 is required. Slots 2-9 entities still exist in the suffix map for
backward compatibility (discovery will pick them up if enabled), but BESS only
actively uses slot 1. A `time_N_clear` button also exists in the plugin
(zeros out the slot) but is not used by BESS.

> **Note:** The `entity_id` for the enabled/disabled entity contains `active`
> (from the plugin's display name "Time N Active") while the `unique_id`
> contains `enabled` (from the plugin's internal key). BESS matches on
> `unique_id`, so the suffix map uses `time_N_enabled`.
>
> **Slot availability:** Slots 1-3 are enabled by default in HA. Slots 4-9
> are disabled by default in the entity registry and must be manually enabled
> in HA before BESS can discover or use them.

**Lifetime energy (GEN4, optional):**

| BESS Sensor Key | solax_modbus Suffix | Notes |
|-----------------|---------------------|-------|
| `lifetime_battery_charged` | `total_battery_input_energy` | |
| `lifetime_battery_discharged` | `total_battery_output_energy` | |
| `lifetime_solar_energy` | `total_solar_energy` | |
| `lifetime_import_from_grid` | `total_grid_import` | |
| `lifetime_export_to_grid` | `total_grid_export` | |
| `lifetime_system_production` | `total_yield` | GEN4 register 3077 |
| `lifetime_load_consumption` | — | **No native register.** BESS derives: solar + grid_import − grid_export |

### Growatt MIX/SPH (Local) — GEN3 — `solax_modbus` Growatt plugin

**Monitoring and EMS control (GEN3):**

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
| `battery_charging_power_rate` | number | `battery_first_charge_rate` | Charge rate (battery-first mode) |
| `battery_discharging_power_rate` | number | `grid_first_discharge_rate` | Discharge rate (grid-first mode) |
| `battery_charge_stop_soc` | number | `battery_first_maximum_soc` | Max SOC target |
| `battery_discharge_stop_soc` | number | `load_first_battery_minimum_soc` | Min SOC target |

**Lifetime energy (GEN3, optional):**

| BESS Sensor Key | solax_modbus Suffix | Notes |
|-----------------|---------------------|-------|
| `lifetime_battery_charged` | `total_battery_input_energy` | Register 1058 |
| `lifetime_battery_discharged` | `total_battery_output_energy` | Register 1054 |
| `lifetime_solar_energy` | `total_solar_energy` | |
| `lifetime_import_from_grid` | `total_grid_import` | Register 1046 |
| `lifetime_export_to_grid` | `total_grid_export` | Register 1050 |
| `lifetime_load_consumption` | `total_load` | Register 1062 |
| `lifetime_system_production` | — | **No native register.** BESS derives from `lifetime_solar_energy` |

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
   - If `growatt_server.write_ac_charge_times` service exists → **Growatt SPH (Cloud)**

2. **solax_modbus detected** (`platform: solax_modbus`):
   - If `time_1_enabled` unique_id suffix found → **Growatt MIN (Local) — GEN4**
   - Else if `load_first_battery_minimum_soc` unique_id suffix found → **Growatt MIX/SPH (Local) — GEN3**
   - Else if VPP entities present (`remotecontrol_power_control`) → **SolaX**

   Detection uses `unique_id` (built from the plugin's internal `key` field),
   not `entity_id` (built from display `name`). For Growatt TOU entities the
   unique_id ends with `time_1_enabled` even though the entity_id contains
   `time_1_active`.

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
