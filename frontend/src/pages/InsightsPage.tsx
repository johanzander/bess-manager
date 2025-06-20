// frontend/src/pages/InsightsPage.tsx

import React from 'react';
import DecisionFramework from '../components/DecisionFramework';
import { Brain, Info } from 'lucide-react';

const InsightsPage: React.FC = () => {
  return (
    <div className="p-6 space-y-6 bg-gray-50 dark:bg-gray-900 min-h-screen">
      {/* Page Header */}
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white flex items-center">
          <Brain className="h-8 w-8 mr-3 text-purple-600 dark:text-purple-400" />
          Insights & Decision Intelligence
        </h1>
        <p className="text-gray-600 dark:text-gray-300 mt-2">
          Deep insights into your battery system's decision-making process and optimization strategies
        </p>
      </div>

      {/* Decision Framework Component */}
      <DecisionFramework />

      {/* Educational Information */}
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow border">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4 flex items-center">
          <Info className="h-5 w-5 mr-2" />
          About Decision Intelligence
        </h2>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 text-sm text-gray-700 dark:text-gray-300">
          <div>
            <h3 className="font-medium mb-2 text-gray-900 dark:text-white">How It Works</h3>
            <p className="mb-3">
              The Decision Intelligence framework analyzes every battery decision using sophisticated 
              Dynamic Programming optimization. Each action is evaluated based on current conditions, 
              future price forecasts, and multi-hour arbitrage opportunities.
            </p>
            
            <h3 className="font-medium mb-2 text-gray-900 dark:text-white">Energy Flow Analysis</h3>
            <p>
              The system tracks all energy movements between solar panels, grid, home consumption, 
              and battery storage, calculating the economic value of each flow to maximize savings.
            </p>
          </div>
          
          <div>
            <h3 className="font-medium mb-2 text-gray-900 dark:text-white">Economic Strategies</h3>
            <p className="mb-3">
              Economic chains show how current decisions enable future opportunities. For example, 
              charging at cheap night rates to discharge during expensive peak hours, creating 
              profitable arbitrage strategies.
            </p>
            
            <h3 className="font-medium mb-2 text-gray-900 dark:text-white">Future Opportunities</h3>
            <p>
              Each decision includes forward-looking analysis showing what future opportunities 
              it enables, with expected values and dependency analysis to build trust in the 
              system's sophisticated optimization logic.
            </p>
          </div>
        </div>

        <div className="mt-6 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-700">
          <h3 className="font-medium text-blue-900 dark:text-blue-100 mb-2">Understanding the Columns</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm text-blue-800 dark:text-blue-200">
            <div>
              <p><strong>Battery Actions:</strong> What the algorithm controls - charge, discharge, or idle</p>
              <p><strong>Rationale:</strong> Why this decision makes economic sense</p>
            </div>
            <div>
              <p><strong>Energy Flows:</strong> Resulting movements between solar, grid, home, and battery</p>
              <p><strong>Strategy Value:</strong> Economic outcome with immediate and future value breakdown</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default InsightsPage;