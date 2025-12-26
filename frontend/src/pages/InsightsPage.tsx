// frontend/src/pages/InsightsPage.tsx

import React from 'react';
import PredictionAnalysisView from '../components/PredictionAnalysisView';
import { TrendingUp } from 'lucide-react';

const InsightsPage: React.FC = () => {
  return (
    <div className="p-6 space-y-6 bg-gray-50 dark:bg-gray-900 min-h-screen">
      {/* Page Header */}
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white flex items-center">
          <TrendingUp className="h-8 w-8 mr-3 text-purple-600 dark:text-purple-400" />
          Prediction Analysis
        </h1>
        <p className="text-gray-600 dark:text-gray-300 mt-2">
          Track how predictions evolve throughout the day and compare them against actual outcomes
        </p>
      </div>

      {/* Prediction Analysis View */}
      <PredictionAnalysisView />
    </div>
  );
};

export default InsightsPage;