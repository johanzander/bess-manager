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
| Huawei LUNA2000 (Local) | Huawei LUNA2000 | [huawei_solar](https://github.com/wlcrs/huawei_solar) | Local Modbus | TOU period-list writes | — |

> **solax_modbus generation mapping:** The `wills106/homeassistant-solax-modbus`
> Growatt plugin classifies inverters by generation. GEN4 = MIN/MOD/MID/TL-X
> (AC-coupled, numbered TOU slots). GEN3 = MIX/SPA/SPH (DC-coupled, mode-specific
> time slots). BESS detects the generation automatically from entity markers.

## Inverter Integration Patterns

Inverter control is **not** a single flat list of patterns — it is **two
orthogonal axes** plus a shared vocabulary of control primitives. (This mirrors
how cross-inverter optimizers like Predbat abstract ~20 brands: a *transport*
capability set × a *common control vocabulary*, not a per-brand enumeration.)
Adding a new inverter means placing it on both axes and listing which primitives
it supports — that determines which existing controller to model on and how much
is new.

### Axis 1 — Transport (how commands reach the inverter)

| Transport | HA integration(s) | Mechanism | Implemented today | Model controller(s) |
|-----------|-------------------|-----------|-------------------|---------------------|
| **TX-Cloud** | `growatt_server` | Vendor cloud API via HA **service calls** | ✅ | `GrowattMinController`, `GrowattSphController` |
| **TX-Modbus** | `solax_modbus` (multi-brand: SolaX, Solis, Growatt, Sofar, AlphaESS, …) | Local Modbus **entity writes** (select/number/button) | ✅ | `SolaxModbusGrowattController`, `SolaxController` |
| **TX-Vendor-service** | `huawei_solar` (and similar) | Local vendor integration: entity writes **+** ephemeral **service calls** (`forcible_charge`) | ❌ not yet | *(would model on `SolaxController` for the ephemeral half)* |
| **TX-REST / TX-MQTT** | GivTCP, Solar Assistant, Sofar2mqtt | REST API / MQTT | ❌ not planned | — |

`solax_modbus` is a **generic transport**, not a Growatt thing — the same channel
serves SolaX, Solis, Growatt, Sofar, etc. via per-brand register/entity names.

### Axis 2 — Scheduling model (how a plan is expressed)

| Scheduling model | Description | Implemented example |
|------------------|-------------|---------------------|
| **SM-TOU-numbered** | Persistent **numbered** TOU slots (start/end/mode) | Growatt MIN (cloud & GEN4 single-segment) |
| **SM-Period-lists** | Persistent **charge/discharge period lists** (≤N each), power/SOC in the write | Growatt SPH (cloud) |
| **SM-Mode-slots** | Persistent **mode-specific** time slots | Growatt MIX/SPH GEN3 (monitoring-only today) |
| **SM-Ephemeral** | **No persistent schedule** — push a duration-bounded command that auto-expires | SolaX VPP; Huawei `forcible_charge` would land here |

### Common control primitives (the shared vocabulary)

Regardless of transport/model, a controller works in these terms (each platform
declares which it supports, mapped to BESS sensor keys): **charge window**
(start/end) · **discharge window** · **target / charge-stop SOC** ·
**reserve / discharge-stop SOC** · **charge rate** · **discharge rate** ·
**grid-charge enable**.

### The five existing platforms as coordinates

| Platform | Transport | Scheduling model | Controller | Detection marker / service | Suffix map |
|----------|-----------|------------------|------------|----------------------------|-----------|
| `growatt_server_min` | TX-Cloud | SM-TOU-numbered | `GrowattMinController` | `growatt_server.update_time_segment` | `GROWATT_MIN_SUFFIX_MAP` |
| `growatt_server_sph` | TX-Cloud | SM-Period-lists | `GrowattSphController` | `growatt_server.write_ac_charge_times` | `GROWATT_SPH_SUFFIX_MAP` |
| `solax_modbus_growatt_min` | TX-Modbus | SM-TOU-numbered (single-segment) | `SolaxModbusGrowattController` | `_GROWATT_TOU_MARKER_SUFFIX` (`time_1_enabled`) | `SOLAX_GROWATT_MIN_SUFFIX_MAP` |
| `solax_modbus_growatt_sph` | TX-Modbus | SM-Mode-slots (GEN3, monitoring-only) | `SolaxModbusGrowattController` | `_GROWATT_GEN3_MARKER_SUFFIX` | `SOLAX_GROWATT_SPH_SUFFIX_MAP` |
| `solax_modbus_native` | TX-Modbus | SM-Ephemeral (VPP) | `SolaxController` | `_SOLAX_NATIVE_MARKER_SUFFIX` (`remotecontrol_power_control`) | `SOLAX_NATIVE_SUFFIX_MAP` |
| `huawei_solar_luna2000` | TX-Vendor-service | SM-Period-lists | `HuaweiController` | `_HUAWEI_BATTERY_MARKER_SUFFIX` (`storage_working_mode_settings`) | `HUAWEI_SUFFIX_MAP` |

### Worked examples for new inverters

- **Solis** (issue #130) — same **scheduling model** (persistent timed
  charge/discharge slots + charge/discharge current) regardless of integration,
  but Solis has several HA integrations across **both** transports. We support
  **one of two** (chosen per the reporter's actual setup; **`solax_modbus` is the
  default priority** because we already support that transport):
  - **`solax_modbus`** (TX-Modbus, local; 491★ multi-brand, the community
    standard) → **most additive**: new `SolisController` + `SOLIS_SUFFIX_MAP` + a
    detection branch **before** the `solax_modbus_native` fallback. No new
    transport, no ABC change.
  - **`solis-cloud-control`** (TX-Cloud, SolisCloud Control API; easiest
    onboarding, no wiring, but a young integration) → adds a **new TX-Cloud
    domain** (detection branch + cloud service helpers), like Growatt cloud.
    Treat as **experimental**.

  *Not supported:* `solis-sensor` (monitoring-only) and `Pho3niX90/solis_modbus`
  (redundant with `solax_modbus`'s local niche). **Decision: ask the reporter
  which of the two they run, implement that one, default to `solax_modbus`.**
- **Huawei LUNA2000** — persistent charge/discharge TOU period lists via the
  `huawei_solar` integration, shipping with full schedule control and
  auto-discovery. See **"How BESS Controls Huawei LUNA2000"** section below.

> **Both axes new?** A coordinate that needs a **new transport AND a new
> scheduling model** is the expensive case. The safe interim for any new inverter
> is **monitoring-only** (detection + sensors, no schedule control), as Growatt
> GEN3 currently is.

> **Note on the controller ABC:** `InverterController`'s method names are
> TOU-centric (`get_all_tou_segments`, `get_daily_TOU_settings`,
> `log_current_TOU_schedule`) and `_write_period_to_hardware` defaults to the
> Growatt register interface. SM-Ephemeral inverters (SolaX today, Huawei later)
> implement these by synthesizing "segments." It works; renaming to neutral terms
> is an optional future cleanup, not a prerequisite.

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

### Growatt VPP control mode (GEN3 + GEN4) — *(experimental)*

*Not yet real-world validated — see
[`docs/agents/memory/project_platform_maturity.md`](agents/memory/project_platform_maturity.md).*

`solax_modbus_growatt_min` (GEN4) and `solax_modbus_growatt_sph` (GEN3) both
support a second control strategy, `control_mode="vpp"`, selectable via the
`inverter.control_mode` setting (`"tou"` or `"vpp"`; GEN4 default remains
`"tou"` — GEN3 always runs `"vpp"` since it has no working TOU path). VPP
uses Growatt's remote power control registers instead of a persistent TOU
schedule — the same **SM-Ephemeral** model the SolaX platform below already
uses. See issue [#118](https://github.com/johanzander/bess-manager/issues/118).

Verified against `wills106/homeassistant-solax-modbus`'s
`custom_components/solax_modbus/plugin_growatt.py` (`NUMBER_TYPES`/
`SELECT_TYPES`, `allowedtypes=GEN3 | GEN4` — present on both generations):

| BESS Sensor Key | Entity Type | Register | Purpose |
|-----------------|-------------|----------|---------|
| `growatt_vpp_status` | select | 30100 | Master VPP enable (written once at startup) |
| `growatt_vpp_remote_control` | select | 30407 | Per-period VPP active/inactive |
| `growatt_vpp_allow_ac_charging` | select | 30410 | Allow charging from grid via VPP (written once) |
| `growatt_vpp_time` | number | 30408 | Fallback timer, minutes — reset every active period; reverts inverter to `load_first` on its own if BESS stops writing |
| `growatt_vpp_power` | number | 30409 | Power target, -100..100% (negative=discharge/export, positive=charge) |

**Intent → VPP mapping** (mirrors `SolaxController`, plus a
`block_passive_charging` distinction at rate=0 — see "SOLAR_EXPORT
semantics" below):
- `GRID_CHARGING` → `vpp_power=+100%`, remote control enabled
- `LOAD_SUPPORT`/`BATTERY_EXPORT` (rate>0) → `vpp_power=-rate%`, remote control enabled
- `SOLAR_STORAGE`/`IDLE` (rate=0, `block_passive_charging=False`) → remote
  control disabled (`load_first`/self-use — battery may absorb solar surplus)
- `SOLAR_EXPORT` (rate=0, `block_passive_charging=True`) → `vpp_power=0`,
  remote control **enabled** (`grid_first` hold)

**SOLAR_EXPORT semantics (fixed — issue [#355](https://github.com/johanzander/bess-manager/issues/355)):**
The Growatt VPP protocol
([`GROWATT VPP COMMUNICATION PROTOCOL OF INVERTER V2.01`](https://github.com/user-attachments/files/18301858/2.1.GROWATT.VPP.COMMUNICATION.PROTOCOL.OF.INVERTER_V2.01.pdf),
2024-9-20, linked from issue #118 — the authoritative vendor register
reference for all Growatt VPP work; check here first before assuming any
Growatt VPP register behavior), §3.5 "Remote power control schematic
diagram", p.32) documents that with
`vpp_remote_control` (30407) *enabled*, the sign of `vpp_power` (30409)
selects the firmware priority mode: **`> 0` → battery first (charge); `≤ 0`
→ grid first**. That is, `vpp_power=0` while remote control stays *enabled*
is a distinct, documented state — `grid first`, the same solar-goes-to-load-
then-grid priority TOU mode uses for `BATTERY_EXPORT` — not the same thing as
*disabling* remote control, which instead falls through to plain `load
first` self-use (battery-first for any solar surplus).

The controller previously conflated these two zero-power states: it always
disabled remote control at `rate=0`, landing in self-use `load_first`
instead of the documented `grid_first` hold, which let solar surplus
recharge the battery during `SOLAR_EXPORT` periods instead of holding it out
and exporting. The DP's SOLAR_EXPORT-below-max candidate (issue #313)
assumes charging can be blocked, an assumption that only holds for
TOU-style hardware rate control unless VPP mode is given an equivalent
signal — see
[`docs/superpowers/specs/2026-07-20-vpp-passive-charge-block-design.md`](superpowers/specs/2026-07-20-vpp-passive-charge-block-design.md)
for the full design (a `block_passive_charging` flag threaded through
`InverterController.apply_period`, computed once from intent, acted on only
by forced-power/VPP-style controllers).

`SOLAR_EXPORT` now keeps `vpp_remote_control` **enabled** and writes
`vpp_power=0` instead of disabling remote control, selecting the documented
`grid first` state instead of self-use `load_first`. **Not yet
real-hardware-validated**: whether `grid first` reached via a forced
`vpp_power=0` command holds the battery exactly like `grid_first` under TOU
is a firmware behavior claim the register table documents the *mode
selection logic* for, not the runtime power-flow guarantee — ships as
experimental pending confirmation from a real debug export (no existing TOU
code path exercises `grid_first` with a zero target either, so there's no
already-proven precedent to lean on).

`SolaxController` (real SolaX hardware) has the same underlying
architectural gap but is **not** fixed here — no SolaX vendor protocol has
been verified the way the Growatt spec was, so extending this fix there
would be speculation, not a verified command. Tracked as a follow-up.

**Enable sequence** (real-hardware-tested, see issue #118 comments): write
`vpp_status=Enabled` + `vpp_allow_ac_charging=Enabled`, wait ~1s, then write
`vpp_remote_control` — VPP Remote Control has no effect while VPP Status is
disabled. State survives controller re-instantiation (BESS recreates the
controller each optimization cycle) by reading the VPP registers back from
hardware in `read_and_initialize_from_hardware`, the same pattern TOU mode
already uses — not class-level statics.

**Out of scope:** sub-period reactive power correction against a live P1/smart
meter reading (demonstrated in community forks of this feature) is not built
into BESS — BESS stays on its 15-minute period model. Users wanting tighter
self-consumption can add their own HA automation nudging `growatt_vpp_power`
between BESS's writes, using the sensor key above as the target entity.

**Why VPP over TOU long-term:** VPP's per-period writes
(`growatt_vpp_power`/`growatt_vpp_time`) target RAM-backed registers, safe to
rewrite every period. TOU mode's per-period rate control instead writes
`ems_charging_rate`/`ems_discharging_rate`, which are flash-backed — fine at
TOU's lower write frequency, but not something VPP mode should ever fall back
to, since it writes far more often. This is the reasoning behind the
"Path to deprecating TOU" plan above, not yet a recommendation: GEN4 default
stays `"tou"` until VPP is validated on real hardware (see the platform
maturity note at the top of this section).

**Path to deprecating TOU:** once GEN4 VPP is validated on real hardware, the
GEN4 default flips to `"vpp"`, then the `"tou"` code path and setting are
removed entirely in a later release — no user migration needed, since this is
a setting inside the existing platform IDs, not a new platform ID.

### Growatt SPH (Cloud) — `growatt_sph`

SPH inverters use separate charge and discharge period lists (max 3 each)
rather than TOU slots. Each write sets all periods at once with global power
and SOC targets.

**Schedule writes:** HA service calls:
```
growatt_server.write_ac_charge_times(periods, power, stop_soc, mains_enabled)
growatt_server.write_ac_discharge_times(periods, power, stop_soc)
```

**Per-period control:** None — the `growatt_server` integration exposes no
number or switch entities for SPH models. All control (power rates, SOC
limits, grid charge) is embedded in the service call parameters.

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

### Huawei LUNA2000 (Local) — `huawei_solar_luna2000`

Huawei LUNA2000 batteries use a persistent charge/discharge period list (max
14 periods) gated behind the working-mode select entity. BESS writes a combined
list with separate charge and discharge periods, each specifying a time range
and the number of periods effective.

**Schedule writes:** Single HA service call with atomically-deployed charge/discharge lists:
```
huawei_solar.set_tou_periods(device_id, charge_periods, discharge_periods, working_mode_settings="time_of_use_luna2000")
```

The service call is gated by a preflight check verifying the battery model via
`get_huawei_working_mode_options()` — **LUNA2000 only**; LG RESU batteries are
explicitly not supported (they use a price-bidding TOU format incompatible with
BESS's optimization model).

**Scheduling model:** Charge periods are flagged `GRID_CHARGING` intents;
discharge periods are flagged `LOAD_SUPPORT` or `BATTERY_EXPORT` intents.
Periods without an explicit flag (SOLAR_STORAGE, SOLAR_EXPORT, IDLE) use the
inverter's default self-consumption mode.

**Per-period control:** None — all control (power, SOC limits, working mode) is
embedded in the service call parameters or requires manual inverter
configuration.

**Note on open items:** The LUNA2000's `days_effective` digit convention
(mapping "1234567" to day-of-week slots) and out-of-period battery behavior
remain unverified on real hardware — currently specified per the `huawei_solar`
integration's source code (`services.py`). See
[`docs/superpowers/specs/2026-07-22-issue-120-huawei-inverter-platform-design.md`](superpowers/specs/2026-07-22-issue-120-huawei-inverter-platform-design.md)
for design rationale and open items.

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

### Growatt SPH (Cloud) — `growatt_server` integration

The `growatt_server` integration exposes **no number or switch entities** for
SPH models. All control (power, SOC, grid charge, time periods) is via
`write_ac_charge_times` and `write_ac_discharge_times` service calls.

**Monitoring sensors (required):**

| BESS Sensor Key | Entity Type | Growatt Server Suffix | Purpose |
|-----------------|-------------|----------------------|---------|
| `battery_soc` | sensor | `state_of_charge_soc` | Current battery level |
| `battery_charge_power` | sensor | `battery_1_charging_w` | Charge power (W) |
| `battery_discharge_power` | sensor | `battery_1_discharging_w` | Discharge power (W) |
| `import_power` | sensor | `import_power` | Grid import (W) |
| `export_power` | sensor | `export_power` | Grid export (W) |
| `pv_power` | sensor | `internal_wattage` | Solar production (W) |
| `local_load_power` | sensor | `local_load_power` | Home consumption (W) |

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
| `grid_charge` | select | `charger_switch` | Grid charge enable (Enabled/Disabled) |
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
| `import_power` | sensor | `ac_power_to_user` | Grid import (W) |
| `export_power` | sensor | `ac_power_to_grid` | Grid export (W) |
| `pv_power` | sensor | `pv_power_total` | Solar production (W) |
| `local_load_power` | sensor | `total_load_power` | Home consumption (W) |
| `grid_charge` | select | `battery_first_charge_from_grid` | Grid charge enable |
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
| `battery_soc` | sensor | `battery_capacity` | Current battery level |
| `battery_charge_power` | sensor | `battery_power_charge` | Charge power (W) |
| `battery_discharge_power` | sensor | `battery_power_discharge` | Discharge power (W) |
| `import_power` | sensor | `measured_power` | Grid import (W) |
| `export_power` | sensor | `grid_export` | Grid export (W) |
| `pv_power` | sensor | `pv_power_1` | Solar production (W) |
| `local_load_power` | sensor | `house_load` | Home consumption (W) |

**Lifetime energy (optional):**

| BESS Sensor Key | solax_modbus Suffix | Notes |
|-----------------|---------------------|-------|
| `lifetime_battery_charged` | `battery_input_energy_total` | |
| `lifetime_battery_discharged` | `battery_output_energy_total` | |
| `lifetime_solar_energy` | `total_solar_energy` | |
| `lifetime_import_from_grid` | `grid_import_total` | |
| `lifetime_export_to_grid` | `grid_export_total` | |
| `lifetime_system_production` | `total_yield` | Register 0x52, "Total Yield" (production) |
| `lifetime_load_consumption` | — | **No native register.** Derived from other sensors |

**VPP control (required for SolaX):**

| BESS Sensor Key | Entity Type | solax_modbus Suffix | Purpose |
|-----------------|-------------|---------------------|---------|
| `solax_power_control_mode` | select | `remotecontrol_power_control` | Enable/disable VPP |
| `solax_active_power` | number | `remotecontrol_active_power` | Power target (W) |
| `solax_autorepeat_duration` | number | `remotecontrol_autorepeat_duration` | Command timeout (s) |
| `solax_power_control_trigger` | button | `remotecontrol_trigger` | Execute command |
| `solax_battery_min_soc` | number | `battery_minimum_capacity` | Min battery SOC (%) |
| `solax_charger_use_mode` | select | `charger_use_mode` | Charger use mode (optional) |

### Huawei LUNA2000 (Local) — `huawei_solar` integration

**Monitoring and schedule control:**

| BESS Sensor Key | Entity Type | huawei_solar Suffix | Purpose |
|-----------------|-------------|---------------------|---------|
| `battery_soc` | sensor | `storage_state_of_capacity` | Current battery level (%) |
| `battery_charge_power` | sensor | `storage_charge_discharge_power` | Net power (W; positive=charging) |
| `battery_charging_power_rate` | number | `storage_maximum_charging_power` | Max charge power (W) |
| `battery_discharging_power_rate` | number | `storage_maximum_discharging_power` | Max discharge power (W) |
| `battery_charge_stop_soc` | number | `storage_charging_cutoff_capacity` | Charge stop SOC (%) |
| `battery_discharge_stop_soc` | number | `storage_grid_charge_cutoff_state_of_charge` | Discharge stop SOC (%) |
| `grid_charge` | switch | `storage_charge_from_grid_function` | Grid charge enable |
| `huawei_working_mode` | select | `storage_working_mode_settings` | Battery working mode (gating TOU writes) |
| `local_load_power` | sensor | `active_power` | Home consumption (W) |

**Lifetime energy (optional):**

The `huawei_solar` integration does not expose lifetime energy counters for BESS's
standard usage (battery input/output, solar production, grid import/export). Custom
register reads via a separate Modbus probe are required; this is not yet
integrated into BESS.

**Auto-detection:** Presence of `huawei_solar` integration entities with the
`storage_working_mode_settings` unique_id suffix triggers Huawei platform
detection; the setup wizard confirms the battery model is LUNA2000 via
`get_huawei_working_mode_options()` before proceeding.

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

3. **huawei_solar detected** (`platform: huawei_solar`):
   - If `storage_working_mode_settings` unique_id suffix found → Probe `get_huawei_working_mode_options(device_id)` to verify LUNA2000 model
   - If confirmed LUNA2000 → **Huawei LUNA2000 (Local)**
   - Else (LG RESU or other unsupported model) → **Not supported**

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
