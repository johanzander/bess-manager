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
}

export function HomeFormSection({ form, onChange }: Props) {
  return (
    <div className="space-y-3">
      <SectionCard
        title="Home Consumption Prediction"
        description="The data source the optimizer uses for expected home load each hour. A sensor gives the most accurate forecast; use a fixed value if no consumption sensor is available."
      >
        {radioGroup(
          'Data source',
          [
            { value: 'sensor', label: 'Home Assistant sensor' },
            { value: 'fixed', label: 'Fixed value' },
            { value: 'influxdb_7d_avg', label: 'InfluxDB (requires InfluxDB integration)' },
          ],
          form.consumptionStrategy,
          v => onChange({ ...form, consumptionStrategy: v }),
        )}
        {form.consumptionStrategy === 'sensor' && (
          <p className="text-xs text-gray-500 dark:text-gray-400 pt-1">
            Reads any HA sensor that provides an hourly consumption estimate — for example a custom helper
            that computes a 48h rolling average of grid import.
            Configure the sensor entity ID in the <strong>Sensors</strong> tab under Consumption Forecast.
          </p>
        )}
        {form.consumptionStrategy === 'fixed' && (
          <div className="pt-1">
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">Always uses the value below — no sensor required.</p>
            {numField('Default Hourly Consumption', form.consumption,
              v => onChange({ ...form, consumption: v }), { unit: 'kWh', min: 0, step: 0.1 })}
          </div>
        )}
        {form.consumptionStrategy === 'influxdb_7d_avg' && (
          <p className="text-xs text-gray-500 dark:text-gray-400 pt-1">
            Queries InfluxDB directly for the past 7 days of local load power and uses the hourly average
            profile. Requires the InfluxDB integration to be configured.
            Configure the local load power sensor entity ID in the <strong>Sensors</strong> tab under Growatt Server.
          </p>
        )}
      </SectionCard>

      <SectionCard
        title="Power Monitoring"
        description="Monitors real-time load and limits battery charge power to prevent blowing the main fuse. Enable to configure."
      >
        {toggle('Enable fuse protection', form.powerMonitoringEnabled,
          v => onChange({ ...form, powerMonitoringEnabled: v }))}
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
