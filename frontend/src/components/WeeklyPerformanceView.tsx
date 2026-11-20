import React, { useEffect, useState } from 'react';
import { isAxiosError } from 'axios';
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import DateSelector from './DateSelector';
import api from '../lib/api';
import { WeeklyPerformance } from '../types';
import { toISODate } from '../utils/timeUtils';
import { weeklyFlowRows } from '../utils/weeklyPerformance';

const panel = 'min-w-0 bg-white dark:bg-gray-800 rounded-lg shadow p-5 space-y-3';
const dayLabel = (value: string) => value.slice(5);
const number = (value: number | null | undefined, unit: string) =>
  value == null
    ? 'N/A'
    : `${value.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 })} ${unit}`;

const WeeklyPerformanceView: React.FC = () => {
  const [anchor, setAnchor] = useState<string>();
  const [data, setData] = useState<WeeklyPerformance | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [scenario, setScenario] = useState<'actual' | 'optimal'>('actual');
  const [retry, setRetry] = useState(0);
  const [mode, setMode] = useState<'verified' | 'estimated'>('verified');
  const [approved, setApproved] = useState(false);
  const [allowPartial, setAllowPartial] = useState(false);
  useEffect(() => {
    if (mode === 'estimated' && !approved) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(undefined);
    api
      .get<{ weeklyPerformance: WeeklyPerformance }>('/api/insights/weekly-performance', {
        params: {
          ...(anchor ? { date: anchor } : {}),
          mode,
          ...(mode === 'estimated'
            ? { assumptions_source: 'backup', allow_partial: allowPartial }
            : {}),
        },
        signal: controller.signal,
      })
      .then(({ data: response }) => {
        if (!controller.signal.aborted) setData(response.weeklyPerformance);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          setError(
            isAxiosError<{ detail: string }>(error)
              ? (error.response?.data.detail ?? error.message)
              : 'Weekly performance could not be loaded.'
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [anchor, retry, mode, approved, allowPartial]);

  const currency = data?.currency ?? '';
  const actual = data?.actual;
  const optimal = data?.optimal;
  const flows = data ? weeklyFlowRows(data, scenario) : [];
  const hasResult = data && ['complete', 'estimated', 'estimated_partial'].includes(data.status);
  const valid =
    !loading &&
    !error &&
    hasResult &&
    actual &&
    optimal &&
    (mode === 'verified' || approved) &&
    (data?.mode ?? 'verified') === mode;
  const captured = data?.capturedPercent;
  const tickTime = (value: string) =>
    new Date(value).toLocaleString(undefined, {
      timeZone: data?.timezone,
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  const socRows =
    data?.socTimeline ??
    (data?.periods.length
      ? [
          ...data.periods,
          {
            ...data.periods[data.periods.length - 1],
            timestamp: new Date(
              new Date(data.periods[data.periods.length - 1].timestamp).getTime() + 15 * 60 * 1000
            ).toISOString(),
            actualSoc: data.periods[data.periods.length - 1].actualSocEnd,
            optimalSoc: data.periods[data.periods.length - 1].optimalSocEnd,
            buyPrice: null,
          },
        ]
      : []);

  return (
    <section
      className="space-y-6 text-gray-900 dark:text-gray-100 [&_.recharts-cartesian-axis-tick-value]:fill-current [&_.recharts-default-tooltip]:!text-gray-900 dark:[&_.recharts-default-tooltip]:!bg-gray-700 dark:[&_.recharts-default-tooltip]:!text-gray-100"
      aria-label="Weekly Performance"
    >
      <div className={panel}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold">Weekly Performance</h1>
            <p className="text-sm text-gray-600 dark:text-gray-300 mt-1">
              Historical observations against a continuous hindsight model, with verification and
              assumptions kept separate.
            </p>
          </div>
          {data && (
            <div className="w-[300px] max-w-full [&>div>div:first-child]:!w-full">
              <DateSelector
                selectedDate={new Date(`${anchor ?? data.startDate}T00:00:00`)}
                onDateChange={date => setAnchor(toISODate(date))}
                availableDates={new Set(data.availableWeeks)}
                resolution="week"
                isLoading={loading}
              />
            </div>
          )}
        </div>
        {data && (
          <p className="text-sm">
            {data.startDate} – {data.endDate} · {data.timezone} ·{' '}
            {data.diagnostics
              ? `${data.diagnostics.actualPeriods}/${data.expectedPeriods} actual energy quarters; ${data.diagnostics.predictedPeriods} predicted`
              : `${data.verifiedPeriods}/${data.expectedPeriods} verified quarters`}{' '}
            ({data.coveragePercent.toFixed(1)}% actual-energy coverage)
          </p>
        )}
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label htmlFor="historical-analysis-mode">Historical analysis mode</label>
          <select
            id="historical-analysis-mode"
            value={mode}
            onChange={event => setMode(event.target.value as 'verified' | 'estimated')}
            className="rounded bg-white dark:bg-gray-700"
          >
            <option value="verified">Verified Historical</option>
            <option value="estimated">Estimated Historical</option>
          </select>
        </div>
        {mode === 'estimated' && (
          <div className="rounded border border-amber-300 dark:border-amber-700 p-3 space-y-3 text-sm">
            {data?.assumptionProfile ? (
              <>
                <p>
                  Backup assumption profile: {data.assumptionProfile.source} ·{' '}
                  {data.assumptionProfile.timezone}
                </p>
                <p>
                  {data.assumptionProfile.battery.totalCapacity} kWh · SOC{' '}
                  {data.assumptionProfile.battery.minSoc}–{data.assumptionProfile.battery.maxSoc}% ·
                  charge/discharge {data.assumptionProfile.battery.maxChargePowerKw}/
                  {data.assumptionProfile.battery.maxDischargePowerKw} kW · efficiency{' '}
                  {number(data.assumptionProfile.battery.efficiencyCharge * 100, '%')}/
                  {number(data.assumptionProfile.battery.efficiencyDischarge * 100, '%')} · wear{' '}
                  {number(
                    data.assumptionProfile.battery.cycleCostPerKwh,
                    `${data.assumptionProfile.currency}/kWh charged`
                  )}
                </p>
                <p>
                  Huawei capability declarations are recorded by the software; executable
                  period-list behavior has not been validated.
                </p>
                <label className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    checked={approved}
                    onChange={event => setApproved(event.target.checked)}
                  />
                  Use this backup configuration as an explicit assumption, not verified historical
                  settings.
                </label>
                <label className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    checked={allowPartial}
                    onChange={event => setAllowPartial(event.target.checked)}
                  />
                  Allow an observed-interval calculation when energy quarters are missing. Exclude
                  unknown costs and withhold full-week savings scores.
                </label>
              </>
            ) : (
              <p>
                {data?.assumptionProfileError ??
                  'No backup assumption profile is configured. Current settings are not substituted.'}
              </p>
            )}
          </div>
        )}
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
                    `${data.diagnostics.pricesVerified} provenance verified`,
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
        {hasResult && !loading && (
          <p className="text-sm text-amber-800 dark:text-amber-300">
            {data?.mode === 'estimated' ? 'Estimated Historical. ' : ''}Model estimate using
            delivered solar.{' '}
            {data?.scope === 'observed_intervals'
              ? 'Observed intervals only; full-week costs, missed savings and capture are unavailable. '
              : ''}
            Unmeasured available solar can change achievable savings.
          </p>
        )}
        {loading && <p role="status">Calculating weekly hindsight…</p>}
        {error && (
          <div role="alert">
            {error}{' '}
            <button className="underline" onClick={() => setRetry(r => r + 1)}>
              Retry
            </button>
          </div>
        )}
        {!loading && !error && data && !hasResult && (
          <div role="status" className="rounded bg-amber-50 dark:bg-amber-950 p-4">
            <h2 className="font-semibold">
              Comparison withheld — historical data or model coverage is insufficient
            </h2>
            <ul className="list-disc pl-5 mt-2 text-sm">
              {data.issues.map(issue => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
            <p className="text-sm mt-2">
              Missed savings and captured savings: N/A. Forecasts, zero-filled prices and current
              configuration are not substituted for observations.
            </p>
          </div>
        )}
      </div>

      {valid && data && (
        <>
          {data.scope === 'observed_intervals' && (
            <div className={panel}>
              <p className="font-semibold">
                Estimated observed-interval model · {data.periods.length}/{data.expectedPeriods}{' '}
                quarters
              </p>
              <p>
                Observed-cost model difference: {number(data.modelCostDifference, currency)}. This
                is not a complete-week missed-savings result or a verified Huawei schedule.
              </p>
              <p className="text-sm">
                Unknown energy quarters are excluded; the hypothetical battery holds energy through
                each gap. Gap household cost is unknown, not zero.
              </p>
            </div>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
            {[
              ['Actual net grid cost', number(actual.netGridCost, currency)],
              ['Hindsight net grid cost', number(optimal.netGridCost, currency)],
              ['Missed savings opportunity', number(data.missedSavings, currency)],
              ['Achievable savings captured', number(captured, '%')],
              ['Actual battery throughput', number(actual.throughputKwh, 'kWh')],
              ['Actual cycle wear cost', number(actual.wearCost, currency)],
              ['Actual solar self-consumption', number(actual.solarSelfConsumptionPercent, '%')],
              ['Actual solar export', number(actual.solarExportKwh, 'kWh')],
            ].map(([label, value]) => (
              <div className={panel} key={label}>
                <h2 className="text-sm text-gray-600 dark:text-gray-300">{label}</h2>
                <p className="text-2xl font-semibold">{value}</p>
              </div>
            ))}
          </div>

          <div className={panel}>
            <h2 className="font-semibold text-lg">Recorded operation vs hindsight model</h2>
            <p className="text-sm">
              {data.scope === 'observed_intervals'
                ? 'Energy and costs cover observed quarters only. '
                : ''}
              SOC is recorded or constrained at the stated boundaries. Huawei execution and
              historical configuration assumptions remain separate from physical model feasibility.
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
                      ['Solar only', data.solarOnly],
                      ['BESS Manager actual', actual],
                      ['Hindsight model', optimal],
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
          </div>

          <div className={panel}>
            <h2 className="font-semibold text-lg">Actual vs optimal net grid cost</h2>
            <p className="text-sm">
              {data.scope === 'observed_intervals' ? 'Observed actual subtotal' : 'Weekly actual'}{' '}
              {number(actual.netGridCost, currency)} · hindsight model{' '}
              {number(optimal.netGridCost, currency)}
            </p>
            {data.scope === 'observed_intervals' && (
              <p className="text-sm">
                Daily bars exclude unknown energy quarters; these are not complete daily or weekly
                totals.
              </p>
            )}
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={data.daily}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={dayLabel} />
                <YAxis unit={` ${currency}`} width={80} />
                <Tooltip formatter={value => number(Number(value), currency)} />
                <Legend />
                <ReferenceLine y={0} stroke="#9ca3af" />
                <Bar
                  isAnimationActive={false}
                  dataKey="actualGridCost"
                  name="Actual net grid cost"
                  fill="#3b82f6"
                />
                <Bar
                  isAnimationActive={false}
                  dataKey="optimalGridCost"
                  name="Hindsight net grid cost"
                  fill="#10b981"
                />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className={panel}>
            <h2 className="font-semibold text-lg">Battery SOC: actual vs optimal</h2>
            <p className="text-sm">
              Quarter-hour boundaries in {data.timezone}; import and export prices retain historical
              charges.
            </p>
            <div className="overflow-x-auto">
              <div className="min-w-[640px]">
                <ResponsiveContainer width="100%" height={300}>
                  <ComposedChart data={socRows}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="timestamp" tickFormatter={tickTime} minTickGap={80} />
                    <YAxis yAxisId="soc" domain={[0, 100]} unit="%" />
                    <YAxis
                      yAxisId="price"
                      orientation="right"
                      unit={` ${currency}/kWh`}
                      width={100}
                    />
                    <Tooltip
                      labelFormatter={value => tickTime(String(value))}
                      formatter={(value, name) =>
                        number(
                          Number(value),
                          name === 'Import price' || name === 'Export price'
                            ? `${currency}/kWh`
                            : '%'
                        )
                      }
                    />
                    <Legend />
                    <Line
                      yAxisId="soc"
                      dataKey="actualSoc"
                      name="Actual SOC"
                      stroke="#3b82f6"
                      dot={false}
                      isAnimationActive={false}
                    />
                    <Line
                      yAxisId="soc"
                      dataKey="optimalSoc"
                      name="Hindsight SOC"
                      stroke="#10b981"
                      dot={false}
                      isAnimationActive={false}
                    />
                    <Line
                      yAxisId="price"
                      dataKey="buyPrice"
                      name="Import price"
                      stroke="#f59e0b"
                      dot={false}
                      isAnimationActive={false}
                    />
                    <Line
                      yAxisId="price"
                      dataKey="sellPrice"
                      name="Export price"
                      stroke="#a855f7"
                      dot={false}
                      isAnimationActive={false}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <label htmlFor="weekly-flow-scenario">Energy flow scenario</label>
            <select
              id="weekly-flow-scenario"
              className="rounded bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600"
              value={scenario}
              onChange={e => setScenario(e.target.value as 'actual' | 'optimal')}
            >
              <option value="actual">Actual</option>
              <option value="optimal">Hindsight model</option>
            </select>
          </div>
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
            <div className={panel}>
              <h2 className="font-semibold text-lg">Household supply ↑ / grid export ↓</h2>
              {scenario === 'actual' && !!data.actualValidation?.energyBalanceMismatches && (
                <p className="text-sm text-amber-800 dark:text-amber-300">
                  Recorded meters exceed reconciliation tolerance in{' '}
                  {data.actualValidation.energyBalanceMismatches} quarters (maximum{' '}
                  {number(data.actualValidation.maxEnergyBalanceErrorKwh, 'kWh')}). Raw observations
                  are retained.
                </p>
              )}
              <p className="text-sm">
                Daily kWh. Positive supply serves the home; exports appear below zero.
              </p>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={flows} stackOffset="sign">
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" tickFormatter={dayLabel} />
                  <YAxis unit=" kWh" width={85} />
                  <Tooltip formatter={value => number(Math.abs(Number(value)), 'kWh')} />
                  <Legend />
                  <ReferenceLine y={0} stroke="#6b7280" />
                  <Bar
                    isAnimationActive={false}
                    dataKey="solarHome"
                    name="Solar → Home"
                    stackId="flow"
                    fill="#f59e0b"
                  />
                  <Bar
                    isAnimationActive={false}
                    dataKey="batteryHome"
                    name="Battery → Home"
                    stackId="flow"
                    fill="#10b981"
                  />
                  <Bar
                    isAnimationActive={false}
                    dataKey="gridHome"
                    name="Grid → Home"
                    stackId="flow"
                    fill="#3b82f6"
                  />
                  <Bar
                    isAnimationActive={false}
                    dataKey="solarExport"
                    name="Solar → Grid"
                    stackId="flow"
                    fill="#f97316"
                  />
                  <Bar
                    isAnimationActive={false}
                    dataKey="batteryExport"
                    name="Battery → Grid"
                    stackId="flow"
                    fill="#8b5cf6"
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className={panel}>
              <h2 className="font-semibold text-lg">Battery discharge ↑ / charging ↓</h2>
              <p className="text-sm">
                Daily kWh. Charging is battery input energy, separate from household supply.
              </p>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={flows} stackOffset="sign">
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" tickFormatter={dayLabel} />
                  <YAxis unit=" kWh" width={85} />
                  <Tooltip formatter={value => number(Math.abs(Number(value)), 'kWh')} />
                  <Legend />
                  <ReferenceLine y={0} stroke="#6b7280" />
                  <Bar
                    isAnimationActive={false}
                    dataKey="discharge"
                    name="Battery discharge"
                    stackId="battery"
                    fill="#10b981"
                  />
                  <Bar
                    isAnimationActive={false}
                    dataKey="solarCharge"
                    name="Solar → Battery"
                    stackId="battery"
                    fill="#f59e0b"
                  />
                  <Bar
                    isAnimationActive={false}
                    dataKey="gridCharge"
                    name="Grid → Battery"
                    stackId="battery"
                    fill="#3b82f6"
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className={panel}>
            <h2 className="font-semibold text-lg">Optimization opportunity</h2>
            <p>
              Captured {number(captured, '%')} · missed opportunity{' '}
              {number(data.missedSavings, currency)} (including wear)
            </p>
            {captured != null && captured >= 0 && captured <= 100 ? (
              <div
                role="img"
                aria-label={`Captured ${captured.toFixed(1)}%, remaining ${(100 - captured).toFixed(1)}%`}
                className="flex h-7 rounded overflow-hidden bg-amber-200 dark:bg-amber-800"
              >
                <div className="bg-emerald-500" style={{ width: `${captured}%` }} />
              </div>
            ) : (
              <p className="text-sm">
                {captured == null
                  ? data.scope === 'observed_intervals'
                    ? 'N/A: complete-week energy coverage is insufficient.'
                    : data.executionVerified === false
                      ? 'N/A: inverter execution is unverified.'
                      : 'N/A: no positive achievable battery saving.'
                  : 'Value outside 0–100%; see model warnings. No bounded percentage bar is shown.'}
              </p>
            )}
            <p className="text-sm">Green: captured savings · amber: remaining achievable savings</p>
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
              midnight. Initial energy {number(data.initialEnergyKwh, 'kWh')}; recorded terminal
              minimum {number(data.terminalEnergyKwh, 'kWh')}; modeled terminal{' '}
              {number(data.modelTerminalEnergyKwh, 'kWh')}. Excess terminal energy receives no cost
              credit. Solve time {number(data.solveSeconds, 's')}.
            </p>
            <p className="text-sm">
              Missed savings = actual total economic cost − hindsight total economic cost. Captured
              = (solar-only total − actual total) / (solar-only total − hindsight total) × 100. Wear
              is charged per kWh charged, using the selected historical model. Solar
              self-consumption includes solar stored in the battery; it does not track the eventual
              destination of that stored solar.
            </p>
          </details>
        </>
      )}
    </section>
  );
};

export default WeeklyPerformanceView;
