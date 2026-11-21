import React from 'react';
import { PerformanceResult, PerformanceScenario } from '../../types';
import { number, panel } from './format';

/** The collapsed evidence: model inputs, cost tables, coverage and notes. */
const ProofSection: React.FC<{
  data: PerformanceResult;
  actual: PerformanceScenario;
  optimal: PerformanceScenario;
  currency: string;
  modelBattery: Record<string, number>;
}> = ({ data, actual, optimal, currency, modelBattery }) => (
  <details className="space-y-6">
    <summary className="text-xl font-semibold pt-4 cursor-pointer">
      Verification and calculation proof
    </summary>
    <div className={panel}>
      <h2 className="font-semibold text-lg">Model inputs</h2>
      {data.assumptionProfile && data.mode === 'estimated' ? (
        <div className="text-sm space-y-1">
          <p>
            Battery model assumed for this week: {data.assumptionProfile.source} ·{' '}
            {data.assumptionProfile.timezone}
          </p>
          <p>
            {modelBattery.totalCapacity} kWh · SOC {modelBattery.minSoc}–{modelBattery.maxSoc}% ·
            charge/discharge {modelBattery.maxChargePowerKw}/{modelBattery.maxDischargePowerKw} kW ·
            efficiency {number(modelBattery.efficiencyCharge * 100, '%')}/
            {number(modelBattery.efficiencyDischarge * 100, '%')} · wear{' '}
            {number(modelBattery.cycleCostPerKwh, `${data.assumptionProfile.currency}/kWh charged`)}
          </p>
          {data.efficiencyCalibration?.applied && (
            <p>
              Efficiency calibrated from {data.efficiencyCalibration.source}:{' '}
              {number((data.efficiencyCalibration.charge ?? 0) * 100, '%')} charge /{' '}
              {number((data.efficiencyCalibration.discharge ?? 0) * 100, '%')} discharge (configured{' '}
              {number(data.efficiencyCalibration.configuredCharge * 100, '%')} /{' '}
              {number(data.efficiencyCalibration.configuredDischarge * 100, '%')})
              {data.efficiencyCalibration.capped
                ? '; the history implies more than 100 %, so meter and SOC readings disagree.'
                : '.'}
            </p>
          )}
        </div>
      ) : (
        <p className="text-sm">Battery model recorded with the history.</p>
      )}
    </div>

    {data.scope === 'observed_intervals' && (
      <div className={panel}>
        <p className="font-semibold">
          Estimated observed-interval model · {data.periods.length}/{data.expectedPeriods} quarters
        </p>
        <p>
          Observed-cost model difference: {number(data.modelCostDifference, currency)}. This is not
          a complete-week missed-savings result or a verified Huawei schedule.
        </p>
        <p className="text-sm">
          Unknown energy quarters are excluded; the hypothetical battery holds energy through each
          gap. Gap household cost is unknown, not zero.
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
                ['Grid only · no solar, no battery', data.gridOnly],
                ['Solar only · no battery', data.solarOnly],
                ['BESS Manager actual', actual],
                ['Hindsight · relaxed lower-cost bound', optimal],
                ...(data.huaweiFeasible
                  ? ([
                      ['Hindsight intents replayed with Huawei TOU rules', data.huaweiFeasible],
                    ] as const)
                  : []),
              ] as const
            ).map(([name, cost]) => (
              <tr key={name} className="border-t border-gray-200 dark:border-gray-700">
                <th className="py-3">{name}</th>
                <td>{number(cost?.netGridCost, currency)}</td>
                <td>{number(cost?.wearCost, currency)}</td>
                <td>{number(cost?.totalEconomicCost, currency)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.huaweiFeasible && (
        <p className="text-sm mt-2">
          The relaxed bound may use actions a Huawei period list cannot execute (for example battery
          export). The Huawei replay executes the same intents as charge periods at full power,
          load-following discharge periods and idle otherwise; it is a feasible schedule, not the
          Huawei optimum, and its rules are inferred from observed operation.
          {data.huaweiFeasible.comparable
            ? ''
            : ` It ends ${number(data.huaweiFeasible.terminalShortfallKwh, 'kWh')} below the measured closing energy; terminal-adjusted total ${number(data.huaweiFeasible.terminalAdjustedTotalCost, currency)}.`}
        </p>
      )}
      {data.priceReferenceSource && (
        <p className="text-sm mt-2">Prices: {data.priceReferenceSource}.</p>
      )}
    </div>

    <div className={panel}>
      <h2 className="font-semibold text-lg">Recorded operation vs hindsight model</h2>
      <p className="text-sm">
        {data.scope === 'observed_intervals'
          ? 'Energy and costs cover observed quarters only. '
          : ''}
        SOC is recorded or constrained at the stated boundaries. Huawei execution and historical
        configuration assumptions remain separate from physical model feasibility.
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
      {data?.diagnostics && (
        <div className="overflow-x-auto">
          <table className="min-w-[540px] w-full text-sm text-left">
            <caption className="text-left font-semibold mb-2">
              Independent historical coverage
            </caption>
            <thead>
              <tr>
                <th>Input</th>
                <th>Available / recorded</th>
                <th>Verification / assumptions</th>
              </tr>
            </thead>
            <tbody>
              {[
                [
                  'Energy periods',
                  `${data.diagnostics.actualPeriods} actual; ${data.diagnostics.predictedPeriods} predicted`,
                  `${data.diagnostics.energyVerified} provenance verified`,
                ],
                [
                  'Historical import / export prices',
                  `${data.diagnostics.pricesAvailable}/${data.expectedPeriods} valid numeric pairs`,
                  data.priceReferenceSource
                    ? `${data.diagnostics.pricesReferenceConfirmed} match published day-ahead; ${data.diagnostics.pricesReferenceMismatched} differ (repriced in estimated mode); ${data.diagnostics.pricesReferenceMissing} without reference`
                    : `${data.diagnostics.pricesVerified} provenance verified; no published reference configured`,
                ],
                [
                  'Battery SOC / SoE',
                  `${data.diagnostics.socAvailable} actual records with numeric states`,
                  `${data.diagnostics.socVerified} provenance verified`,
                ],
                [
                  'Historical configuration',
                  `${data.diagnostics.configurationRecorded} recorded`,
                  `${data.diagnostics.configurationAssumed} assumed`,
                ],
                [
                  'Inverter capabilities',
                  `${data.diagnostics.capabilitiesRecorded} recorded`,
                  `${data.diagnostics.capabilitiesAssumed} assumed; execution ${data.executionVerified == null ? 'not checked' : data.executionVerified ? 'replayed' : 'unverified'}`,
                ],
                [
                  'Physical constraint settings',
                  `${data.diagnostics.constraintsRecorded} recorded`,
                  data.mode === 'estimated'
                    ? 'Backup model assumptions'
                    : 'Recorded model required',
                ],
                [
                  'Legacy recording artefacts',
                  `${data.diagnostics.restartPlaceholders ?? 0} zero-filled restart quarters`,
                  `${data.diagnostics.socDropouts ?? 0} quarters with SOC recorded as 0 % (shown as unknown)`,
                ],
                [
                  'Missing / invalid records',
                  `${data.diagnostics.missingPeriods} missing; ${data.diagnostics.invalidRecords} invalid`,
                  `${data.excludedIntervals?.length ?? 0} energy intervals excluded`,
                ],
                [
                  'Optimizer energy feasibility',
                  data.diagnostics.optimizerFeasible == null
                    ? 'Not run'
                    : data.diagnostics.optimizerFeasible
                      ? 'Passed physical model checks'
                      : 'Rejected',
                  'Separate from inverter executability',
                ],
              ].map(([name, count, explanation]) => (
                <tr key={name} className="border-t border-gray-200 dark:border-gray-700">
                  <th className="py-2 pr-3">{name}</th>
                  <td className="pr-3">{count}</td>
                  <td>{explanation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
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
        One continuous DP over {data.periods.length} observed quarters; SOC carries across midnight.
        Initial energy {number(data.initialEnergyKwh, 'kWh')}; recorded terminal minimum{' '}
        {number(data.terminalEnergyKwh, 'kWh')}; modeled terminal{' '}
        {number(data.modelTerminalEnergyKwh, 'kWh')}. Excess terminal energy receives no cost
        credit. Solve time {number(data.solveSeconds, 's')}.
      </p>
      <p className="text-sm">
        Missed savings = actual total economic cost − hindsight total economic cost. Captured =
        (solar-only total − actual total) / (solar-only total − hindsight total) × 100. Wear is
        charged per kWh charged, using the selected historical model. Solar self-consumption
        includes solar stored in the battery; it does not track the eventual destination of that
        stored solar.
      </p>
    </details>
  </details>
);

export default ProofSection;
