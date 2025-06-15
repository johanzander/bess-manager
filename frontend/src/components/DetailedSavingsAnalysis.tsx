import React, { useState, useEffect } from 'react';
import { BatterySettings } from '../types';
import api from '../lib/api';

// Updated interface based on consolidated dashboard API
interface DashboardHourlyData {
  hour: number;
  dataSource: 'actual' | 'predicted';
  solarGenerated: number;
  homeConsumed: number;
  gridImported: number;
  gridExported: number;
  batteryCharged: number;
  batteryDischarged: number;
  batterySocStart: number;
  batterySocEnd: number;
  buyPrice: number;
  sellPrice: number;
  hourlyCost: number;
  hourlySavings: number;
  batteryAction: number | string;
  isActual: boolean;
  isPredicted: boolean;
}

interface DashboardResponse {
  date: string;
  currentHour: number;
  totalDailySavings: number;
  actualSavingsSoFar: number;
  predictedRemainingSavings: number;
  actualHoursCount: number;
  predictedHoursCount: number;
  hourlyData: DashboardHourlyData[];
}

interface BatteryScheduleTableProps {
  settings: BatterySettings;
}

export const DetailedSavingsAnalysis: React.FC<BatteryScheduleTableProps> = ({
}) => {
  const [dashboardData, setDashboardData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch data using the new consolidated dashboard API
  useEffect(() => {
    const fetchDashboardData = async () => {
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

    fetchDashboardData();
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
  const calculateHourData = (hour: DashboardHourlyData) => {
    // Use actual prices from backend (no frontend calculation!)
    const basePrice = hour.buyPrice;
    const sellPrice = hour.sellPrice ; // fallback only if missing
    
    // Calculate base cost (grid-only scenario)
    const baseCost = hour.homeConsumed * basePrice;
    
    // Calculate solar-only scenario
    const directSolar = Math.min(hour.homeConsumed, hour.solarGenerated);
    const solarExcess = Math.max(0, hour.solarGenerated - directSolar);
    const gridImportNeeded = Math.max(0, hour.homeConsumed - directSolar);
    const solarOnlyCost = gridImportNeeded * basePrice - solarExcess * sellPrice;
    const solarSavings = baseCost - solarOnlyCost;
    
    // Battery+Solar scenario (actual costs from optimization)
    const batterySolarCost = hour.hourlyCost;
    const totalSavings = hour.hourlySavings;
    
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
          <span className="ml-2">Loading detailed analysis...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white p-6 rounded-lg shadow">
        <div className="bg-red-50 border border-red-200 rounded-md p-4">
          <h3 className="text-red-800 font-medium">Error Loading Data</h3>
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

  if (!dashboardData) {
    return (
      <div className="bg-white p-6 rounded-lg shadow">
        <div className="text-center text-gray-500">No data available</div>
      </div>
    );
  }

  // Calculate totals for summary row
  const totals = dashboardData.hourlyData.reduce((acc, hour) => {
    const derived = calculateHourData(hour);
    return {
      totalConsumption: acc.totalConsumption + hour.homeConsumed,
      totalSolar: acc.totalSolar + hour.solarGenerated,
      totalGridImport: acc.totalGridImport + hour.gridImported,
      totalGridExport: acc.totalGridExport + hour.gridExported,
      totalBaseCost: acc.totalBaseCost + derived.baseCost,
      totalSolarOnlyCost: acc.totalSolarOnlyCost + derived.solarOnlyCost,
      totalSolarSavings: acc.totalSolarSavings + derived.solarSavings,
      totalBatterySolarCost: acc.totalBatterySolarCost + derived.batterySolarCost,
      totalOptimizationSavings: acc.totalOptimizationSavings + derived.totalSavings,
    };
  }, {
    totalConsumption: 0,
    totalSolar: 0,
    totalGridImport: 0,
    totalGridExport: 0,
    totalBaseCost: 0,
    totalSolarOnlyCost: 0,
    totalSolarSavings: 0,
    totalBatterySolarCost: 0,
    totalOptimizationSavings: 0,
  });

  return (
    <div className="bg-white p-6 rounded-lg shadow overflow-x-auto">
      <div className="mb-6">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">Detailed Financial Analysis</h2>
        <p className="text-sm text-gray-600 mb-4">
          Comprehensive comparison of three scenarios: Grid-only (baseline), Solar-only (without battery), and Solar+Battery (optimized).
          All monetary values in SEK. Energy values in kWh.
        </p>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-gray-50 p-4 rounded-lg text-center border">
          <div className="text-2xl font-bold text-gray-600">{displayValue(totals.totalBaseCost)}</div>
          <div className="text-sm text-gray-600">Grid-Only Cost (SEK)</div>
          <div className="text-xs text-gray-500">Baseline without solar</div>
        </div>
        
        <div className="bg-yellow-50 p-4 rounded-lg text-center border">
          <div className="text-2xl font-bold text-yellow-600">{displayValue(totals.totalSolarOnlyCost)}</div>
          <div className="text-sm text-gray-600">Solar-Only Cost (SEK)</div>
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
          <div className="text-2xl font-bold text-green-600">{displayValue(dashboardData.totalDailySavings)}</div>
          <div className="text-sm text-gray-600">Total Savings (SEK)</div>
          <div className="text-xs text-gray-500">{displayValue((dashboardData.totalDailySavings / totals.totalBaseCost) * 100, "0", 1)}% saved</div>
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
              Export
            </th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border bg-green-100">
              Cost
            </th>
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {dashboardData.hourlyData.map((hour, index) => {
            const derived = calculateHourData(hour);
            const isCurrentHour = hour.hour === dashboardData.currentHour;
            
            return (
              <tr key={index} className={`${
                isCurrentHour ? 'bg-blue-100' : 
                hour.isActual ? 'bg-gray-100' : 'bg-white'
              }`}>
                <td className="px-3 py-2 whitespace-nowrap text-sm font-medium text-gray-900 border text-center">
                  <div>
                    {hour.hour.toString().padStart(2, '0')}:00
                    {isCurrentHour && <span className="block text-xs text-blue-600 font-normal">Current</span>}
                    {!isCurrentHour && !hour.isActual && <span className="block text-xs text-gray-500 font-normal">Pred.</span>}
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
                  <div className="font-medium">{displayValue(hour.homeConsumed, "N/A", 1)}</div>
                  <div className="text-xs text-gray-500">kWh</div>
                </td>
                
                {/* Grid-Only Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-blue-50 text-center">
                  <div className="font-medium">{displayValue(derived.baseCost)}</div>
                  <div className="text-xs text-gray-500">SEK</div>
                </td>
                
                {/* Solar-Only Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50 text-center">
                  <div className="font-medium text-yellow-600">{displayValue(hour.solarGenerated, "N/A", 1)}</div>
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
                  <div className={`font-medium ${
                    derived.solarSavings > 0 ? 'text-green-600' : 
                    derived.solarSavings < 0 ? 'text-red-600' : 'text-gray-600'
                  }`}>
                    {derived.solarSavings > 0 ? '+' : ''}{displayValue(derived.solarSavings)}
                  </div>
                  <div className="text-xs text-gray-500">SEK</div>
                </td>
                
                {/* Solar+Battery Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50 text-center">
                  <div className={`font-medium ${
                    typeof hour.batteryAction === 'number' && hour.batteryAction > 0.01 ? 'text-green-600' :
                    typeof hour.batteryAction === 'number' && hour.batteryAction < -0.01 ? 'text-red-600' :
                    'text-gray-600'
                  }`}>
                    {typeof hour.batteryAction === 'number' ? 
                      (Math.abs(hour.batteryAction) < 0.01 ? '0.0' :
                       hour.batteryAction > 0 ? `+${hour.batteryAction.toFixed(1)}` : 
                       hour.batteryAction.toFixed(1)) : 
                      hour.batteryAction || '0.0'}
                  </div>
                  <div className="text-xs text-gray-500">kWh</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50 text-center">
                  <div className="font-medium">{displayValue(hour.batterySocEnd, "N/A", 0)}%</div>
                  <div className="text-xs text-gray-500">SOC</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50 text-center">
                  <div className={`font-medium ${hour.gridImported > 0 ? 'text-red-600' : 'text-gray-400'}`}>
                    {displayValue(hour.gridImported, "N/A", 1)}
                  </div>
                  <div className="text-xs text-gray-500">kWh</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50 text-center">
                  <div className={`font-medium ${hour.gridExported > 0 ? 'text-green-600' : 'text-gray-400'}`}>
                    {displayValue(hour.gridExported, "N/A", 1)}
                  </div>
                  <div className="text-xs text-gray-500">kWh</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50 text-center">
                  <div className="font-medium">{displayValue(derived.batterySolarCost)}</div>
                  <div className="text-xs text-gray-500">SEK</div>
                </td>
              </tr>
            );
          })}
          
          {/* Totals Row */}
          <tr className="bg-gray-200 font-bold border-t-2">
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border text-center">
              TOTAL
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-gray-100 text-center">
              -
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-gray-100 text-center">
              {displayValue(totals.totalConsumption, "N/A", 1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-blue-100 text-center">
              {displayValue(totals.totalBaseCost)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-100 text-center">
              {displayValue(totals.totalSolar, "N/A", 1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-100 text-center">
              -
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-100 text-center">
              {displayValue(totals.totalGridImport, "N/A", 1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-100 text-center">
              {displayValue(totals.totalGridExport, "N/A", 1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-100 text-center">
              {displayValue(totals.totalSolarOnlyCost)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-100 text-center">
              <span className={totals.totalSolarSavings > 0 ? 'text-green-600' : 'text-red-600'}>
                {totals.totalSolarSavings > 0 ? '+' : ''}{displayValue(totals.totalSolarSavings)}
              </span>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-100 text-center">
              -
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-100 text-center">
              -
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-100 text-center">
              {displayValue(totals.totalGridImport, "N/A", 1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-100 text-center">
              {displayValue(totals.totalGridExport, "N/A", 1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-100 text-center">
              {displayValue(totals.totalBatterySolarCost)}
            </td>
          </tr>
        </tbody>
      </table>

      {/* Explanation */}
      <div className="mt-4 p-4 bg-gray-50 rounded-lg text-sm">
        <h4 className="font-medium text-gray-900 mb-2">Table Explanation:</h4>
        <p className="text-gray-600">
          <strong>Grid-Only:</strong> Cost if using only grid power without solar panels. 
          <strong>Solar-Only:</strong> Cost with solar panels but no battery optimization - excess solar is exported at lower price.
          <strong>Solar+Battery:</strong> Actual optimized system with battery charging/discharging to minimize costs.
          Battery actions: <span className="bg-green-100 text-green-800 px-1 rounded">green = charging</span>, 
          <span className="bg-red-100 text-red-800 px-1 rounded">red = discharging</span>.
        </p>
      </div>
    </div>
  );
};