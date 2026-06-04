---
name: solax_modbus unique_id format
description: How solax_modbus constructs entity unique_ids — critical for suffix map keys
type: reference
---

## solax_modbus unique_id format

**Format:** `{user_chosen_device_name}_{register_key}`

- The **prefix** (`user_chosen_device_name`) is whatever the user typed as `CONF_NAME`
  during solax_modbus setup. Default is `"SolaX"` but users change it freely.
  Examples from production: `solax`, `SolaXA`, `Growatt_Modbus`, `My Inverter`.

- The **register key** (e.g. `battery_soc`, `time_1_enabled`, `charger_switch`)
  is fixed in the solax_modbus plugin code (`entity_description.key`) and is
  NOT user-configurable.

- The serial number is NOT part of the unique_id.

**Source:** `wills106/homeassistant-solax-modbus` — `SolaXModbusSensor.unique_id`
property in `sensor.py`: `f"{self._platform_name}_{self.entity_description.key}"`.

## Implications for BESS Manager suffix maps

The suffix maps (`SOLAX_GROWATT_MIN_SUFFIX_MAP`, `SOLAX_GROWATT_SPH_SUFFIX_MAP`,
`SOLAX_NATIVE_SUFFIX_MAP`) must use **only the register key** as the map key,
never the device name prefix.

**Correct:** `"battery_soc": "battery_soc"`
**Wrong:** `"solax_battery_soc": "battery_soc"` (only works if user named device "solax")

The matching code in `_map_entities_to_sensors()` uses `endswith(f"_{suffix}")`
which correctly strips any device name prefix.

The TOU/GEN3 marker suffixes (`_GROWATT_TOU_MARKER_SUFFIX = "time_1_enabled"`)
already follow this pattern correctly.

## Known production examples

| User   | Device name | Example unique_id          | Register key       |
|--------|-------------|----------------------------|--------------------|
| Niklas | `solax`     | `solax_battery_soc`        | `battery_soc`      |
| Hans   | `SolaXA`    | `SolaXA_battery_soc`       | `battery_soc`      |
