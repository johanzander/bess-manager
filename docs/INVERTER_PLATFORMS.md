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
| Solis | Solis hybrid | [solis_modbus](https://github.com/Pho3niX90/solis_modbus) | Local Modbus | Grid Time of Use v2 (6 charge + 6 discharge periods) | — |
| Huawei LUNA2000 (Local) | Huawei LUNA2000 | [huawei_solar](https://github.com/wlcrs/huawei_solar) | Local Modbus | TOU period-list writes | — |

> **solax_modbus generation mapping:** The `wills106/homeassistant-solax-modbus`
> Growatt plugin classifies inverters by generation. GEN4 = MIN/MOD/MID/TL-X
> (AC-coupled, numbered TOU slots). GEN3 = MIX/SPA/SPH (DC-coupled, mode-specific
> time slots). BESS detects the generation automatically from entity markers.

> **Why `solis_modbus` and not `solax_modbus` for Solis:** `solax_modbus`
> (the `wills106` project) advertises multi-brand support but does **not**
> support Solis inverters in practice, so
> [`Pho3niX90/solis_modbus`](https://github.com/Pho3niX90/solis_modbus) — a
> separate, dedicated integration domain — is the only viable local-Modbus
> option for Solis.

## Inverter Integration Patterns

Inverter control is **not** a single flat list of patterns — it is **two
orthogonal axes** plus a shared vocabulary of control primitives. Adding a new
inverter means placing it on both axes and listing which primitives it
supports — that determines which existing controller to model on and how much
is new.

### Axis 1 — Transport (how commands reach the inverter)

| Transport | HA integration(s) | Mechanism | Implemented today | Model controller(s) |
|-----------|-------------------|-----------|-------------------|---------------------|
| **TX-Cloud** | `growatt_server` | Vendor cloud API via HA **service calls** | ✅ | `GrowattMinController`, `GrowattSphController` |
| **TX-Modbus** | `solax_modbus` (multi-brand: SolaX, Solis, Growatt, Sofar, AlphaESS, …) | Local Modbus **entity writes** (select/number/button) | ✅ | `SolaxModbusGrowattController`, `SolaxController` |
| **TX-Vendor-service** | `huawei_solar` (and similar) | Local vendor integration: entity writes to persistent **TOU period lists** gated by working-mode select | ✅ | `HuaweiController` |
| **TX-REST / TX-MQTT** | GivTCP, Solar Assistant, Sofar2mqtt | REST API / MQTT | ❌ not planned | — |

`solax_modbus` is a **generic transport**, not a Growatt thing — the same channel
serves SolaX, Solis, Growatt, Sofar, etc. via per-brand register/entity names.

### Axis 2 — Scheduling model (how a plan is expressed)

| Scheduling model | Description | Implemented example |
|------------------|-------------|---------------------|
| **SM-TOU-numbered** | Persistent **numbered** TOU slots (start/end/mode) | Growatt MIN (cloud & GEN4 single-segment) |
| **SM-Period-lists** | Persistent **charge/discharge period lists** (≤N each), power/SOC in the write | Growatt SPH (cloud), Huawei LUNA2000 (local) |
| **SM-Mode-slots** | Persistent **mode-specific** time slots | Growatt MIX/SPH GEN3 (monitoring-only today) |
| **SM-Ephemeral** | **No persistent schedule** — push a duration-bounded command that auto-expires | SolaX VPP, Growatt VPP (GEN3+GEN4, experimental) |

### Common control primitives (the shared vocabulary)

Regardless of transport/model, a controller works in these terms (each platform
declares which it supports, mapped to BESS sensor keys): **charge window**
(start/end) · **discharge window** · **target / charge-stop SOC** ·
**reserve / discharge-stop SOC** · **charge rate** · **discharge rate** ·
**grid-charge enable**.

### The six platforms as coordinates

| Platform | Transport | Scheduling model | Controller | Detection marker / service | Suffix map |
|----------|-----------|------------------|------------|----------------------------|-----------|
| `growatt_server_min` | TX-Cloud | SM-TOU-numbered | `GrowattMinController` | `growatt_server.update_time_segment` | `GROWATT_MIN_SUFFIX_MAP` |
| `growatt_server_sph` | TX-Cloud | SM-Period-lists | `GrowattSphController` | `growatt_server.write_ac_charge_times` | `GROWATT_SPH_SUFFIX_MAP` |
| `solax_modbus_growatt_min` | TX-Modbus | SM-TOU-numbered (single-segment) | `SolaxModbusGrowattController` | `_GROWATT_TOU_MARKER_SUFFIX` (`time_1_enabled`) | `SOLAX_GROWATT_MIN_SUFFIX_MAP` |
| `solax_modbus_growatt_sph` | TX-Modbus | SM-Mode-slots (GEN3, monitoring-only) | `SolaxModbusGrowattController` | `_GROWATT_GEN3_MARKER_SUFFIX` | `SOLAX_GROWATT_SPH_SUFFIX_MAP` |
| `solax_modbus_native` | TX-Modbus | SM-Ephemeral (VPP) | `SolaxController` | `_SOLAX_NATIVE_MARKER_SUFFIX` (`remotecontrol_power_control`) | `SOLAX_NATIVE_SUFFIX_MAP` |
| `solis_modbus` | TX-Modbus | SM-Period-lists (6 charge + 6 discharge) | `SolisModbusController` | `_SOLIS_TOU_MARKER_SUFFIX` (`time_entity_43711`) | `SOLIS_SUFFIX_MAP` + `SOLIS_DICT_EMBEDDED_SUFFIX_MAP` |
| `huawei_solar_luna2000` | TX-Vendor-service | SM-Period-lists | `HuaweiController` | `_HUAWEI_BATTERY_MARKER_SUFFIX` (`storage_working_mode_settings`) | `HUAWEI_SUFFIX_MAP` |

### Bring-your-own integration

BESS reaches your inverter through whatever Home Assistant integration you
have installed. It is not bound to the specific integration named in the
table above — that column records what the platform was built against, not
a requirement. If the usual integration can't reach your hardware, or you
run a different one that talks to it, BESS can be pointed at that instead.

**The case this exists for — Huawei behind an EMMA energy manager.** Where
a third party owns the Modbus TCP socket, [`wlcrs/huawei_solar`](https://github.com/wlcrs/huawei_solar)
cannot connect to the inverter at all.
[`valexi7/Huawei-Modbus-TLS-Server`](https://github.com/valexi7/Huawei-Modbus-TLS-Server)
gets there through EMMA and exposes the same `set_tou_periods` service
under its own domain, so BESS drives such an install as an ordinary
`huawei_solar_luna2000` platform with one setting changed.

What has to line up:

- **The vendor service call.** Growatt Cloud and Huawei are the only
  platforms with one (see Axis 1). Your integration must expose that same
  service, with the same signature, under its own domain — set
  `inverter.service_domain` to that domain. The exact signatures are in the
  Growatt Cloud and Huawei LUNA2000 sections below. TX-Modbus platforms
  (Growatt Local, SolaX, Solis) have no vendor service at all: control
  there is plain `number`/`select`/`switch` entity writes, so only the
  entities below matter.
- **The entities.** Auto-discovery only recognizes the integration domains
  in the table above, so map the sensors — and, for Huawei, the battery
  Device ID — by hand under Settings → Integrations & Sensors.
- **Optional entities may legitimately be missing.** Huawei's working-mode
  select is the example: EMMA owns the mode, so nothing maps it. BESS then
  skips both the mode write and the LUNA2000-vs-LG-RESU battery check, logs
  that it did, and the health check reports WARNING rather than OK. If an
  EMMA integration does expose the select, BESS recognizes its `Time Of Use`
  option as equivalent to `time_of_use_luna2000`.

BESS cannot test against an integration it doesn't ship support for, so any
such setup is experimental by definition. If your inverter has no matching
platform at all — a scheduling model BESS doesn't implement — configuration
can't bridge that; open an issue describing what it needs.

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

**Lifetime energy notes (GEN4):** GEN4 *does* have a native load consumption
register — `total_yield` (register 3077, "Total Load Energy") maps to
`lifetime_load_consumption`, and `total_power_generation` (register 3051) maps
to `lifetime_system_production`. GEN4 therefore never takes the derived-load
path. (`total_load` is GEN3, `home_consumption_energy` is SPF.)

### Export-limit curtailment (GEN2/GEN3/GEN4) — *(optional, opt-in)*

Registers 122/123 via the solax_modbus Growatt plugin — verified against
`plugin_growatt.py` SELECT_TYPES/NUMBER_TYPES (`allowedtypes=GEN2|GEN3|GEN4`),
so this is available on both GEN3 and GEN4 hardware, not GEN4-only. Requires
a grid CT/smart meter; disabled (`BatterySettings.export_curtailment_enabled
= False`) by default.

When enabled and a period is exporting solar surplus at a sell price below
`export_curtailment_price_floor`, BESS writes:
```
select.select_option(entity: limit_grid_export, option: "Meter 1")
number.set_value(entity: grid_export_limit, value: 0)
```
This throttles PV/MPPT production at the panel via the CT meter's real-time
export reading — genuine supply-side curtailment, not just a downstream cap
that gets bypassed once the battery is full. Confirmed by a real user's live
test (Meter 1 + 0% dropped measured export to 0W within seconds). Once the
period's sell price is no longer below the floor, BESS releases the limit
with `select.select_option(entity: limit_grid_export, option: "Disabled")`
only — the percentage register is left untouched on release (its negative
range means "allow this much import," never written by BESS).

The decision is platform-agnostic (`grid_exported > 0 AND sell_price <
floor`, independent of strategic intent) but the actuation itself is
gated by the `supports_export_limit_control` capability flag — currently
only `SolaxModbusGrowattController` implements it. `growatt_server` (cloud)
has no equivalent HA service to hook into and stays a safe no-op.

This same condition is also computed at planning time (mirrored, not
re-derived at dispatch) and exposed as `PeriodData.decision.curtailed`
(#501), so the UI can show a period the plan expects to curtail as
distinct from a genuinely profitable export — see
`core/bess/dp_battery_algorithm.py`'s `_build_period_data`.

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

**Intent → VPP mapping** (originally mirrored `SolaxController`; `LOAD_SUPPORT`
has since diverged — see "LOAD_SUPPORT semantics" below — plus a
`block_passive_charging` distinction at rate=0 — see "SOLAR_EXPORT
semantics" below):
- `GRID_CHARGING` → `vpp_power=+100%`, remote control enabled
- `BATTERY_EXPORT` (rate>0) → `vpp_power=-rate%`, remote control enabled
- `LOAD_SUPPORT` (any rate) → `vpp_power=0`, remote control **disabled**,
  regardless of `discharge_rate` (releases to `load_first` self-use — see
  "LOAD_SUPPORT semantics" below)
- `SOLAR_STORAGE` (rate=0, `block_passive_charging=False`) → remote
  control disabled (`load_first`/self-use — battery may absorb solar surplus)
- `IDLE` (rate=0) → `vpp_power=+1%`, remote control **enabled**
  (`battery_first` hold — see "IDLE semantics" below)
- `SOLAR_EXPORT` (rate=0, `block_passive_charging=True`) → `vpp_power=0`,
  remote control **enabled** (`grid_first` hold)

**Register write ordering (issue [#593](https://github.com/johanzander/bess-manager/issues/593)):**
Growatt VPP has no separate trigger entity — writing `vpp_remote_control`
(30407) *is* the commit, so the inverter immediately executes whatever
30409/30408 already hold. The write order is therefore load-bearing, not
stylistic:

- **Activating** a period: `vpp_power` (30409) → `vpp_time` (30408) →
  `vpp_remote_control=Enabled` (30407) **last**. Arming first would execute
  the previous active period's power value until the new one lands — up to
  ±100%, i.e. a full-rated charge or export spike on every mode switch.
- **Releasing** to `load_first`: `vpp_remote_control=Disabled` **first**, then
  `vpp_power=0`. The zero clears the latch so the *next* activation can't
  inherit a stale value; it must come after the disable, because a 0 written
  while remote control is still enabled selects the `grid_first` hold (see
  "SOLAR_EXPORT semantics" below) rather than being inert.

A consequence worth knowing when reading logs: a failed power or timer write
now leaves remote control untouched, so the period degrades to `load_first`
self-use instead of executing a stale command.

**LOAD_SUPPORT semantics (fixed — issue [#413](https://github.com/johanzander/bess-manager/issues/413)):**
Unlike TOU mode (where `LOAD_SUPPORT` maps to `load_first`, letting the
inverter's own control loop follow actual house load), VPP mode previously
forced `LOAD_SUPPORT` into the same branch as `BATTERY_EXPORT` — a fixed
`grid_first` discharge percentage, immune to real load. Since `grid_first`'s
power value is an immediate forced command rather than a load-following
ceiling, this caused unnecessary grid imports/exports whenever the DP's
average-power discharge rate for the period didn't match the real,
fluctuating house load. `LOAD_SUPPORT` now disables `vpp_remote_control`
outright, falling back to the inverter's native `load_first` self-consumption
— the VPP-mode equivalent of TOU's `load_first` mapping. Reported
independently by two real-hardware testers (Growatt MIN, control_mode=vpp)
on issue [#118](https://github.com/johanzander/bess-manager/issues/118).

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

**IDLE semantics (fixed — issue [#466](https://github.com/johanzander/bess-manager/issues/466)):**
`IDLE` previously mapped to the same `remote_control=Disabled` → native
`load_first` self-use as `SOLAR_STORAGE`. That is wrong for IDLE
specifically: `load_first` self-use discharges the battery to cover house
load before drawing from grid, but the DP's own cost model for IDLE periods
(`_idle_battery_flows` in `dp_battery_algorithm.py`) never credits the
battery discharging — it only ever models passive solar absorption
(charging). A real overnight IDLE period therefore drained the battery for
house load in a way the optimizer's schedule never priced for. Confirmed by
a real-hardware report (Growatt MIN, control_mode=vpp) on issue #466.

The `grid_first` hold used for `SOLAR_EXPORT` above is **not** a fix for
this: per issue #118's real-hardware testing, `grid_first`
(`vpp_power<=0`, remote control enabled) still draws self-consumption from
the battery — it only stops the battery *absorbing* solar, not discharging
for load. Only `battery_first` (`vpp_power>0`) releases self-consumption to
grid/solar. `IDLE` now maps to `remote_control=Enabled`, `vpp_power=+1`
(the minimal `battery_first` magnitude) instead. **Not yet
real-hardware-validated**: ships experimental pending confirmation that this
doesn't cause any grid-charge creep overnight (`vpp_power>0` is the same
mechanism `GRID_CHARGING` uses at `+100%` to force-charge from grid, just at
a 1% target).

**IDLE at the reserve floor (issue [#592](https://github.com/johanzander/bess-manager/issues/592)):**
The `battery_first` hold above exists to protect *stored* energy from
self-consumption. At the configured minimum SoC there is none left to
protect, so the hold buys nothing — and because it keeps remote control
enabled, `_apply_period_vpp` rewrites the command every period to refresh
the fallback timer, so the inverter is never handed back and its BMS never
idles down. Reported on real hardware as a long overnight idle where the
battery and BMS stayed awake.

`IDLE` with the battery at (or below) `min_soc` therefore maps to
`vpp_power=0`, remote control **disabled** — released to the inverter's own
`load_first` self-use. Above the floor the `battery_first` hold is
unchanged, so #466 is preserved.

Releasing is chosen over the alternative of writing `vpp_power=0` with
remote control still *enabled* (`grid_first`) because only the released form
is flow-neutral: `load_first` still absorbs passive solar surplus exactly as
the `battery_first` hold does, whereas `grid_first` holds against charging
and would bypass that surplus to the grid — a real change, since IDLE's DP
cost model does credit passive absorption. Verified across the fixture
corpus: the v10.0.2 VPP regression baseline's **commands** move at every
IDLE-at-floor period — 499 periods across 50 entries, `[1, true]` →
`[0, false]` — while **realized cost and the SoE trajectory are bit-identical**
(0.000000000000 on both halves of the pin). Commands changing with no energy
moving is precisely what flow-neutral means here; an unchanged baseline would
have meant the branch was never exercised, which is what an earlier revision
of this fix wrongly reported.

**Caveat — the floor that actually binds is the inverter's own.** How far
the battery can fall under released self-use is governed by the inverter's
`discharge_stop_soc` register, not by BESS's `min_soc`, and **in VPP mode
BESS never writes that register** (`initialize_hardware` returns before
`sync_soc_limits` — see issue #309). If the inverter's own floor sits below
the configured `min_soc`, released self-use can draw the gap between them.
This is not new to #592: `LOAD_SUPPORT` (#413) and `SOLAR_STORAGE` already
release control the same way at any SoC. `vpp_simulator` models the release
as a hold at `min_soe_kwh`, i.e. it assumes the two floors agree. **Not yet
real-hardware-validated**; ships experimental pending confirmation that the
BMS does sleep and that the battery does not discharge below the configured
minimum.

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

### Solis — `solis_modbus`

Solis hybrids, connected via the community
[`Pho3niX90/solis_modbus`](https://github.com/Pho3niX90/solis_modbus)
integration (verified against release v4.1.6), share Growatt SPH's
**SM-Period-lists** scheduling model — separate charge and discharge period
lists — but Solis's "Grid Time of Use v2" schedule supports **6 charge
periods and 6 discharge periods** (not SPH's 3+3), and each period is written
directly to HA `time`/`switch` entities rather than via a cloud service call.
Credit: based on SA7BNT's research and initial implementation in
bess-manager-beta [PR #51](https://github.com/johanzander/bess-manager-beta/pull/51).

**Schedule writes:** one `time.set_value` call for each slot's start and end,
plus one `switch.turn_on`/`turn_off` for its enable bit — for all 6 charge
slots and all 6 discharge slots, every time (full rewrite, unused slots get
`00:00-00:00` + disabled):
```
time.set_value(entity: solis_charge_start_N, time: "HH:MM:00")
time.set_value(entity: solis_charge_end_N,   time: "HH:MM:00")
switch.turn_on/turn_off(entity: solis_charge_enable_N)
# ...and the same for solis_discharge_{start,end,enable}_N, N = 1..6
```

**Per-period control:** none — Solis has no per-period charge/discharge rate
register exposed by solis_modbus (`supports_charge_rate_control = False`,
same limitation as SPH).

**Verified integration bug (source-cited):** `SolisSensorGroup.__init__`
(`sensors/solis_base_sensor.py:254`) calls
`unique_id_generator(controller, entity)` — passing the **entire entity
definition dict** instead of `entity["unique"]`. This means most read-only
sensors and all "editable" number entities (per-slot TOU current/cutoff-SOC,
global charge/discharge stop SOC) get a `unique_id` containing the Python
`repr()` of their whole definition dict, e.g. ``solis_modbus_SN123_{'name':
'Battery SOC', ..., 'unique': 'solis_modbus_inverter_battery_soc', ...}`` —
not a clean, `endswith()`-matchable suffix. Present in v4.1.6 (stable) and
unchanged on the integration's HEAD as of 2026-07-05. BESS works around this
with a **Solis-only** substring matcher
(`_match_solis_dict_embedded_entities` in `ha_api_controller.py`) that
checks for the verified `'unique': '<key>'` fragment — this never touches
the shared `_map_registry_entities` suffix matching every other platform
uses. TOU period times (`time.py`) and per-slot enable switches
(`solis_binary_sensor.py`) go through the integration's *correct*
`unique_id_generator` call and are matched normally.

**Known gaps in this first pass:**
- Global charge/discharge stop SOC ("Max Charge SOC" / "Overdischarge SOC")
  are affected by the same dict-embedded-unique_id bug and have no verified
  write path yet — `sync_soc_limits()` is an explicit no-op, not a silent
  fallback.
- `pv_power` maps to PV string 1 only (`dc_power_1`); Solis hybrids with
  multiple MPPT strings will under-report total PV power until a summed
  sensor is added.
- `import_power` and `export_power` both resolve to the single signed "Grid
  Power Net" sensor (Solis exposes no separate import/export power
  entities). `HomeAssistantAPIController.grid_power_polarity`
  (`"import_positive"` for `solis_modbus`, set via
  `SettingsStore.get_grid_power_polarity()`) splits the one raw reading by
  sign at read time: positive → `import_power`, negative → `export_power`.
  Not user-configurable — it's a fixed property of the platform, not
  install-specific.

### Huawei LUNA2000 (Local) — `huawei_solar_luna2000`

Huawei LUNA2000 batteries use a persistent charge/discharge period list (max
14 periods) gated behind the working-mode select entity. BESS writes a combined
list with separate charge and discharge periods, each specifying a time range
and the number of periods effective.

**Schedule writes:** Single HA service call with atomically-deployed charge/discharge lists:
```
huawei_solar.set_tou_periods(device_id, charge_periods, discharge_periods, working_mode_settings="time_of_use_luna2000")
```

The service call is gated by a preflight check verifying a compatible TOU mode
via `get_huawei_working_mode_options()`. Stock `huawei_solar` exposes
`time_of_use_luna2000`; Huawei EMMA exposes the equivalent `Time Of Use`
(matched case- and separator-insensitively). LG RESU batteries remain
explicitly unsupported because they use a price-bidding TOU format incompatible
with BESS's optimization model.

**When no working-mode entity is mapped**, that whole gate is skipped: BESS
neither sets the working mode nor verifies the battery family, and logs both.
This is the expected shape for an install behind an energy manager (EMMA),
where the manager owns the mode. The health check reports WARNING rather than
OK for such an install, since BESS is then trusting the operator's platform
choice instead of checking it.

**Compatible integrations under another domain.** This `set_tou_periods` call
targets whichever domain `inverter.service_domain` resolves to (default
`huawei_solar`) — see "Bring-your-own integration" above for when and how to
change it.

**Schedule readback (optional, #431).** `huawei_solar` has no
`read_tou_periods` service, but its TOU period sensor publishes the
programmed periods as `Period N` extra state attributes, in the very text
format `set_tou_periods` accepts (`HuaweiSolarTOUSensorEntity`, sensor.py).
When the `huawei_tou_periods` sensor is mapped, BESS reads those in two
places, the same read-compare-write shape Growatt MIN adopted in #551/#552:

- at startup, to initialise the period list from what the battery actually
  holds, so a restart doesn't rewrite a schedule already running. The periods
  carry no strategic intent (the battery reports only charge/discharge
  flags), so they display as `existing_schedule` until the first optimization.
- before every write, comparing the plan against a fresh read rather than
  against BESS's own model of the battery — a model can only ever claim what
  BESS *meant* to write. `set_tou_periods` rewrites the whole list atomically
  and cannot update just what moved, so every skipped write is a flash-wear
  event spared. Paths that write without consulting `evaluate_intents` (a
  retried write, the corruption flag, the 23:55 next-day preparation) go
  through this check too.

An empty plan still writes: the empty string is how BESS clears periods the
battery is otherwise left running.

Readback is enabled by the sensor being *mapped*, never by attempting the
read and catching failure. Installs whose integration exposes no such entity
keep the original behaviour: start with an empty period list, converge on the
first cycle. If the entity is mapped but unreadable, that raises rather than
reading as "no periods programmed" — the two must not look alike, or BESS
would skip a write it genuinely needs. That read is the *first* thing
`sync_to_hardware` does, ahead of the working-mode and grid-charge writes, so
a failed read aborts the cycle with the battery untouched instead of arming
grid charging against the period list the old plan left behind; BSM's
`_hardware_write_pending` then retries the whole sync next cycle.

`days` is part of a period's identity in that comparison. BESS always writes
all-days (`1234567`) periods, so a period programmed elsewhere for a subset
of weekdays is not a match for BESS's own period even at identical times.

EMMA's equivalent register (`emma_tou_periods`) uses the same period format
but its entity is disabled by default upstream, so it is deliberately left
out of `HUAWEI_SUFFIX_MAP` — auto-discovery would otherwise map a disabled,
stateless entity. EMMA users who enable it can map it by hand in Settings.

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

### Derived load consumption

**SolaX native, Solis and Huawei LUNA2000** expose no lifetime load-consumption
register. For those three, BESS derives it from the energy balance:

```
load = solar + grid_import + battery_discharged − battery_charged − grid_export
```

All three map both battery counters, so the derivation is always computable
where it is used. If any of the five inputs is unmapped, BESS returns *no
value* rather than a partial one — dropping the battery terms would report
load plus net battery charge, a kWh-scale error on every period the battery is
active (issue #528). The identity lives in one place,
`core/bess/energy_balance.py`, and is shared by the lifetime-sensor path
(`ha_api_controller`) and the per-period flow path (`energy_flow_calculator`).

Every Growatt variant maps a native load register and never takes this path.

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
| `lifetime_system_production` | `total_power_generation` | GEN4 register 3051 |
| `lifetime_load_consumption` | `total_yield` | GEN4 register 3077, "Total Load Energy" |

**Export-limit curtailment (GEN4, optional):**

| BESS Sensor Key | Entity Type | solax_modbus Suffix | Purpose |
|-----------------|-------------|---------------------|---------|
| `growatt_export_limit_mode` | select | `limit_grid_export` | Meter/CT selection (Disabled/Meter 1/Meter 2/CT Clamp), register 122 |
| `growatt_export_limit_value` | number | `grid_export_limit` | Export limit percentage, register 123 |

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

**Export-limit curtailment (GEN3, optional):** same registers/entities as
GEN4 above (`limit_grid_export` / `grid_export_limit`, registers 122/123) —
`plugin_growatt.py` marks these `allowedtypes=GEN2|GEN3|GEN4`, not GEN4-only.

### SolaX — `solax_modbus` integration (native)

**Monitoring:**

| BESS Sensor Key | Entity Type | solax_modbus Suffix | Purpose |
|-----------------|-------------|---------------------|---------|
| `battery_soc` | sensor | `battery_capacity` | Current battery level |
| `battery_charge_power` / `battery_discharge_power` | sensor | `battery_power_charge` (signed) | Battery power (W); both keys map to this entity, split by sign at read time (`battery_power_polarity`, `"charge_positive"` — issue #542) |
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
| `lifetime_load_consumption` | — | **No native register.** BESS derives it — see [Derived load consumption](#derived-load-consumption) |

**VPP control (required for SolaX):**

| BESS Sensor Key | Entity Type | solax_modbus Suffix | Purpose |
|-----------------|-------------|---------------------|---------|
| `solax_power_control_mode` | select | `remotecontrol_power_control` | Enable/disable VPP |
| `solax_active_power` | number | `remotecontrol_active_power` | Power target (W) |
| `solax_autorepeat_duration` | number | `remotecontrol_autorepeat_duration` | Command timeout (s) |
| `solax_power_control_trigger` | button | `remotecontrol_trigger` | Execute command |
| `solax_battery_min_soc` | number | `battery_minimum_capacity` | Min battery SOC (%) |
| `solax_charger_use_mode` | select | `charger_use_mode` | Charger use mode (optional) |

### Solis — `solis_modbus` integration

**Monitoring:**

| BESS Sensor Key | Entity Type | solis_modbus unique_id (verified) | Purpose |
|-----------------|-------------|-----------------------------------|---------|
| `battery_soc` | sensor | dict-embedded: `'unique': 'solis_modbus_inverter_battery_soc'` | Current battery level |
| `battery_charge_power` | sensor | `solis_modbus_inverter_battery_charge_power` (derived, clean) | Charge power (W) |
| `battery_discharge_power` | sensor | `solis_modbus_inverter_battery_discharge_power` (derived, clean) | Discharge power (W) |
| `import_power` / `export_power` | sensor | `solis_modbus_inverter_grid_power_net` (derived, clean, signed) | Net grid power (W); both keys map to this entity, split by sign at read time (`grid_power_polarity`) |
| `pv_power` | sensor | `solis_modbus_inverter_dc_power_1` (derived, clean) | PV string 1 power (W) — see known gaps above |
| `local_load_power` | sensor | dict-embedded: `'unique': 'solis_modbus_inverter_household_load_power'` | Home consumption (W) |

**Lifetime energy (optional, all dict-embedded — see "Verified integration bug" above):**

| BESS Sensor Key | solis_modbus `unique` key | Notes |
|-----------------|---------------------------|-------|
| `lifetime_battery_charged` | `solis_modbus_inverter_total_battery_charge_energy` | |
| `lifetime_battery_discharged` | `solis_modbus_inverter_total_battery_discharge_energy` | |
| `lifetime_solar_energy` | `solis_modbus_inverter_pv_total_generation` | |
| `lifetime_import_from_grid` | `solis_modbus_inverter_total_energy_imported_from_grid` | |
| `lifetime_export_to_grid` | `solis_modbus_inverter_total_energy_fed_into_grid` | |

**Grid Time of Use v2 schedule (required, 6 charge + 6 discharge slots):**

| BESS Sensor Key | Entity Type | solis_modbus unique_id | Purpose |
|-----------------|-------------|-------------------------|---------|
| `solis_charge_start_N` (N=1-6) | time | `time_entity_{register}` (registers 43711/43718/43725/43732/43739/43746) | Charge slot N start |
| `solis_charge_end_N` | time | `time_entity_{register}` (43713/43720/43727/43734/43741/43748) | Charge slot N end |
| `solis_charge_enable_N` | switch | `{register}_{bit}` = `43707_0`..`43707_5` | Charge slot N enable |
| `solis_discharge_start_N` | time | `time_entity_{register}` (43753/43760/43767/43774/43781/43788) | Discharge slot N start |
| `solis_discharge_end_N` | time | `time_entity_{register}` (43755/43762/43769/43776/43783/43790) | Discharge slot N end |
| `solis_discharge_enable_N` | switch | `{register}_{bit}` = `43707_6`..`43707_11` | Discharge slot N enable |

Only slot 1 of each direction is strictly required; slots 2-6 are optional
(unused slots are simply left disabled by BESS).

### Huawei LUNA2000 (Local) — `huawei_solar` integration

**Monitoring and schedule control:**

| BESS Sensor Key | Entity Type | huawei_solar Suffix | Purpose |
|-----------------|-------------|---------------------|---------|
| `battery_soc` | sensor | `storage_state_of_capacity` | Current battery level (%) |
| `battery_charge_power` / `battery_discharge_power` | sensor | `storage_charge_discharge_power` (signed, reg 37765) | Battery power (W); both keys map to this entity, split by sign at read time (`battery_power_polarity`, `"charge_positive"` — issue #542) |
| `battery_charging_power_rate` | number | `storage_maximum_charging_power` | Max charge power (W) |
| `battery_discharging_power_rate` | number | `storage_maximum_discharging_power` | Max discharge power (W) |
| `battery_charge_stop_soc` | number | `storage_charging_cutoff_capacity` | Charge stop SOC (%) |
| `battery_discharge_stop_soc` | number | `storage_discharging_cutoff_capacity` | Discharge stop SOC (%) |
| `grid_charge` | switch | `storage_charge_from_grid_function` | Grid charge enable |
| `huawei_working_mode` | select | `storage_working_mode_settings` | Battery working mode (gating TOU writes) |
| `huawei_tou_periods` | sensor | `storage_huawei_luna2000_time_of_use_charging_and_discharging_periods` | Optional: programmed TOU periods, read back at startup (#431) |
| `local_load_power` | sensor | `active_power` | Home consumption (W) |
| `pv_power` | sensor | `input_power` | Real-time solar PV power (W) |
| `import_power` / `export_power` | sensor | `power_meter_active_power` (separate power-meter device, signed) | Net grid power (W); both keys map to this entity, split by sign at read time (`grid_power_polarity`, `"export_positive"` — issue #438) |

**Lifetime energy:** see `HUAWEI_SUFFIX_MAP` in `ha_api_controller.py` for the
five lifetime-energy suffixes added in #471/#473 (not reproduced here to
avoid duplicating a list that will drift — the suffix map is the source of
truth). These map to the same five core energy sensors `EnergyFlowCalculator`
requires on every platform (`energy_flow_calculator.py`), so they're required
for BESS to compute energy flows on Huawei too, same as elsewhere — not
optional. `grid_exported_energy`/`grid_accumulated_energy` specifically come
from the separate power-meter device (see the real-time grid-power row
above); an install with no power meter genuinely cannot report them, and the
health check correctly reports that as an error rather than silently
reporting OK.

**`lifetime_solar_energy` is `total_dc_input_power`, not `accumulated_yield_energy`
(#569) — do not "correct" it back.** The obvious-looking candidate,
`accumulated_yield_energy` (reg 32106, entity "Total yield"), is the inverter's
accumulated AC *output*: on a LUNA2000 hybrid it rises while the battery
discharges and misses everything used to charge it, which upstream states
outright in its README FAQ. Feeding that to `derive_load_consumption`'s
five-term balance inflates home consumption — and therefore `grid_only_cost`
and reported savings — by `battery_discharged - solar_to_battery`, silently,
because the lifetime total stays positive and the health check still passes.
`total_dc_input_power` (reg 32108, entity "Total DC input energy") is the
lifetime integral of reg 32064, already mapped to `pv_power` above. It is
DC-side, so it excludes inverter conversion losses (a systematic ~2-3% bias on
the solar term); Huawei exposes no AC-side PV total at all, so that residual is
irreducible. FusionSolar's own reconstruction
(`yield - discharge + charge`) is **not** a valid alternative here: it assumes
all battery charge came from PV, and BESS grid-charges for arbitrage, so it
would report grid-charged energy as solar production.

Note the suffix collision this creates: `..._total_dc_input_power` also ends in
`_input_power`. The two stay apart only because `_map_registry_entities` sorts
suffixes longest-first before breaking on the first match.

**Auto-detection:** `HUAWEI_SUFFIX_MAP` is wired into `discover_sensors_from_registry`
(the same production entity-registry scan every other platform uses — fixed
in #438; previously this map had no caller there and every Huawei sensor
required manual entity entry). Presence of `huawei_solar` integration entities
with the `storage_working_mode_settings` unique_id suffix triggers Huawei
platform detection; the setup wizard confirms the battery model is LUNA2000
via `get_huawei_working_mode_options()` before proceeding.

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

3. **solis_modbus detected** (`platform: solis_modbus`, its own dedicated
   integration domain — no sub-variant disambiguation needed): confirmed
   further by checking for the `time_entity_43711` unique_id suffix (Grid
   Time of Use v2 Charge Start, Slot 1) — if absent, the installed
   inverter/firmware lacks the v2 schedule and schedule control is
   unavailable (monitoring sensors are still mapped).

4. **huawei_solar detected** (`platform: huawei_solar`):
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
