import React from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertCircle, Zap } from 'lucide-react';
import SystemHealthComponent from '../components/SystemHealth';
import { useReportProblem } from '../components/ReportProblemContext';

const SystemHealthPage: React.FC = () => {
  const navigate = useNavigate();
  const { openReportProblem } = useReportProblem();

  return (
    <div className="p-6 space-y-6 bg-gray-50 dark:bg-gray-900 min-h-screen">
      <div className="mb-6 flex justify-between items-start">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">System Health</h1>
          <p className="text-gray-600 dark:text-gray-300">
            Monitor all system components to ensure they have proper access to required sensors and can operate correctly.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => navigate('/setup')}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-green-600 hover:bg-green-700 text-white font-medium transition-colors"
            title="Run auto-configuration to detect sensors and integrations"
          >
            <Zap className="w-4 h-4" />
            Auto-Configure
          </button>

          <button
            onClick={() => openReportProblem()}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-medium transition-colors"
            title="Report a problem — generates a debug bundle and opens a GitHub issue"
          >
            <AlertCircle className="w-4 h-4" />
            Report a Problem
          </button>
        </div>
      </div>
      
      <div className="mb-6">
        <SystemHealthComponent />
      </div>
      
      <div className="mt-8 bg-gray-100 dark:bg-gray-800/50 p-4 rounded-lg border border-gray-200 dark:border-gray-700">
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">Status Indicators</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
          <div>
            <ul className="space-y-1 text-gray-600 dark:text-gray-400">
              <li><span className="text-green-600 dark:text-green-400 font-medium">OK</span>: Component is fully functional with all required sensors.</li>
              <li><span className="text-amber-600 dark:text-amber-400 font-medium">WARNING</span>: Component has minor issues but can operate with limitations.</li>
              <li><span className="text-red-600 dark:text-red-400 font-medium">ERROR</span>: Component has critical issues and may not function correctly.</li>
            </ul>
          </div>
          <div>
            <ul className="space-y-1 text-gray-600 dark:text-gray-400">
              <li><span className="font-medium">Required</span>: Essential for basic system operation.</li>
              <li><span className="font-medium">Optional</span>: Enhances functionality but not essential for basic operation.</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SystemHealthPage;