import React, { useState, useEffect } from 'react';
import api from '../lib/api';

interface DetailedSavingsAnalysisProps {
  settings: any;
}

interface DashboardHourlyData {
  hour: number;
  dataSource: 'actual' | 'predicted';
  // Using canonical camelCase field names:
  solarProduction: number;
  homeConsumption: number;
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
  batteryAction: number;
  isActual: boolean;
  isPredicted: boolean;
  
  // Values calculated on the backend
  gridOnlyCost: number;  // Updated name
  directSolar: number;
  gridImportNeeded: number;
  solarExcess: number;
  solarOnlyCost: number;
  solarSavings: number;
  batterySolarCost: number;
  batterySavings: number;
}

interface DashboardTotals {
  totalSolarProduction: number;
  totalHomeConsumption: number;
  totalGridImport: number;
  totalGridExport: number;
  totalBatteryCharged: number;
  totalBatteryDischarged: number;
  totalGridOnlyCost: number;  // Updated name
  totalSolarOnlyCost: number;
  totalBatterySolarCost: number;
  totalSolarSavings: number;
  totalBatterySavings: number;
  totalOptimizationSavings: number;
}

interface DashboardSummary {
  gridOnlyCost: number;
  solarOnlyCost: number;
  optimizedCost: number;
  totalGridCost: number;
  totalBatteryCycleCost: number;
  totalSavings: number;
  solarSavings: number;
  batterySavings: number;
  totalSolarProduction: number;
  totalHomeConsumption: number;
  totalBatteryCharged: number;
  totalBatteryDischarged: number;
  totalGridImported: number;
  totalGridExported: number;
  cycleCount: number;
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
  batteryCapacity?: number;
  totals: DashboardTotals;
  summary: DashboardSummary;
}

