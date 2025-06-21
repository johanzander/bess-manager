import React, { useState, useEffect } from 'react';
import { Zap } from 'lucide-react';
import api from '../lib/api';

interface SavingsOverviewProps {
  // Empty props interface for future extensions if needed
}

interface DashboardResponse {
  currentHour: number;
  totalDailySavings: number;
  batteryCapacity?: number;
  hourlyData: Array<{
    hour: number;
    isActual?: boolean;
    dataSource?: string;
    homeConsumed: number;
    solarGenerated: number;
    gridImported: number;
    gridExported: number;
    batteryCharged: number;
    batteryDischarged: number;
    batterySocEnd: number;
    buyPrice: number;
    hourlyCost: number;
    hourlySavings: number;
  }>;
}

export const SavingsOverview: React.FC<SavingsOverviewProps> = () => {
  const [dashboardData, setDashboardData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const response = await api.get('/api/dashboard');
        setDashboardData(response.data);
        setError(null);
      } catch (err) {
        console.error('Error fetching dashboard data:', err);
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

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

  // Calculate summary data from the hourly data
  const totalConsumption = dashboardData.hourlyData.reduce((sum: number, h: any) => sum + h.homeConsumed, 0);
  const totalSolar = dashboardData.hourlyData.reduce((sum: number, h: any) => sum + h.solarGenerated, 0);
  const totalGridImport = dashboardData.hourlyData.reduce((sum: number, h: any) => sum + h.gridImported, 0);
  const totalGridExport = dashboardData.hourlyData.reduce((sum: number, h: any) => sum + h.gridExported, 0);
  const totalBatteryCharged = dashboardData.hourlyData.reduce((sum: number, h: any) => sum + h.batteryCharged, 0);
  const totalBatteryDischarged = dashboardData.hourlyData.reduce((sum: number, h: any) => sum + h.batteryDischarged, 0);
  const netBatteryAction = totalBatteryCharged - totalBatteryDischarged;
  
  // Calculate base cost (grid-only scenario)
  const baseCost = dashboardData.hourlyData.reduce((sum: number, h: any) => sum + (h.homeConsumed * h.buyPrice), 0);
  
  // Actual optimized cost
  const optimizedCost = dashboardData.hourlyData.reduce((sum: number, h: any) => sum + h.hourlyCost, 0);
  
  // Total savings from optimization
  const totalSavings = dashboardData.totalDailySavings;

  // Average price
  const avgPrice = dashboardData.hourlyData.reduce((sum: number, h: any) => sum + h.buyPrice, 0) / dashboardData.hourlyData.length;

  const summary = {
    baseCost,
    optimizedCost,
    savings: totalSavings
  };

  // Calculate final SOE for the totals row
  const finalHour = dashboardData.hourlyData[dashboardData.hourlyData.length - 1];
  const finalSOE = finalHour ? (finalHour.batterySocEnd / 100) * (dashboardData.batteryCapacity || 30) : 0;

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
          <div className="text-2xl font-bold text-blue-600 dark:text-blue-400">{baseCost.toFixed(2)} SEK</div>
          <div className="text-sm text-gray-600 dark:text-gray-300">Grid-Only Cost</div>
          <div className="text-xs text-gray-500 dark:text-gray-400">Without solar or battery</div>
        </div>
        
        <div className="bg-green-50 dark:bg-green-900/20 p-4 rounded-lg text-center border border-green-200 dark:border-green-800">
          <div className="text-2xl font-bold text-green-600 dark:text-green-400">{optimizedCost.toFixed(2)} SEK</div>
          <div className="text-sm text-gray-600 dark:text-gray-300">Optimized Cost</div>
          <div className="text-xs text-gray-500 dark:text-gray-400">With solar & battery</div>
        </div>

        <div className="bg-purple-50 dark:bg-purple-900/20 p-4 rounded-lg text-center border border-purple-200 dark:border-purple-800">
          <div className="text-2xl font-bold text-purple-600 dark:text-purple-400">{totalSavings.toFixed(2)} SEK</div>
          <div className="text-sm text-gray-600 dark:text-gray-300">Total Savings</div>
          <div className="text-xs text-gray-500 dark:text-gray-400">{((totalSavings / baseCost) * 100).toFixed(1)}% saved</div>
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
            let rowClass = 'border-l-4 ';
            if (isCurrentHour) {
              rowClass += 'bg-purple-50 dark:bg-purple-900/20 border-purple-400';
            } else if (hour.isActual) {
              rowClass += 'bg-gray-50 dark:bg-gray-700 border-green-400';
            } else {
              rowClass += 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-600';
            }
            
            return (
              <tr key={index} className={rowClass}>
                <td className="px-3 py-2 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600">
                  <div className="flex items-center">
                    {hour.hour.toString().padStart(2, '0')}:00
                    {hour.isActual && (
                      <span className="ml-2 text-xs bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 px-2 py-1 rounded">
                        Actual
                      </span>
                    )}
                    {!hour.isActual && !isCurrentHour && (
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
                  <div className="font-medium">{hour.buyPrice.toFixed(2)}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">SEK/kWh</div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                  <div className="font-medium text-yellow-600 dark:text-yellow-400">{hour.solarGenerated.toFixed(1)}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                  <div className="font-medium">{hour.homeConsumed.toFixed(1)}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                  <div className="flex items-center justify-center">
                    {hour.batteryCharged > 0.01 && (
                      <span className="text-sm font-medium text-green-600 dark:text-green-400 bg-green-100 dark:bg-green-900/30 px-2 py-1 rounded flex items-center">
                        <Zap className="h-3 w-3 mr-1" />
                        +{hour.batteryCharged.toFixed(1)}
                      </span>
                    )}
                    {hour.batteryDischarged > 0.01 && (
                      <span className="text-sm font-medium text-red-600 dark:text-red-400 bg-red-100 dark:bg-red-900/30 px-2 py-1 rounded flex items-center">
                        <Zap className="h-3 w-3 mr-1" />
                        -{hour.batteryDischarged.toFixed(1)}
                      </span>
                    )}
                    {hour.batteryCharged <= 0.01 && hour.batteryDischarged <= 0.01 && (
                      <span className="text-sm text-gray-500 dark:text-gray-400">—</span>
                    )}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                  <div className="font-medium">{hour.batterySocEnd.toFixed(0)}%</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">
                    {((hour.batterySocEnd / 100) * (dashboardData.batteryCapacity || 30)).toFixed(1)} kWh
                  </div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                  <div className={`font-medium ${hour.gridImported > 0 ? 'text-red-600 dark:text-red-400' : 'text-gray-400 dark:text-gray-500'}`}>
                    {hour.gridImported.toFixed(1)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                  <div className={`font-medium ${hour.gridExported > 0 ? 'text-green-600 dark:text-green-400' : 'text-gray-400 dark:text-gray-500'}`}>
                    {hour.gridExported.toFixed(1)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                  <div className={`font-medium ${
                    Math.abs(hour.hourlyCost) < 0.01 ? 'text-gray-900 dark:text-white' : 
                    hour.hourlyCost > 0 ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'
                  }`}>
                    {hour.hourlyCost.toFixed(2)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">SEK</div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm border border-gray-300 dark:border-gray-600 text-center">
                  <div className={`font-medium ${
                    Math.abs(hour.hourlySavings) < 0.01 ? 'text-gray-900 dark:text-white' : 
                    hour.hourlySavings > 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
                  }`}>
                    {Math.abs(hour.hourlySavings) < 0.01 ? '0.00' : 
                     hour.hourlySavings > 0 ? `+${hour.hourlySavings.toFixed(2)}` : hour.hourlySavings.toFixed(2)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">SEK</div>
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
              <div>{avgPrice.toFixed(2)}</div>
            </td>
            
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
              <div className="font-medium text-yellow-600 dark:text-yellow-400">
                {totalSolar.toFixed(1)}
              </div>
            </td>
            
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
              <div className="font-medium">
                {totalConsumption.toFixed(1)}
              </div>
            </td>
            
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
              <div className="flex flex-col items-center">
                <div className="text-xs mb-1 text-blue-600 dark:text-blue-400">
                  +{totalBatteryCharged.toFixed(1)} kWh
                </div>
                <div className="text-xs text-orange-600 dark:text-orange-400">
                  -{totalBatteryDischarged.toFixed(1)} kWh
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Net: {netBatteryAction.toFixed(1)} kWh
                </div>
              </div>
            </td>
            
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
              <div className="text-xs text-gray-500 dark:text-gray-400">Final</div>
              <div className="font-medium">
                {finalHour?.batterySocEnd.toFixed(0) || '-'}%
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">
                {finalSOE.toFixed(1)} kWh
              </div>
            </td>
            
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
              <div className="font-medium text-red-600 dark:text-red-400">
                {totalGridImport.toFixed(1)}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
            </td>
            
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
              <div className="font-medium text-green-600 dark:text-green-400">
                {totalGridExport.toFixed(1)}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
            </td>
            
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
              <div className={`font-medium ${
                Math.abs(summary.optimizedCost) < 0.01 ? 'text-gray-900 dark:text-white' : 
                summary.optimizedCost > 0 ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'
              }`}>
                {summary.optimizedCost.toFixed(2)}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">SEK</div>
            </td>
            
            <td className="px-3 py-2 whitespace-nowrap text-sm border border-gray-300 dark:border-gray-600 text-center">
              <div className={`font-medium ${
                Math.abs(summary.savings) < 0.01 ? 'text-gray-900 dark:text-white' : 
                summary.savings > 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
              }`}>
                {Math.abs(summary.savings) < 0.01 ? '0.00' : 
                 summary.savings > 0 ? `+${summary.savings.toFixed(2)}` : summary.savings.toFixed(2)}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">SEK</div>
            </td>
          </tr>
        </tbody>
      </table>

      {/* Explanation */}
      <div className="mt-4 p-3 bg-gray-50 dark:bg-gray-700 rounded-lg text-sm">
        <p className="text-gray-600 dark:text-gray-300">
          Battery actions: <span className="bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300 px-1 rounded">green = charging</span>, 
          <span className="bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-300 px-1 rounded">red = discharging</span>.
          The "Savings" column shows hourly optimization: positive (green) = money saved, 
          zero (black) = break-even, negative (red) = additional cost that hour.
        </p>
      </div>
    </div>
  );
};