import React, { useState, useEffect } from 'react';
import { BatterySettings } from '../types';

// Interface for the new DailyView API response
interface DailyViewHourlyData {
  hour: number;
  data_source: 'actual' | 'predicted';
  solar_generated: number;
  home_consumed: number;
  grid_imported: number;
  grid_exported: number;
  battery_charged: number;
  battery_discharged: number;
  battery_soc_start: number;
  battery_soc_end: number;
  electricity_price: number;
  hourly_cost: number;
  hourly_savings: number;
  battery_action: number | null;
  battery_cycle_cost: number;
  is_actual: boolean;
  is_predicted: boolean;
}

interface DailyViewResponse {
  date: string;
  current_hour: number;
  total_daily_savings: number;
  actual_savings_so_far: number;
  predicted_remaining_savings: number;
  actual_hours_count: number;
  predicted_hours_count: number;
  hourly_data: DailyViewHourlyData[];
  battery_capacity?: number; // Optional battery capacity from backend
}

interface SimplifiedSavingsTableProps {
  settings: BatterySettings;
}

export const SavingsOverview: React.FC<SimplifiedSavingsTableProps> = ({
  settings
}) => {
  const [dailyView, setDailyView] = useState<DailyViewResponse | null>(null);
  const [batterySettings, setBatterySettings] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Helper function to calculate SOE from SOC
  const calculateSOE = (socPercent: number, batteryCapacity: number = 30.0): number => {
    return (socPercent / 100) * batteryCapacity;
  };

  // Get battery capacity from API response (snake_case), settings prop (camelCase), or use default
  const batteryCapacity = batterySettings?.total_capacity || batterySettings?.totalCapacity || settings?.totalCapacity || 30.0;

  // Fetch battery settings and daily view data
  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        
        // Fetch battery settings
        const batteryResponse = await fetch('/api/settings/battery', {
          cache: 'no-cache',
          headers: {
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
          }
        });
        if (batteryResponse.ok) {
          const batteryData = await batteryResponse.json();
          setBatterySettings(batteryData);
          console.log('Battery settings fetched:', batteryData);
        } else {
          console.warn('Failed to fetch battery settings, using fallback');
        }
        
        // Fetch daily view
        const dailyResponse = await fetch('/api/v2/daily_view', {
          cache: 'no-cache',
          headers: {
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
          }
        });
        if (!dailyResponse.ok) {
          throw new Error(`Failed to fetch daily view: ${dailyResponse.status} ${dailyResponse.statusText}`);
        }
        const dailyData = await dailyResponse.json();
        setDailyView(dailyData);
        setError(null);
        
      } catch (err) {
        console.error('Error fetching data:', err);
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  if (loading) {
    return (
      <div className="bg-white p-6 rounded-lg shadow">
        <div className="flex items-center justify-center h-32">
          <div className="animate-spin h-8 w-8 border-2 border-blue-500 rounded-full border-t-transparent"></div>
          <span className="ml-2">Loading schedule...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white p-6 rounded-lg shadow">
        <div className="bg-red-50 border border-red-200 rounded-md p-4">
          <h3 className="text-red-800 font-medium">Error Loading Schedule</h3>
          <p className="text-red-600 mt-1">{error}</p>
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

  if (!dailyView) {
    return (
      <div className="bg-white p-6 rounded-lg shadow">
        <div className="text-center text-gray-500">No schedule data available</div>
      </div>
    );
  }

  // Calculate summary data from the hourly data
  const totalConsumption = dailyView.hourly_data.reduce((sum, h) => sum + h.home_consumed, 0);
  const totalSolar = dailyView.hourly_data.reduce((sum, h) => sum + h.solar_generated, 0);
  const totalGridImport = dailyView.hourly_data.reduce((sum, h) => sum + h.grid_imported, 0);
  const totalGridExport = dailyView.hourly_data.reduce((sum, h) => sum + h.grid_exported, 0);
  const totalBatteryCharged = dailyView.hourly_data.reduce((sum, h) => sum + h.battery_charged, 0);
  const totalBatteryDischarged = dailyView.hourly_data.reduce((sum, h) => sum + h.battery_discharged, 0);
  const netBatteryAction = totalBatteryCharged - totalBatteryDischarged;
  
  // Calculate base cost (grid-only scenario)
  const baseCost = dailyView.hourly_data.reduce((sum, h) => sum + (h.home_consumed * h.electricity_price), 0);
  
  // Actual optimized cost
  const optimizedCost = dailyView.hourly_data.reduce((sum, h) => sum + h.hourly_cost, 0);
  
  // Total savings from optimization
  const totalSavings = dailyView.total_daily_savings;

  // Average price
  const avgPrice = dailyView.hourly_data.reduce((sum, h) => sum + h.electricity_price, 0) / dailyView.hourly_data.length;

  const summary = {
    baseCost,
    optimizedCost,
    savings: totalSavings
  };

  // Calculate final SOE for the totals row
  const finalHour = dailyView.hourly_data[dailyView.hourly_data.length - 1];
  const finalSOE = finalHour ? calculateSOE(finalHour.battery_soc_end, batteryCapacity) : 0;

  // Debug logging
  console.log('Battery capacity being used:', batteryCapacity);
  console.log('batterySettings?.total_capacity:', batterySettings?.total_capacity);
  console.log('batterySettings?.totalCapacity:', batterySettings?.totalCapacity);
  console.log('settings?.totalCapacity:', settings?.totalCapacity);

  return (
    <div className="bg-white p-6 rounded-lg shadow overflow-x-auto">
      {/* Summary Cards at Top */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div className="bg-red-50 p-4 rounded-lg text-center border">
          <div className="text-2xl font-bold text-red-600">{summary.baseCost.toFixed(2)}</div>
          <div className="text-sm text-gray-600">Grid-Only Cost (SEK)</div>
          <div className="text-xs text-gray-500">What you would have paid</div>
        </div>
        
        <div className="bg-blue-50 p-4 rounded-lg text-center border">
          <div className="text-2xl font-bold text-blue-600">{summary.optimizedCost.toFixed(2)}</div>
          <div className="text-sm text-gray-600">Actual Cost (SEK)</div>
          <div className="text-xs text-gray-500">With solar + battery</div>
        </div>
        
        <div className="bg-green-50 p-4 rounded-lg text-center border">
          <div className="text-2xl font-bold text-green-600">{summary.savings.toFixed(2)}</div>
          <div className="text-sm text-gray-600">Total Savings (SEK)</div>
          <div className="text-xs text-gray-500">{((summary.savings / summary.baseCost) * 100).toFixed(1)}% saved</div>
        </div>
      </div>

      {/* Simplified Hourly Table */}
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-800 uppercase tracking-wider border">
              Hour
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border">
              Price
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border">
              Solar
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border">
              Consumption
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border">
              Battery Action
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border">
              Battery Level
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border">
              Grid Import
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border">
              Grid Export
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border">
              Actual Cost
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border">
              Savings
            </th>
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {dailyView.hourly_data.map((hour, index) => {
            const isActual = hour.data_source === 'actual';
            const isCurrent = hour.hour === dailyView.current_hour;
            
            // Calculate base cost for this hour (grid-only scenario)
            const gridOnlyCost = hour.home_consumed * hour.electricity_price;
            
            // Calculate SOE for this hour
            const soeKwh = calculateSOE(hour.battery_soc_end, batteryCapacity);
            
            // Row styling based on actual/predicted/current
            let rowClass = 'border-l-4 ';
            if (isCurrent) {
              rowClass += 'bg-purple-50 border-purple-400';
            } else if (isActual) {
              rowClass += 'bg-gray-50 border-green-400';
            } else {
              rowClass += 'bg-white border-gray-200';
            }
            
            return (
              <tr key={index} className={rowClass}>
                <td className="px-3 py-2 whitespace-nowrap text-sm font-medium text-gray-900 border">
                  <div className="flex items-center">
                    {hour.hour.toString().padStart(2, '0')}
                    {isActual && (
                      <span className="ml-2 text-xs bg-green-100 text-green-700 px-2 py-1 rounded">
                        Actual
                      </span>
                    )}
                    {!isActual && !isCurrent && (
                      <span className="ml-2 text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded">
                        Predicted
                      </span>
                    )}
                    {isCurrent && (
                      <span className="ml-2 text-xs bg-purple-100 text-purple-700 px-2 py-1 rounded">
                        Current
                      </span>
                    )}
                  </div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border text-center">
                  <div>{hour.electricity_price.toFixed(2)}</div>
                  <div className="text-xs text-gray-500">
                    {(hour.electricity_price * 0.6).toFixed(2)} sell
                  </div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border text-center">
                  <div className="font-medium text-yellow-600">{hour.solar_generated.toFixed(1)}</div>
                  <div className="text-xs text-gray-500">kWh</div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border text-center">
                  <div className="font-medium">{hour.home_consumed.toFixed(1)}</div>
                  <div className="text-xs text-gray-500">kWh</div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap border text-center">
                  <span className={`px-2 py-1 inline-flex text-sm leading-5 font-semibold rounded-full ${
                    (hour.battery_action || 0) > 0.1
                      ? 'bg-green-100 text-green-800'
                      : (hour.battery_action || 0) < -0.1
                      ? 'bg-red-100 text-red-800'
                      : 'bg-gray-100 text-gray-800'
                  }`}>
                    {(hour.battery_action || 0) > 0.1 ? '+' : ''}{(hour.battery_action || 0).toFixed(1)}
                  </span>
                  <div className="text-xs text-gray-500">kWh</div>
                </td>
                
                {/* Updated Battery Level cell with both SOC and SOE */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border text-center">
                  <div className="font-medium">{hour.battery_soc_end.toFixed(0)}%</div>
                  <div className="text-xs text-gray-500">
                    {soeKwh.toFixed(1)} kWh
                  </div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border text-center">
                  <div className={`font-medium ${hour.grid_imported > 0 ? 'text-red-600' : 'text-gray-400'}`}>
                    {hour.grid_imported.toFixed(1)}
                  </div>
                  <div className="text-xs text-gray-500">kWh</div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border text-center">
                  <div className={`font-medium ${hour.grid_exported > 0 ? 'text-green-600' : 'text-gray-400'}`}>
                    {hour.grid_exported.toFixed(1)}
                  </div>
                  <div className="text-xs text-gray-500">kWh</div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border text-center">
                  <div className="font-medium">{hour.hourly_cost.toFixed(2)}</div>
                  <div className="text-xs text-gray-500">SEK</div>
                </td>
                
                <td className="px-3 py-2 whitespace-nowrap text-sm border text-center">
                  <div className={`font-medium ${
                    Math.abs(hour.hourly_savings) < 0.01 ? 'text-gray-900' : 
                    hour.hourly_savings > 0 ? 'text-green-600' : 'text-red-600'
                  }`}>
                    {Math.abs(hour.hourly_savings) < 0.01 ? '0.00' : 
                     hour.hourly_savings > 0 ? `+${hour.hourly_savings.toFixed(2)}` : hour.hourly_savings.toFixed(2)}
                  </div>
                  <div className="text-xs text-gray-500">SEK</div>
                </td>
              </tr>
            );
          })}
          
          {/* Totals Row */}
          <tr className="bg-gray-100 font-semibold border-t-2">
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
              TOTAL
            </td>
            
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border text-center">
              <div className="text-xs text-gray-500">AVG</div>
              <div>{avgPrice.toFixed(2)}</div>
            </td>
            
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border text-center">
              <div className="font-medium text-yellow-600">
                {totalSolar.toFixed(1)}
              </div>
            </td>
            
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border text-center">
              <div className="font-medium">
                {totalConsumption.toFixed(1)}
              </div>
            </td>
            
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border text-center">
              <div className="text-xs text-gray-500">Net</div>
              <div className="font-medium">
                {netBatteryAction.toFixed(1)}
              </div>
            </td>
            
            {/* Updated Totals Battery Level cell with both SOC and SOE */}
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border text-center">
              <div className="text-xs text-gray-500">Final</div>
              <div className="font-medium">
                {finalHour?.battery_soc_end.toFixed(0) || '-'}%
              </div>
              <div className="text-xs text-gray-500">
                {finalSOE.toFixed(1)} kWh
              </div>
            </td>
            
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border text-center">
              <div className="font-medium text-red-600">
                {totalGridImport.toFixed(1)}
              </div>
            </td>
            
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border text-center">
              <div className="font-medium text-green-600">
                {totalGridExport.toFixed(1)}
              </div>
            </td>
            
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border text-center">
              <div className="font-medium">{summary.optimizedCost.toFixed(2)}</div>
            </td>
            
            <td className="px-3 py-2 whitespace-nowrap text-sm border text-center">
              <div className={`font-medium ${
                Math.abs(summary.savings) < 0.01 ? 'text-gray-900' : 
                summary.savings > 0 ? 'text-green-600' : 'text-red-600'
              }`}>
                {Math.abs(summary.savings) < 0.01 ? '0.00' : 
                 summary.savings > 0 ? `+${summary.savings.toFixed(2)}` : summary.savings.toFixed(2)}
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      
      {/* Key Insights */}
      <div className="mt-6 bg-gray-50 p-4 rounded-lg">
        <h3 className="text-lg font-semibold mb-3 text-gray-800">Daily Summary</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
          <div className="bg-white p-3 rounded border">
            <div className="font-medium text-gray-700 mb-1">Energy Independence</div>
            <div className="text-lg font-bold text-green-600">
              {totalConsumption > 0 ? 
                (((totalSolar + totalBatteryDischarged) / totalConsumption) * 100).toFixed(0) : '0'}%
            </div>
            <div className="text-xs text-gray-500">
              From renewable sources
            </div>
          </div>
          
          <div className="bg-white p-3 rounded border">
            <div className="font-medium text-gray-700 mb-1">Solar Production</div>
            <div className="text-lg font-bold text-yellow-600">
              {totalSolar.toFixed(1)} kWh
            </div>
            <div className="text-xs text-gray-500">
              {totalSolar > 0 ? 
                (((totalSolar - totalGridExport) / totalSolar) * 100).toFixed(0) + '% self-consumed'
                : 'No solar today'}
            </div>
          </div>
          
          <div className="bg-white p-3 rounded border">
            <div className="font-medium text-gray-700 mb-1">Battery Activity</div>
            <div className="text-lg font-bold text-blue-600">
              {totalBatteryCharged.toFixed(1)} / {totalBatteryDischarged.toFixed(1)}
            </div>
            <div className="text-xs text-gray-500">
              kWh charged / discharged
            </div>
          </div>
          
          <div className="bg-white p-3 rounded border">
            <div className="font-medium text-gray-700 mb-1">Cost Efficiency</div>
            <div className="text-lg font-bold text-purple-600">
              {((summary.savings / summary.baseCost) * 100).toFixed(1)}%
            </div>
            <div className="text-xs text-gray-500">
              {summary.savings.toFixed(1)} SEK saved today
            </div>
          </div>
        </div>
        
        {/* Additional Energy Breakdown */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4 text-sm">
          <div className="bg-white p-3 rounded border">
            <div className="font-medium text-gray-700 mb-2">Home Consumption</div>
            <div className="flex justify-between items-center">
              <span>Total:</span>
              <span className="font-medium">{totalConsumption.toFixed(1)} kWh</span>
            </div>
            <div className="flex justify-between items-center">
              <span>Average:</span>
              <span className="font-medium">{(totalConsumption / dailyView.hourly_data.length).toFixed(1)} kWh/h</span>
            </div>
          </div>
          
          <div className="bg-white p-3 rounded border">
            <div className="font-medium text-gray-700 mb-2">Grid Exchange</div>
            <div className="flex justify-between items-center">
              <span>Import:</span>
              <span className="font-medium text-red-600">{totalGridImport.toFixed(1)} kWh</span>
            </div>
            <div className="flex justify-between items-center">
              <span>Export:</span>
              <span className="font-medium text-green-600">{totalGridExport.toFixed(1)} kWh</span>
            </div>
            <div className="flex justify-between items-center border-t pt-1">
              <span>Net:</span>
              <span className={`font-medium ${
                (totalGridImport - totalGridExport) > 0 ? 'text-red-600' : 'text-green-600'
              }`}>
                {(totalGridImport - totalGridExport).toFixed(1)} kWh
              </span>
            </div>
          </div>
        </div>

        {/* Battery Capacity Info */}
        <div className="bg-white p-3 rounded border mt-4">
          <div className="font-medium text-gray-700 mb-2">Battery Information</div>
          <div className="flex justify-between items-center">
            <span>Total Capacity:</span>
            <span className="font-medium">{batteryCapacity.toFixed(1)} kWh</span>
          </div>
          <div className="flex justify-between items-center">
            <span>Current Level:</span>
            <span className="font-medium">
              {finalHour?.battery_soc_end.toFixed(0) || '0'}% ({finalSOE.toFixed(1)} kWh)
            </span>
          </div>
        </div>
      </div>
      
      {/* Data Quality Info */}
      <div className="mt-4 bg-blue-50 border border-blue-200 rounded-md p-3">
        <h4 className="font-medium text-blue-800 mb-2">📊 Data Overview</h4>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm text-blue-700">
          <div>
            <span className="font-medium">Actual Hours:</span> {dailyView.actual_hours_count}
          </div>
          <div>
            <span className="font-medium">Predicted Hours:</span> {dailyView.predicted_hours_count}
          </div>
          <div>
            <span className="font-medium">Total Savings:</span> {dailyView.total_daily_savings.toFixed(2)} SEK
          </div>
          <div>
            <span className="font-medium">Current Hour:</span> {dailyView.current_hour}
          </div>
        </div>
      </div>
      
      {/* Legend for row styling */}
      <div className="mt-4 bg-blue-50 border border-blue-200 rounded-md p-3">
        <h4 className="font-medium text-blue-800 mb-2">Row Styling Legend</h4>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
          <div className="flex items-center">
            <div className="w-4 h-4 bg-gray-50 border-l-4 border-green-400 mr-2"></div>
            <span className="text-blue-700">Actual data (completed hours)</span>
          </div>
          <div className="flex items-center">
            <div className="w-4 h-4 bg-white border-l-4 border-gray-200 mr-2"></div>
            <span className="text-blue-700">Predicted data (future hours)</span>
          </div>
          <div className="flex items-center">
            <div className="w-4 h-4 bg-purple-50 border-l-4 border-purple-400 mr-2"></div>
            <span className="text-blue-700">Current hour</span>
          </div>
        </div>
      </div>
      
      {/* Usage Tips */}
      <div className="mt-4 bg-blue-50 border border-blue-200 rounded-md p-3">
        <p className="text-blue-800 text-sm">
          <strong>Reading the table:</strong> Battery Level shows both percentage and energy amount (kWh). 
          Battery actions: <span className="bg-green-100 text-green-800 px-1 rounded">green = charging</span>, 
          <span className="bg-red-100 text-red-800 px-1 rounded">red = discharging</span>.
          The "Savings" column shows hourly optimization: positive (green) = money saved, 
          zero (black) = break-even, negative (red) = additional cost that hour.
        </p>
      </div>
    </div>
  );
};