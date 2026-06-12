// Shared sensor integration definitions — used by SetupWizardPage and SettingsPage.

export interface SensorDef {
  key: string;
  label: string;
  required: boolean;
}

export interface SensorGroup {
  name: string;
  sensors: SensorDef[];
}

export interface IntegrationDef {
  id: string;
  name: string;
  required: boolean;
  description: string;
  sensorGroups: SensorGroup[];
}

// Platform IDs — one consistent string used everywhere.
// Maps platform → integration section ID (used to show the right sensor form).
export const INVERTER_INTEGRATION_IDS: Record<string, string> = {
  growatt_server_min: 'growatt_server_min',
  growatt_server_sph: 'growatt_server_sph',
  solax_modbus_growatt_min: 'solax_modbus_growatt_min',
  solax_modbus_growatt_sph: 'solax_modbus_growatt_sph',
  solax_modbus_native: 'solax_modbus_native',
  huawei_solar: 'huawei_solar',
};

// Platform IDs are now used consistently at all layers — no conversion needed.

// All valid platform IDs.
export const VALID_PLATFORMS = [
  'growatt_server_min',
  'growatt_server_sph',
  'solax_modbus_growatt_min',
  'solax_modbus_growatt_sph',
  'solax_modbus_native',
  'huawei_solar',
] as const;

export type PlatformId = typeof VALID_PLATFORMS[number];

/**
 * Per-platform sensor storage structure (mirrors backend settings_store).
 * Each platform has its own independent sensor dict. Switching platform
 * just changes the `platform` field — no clearing or swapping.
 */
export interface PerPlatformSensors {
  [key: string]: string | Record<string, string>;
  platform: string;
  growatt_server_min: Record<string, string>;
  growatt_server_sph: Record<string, string>;
  solax_modbus_growatt_min: Record<string, string>;
  solax_modbus_growatt_sph: Record<string, string>;
  solax_modbus_native: Record<string, string>;
  huawei_solar: Record<string, string>;
  shared: Record<string, string>;
}

/** IDs of non-inverter (shared) integrations. */
export const SHARED_INTEGRATION_IDS = new Set([
  'nordpool', 'solar_forecast', 'consumption_forecast',
  'phase_current', 'discharge_inhibit', 'weather',
]);

/** Create an empty per-platform sensors structure. */
export function emptyPerPlatformSensors(platform = ''): PerPlatformSensors {
  return {
    platform,
    growatt_server_min: {},
    growatt_server_sph: {},
    solax_modbus_growatt_min: {},
    solax_modbus_growatt_sph: {},
    solax_modbus_native: {},
    huawei_solar: {},
    shared: {},
  };
}

/**
 * Merge the active platform's sensors with shared sensors into a flat dict.
 * Used when sending data to the backend (setup_complete) and for
 * checking if required sensors are filled.
 */
export function getActiveSensorsFlat(sensors: PerPlatformSensors): Record<string, string> {
  const platform = sensors.platform as PlatformId;
  return {
    ...(sensors.shared ?? {}),
    ...(sensors[platform] ?? {}),
  };
}

// Shared sensor groups used by multiple Growatt platforms.
const GROWATT_POWER_MONITORING: SensorGroup = {
  name: 'Power Monitoring',
  sensors: [
    { key: 'pv_power', label: 'Solar PV Power', required: false },
    { key: 'local_load_power', label: 'Local Load Power', required: false },
    { key: 'import_power', label: 'Grid Import Power', required: false },
    { key: 'export_power', label: 'Grid Export Power', required: false },
  ],
};

const GROWATT_CLOUD_LIFETIME: SensorGroup = {
  name: 'Lifetime Energy Totals',
  sensors: [
    { key: 'lifetime_battery_charged', label: 'Total Battery Charged', required: true },
    { key: 'lifetime_battery_discharged', label: 'Total Battery Discharged', required: true },
    { key: 'lifetime_solar_energy', label: 'Total Solar Energy', required: true },
    { key: 'lifetime_export_to_grid', label: 'Total Export to Grid', required: true },
    { key: 'lifetime_import_from_grid', label: 'Total Import from Grid', required: true },
    { key: 'lifetime_load_consumption', label: 'Total Load Consumption', required: true },
  ],
};

