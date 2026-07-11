// frontend/src/pages/InsightsPage.tsx

import React, { useState } from 'react';
import ConsumptionForecastComparison from '../components/ConsumptionForecastComparison';
import PredictionAccuracyView from '../components/PredictionAccuracyView';
import { BatteryActionsTable } from '../components/BatteryActionsTable';
import { DetailedSavingsAnalysis } from '../components/DetailedSavingsAnalysis';
import DateSelector from '../components/DateSelector';
import { useUserPreferences } from '../hooks/useUserPreferences';
import { useAvailableDashboardDates } from '../hooks/useAvailableDashboardDates';
import { toISODate } from '../utils/timeUtils';

type InsightsTab = 'forecast-accuracy' | 'battery-actions' | 'scenario-comparison';

const TABS: { id: InsightsTab; label: string }[] = [
  { id: 'forecast-accuracy', label: 'Forecast Accuracy' },
  { id: 'battery-actions', label: 'Battery Actions' },
  { id: 'scenario-comparison', label: 'Scenario Comparison' },
];

const isToday = (date: Date): boolean => toISODate(date) === toISODate(new Date());

const InsightsPage: React.FC = () => {
  const { dataResolution } = useUserPreferences();
  const [activeTab, setActiveTab] = useState<InsightsTab>('forecast-accuracy');
  const [selectedDate, setSelectedDate] = useState<Date>(new Date());
  const availableDates = useAvailableDashboardDates();

  return (
    <div className="p-6 space-y-6 bg-gray-50 dark:bg-gray-900 min-h-screen">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div className="flex bg-gray-100 dark:bg-gray-700 rounded-lg p-1 w-fit">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                activeTab === tab.id
                  ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                  : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {activeTab === 'battery-actions' && (
          <DateSelector
            selectedDate={selectedDate}
            onDateChange={setSelectedDate}
            availableDates={availableDates}
          />
        )}
      </div>

      {activeTab === 'forecast-accuracy' && (
        <div className="space-y-6">
          <PredictionAccuracyView />
          <ConsumptionForecastComparison />
        </div>
      )}

      {activeTab === 'battery-actions' && (
        <BatteryActionsTable
          resolution={dataResolution}
          date={isToday(selectedDate) ? undefined : toISODate(selectedDate)}
        />
      )}

      {activeTab === 'scenario-comparison' && (
        <DetailedSavingsAnalysis resolution={dataResolution} />
      )}
    </div>
  );
};

export default InsightsPage;
