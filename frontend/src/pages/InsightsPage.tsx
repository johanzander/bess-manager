// frontend/src/pages/InsightsPage.tsx

import React from 'react';
import ConsumptionForecastComparison from '../components/ConsumptionForecastComparison';
import PredictionAccuracyView from '../components/PredictionAccuracyView';

const InsightsPage: React.FC = () => {
  return (
    <div className="p-6 space-y-6 bg-gray-50 dark:bg-gray-900 min-h-screen">
      <PredictionAccuracyView />
      <ConsumptionForecastComparison />
    </div>
  );
};

export default InsightsPage;