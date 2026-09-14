import React from 'react';
import { numField, txtInput, radioGroup, toggle, SectionCard } from './FormHelpers';

export interface PricingForm {
  currency: string;
  provider: string;
  nordpoolConfigEntryId: string;
  nordpoolEntity: string;
  octopusImportTodayEntity: string;
  octopusImportTomorrowEntity: string;
  octopusExportTodayEntity: string;
  octopusExportTomorrowEntity: string;
  octopusFreeImportPrice: number;
  octopusPowerUpCalendarEntity: string;
  octopusPowerDownEnabled: boolean;
  octopusPowerDownCalendarEntity: string;
  octopusPowerDownExportKw: number;
  octopusPowerDownExportMinutes: number;
  octopusPowerDownEventsEntity: string;
  entsoeEntity: string;
  area: string;
  markupRate: number;
  vatMultiplier: number;
  additionalCosts: number;
  taxReduction: number;
  spotMultiplier: number;
  exportSpotMultiplier: number;
}

interface Props {
  form: PricingForm;
  onChange: (f: PricingForm) => void;
  /** Set when HA has the Power Down calendar entity disabled — same shape as
   * the setup wizard's powerUpCalendarDisabledBy notice. */
  powerDownCalendarDisabledBy?: string;
}

export function PricingFormSection({ form, onChange, powerDownCalendarDisabledBy }: Props) {
  const isOctopus = form.provider === 'octopus';
  const isEntsoe = form.provider === 'entsoe';
  const currency = isOctopus ? 'GBP' : form.currency;

  const sm = form.spotMultiplier ?? 1.0;
  const esm = form.exportSpotMultiplier ?? 1.0;
  const previewSpot = 1.0;
  const previewBuy = Number(
    ((previewSpot * sm + form.markupRate) * form.vatMultiplier + form.additionalCosts).toFixed(4),
  );
  const previewSell = Number((previewSpot * esm + form.taxReduction).toFixed(4));

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
            { value: 'nordpool_hacs', label: 'Nord Pool (HACS custom sensor)' },
            { value: 'octopus', label: 'Octopus Energy' },
            { value: 'entsoe', label: 'ENTSO-e / Belpex (Transparency Platform)' },
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
              {txtInput('Currency', form.currency,
                v => onChange({ ...form, currency: v }), 'Auto-detected…',
                { readOnly: !!(form.area && form.area.length <= 5 && form.currency) })}
            </div>
          </div>
        )}

        {form.provider === 'nordpool_hacs' && (
          <div className="space-y-3">
            {txtInput('Sensor', form.nordpoolEntity,
              v => onChange({ ...form, nordpoolEntity: v }), 'sensor.nordpool_…')}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {txtInput('Price Area', form.area, () => {}, 'Auto-detected…', { readOnly: true })}
              {txtInput('Currency', form.currency,
                v => onChange({ ...form, currency: v }), 'Auto-detected…',
                { readOnly: !!(form.area && form.area.length <= 5 && form.currency) })}
            </div>
          </div>
        )}

        {isOctopus && (
          <div className="space-y-3">
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
            <div className="pt-2 border-t border-gray-200 dark:border-gray-700 space-y-3">
              <p className="text-sm font-medium text-gray-700 dark:text-gray-200">
                Octoplus free power windows
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {txtInput('Free power calendar', form.octopusPowerUpCalendarEntity,
                  v => onChange({ ...form, octopusPowerUpCalendarEntity: v }),
                  'calendar.octopus_energy_…_octoplus_power_up')}
                {numField('Price during free windows', form.octopusFreeImportPrice,
                  v => onChange({ ...form, octopusFreeImportPrice: v }),
                  { unit: 'GBP/kWh', min: 0, step: 0.001 })}
              </div>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                The Octopus Energy integration's Octoplus power-up calendar, disabled
                by default in Home Assistant — enable it there first. Leave empty to
                disable. Octopus doesn't distinguish Power Up sessions from Weekend
                Happy Hours in the calendar, so set a small non-zero price to stay
                conservative.
              </p>
            </div>
            <div className="pt-2 border-t border-gray-200 dark:border-gray-700 space-y-3">
              <p className="text-sm font-medium text-gray-700 dark:text-gray-200">
                Octoplus Power Down sessions
              </p>
              {toggle('Export during Power Down sessions', form.octopusPowerDownEnabled,
                v => onChange({ ...form, octopusPowerDownEnabled: v }))}
              {powerDownCalendarDisabledBy && (
                <div
                  data-testid="power-down-calendar-disabled-warning"
                  className="p-3 bg-orange-50 dark:bg-orange-900/20 border border-orange-200 dark:border-orange-800 rounded-lg text-sm text-orange-700 dark:text-orange-300"
                >
                  Enable the Octoplus power-down calendar entity (
                  <span className="font-mono text-xs">{form.octopusPowerDownCalendarEntity}</span>
                  ) in Home Assistant to use Power Down sessions.
                </div>
              )}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {txtInput('Power Down calendar', form.octopusPowerDownCalendarEntity,
                  v => onChange({ ...form, octopusPowerDownCalendarEntity: v }),
                  'calendar.octopus_energy_…_octoplus_power_down')}
                {txtInput('Octoplus Power Down events entity (for session rewards)',
                  form.octopusPowerDownEventsEntity,
                  v => onChange({ ...form, octopusPowerDownEventsEntity: v }),
                  'event.octopus_energy_…_octoplus_power_down_events')}
                {numField('Export power', form.octopusPowerDownExportKw,
                  v => onChange({ ...form, octopusPowerDownExportKw: v }),
                  { unit: 'kW', min: 0.1, step: 0.1 })}
                <label className="block">
                  <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Export duration</span>
                  <select
                    value={form.octopusPowerDownExportMinutes}
                    onChange={e => onChange({ ...form, octopusPowerDownExportMinutes: Number(e.target.value) })}
                    className="mt-1 block w-full rounded-lg border bg-white dark:bg-gray-700 border-gray-300 dark:border-gray-600 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value={15}>15 minutes</option>
                    <option value={30}>30 minutes</option>
                    <option value={45}>45 minutes</option>
                    <option value={60}>60 minutes</option>
                  </select>
                </label>
                <div className="flex items-end">
                  <p className="text-sm text-gray-600 dark:text-gray-400 pb-2">
                    ≈ {(form.octopusPowerDownExportKw * form.octopusPowerDownExportMinutes / 60).toFixed(2)} kWh per session
                  </p>
                </div>
              </div>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                During each joined Octoplus Power Down session, BESS exports at least
                the chosen power for the chosen duration at the start of the session,
                and plans no grid import for the rest of the session, so your meter
                reads net export. Your grid connection must allow exporting. Export
                power is also the safety margin if the house uses more than forecast.
                Whether exporting improves session scoring is unproven, which is why
                this is off by default.
              </p>
            </div>
          </div>
        )}

        {form.provider === 'entsoe' && (
          <div className="space-y-3">
            {txtInput('Sensor', form.entsoeEntity,
              v => onChange({ ...form, entsoeEntity: v }), 'sensor.…_average_electricity_price')}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {txtInput('Currency', form.currency, () => {}, 'Auto-detected…', { readOnly: true })}
            </div>
          </div>
        )}
      </SectionCard>

      <SectionCard
        title="Price Calculation"
        description={isOctopus
          ? 'Octopus prices are already final (VAT-inclusive, GBP/kWh). Only tax reduction applies.'
          : isEntsoe
            ? 'Calculate your actual electricity costs from ENTSO-e/Belpex spot prices. Supports both additive markup and multiplicative spot adjustments.'
            : 'Calculate your actual electricity costs from spot prices, fees and taxes.'}
      >
        {!isOctopus && (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {isEntsoe && numField('Import Spot Multiplier', form.spotMultiplier,
                v => onChange({ ...form, spotMultiplier: v }),
                { unit: 'factor (1.0 = no adjustment)', min: 0.5, max: 2.0, step: 0.0001 })}
              {numField('Markup Rate', form.markupRate,
                v => onChange({ ...form, markupRate: v }),
                { unit: `${currency}/kWh (ex-VAT)`, min: 0, step: 0.001 })}
              {numField('VAT Multiplier', form.vatMultiplier,
                v => onChange({ ...form, vatMultiplier: v }),
                { unit: 'factor', min: 1, step: 0.01 })}
              {numField('Additional Costs', form.additionalCosts,
                v => onChange({ ...form, additionalCosts: v }),
                { unit: `${currency}/kWh`, min: 0, step: 0.001 })}
              {isEntsoe && numField('Export Spot Multiplier', form.exportSpotMultiplier,
                v => onChange({ ...form, exportSpotMultiplier: v }),
                { unit: 'factor (1.0 = no adjustment)', min: 0.5, max: 2.0, step: 0.0001 })}
              {numField('Export Compensation', form.taxReduction,
                v => onChange({ ...form, taxReduction: v }),
                { unit: `${currency}/kWh`, step: 0.001 })}
            </div>
            {isEntsoe ? (
              <div className="rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800/40 px-4 py-3 space-y-3 text-xs text-gray-600 dark:text-gray-400">
                <div className="space-y-2">
                  <div><span className="font-medium text-blue-900 dark:text-blue-200">Import Spot Multiplier:</span> Contract-specific factor applied to raw spot price. E.g. Luminus Dynamic: 1.0175.</div>
                  <div><span className="font-medium text-blue-900 dark:text-blue-200">Markup Rate:</span> Fixed costs before VAT: supplier margin, excise duty, grid fees, etc.</div>
                  <div><span className="font-medium text-blue-900 dark:text-blue-200">VAT Multiplier:</span> VAT factor on import. 1.06 = 6% (Belgium), 1.21 = 21% (Netherlands).</div>
                  <div><span className="font-medium text-blue-900 dark:text-blue-200">Additional Costs:</span> Post-VAT fixed costs. Set to 0 if all costs are already included above.</div>
                  <div><span className="font-medium text-blue-900 dark:text-blue-200">Export Spot Multiplier:</span> Contract-specific factor on spot for export/injection. E.g. Luminus: 1.018.</div>
                  <div><span className="font-medium text-blue-900 dark:text-blue-200">Export Compensation:</span> Fixed per-kWh payment or deduction for exported energy. Use negative values for deductions.</div>
                </div>
                <div className="space-y-2 pt-2 border-t border-blue-200 dark:border-blue-700">
                  <p className="font-medium text-blue-900 dark:text-blue-200">How the raw spot price is converted:</p>
                  <p className="pl-2 border-l-2 border-blue-300 dark:border-blue-600"><strong>Buy price:</strong> (spot × import multiplier + markup) × VAT + additional costs</p>
                  <p className="pl-2 border-l-2 border-blue-300 dark:border-blue-600"><strong>Sell price:</strong> spot × export multiplier + export compensation</p>
                </div>
              </div>
            ) : (
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
            )}
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
