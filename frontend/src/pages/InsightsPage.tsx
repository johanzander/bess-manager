// frontend/src/pages/InsightsPage.tsx

import React from 'react';
import PredictionAccuracyView from '../components/PredictionAccuracyView';

const InsightsPage: React.FC = () => {
  return (
    <div className="p-6 space-y-6 bg-gray-50 dark:bg-gray-900 min-h-screen">
      <PredictionAccuracyView />
    </div>
  );
};

export default InsightsPage;