import React, { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { useSavingsAggregate } from '../hooks/useSavingsAggregate';
import { SavingsAggregatePeriod } from '../api/scheduleApi';

const PERIODS: SavingsAggregatePeriod[] = ['day', 'week', 'month', 'year'];

const PERIOD_LABELS: Record<SavingsAggregatePeriod, string> = {
  day: 'Today',
  week: 'Week',
  month: 'Month',
  year: 'Year',
};

export const SavingsAggregateView: React.FC = () => {
  const [period, setPeriod] = useState<SavingsAggregatePeriod>('week');
  const [viewMode, setViewMode] = useState<'chart' | 'table'>('chart');
  const { data, loading, error } = useSavingsAggregate(period);
  const [isDarkMode, setIsDarkMode] = useState(
    document.documentElement.classList.contains('dark')
  );

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

  const hasData = !!data && data.some((b) => b.dayCount > 0);

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700 p-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-4 gap-3">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Savings</h2>
        <div className="flex gap-2">
          <div className="flex bg-gray-100 dark:bg-gray-700 rounded-lg p-1">
            {PERIODS.map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`px-3 py-1 rounded-md text-sm font-medium capitalize transition-colors ${
                  period === p
                    ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                    : 'text-gray-600 dark:text-gray-300'
                }`}
              >
                {PERIOD_LABELS[p]}
              </button>
            ))}
          </div>
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
        <p className="text-sm text-red-600 dark:text-red-400">Could not load savings history: {error}</p>
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
              data={data!.map((b) => ({
                label: b.label,
                gridOnlyCost: b.gridOnlyCost.value,
                gridCost: b.gridCost.value,
                savings: b.savingsVsGridOnly.value,
              }))}
              margin={{ top: 10, right: 10, left: 0, bottom: 10 }}
            >
              <CartesianGrid stroke={colors.gridLines} strokeOpacity={isDarkMode ? 0.12 : 0.3} strokeWidth={0.5} />
              <XAxis dataKey="label" stroke={colors.text} tick={{ fill: colors.text, fontSize: 11 }} />
              <YAxis stroke={colors.text} tick={{ fill: colors.text, fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="gridOnlyCost" name="Grid-Only Cost" fill={colors.text} fillOpacity={0.35} isAnimationActive={false} />
              <Bar dataKey="gridCost" name="Net Grid Cost" fill={colors.cost} fillOpacity={0.8} isAnimationActive={false} />
              <Bar dataKey="savings" name="Savings" fill={colors.savings} fillOpacity={0.8} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {!loading && !error && hasData && viewMode === 'table' && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 dark:text-gray-400">
                <th className="pr-4 py-1">Period</th>
                <th className="pr-4 py-1">Days</th>
                <th className="pr-4 py-1">Import</th>
                <th className="pr-4 py-1">Export</th>
                <th className="pr-4 py-1">Grid-Only Cost</th>
                <th className="pr-4 py-1">Net Grid Cost</th>
                <th className="pr-4 py-1">Savings</th>
              </tr>
            </thead>
            <tbody>
              {[...data!].reverse().map((b) => (
                <tr key={b.label} className="border-t border-gray-100 dark:border-gray-700">
                  <td className="pr-4 py-1 text-gray-900 dark:text-white">{b.label}</td>
                  <td className="pr-4 py-1 text-gray-500 dark:text-gray-400">{b.dayCount}</td>
                  <td className="pr-4 py-1 text-gray-600 dark:text-gray-300">{b.importEur.text}</td>
                  <td className="pr-4 py-1 text-gray-600 dark:text-gray-300">{b.exportEur.text}</td>
                  <td className="pr-4 py-1 text-gray-500 dark:text-gray-400">{b.gridOnlyCost.text}</td>
                  <td className="pr-4 py-1 font-medium text-gray-900 dark:text-white">{b.gridCost.text}</td>
                  <td className="pr-4 py-1 text-gray-600 dark:text-gray-300">{b.savingsVsGridOnly.text}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default SavingsAggregateView;
