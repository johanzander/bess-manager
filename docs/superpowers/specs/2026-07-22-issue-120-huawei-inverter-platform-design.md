# Huawei Inverter Platform — Design (Issue #120)

## Context

Issue #120: a Huawei-inverter user in Sweden volunteered to test support.
There is no debug log yet — no entity registry, no battery model, no HA
`huawei_solar` integration version. This design produces the **Phase 1**
implementation (per the `add-inverter-platform` skill): a source-derived
controller + detection + fixtures, ready to ship experimental, so the
reporter can install and test immediately rather than waiting on a
back-and-forth to gather details first.

Huawei is placed on `docs/INVERTER_PLATFORMS.md`'s two control axes as
**TX-Vendor-service × SM-Period-lists**: a new local-Modbus vendor
integration (`huawei_solar`), controlled via a persistent multi-period
charge/discharge list (`huawei_solar.set_tou_periods`), gated behind a
working-mode select — the same shape as Growatt SPH's period lists, not
SolaX's ephemeral per-period commands. The rationale for that placement is
below.

## Research: what the integration actually offers

Source: `wlcrs/huawei_solar` (HA integration, 911★, `DOMAIN = "huawei_solar"`)
+ `wlcrs/huawei-solar-lib` (the underlying register library it depends on).

### Two write paths exist, not one

The integration registers 12 services. Two are relevant to a scheduled
charge/discharge plan:

