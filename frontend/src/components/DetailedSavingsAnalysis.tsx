import React from 'react';
import FormattedValueComponent from './FormattedValue';
import { useDashboardData } from '../hooks/useDashboardData';
import { periodToTimeString, periodToEndTime } from '../utils/timeUtils';
import { DataResolution } from '../hooks/useUserPreferences';

interface DetailedSavingsAnalysisProps {
  settings: any;
  resolution: DataResolution;
}


export const DetailedSavingsAnalysis: React.FC<DetailedSavingsAnalysisProps> = ({ resolution }) => {
  const { data: dashboardData, loading, error } = useDashboardData(undefined, resolution);

  if (loading) {
    return (
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
        <div className="flex items-center justify-center h-32">
          <div className="animate-spin h-8 w-8 border-2 border-blue-500 rounded-full border-t-transparent"></div>
          <span className="ml-2 text-gray-900 dark:text-white">Loading detailed analysis...</span>
        </div>
      </div>
    );
  }

  if (error || !dashboardData) {
    return (
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
        <div className="text-center text-red-600 dark:text-red-400">
          Error loading analysis data: {error}
        </div>
      </div>
    );
  }

  // Helper function to safely display backend-formatted strings only
  const displayValue = (value: string | null | undefined, fallback = "N/A"): string => {
    if (value === null || value === undefined || value === "") {
      return fallback;
    }
    return value;
  };

  // Use backend-calculated total optimization savings from summary instead of calculating in frontend
  const totalDailySavings = typeof dashboardData?.summary?.totalSavings === 'object'
    ? dashboardData.summary.totalSavings.value || 0
    : dashboardData?.summary?.totalSavings || 0;

  return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow overflow-x-auto">
      <div className="mb-6">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">Scenario Comparison Analysis</h2>
        <p className="text-sm text-gray-600 dark:text-gray-300 mb-4">
          This analysis compares three scenarios: Grid-only, Solar-only and Solar+Battery.
          It helps quantify how much of your savings comes from solar panels versus how much additional value the battery system provides.
        </p>
        
        {/* Summary Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          {/* Grid-Only Card */}
          <div className="bg-blue-50 dark:bg-blue-900/20 p-4 rounded-lg shadow border border-blue-200 dark:border-blue-800">
            <div className="flex items-center justify-center mb-1">
              <div className="px-2 py-1 bg-blue-200 dark:bg-blue-800 text-blue-800 dark:text-blue-200 rounded text-xs font-medium">GRID-ONLY</div>
            </div>
            <FormattedValueComponent
              data={dashboardData.summary?.gridOnlyCost}
              size="lg"
              align="center"
              color="default"
              className="block"
            />
            <div className="text-sm text-gray-600 dark:text-gray-300">Baseline Cost</div>
            <div className="text-xs text-gray-500 dark:text-gray-400 mt-3">
              All electricity purchased from grid at market price
            </div>
          </div>
          
          {/* Solar-Only Card */}
          <div className="bg-yellow-50 dark:bg-yellow-900/20 p-4 rounded-lg shadow border border-yellow-200 dark:border-yellow-800">
            <div className="flex items-center justify-center mb-1">
              <div className="px-2 py-1 bg-yellow-200 dark:bg-yellow-800 text-yellow-800 dark:text-yellow-200 rounded text-xs font-medium">SOLAR-ONLY</div>
            </div>
            <FormattedValueComponent
              data={dashboardData.summary?.solarOnlyCost}
              size="lg"
              align="center"
              color="warning"
              className="block"
            />
            <div className="text-sm text-gray-600 dark:text-gray-300">Solar-Only Cost</div>
            <div className="flex justify-between items-center mt-2 border-t border-yellow-200 dark:border-yellow-800 pt-2">
              <div className="text-left text-xs text-gray-600 dark:text-gray-300">Solar savings:</div>
              <FormattedValueComponent
                data={dashboardData.summary?.solarSavings}
                size="sm"
                align="right"
                color="success"
                className="text-green-600 dark:text-green-400"
              />
            </div>
            <div className="flex justify-between items-center">
              <div className="text-left text-xs text-gray-600 dark:text-gray-300">% Saved:</div>
              <div className="text-right text-xs font-medium text-gray-700 dark:text-gray-200">{dashboardData.summary?.solarSavingsPercentage?.text}</div>
            </div>
            <div className="flex justify-between items-center">
              <div className="text-left text-xs text-gray-600 dark:text-gray-300">Self-consumption:</div>
              <div className="text-right text-xs font-medium text-gray-700 dark:text-gray-200">{dashboardData.summary?.selfConsumptionPercentage?.text}</div>
            </div>
          </div>
          
          {/* Solar+Battery Card */}
          <div className="bg-green-50 dark:bg-green-900/20 p-4 rounded-lg shadow border border-green-200 dark:border-green-800">
            <div className="flex items-center justify-center mb-1">
              <div className="px-2 py-1 bg-green-200 dark:bg-green-800 text-green-800 dark:text-green-200 rounded text-xs font-medium">SOLAR+BATTERY</div>
            </div>
            <FormattedValueComponent
              data={dashboardData.summary?.optimizedCost}
              size="lg"
              align="center"
              color="success"
              className="block"
            />
            <div className="text-sm text-gray-600 dark:text-gray-300">Optimized Cost</div>
            <div className="flex justify-between items-center mt-2 border-t border-green-200 dark:border-green-800 pt-2">
              <div className="text-left text-xs text-gray-600 dark:text-gray-300">Total savings:</div>
              <FormattedValueComponent
                data={dashboardData.summary?.totalSavings}
                size="sm"
                align="right"
                color="success"
                className="text-green-600 dark:text-green-400"
              />
            </div>
            <div className="flex justify-between items-center">
              <div className="text-left text-xs text-gray-600 dark:text-gray-300">% Saved:</div>
              <FormattedValueComponent
                data={dashboardData.summary?.totalSavingsPercentage}
                size="sm"
                align="right"
                color="default"
              />
            </div>
            <div className="flex justify-between items-center">
              <div className="text-left text-xs text-gray-600 dark:text-gray-300">Battery contribution:</div>
              <FormattedValueComponent
                data={dashboardData.summary?.batterySavings}
                size="sm"
                align="right"
                color="success"
                className="text-green-600 dark:text-green-400"
              />
            </div>
          </div>
        </div>
      </div>

      <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
        <thead className="bg-gray-50 dark:bg-gray-700">
          <tr>
            <th rowSpan={2} className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600 w-16">
              Hour
            </th>
            {/* Common Data Column Group */}
            <th colSpan={2} className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600 bg-gray-100 dark:bg-gray-600">
              Common Data
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600 bg-blue-100 dark:bg-blue-900/30 w-20">
              Grid-Only Case
            </th>
            <th colSpan={6} className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30">
              Solar-Only Case
            </th>
            <th colSpan={6} className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30">
              Solar+Battery Case
            </th>
          </tr>
          <tr className="bg-gray-50 dark:bg-gray-700">
            {/* Common Data Headers */}
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600 bg-gray-100 dark:bg-gray-600 w-20">
              Price Buy/Sell
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600 bg-gray-100 dark:bg-gray-600 w-20">
              Cons.
            </th>
            
            {/* Grid-Only Headers */}
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600 bg-blue-100 dark:bg-blue-900/30 w-20">
              Cost
            </th>
            
            {/* Solar-Only Headers */}
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30">
              Solar
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30">
              Direct
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30">
              Import
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30">
              Export
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30">
              Cost
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30">
              Savings
            </th>
            
            {/* Solar+Battery Headers */}
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30">
              Action
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30">
              Battery Level
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30">
              Import
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30">
              Export
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30">
              Cost
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30">
              Savings
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
          {dashboardData.hourlyData.map((hour, index) => {
            const batteryAction = typeof hour.batteryAction === 'number' ? hour.batteryAction : 0;
            const batterySoc = hour.batterySocEnd;
            const isCurrentPeriod = hour.period === dashboardData.currentPeriod;
            const isActual = hour.dataSource === 'actual';

            // Row styling based on actual/predicted/current
            let rowClass = '';
            let firstCellClass = 'px-3 py-2 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-white border-t border-r border-b border-gray-300 dark:border-gray-600 text-center ';

            if (isCurrentPeriod) {
              rowClass = 'bg-purple-50 dark:bg-purple-900/20';
              firstCellClass += 'border-l-4 border-l-purple-400';
            } else if (isActual) {
              rowClass = 'bg-gray-50 dark:bg-gray-700';
              firstCellClass += 'border-l-4 border-l-green-400';
            } else {
              rowClass = 'bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700';
              firstCellClass += 'border-l border-l-gray-300 dark:border-l-gray-600';
            }

            return (
              <tr key={index} className={rowClass}>
                <td className={firstCellClass}>
                  <div className="text-center">
                    <div>{periodToTimeString(hour.period, resolution)}</div>
                    <div className="text-xs text-gray-400 dark:text-gray-500">{periodToEndTime(hour.period, resolution)}</div>
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400 text-center">
                    {(hour.dataSource || 'predicted').charAt(0).toUpperCase() + (hour.dataSource || 'predicted').slice(1)}
                  </div>
                </td>
                
                {/* Common Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-center">
                  <div>
                    {hour.buyPrice?.display || '0.00'} / {hour.sellPrice?.display || '0.00'}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">
                    {hour.buyPrice?.unit || '???'}
                  </div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-center">
                  <div className="font-medium">{hour.homeConsumption?.display || '0.0'}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">{hour.homeConsumption?.unit || 'kWh'}</div>
                </td>
                
                {/* Grid-Only Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-blue-50 dark:bg-blue-900/20 text-center">
                  <div className={`font-medium ${
                    Math.abs(hour.gridOnlyCost?.value || 0) < 0.01 ? 'text-gray-900 dark:text-white' :
                    (hour.gridOnlyCost?.value || 0) > 0 ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'
                  }`}>
                    {hour.gridOnlyCost?.display || '0.00'}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">{hour.gridOnlyCost?.unit || '???'}</div>
                </td>
                
                {/* Solar-Only Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-50 dark:bg-yellow-900/20 text-center">
                  <div className="font-medium text-yellow-600 dark:text-yellow-400">{hour.solarProduction?.display || '0.0'}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">{hour.solarProduction?.unit || 'kWh'}</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-50 dark:bg-yellow-900/20 text-center">
                  <div className="font-medium">{hour.directSolar?.display || '0.0'}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-50 dark:bg-yellow-900/20 text-center">
                  <div className={`font-medium ${
                    (hour.gridImportNeeded?.value || 0) > 0 ? 'text-red-600 dark:text-red-400' : 'text-gray-900 dark:text-white'
                  }`}>
                    {hour.gridImportNeeded?.display || '0.0'}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">{hour.gridImportNeeded?.unit || 'kWh'}</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-50 dark:bg-yellow-900/20 text-center">
                  <div className={`font-medium ${
                    (hour.solarExcess?.value || 0) > 0 ? 'text-green-600 dark:text-green-400' : 'text-gray-900 dark:text-white'
                  }`}>
                    {hour.solarExcess?.display || '0.0'}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">{hour.solarExcess?.unit || 'kWh'}</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-50 dark:bg-yellow-900/20 text-center">
                  <div className={`font-medium ${
                    Math.abs(hour.solarOnlyCost?.value || 0) < 0.01 ? 'text-gray-900 dark:text-white' :
                    (hour.solarOnlyCost?.value || 0) > 0 ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'
                  }`}>
                    {hour.solarOnlyCost?.display || '0.00'}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">{hour.solarOnlyCost?.unit || '???'}</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-50 dark:bg-yellow-900/20 text-center">
                  <div className={`font-medium ${
                    Math.abs(hour.solarSavings?.value || 0) < 0.01 ? 'text-gray-900 dark:text-white' :
                    (hour.solarSavings?.value || 0) > 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
                  }`}>
                    {hour.solarSavings?.display || '0.00'}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">{hour.solarSavings?.unit || '???'}</div>
                </td>
                
                {/* Solar+Battery Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-50 dark:bg-green-900/20 text-center">
                  {(hour.batteryCharged?.value || 0) > 0.01 && (
                    <div className="font-medium text-blue-600 dark:text-blue-400">
                      +{hour.batteryCharged?.display || '0.0'}
                    </div>
                  )}
                  {(hour.batteryDischarged?.value || 0) > 0.01 && (
                    <div className="font-medium text-orange-600 dark:text-orange-400">
                      -{hour.batteryDischarged?.display || '0.0'}
                    </div>
                  )}
                  {(hour.batteryCharged?.value || 0) <= 0.01 && (hour.batteryDischarged?.value || 0) <= 0.01 && (
                    <div className="font-medium text-gray-500 dark:text-gray-400">0.0</div>
                  )}
                  <div className="text-xs text-gray-500 dark:text-gray-400">{hour.batteryCharged?.unit || 'kWh'}</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-50 dark:bg-green-900/20 text-center">
                  <div className="font-medium">{Math.round(hour.batterySocEnd?.value || 0)} %</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">
                    {hour.batterySoeEnd?.display || '0.0'} {hour.batterySoeEnd?.unit || 'kWh'}
                  </div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-50 dark:bg-green-900/20 text-center">
                  <div className={`font-medium ${
                    (hour.gridImported?.value || 0) > 0 ? 'text-red-600 dark:text-red-400' : 'text-gray-900 dark:text-white'
                  }`}>
                    {hour.gridImported?.display || '0.0'}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">{hour.gridImported?.unit || 'kWh'}</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-50 dark:bg-green-900/20 text-center">
                  <div className={`font-medium ${
                    (hour.gridExported?.value || 0) > 0 ? 'text-green-600 dark:text-green-400' : 'text-gray-900 dark:text-white'
                  }`}>
                    {hour.gridExported?.display || '0.0'}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">{hour.gridExported?.unit || 'kWh'}</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-50 dark:bg-green-900/20 text-center">
                  <div className={`font-medium ${
                    Math.abs(hour.hourlyCost?.value || 0) < 0.01 ? 'text-gray-900 dark:text-white' :
                    (hour.hourlyCost?.value || 0) > 0 ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'
                  }`}>
                    {hour.hourlyCost?.display || '0.00'}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">{hour.hourlyCost?.unit || '???'}</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-50 dark:bg-green-900/20 text-center">
                  <div className={`font-medium ${
                    Math.abs(hour.hourlySavings?.value || 0) < 0.01 ? 'text-gray-900 dark:text-white' :
                    (hour.hourlySavings?.value || 0) > 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
                  }`}>
                    {hour.hourlySavings?.display || '0.00'}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">{hour.hourlySavings?.unit || '???'}</div>
                </td>
              </tr>
            );
          })}
          
          {/* Totals Row */}
          <tr className="bg-gray-100 dark:bg-gray-700 font-medium border-t-2 border-gray-300 dark:border-gray-600">
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-gray-100 dark:bg-gray-600 text-center">
              TOTAL
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-gray-100 dark:bg-gray-600 text-center">
              -
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-gray-100 dark:bg-gray-600 text-center">
              <div className="font-medium">{dashboardData.summary?.totalHomeConsumption?.display || '0.0'}</div>
              <div className="text-xs text-gray-500 dark:text-gray-400">{dashboardData.summary?.totalHomeConsumption?.unit || 'kWh'}</div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-blue-100 dark:bg-blue-900/30 text-center">
              <div className="font-medium text-red-600 dark:text-red-400">
                {dashboardData.summary?.gridOnlyCost?.display || '0.00'}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">{dashboardData.summary?.gridOnlyCost?.unit || '???'}</div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30 text-center">
              <div className="font-medium text-yellow-600 dark:text-yellow-400">
                {dashboardData.summary?.totalSolarProduction?.display || '0.0'}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">{dashboardData.summary?.totalSolarProduction?.unit || 'kWh'}</div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30 text-center">
              -
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30 text-center">
              <div className="font-medium text-red-600 dark:text-red-400">
                {dashboardData.summary?.totalGridImported?.display || '0.0'}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">{dashboardData.summary?.totalGridImported?.unit || 'kWh'}</div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30 text-center">
              <div className="font-medium text-green-600 dark:text-green-400">
                {dashboardData.summary?.totalGridExported?.display || '0.0'}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">{dashboardData.summary?.totalGridExported?.unit || 'kWh'}</div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30 text-center">
              <div className="font-medium text-red-600 dark:text-red-400">
                {dashboardData.summary?.solarOnlyCost?.display || '0.00'}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">{dashboardData.summary?.solarOnlyCost?.unit || '???'}</div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30 text-center">
              <div className="font-medium text-green-600 dark:text-green-400">
                {dashboardData.summary?.solarSavings?.display || '0.00'}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">{dashboardData.summary?.solarSavings?.unit || '???'}</div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30 text-center">
              <div className="font-medium text-blue-600 dark:text-blue-400">
                +{dashboardData.summary?.totalBatteryCharged?.display || '0.0'}
              </div>
              <div className="font-medium text-orange-600 dark:text-orange-400">
                -{dashboardData.summary?.totalBatteryDischarged?.display || '0.0'}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">{dashboardData.summary?.totalBatteryCharged?.unit || 'kWh'}</div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30 text-center">
              -
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30 text-center">
              <div className="font-medium text-red-600 dark:text-red-400">
                {dashboardData.summary?.totalGridImported?.display || '0.0'}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">{dashboardData.summary?.totalGridImported?.unit || 'kWh'}</div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30 text-center">
              <div className="font-medium text-green-600 dark:text-green-400">
                {dashboardData.summary?.totalGridExported?.display || '0.0'}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">{dashboardData.summary?.totalGridExported?.unit || 'kWh'}</div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30 text-center">
              <div className="font-medium text-red-600 dark:text-red-400">
                {dashboardData.summary?.optimizedCost?.display || '0.00'}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">{dashboardData.summary?.optimizedCost?.unit || '???'}</div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30 text-center">
              <div className="font-medium text-green-600 dark:text-green-400">
                {dashboardData.summary?.totalSavings?.display || '0.00'}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">{dashboardData.summary?.totalSavings?.unit || '???'}</div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
};