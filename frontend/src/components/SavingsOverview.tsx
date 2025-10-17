import React from 'react';
import { Zap } from 'lucide-react';
import { FormattedValue } from '../types';
import FormattedValueComponent from './FormattedValue';
import { useDashboardData } from '../hooks/useDashboardData';

type SavingsOverviewProps = Record<string, never>

export const SavingsOverview: React.FC<SavingsOverviewProps> = () => {
  const { data: dashboardData, loading, error } = useDashboardData();

  // Helper function to get numeric value from FormattedValue objects (for calculations)
  const getNumericValue = (field: any) => {
    if (typeof field === 'object' && field?.value !== undefined) {
      return field.value;
    }
    return field || 0;
  };

  // Helper function to get formatted text from FormattedValue objects (for display)
  const getFormattedText = (field: any) => {
    if (typeof field === 'object' && field?.text !== undefined) {
      return field.text;
    }
    // Fallback for legacy or raw numeric values
    if (typeof field === 'number') {
      return field.toFixed(2);
    }
    return field || 'N/A';
  };

  // Helper function to get display value (without unit) from FormattedValue objects
  const getDisplayValue = (field: any) => {
    if (typeof field === 'object' && field?.display !== undefined) {
      return field.display;
    }
    return field || 'N/A';
  };

  // Helper function to get unit from FormattedValue objects - NO FALLBACKS for determinism
  const getUnit = (field: any) => {
    if (typeof field === 'object' && field?.unit !== undefined) {
      // Convert Wh to kWh for display
      return field.unit === 'Wh' ? 'kWh' : field.unit;
    }
    // No fallback - if unit is missing, it indicates a backend configuration issue
    return '???';
  };


  if (loading) {
    return (
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
        <div className="flex items-center justify-center h-32">
          <div className="animate-spin h-8 w-8 border-2 border-blue-500 rounded-full border-t-transparent"></div>
          <span className="ml-2 text-gray-900 dark:text-white">Loading schedule...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md p-4">
          <h3 className="text-red-800 dark:text-red-200 font-medium">Error Loading Schedule</h3>
          <p className="text-red-600 dark:text-red-300 mt-1">{error}</p>
          <button 
            onClick={() => window.location.reload()} 
            className="mt-2 px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!dashboardData) {
    return (
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
        <div className="text-center text-gray-500 dark:text-gray-400">No schedule data available</div>
      </div>
    );
  }

  // Use backend-calculated summary data instead of frontend calculations

  // Get final hour for SOC display
  const finalHour = dashboardData.hourlyData[dashboardData.hourlyData.length - 1];

  return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow overflow-x-auto">
      <div className="mb-6">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">Hourly Battery Actions & Savings</h2>
        <p className="text-sm text-gray-600 dark:text-gray-300">
          Current hour highlighted in purple.
        </p>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div className="bg-blue-50 dark:bg-blue-900/20 p-4 rounded-lg text-center border border-blue-200 dark:border-blue-800">
          <FormattedValueComponent
            data={dashboardData.summary?.gridOnlyCost || 'N/A'}
            size="lg"
            align="center"
            color="default"
            className="block"
          />
          <div className="text-sm text-gray-600 dark:text-gray-300">Grid-Only Cost</div>
          <div className="text-xs text-gray-500 dark:text-gray-400">Without solar or battery</div>
        </div>

        <div className="bg-green-50 dark:bg-green-900/20 p-4 rounded-lg text-center border border-green-200 dark:border-green-800">
          <FormattedValueComponent
            data={dashboardData.summary?.optimizedCost || 'N/A'}
            size="lg"
            align="center"
            color="default"
            className="block"
          />
          <div className="text-sm text-gray-600 dark:text-gray-300">Optimized Cost</div>
          <div className="text-xs text-gray-500 dark:text-gray-400">With solar & battery</div>
        </div>

        <div className="bg-purple-50 dark:bg-purple-900/20 p-4 rounded-lg text-center border border-purple-200 dark:border-purple-800">
          <FormattedValueComponent
            data={dashboardData.summary?.totalSavings || 'N/A'}
            size="lg"
            align="center"
            color="default"
            className="block"
          />
          <div className="text-sm text-gray-600 dark:text-gray-300">Total Savings</div>
          <div className="text-xs text-gray-500 dark:text-gray-400">
            <FormattedValueComponent
              data={dashboardData.summary?.totalSavingsPercentage || 'N/A'}
              size="sm"
              align="center"
              color="default"
            />
          </div>
        </div>
      </div>

      {/* Simplified Hourly Table */}
      <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
        <thead className="bg-gray-50 dark:bg-gray-700">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600">
              Hour
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600">
              Price
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600">
              Solar
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600">
              Consumption
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600">
              Battery Action
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600">
              Battery Level
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600">
              Grid Import
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600">
              Grid Export
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600">
              Actual Cost
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600">
              Savings
            </th>
          </tr>
        </thead>
        <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
          {dashboardData.hourlyData.map((hour: any, index: number) => {
            const isCurrentHour = hour.hour === dashboardData.currentHour;
            
            // Row styling based on actual/predicted/current
            const isActual = hour.dataSource === 'actual';
            let rowClass = 'border-l-4 ';
            if (isCurrentHour) {
              rowClass += 'bg-purple-50 dark:bg-purple-900/20 border-purple-400';
            } else if (isActual) {
              rowClass += 'bg-gray-50 dark:bg-gray-700 border-green-400';
            } else {
              rowClass += 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-600';
            }
            
            return (
              <tr key={index} className={rowClass}>
                <td className="px-3 py-2 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600">
                  <div className="flex items-center">
                    <div className="text-right">
                      <div>{hour.hour.toString().padStart(2, '0')}:00</div>
                      <div className="text-xs text-gray-400 dark:text-gray-500">-{hour.hour.toString().padStart(2, '0')}:59</div>
                    </div>
                    {isActual && (
                      <span className="ml-2 text-xs bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 px-2 py-1 rounded">
                        Actual
                      </span>
                    )}
                    {!isActual && !isCurrentHour && (
                      <span className="ml-2 text-xs bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 px-2 py-1 rounded">
                        Predicted
                      </span>
                    )}
                    {isCurrentHour && (
                      <span className="ml-2 text-xs bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 px-2 py-1 rounded">
                        Current
                      </span>
                    )}
                  </div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                  <div className="font-medium">{getDisplayValue(hour.buyPrice)}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">{getUnit(hour.buyPrice)}</div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                  <div className={`font-medium ${getNumericValue(hour.solarProduction) > 0 ? 'text-yellow-600 dark:text-yellow-400' : 'text-gray-400 dark:text-gray-500'}`}>
                    {getDisplayValue(hour.solarProduction)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">{getUnit(hour.solarProduction)}</div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                  <div className="font-medium">{getDisplayValue(hour.homeConsumption)}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">{getUnit(hour.homeConsumption)}</div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                  <div className="flex flex-col items-center space-y-1">
                    {getNumericValue(hour.batteryCharged) > 0.01 && (
                      <span className="text-sm font-medium text-blue-600 dark:text-blue-400 bg-blue-100 dark:bg-blue-900/30 px-2 py-1 rounded flex items-center">
                        <Zap className="h-3 w-3 mr-1" />
                        +{getDisplayValue(hour.batteryCharged)}
                      </span>
                    )}
                    {getNumericValue(hour.batteryDischarged) > 0.01 && (
                      <span className="text-sm font-medium text-orange-600 dark:text-orange-400 bg-orange-100 dark:bg-orange-900/30 px-2 py-1 rounded flex items-center">
                        <Zap className="h-3 w-3 mr-1" />
                        -{getDisplayValue(hour.batteryDischarged)}
                      </span>
                    )}
                    {getNumericValue(hour.batteryCharged) <= 0.01 && getNumericValue(hour.batteryDischarged) <= 0.01 && (
                      <span className="text-sm text-gray-500 dark:text-gray-400">—</span>
                    )}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                  <div className="font-medium">{getFormattedText(hour.batterySocEnd)}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">
                    {getFormattedText(hour.batterySoeEnd) || 'N/A'}
                  </div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                  <div className={`font-medium ${getNumericValue(hour.gridImportNeeded) > 0 ? 'text-red-600 dark:text-red-400' : 'text-gray-400 dark:text-gray-500'}`}>
                    {getDisplayValue(hour.gridImportNeeded)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">{getUnit(hour.gridImportNeeded)}</div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                  <div className={`font-medium ${getNumericValue(hour.gridExported) > 0 ? 'text-green-600 dark:text-green-400' : 'text-gray-400 dark:text-gray-500'}`}>
                    {getDisplayValue(hour.gridExported)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">{getUnit(hour.gridExported)}</div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                  <div className={`font-medium ${
                    Math.abs(getNumericValue(hour.hourlyCost)) < 0.01 ? 'text-gray-900 dark:text-white' :
                    getNumericValue(hour.hourlyCost) > 0 ? 'text-red-600 dark:text-red-400' : 'text-gray-900 dark:text-white'
                  }`}>
                    {getDisplayValue(hour.hourlyCost)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">{getUnit(hour.hourlyCost)}</div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm border border-gray-300 dark:border-gray-600 text-center">
                  <div className={`font-medium ${
                    Math.abs(getNumericValue(hour.hourlySavings)) < 0.01 ? 'text-gray-900 dark:text-white' :
                    getNumericValue(hour.hourlySavings) > 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
                  }`}>
                    {getDisplayValue(hour.hourlySavings)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">{getUnit(hour.hourlySavings)}</div>
                </td>
              </tr>
            );
          })}
          
          {/* Totals Row */}
          <tr className="bg-gray-100 dark:bg-gray-600 font-semibold border-t-2 border-gray-400 dark:border-gray-500">
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600">
              TOTAL
            </td>
            
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
              <div className="text-xs text-gray-500 dark:text-gray-400">AVG</div>
              <div className="font-medium">{getDisplayValue(dashboardData.summary?.averagePrice)}</div>
              <div className="text-xs text-gray-500 dark:text-gray-400">{getUnit(dashboardData.summary?.averagePrice)}</div>
            </td>

            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
              <div className="font-medium text-yellow-600 dark:text-yellow-400">
                {getDisplayValue(dashboardData.summary?.totalSolarProduction)}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">{getUnit(dashboardData.summary?.totalSolarProduction)}</div>
            </td>

            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
              <div className="font-medium">
                {getDisplayValue(dashboardData.summary?.totalHomeConsumption)}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">{getUnit(dashboardData.summary?.totalHomeConsumption)}</div>
            </td>
            
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
              <div className="flex flex-col items-center">
                <div className="text-sm mb-1 text-blue-600 dark:text-blue-400 font-medium">
                  +{getDisplayValue(dashboardData.summary?.totalBatteryCharged)}
                </div>
                <div className="text-sm text-orange-600 dark:text-orange-400 font-medium">
                  -{getDisplayValue(dashboardData.summary?.totalBatteryDischarged)}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  {getUnit(dashboardData.summary?.totalBatteryCharged)}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400">
                  Net: {getDisplayValue(dashboardData.summary?.netBatteryAction)}
                </div>
              </div>
            </td>
            
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
              <div className="text-xs text-gray-500 dark:text-gray-400">Final</div>
              <div className="font-medium">
                {finalHour ? getFormattedText(finalHour.batterySocEnd) : '-'}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">
                {getFormattedText(dashboardData.summary?.finalBatterySoe) || getFormattedText(finalHour?.batterySoeEnd) || 'N/A'}
              </div>
            </td>
            
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
              <div className="font-medium text-red-600 dark:text-red-400">
                {getDisplayValue(dashboardData.summary?.totalGridImported)}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">{getUnit(dashboardData.summary?.totalGridImported)}</div>
            </td>

            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
              <div className="font-medium text-green-600 dark:text-green-400">
                {getDisplayValue(dashboardData.summary?.totalGridExported)}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">{getUnit(dashboardData.summary?.totalGridExported)}</div>
            </td>

            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
              <div className="font-medium text-red-600 dark:text-red-400">
                {getDisplayValue(dashboardData.summary?.optimizedCost)}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">{getUnit(dashboardData.summary?.optimizedCost)}</div>
            </td>

            <td className="px-3 py-2 whitespace-nowrap text-sm border border-gray-300 dark:border-gray-600 text-center">
              <div className="font-medium text-green-600 dark:text-green-400">
                {getDisplayValue(dashboardData.summary?.totalSavings)}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">{getUnit(dashboardData.summary?.totalSavings)}</div>
            </td>
          </tr>
        </tbody>
      </table>

      {/* Explanation */}
      <div className="mt-4 p-3 bg-gray-50 dark:bg-gray-700 rounded-lg text-sm">
        <p className="text-gray-600 dark:text-gray-300">
          Battery actions: <span className="bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-300 px-1 rounded">blue = charging</span>,
          <span className="bg-orange-100 dark:bg-orange-900/30 text-orange-800 dark:text-orange-300 px-1 rounded">orange = discharging</span>.
          The "Savings" column shows hourly optimization: positive (green) = money saved, 
          zero (black) = break-even, negative (red) = additional cost that hour.
        </p>
      </div>
    </div>
  );
};