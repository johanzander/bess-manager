import React, { useState, useEffect } from 'react';
import api from '../lib/api';

interface DetailedSavingsAnalysisProps {
  settings: any;
}

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
  electricityPrice: number;
  electricitySellPrice: number;
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

export const DetailedSavingsAnalysis: React.FC<DetailedSavingsAnalysisProps> = ({ settings }) => {
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

  const displayValue = (value: number | string | null | undefined, fallback = "N/A", decimals = 2): string => {
    if (value === null || value === undefined || value === "" || (typeof value === 'number' && isNaN(value))) {
      return fallback;
    }
    if (typeof value === 'string') return value;
    return Number(value).toFixed(decimals);
  };

  const calculateHourData = (hour: DashboardHourlyData) => {
    const basePrice = hour.electricityPrice + (settings.markupRate * hour.electricityPrice) + settings.additionalCosts;
    const sellPrice = hour.electricitySellPrice || hour.electricityPrice * 0.7;
    const baseCost = hour.homeConsumed * basePrice;
    
    // Solar-only calculations
    const directSolar = Math.min(hour.solarGenerated, hour.homeConsumed);
    const gridImportNeeded = Math.max(0, hour.homeConsumed - directSolar);
    const solarExcess = Math.max(0, hour.solarGenerated - hour.homeConsumed);
    const solarOnlyCost = (gridImportNeeded * basePrice) - (solarExcess * sellPrice);
    const solarSavings = baseCost - solarOnlyCost;
    
    // Battery+Solar cost (actual from data)
    const batterySolarCost = (hour.gridImported * basePrice) - (hour.gridExported * sellPrice);
    const totalSavings = baseCost - batterySolarCost;

    return {
      basePrice,
      sellPrice,
      baseCost,
      directSolar,
      gridImportNeeded,
      solarExcess,
      solarOnlyCost,
      solarSavings,
      batterySolarCost,
      totalSavings
    };
  };

  // Calculate totals
  const totals = dashboardData.hourlyData.reduce((acc: any, hour: DashboardHourlyData) => {
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
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow overflow-x-auto">
      <div className="mb-6">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">Detailed Financial Analysis</h2>
        <p className="text-sm text-gray-600 dark:text-gray-300 mb-4">
          Comprehensive comparison of three scenarios: Grid-only (baseline), Solar-only (without battery), and Solar+Battery (optimized).
          All monetary values in SEK. Energy values in kWh.
        </p>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-gray-50 dark:bg-gray-700 p-4 rounded-lg text-center border border-gray-200 dark:border-gray-600">
          <div className="text-2xl font-bold text-gray-600 dark:text-gray-300">{displayValue(totals.totalBaseCost)}</div>
          <div className="text-sm text-gray-600 dark:text-gray-300">Grid-Only Cost (SEK)</div>
          <div className="text-xs text-gray-500 dark:text-gray-400">Baseline without solar</div>
        </div>
        
        <div className="bg-yellow-50 dark:bg-yellow-900/20 p-4 rounded-lg text-center border border-yellow-200 dark:border-yellow-800">
          <div className="text-2xl font-bold text-yellow-600 dark:text-yellow-400">{displayValue(totals.totalSolarOnlyCost)}</div>
          <div className="text-sm text-gray-600 dark:text-gray-300">Solar-Only Cost (SEK)</div>
          <div className="text-xs text-gray-500 dark:text-gray-400">
            {totals.totalSolar > 0 ? 
              `${displayValue(((totals.totalSolar - totals.totalGridExport) / totals.totalSolar) * 100, "0", 0)}% self-consumed` 
              : 'No solar today'}
          </div>
        </div>
        
        <div className="bg-blue-50 dark:bg-blue-900/20 p-4 rounded-lg text-center border border-blue-200 dark:border-blue-800">
          <div className="text-2xl font-bold text-blue-600 dark:text-blue-400">{displayValue(totals.totalBatterySolarCost)}</div>
          <div className="text-sm text-gray-600 dark:text-gray-300">Actual Cost (SEK)</div>
          <div className="text-xs text-gray-500 dark:text-gray-400">With solar + battery</div>
        </div>

        <div className="bg-green-50 dark:bg-green-900/20 p-4 rounded-lg text-center border border-green-200 dark:border-green-800">
          <div className="text-2xl font-bold text-green-600 dark:text-green-400">{displayValue(dashboardData.totalDailySavings)}</div>
          <div className="text-sm text-gray-600 dark:text-gray-300">Total Savings (SEK)</div>
          <div className="text-xs text-gray-500 dark:text-gray-400">{displayValue((dashboardData.totalDailySavings / totals.totalBaseCost) * 100, "0", 1)}% saved</div>
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
            <th colSpan={5} className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30">
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
              SOC
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
          </tr>
        </thead>
        <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
          {dashboardData.hourlyData.map((hour: DashboardHourlyData, index: number) => {
            const derived = calculateHourData(hour);
            const isCurrentHour = hour.hour === dashboardData.currentHour;
            
            return (
              <tr key={index} className={`${
                isCurrentHour ? 'bg-blue-100 dark:bg-blue-900/20' : 
                hour.isActual ? 'bg-gray-100 dark:bg-gray-700' : 'bg-white dark:bg-gray-800'
              }`}>
                <td className="px-3 py-2 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                  <div>
                    {hour.hour.toString().padStart(2, '0')}:00
                    {isCurrentHour && <span className="block text-xs text-blue-600 dark:text-blue-400 font-normal">Current</span>}
                    {!isCurrentHour && !hour.isActual && <span className="block text-xs text-gray-500 dark:text-gray-400 font-normal">Pred.</span>}
                  </div>
                </td>
                
                {/* Common Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-center">
                  <div className="font-medium">{displayValue(derived.basePrice)}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">
                    {displayValue(derived.sellPrice)} sell
                  </div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-center">
                  <div className="font-medium">{displayValue(hour.homeConsumed, "N/A", 1)}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
                </td>
                
                {/* Grid-Only Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-blue-50 dark:bg-blue-900/20 text-center">
                  <div className="font-medium">{displayValue(derived.baseCost)}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">SEK</div>
                </td>
                
                {/* Solar-Only Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-50 dark:bg-yellow-900/20 text-center">
                  <div className="font-medium text-yellow-600 dark:text-yellow-400">{displayValue(hour.solarGenerated, "N/A", 1)}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-50 dark:bg-yellow-900/20 text-center">
                  <div className="font-medium">{displayValue(derived.directSolar, "N/A", 1)}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-50 dark:bg-yellow-900/20 text-center">
                  <div className={`font-medium ${derived.gridImportNeeded > 0 ? 'text-red-600 dark:text-red-400' : 'text-gray-400 dark:text-gray-500'}`}>
                    {displayValue(derived.gridImportNeeded, "N/A", 1)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-50 dark:bg-yellow-900/20 text-center">
                  <div className={`font-medium ${derived.solarExcess > 0 ? 'text-green-600 dark:text-green-400' : 'text-gray-400 dark:text-gray-500'}`}>
                    {displayValue(derived.solarExcess, "N/A", 1)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-50 dark:bg-yellow-900/20 text-center">
                  <div className="font-medium">{displayValue(derived.solarOnlyCost)}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">SEK</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-50 dark:bg-yellow-900/20 text-center">
                  <div className={`font-medium ${
                    derived.solarSavings > 0 ? 'text-green-600 dark:text-green-400' : 
                    derived.solarSavings < 0 ? 'text-red-600 dark:text-red-400' : 'text-gray-600 dark:text-gray-400'
                  }`}>
                    {derived.solarSavings > 0 ? '+' : ''}{displayValue(derived.solarSavings)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">SEK</div>
                </td>
                
                {/* Solar+Battery Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-50 dark:bg-green-900/20 text-center">
                  <div className={`font-medium ${
                    typeof hour.batteryAction === 'number' && hour.batteryAction > 0.01 ? 'text-green-600 dark:text-green-400' :
                    typeof hour.batteryAction === 'number' && hour.batteryAction < -0.01 ? 'text-red-600 dark:text-red-400' :
                    'text-gray-600 dark:text-gray-400'
                  }`}>
                    {typeof hour.batteryAction === 'number' ? 
                      (Math.abs(hour.batteryAction) < 0.01 ? '0.0' :
                       hour.batteryAction > 0 ? `+${hour.batteryAction.toFixed(1)}` : 
                       hour.batteryAction.toFixed(1)) : 
                      hour.batteryAction || '0.0'}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-50 dark:bg-green-900/20 text-center">
                  <div className="font-medium">{displayValue(hour.batterySocEnd, "N/A", 0)}%</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">SOC</div>
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
                  <div className="font-medium">{displayValue(derived.batterySolarCost)}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">SEK</div>
                </td>
              </tr>
            );
          })}
          
          {/* Totals Row */}
          <tr className="bg-gray-200 dark:bg-gray-600 font-bold border-t-2 border-gray-400 dark:border-gray-500">
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
              TOTAL
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-gray-100 dark:bg-gray-600 text-center">
              -
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-gray-100 dark:bg-gray-600 text-center">
              {displayValue(totals.totalConsumption, "N/A", 1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-blue-100 dark:bg-blue-900/30 text-center">
              {displayValue(totals.totalBaseCost)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30 text-center">
              {displayValue(totals.totalSolar, "N/A", 1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30 text-center">
              -
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30 text-center">
              {displayValue(totals.totalGridImport, "N/A", 1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30 text-center">
              {displayValue(totals.totalGridExport, "N/A", 1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30 text-center">
              {displayValue(totals.totalSolarOnlyCost)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-yellow-100 dark:bg-yellow-900/30 text-center">
              <span className={totals.totalSolarSavings > 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}>
                {totals.totalSolarSavings > 0 ? '+' : ''}{displayValue(totals.totalSolarSavings)}
              </span>
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30 text-center">
              -
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30 text-center">
              -
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30 text-center">
              {displayValue(totals.totalGridImport, "N/A", 1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30 text-center">
              {displayValue(totals.totalGridExport, "N/A", 1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 bg-green-100 dark:bg-green-900/30 text-center">
              {displayValue(totals.totalBatterySolarCost)}
            </td>
          </tr>
        </tbody>
      </table>

      {/* Analysis Notes */}
      <div className="mt-6 text-sm text-gray-600 dark:text-gray-300 space-y-2">
        <p><strong>Reading the Table:</strong></p>
        <ul className="list-disc list-inside space-y-1 ml-4">
          <li><strong>Blue highlight:</strong> Current hour being executed</li>
          <li><strong>Gray rows:</strong> Historical actual data</li>
          <li><strong>White rows:</strong> Predicted future hours</li>
          <li><strong>Common Data:</strong> Basic hourly electricity prices and home consumption</li>
          <li><strong>Grid-Only:</strong> Cost if no solar panels existed (baseline)</li>
          <li><strong>Solar-Only:</strong> Cost with solar but no battery storage</li>
          <li><strong>Solar+Battery:</strong> Actual optimized scenario with battery storage</li>
        </ul>
      </div>
    </div>
  );
};