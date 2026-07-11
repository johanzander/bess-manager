import React, { useState, useEffect } from 'react';
import { SavingsAggregateView, SAVINGS_PERIODS, SAVINGS_PERIOD_LABELS } from '../components/SavingsAggregateView';
import { SavingsAggregatePeriod } from '../api/scheduleApi';
import api from '../lib/api';

const SavingsPage: React.FC = () => {
  const [systemMode, setSystemMode] = useState<string>('normal');
  const [period, setPeriod] = useState<SavingsAggregatePeriod>('day');

  useEffect(() => {
    api.get('/api/settings')
      .then(({ data }) => {
        const dm = data.demoMode || data.demo_mode || {};
        setSystemMode(dm.enabled ? 'demo' : 'normal');
      })
      .catch(() => {});
  }, []);

  return (
    <div className="space-y-6">
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">Savings Report</h1>
            <p className="text-gray-600 dark:text-gray-300">
              What you actually paid the grid, and how much solar and battery saved you against grid-only power, over time.
            </p>
            {systemMode === 'demo' && (
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                All savings are theoretical estimates based on optimization plans
              </p>
            )}
          </div>

          <div className="flex bg-gray-100 dark:bg-gray-700 rounded-lg p-1 w-fit">
            {SAVINGS_PERIODS.map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`px-3 py-1 rounded-md text-sm font-medium capitalize transition-colors ${
                  period === p
                    ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                    : 'text-gray-600 dark:text-gray-300'
                }`}
              >
                {SAVINGS_PERIOD_LABELS[p]}
              </button>
            ))}
          </div>
        </div>
      </div>

      <SavingsAggregateView period={period} />
    </div>
  );
};

export default SavingsPage;
