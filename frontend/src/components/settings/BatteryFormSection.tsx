import React, { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { numField, txtInput, radioGroup, toggle, SectionCard } from './FormHelpers';

export interface BatteryForm {
  totalCapacity: number;
  minSoc: number;
  maxSoc: number;
  maxChargeDischargePowerKw: number;
  cycleCostPerKwh: number;
  efficiencyCharge: number;
  efficiencyDischarge: number;
  temperatureDeratingEnabled: boolean;
  minActionProfit: number;
}

export interface InverterForm {
  inverterType: string;
  deviceId: string;
}

interface Props {
  form: BatteryForm;
  onChange: (f: BatteryForm) => void;
  inverterForm: InverterForm;
  onInverterChange: (f: InverterForm) => void;
  currency?: string;
  weatherEntity?: string;
}

export function BatteryFormSection({
  form, onChange, inverterForm, onInverterChange, currency = '', weatherEntity = '',
}: Props) {
  const [effOpen, setEffOpen] = useState(false);

  return (
    <div className="space-y-3">
      <SectionCard
        title="Inverter Type"
        description="Select your Growatt inverter series (auto-detected during setup)."
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            {radioGroup(
              'Inverter type',
              [{ value: 'MIN', label: 'MIN (AC-coupled)' }, { value: 'SPH', label: 'SPH (DC-coupled)' }],
              inverterForm.inverterType,
              v => onInverterChange({ ...inverterForm, inverterType: v }),
            )}
          </div>
          {txtInput('Device ID', inverterForm.deviceId,
            v => onInverterChange({ ...inverterForm, deviceId: v }), 'Growatt device ID')}
        </div>
      </SectionCard>

      <SectionCard
        title="Capacity & SOC Limits"
        description="Total battery capacity in kWh — set this to match your actual battery exactly. Min/Max SOC values are synced to the Growatt inverter and define the operating range the optimizer will stay within."
      >
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {numField('Total Capacity', form.totalCapacity,
            v => onChange({ ...form, totalCapacity: v }), { unit: 'kWh', min: 1, step: 0.1 })}
          {numField('Min SOC', form.minSoc,
            v => onChange({ ...form, minSoc: v }), { unit: '%', min: 0, max: 100, step: 1 })}
          {numField('Max SOC', form.maxSoc,
            v => onChange({ ...form, maxSoc: v }), { unit: '%', min: 0, max: 100, step: 1 })}
        </div>
      </SectionCard>

      <SectionCard
        title="Power"
        description="Maximum charge and discharge power available to the optimizer. Calculate from your battery's C-rate: e.g. 30 kWh × 0.5C = 15 kW."
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {numField('Max Charge / Discharge Power', form.maxChargeDischargePowerKw,
            v => onChange({ ...form, maxChargeDischargePowerKw: v }), { unit: 'kW', min: 0, step: 0.1 })}
        </div>
      </SectionCard>

      {/* Advanced settings collapsible */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
        <button
          type="button"
          onClick={() => setEffOpen(o => !o)}
          className="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-50 dark:hover:bg-gray-700/40 transition-colors text-left"
        >
          <div>
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Advanced settings</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              Cycle cost, profit threshold, efficiency factors and temperature derating
            </p>
          </div>
          {effOpen
            ? <ChevronUp className="h-4 w-4 text-gray-400 flex-shrink-0" />
            : <ChevronDown className="h-4 w-4 text-gray-400 flex-shrink-0" />}
        </button>
        {effOpen && (
          <div className="border-t border-gray-100 dark:border-gray-700 px-5 py-4 space-y-4">
            {numField('Cycle Cost', form.cycleCostPerKwh,
              v => onChange({ ...form, cycleCostPerKwh: v }),
              { unit: `${currency}/kWh`, min: 0, step: 0.001 })}
            <p className="text-xs text-gray-500 dark:text-gray-400 -mt-2">
              Represents battery wear — a small cost added to every kWh cycled. Used by the optimizer
              to decide whether a charge/discharge cycle is worth doing given the price spread. A higher
              value makes cycles less attractive and reduces unnecessary wear.
            </p>
            {numField('Min Action Profit', form.minActionProfit,
              v => onChange({ ...form, minActionProfit: v }),
              { unit: `${currency} — skip cycles below this gain`, min: 0, step: 0.1 })}
            <p className="text-xs text-gray-500 dark:text-gray-400 -mt-2">
              Minimum profit threshold for a charge/discharge action. The optimizer skips cycles where
              the expected gain is below this value, reducing unnecessary wear from marginal trades.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {numField('Charge Efficiency', form.efficiencyCharge,
                v => onChange({ ...form, efficiencyCharge: v }), { unit: '%', min: 0, max: 100, step: 0.1 })}
              {numField('Discharge Efficiency', form.efficiencyDischarge,
                v => onChange({ ...form, efficiencyDischarge: v }), { unit: '%', min: 0, max: 100, step: 0.1 })}
            </div>
            {toggle('Enable temperature derating', form.temperatureDeratingEnabled,
              v => onChange({ ...form, temperatureDeratingEnabled: v }))}
            {form.temperatureDeratingEnabled && (
              <>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  Uses the weather entity to derate charging power in cold temperatures (LFP protection).
                  Configure the weather entity in the <strong>Sensors</strong> tab under Weather Integration.
                  {weatherEntity && (
                    <span className="ml-1 text-green-600 dark:text-green-400">Current: {weatherEntity}</span>
                  )}
                </p>
                <div>
                  <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">
                    Derating curve (LFP default, read-only)
                  </p>
                  <div className="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
                    <table className="w-full text-xs">
                      <thead className="bg-gray-50 dark:bg-gray-700/50">
                        <tr>
                          <th className="px-3 py-1.5 text-left font-medium text-gray-500 dark:text-gray-400">Temperature</th>
                          <th className="px-3 py-1.5 text-left font-medium text-gray-500 dark:text-gray-400">Max charge rate</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                        {[[-1, 20], [0, 20], [5, 50], [10, 80], [15, 100]].map(([temp, rate]) => (
                          <tr key={temp} className="bg-white dark:bg-gray-800">
                            <td className="px-3 py-1.5 text-gray-700 dark:text-gray-300">{temp}°C</td>
                            <td className="px-3 py-1.5 text-gray-700 dark:text-gray-300">{rate}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