- **`huawei_solar.set_tou_periods`** — writes a **persistent, multi-period**
  charge/discharge list to the battery's TOU register (`set_battery_tou_periods`
  in `services.py`), keyed by `device_id` (HA device-registry ID of the
  **battery** device, not the inverter). For Huawei LUNA2000 batteries, each
  period is a text line `"HH:MM-HH:MM/<days>/<+|->"` where `+` = charge,
  `-` = discharge, `<days>` is a digit string (Sunday=0..Saturday=6, e.g.
  `1234567` for all days — actually digits index `% 7`, verify exact digit
  convention against the reporter's HA version before shipping). Max
  **14 periods** (`HUAWEI_LUNA2000_TOU_PERIODS = 14` in
  `register_definitions/periods.py`). This register only takes effect while
  the battery's **working mode** is `TIME_OF_USE_LUNA2000`.
- **`huawei_solar.forcible_charge_soc`** / **`forcible_discharge_soc`** /
  **`stop_forcible_charge`** — duration- or SOC-target-bounded ephemeral
  commands, also keyed by `device_id`. No persistent state; re-issued per
  control interval by the caller.

### Scheduling model: SM-Period-lists, not SM-Ephemeral

BESS's `InverterController` ABC is **agnostic** between persistent-schedule
control (`GrowattMinController`, `GrowattSphController`) and ephemeral
per-period control (`SolaxController`) — it already supports both models, so
this is a design choice for Huawei specifically, not something the
architecture forces. Two real-world projects independently chose
differently, for reasons tied to their own design:

- **Predbat** (`springfall2008/batpred`), a generic optimizer supporting ~20
  inverter brands behind one abstraction, replans every 5–30 min and uses
  `forcible_charge_soc` / `forcible_discharge_soc` / `stop_forcible_charge`
  exclusively for Huawei (`templates/huawei.yaml`). Fits Predbat's model: no
  persistent per-brand plan, just "what should the battery be doing right
  now," reissued continuously across many brands behind one abstraction.
- **hsem** (`woopstar/hsem`), a Huawei-only energy manager that computes a
  plan and writes it down (architecturally the closest existing analog to
  BESS), does the opposite: sets the working-mode select to
  `TIME_OF_USE_LUNA2000` and writes the day's charge/discharge windows via
  `set_tou_periods` (`custom_sensors/applier.py`), using `forcible_discharge`
  only as a situational override (forcing export of excess battery on top of
  the base plan), never as the primary mechanism.

### Flash/NVM write-wear

Huawei is **local Modbus** (`manifest.json`: `"iot_class": "local_polling"`;
README: *"exposes... functions... over Modbus"*), the same low-latency local
transport that makes Growatt GEN4's RAM-backed VPP path attractive for
sub-period reactive control (`ems_charging_rate`/`ems_discharging_rate` are
flash-backed; `growatt_vpp_power`/`growatt_vpp_time` are RAM-backed and safe
to rewrite every 15-min period — the documented basis for BESS's plan to move
GEN4 off TOU and onto VPP once validated, per `INVERTER_PLATFORMS.md`). The
same question applies here: does Huawei expose an equivalent RAM-backed path
for battery dispatch?

- Huawei's Modbus spec **does** distinguish persistent vs non-persistent
  registers in at least one documented case: open feature request
  [wlcrs/huawei_solar#1321](https://github.com/wlcrs/huawei_solar/issues/1321)
  (still unimplemented) asks for exposing "Remote Output Control" (Active
  Power Control Mode = 6) as a **non-persistent** alternative to the existing
  power-derating services, explicitly because *"each of those writes goes to
  NVM, and Huawei's own Modbus spec distinguishes between the persistent
  derating registers and a non-persistent 'Remote output control' path
  precisely because the persistent ones aren't designed for frequent
  updates."* This confirms the general mechanism exists on this hardware
  family — but for **power output derating/curtailment, not battery
  charge/discharge scheduling**.
- For the battery registers specifically, the integration's own coordinator
  wiring is the best available signal, and it points the other way from what
  the local-Modbus argument would hope: `services.py`'s `forcible_charge`
  handler writes `STORAGE_FORCIBLE_CHARGE_POWER`,
  `STORAGE_FORCED_CHARGING_AND_DISCHARGING_PERIOD`,
  `STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE`, and
  `STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE`, then calls
  `dd.configuration_update_coordinator.async_refresh()` — the **same**
  15-minute-interval coordinator group (`CONFIGURATION_UPDATE_INTERVAL`,
  `const.py`) that the working-mode select and, by construction, the TOU
  register belong to (`select.py` marks `STORAGE_WORKING_MODE_SETTINGS` as
  `EntityCategory.CONFIG`; `const.py`'s comment on that interval reads
  *"configuration can only change when edited through FusionSolar web or
  app"*). There is a **separate, faster** `energy_storage_update_coordinator`
  (`ENERGY_STORAGE_UPDATE_INTERVAL`, 30s) for live operational data, and
  `forcible_charge` is not wired to it.
- `forcible_charge`/`forcible_discharge` appear to hit the **same register
  class as `set_tou_periods`**, not a distinct RAM-backed fast path the way
  `growatt_vpp_power` is distinct from `ems_charging_rate`. This is
  **inferred from which coordinator the integration's author chose to
  refresh after the write, not a vendor Modbus-spec citation** — a strong
  signal (no reason to refresh the slow "rarely changes" group after a
  fast-changing write) but not proof. No evidence of a Huawei equivalent to
  Growatt's VPP register was found for battery dispatch specifically.

The local-Modbus/low-latency argument for ephemeral control is sound in
principle, and mirrors real reasoning BESS already applies to Growatt GEN4.
But unlike Growatt, where the RAM-backed path is documented and already the
basis of a stated migration plan, **no evidence currently available shows
Huawei exposes a lower-wear path for battery charge/discharge specifically**
— `forcible_charge` looks, from the coordinator wiring, like it writes to
the same class of register as the persistent TOU list. Open item #5 below
tracks re-examining this once better evidence exists.

### Write frequency

BESS's scheduler recomputes the DP plan every 15 minutes
(`update_schedule_quarterly`, `backend/app.py:319`). For persistent-schedule
inverters, the **hardware write is debounced**:
`battery_system_manager.py`'s `_should_apply_schedule` (~line 669) only
triggers `_apply_schedule` (the full TOU/period-list write) when the
computed plan actually changed from what's on hardware — most 15-min ticks
don't write at all. Ephemeral inverters (SolaX today) have no persistent
state to diff against, so `_apply_period_schedule` fires **unconditionally
every 15-min period** (`battery_system_manager.py:712`).

Applied to Huawei: `set_tou_periods` (persistent) follows the debounced
pattern — writes only when the plan changes. `forcible_charge`/
`forcible_discharge` (ephemeral) would need the SolaX-style unconditional
per-quarter reissue, since there's nothing to diff against. Combined with the
coordinator-grouping evidence above (both paths look like the same register
class), the debounced persistent write is the lower-wear choice on current
evidence.

### Chosen write path

`set_tou_periods` + working-mode select is the primary write path — matching
hsem's model, Growatt SPH's existing `SM-Period-lists` pattern in BESS, and
the wear/frequency reasoning above. `forcible_charge`/`forcible_discharge`/
`stop_forcible_charge` are documented as a possible future mechanism (e.g. an
immediate manual override outside the plan, or if a genuinely volatile
register is confirmed later — see open item #5) but **not built in this
pass** — no BESS use case needs them yet, and building unused code paths
violates `CLAUDE.md`'s scope discipline.

### Battery scope: LUNA2000 only

The integration supports two battery families with incompatible TOU period
formats:

- **LUNA2000**: explicit `charge_flag` (`+`/`-`) per period — a direct
  instruction, exactly what BESS's DP schedule already produces.
- **LG RESU**: each period carries an `electricity_price` instead of a
  charge/discharge flag — the inverter runs its own internal price-bidding
  logic to decide charge/discharge. This is a fundamentally different
  control model (the inverter, not BESS, makes the dispatch decision) and
  isn't compatible with BESS owning the optimization.

**This design supports LUNA2000 control only.** LG RESU setups fall back to
**monitoring-only**, the same precedent as Growatt GEN3 — detected and
reported, schedule control explicitly raises "not yet implemented."
`device.battery_type` (`StorageProductModel.HUAWEI_LUNA2000` vs `LG_RESU`)
is available from the coordinator and drives this branch.

### Working-mode control

`select.STORAGE_WORKING_MODE_SETTINGS` (unique_id suffix
`storage_working_mode_settings`) is a **standard HA select entity** — BESS
writes it with the standard `select.select_option` service, not a
`huawei_solar`-specific call. Options are `StorageWorkingModesC` values
(`adaptive`, `fixed_charge_discharge`, `maximise_self_consumption`,
`time_of_use_lg`, `fully_fed_to_grid`, `time_of_use_luna2000`), lowercased.
BESS sets `time_of_use_luna2000` once (or whenever drifted) before/alongside
writing periods, mirroring how `GrowattSphController` doesn't need to touch
a mode entity because SPH's period lists are always active — Huawei's
period list is gated behind this mode selection, which is the delta.

### Entity `unique_id` pattern (verified from source)

All Huawei entities use `f"{device.serial_number}_{register_key}"`
(`select.py:204`, `number.py:358`, `switch.py:200`) — **not** an
`entity_id`-derived pattern, and **no shared prefix constant** across entity
types (unlike Growatt's `-tlx_`/`-mix_` prefixes). Detection must match on
the HA entity registry's `platform == "huawei_solar"` field plus a marker
suffix, not on `unique_id` structure alone.

Relevant register keys (from `huawei-solar-lib/register_names.py`,
confirmed present in `select.py`/`number.py`/`sensor.py`):

| BESS sensor key | Register key (`unique_id` suffix) | Entity type | Source |
|---|---|---|---|
| Battery SOC | `storage_state_of_capacity` | sensor | `sensor.py:654` |
| Battery charge/discharge power | `storage_charge_discharge_power` | sensor | `sensor.py:678` |
| Max charge power | `storage_maximum_charging_power` | number | `number.py:140` |
| Max discharge power | `storage_maximum_discharging_power` | number | `number.py:148` |
| Charging cutoff SOC (charge-stop) | `storage_charging_cutoff_capacity` | number | `number.py:156` |
| Grid-charge cutoff SOC (reserve) | `storage_grid_charge_cutoff_state_of_charge` | number | `number.py:175` |
| Grid-charge enable | `storage_charge_from_grid_function` | switch | `switch.py:72` |
| Working mode (marker + control) | `storage_working_mode_settings` | select | `select.py:301` |
| Inverter AC output power | `active_power` | sensor | `sensor.py:189` |
| Grid import/export power | requires the separate power-meter device's `active_power`/exported-energy entities — verify against the reporter's actual meter setup | sensor | `sensor.py` (power meter block) |

`storage_working_mode_settings` only exists on battery-equipped installs —
this is the detection marker suffix (`_HUAWEI_BATTERY_MARKER_SUFFIX`),
parallel to `_SOLAX_NATIVE_MARKER_SUFFIX`.

### `device_id` resolution for service calls

`set_tou_periods` (and the ephemeral services, if built later) take
`device_id` — the HA **device-registry ID of the battery device**
specifically (`services.yaml`: `model: "Batteries"`), not the inverter
device, and not an `entity_id`. This matches BESS's existing
`growatt_device_id` pattern exactly
(`ha_api_controller.py:discover_ha_metadata`/`_parse_ha_metadata`): a
config-entry-domain match (`huawei_solar`) against the WS
`config/device_registry/list` result, auto-discovered during setup and
stored in settings, with a manual-entry fallback. The one difference: the
`huawei_solar` integration creates **multiple devices** per config entry
(inverter, battery pack, power meter, optionally EMMA) — the device-registry
match must additionally filter on device `model == "Batteries"` (or match by
which device owns the `storage_working_mode_settings` entity) to pick the
right one, unlike Growatt where the config entry maps to a single device.

## Architecture

### New file: `core/bess/huawei_controller.py`

`HuaweiController(InverterController)`, modeled on `GrowattSphController`
for the period-list shape (`MAX_TOU_PERIODS = 14`, build charge/discharge
period objects from the DP schedule's active intervals) crossed with
`SolaxController` for the vendor-service call plumbing (this is the "first
platform on a third integration" case flagged in `INVERTER_PLATFORMS.md`).

- `create_schedule` — group the DP schedule's per-period intents into
  charge/discharge windows (reuse the same intent→period grouping logic
  `GrowattSphController` already has for GRID_CHARGING/LOAD_SUPPORT/
  BATTERY_EXPORT; SOLAR_STORAGE/IDLE need no period — self-consumption is
  the mode's default between listed periods, same assumption as SPH).
- `write_schedule_to_hardware` — (1) `select.select_option` on the working-
  mode entity if not already `time_of_use_luna2000`; (2) `huawei_solar.set_tou_periods`
  with `device_id` + the newline-joined period text.
- `sync_soc_limits` — `number.set_value` on
  `storage_charging_cutoff_capacity` / `storage_grid_charge_cutoff_state_of_charge`.
- `compare_schedules`, `active_tou_intervals`, `get_all_tou_segments`,
  `get_daily_TOU_settings`, `log_current_TOU_schedule`,
  `log_detailed_schedule`, `check_health` — same shape as
  `GrowattSphController`'s, since the underlying model (persistent period
  list, no per-period live write) is the same.
- **No silent fallbacks**: if the detected battery is LG RESU, or the
  working-mode entity/`storage_working_mode_settings` unique_id isn't found,
  raise from the write path with a clear "control not implemented for this
  battery type" error — do not attempt a `set_tou_periods` call that would
  silently no-op or corrupt the LG RESU price-period register.

### Wiring changes

- `battery_system_manager.py`: `_create_inverter_controller()` branch for
  `"huawei"`; `VALID_PLATFORMS` += `"huawei"`; `_INVERTER_TYPE_TO_PLATFORM["huawei"] = "huawei"`.
- `backend/settings_store.py`: `VALID_PLATFORMS` at **both** L35 and L58
  (known duplication, per the skill's checklist).
- `ha_api_controller.py`:
  - `HUAWEI_SUFFIX_MAP` (table above).
  - `_HUAWEI_BATTERY_MARKER_SUFFIX = "storage_working_mode_settings"`.
  - `_INVERTER_PLATFORMS["huawei"] = ["huawei_solar"]`.
  - Detection branch in `detect_inverter_integrations()` / `_detect_platforms()`
    matching `platform == "huawei_solar"` + marker suffix present; branch
    the LUNA2000-vs-LG-RESU distinction here too (via `device.battery_type`,
    surfaced through whichever coordinator/device-info field
    `sensor.py`/`select.py` expose — confirm exact field name during
    implementation, this is read from the library, not hand-derived).
  - Extend `discover_ha_metadata`/`_parse_ha_metadata` with a
    `huawei_device_id` result, filtered to the config entry's **battery**
    device (`model == "Batteries"`) as described above.
- `debug_data_exporter.py`: include the Huawei entities so the reporter's
  first debug bundle captures everything needed to build the real fixture.

### Frontend

Same three-file pattern as every other platform (`SetupWizardPage.tsx`,
`SettingsPage.tsx`, `SensorConfigSection.tsx` + `sensorDefinitions.ts`) —
no new UI concepts, just a new platform entry and its required-sensor list
per the table above.

## Regression fixtures (Phase 1, per the skill)

No real registry exists yet. Build a **source-derived** fixture: a
`solax`/`growatt`-style mock entity registry with `platform: "huawei_solar"`
entities using the verified `{serial_number}_{register_key}` unique_ids from
the table above, one LUNA2000 battery, one inverter, one power meter device.
Drives:

- `test_huawei_controller.py` (new) — schedule build, `set_tou_periods`
  payload shape, working-mode write, missing-entity/LG-RESU failure paths.
- A `huawei` case in `test_registry_discovery.py` / `test_scenario_discovery.py`.
- `scripts/mock_ha/scenarios/ci-wizard-huawei.json` + `wizard-expectations.ts`
  + `setup-wizard.spec.ts` entry + `run-e2e.sh`/`ci.yml` scenario wiring.

**Phase 2** (when the reporter's debug log arrives) replaces this fixture
with their real registry via `from_debug_log.py`, confirms the exact
`days_effective` digit convention and the working-mode option casing against
a live install, and is the point at which any bugs loop back through
`add-inverter-platform` for a minimal fix — not this design.

## Docs

- `INVERTER_PLATFORMS.md`: update the Huawei coordinate row from
  "SM-Ephemeral" to **TX-Vendor-service × SM-Period-lists**, add it to the
  "five platforms" coordinate table, add a "How BESS Controls" section with
  the `set_tou_periods` payload shape and the LUNA2000-only scope note.
- `README.md`: add Huawei to supported platforms, marked experimental.
- `CHANGELOG.md`: entry under `## [Unreleased]`.
- Maturity memory: record Huawei as experimental/not real-world tested
  until the reporter confirms (same convention as GEN3/SolaX VPP).

## Open items to confirm once the reporter's debug log arrives

1. Exact `days_effective` digit convention in the `set_tou_periods` text
   format (`_parse_days_effective` does `int(day) % 7` — confirm which
   digit maps to which weekday against a live write, not just source
   reading).
2. Behavior of hours **not** covered by any TOU period while working mode is
   `time_of_use_luna2000` — assumed to default to self-consumption
   (matching the SPH assumption already in BESS), not verified against
   hardware.
3. Which `huawei_solar` integration version / HA core version the reporter
   runs — the service/entity shapes above are as of `wlcrs/huawei_solar`
   `main` (manifest version `2.1.1`); older installs may differ.
4. Whether the reporter's setup has a separate power-meter device for
   grid import/export, and its entity registry field names.
5. Whether `STORAGE_FORCIBLE_CHARGE_POWER`/`STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE`
   are genuinely volatile (RAM-backed) despite being wired to the
   `configuration_update_coordinator` refresh in `services.py` — this
   analysis relied on coordinator grouping as a proxy for persistence class,
   not a citation from Huawei's official Modbus register spec (not
   consulted directly). If this were confirmed volatile, it would be grounds
   to revisit the ephemeral-controller alternative for a future revision.
