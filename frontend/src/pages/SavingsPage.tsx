import React, { useState } from 'react';
import { DetailedSavingsAnalysis } from '../components/DetailedSavingsAnalysis';
import { SavingsOverview } from '../components/SavingsOverview';
import { useSettings } from '../hooks/useSettings';
import { Eye, Table2 } from 'lucide-react';

const SavingsPage: React.FC = () => {
  const { batterySettings } = useSettings();
  const [viewMode, setViewMode] = useState<'simple' | 'detailed'>('simple');

  // Create merged settings with defaults for the table
  const mergedSettings = {
    totalCapacity: batterySettings?.totalCapacity || 10,
    reservedCapacity: batterySettings?.reservedCapacity || 2,
    estimatedConsumption: batterySettings?.estimatedConsumption || 1.5,
    maxChargeDischarge: batterySettings?.maxChargeDischarge || 6,
    chargeCycleCost: batterySettings?.chargeCycleCost || 10,
    chargingPowerRate: batterySettings?.chargingPowerRate || 90,
    useActualPrice: true,
    markupRate: 0.05,
    vatMultiplier: 1.25,
    additionalCosts: 0.45,
    taxReduction: 0.1,
    area: 'SE3' as const
  };

  return (
    <div className="space-y-6">
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between">
          <div className="mb-4 sm:mb-0">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">Financial Analysis & Savings Report</h1>
            <p className="text-gray-600 dark:text-gray-300">
              Detailed breakdown of energy costs across three scenarios: grid-only, solar-only, and optimized solar+battery.
            </p>
          </div>
          
          {/* View Mode Switcher */}
          <div className="flex bg-gray-100 dark:bg-gray-700 rounded-lg p-1">
            <button
              onClick={() => setViewMode('simple')}
              className={`flex items-center px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                viewMode === 'simple'
                  ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                  : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              <Eye className="h-4 w-4 mr-2" />
              Simple View
            </button>
            <button
              onClick={() => setViewMode('detailed')}
              className={`flex items-center px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                viewMode === 'detailed'
                  ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                  : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              <Table2 className="h-4 w-4 mr-2" />
              Detailed View
            </button>
          </div>
        </div>
        
        {/* View Mode Description */}
        <div className="mt-4 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
          <p className="text-sm text-blue-800 dark:text-blue-200">
            {viewMode === 'simple' ? (
              <>
                <strong>Simple View:</strong> Clean overview showing key energy flows, battery actions, and savings per hour. 
                Perfect for daily monitoring and quick insights.
              </>
            ) : (
              <>
                <strong>Detailed View:</strong> Complete breakdown comparing grid-only, solar-only, and solar+battery scenarios. 
                Shows all economic calculations and energy allocations for in-depth analysis.
              </>
            )}
          </p>
        </div>
      </div>

      {/* Render the appropriate table based on view mode */}
      {viewMode === 'simple' ? (
        <SavingsOverview settings={mergedSettings} />
      ) : (
        <DetailedSavingsAnalysis settings={mergedSettings} />
      )}
    </div>
  );
};

export default SavingsPage;