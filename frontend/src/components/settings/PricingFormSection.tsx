import React from 'react';
import { numField, txtInput, radioGroup, SectionCard } from './FormHelpers';

export interface PricingForm {
  currency: string;
  provider: string;
  nordpoolConfigEntryId: string;
  nordpoolTodayEntity: string;
  nordpoolTomorrowEntity: string;
  octopusImportTodayEntity: string;
  octopusImportTomorrowEntity: string;
  octopusExportTodayEntity: string;
  octopusExportTomorrowEntity: string;
  area: string;
  markupRate: number;
  vatMultiplier: number;
  additionalCosts: number;
  taxReduction: number;
}

interface Props {
  form: PricingForm;
  onChange: (f: PricingForm) => void;
}

export function PricingFormSection({ form, onChange }: Props) {
  const previewSpot = 1.0;
  const previewBuy = Number(
    ((previewSpot + form.markupRate) * form.vatMultiplier + form.additionalCosts).toFixed(4),
  );
  const previewSell = Number((previewSpot + form.taxReduction).toFixed(4));

  return (
    <div className="space-y-3">
      <SectionCard
        title="Price Source"
        description="Where spot prices come from. Nord Pool (official) uses the HA integration's config entry ID. Nord Pool (custom sensor) reads from two sensor entities. Octopus Energy uses event entities from the Octopus Energy HACS integration."
      >
        {radioGroup(
          'Provider',
          [
            { value: 'nordpool_official', label: 'Nord Pool (official HA integration)' },
            { value: 'nordpool', label: 'Nord Pool (custom sensor)' },
            { value: 'octopus', label: 'Octopus Energy' },
          ],
          form.provider,
          v => onChange({ ...form, provider: v }),
        )}
        {form.provider === 'nordpool_official' && (
          <div className="pt-1">
            {txtInput('Config Entry ID', form.nordpoolConfigEntryId,
              v => onChange({ ...form, nordpoolConfigEntryId: v }), 'e.g. abc123…')}
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Auto-detected by Auto-Configure.</p>
          </div>
        )}
        {form.provider === 'nordpool' && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
            {txtInput('Today entity', form.nordpoolTodayEntity,
              v => onChange({ ...form, nordpoolTodayEntity: v }), 'sensor.nordpool_…')}
            {txtInput('Tomorrow entity', form.nordpoolTomorrowEntity,
              v => onChange({ ...form, nordpoolTomorrowEntity: v }), 'sensor.nordpool_…')}
          </div>
        )}
        {form.provider === 'octopus' && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
            {txtInput('Import today entity', form.octopusImportTodayEntity,
              v => onChange({ ...form, octopusImportTodayEntity: v }))}
            {txtInput('Import tomorrow entity', form.octopusImportTomorrowEntity,
              v => onChange({ ...form, octopusImportTomorrowEntity: v }))}
            {txtInput('Export today entity', form.octopusExportTodayEntity,
              v => onChange({ ...form, octopusExportTodayEntity: v }))}
            {txtInput('Export tomorrow entity', form.octopusExportTomorrowEntity,
              v => onChange({ ...form, octopusExportTomorrowEntity: v }))}
          </div>
        )}
        {form.provider !== 'octopus' && (
          <div className="pt-1">
            {txtInput('Price Area', form.area,
              v => onChange({ ...form, area: v }), 'e.g. SE4, NO1, DK1, GB')}
          </div>
        )}
        <label className="block">
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Currency</span>
          <select
            value={form.currency}
            onChange={e => onChange({ ...form, currency: e.target.value })}
            className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">Select currency</option>
            {['SEK', 'NOK', 'DKK', 'EUR', 'GBP'].map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </label>
      </SectionCard>

      <SectionCard
        title="Price Calculation"
        description={form.provider === 'octopus'
          ? 'Octopus prices are already final (VAT-inclusive, GBP/kWh). Only tax reduction applies.'
          : 'Calculate your actual electricity costs from spot prices, fees and taxes.'}
      >
        {form.provider !== 'octopus' && (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {numField('Markup Rate', form.markupRate,
                v => onChange({ ...form, markupRate: v }),
                { unit: `${form.currency}/kWh (ex-VAT)`, min: 0, step: 0.001 })}
              {numField('VAT Multiplier', form.vatMultiplier,
                v => onChange({ ...form, vatMultiplier: v }),
                { unit: 'factor', min: 1, step: 0.01 })}
              {numField('Additional Costs', form.additionalCosts,
                v => onChange({ ...form, additionalCosts: v }),
                { unit: `${form.currency}/kWh`, min: 0, step: 0.001 })}
              {numField('Export Compensation', form.taxReduction,
                v => onChange({ ...form, taxReduction: v }),
                { unit: `${form.currency}/kWh`, min: 0, step: 0.001 })}
            </div>
            <div className="rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800/40 px-4 py-3 space-y-3 text-xs text-gray-600 dark:text-gray-400">
              <div className="space-y-2">
                <div><span className="font-medium text-blue-900 dark:text-blue-200">Markup Rate:</span> Energy provider margin fee. E.g. Tibber 0.08 (8 öre/kWh), Ellevio ~0.15. Applied before VAT.</div>
                <div><span className="font-medium text-blue-900 dark:text-blue-200">VAT Multiplier:</span> VAT factor. 1.25 = 25% (Sweden/Norway), 1.20 = 20% (UK/EU).</div>
                <div><span className="font-medium text-blue-900 dark:text-blue-200">Additional Costs:</span> Grid transfer fee + energy tax (sum ex-VAT, then VAT applied). E.g. E.ON: (0.2584 + 0.3600) × 1.25 = 0.773 SEK/kWh.</div>
                <div><span className="font-medium text-blue-900 dark:text-blue-200">Export Compensation:</span> Per-kWh payment from grid operator (Nätnytta) when selling surplus electricity. Check your energy bill under "Producent/Självfaktura". E.g. E.ON: 0.1988 (19.88 öre/kWh).</div>
              </div>
              
              <div className="space-y-2 pt-2 border-t border-blue-200 dark:border-blue-700">
                <p className="font-medium text-blue-900 dark:text-blue-200">How the raw spot price is converted:</p>
                <p className="pl-2 border-l-2 border-blue-300 dark:border-blue-600"><strong>Buy price:</strong> (raw spot + markup) × VAT multiplier + grid fees</p>
                <p className="pl-2 border-l-2 border-blue-300 dark:border-blue-600"><strong>Sell price:</strong> raw spot + export compensation</p>
                <p className="text-gray-500 dark:text-gray-500 italic">Note: Markup is added before VAT (ex-VAT), while grid fees already include VAT.</p>
              </div>
            </div>
            <div className="rounded-lg bg-gray-50 dark:bg-gray-700/50 px-4 py-3 text-sm space-y-1.5">
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Preview at spot = 1.00
              </p>
              <div className="flex justify-between font-medium">
                <span className="text-gray-700 dark:text-gray-200">Buy price</span>
                <span className="text-blue-600 dark:text-blue-400">
                  {previewBuy.toFixed(2)} {form.currency}/kWh
                </span>
              </div>
              <div className="flex justify-between font-medium">
                <span className="text-gray-700 dark:text-gray-200">Sell price</span>
                <span className="text-green-600 dark:text-green-400">
                  {previewSell.toFixed(2)} {form.currency}/kWh
                </span>
              </div>
            </div>
          </>
        )}
        {form.provider === 'octopus' && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {numField('Tax Reduction', form.taxReduction,
              v => onChange({ ...form, taxReduction: v }),
              { unit: 'GBP/kWh credit on sold energy', min: 0, step: 0.001 })}
          </div>
        )}
      </SectionCard>
    </div>
  );
}
