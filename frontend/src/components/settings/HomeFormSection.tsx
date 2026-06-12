import React from 'react';
import { numField, radioGroup, toggle, SectionCard } from './FormHelpers';

export interface HomeForm {
  consumption: number;
  consumptionStrategy: string;
  maxFuseCurrent: number;
  voltage: number;
  safetyMarginFactor: number;
  phaseCount: number;
  powerMonitoringEnabled: boolean;
}

interface Props {
  form: HomeForm;
  onChange: (f: HomeForm) => void;
  sensors?: Record<string, string>;
}

export function HomeFormSection({ form, onChange, sensors }: Props) {
  const haStatsSensorConfigured = Boolean(sensors?.['lifetime_load_consumption']);
  const localLoadSensorConfigured = Boolean(sensors?.['local_load_power']);
  const chargeRateSensorConfigured = Boolean(sensors?.['battery_charging_power_rate']);
  return (
    <div className="space-y-3">
      <SectionCard
        title="Home Consumption Prediction"
        description="The data source the optimizer uses for home load prediction."
      >
        {radioGroup(
          'Data source',
          [
            { value: 'fixed', label: 'Fixed value' },
            { value: 'sensor', label: 'Home Assistant sensor' },
            { value: 'influxdb_7d_avg', label: 'InfluxDB (requires InfluxDB integration)', disabled: !localLoadSensorConfigured },
            { value: 'ha_statistics', label: 'HA Statistics (7-day hourly profile)', disabled: !haStatsSensorConfigured },
          ],
          form.consumptionStrategy,
          v => onChange({ ...form, consumptionStrategy: v }),
        )}
        {!localLoadSensorConfigured && (
          <p className="text-xs text-amber-600 dark:text-amber-400 pt-1">
            InfluxDB requires the <strong>Local Load Power</strong> sensor to be configured in the{' '}
            <strong>Sensors</strong> tab. This sensor is not available on all inverter platforms (e.g. Growatt SPH).
          </p>
        )}
        {!haStatsSensorConfigured && (
          <p className="text-xs text-amber-600 dark:text-amber-400 pt-1">
            HA Statistics requires the <strong>Lifetime Load Consumption</strong> sensor to be
            configured in the <strong>Sensors</strong> tab.
          </p>
        )}
        {form.consumptionStrategy === 'fixed' && (
          <div className="pt-1">
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">Always uses the value below — no sensor required.</p>
            {numField('Default Hourly Consumption', form.consumption,
              v => onChange({ ...form, consumption: v }), { unit: 'kWh', min: 0, step: 0.1 })}
          </div>
        )}
        {form.consumptionStrategy === 'sensor' && (
          <p className="text-xs text-gray-500 dark:text-gray-400 pt-1">
            Reads any HA sensor that provides an hourly consumption estimate — for example a custom helper
            that computes a 48h rolling average of grid import.
            Configure the sensor entity ID in the <strong>Sensors</strong> tab under Consumption Forecast.
          </p>
        )}
        {form.consumptionStrategy === 'influxdb_7d_avg' && (
          <p className="text-xs text-gray-500 dark:text-gray-400 pt-1">
            Queries InfluxDB directly for the past 7 days of local load power and uses the hourly average
            profile. Requires the InfluxDB integration to be configured.
            Configure the local load power sensor entity ID in the <strong>Sensors</strong> tab under Growatt Server.
          </p>
        )}
        {form.consumptionStrategy === 'ha_statistics' && (
          <p className="text-xs text-gray-500 dark:text-gray-400 pt-1">
            Uses Home Assistant's built-in long-term statistics to build a time-of-day consumption profile
            from the past 7 days. Captures daily patterns (morning/evening peaks, overnight baseline) using
            a trimmed average that filters out outlier spikes like EV charging. No extra integrations needed.
            Configure the load consumption sensor in the <strong>Sensors</strong> tab under Consumption Forecast.
          </p>
        )}
      </SectionCard>

      <SectionCard
        title="Power Monitoring"
        description="Monitors real-time load and limits battery charge power to prevent blowing the main fuse. Enable to configure."
      >
        {!chargeRateSensorConfigured && (
          <p className="text-xs text-amber-600 dark:text-amber-400">
            Fuse protection requires a <strong>Battery Charging Power Rate</strong> entity, which is not
            available on all inverter platforms (e.g. Growatt SPH).
          </p>
        )}
        {toggle('Enable fuse protection', form.powerMonitoringEnabled,
          v => onChange({ ...form, powerMonitoringEnabled: v }),
          { disabled: !chargeRateSensorConfigured })}
        {form.powerMonitoringEnabled && (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-1">
              {numField('Fuse Current', form.maxFuseCurrent,
                v => onChange({ ...form, maxFuseCurrent: Math.round(v) }), { unit: 'A', min: 1, step: 1 })}
              {numField('Voltage', form.voltage,
                v => onChange({ ...form, voltage: Math.round(v) }), { unit: 'V', min: 100, step: 1 })}
              {numField('Safety Margin Factor', form.safetyMarginFactor,
                v => onChange({ ...form, safetyMarginFactor: v }), { min: 0, max: 2, step: 0.05 })}
            </div>
            <div className="pt-1">
              {radioGroup(
                'Phase count',
                [{ value: '1', label: '1-phase' }, { value: '3', label: '3-phase' }],
                String(form.phaseCount),
                v => onChange({ ...form, phaseCount: parseInt(v, 10) }),
              )}
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 pt-1">
              Configure per-phase current sensor entity IDs in the <strong>Sensors</strong> tab
              under Phase Current Monitoring.
            </p>
          </>
        )}
      </SectionCard>
    </div>
  );
}
