import React, { useEffect, useState } from 'react';
import { isAxiosError } from 'axios';
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  Battery,
  CheckCircle,
  Activity,
  DollarSign,
  Sun,
  Target,
  TrendingDown,
  Zap,
} from 'lucide-react';
import DateSelector from './DateSelector';
import ProofSection from './performance/ProofSection';
import { number, panel } from './performance/format';
import CostComparison, { CostScenario } from './performance/CostComparison';
import CoverageStrip from './performance/CoverageStrip';
import CoverageTable from './performance/CoverageTable';
import MissedValueHeatmap from './performance/MissedValueHeatmap';
import api from '../lib/api';
import { PerformanceResult } from '../types';
import { toISODate } from '../utils/timeUtils';
import {
  bandRuns,
  cumulativeSavings,
  dailyStrategy,
  hourlyStrategyRows,
  tradingStats,
  weeklyFlowRows,
} from '../utils/performance';

const dayLabel = (value: string) => value.slice(5);

const PerformanceView: React.FC = () => {
  const [anchor, setAnchor] = useState<string>();
  const [data, setData] = useState<PerformanceResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [retry, setRetry] = useState(0);
  const [strategyDay, setStrategyDay] = useState<string>();
  const [period, setPeriod] = useState<'week' | 'month'>('week');
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(undefined);
    api
      .get<{ performance: PerformanceResult }>('/api/insights/performance', {
        params: { period, ...(anchor ? { date: anchor } : {}) },
        signal: controller.signal,
      })
      .then(({ data: response }) => {
        if (!controller.signal.aborted) setData(response.performance);
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
  }, [anchor, retry, period]);

  const currency = data?.currency ?? '';
  const comparison = data?.comparison ?? null;
  const actual = comparison?.actual;
  const optimal = comparison?.optimal;
  const gridOnly = comparison?.gridOnly;
  const solarOnly = comparison?.solarOnly;
  const flowRows = {
    actual: data ? weeklyFlowRows(data, 'actual') : [],
    optimal: data ? weeklyFlowRows(data, 'optimal') : [],
  };
  // One axis for both scenarios, so equal bar heights mean equal energy.
  const sharedDomain = (keys: string[]): [number, number] => {
    let low = 0;
    let high = 0;
    for (const row of [...flowRows.actual, ...flowRows.optimal]) {
      const values = keys.map(key => Number((row as Record<string, unknown>)[key] ?? 0));
      high = Math.max(
        high,
        values.filter(v => v > 0).reduce((a, b) => a + b, 0)
      );
      low = Math.min(
        low,
        values.filter(v => v < 0).reduce((a, b) => a + b, 0)
      );
    }
    const step = [5, 10, 20, 25, 50, 100].find(size => (high - low) / size <= 6) ?? 200;
    return [Math.floor(low / step) * step, Math.ceil(high / step) * step];
  };
  const domainTicks = ([low, high]: [number, number]) => {
    const step = [5, 10, 20, 25, 50, 100].find(size => (high - low) / size <= 6) ?? 200;
    return Array.from({ length: Math.round((high - low) / step) + 1 }, (_, i) => low + i * step);
  };
  const householdKeys = ['solarHome', 'batteryHome', 'gridHome', 'solarExport', 'batteryExport'];
  const batteryKeys = ['discharge', 'solarCharge', 'gridCharge'];
  const pairedFlows = flowRows.actual.map((row, index) => ({
    date: row.date,
    actual: row,
    optimal: flowRows.optimal[index],
  }));
  const strategyDays = data ? dailyStrategy(data) : [];
  // Open on the day where the two strategies differed most in cost.
  const biggestDay = [...strategyDays].sort(
    (a, b) => Math.abs(b.costDifference) - Math.abs(a.costDifference)
  )[0]?.date;
  // A whole month of hourly bars is unreadable, so a month is shown day by day.
  const mondayOf = (iso: string) => {
    const date = new Date(`${iso}T00:00:00`);
    date.setDate(date.getDate() - ((date.getDay() + 6) % 7));
    return toISODate(date);
  };
  const strategyWeeks =
    period === 'month' ? [...new Set(strategyDays.map(day => mondayOf(day.date)))] : [];
  // Selection: 'week' (whole week view), 'week:<monday>' (a week of a month) or a day.
  const selection =
    strategyDay === 'week' && period === 'week'
      ? 'week'
      : strategyDay?.startsWith('week:') && strategyWeeks.includes(strategyDay.slice(5))
        ? strategyDay
        : strategyDays.some(day => day.date === strategyDay)
          ? strategyDay
          : biggestDay;
  const selectedDays =
    selection === 'week' || selection == null
      ? undefined
      : selection.startsWith('week:')
        ? strategyDays.map(day => day.date).filter(day => mondayOf(day) === selection.slice(5))
        : [selection];
  const singleDay = selectedDays?.length === 1;
  // Weekly subtotals of a month, from the same per-day figures as the charts.
  const weeklyReports = Object.values(
    (period === 'month' && data ? data.daily : []).reduce<
      Record<string, { days: typeof data.daily; monday: string }>
    >((weeks, day) => {
      const date = new Date(`${day.date}T00:00:00`);
      date.setDate(date.getDate() - ((date.getDay() + 6) % 7));
      const monday = toISODate(date);
      weeks[monday] = weeks[monday] ?? { days: [], monday };
      weeks[monday].days.push(day);
      return weeks;
    }, {})
  ).map(({ days, monday }) => {
    const sum = (pick: (day: (typeof days)[number]) => number) =>
      days.reduce((total, day) => total + pick(day), 0);
    const solar = sum(day => day.solarOnlyCost ?? 0);
    const actualCost = sum(day => day.actualGridCost + (day.actualWearCost ?? 0));
    const optimalCost = sum(day => day.optimalGridCost + (day.optimalWearCost ?? 0));
    return {
      monday,
      first: days[0].date,
      last: days[days.length - 1].date,
      observed: sum(day => day.observedPeriods ?? 0),
      gridOnly: sum(day => day.gridOnlyCost ?? 0),
      solar,
      actualCost,
      optimalCost,
      capture:
        solar - optimalCost > 1e-9 ? (100 * (solar - actualCost)) / (solar - optimalCost) : null,
    };
  });
  const costScenarios: CostScenario[] =
    comparison && gridOnly && solarOnly && actual && optimal
      ? [
          {
            label: 'Grid only',
            cost: gridOnly.totalEconomicCost,
            description: 'No solar or battery',
            tone: 'baseline',
          },
          {
            label: 'Solar only',
            cost: solarOnly.totalEconomicCost,
            description: 'No battery',
            tone: 'baseline',
          },
          {
            label: 'Actual BESS',
            cost: actual.totalEconomicCost,
            description: 'Including battery wear',
            tone: 'actual',
          },
          {
            label: 'Relaxed hindsight',
            cost: optimal.totalEconomicCost,
            description: comparison.executionReplayed
              ? 'Physical model with inverter replay'
              : 'Physical model; inverter execution not modelled',
            tone: 'hindsight',
          },
        ]
      : [];
  const trading = tradingStats(strategyDays);
  const describe = (side: (typeof strategyDays)[number]['actual']) =>
    [
      side.chargedKwh > 0.05
        ? `charged ${number(side.chargedKwh, 'kWh')} at ${price(side.chargePrice)}${side.chargeHours ? ` (${side.chargeHours})` : ''}`
        : 'did not charge',
      side.dischargedKwh > 0.05
        ? `discharged ${number(side.dischargedKwh, 'kWh')} while import averaged ${price(side.dischargePrice)}`
        : 'did not discharge',
    ].join(' and ');
  const hourRows = data ? hourlyStrategyRows(data, selectedDays) : [];
  const bands = bandRuns(hourRows);
  const hourTicks = hourRows
    .map(row => row.hour)
    .filter(hour => {
      const local = Number(
        new Date(hour).toLocaleString('en-GB', {
          timeZone: data?.timezone,
          hour: '2-digit',
          hour12: false,
        })
      );
      return singleDay ? local % 3 === 0 : local === 0;
    });
  const hourLabel = (hour: string) =>
    new Date(hour).toLocaleString(undefined, {
      timeZone: data?.timezone,
      ...(singleDay
        ? { hour: '2-digit', minute: '2-digit' }
        : { weekday: 'short', day: 'numeric', month: 'numeric' }),
    });
  const hourTooltip = ({
    active,
    payload,
  }: {
    active?: boolean;
    payload?: { payload: (typeof hourRows)[number] }[];
  }) => {
    const row = active && payload?.length ? payload[0].payload : null;
    if (!row) return null;
    return (
      <div className="rounded border border-gray-300 bg-white dark:bg-gray-700 p-2 text-xs space-y-0.5">
        <p className="font-semibold">
          {new Date(row.hour).toLocaleString(undefined, {
            timeZone: data?.timezone,
            weekday: 'short',
            day: 'numeric',
            month: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
          })}
        </p>
        {row.actualKwh == null ? (
          <p>Unknown hour (no observed quarters)</p>
        ) : (
          <>
            <p>Import price {price(row.buyPrice)}</p>
            <p>Actual battery {number(row.actualKwh, 'kWh')} (+ charge, − discharge)</p>
            <p>Hindsight battery {number(row.optimalKwh, 'kWh')}</p>
            <p>
              Grid cost effect:{' '}
              {row.costDifference != null && row.costDifference >= 0
                ? `hindsight ${number(row.costDifference, currency)} cheaper`
                : `actual ${number(Math.abs(row.costDifference ?? 0), currency)} cheaper`}
            </p>
          </>
        )}
      </div>
    );
  };
  const price = (value: number | null) =>
    value == null ? 'N/A' : `${value.toFixed(3)} ${currency}/kWh`;
  const dailySavings = (data?.daily ?? []).map(day => ({
    date: day.date,
    actualSaving:
      day.gridOnlyCost == null
        ? null
        : day.gridOnlyCost - day.actualGridCost - (day.actualWearCost ?? 0),
    optimalSaving:
      day.gridOnlyCost == null
        ? null
        : day.gridOnlyCost - day.optimalGridCost - (day.optimalWearCost ?? 0),
  }));
  const gridOnlyActualSaving =
    gridOnly && actual ? gridOnly.totalEconomicCost - actual.totalEconomicCost : null;
  const gridOnlyOptimalSaving =
    gridOnly && optimal ? gridOnly.totalEconomicCost - optimal.totalEconomicCost : null;
  const missed = comparison?.missedSavings ?? null;
  const capture = comparison?.capturedPercent ?? null;
  // The analysis may calibrate the battery to what it demonstrably did.
  const modelBattery = data?.batteryModel ?? null;
  const cumulative = data ? cumulativeSavings(data, modelBattery?.cycleCostPerKwh ?? 0) : [];
  const kpis = [
    {
      label: 'Actual net grid cost',
      value: number(actual?.netGridCost, currency),
      Icon: DollarSign,
      tone: '',
    },
    {
      label: 'Hindsight optimal net grid cost',
      value: number(optimal?.netGridCost, currency),
      Icon: Target,
      tone: '',
    },
    {
      label: 'Missed savings opportunity',
      value: number(missed, currency),
      Icon: TrendingDown,
      tone: 'text-red-600 dark:text-red-400',
    },
    {
      label: 'Battery savings captured',
      value: number(capture, '%'),
      Icon: CheckCircle,
      tone: 'text-emerald-600 dark:text-emerald-400',
    },
    {
      label: 'Battery efficiency',
      value:
        modelBattery == null
          ? 'N/A'
          : `In ${(modelBattery.efficiencyCharge * 100).toFixed(1)} %\nOut ${(modelBattery.efficiencyDischarge * 100).toFixed(1)} %`,
      Icon: Activity,
      tone: '',
      note: modelBattery?.efficiencyCalibration?.applied
        ? modelBattery.efficiencyCalibration.capped
          ? 'Calibrated · capped at 100 %'
          : 'Calibrated from history'
        : 'Configured',
    },
    {
      label: 'Battery throughput',
      value: number(actual?.throughputKwh, 'kWh'),
      Icon: Battery,
      tone: '',
    },
    {
      label: 'Estimated cycle wear cost',
      value: number(actual?.wearCost, currency),
      Icon: Activity,
      tone: '',
    },
    {
      label: 'Solar self-consumption',
      value: number(actual?.solarSelfConsumptionPercent, '%'),
      Icon: Sun,
      tone: 'text-emerald-600 dark:text-emerald-400',
    },
    {
      label: 'Solar export',
      value: number(actual?.solarExportKwh, 'kWh'),
      Icon: Zap,
      tone: '',
    },
  ];
  const batteryBenefit =
    solarOnly && actual ? solarOnly.totalEconomicCost - actual.totalEconomicCost : null;
  const hasResult = comparison != null;
  const partial = data?.status === 'estimated_partial';
  const valid = !loading && !error && comparison && actual && optimal;
  const tickTime = (value: string) =>
    new Date(value).toLocaleString(undefined, {
      timeZone: data?.timezone,
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  const socRows = data?.socTimeline ?? [];

  return (
    <section
      className="space-y-6 text-gray-900 dark:text-gray-100 [&_.recharts-cartesian-axis-tick-value]:fill-current [&_.recharts-default-tooltip]:!text-gray-900 dark:[&_.recharts-default-tooltip]:!bg-gray-700 dark:[&_.recharts-default-tooltip]:!text-gray-100"
      aria-label="Performance"
    >
      <div className={panel}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold">Performance</h1>
            <p className="text-sm text-gray-600 dark:text-gray-300 mt-1">
              Recorded history against a continuous perfect-hindsight model. Every figure is an
              estimate on your current battery, home and inverter settings.
            </p>
          </div>
          {data && (
            <div className="flex flex-wrap items-center gap-3">
              <div
                className="flex rounded border border-gray-300 dark:border-gray-600 overflow-hidden text-sm"
                role="group"
                aria-label="Analysis period"
              >
                {(['week', 'month'] as const).map(option => (
                  <button
                    key={option}
                    type="button"
                    aria-pressed={period === option}
                    onClick={() => {
                      setPeriod(option);
                      setAnchor(undefined);
                      setStrategyDay(undefined);
                    }}
                    className={`px-3 py-1 ${period === option ? 'bg-blue-600 text-white' : ''}`}
                  >
                    {option === 'week' ? 'Week' : 'Month'}
                  </button>
                ))}
              </div>
              <div className="w-[300px] max-w-full [&>div>div:first-child]:!w-full">
                <DateSelector
                  selectedDate={new Date(`${anchor ?? data.startDate}T00:00:00`)}
                  onDateChange={date => setAnchor(toISODate(date))}
                  availableDates={new Set(data.availablePeriods)}
                  resolution={period}
                  isLoading={loading}
                />
              </div>
            </div>
          )}
        </div>
        {data && (
          <p className="text-sm">
            {data.startDate} – {data.endDate} · {data.timezone} ·{' '}
            {`${data.coverage.actualPeriods}/${data.coverage.expectedPeriods} actual energy quarters; ${data.coverage.predictedPeriods} predicted${data.coverage.restartPlaceholders ? `; ${data.coverage.restartPlaceholders} zero-filled restart placeholders` : ''}`}{' '}
            ({data.coverage.coveragePercent.toFixed(1)}% actual-energy coverage)
          </p>
        )}
        {data && hasResult && (
          <div className="flex flex-wrap items-center gap-2 text-xs font-semibold">
            <span
              className="rounded-full px-2 py-0.5 bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200"
              title="Modelled with your current settings for the whole period; the inputs are listed under Model inputs."
            >
              Estimate
            </span>
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-gray-700 dark:bg-gray-700 dark:text-gray-200">
              {data.coverage.coveragePercent.toFixed(0)} % coverage
            </span>
            {data.inProgress && (
              <span className="rounded-full bg-blue-100 px-2 py-0.5 text-blue-800 dark:bg-blue-900 dark:text-blue-200">
                In progress · to date
              </span>
            )}
          </div>
        )}
        {valid && data && (
          <p className="text-base">
            BESS saved <span className="font-semibold">{number(batteryBenefit, currency)}</span>{' '}
            against solar only. Perfect hindsight would have saved{' '}
            <span className="font-semibold">{number(missed, currency)}</span> more, so{' '}
            <span className="font-semibold">{number(capture, '%')}</span> of the achievable saving
            was captured.
          </p>
        )}
        {valid && data && <CoverageStrip data={data} />}
        {!valid && data && <CoverageTable data={data} />}
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
              Missed savings and captured savings: N/A. Forecasts and zero-filled prices are not
              substituted for observations.
            </p>
          </div>
        )}
      </div>

      {valid && data && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-9 gap-3">
            {kpis.map(({ label, value, Icon, tone, note }) => (
              <div className={`${panel} !p-4 !space-y-1`} key={label}>
                {/* A fixed three-line title block keeps every value on one baseline. */}
                <div className="flex items-start gap-2 h-[2.85rem] overflow-hidden text-gray-600 dark:text-gray-300">
                  <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                  <h2 className="text-xs leading-tight">{label}</h2>
                </div>
                <p
                  className={`font-semibold ${value.includes('\n') ? 'text-lg whitespace-pre' : 'text-xl whitespace-nowrap'} leading-7 ${tone}`}
                >
                  {value}
                </p>
                {note && <p className="text-xs text-amber-700 dark:text-amber-300">{note}</p>}
              </div>
            ))}
          </div>

          <section className={panel} aria-label="Cost comparison">
            <h2 className="font-semibold text-lg">
              Estimated cost comparison
              {partial ? ' · observed intervals' : ''}
            </h2>
            <p className="text-sm text-gray-600 dark:text-gray-300">
              Total energy cost including battery wear. Each bar compares the same observed
              quarters.
            </p>
            <CostComparison
              scenarios={costScenarios}
              format={value => number(value, currency)}
              batteryBenefit={batteryBenefit}
            />
            <details className="border-t border-gray-200 dark:border-gray-700 pt-3">
              <summary className="cursor-pointer text-sm font-semibold">
                Charging and discharging prices
              </summary>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
                {(
                  [
                    ['Average charging price', 'chargePrice'],
                    ['Average price avoided by discharging', 'dischargePrice'],
                    ['Spread captured per kWh', 'spread'],
                  ] as const
                ).map(([label, key]) => (
                  <div
                    key={key}
                    className="rounded border border-gray-200 dark:border-gray-700 p-3"
                  >
                    <p className="text-xs text-gray-600 dark:text-gray-300">{label}</p>
                    <p className="tabular-nums">
                      <span className="font-semibold">{price(trading.actual[key])}</span> actual
                    </p>
                    <p className="tabular-nums text-gray-600 dark:text-gray-300">
                      {price(trading.optimal[key])} hindsight
                    </p>
                  </div>
                ))}
              </div>
            </details>
          </section>

          {period === 'month' && weeklyReports.length > 0 && (
            <div className={panel}>
              <h2 className="font-semibold text-lg">Weekly reports</h2>
              <p className="text-sm">
                Each week's share of this month's continuous comparison, total cost including wear.
                Weeks at the month's edges cover only their days inside the month.
              </p>
              <div className="overflow-x-auto">
                <table className="min-w-[640px] w-full text-sm text-left">
                  <thead>
                    <tr>
                      <th>Week</th>
                      <th>Observed quarters</th>
                      <th>Grid only</th>
                      <th>Solar only</th>
                      <th>Actual</th>
                      <th>Hindsight</th>
                      <th>Missed</th>
                      <th>Captured</th>
                    </tr>
                  </thead>
                  <tbody>
                    {weeklyReports.map(week => (
                      <tr
                        key={week.monday}
                        className="border-t border-gray-200 dark:border-gray-700"
                      >
                        <th className="py-2">
                          {dayLabel(week.first)} – {dayLabel(week.last)}
                        </th>
                        <td>{week.observed}</td>
                        <td>{number(week.gridOnly, currency)}</td>
                        <td>{number(week.solar, currency)}</td>
                        <td>{number(week.actualCost, currency)}</td>
                        <td>{number(week.optimalCost, currency)}</td>
                        <td className="text-red-600 dark:text-red-400">
                          {number(week.actualCost - week.optimalCost, currency)}
                        </td>
                        <td className="text-emerald-700 dark:text-emerald-400">
                          {week.solar - week.actualCost < 0
                            ? 'Cost more than solar only'
                            : week.capture != null && week.capture > 100
                              ? 'Beat hindsight'
                              : number(week.capture, '%')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-gray-600 dark:text-gray-300">
                Captured is the share of the possible saving against solar only that was achieved.
                "Cost more than solar only" means the battery bought energy that week that was used
                in a later week, so the week alone looks worse than having no battery; the month as
                a whole is the fair measure.
              </p>
            </div>
          )}

          <div className={panel}>
            <h2 className="font-semibold text-lg">
              Daily net grid cost: grid only, actual, optimal
            </h2>
            <p className="text-sm">
              {partial ? 'Observed actual subtotal' : 'Weekly actual'}{' '}
              {number(actual.netGridCost, currency)} · hindsight model{' '}
              {number(optimal.netGridCost, currency)}
            </p>
            {partial && (
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
                  dataKey="gridOnlyCost"
                  name="Grid only (no solar, no battery)"
                  fill="#9ca3af"
                />
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
            <h3 className="font-semibold">Daily saving against grid only, after cycle wear</h3>
            <p className="text-sm">
              Grid-only cost minus net grid cost and wear: the combined benefit of solar and battery
              operation on the same quarters ({number(gridOnlyActualSaving, currency)} actual ·{' '}
              {number(gridOnlyOptimalSaving, currency)} hindsight).
            </p>
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={dailySavings}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={dayLabel} />
                <YAxis unit={` ${currency}`} width={80} />
                <Tooltip formatter={value => number(Number(value), currency)} />
                <Legend />
                <ReferenceLine y={0} stroke="#9ca3af" />
                <Bar
                  isAnimationActive={false}
                  dataKey="actualSaving"
                  name="Actual saving"
                  fill="#3b82f6"
                />
                <Bar
                  isAnimationActive={false}
                  dataKey="optimalSaving"
                  name="Hindsight saving"
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
                    <Area
                      yAxisId="price"
                      type="stepAfter"
                      dataKey="buyPrice"
                      name="Import price"
                      stroke="#f59e0b"
                      strokeOpacity={0.5}
                      fill="#f59e0b"
                      fillOpacity={0.15}
                      isAnimationActive={false}
                    />
                    <Area
                      yAxisId="price"
                      type="stepAfter"
                      dataKey="sellPrice"
                      name="Export price"
                      stroke="#a855f7"
                      strokeOpacity={0.5}
                      fill="#a855f7"
                      fillOpacity={0.15}
                      isAnimationActive={false}
                    />
                    <Line
                      yAxisId="soc"
                      dataKey="actualSoc"
                      name="Actual SOC"
                      stroke="#2563eb"
                      strokeWidth={3}
                      dot={false}
                      isAnimationActive={false}
                    />
                    <Line
                      yAxisId="soc"
                      dataKey="optimalSoc"
                      name="Hindsight SOC"
                      stroke="#059669"
                      strokeWidth={2}
                      strokeDasharray="6 4"
                      dot={false}
                      isAnimationActive={false}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          <div className={panel}>
            <h2 className="font-semibold text-lg">Cumulative saving against solar only</h2>
            <p className="text-sm">
              Running total after wear. Where the green line pulls away, hindsight found value the
              live schedule did not.
            </p>
            <div className="overflow-x-auto">
              <div className="min-w-[640px]">
                <ResponsiveContainer width="100%" height={240}>
                  <ComposedChart data={cumulative}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="timestamp" tickFormatter={tickTime} minTickGap={80} />
                    <YAxis unit={` ${currency}`} width={80} />
                    <Tooltip
                      labelFormatter={value => tickTime(String(value))}
                      formatter={value => number(Number(value), currency)}
                    />
                    <Legend />
                    <ReferenceLine y={0} stroke="#9ca3af" />
                    <Line
                      dataKey="actual"
                      name="Actual"
                      stroke="#2563eb"
                      strokeWidth={2.5}
                      dot={false}
                      isAnimationActive={false}
                    />
                    <Line
                      dataKey="optimal"
                      name="Hindsight"
                      stroke="#059669"
                      strokeWidth={2}
                      strokeDasharray="6 4"
                      dot={false}
                      isAnimationActive={false}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          <div className={panel}>
            <h2 className="font-semibold text-lg">Where the value was missed</h2>
            <p className="text-sm">
              Grid cost difference per hour: red where hindsight was cheaper, blue where actual was,
              grey where unknown.
            </p>
            <MissedValueHeatmap
              rows={hourlyStrategyRows(data)}
              timeZone={data.timezone}
              format={value => number(value, currency)}
            />
          </div>

          <div className={panel}>
            <h2 className="font-semibold text-lg">What hindsight did differently</h2>
            <p className="text-sm">
              Hourly battery energy: charging above zero, discharging below, as on the main screen.
              Green shading marks the day's cheapest quarter of hours, red its dearest; good timing
              charges in green and discharges in red. Hover for the cost effect. Gaps are unknown
              hours.
            </p>
            <div className="flex flex-wrap gap-2" role="group" aria-label="Strategy period">
              {[
                ...(period === 'week' ? [{ key: 'week', label: 'Whole week' }] : []),
                ...strategyWeeks.map(monday => {
                  const days = strategyDays
                    .map(day => day.date)
                    .filter(day => mondayOf(day) === monday);
                  return {
                    key: `week:${monday}`,
                    label: `Week ${dayLabel(days[0])}–${dayLabel(days[days.length - 1])}`,
                  };
                }),
                ...strategyDays.map(day => ({ key: day.date, label: dayLabel(day.date) })),
              ].map(option => (
                <button
                  key={option.key}
                  type="button"
                  aria-pressed={selection === option.key}
                  onClick={() => setStrategyDay(option.key)}
                  className={`rounded px-3 py-1 text-sm border ${
                    selection === option.key
                      ? 'bg-blue-600 text-white border-blue-600'
                      : option.key.startsWith('week')
                        ? 'border-blue-300 dark:border-blue-700 font-semibold'
                        : 'border-gray-300 dark:border-gray-600'
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <div className="overflow-x-auto">
              <div className="min-w-[640px]">
                <ResponsiveContainer width="100%" height={340}>
                  <ComposedChart data={hourRows} barGap={0} margin={{ left: 0, right: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis
                      dataKey="hour"
                      ticks={hourTicks}
                      tickFormatter={hourLabel}
                      interval={0}
                    />
                    <YAxis
                      yAxisId="energy"
                      unit=" kWh"
                      width={70}
                      label={{
                        value: 'Battery energy per hour',
                        angle: -90,
                        position: 'insideLeft',
                        offset: 10,
                        style: { fontSize: 12 },
                      }}
                    />
                    <YAxis
                      yAxisId="price"
                      orientation="right"
                      width={90}
                      stroke="#d97706"
                      tickFormatter={value => Number(value).toFixed(3)}
                      domain={[
                        (min: number) => Math.max(0, min - 0.01),
                        (max: number) => max + 0.01,
                      ]}
                      label={{
                        value: `Import price (${currency}/kWh)`,
                        angle: 90,
                        position: 'insideRight',
                        offset: 10,
                        style: { fontSize: 12, fill: '#d97706' },
                      }}
                    />
                    {bands.map(run => (
                      <ReferenceArea
                        key={`${run.band}-${run.from}`}
                        x1={run.from}
                        x2={run.to}
                        yAxisId="energy"
                        fill={run.band === 'cheap' ? '#10b981' : '#ef4444'}
                        fillOpacity={0.12}
                        ifOverflow="extendDomain"
                      />
                    ))}
                    <Tooltip content={hourTooltip} />
                    <Legend />
                    <ReferenceLine yAxisId="energy" y={0} stroke="#6b7280" />
                    <Bar
                      yAxisId="energy"
                      dataKey="actualKwh"
                      name="Actual (+ charge / − discharge)"
                      fill="#2563eb"
                      isAnimationActive={false}
                    />
                    <Bar
                      yAxisId="energy"
                      dataKey="optimalKwh"
                      name="Hindsight"
                      fill="#10b981"
                      fillOpacity={0.6}
                      isAnimationActive={false}
                    />
                    <Line
                      yAxisId="price"
                      type="step"
                      dataKey="buyPrice"
                      name="Import price (right axis)"
                      stroke="#d97706"
                      strokeWidth={2}
                      dot={false}
                      connectNulls={false}
                      isAnimationActive={false}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>
            <ul className="space-y-2 text-sm">
              {strategyDays
                .filter(day => !selectedDays || selectedDays.includes(day.date))
                .map(day => (
                  <li key={day.date}>
                    <span className="font-semibold">{dayLabel(day.date)}:</span> hindsight{' '}
                    {describe(day.optimal)}; actual {describe(day.actual)}.{' '}
                    {day.costDifference >= 0 ? 'Hindsight was ' : 'Actual was '}
                    {number(Math.abs(day.costDifference), currency)} cheaper that day, after wear.
                  </li>
                ))}
            </ul>
            <p className="text-xs text-gray-600 dark:text-gray-300">
              A single day can favour either side because energy bought one day is used the next;
              the whole {period}, with closing battery energy held equal, is the fair comparison.
            </p>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
            <div className={panel}>
              <h2 className="font-semibold text-lg">
                Household supply ↑ / grid export ↓ · actual vs hindsight
              </h2>
              {!!comparison?.actualValidation.energyBalanceMismatches && (
                <p className="text-sm text-amber-800 dark:text-amber-300">
                  Recorded meters exceed reconciliation tolerance in{' '}
                  {comparison.actualValidation.energyBalanceMismatches} actual quarters (maximum{' '}
                  {number(comparison.actualValidation.maxEnergyBalanceErrorKwh, 'kWh')}). Raw
                  observations are retained.
                </p>
              )}
              <p className="text-sm">
                Daily kWh. Positive supply serves the home; exports appear below zero. Each day:
                left bar actual (solid), right bar hindsight (lighter).
              </p>
              <ResponsiveContainer width="100%" height={320}>
                <BarChart data={pairedFlows} stackOffset="sign" barGap={2}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" tickFormatter={dayLabel} />
                  <YAxis
                    unit=" kWh"
                    width={85}
                    domain={sharedDomain(householdKeys)}
                    ticks={domainTicks(sharedDomain(householdKeys))}
                  />
                  <Tooltip formatter={value => number(Math.abs(Number(value)), 'kWh')} />
                  <Legend />
                  <ReferenceLine y={0} stroke="#6b7280" />
                  <Bar
                    isAnimationActive={false}
                    dataKey="actual.solarHome"
                    name="Solar → Home"
                    stackId="actual"
                    fill="#f59e0b"
                    fillOpacity={1}
                  />
                  <Bar
                    isAnimationActive={false}
                    dataKey="actual.batteryHome"
                    name="Battery → Home"
                    stackId="actual"
                    fill="#10b981"
                    fillOpacity={1}
                  />
                  <Bar
                    isAnimationActive={false}
                    dataKey="actual.gridHome"
                    name="Grid → Home"
                    stackId="actual"
                    fill="#3b82f6"
                    fillOpacity={1}
                  />
                  <Bar
                    isAnimationActive={false}
                    dataKey="actual.solarExport"
                    name="Solar → Grid"
                    stackId="actual"
                    fill="#f97316"
                    fillOpacity={1}
                  />
                  <Bar
                    isAnimationActive={false}
                    dataKey="actual.batteryExport"
                    name="Battery → Grid"
                    stackId="actual"
                    fill="#8b5cf6"
                    fillOpacity={1}
                  />
                  <Bar
                    isAnimationActive={false}
                    dataKey="optimal.solarHome"
                    name="Solar → Home · hindsight"
                    stackId="optimal"
                    fill="#f59e0b"
                    fillOpacity={0.45}
                    legendType="none"
                  />
                  <Bar
                    isAnimationActive={false}
                    dataKey="optimal.batteryHome"
                    name="Battery → Home · hindsight"
                    stackId="optimal"
                    fill="#10b981"
                    fillOpacity={0.45}
                    legendType="none"
                  />
                  <Bar
                    isAnimationActive={false}
                    dataKey="optimal.gridHome"
                    name="Grid → Home · hindsight"
                    stackId="optimal"
                    fill="#3b82f6"
                    fillOpacity={0.45}
                    legendType="none"
                  />
                  <Bar
                    isAnimationActive={false}
                    dataKey="optimal.solarExport"
                    name="Solar → Grid · hindsight"
                    stackId="optimal"
                    fill="#f97316"
                    fillOpacity={0.45}
                    legendType="none"
                  />
                  <Bar
                    isAnimationActive={false}
                    dataKey="optimal.batteryExport"
                    name="Battery → Grid · hindsight"
                    stackId="optimal"
                    fill="#8b5cf6"
                    fillOpacity={0.45}
                    legendType="none"
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className={panel}>
              <h2 className="font-semibold text-lg">
                Battery charging ↑ / discharge ↓ · actual vs hindsight
              </h2>
              <p className="text-sm">
                Daily kWh. Charging is battery input energy, separate from household supply. Each
                day: left bar actual (solid), right bar hindsight (lighter).
              </p>
              <ResponsiveContainer width="100%" height={320}>
                <BarChart data={pairedFlows} stackOffset="sign" barGap={2}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" tickFormatter={dayLabel} />
                  <YAxis
                    unit=" kWh"
                    width={85}
                    domain={sharedDomain(batteryKeys)}
                    ticks={domainTicks(sharedDomain(batteryKeys))}
                  />
                  <Tooltip formatter={value => number(Math.abs(Number(value)), 'kWh')} />
                  <Legend />
                  <ReferenceLine y={0} stroke="#6b7280" />
                  <Bar
                    isAnimationActive={false}
                    dataKey="actual.discharge"
                    name="Battery discharge"
                    stackId="actual"
                    fill="#10b981"
                    fillOpacity={1}
                  />
                  <Bar
                    isAnimationActive={false}
                    dataKey="actual.solarCharge"
                    name="Solar → Battery"
                    stackId="actual"
                    fill="#f59e0b"
                    fillOpacity={1}
                  />
                  <Bar
                    isAnimationActive={false}
                    dataKey="actual.gridCharge"
                    name="Grid → Battery"
                    stackId="actual"
                    fill="#3b82f6"
                    fillOpacity={1}
                  />
                  <Bar
                    isAnimationActive={false}
                    dataKey="optimal.discharge"
                    name="Battery discharge · hindsight"
                    stackId="optimal"
                    fill="#10b981"
                    fillOpacity={0.45}
                    legendType="none"
                  />
                  <Bar
                    isAnimationActive={false}
                    dataKey="optimal.solarCharge"
                    name="Solar → Battery · hindsight"
                    stackId="optimal"
                    fill="#f59e0b"
                    fillOpacity={0.45}
                    legendType="none"
                  />
                  <Bar
                    isAnimationActive={false}
                    dataKey="optimal.gridCharge"
                    name="Grid → Battery · hindsight"
                    stackId="optimal"
                    fill="#3b82f6"
                    fillOpacity={0.45}
                    legendType="none"
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <ProofSection data={data} comparison={comparison} currency={currency} />
        </>
      )}
    </section>
  );
};

export default PerformanceView;