// MIN cloud: uses entity-based SOC limits, power rates, and grid_charge
const GROWATT_CLOUD_MIN_SENSOR_GROUPS: SensorGroup[] = [
  {
    name: 'Battery Control',
    sensors: [
      { key: 'battery_soc', label: 'State of Charge (SOC)', required: true },
      { key: 'battery_charge_power', label: 'Charging Power', required: true },
      { key: 'battery_discharge_power', label: 'Discharging Power', required: true },
      { key: 'battery_charge_stop_soc', label: 'Charge Stop SOC', required: true },
      { key: 'battery_discharge_stop_soc', label: 'Discharge Stop SOC', required: true },
      { key: 'battery_charging_power_rate', label: 'Charging Power Rate', required: true },
      { key: 'battery_discharging_power_rate', label: 'Discharging Power Rate', required: true },
      { key: 'grid_charge', label: 'Grid Charge Enable', required: true },
    ],
  },
  GROWATT_POWER_MONITORING,
  GROWATT_CLOUD_LIFETIME,
];

// SPH cloud: the growatt_server integration exposes NO number or switch
// entities for SPH — all control is via service calls (write_ac_charge_times,
// write_ac_discharge_times).  Only sensors (SOC, power, lifetime) exist.
// SPH also lacks local_load_power (no pac_to_local_load register),
// lifetime_system_production, and lifetime_self_consumption.
const GROWATT_CLOUD_SPH_POWER_MONITORING: SensorGroup = {
  name: 'Power Monitoring',
  sensors: [
    { key: 'pv_power', label: 'Solar PV Power', required: false },
    { key: 'import_power', label: 'Grid Import Power', required: false },
    { key: 'export_power', label: 'Grid Export Power', required: false },
  ],
};

const GROWATT_CLOUD_SPH_LIFETIME: SensorGroup = {
  name: 'Lifetime Energy Totals',
  sensors: [
    { key: 'lifetime_battery_charged', label: 'Total Battery Charged', required: true },
    { key: 'lifetime_battery_discharged', label: 'Total Battery Discharged', required: true },
    { key: 'lifetime_solar_energy', label: 'Total Solar Energy', required: true },
    { key: 'lifetime_export_to_grid', label: 'Total Export to Grid', required: true },
    { key: 'lifetime_import_from_grid', label: 'Total Import from Grid', required: true },
    { key: 'lifetime_load_consumption', label: 'Total Load Consumption', required: true },
  ],
};

const GROWATT_CLOUD_SPH_SENSOR_GROUPS: SensorGroup[] = [
  {
    name: 'Battery Monitoring',
    sensors: [
      { key: 'battery_soc', label: 'State of Charge (SOC)', required: true },
      { key: 'battery_charge_power', label: 'Charging Power', required: true },
      { key: 'battery_discharge_power', label: 'Discharging Power', required: true },
    ],
  },
  GROWATT_CLOUD_SPH_POWER_MONITORING,
  GROWATT_CLOUD_SPH_LIFETIME,
];

