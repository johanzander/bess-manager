import React, { useState } from 'react';
import { DetailedSavingsAnalysis } from '../components/DetailedSavingsAnalysis';
import { SavingsOverview } from '../components/SavingsOverview';
import { useSettings } from '../hooks/useSettings';
import { useUserPreferences } from '../hooks/useUserPreferences';
import { Eye, Table2 } from 'lucide-react';

const SavingsPage: React.FC = () => {
  const { batterySettings } = useSettings();
  const { dataResolution, setDataResolution } = useUserPreferences();
  const [viewMode, setViewMode] = useState<'simple' | 'detailed'>('simple');

  // Create merged settings with defaults for the table
  const mergedSettings = {
    totalCapacity: batterySettings?.totalCapacity || 10,
    reservedCapacity: batterySettings?.reservedCapacity || 2,
    estimatedConsumption: batterySettings?.estimatedConsumption || 1.5,
    maxChargePowerKw: batterySettings?.maxChargePowerKw || 6,      
    maxDischargePowerKw: batterySettings?.maxDischargePowerKw || 6, 
    cycleCostPerKwh: batterySettings?.cycleCostPerKwh || 10,       
    chargingPowerRate: batterySettings?.chargingPowerRate || 90,
    minSoc: batterySettings?.minSoc || 20,                        
    maxSoc: batterySettings?.maxSoc || 95,                        
    efficiencyCharge: batterySettings?.efficiencyCharge || 95,    
    efficiencyDischarge: batterySettings?.efficiencyDischarge || 95, 
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
              Compare how your battery system optimizes energy costs and increases solar utilization.
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
              Standard View
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

        {/* Resolution Selector */}
        <div className="mt-4 flex items-center justify-end">
          <div className="flex bg-gray-100 dark:bg-gray-700 rounded-lg p-1">
            <button
              onClick={() => setDataResolution('hourly')}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                dataResolution === 'hourly'
                  ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                  : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              60 min
            </button>
            <button
              onClick={() => setDataResolution('quarter-hourly')}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                dataResolution === 'quarter-hourly'
                  ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                  : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              15 min
            </button>
          </div>
        </div>
      </div>

      {/* Render the appropriate table based on view mode */}
      {viewMode === 'simple' ? (
        <SavingsOverview resolution={dataResolution} />
      ) : (
        <DetailedSavingsAnalysis settings={mergedSettings} resolution={dataResolution} />
      )}
    </div>
  );
};

export default SavingsPage;