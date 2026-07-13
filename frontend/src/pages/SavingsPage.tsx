import React, { useState, useEffect } from 'react';
import { SavingsAggregateView, SAVINGS_PERIOD_LABELS } from '../components/SavingsAggregateView';
import DateSelector from '../components/DateSelector';
import { useAvailableDashboardDates } from '../hooks/useAvailableDashboardDates';
import { SavingsAggregatePeriod } from '../api/scheduleApi';
import { toISODate } from '../utils/timeUtils';
import api from '../lib/api';

type SavingsResolution = Extract<SavingsAggregatePeriod, 'day' | 'month' | 'year'>;

const RESOLUTIONS: SavingsResolution[] = ['day', 'month', 'year'];

const SavingsPage: React.FC = () => {
  const [systemMode, setSystemMode] = useState<string>('normal');
  const [resolution, setResolution] = useState<SavingsResolution>('day');
  const [selectedDate, setSelectedDate] = useState<Date>(new Date());
  const availableDates = useAvailableDashboardDates();

  useEffect(() => {
    api.get('/api/settings')
      .then(({ data }) => {
        const dm = data.demoMode || data.demo_mode || {};
        setSystemMode(dm.enabled ? 'demo' : 'normal');
      })
      .catch(() => {});
  }, []);

  const isLive = toISODate(selectedDate) === toISODate(new Date());

  return (
    <div className="space-y-6">
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">Savings Report</h1>
            <p className="text-gray-600 dark:text-gray-300">
              What you actually paid for grid electricity, and how much solar and battery saved you against grid-only power, over time.
            </p>
            {systemMode === 'demo' && (
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                All savings are theoretical estimates based on optimization plans
              </p>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="flex bg-gray-100 dark:bg-gray-700 rounded-lg p-1 w-fit">
              {RESOLUTIONS.map((r) => (
                <button
                  key={r}
                  onClick={() => setResolution(r)}
                  className={`px-3 py-1 rounded-md text-sm font-medium capitalize transition-colors ${
                    resolution === r
                      ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                      : 'text-gray-600 dark:text-gray-300'
                  }`}
                >
                  {SAVINGS_PERIOD_LABELS[r]}
                </button>
              ))}
            </div>
            <DateSelector
              selectedDate={selectedDate}
              onDateChange={setSelectedDate}
              availableDates={availableDates}
              resolution={resolution}
            />
          </div>
        </div>
      </div>

      <SavingsAggregateView
        period={resolution}
        date={isLive ? undefined : toISODate(selectedDate)}
      />
    </div>
  );
};

export default SavingsPage;
