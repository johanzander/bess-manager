import React, { useState, useEffect } from 'react';
import { BatterySettings } from '../types';
import api from '../lib/api';

// New interface based on DailyView API
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
}

interface BatteryScheduleTableProps {
  settings: BatterySettings;
}

export const DetailedSavingsAnalysis: React.FC<BatteryScheduleTableProps> = ({
}) => {
  const [dailyView, setDailyView] = useState<DailyViewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch data using the new DailyView API
  useEffect(() => {
    const fetchDailyView = async () => {
      try {
        setLoading(true);
        const response = await api.get('/api/v2/daily_view');
        setDailyView(response.data);
        setError(null);
      } catch (err) {
        console.error('Error fetching daily view:', err);
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchDailyView();
  }, []);

  // Helper function to safely display values
  const displayValue = (value: any, defaultText: string = "N/A", decimals: number = 2) => {
    if (value === undefined || value === null) {
      return defaultText;
    }
    if (typeof value === 'number') {
      return value.toFixed(decimals);
    }
    return String(value);
  };

  // Calculate derived values for each hour
  const calculateHourData = (hour: DailyViewHourlyData) => {
    const basePrice = hour.electricity_price;
    const sellPrice = basePrice * 0.6; // Standard sell price calculation
    
    // Calculate base cost (grid-only scenario)
    const baseCost = hour.home_consumed * basePrice;
    
    // Calculate solar-only scenario
    const directSolar = Math.min(hour.home_consumed, hour.solar_generated);
    const solarExcess = Math.max(0, hour.solar_generated - directSolar);
    const gridImportNeeded = Math.max(0, hour.home_consumed - directSolar);
    const solarOnlyCost = gridImportNeeded * basePrice - solarExcess * sellPrice;
    const solarSavings = baseCost - solarOnlyCost;
    
    // Battery+Solar scenario (actual costs from optimization)
    const batterySolarCost = hour.hourly_cost;
    const totalSavings = hour.hourly_savings;
    
    return {
      basePrice,
      sellPrice,
      baseCost,
      directSolar,
      solarExcess,
      gridImportNeeded,
      solarOnlyCost,
      solarSavings,
      batterySolarCost,
      totalSavings
    };
  };

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

  // Calculate totals
  const totals = dailyView.hourly_data.reduce(
    (acc, hour) => {
      const derived = calculateHourData(hour);
      acc.totalConsumption += hour.home_consumed;
      acc.totalSolar += hour.solar_generated;
      acc.totalBaseCost += derived.baseCost;
      acc.totalSolarOnlyCost += derived.solarOnlyCost;
      acc.totalBatterySolarCost += hour.hourly_cost;
      acc.totalSolarSavings += derived.solarSavings;
      acc.totalSavings += hour.hourly_savings;
      acc.totalBatteryCharged += hour.battery_charged;
      acc.totalBatteryDischarged += hour.battery_discharged;
      acc.totalDirectSolar += derived.directSolar;
      acc.totalSolarExcess += derived.solarExcess;
      acc.totalGridImport += hour.grid_imported;
      acc.totalGridExport += hour.grid_exported;
      return acc;
    },
    {
      totalConsumption: 0,
      totalSolar: 0,
      totalBaseCost: 0,
      totalSolarOnlyCost: 0,
      totalBatterySolarCost: 0,
      totalSolarSavings: 0,
      totalSavings: 0,
      totalBatteryCharged: 0,
      totalBatteryDischarged: 0,
      totalDirectSolar: 0,
      totalSolarExcess: 0,
      totalGridImport: 0,
      totalGridExport: 0
    }
  );

  const avgPrice = totals.totalBaseCost / totals.totalConsumption;

  return (
    <div className="bg-white p-6 rounded-lg shadow overflow-x-auto">
      {/* Summary Cards at Top */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <div className="bg-red-50 p-4 rounded-lg text-center border">
          <div className="text-2xl font-bold text-red-600">{displayValue(totals.totalBaseCost)}</div>
          <div className="text-sm text-gray-600">Grid-Only Cost (SEK)</div>
          <div className="text-xs text-gray-500">What you would have paid</div>
        </div>
        
        <div className="bg-yellow-50 p-4 rounded-lg text-center border">
          <div className="text-2xl font-bold text-yellow-600">{displayValue(totals.totalSolar, "0", 1)}</div>
          <div className="text-sm text-gray-600">Solar Production (kWh)</div>
          <div className="text-xs text-gray-500">
            {totals.totalSolar > 0 ? 
              `${displayValue(((totals.totalSolar - totals.totalGridExport) / totals.totalSolar) * 100, "0", 0)}% self-consumed` 
              : 'No solar today'}
          </div>
        </div>
        
        <div className="bg-blue-50 p-4 rounded-lg text-center border">
          <div className="text-2xl font-bold text-blue-600">{displayValue(totals.totalBatterySolarCost)}</div>
          <div className="text-sm text-gray-600">Actual Cost (SEK)</div>
          <div className="text-xs text-gray-500">With solar + battery</div>
        </div>

        <div className="bg-green-50 p-4 rounded-lg text-center border">
          <div className="text-2xl font-bold text-green-600">{displayValue(dailyView.total_daily_savings)}</div>
          <div className="text-sm text-gray-600">Total Savings (SEK)</div>
          <div className="text-xs text-gray-500">{displayValue((dailyView.total_daily_savings / totals.totalBaseCost) * 100, "0", 1)}% saved</div>
        </div>
      </div>

      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th rowSpan={2} className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border w-16">
              Hour
            </th>
            {/* Common Data Column Group */}
            <th colSpan={2} className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border bg-gray-100">
              Common Data
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border bg-blue-100 w-20">
              Grid-Only Case
            </th>
            <th colSpan={6} className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border bg-yellow-100">
              Solar-Only Case
            </th>
            <th colSpan={5} className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border bg-green-100">
              Solar+Battery Case
            </th>
          </tr>
          <tr className="bg-gray-50">
            {/* Common Data Headers */}
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border bg-gray-100 w-20">
              Price Buy/Sell
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border bg-gray-100 w-20">
              Cons.
            </th>
            
            {/* Grid-Only Headers */}
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border bg-blue-100 w-20">
              Cost
            </th>
            
            {/* Solar-Only Headers */}
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border bg-yellow-100">
              Solar
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border bg-yellow-100">
              Direct
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border bg-yellow-100">
              Import
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border bg-yellow-100">
              Export
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border bg-yellow-100">
              Cost
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border bg-yellow-100">
              Savings
            </th>
            
            {/* Solar+Battery Headers */}
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border bg-green-100">
              Action
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border bg-green-100">
              SOC
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border bg-green-100">
              Import
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border bg-green-100">
              Cost
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border bg-green-100">
              Savings
            </th>
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {dailyView.hourly_data.map((hour, index) => {
            const derived = calculateHourData(hour);
            const isActual = hour.data_source === 'actual';
            const isCurrent = hour.hour === dailyView.current_hour;
            
            // Row styling based on data source
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
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border text-center">
                  <div className="flex flex-col items-center">
                    <div>{hour.hour.toString().padStart(2, '0')}</div>
                    {isActual && (
                      <span className="text-xs bg-green-100 text-green-700 px-2 py-1 rounded mt-1">
                        Actual
                      </span>
                    )}
                    {!isActual && !isCurrent && (
                      <span className="text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded mt-1">
                        Predicted
                      </span>
                    )}
                    {isCurrent && (
                      <span className="text-xs bg-purple-100 text-purple-700 px-2 py-1 rounded mt-1">
                        Current
                      </span>
                    )}
                  </div>
                </td>
                
                {/* Common Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-gray-50 text-center">
                  <div className="font-medium">{displayValue(derived.basePrice)}</div>
                  <div className="text-xs text-gray-500">
                    {displayValue(derived.sellPrice)} sell
                  </div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-gray-50 text-center">
                  <div className="font-medium">{displayValue(hour.home_consumed, "N/A", 1)}</div>
                  <div className="text-xs text-gray-500">kWh</div>
                </td>
                
                {/* Grid-Only Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-blue-50 text-center">
                  <div className="font-medium">{displayValue(derived.baseCost)}</div>
                  <div className="text-xs text-gray-500">SEK</div>
                </td>
                
                {/* Solar-Only Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50 text-center">
                  <div className="font-medium text-yellow-600">{displayValue(hour.solar_generated, "N/A", 1)}</div>
                  <div className="text-xs text-gray-500">kWh</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50 text-center">
                  <div className="font-medium">{displayValue(derived.directSolar, "N/A", 1)}</div>
                  <div className="text-xs text-gray-500">kWh</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50 text-center">
                  <div className={`font-medium ${derived.gridImportNeeded > 0 ? 'text-red-600' : 'text-gray-400'}`}>
                    {displayValue(derived.gridImportNeeded, "N/A", 1)}
                  </div>
                  <div className="text-xs text-gray-500">kWh</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50 text-center">
                  <div className={`font-medium ${derived.solarExcess > 0 ? 'text-green-600' : 'text-gray-400'}`}>
                    {displayValue(derived.solarExcess, "N/A", 1)}
                  </div>
                  <div className="text-xs text-gray-500">kWh</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50 text-center">
                  <div className="font-medium">{displayValue(derived.solarOnlyCost)}</div>
                  <div className="text-xs text-gray-500">SEK</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50 text-center">
                  <div className={`font-medium ${derived.solarSavings > 0 ? 'text-green-600' : 'text-red-600'}`}>
                    {displayValue(derived.solarSavings)}
                  </div>
                  <div className="text-xs text-gray-500">SEK</div>
                </td>
                
                {/* Solar+Battery Data */}
                <td className="px-3 py-2 whitespace-nowrap border bg-green-50 text-center">
                  <span className={`px-2 py-1 inline-flex text-sm leading-5 font-semibold rounded-full ${
                    (hour.battery_action || 0) > 0
                      ? 'bg-green-100 text-green-800'
                      : (hour.battery_action || 0) < 0
                      ? 'bg-red-100 text-red-800'
                      : 'bg-gray-100 text-gray-800'
                  }`}>
                    {displayValue(hour.battery_action, "0.0", 1)}
                    {(hour.battery_action || 0) > 0 ? '↑' : (hour.battery_action || 0) < 0 ? '↓' : '-'}
                  </span>
                  <div className="text-xs text-gray-500">kWh</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50 text-center">
                  <div className="font-medium">{displayValue(hour.battery_soc_end, "N/A", 0)}</div>
                  <div className="text-xs text-gray-500">%</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50 text-center">
                  <div className="font-medium">{displayValue(hour.grid_imported, "N/A", 1)}</div>
                  <div className="text-xs text-gray-500">kWh</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50 text-center">
                  <div className="font-medium">{displayValue(hour.hourly_cost)}</div>
                  <div className="text-xs text-gray-500">SEK</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50 text-center">
                  <div className={`font-medium ${hour.hourly_savings > 0 ? 'text-green-600' : 'text-red-600'}`}>
                    {displayValue(hour.hourly_savings)}
                  </div>
                  <div className="text-xs text-gray-500">SEK</div>
                </td>
              </tr>
            );
          })}
          
          {/* Totals Row */}
          <tr className="bg-gray-100 font-semibold">
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border text-center">
              TOTAL
            </td>
            
            {/* Common Data Totals */}
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-gray-50 text-center">
              <span className="text-xs text-gray-500">AVG:</span> {displayValue(avgPrice)} <span className="text-xs">SEK</span>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-gray-50 text-center">
              {displayValue(totals.totalConsumption, "N/A", 1)} <span className="text-xs">kWh</span>
            </td>
            
            {/* Grid-Only Totals */}
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-blue-50 text-center">
              {displayValue(totals.totalBaseCost)} <span className="text-xs">SEK</span>
            </td>
            
            {/* Solar-Only Totals */}
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50 text-center">
              {displayValue(totals.totalSolar, "N/A", 1)} <span className="text-xs">kWh</span>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50 text-center">
              {displayValue(totals.totalDirectSolar, "N/A", 1)} <span className="text-xs">kWh</span>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50 text-center">
              {displayValue(totals.totalGridImport, "N/A", 1)} <span className="text-xs">kWh</span>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50 text-center">
              {displayValue(totals.totalSolarExcess, "N/A", 1)} <span className="text-xs">kWh</span>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50 text-center">
              {displayValue(totals.totalSolarOnlyCost)} <span className="text-xs">SEK</span>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50 text-center">
              {displayValue(totals.totalSolarSavings)} <span className="text-xs">SEK</span>
            </td>
            
            {/* Solar+Battery Totals */}
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50 text-center">
              C: {displayValue(totals.totalBatteryCharged, "N/A", 1)} <span className="text-xs">kWh</span>
              <br />
              D: {displayValue(totals.totalBatteryDischarged, "N/A", 1)} <span className="text-xs">kWh</span>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50 text-center">
              {displayValue(dailyView.hourly_data[dailyView.hourly_data.length-1]?.battery_soc_end, "-", 0)} <span className="text-xs">%</span>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50 text-center">
              {displayValue(totals.totalGridImport, "N/A", 1)} <span className="text-xs">kWh</span>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50 text-center">
              <div className="font-medium">{displayValue(totals.totalBatterySolarCost)}</div>
              <div className="text-xs text-gray-500">SEK</div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50 text-center">
              <div className={`font-medium ${totals.totalSavings > 0 ? 'text-green-600' : 'text-red-600'}`}>
                {displayValue(totals.totalSavings)}
              </div>
              <div className="text-xs text-gray-500">SEK</div>
            </td>
          </tr>
        </tbody>
      </table>
      
      {/* Summary */}
      <div className="mt-6 bg-gray-50 p-6 rounded-lg">
        <h3 className="text-xl font-semibold mb-4">Daily Summary</h3>
        
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Grid-Only Case Summary */}
          <div className="bg-white p-4 rounded-lg shadow">
            <h4 className="text-lg font-semibold mb-3 text-gray-700 flex items-center">
              <span className="w-3 h-3 bg-blue-400 rounded-full mr-2"></span>
              Grid-Only Case
            </h4>
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-gray-600">Total Consumption:</span>
                <span className="font-semibold">{displayValue(totals.totalConsumption, "N/A", 1)} kWh</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-600">Total Cost:</span>
                <span className="font-semibold">{displayValue(totals.totalBaseCost)} SEK</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-600">Average Price:</span>
                <span className="font-semibold">{displayValue(avgPrice)} SEK/kWh</span>
              </div>
            </div>
          </div>
          
          {/* Solar-Only Case Summary */}
          <div className="bg-white p-4 rounded-lg shadow">
            <h4 className="text-lg font-semibold mb-3 text-gray-700 flex items-center">
              <span className="w-3 h-3 bg-yellow-400 rounded-full mr-2"></span>
              Solar-Only Case
            </h4>
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-gray-600">Solar Produced:</span>
                <span className="font-semibold text-yellow-600">{displayValue(totals.totalSolar, "N/A", 1)} kWh</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-600">Direct Solar Use:</span>
                <span className="font-semibold text-green-600">{displayValue(totals.totalDirectSolar, "N/A", 1)} kWh</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-600">Solar Excess:</span>
                <span className="font-semibold text-blue-600">{displayValue(totals.totalSolarExcess, "N/A", 1)} kWh</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-600">Net Cost:</span>
                <span className="font-semibold">{displayValue(totals.totalSolarOnlyCost)} SEK</span>
              </div>
              <div className="flex justify-between items-center border-t pt-2">
                <span className="text-gray-600">Solar Savings:</span>
                <span className="font-semibold text-green-700">{displayValue(totals.totalSolarSavings)} SEK</span>
              </div>
            </div>
          </div>
          
          {/* Solar+Battery Case Summary */}
          <div className="bg-white p-4 rounded-lg shadow">
            <h4 className="text-lg font-semibold mb-3 text-gray-700 flex items-center">
              <span className="w-3 h-3 bg-green-400 rounded-full mr-2"></span>
              Solar+Battery Case
            </h4>
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-gray-600">Battery Charged:</span>
                <span className="font-semibold text-blue-600">{displayValue(totals.totalBatteryCharged, "N/A", 1)} kWh</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-600">Battery Discharged:</span>
                <span className="font-semibold text-purple-600">{displayValue(totals.totalBatteryDischarged, "N/A", 1)} kWh</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-600">Net Cost:</span>
                <span className="font-semibold">{displayValue(totals.totalBatterySolarCost)} SEK</span>
              </div>
              <div className="flex justify-between items-center border-t pt-2">
                <span className="text-gray-600">Total Savings:</span>
                <span className="font-semibold text-green-700">{displayValue(totals.totalSavings)} SEK</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-600">Savings %:</span>
                <span className="font-semibold text-green-700">{displayValue((totals.totalSavings / totals.totalBaseCost) * 100, "0", 1)}%</span>
              </div>
            </div>
          </div>
        </div>
        
        {/* Data Quality Info */}
        <div className="mt-6 bg-blue-50 border border-blue-200 rounded-md p-4">
          <h4 className="font-medium text-blue-800 mb-2">📊 Data Quality Information</h4>
          <div className="text-sm text-blue-700">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <span className="font-medium">Actual Hours:</span> {dailyView.actual_hours_count}
              </div>
              <div>
                <span className="font-medium">Predicted Hours:</span> {dailyView.predicted_hours_count}
              </div>
              <div>
                <span className="font-medium">Total Savings:</span> {displayValue(dailyView.total_daily_savings)} SEK
              </div>
              <div>
                <span className="font-medium">Current Hour:</span> {dailyView.current_hour}
              </div>
            </div>
            <div className="mt-2 text-xs">
              <span className="inline-block w-3 h-3 bg-green-400 rounded-full mr-1"></span>
              <span className="mr-4">Actual (historical data)</span>
              <span className="inline-block w-3 h-3 bg-gray-400 rounded-full mr-1"></span>
              <span className="mr-4">Predicted (optimization forecast)</span>
              <span className="inline-block w-3 h-3 bg-purple-400 rounded-full mr-1"></span>
              <span>Current hour</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};