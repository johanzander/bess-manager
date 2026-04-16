import React from 'react';
import { numField, txtInput, radioGroup, SectionCard } from './FormHelpers';

export interface PricingForm {
  currency: string;
  provider: string;
  nordpoolConfigEntryId: string;
  nordpoolEntity: string;
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
  const isOctopus = form.provider === 'octopus';
  const currency = isOctopus ? 'GBP' : form.currency;

  const previewSpot = 1.0;
  const previewBuy = Number(
    ((previewSpot + form.markupRate) * form.vatMultiplier + form.additionalCosts).toFixed(4),
  );
  const previewSell = Number((previewSpot + form.taxReduction).toFixed(4));

  return (
    <div className="space-y-3">
      <SectionCard
        title="Price Source"
        description="Configure where to fetch your electricity prices from. Choose your provider and the relevant Home Assistant entities."
      >
        {radioGroup(
          'Provider',
          [
            { value: 'nordpool_official', label: 'Nord Pool (official HA integration)' },
            { value: 'nordpool', label: 'Nord Pool (HACS custom sensor)' },
            { value: 'octopus', label: 'Octopus Energy' },
          ],
          form.provider,
          v => onChange({ ...form, provider: v }),
        )}

        {form.provider === 'nordpool_official' && (
          <div className="space-y-3">
            {txtInput('Config Entry ID', form.nordpoolConfigEntryId,
              v => onChange({ ...form, nordpoolConfigEntryId: v }), 'Auto-detected…')}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {txtInput('Price Area', form.area, () => {}, 'Auto-detected…', { readOnly: true })}
              {txtInput('Currency', form.currency, () => {}, 'Auto-detected…', { readOnly: true })}
            </div>
          </div>
        )}

        {form.provider === 'nordpool' && (
          <div className="space-y-3">
            {txtInput('Sensor', form.nordpoolEntity,
              v => onChange({ ...form, nordpoolEntity: v }), 'sensor.nordpool_…')}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {txtInput('Price Area', form.area, () => {}, 'Auto-detected…', { readOnly: true })}
              {txtInput('Currency', form.currency, () => {}, 'Auto-detected…', { readOnly: true })}
            </div>
          </div>
        )}

        {isOctopus && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {txtInput('Import today', form.octopusImportTodayEntity,
              v => onChange({ ...form, octopusImportTodayEntity: v }))}
            {txtInput('Import tomorrow', form.octopusImportTomorrowEntity,
              v => onChange({ ...form, octopusImportTomorrowEntity: v }))}
            {txtInput('Export today', form.octopusExportTodayEntity,
              v => onChange({ ...form, octopusExportTodayEntity: v }))}
            {txtInput('Export tomorrow', form.octopusExportTomorrowEntity,
              v => onChange({ ...form, octopusExportTomorrowEntity: v }))}
          </div>
        )}
      </SectionCard>

      <SectionCard
        title="Price Calculation"
        description={isOctopus
          ? 'Octopus prices are already final (VAT-inclusive, GBP/kWh). Only tax reduction applies.'
          : 'Calculate your actual electricity costs from spot prices, fees and taxes.'}
      >
        {!isOctopus && (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {numField('Markup Rate', form.markupRate,
                v => onChange({ ...form, markupRate: v }),
                { unit: `${currency}/kWh (ex-VAT)`, min: 0, step: 0.001 })}
              {numField('VAT Multiplier', form.vatMultiplier,
                v => onChange({ ...form, vatMultiplier: v }),
                { unit: 'factor', min: 1, step: 0.01 })}
              {numField('Additional Costs', form.additionalCosts,
                v => onChange({ ...form, additionalCosts: v }),
                { unit: `${currency}/kWh`, min: 0, step: 0.001 })}
              {numField('Export Compensation', form.taxReduction,
                v => onChange({ ...form, taxReduction: v }),
                { unit: `${currency}/kWh`, min: 0, step: 0.001 })}
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
                  {previewBuy.toFixed(2)} {currency}/kWh
                </span>
              </div>
              <div className="flex justify-between font-medium">
                <span className="text-gray-700 dark:text-gray-200">Sell price</span>
                <span className="text-green-600 dark:text-green-400">
                  {previewSell.toFixed(2)} {currency}/kWh
                </span>
              </div>
            </div>
          </>
        )}
        {isOctopus && (
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