export const INTEGRATIONS: IntegrationDef[] = [

  {
    id: 'huawei_solar',
    name: 'Huawei Solar (Experimental — read-only)',
    required: true,
    description: 'Experimental read-only Huawei Solar support. Battery, grid, PV, and calculated house-load monitoring are supported; an optional direct house-load sensor can be used when available. Active battery control is not implemented and no Huawei settings or entities will be written.',
    sensorGroups: [
      {
        name: 'Raw Huawei Inputs',
        sensors: [
          { key: 'battery_soc', label: 'Battery SOC', required: true },
          { key: 'huawei_battery_power', label: 'Battery Charge/Discharge Power (signed)', required: true },
          { key: 'huawei_grid_power', label: 'Grid Active Power (signed)', required: true },
          { key: 'pv_power', label: 'Inverter Input Power (PV)', required: true },
        ],
      },
      {
        name: 'Optional Direct House Load',
        sensors: [
          { key: 'huawei_house_load_power_entity', label: 'House Load Power', required: false },
        ],
      },
    ],
  },
  {
    id: 'growatt_server_min',
    name: 'Growatt Cloud (MIN)',
    required: true,
    description: 'Growatt MIN inverter controlled via the Growatt Server cloud integration',
    sensorGroups: GROWATT_CLOUD_MIN_SENSOR_GROUPS,
  },
  {
    id: 'growatt_server_sph',
    name: 'Growatt Cloud (SPH)',
    required: true,
    description: 'Growatt SPH inverter controlled via the Growatt Server cloud integration',
    sensorGroups: GROWATT_CLOUD_SPH_SENSOR_GROUPS,
  },
  {
    id: 'solax_modbus_native',
    name: 'SolaX Modbus (Native)',
    required: true,
    description: 'Native SolaX inverter controlled via VPP active-power commands (not for Growatt inverters)',
    sensorGroups: [
      {
        name: 'Battery Monitoring',
        sensors: [
          { key: 'battery_soc', label: 'Battery Capacity (SOC)', required: true },
          { key: 'battery_charge_power', label: 'Battery Charge Power', required: true },
          { key: 'battery_discharge_power', label: 'Battery Discharge Power', required: true },
        ],
      },
      {
        name: 'Power Monitoring',
        sensors: [
          { key: 'pv_power', label: 'PV Power', required: false },
          { key: 'local_load_power', label: 'House Load', required: false },
          { key: 'import_power', label: 'Measured Power (Grid)', required: false },
          { key: 'export_power', label: 'Grid Export Power', required: false },
        ],
      },
      {
        name: 'Lifetime Energy',
        sensors: [
          { key: 'lifetime_battery_charged', label: 'Battery Input Energy Total', required: false },
          { key: 'lifetime_battery_discharged', label: 'Battery Output Energy Total', required: false },
          { key: 'lifetime_solar_energy', label: 'Total Solar Energy', required: false },
          { key: 'lifetime_import_from_grid', label: 'Grid Import Total', required: false },
          { key: 'lifetime_export_to_grid', label: 'Grid Export Total', required: false },
        ],
      },
      {
        name: 'VPP Control',
        sensors: [
          { key: 'solax_power_control_mode', label: 'Power Control Mode', required: true },
          { key: 'solax_active_power', label: 'Active Power Target', required: true },
          { key: 'solax_autorepeat_duration', label: 'Autorepeat Duration', required: true },
          { key: 'solax_power_control_trigger', label: 'Power Control Trigger', required: true },
          { key: 'solax_battery_min_soc', label: 'Battery Minimum SOC', required: true },
          { key: 'solax_charger_use_mode', label: 'Charger Use Mode', required: false },
        ],
      },
    ],
  },
  {
    id: 'solax_modbus_growatt_min',
    name: 'SolaX Modbus (Growatt MIN)',
    required: true,
    description: 'Growatt MIN inverter controlled via the homeassistant-solax-modbus Growatt plugin (local Modbus, TOU entity writes)',
    sensorGroups: [
      {
        name: 'Battery Monitoring',
        sensors: [
          { key: 'battery_soc', label: 'Battery Capacity (SOC)', required: true },
          { key: 'battery_charge_power', label: 'Battery Charge Power', required: true },
          { key: 'battery_discharge_power', label: 'Battery Discharge Power', required: true },
        ],
      },
      {
        name: 'EMS Control',
        sensors: [
          { key: 'battery_charging_power_rate', label: 'EMS Charging Rate', required: true },
          { key: 'battery_discharging_power_rate', label: 'EMS Discharging Rate', required: true },
          { key: 'battery_charge_stop_soc', label: 'EMS Charging Stop SOC', required: true },
          { key: 'battery_discharge_stop_soc', label: 'EMS Discharging Stop SOC', required: true },
          { key: 'grid_charge', label: 'Grid Charge Switch', required: true },
        ],
      },
      {
        name: 'Power Monitoring',
        sensors: [
          { key: 'pv_power', label: 'PV Power', required: false },
          { key: 'local_load_power', label: 'House Load', required: false },
          { key: 'import_power', label: 'Measured Power (Grid)', required: false },
          { key: 'export_power', label: 'Grid Export Power', required: false },
        ],
      },
      {
        name: 'Lifetime Energy',
        sensors: [
          { key: 'lifetime_battery_charged', label: 'Battery Input Energy Total', required: false },
          { key: 'lifetime_battery_discharged', label: 'Battery Output Energy Total', required: false },
          { key: 'lifetime_solar_energy', label: 'Total Solar Energy', required: false },
          { key: 'lifetime_import_from_grid', label: 'Grid Import Total', required: false },
          { key: 'lifetime_export_to_grid', label: 'Grid Export Total', required: false },
          { key: 'lifetime_load_consumption', label: 'Total Load Energy', required: false },
        ],
      },
      {
        name: 'TOU Schedule',
        sensors: [
          { key: 'tou_time_1_enabled', label: 'Time Slot 1 Enabled', required: true },
          { key: 'tou_time_1_begin', label: 'Time Slot 1 Begin', required: true },
          { key: 'tou_time_1_end', label: 'Time Slot 1 End', required: true },
          { key: 'tou_time_1_mode', label: 'Time Slot 1 Mode', required: true },
          { key: 'tou_time_1_update', label: 'Time Slot 1 Update', required: true },
        ],
      },
    ],
  },
  {
    id: 'solax_modbus_growatt_sph',
    name: 'SolaX Modbus (Growatt SPH)',
    required: true,
    description: 'Growatt MIX/SPA/SPH inverter (GEN3) controlled via the homeassistant-solax-modbus Growatt plugin (local Modbus)',
    sensorGroups: [
      {
        name: 'Battery Monitoring',
        sensors: [
          { key: 'battery_soc', label: 'Battery Capacity (SOC)', required: true },
          { key: 'battery_charge_power', label: 'Battery Charge Power', required: true },
          { key: 'battery_discharge_power', label: 'Battery Discharge Power', required: true },
        ],
      },
      {
        name: 'EMS Control',
        sensors: [
          { key: 'battery_charging_power_rate', label: 'Battery First Charge Rate', required: true },
          { key: 'battery_discharging_power_rate', label: 'Grid First Discharge Rate', required: true },
          { key: 'battery_charge_stop_soc', label: 'Battery First Maximum SOC', required: true },
          { key: 'battery_discharge_stop_soc', label: 'Load First Battery Minimum SOC', required: true },
          { key: 'grid_charge', label: 'Charger Switch', required: true },
        ],
      },
      {
        name: 'Power Monitoring',
        sensors: [
          { key: 'pv_power', label: 'PV Power', required: false },
          { key: 'local_load_power', label: 'House Load', required: false },
          { key: 'import_power', label: 'Measured Power (Grid)', required: false },
          { key: 'export_power', label: 'Grid Export Power', required: false },
        ],
      },
      {
        name: 'Lifetime Energy',
        sensors: [
          { key: 'lifetime_battery_charged', label: 'Battery Input Energy Total', required: false },
          { key: 'lifetime_battery_discharged', label: 'Battery Output Energy Total', required: false },
          { key: 'lifetime_solar_energy', label: 'Total Solar Energy', required: false },
          { key: 'lifetime_import_from_grid', label: 'Grid Import Total', required: false },
          { key: 'lifetime_export_to_grid', label: 'Grid Export Total', required: false },
          { key: 'lifetime_load_consumption', label: 'Total Load', required: false },
        ],
      },
    ],
  },
  {
    id: 'nordpool',
    name: 'Nord Pool Official',
    required: true,
    description: 'Electricity spot price data (HA Nord Pool official integration — config entry ID is auto-detected from the integration credentials)',
    sensorGroups: [],
  },
  {
    id: 'solar_forecast',
    name: 'Solar Forecast (Solcast)',
    required: false,
    description: 'PV production forecast (Solcast for Home Assistant integration) — used to plan charge/discharge strategy around expected solar',
    sensorGroups: [
      {
        name: 'Daily Forecasts',
        sensors: [
          { key: 'solar_forecast_today', label: 'Forecast Today (kWh)', required: false },
          { key: 'solar_forecast_tomorrow', label: 'Forecast Tomorrow (kWh)', required: false },
        ],
      },
    ],
  },
  {
    id: 'consumption_forecast',
    name: 'Consumption Forecast',
    required: false,
    description: 'Rolling 48-hour average of grid import — typically a custom helper sensor or InfluxDB-derived entity',
    sensorGroups: [
      {
        name: 'Consumption',
        sensors: [
          { key: '48h_avg_grid_import', label: '48h Avg Grid Import', required: false },
        ],
      },
    ],
  },
  {
    id: 'phase_current',
    name: 'Phase Current Monitoring',
    required: false,
    description: 'Per-phase current sensors (e.g. Tibber Pulse, Shelly 3EM) for grid fuse protection — auto-detected from current_l1/l2/l3 entities',
    sensorGroups: [
      {
        name: 'Phase Currents',
        sensors: [
          { key: 'current_l1', label: 'Phase L1 Current', required: false },
          { key: 'current_l2', label: 'Phase L2 Current', required: false },
          { key: 'current_l3', label: 'Phase L3 Current', required: false },
        ],
      },
    ],
  },
  {
    id: 'discharge_inhibit',
    name: 'Discharge Inhibit',
    required: false,
    description: 'Binary sensor that blocks battery discharge while EV is charging \u2014 any binary_sensor ending with _charging or _is_charging is auto-detected; enter manually if not found',
    sensorGroups: [
      {
        name: 'Constraint',
        sensors: [
          { key: 'discharge_inhibit', label: 'Discharge Inhibit Sensor', required: false },
        ],
      },
    ],
  },
  {
    id: 'weather',
    name: 'Weather Integration',
    required: false,
    description: 'HA weather entity (e.g. weather.home from Met.no or Open-Meteo) — used for LFP cold-temperature derating when enabled',
    sensorGroups: [
      {
        name: 'Weather Entity',
        sensors: [
          { key: 'weather_entity', label: 'HA Weather Entity', required: false },
        ],
      },
    ],
  },
];
