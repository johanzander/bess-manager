import React, { useState, useEffect } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { DollarSign, TrendingUp, Sun, Battery } from 'lucide-react';
import { useSavingsAggregate } from '../hooks/useSavingsAggregate';
import { StatusCard } from './SystemStatusCard';
import { SavingsAggregatePeriod, SavingsBucket } from '../api/scheduleApi';
import { toISODate } from '../utils/timeUtils';

export const SAVINGS_PERIODS: SavingsAggregatePeriod[] = ['day', 'week', 'month', 'year'];

export const SAVINGS_PERIOD_LABELS: Record<SavingsAggregatePeriod, string> = {
  day: 'Day',
  week: 'Week',
  month: 'Month',
  year: 'Year',
};

interface SavingsAggregateViewProps {
  period: SavingsAggregatePeriod;
  date?: string;
}

// Bucket-derived label so titles stay correct when browsing a historical
// date, not just "now" — e.g. "May 2026" instead of always "Month".
const formatPeriodLabel = (period: SavingsAggregatePeriod, bucket: SavingsBucket): string => {
  const start = new Date(`${bucket.startDate}T00:00:00`);
  if (period === 'day') {
    return bucket.startDate === toISODate(new Date())
      ? 'Today'
      : start.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }
  if (period === 'month') {
    return start.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
  }
  if (period === 'year') {
    return bucket.label;
  }
  return SAVINGS_PERIOD_LABELS[period];
};

const SavingsHero: React.FC<{ bucket: SavingsBucket; period: SavingsAggregatePeriod }> = ({
  bucket,
  period,
}) => {
  const percentSaved =
    bucket.gridOnlyCost.value > 0.001
      ? (bucket.netSavings.value / bucket.gridOnlyCost.value) * 100
      : null;

  const periodLabel = formatPeriodLabel(period, bucket);
  const costTitle = periodLabel === 'Today' ? "Today's Cost" : `${periodLabel} Cost`;
  const savingsTitle = periodLabel === 'Today' ? "Today's Savings" : `${periodLabel} Savings`;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <StatusCard
        title={costTitle}
        icon={DollarSign}
        color="blue"
        keyMetric="Net Cost"
        keyValue={bucket.gridCost.text}
        keyUnit=""
        metrics={[
          { label: 'Import Costs', value: bucket.importEur.text, unit: '', icon: DollarSign },
          { label: 'Export Revenues', value: bucket.exportEur.text, unit: '', icon: DollarSign },
        ]}
      />
      <StatusCard
        title={savingsTitle}
        icon={TrendingUp}
        color="green"
        keyMetric="Net Savings"
        keyValue={bucket.netSavings.text}
        keyUnit=""
        headerRight={
          percentSaved !== null && (
            <span
              className={`text-sm font-semibold px-2 py-0.5 rounded-md ${
                percentSaved >= 0
                  ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                  : 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
              }`}
            >
              {percentSaved.toFixed(0)}% saved
            </span>
          )
        }
        metrics={[
          { label: 'Grid Only', value: bucket.gridOnlyCost.text, unit: '', icon: DollarSign },
          {
            label: 'Solar Contribution',
            value: bucket.solarSavings.text,
            unit: '',
            icon: Sun,
          },
          {
            label: 'Battery Contribution',
            value: bucket.batterySavings.text,
            unit: '',
            icon: Battery,
          },
        ]}
      />
    </div>
  );
};

// "Today" still means daily granularity, not just today: request a rolling
// window of recent days (like Week/Month/Year already do) so yesterday and
// earlier are visible without waiting for them to roll into a week total.
const DAY_VIEW_COUNT = 14;

