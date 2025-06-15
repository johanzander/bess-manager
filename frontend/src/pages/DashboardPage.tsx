import { useState, useEffect } from 'react';
import { BatteryLevelChart } from '../components/BatteryLevelChart';
import { EnergyFlowChart } from '../components/EnergyFlowChart';
import { EnergySankeyChart } from '../components/EnergySankeyChart';
import { BatterySettings, ElectricitySettings, ScheduleData } from '../types';
import { Clock, AlertCircle } from 'lucide-react';
import ConsolidatedEnergyCards from '../components/ConsolidatedEnergyCards';
import api from '../lib/api';

interface DashboardProps {
  onLoadingChange: (loading: boolean) => void;
  settings: BatterySettings & ElectricitySettings;
}

export default function DashboardPage({
  onLoadingChange,
  settings
}: DashboardProps) {
  const [dashboardData, setDashboardData] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());
  const [debugInfo, setDebugInfo] = useState<string[]>([]);
  const [showDebug, setShowDebug] = useState(false);

  const fetchData = async (isManualRefresh = false) => {
    onLoadingChange(true);
    setError(null);

    const debugMessages: string[] = [];
    debugMessages.push(`🔄 Fetching dashboard data... (${isManualRefresh ? 'manual' : 'auto'})`);

    try {
      // Clear existing data
      setDashboardData(null);

      // Single unified API call (was already correct)
      debugMessages.push(`📡 Calling unified /api/dashboard endpoint...`);
      const response = await api.get('/api/dashboard');
      
      if (response?.data) {
        setDashboardData(response.data);
        
        const hourlyDataCount = response.data.hourlyData?.length || 0;
        const actualCount = response.data.actualHoursCount || 0;
        const predictedCount = response.data.predictedHoursCount || 0;
        
        debugMessages.push(`✅ Dashboard data loaded successfully`);
        debugMessages.push(`📊 Total hours: ${hourlyDataCount} (${actualCount} actual + ${predictedCount} predicted)`);
        debugMessages.push(`💰 Daily savings: ${response.data.totalDailySavings?.toFixed(2) || 'N/A'} SEK`);
        debugMessages.push(`🔋 Battery capacity: ${response.data.batteryCapacity || 'N/A'} kWh`);
        
        // Log strategic intent summary if available
        if (response.data.strategicIntentSummary) {
          const intents = Object.entries(response.data.strategicIntentSummary)
            .map(([intent, count]) => `${intent}: ${count}`)
            .join(', ');
          debugMessages.push(`🎯 Strategic intents: ${intents}`);
        }
      } else {
        throw new Error('No data received from dashboard endpoint');
      }

      setLastUpdate(new Date());
      debugMessages.push(`✅ Data fetch completed at ${new Date().toLocaleTimeString()}`);

    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Unknown error';
      setError(`Failed to load dashboard data: ${errorMessage}`);
      debugMessages.push(`❌ Critical error: ${errorMessage}`);
    } finally {
      setDebugInfo(debugMessages);
      onLoadingChange(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  // Check if we have valid dashboard data
  const hasValidData = dashboardData && dashboardData.hourlyData && dashboardData.hourlyData.length > 0;
  const currentHour = new Date().getHours();

  // Create compatible data structures for existing charts
  const scheduleData = hasValidData ? {
    hourlyData: dashboardData.hourlyData,
    currentHour: dashboardData.currentHour,
    dataSources: dashboardData.dataSources,
    totals: dashboardData.totals
  } : null;

  // Create synthetic energy data for charts that expect it
  const syntheticEnergyData = hasValidData ? {
    hourlyData: dashboardData.hourlyData
      .filter((hour: any) => hour.dataSource === 'actual' || hour.data_source === 'actual')
      .map((hour: any) => ({
        hour: typeof hour.hour === 'string' ? parseInt(hour.hour.split(':')[0]) : hour.hour,
        system_production: hour.solarProduction || hour.solar_production || hour.solarGenerated || 0,
        load_consumption: hour.homeConsumption || hour.home_consumption || hour.homeConsumed || 0,
        import_from_grid: hour.gridImport || hour.grid_import || hour.gridImported || 0,
        export_to_grid: hour.gridExport || hour.grid_export || hour.gridExported || 0,
        battery_charge: hour.batteryCharged || hour.battery_charged || 0,
        battery_discharge: hour.batteryDischarged || hour.battery_discharged || 0,
      })),
    totals: dashboardData.totals || {}
  } : { hourlyData: [], totals: {} };

  return (
    <div className="space-y-6">
      {/* System Status Header */}
      <div className="bg-white dark:bg-gray-800 p-4 rounded-lg shadow">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Dashboard</h1>
            <div className="flex items-center text-sm text-gray-500 dark:text-gray-400">
              <Clock className="h-4 w-4 mr-1" />
              Last updated: {lastUpdate.toLocaleTimeString()}
            </div>
          </div>
          <div className="flex items-center space-x-2">
            <button
              onClick={() => fetchData(true)}
              className="p-2 text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
              title="Refresh data"
            >
              <Clock className="h-4 w-4" />
            </button>
            <button
              onClick={() => setShowDebug(!showDebug)}
              className="p-2 text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 rounded text-xs"
              title="Toggle debug info"
            >
              Debug
            </button>
          </div>
        </div>
        
        {/* Debug Info */}
        {showDebug && (
          <div className="mt-4 p-3 bg-gray-50 dark:bg-gray-700 rounded text-xs font-mono">
            {debugInfo.map((msg, i) => (
              <div key={i} className="text-gray-600 dark:text-gray-300">{msg}</div>
            ))}
          </div>
        )}
      </div>

      {/* Error Display */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-4 rounded-lg">
          <div className="flex items-center">
            <AlertCircle className="h-5 w-5 text-red-400 mr-3" />
            <div>
              <h3 className="text-sm font-medium text-red-800 dark:text-red-200">Error loading dashboard</h3>
              <p className="text-sm text-red-700 dark:text-red-300 mt-1">{error}</p>
            </div>
          </div>
        </div>
      )}

      {/* Main Content */}
      {hasValidData ? (
        <>
          {/* Energy Cards */}
          <ConsolidatedEnergyCards />
          
          {/* Energy Flow Chart */}
          <EnergyFlowChart 
            dailyViewData={dashboardData.hourlyData}
            energyBalanceData={syntheticEnergyData.hourlyData}
            currentHour={currentHour}
          />

          {/* Battery Level Chart */}
          <BatteryLevelChart 
            hourlyData={dashboardData.hourlyData} 
            settings={settings} 
          />

          {/* Energy Sankey Diagram */}
          <EnergySankeyChart energyData={scheduleData} />
          
          {/* Dashboard Overview */}
          <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
            <h2 className="text-xl font-semibold mb-4 text-gray-900 dark:text-white">Dashboard Overview</h2>
            
            <p className="mb-3 text-gray-700 dark:text-gray-300">
              Your dashboard provides a comprehensive overview of your battery system performance 
              with 4 essential charts covering all key metrics.
            </p>
            <ul className="space-y-2 text-sm text-gray-600 dark:text-gray-400">
              <li>• <strong className="text-gray-900 dark:text-white">Energy Cards:</strong> Real-time cost, solar, consumption, battery, and grid data</li>
              <li>• <strong className="text-gray-900 dark:text-white">Energy Flow Chart:</strong> Hourly energy flows with predictions vs actual data</li>
              <li>• <strong className="text-gray-900 dark:text-white">Battery Chart:</strong> SOC levels, electricity prices, and battery actions</li>
              <li>• <strong className="text-gray-900 dark:text-white">Sankey Diagram:</strong> Visual overview of daily energy flows between sources</li>
            </ul>
            
            {/* Data Source Summary */}
            <div className="mt-4 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-blue-900 dark:text-blue-100">
                  📊 Data: {dashboardData.actualHoursCount} actual + {dashboardData.predictedHoursCount} predicted hours
                </span>
                <span className="text-sm text-blue-700 dark:text-blue-300">
                  💰 Total savings: {dashboardData.totalDailySavings?.toFixed(2)} SEK
                </span>
              </div>
            </div>
          </div>
        </>
      ) : (
        <div className="text-center py-8">
          <AlertCircle className="h-12 w-12 text-gray-400 dark:text-gray-500 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">No Dashboard Data</h3>
          <p className="text-gray-600 dark:text-gray-400 mb-4">
            The dashboard needs data to display charts and analytics.
          </p>
          <button
            onClick={() => fetchData(true)}
            className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
          >
            Retry Loading
          </button>
        </div>
      )}
    </div>
  );
}