import React from 'react';
import SystemHealthComponent from '../components/SystemHealth';

const SystemHealthPage: React.FC = () => {
  return (
    <div className="p-6 space-y-6 bg-gray-50 dark:bg-gray-900 min-h-screen">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">System Health</h1>
        <p className="text-gray-600 dark:text-gray-300">
          Monitor the health and status of all BESS components and integrations
        </p>
      </div>
      
      <div className="mb-6">
        <SystemHealthComponent />
      </div>
      
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">About System Health</h2>
        <p className="mb-3 text-gray-700 dark:text-gray-300">
          The System Health page shows the status of all BESS components and integrations. Each component is checked to ensure it has proper access to the sensors and settings it needs to function correctly.
        </p>
        <div className="mb-3">
          <h3 className="font-semibold text-gray-800 dark:text-gray-200 mb-2">Status Indicators:</h3>
          <ul className="list-disc pl-5 space-y-1 text-gray-700 dark:text-gray-300">
            <li><span className="text-green-600 dark:text-green-400 font-medium">OK</span>: Component is fully functional with all required sensors.</li>
            <li><span className="text-amber-600 dark:text-amber-400 font-medium">WARNING</span>: Component has minor issues but can operate with limitations.</li>
            <li><span className="text-red-600 dark:text-red-400 font-medium">ERROR</span>: Component has critical issues and may not function correctly.</li>
          </ul>
        </div>
        <div>
          <h3 className="font-semibold text-gray-800 dark:text-gray-200 mb-2">Component Types:</h3>
          <ul className="list-disc pl-5 space-y-1 text-gray-700 dark:text-gray-300">
            <li><span className="font-medium">Required</span>: Essential for basic system operation.</li>
            <li><span className="font-medium">Optional</span>: Enhances functionality but not essential for basic operation.</li>
          </ul>
        </div>
        <div className="mt-4 p-4 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-md">
          <h3 className="font-semibold text-blue-800 dark:text-blue-200 mb-2">Navigation Help</h3>
          <p className="text-blue-700 dark:text-blue-300 mb-2">
            The Smart Charger app is organized into three main sections:
          </p>
          <ul className="list-disc pl-5 space-y-1 text-blue-700 dark:text-blue-300">
            <li><span className="font-medium">Dashboard:</span> Shows the current battery schedule, levels, and actions.</li>
            <li><span className="font-medium">Savings:</span> Provides detailed savings reports and analytics.</li>
            <li><span className="font-medium">System Health:</span> Displays the operational status of all components.</li>
          </ul>
        </div>
      </div>
    </div>
  );
};

export default SystemHealthPage;