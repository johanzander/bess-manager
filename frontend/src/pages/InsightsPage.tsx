// frontend/src/pages/InsightsPage.tsx

import React from 'react';
import ConsumptionForecastComparison from '../components/ConsumptionForecastComparison';
import PredictionAccuracyView from '../components/PredictionAccuracyView';
import { BatteryActionsTable } from '../components/BatteryActionsTable';
import { useUserPreferences } from '../hooks/useUserPreferences';

const InsightsPage: React.FC = () => {
  const { dataResolution } = useUserPreferences();

  return (
    <div className="p-6 space-y-6 bg-gray-50 dark:bg-gray-900 min-h-screen">
      <BatteryActionsTable resolution={dataResolution} />
      <PredictionAccuracyView />
      <ConsumptionForecastComparison />
    </div>
  );
};

export default InsightsPage;
