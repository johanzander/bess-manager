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

export const INTEGRATIONS: IntegrationDef[] = [
  {
    id: 'growatt',
    name: 'Growatt Server',
    required: true,
    description: 'Battery inverter — all battery control and power monitoring sensors come from the Growatt Server integration',
    sensorGroups: [
      {
        name: 'Battery Control',
        sensors: [
          { key: 'battery_soc', label: 'State of Charge (SOC)', required: true },
          { key: 'battery_charge_power', label: 'Charging Power', required: true },
          { key: 'battery_discharge_power', label: 'Discharging Power', required: true },
          { key: 'battery_charge_stop_soc', label: 'Charge Stop SOC', required: false },
          { key: 'battery_discharge_stop_soc', label: 'Discharge Stop SOC', required: false },
          { key: 'battery_charging_power_rate', label: 'Charging Power Rate', required: false },
          { key: 'battery_discharging_power_rate', label: 'Discharging Power Rate', required: false },
          { key: 'grid_charge', label: 'Grid Charge Enable', required: false },
        ],
      },
      {
        name: 'Power Monitoring',
        sensors: [
          { key: 'pv_power', label: 'Solar PV Power', required: true },
          { key: 'local_load_power', label: 'Local Load Power', required: true },
          { key: 'import_power', label: 'Grid Import Power', required: true },
          { key: 'export_power', label: 'Grid Export Power', required: true },
        ],
      },
      {
        name: 'Lifetime Energy Totals',
        sensors: [
          { key: 'lifetime_battery_charged', label: 'Total Battery Charged', required: false },
          { key: 'lifetime_battery_discharged', label: 'Total Battery Discharged', required: false },
          { key: 'lifetime_solar_energy', label: 'Total Solar Energy', required: false },
          { key: 'lifetime_export_to_grid', label: 'Total Export to Grid', required: false },
          { key: 'lifetime_import_from_grid', label: 'Total Import from Grid', required: false },
          { key: 'lifetime_load_consumption', label: 'Total Load Consumption', required: false },
          { key: 'lifetime_system_production', label: 'Total System Production', required: false },
          { key: 'lifetime_self_consumption', label: 'Total Self Consumption', required: false },
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