export const SavingsAggregateView: React.FC<SavingsAggregateViewProps> = ({ period, date }) => {
  const [viewMode, setViewMode] = useState<'chart' | 'table'>('chart');
  const { data, loading, error } = useSavingsAggregate(
    period,
    period === 'day' ? DAY_VIEW_COUNT : undefined,
    date
  );
  const [isDarkMode, setIsDarkMode] = useState(document.documentElement.classList.contains('dark'));

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDarkMode(document.documentElement.classList.contains('dark'));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  const colors = {
    text: isDarkMode ? '#9CA3AF' : '#374151',
    gridLines: isDarkMode ? '#374151' : '#e5e7eb',
    savings: '#10b981',
    cost: '#3b82f6',
  };

  // The hero cards always show the bucket anchored to the selected period —
  // the last item in the response — even when it has no data yet, so an
  // empty month/year renders as a zeroed-out card instead of vanishing (and
  // a partial period still shows whatever's accumulated so far).
  const currentBucket = data && data.length > 0 ? data[data.length - 1] : undefined;

  // The History chart/table below is a trend over time, so periods with no
  // recorded day are still excluded there — a "0.00" row for a day with no
  // snapshot yet is just noise in a trend view.
  const bucketsWithData = data ? data.filter(b => b.dayCount > 0) : [];
  const hasData = bucketsWithData.length > 0;
  const currencyUnit = bucketsWithData[0]?.gridOnlyCost.unit ?? currentBucket?.gridOnlyCost.unit ?? '';

  const formatAxisValue = (value: number): string =>
    value.toLocaleString(undefined, { maximumFractionDigits: 0 });

  const formatTooltipValue = (value: number): string =>
    `${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currencyUnit}`;

  return (
    <div className="space-y-6">
      {!loading && !error && currentBucket && (
        <SavingsHero bucket={currentBucket} period={period} />
      )}

      <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700 p-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-4 gap-3">
          <h3 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
            History
          </h3>
          <div className="flex gap-2">
            <div className="flex bg-gray-100 dark:bg-gray-700 rounded-lg p-1">
              <button
                onClick={() => setViewMode('chart')}
                className={`px-3 py-1 rounded-md text-sm font-medium transition-colors ${
                  viewMode === 'chart'
                    ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                    : 'text-gray-600 dark:text-gray-300'
                }`}
              >
                Chart
              </button>
              <button
                onClick={() => setViewMode('table')}
                className={`px-3 py-1 rounded-md text-sm font-medium transition-colors ${
                  viewMode === 'table'
                    ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                    : 'text-gray-600 dark:text-gray-300'
                }`}
              >
                Table
              </button>
            </div>
          </div>
        </div>

        {loading && <p className="text-sm text-gray-500 dark:text-gray-400">Loading...</p>}

        {!loading && error && (
          <p className="text-sm text-red-600 dark:text-red-400">
            Could not load savings history: {error}
          </p>
        )}

        {!loading && !error && !hasData && (
          <p className="text-sm text-gray-500 dark:text-gray-400">
            No savings history yet. A record is captured once per day.
          </p>
        )}

        {!loading && !error && hasData && viewMode === 'chart' && (
          <div style={{ width: '100%', height: '300px' }}>
            <ResponsiveContainer>
              <BarChart
                data={bucketsWithData.map(b => ({
                  label: b.label,
                  gridOnlyCost: b.gridOnlyCost.value,
                  gridCost: b.gridCost.value,
                  savings: b.netSavings.value,
                }))}
                margin={{ top: 10, right: 10, left: 0, bottom: 10 }}
              >
                <CartesianGrid
                  stroke={colors.gridLines}
                  strokeOpacity={isDarkMode ? 0.12 : 0.3}
                  strokeWidth={0.5}
                />
                <XAxis
                  dataKey="label"
                  stroke={colors.text}
                  tick={{ fill: colors.text, fontSize: 11 }}
                />
                <YAxis
                  stroke={colors.text}
                  tick={{ fill: colors.text, fontSize: 11 }}
                  tickFormatter={formatAxisValue}
                  width={70}
                  label={{
                    value: currencyUnit,
                    angle: -90,
                    position: 'insideLeft',
                    style: { textAnchor: 'middle', fill: colors.text },
                    fontSize: 12,
                  }}
                />
                <Tooltip
                  formatter={formatTooltipValue}
                  contentStyle={{
                    backgroundColor: isDarkMode ? '#1f2937' : '#ffffff',
                    borderColor: colors.gridLines,
                    borderRadius: 8,
                    fontSize: 13,
                  }}
                  labelStyle={{ color: colors.text, fontWeight: 600 }}
                />
                <Legend wrapperStyle={{ fontSize: 12, color: colors.text }} />
                <Bar
                  dataKey="gridOnlyCost"
                  name="Grid-Only Cost"
                  fill={colors.text}
                  fillOpacity={0.35}
                  isAnimationActive={false}
                  radius={[4, 4, 0, 0]}
                />
                <Bar
                  dataKey="gridCost"
                  name="Net Grid Cost"
                  fill={colors.cost}
                  fillOpacity={0.8}
                  isAnimationActive={false}
                  radius={[4, 4, 0, 0]}
                />
                <Bar
                  dataKey="savings"
                  name="Net Savings"
                  fill={colors.savings}
                  fillOpacity={0.8}
                  isAnimationActive={false}
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        {!loading && !error && hasData && viewMode === 'table' && (
          <div className="overflow-x-auto">
            <table className="min-w-full text-base">
              <thead>
                <tr className="text-sm uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  <th className="pr-4 py-1"></th>
                  <th
                    colSpan={3}
                    className="px-3 py-1 text-center font-semibold bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 border border-gray-300 dark:border-gray-600"
                  >
                    Grid cost (what you actually paid)
                  </th>
                  <th
                    colSpan={4}
                    className="px-3 py-1 text-center font-semibold bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300 border border-gray-300 dark:border-gray-600"
                  >
                    Savings breakdown
                  </th>
                </tr>
                <tr className="text-left text-sm uppercase tracking-wide text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
                  <th className="pr-4 py-2 font-medium">Period</th>
                  <th className="px-3 py-2 font-medium text-right border-x border-gray-200 dark:border-gray-700">
                    Import Cost
                  </th>
                  <th className="px-3 py-2 font-medium text-right border-r border-gray-200 dark:border-gray-700">
                    Export Revenue
                  </th>
                  <th className="px-3 py-2 font-medium text-right border-r border-gray-200 dark:border-gray-700">
                    = Net Grid Cost
                  </th>
                  <th className="px-3 py-2 font-medium text-right border-r border-gray-200 dark:border-gray-700">
                    Grid-Only Cost
                  </th>
                  <th className="px-3 py-2 font-medium text-right border-r border-gray-200 dark:border-gray-700">
                    From Solar
                  </th>
                  <th className="px-3 py-2 font-medium text-right border-r border-gray-200 dark:border-gray-700">
                    From Battery
                  </th>
                  <th className="px-3 py-2 font-medium text-right">= Net Savings</th>
                </tr>
              </thead>
              <tbody>
                {[...bucketsWithData].reverse().map(b => (
                  <tr key={b.label} className="border-t border-gray-100 dark:border-gray-700">
                    <td className="pr-4 py-2 text-gray-900 dark:text-white">{b.label}</td>
                    <td className="px-3 py-2 text-right text-gray-600 dark:text-gray-300 border-x border-gray-100 dark:border-gray-700">
                      {b.importEur.text}
                    </td>
                    <td className="px-3 py-2 text-right text-gray-600 dark:text-gray-300 border-r border-gray-100 dark:border-gray-700">
                      {b.exportEur.text}
                    </td>
                    <td className="px-3 py-2 text-right font-medium text-gray-900 dark:text-white border-r border-gray-100 dark:border-gray-700">
                      {b.gridCost.text}
                    </td>
                    <td className="px-3 py-2 text-right text-gray-500 dark:text-gray-400 border-r border-gray-100 dark:border-gray-700">
                      {b.gridOnlyCost.text}
                    </td>
                    <td className="px-3 py-2 text-right text-gray-600 dark:text-gray-300 border-r border-gray-100 dark:border-gray-700">
                      {b.solarSavings.text}
                    </td>
                    <td className="px-3 py-2 text-right text-gray-600 dark:text-gray-300 border-r border-gray-100 dark:border-gray-700">
                      {b.batterySavings.text}
                    </td>
                    <td className="px-3 py-2 text-right text-emerald-600 dark:text-emerald-400 font-medium">
                      {b.netSavings.text}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};

export default SavingsAggregateView;
