import React from 'react';
import { PerformanceComparison, PerformanceResult } from '../../types';
import CoverageTable from './CoverageTable';
import { number, panel } from './format';

/** The collapsed evidence: model inputs, cost tables, coverage and notes. */
const ProofSection: React.FC<{
  data: PerformanceResult;
  comparison: PerformanceComparison;
  currency: string;
}> = ({ data, comparison, currency }) => {
  const { actual, optimal } = comparison;
  const battery = data.batteryModel;
  const calibration = battery?.efficiencyCalibration;
  return (
    <details className="space-y-6">
      <summary className="text-xl font-semibold pt-4 cursor-pointer">
        Model inputs and calculation proof
      </summary>
      <div className={panel}>
        <h2 className="font-semibold text-lg">Model inputs</h2>
        {battery && (
          <div className="text-sm space-y-1">
            <p>
              Your current BESS settings, used for the whole {data.period} · {data.timezone}
            </p>
            <p>
              {number(battery.capacityKwh, 'kWh')} · SOC {battery.minSoc}–{battery.maxSoc}% ·
              charge/discharge {battery.maxChargePowerKw}/{battery.maxDischargePowerKw} kW ·
              efficiency {number(battery.efficiencyCharge * 100, '%')}/
              {number(battery.efficiencyDischarge * 100, '%')} · wear{' '}
              {number(battery.cycleCostPerKwh, `${currency}/kWh charged`)}
            </p>
            {calibration?.applied && (
              <p>
                Efficiency calibrated from {battery.historySource}:{' '}
                {number((calibration.charge ?? 0) * 100, '%')} charge /{' '}
                {number((calibration.discharge ?? 0) * 100, '%')} discharge (configured{' '}
                {number(calibration.configuredCharge * 100, '%')} /{' '}
                {number(calibration.configuredDischarge * 100, '%')})
                {calibration.capped
                  ? '; the history implies more than 100 %, so meter and SOC readings disagree.'
                  : '.'}
              </p>
            )}
          </div>
        )}
      </div>

      {data.status === 'estimated_partial' && (
        <div className={panel}>
          <p className="font-semibold">
            Observed intervals · {data.coverage.analyzedPeriods}/{data.coverage.expectedPeriods}{' '}
            quarters
          </p>
          <p className="text-sm">
            Unknown energy quarters are excluded; the hypothetical battery holds energy through each
            gap. Gap household cost is unknown, not zero, so these totals are not the complete{' '}
            {data.period}.
          </p>
        </div>
      )}

      <div className={panel}>
        <h2 className="font-semibold text-lg">Total economic cost · net grid + cycle wear</h2>
        <div className="overflow-x-auto">
          <table className="min-w-[540px] w-full text-sm text-left">
            <thead>
              <tr>
                <th>Scenario</th>
                <th>Net grid ({currency})</th>
                <th>Wear ({currency})</th>
                <th>Total ({currency})</th>
              </tr>
            </thead>
            <tbody>
              {(
                [
                  ['Grid only · no solar, no battery', comparison.gridOnly],
                  ['Solar only · no battery', comparison.solarOnly],
                  ['BESS Manager actual', actual],
                  ['Hindsight · relaxed lower-cost bound', optimal],
                ] as const
              ).map(([name, cost]) => (
                <tr key={name} className="border-t border-gray-200 dark:border-gray-700">
                  <th className="py-3">{name}</th>
                  <td>{number(cost.netGridCost, currency)}</td>
                  <td>{number(cost.wearCost, currency)}</td>
                  <td>{number(cost.totalEconomicCost, currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className={panel}>
        <h2 className="font-semibold text-lg">Recorded operation vs hindsight model</h2>
        <p className="text-sm">
          {data.status === 'estimated_partial'
            ? 'Energy and costs cover observed quarters only. '
            : ''}
          SOC is recorded or constrained at the stated boundaries.
        </p>
        <div className="overflow-x-auto">
          <table className="min-w-[540px] w-full text-sm text-left">
            <thead>
              <tr>
                <th>Metric</th>
                <th>Actual BESS</th>
                <th>Hindsight model</th>
              </tr>
            </thead>
            <tbody>
              {(
                [
                  ['Grid import', 'gridImportKwh', 'kWh'],
                  ['Grid export', 'gridExportKwh', 'kWh'],
                  ['Import cost', 'importCost', currency],
                  ['Export revenue', 'exportRevenue', currency],
                  ['Battery charging', 'chargedKwh', 'kWh'],
                  ['Battery discharging', 'dischargedKwh', 'kWh'],
                  ['Cycle wear', 'wearCost', currency],
                  ['Net grid cost', 'netGridCost', currency],
                  ['Total economic cost', 'totalEconomicCost', currency],
                  ['Initial SOC', 'initialSoc', '%'],
                  ['Final SOC', 'finalSoc', '%'],
                ] as const
              ).map(([name, key, unit]) => (
                <tr key={key} className="border-t border-gray-200 dark:border-gray-700">
                  <th className="py-2">{name}</th>
                  <td>{number(actual[key], unit)}</td>
                  <td>{number(optimal[key], unit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className={panel}>
        <CoverageTable data={data} />
      </div>

      <details className={panel} open>
        <summary className="font-semibold cursor-pointer">
          Model, coverage and calculation details
        </summary>
        <ul className="list-disc pl-5 text-sm space-y-1">
          {data.warnings.map(warning => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
        <p className="text-sm">
          One continuous DP over {data.periods.length} observed quarters; SOC carries across
          midnight. Initial energy {number(comparison.initialEnergyKwh, 'kWh')}; recorded terminal
          minimum {number(comparison.terminalEnergyKwh, 'kWh')}; modeled terminal{' '}
          {number(comparison.modelTerminalEnergyKwh, 'kWh')}. Excess terminal energy receives no
          cost credit. Solve time {number(comparison.solver.solveSeconds, 's')}.
        </p>
        <p className="text-sm">
          Missed savings = actual total economic cost − hindsight total economic cost. Captured =
          (solar-only total − actual total) / (solar-only total − hindsight total) × 100. Wear is
          charged per kWh charged, at the modelled battery's wear rate. Solar self-consumption
          includes solar stored in the battery; it does not track the eventual destination of that
          stored solar.
        </p>
      </details>
    </details>
  );
};

export default ProofSection;