export const DetailedSavingsAnalysis: React.FC<DetailedSavingsAnalysisProps> = ({ }) => {
  const [dashboardData, setDashboardData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  // Helper function to safely display numeric values
  const displayValue = (value: number | string | null | undefined, fallback = "N/A", decimals = 2): string => {
    if (value === null || value === undefined || value === "" || (typeof value === 'number' && isNaN(value))) {
      return fallback;
    }
    if (typeof value === 'string') return value;
    return Number(value).toFixed(decimals);
  };

  // Get data from the backend totals
  const totals = dashboardData.totals;
  
  // Use backend-calculated total optimization savings instead of calculating in frontend
  const totalDailySavings = totals.totalOptimizationSavings;

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
            <div className="text-2xl font-bold text-gray-900 dark:text-white">
              {displayValue(totals.totalGridOnlyCost)} <span className="text-sm font-medium text-gray-600 dark:text-gray-400">SEK</span>
            </div>
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
            <div className="text-2xl font-bold text-gray-900 dark:text-white">
              {displayValue(totals.totalSolarOnlyCost)} <span className="text-sm font-medium text-gray-600 dark:text-gray-400">SEK</span>
            </div>
            <div className="text-sm text-gray-600 dark:text-gray-300">Solar-Only Cost</div>
            <div className="flex justify-between items-center mt-2 border-t border-yellow-200 dark:border-yellow-800 pt-2">
              <div className="text-left text-xs text-gray-600 dark:text-gray-300">Solar savings:</div>
              <div className="text-right text-xs font-medium text-green-600 dark:text-green-400">{displayValue(totals.totalSolarSavings)} <span className="text-xs font-normal text-gray-600 dark:text-gray-400">SEK</span></div>
            </div>
            <div className="flex justify-between items-center">
              <div className="text-left text-xs text-gray-600 dark:text-gray-300">% Saved:</div>
              <div className="text-right text-xs font-medium text-gray-700 dark:text-gray-200">{displayValue(((totals.totalSolarSavings / totals.totalGridOnlyCost) * 100), "0", 1)}%</div>
            </div>
            <div className="flex justify-between items-center">
              <div className="text-left text-xs text-gray-600 dark:text-gray-300">Self-consumption:</div>
              <div className="text-right text-xs font-medium text-gray-700 dark:text-gray-200">{displayValue((totals.totalSolarProduction / totals.totalHomeConsumption) * 100, "0", 0)}%</div>
            </div>
          </div>
          
          {/* Solar+Battery Card */}
          <div className="bg-green-50 dark:bg-green-900/20 p-4 rounded-lg shadow border border-green-200 dark:border-green-800">
            <div className="flex items-center justify-center mb-1">
              <div className="px-2 py-1 bg-green-200 dark:bg-green-800 text-green-800 dark:text-green-200 rounded text-xs font-medium">SOLAR+BATTERY</div>
            </div>
            <div className="text-2xl font-bold text-gray-900 dark:text-white">
              {displayValue(totals.totalBatterySolarCost)} <span className="text-sm font-medium text-gray-600 dark:text-gray-400">SEK</span>
            </div>
            <div className="text-sm text-gray-600 dark:text-gray-300">Optimized Cost</div>
            <div className="flex justify-between items-center mt-2 border-t border-green-200 dark:border-green-800 pt-2">
              <div className="text-left text-xs text-gray-600 dark:text-gray-300">Total savings:</div>
              <div className="text-right text-xs font-medium text-green-600 dark:text-green-400">{displayValue(totalDailySavings)} <span className="text-xs font-normal text-gray-600 dark:text-gray-400">SEK</span></div>
            </div>
            <div className="flex justify-between items-center">
              <div className="text-left text-xs text-gray-600 dark:text-gray-300">% Saved:</div>
              <div className="text-right text-xs font-medium text-gray-700 dark:text-gray-200">{displayValue(((totalDailySavings / totals.totalGridOnlyCost) * 100), "0", 1)}%</div>
            </div>
            <div className="flex justify-between items-center">
              <div className="text-left text-xs text-gray-600 dark:text-gray-300">Battery contribution:</div>
              <div className="text-right text-xs font-medium text-green-600 dark:text-green-400">{displayValue(dashboardData.summary.batterySavings)} <span className="text-xs font-normal text-gray-600 dark:text-gray-400">SEK</span></div>
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
        <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
          {dashboardData.hourlyData.map((hour, index) => {
            const batteryAction = typeof hour.batteryAction === 'number' ? hour.batteryAction : 0;
            const batterySoc = hour.batterySocEnd;
            
            return (
              <tr key={index} className="hover:bg-gray-50 dark:hover:bg-gray-700">
                <td className="px-3 py-2 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                  {String(hour.hour || index).padStart(2, '0')}:00
                  <div className="text-xs text-gray-500 dark:text-gray-400">
                    {hour.dataSource || 'predicted'}
                  </div>
                </td>
                
                {/* Common Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-center">
                  <div className="font-medium">{displayValue(hour.buyPrice, "N/A", 3)}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">
                    {displayValue(hour.sellPrice, "N/A", 3)} sell
                  </div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-center">
                  <div className="font-medium">{displayValue(hour.homeConsumption, "N/A", 1)}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
                </td>
                
                {/* Grid-Only Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-blue-50 dark:bg-blue-900/20 text-center">
                  <div className={`font-medium ${
                    Math.abs(hour.gridOnlyCost) < 0.01 ? 'text-gray-900 dark:text-white' : 
                    hour.gridOnlyCost > 0 ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'
                  }`}>
                    {displayValue(hour.gridOnlyCost)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">SEK</div>
                </td>
                
                {/* Solar-Only Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-50 dark:bg-yellow-900/20 text-center">
                  <div className="font-medium text-yellow-600 dark:text-yellow-400">{displayValue(hour.solarProduction, "N/A", 1)}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-50 dark:bg-yellow-900/20 text-center">
                  <div className="font-medium">{displayValue(hour.directSolar, "N/A", 1)}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-50 dark:bg-yellow-900/20 text-center">
                  <div className={`font-medium ${hour.gridImportNeeded > 0 ? 'text-red-600 dark:text-red-400' : 'text-gray-400 dark:text-gray-500'}`}>
                    {displayValue(hour.gridImportNeeded, "N/A", 1)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-50 dark:bg-yellow-900/20 text-center">
                  <div className={`font-medium ${hour.solarExcess > 0 ? 'text-green-600 dark:text-green-400' : 'text-gray-400 dark:text-gray-500'}`}>
                    {displayValue(hour.solarExcess, "N/A", 1)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-50 dark:bg-yellow-900/20 text-center">
                  <div className={`font-medium ${
                    Math.abs(hour.solarOnlyCost) < 0.01 ? 'text-gray-900 dark:text-white' : 
                    hour.solarOnlyCost > 0 ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'
                  }`}>
                    {displayValue(hour.solarOnlyCost)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">SEK</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-50 dark:bg-yellow-900/20 text-center">
                  <div className={`font-medium ${
                    Math.abs(hour.solarSavings) < 0.01 ? 'text-gray-900 dark:text-white' : 
                    hour.solarSavings > 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
                  }`}>
                    {Math.abs(hour.solarSavings) < 0.01 ? '0.00' : displayValue(hour.solarSavings)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">SEK</div>
                </td>
                
                {/* Solar+Battery Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-50 dark:bg-green-900/20 text-center">
                  <div className={`font-medium ${batteryAction > 0 ? 'text-blue-600 dark:text-blue-400' : batteryAction < 0 ? 'text-orange-600 dark:text-orange-400' : 'text-gray-500 dark:text-gray-400'}`}>
                    {batteryAction > 0 ? '+' : ''}{displayValue(batteryAction, "0.0", 1)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-50 dark:bg-green-900/20 text-center">
                  <div className="font-medium">{displayValue(batterySoc, "N/A", 0)}%</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">
                    {displayValue((batterySoc / 100) * (dashboardData.batteryCapacity || 10), "N/A", 1)} kWh
                  </div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-50 dark:bg-green-900/20 text-center">
                  <div className={`font-medium ${hour.gridImported > 0 ? 'text-red-600 dark:text-red-400' : 'text-gray-400 dark:text-gray-500'}`}>
                    {displayValue(hour.gridImported, "N/A", 1)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-50 dark:bg-green-900/20 text-center">
                  <div className={`font-medium ${hour.gridExported > 0 ? 'text-green-600 dark:text-green-400' : 'text-gray-400 dark:text-gray-500'}`}>
                    {displayValue(hour.gridExported, "N/A", 1)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-50 dark:bg-green-900/20 text-center">
                  <div className={`font-medium ${
                    Math.abs(hour.batterySolarCost) < 0.01 ? 'text-gray-900 dark:text-white' : 
                    hour.batterySolarCost > 0 ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'
                  }`}>
                    {displayValue(hour.batterySolarCost)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">SEK</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-50 dark:bg-green-900/20 text-center">
                  <div className={`font-medium ${
                    Math.abs(hour.gridOnlyCost - hour.batterySolarCost) < 0.01 ? 'text-gray-900 dark:text-white' : 
                    (hour.gridOnlyCost - hour.batterySolarCost) > 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
                  }`}>
                    {Math.abs(hour.gridOnlyCost - hour.batterySolarCost) < 0.01 ? '0.00' : displayValue(hour.gridOnlyCost - hour.batterySolarCost)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">SEK</div>
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
              <div className="font-medium">{displayValue(totals.totalHomeConsumption, "N/A", 1)}</div>
              <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-blue-100 dark:bg-blue-900/30 text-center">
              <div className={`font-medium ${
                Math.abs(totals.totalGridOnlyCost) < 0.01 ? 'text-gray-900 dark:text-white' : 
                totals.totalGridOnlyCost > 0 ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'
              }`}>
                {displayValue(totals.totalGridOnlyCost)}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">SEK</div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30 text-center">
              <div className="font-medium">{displayValue(totals.totalSolarProduction, "N/A", 1)}</div>
              <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30 text-center">
              -
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30 text-center">
              <div className="font-medium">{displayValue(totals.totalGridImport, "N/A", 1)}</div>
              <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30 text-center">
              <div className="font-medium">{displayValue(totals.totalGridExport, "N/A", 1)}</div>
              <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30 text-center">
              <div className={`font-medium ${
                Math.abs(totals.totalSolarOnlyCost) < 0.01 ? 'text-gray-900 dark:text-white' : 
                totals.totalSolarOnlyCost > 0 ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'
              }`}>
                {displayValue(totals.totalSolarOnlyCost)}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">SEK</div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30 text-center">
              <div className={`font-medium ${
                Math.abs(totals.totalSolarSavings) < 0.01 ? 'text-gray-900 dark:text-white' : 
                totals.totalSolarSavings > 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
              }`}>
                {displayValue(totals.totalSolarSavings)}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">SEK</div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30 text-center">
              <div className="flex flex-col items-center">
                <div className="text-xs mb-1 text-blue-600 dark:text-blue-400">
                  +{displayValue(totals.totalBatteryCharged)} kWh
                </div>
                <div className="text-xs text-orange-600 dark:text-orange-400">
                  -{displayValue(totals.totalBatteryDischarged)} kWh
                </div>
              </div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30 text-center">
              -
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30 text-center">
              <div className="font-medium">{displayValue(totals.totalGridImport, "N/A", 1)}</div>
              <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30 text-center">
              <div className="font-medium">{displayValue(totals.totalGridExport, "N/A", 1)}</div>
              <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30 text-center">
              <div className={`font-medium ${
                Math.abs(totals.totalBatterySolarCost) < 0.01 ? 'text-gray-900 dark:text-white' : 
                totals.totalBatterySolarCost > 0 ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'
              }`}>
                {displayValue(totals.totalBatterySolarCost)}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">SEK</div>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30 text-center">
              <div className={`font-medium ${
                Math.abs(totals.totalOptimizationSavings) < 0.01 ? 'text-gray-900 dark:text-white' : 
                totals.totalOptimizationSavings > 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
              }`}>
                {displayValue(totals.totalOptimizationSavings)}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">SEK</div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
};