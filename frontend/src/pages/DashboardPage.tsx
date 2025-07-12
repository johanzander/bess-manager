import { useState, useEffect, useCallback } from 'react';
import { BatteryLevelChart } from '../components/BatteryLevelChart';
import { EnergyFlowChart } from '../components/EnergyFlowChart';
import { EnergySankeyChart } from '../components/EnergySankeyChart';
import { BatterySettings, ElectricitySettings } from '../types';
import { Clock, AlertCircle } from 'lucide-react';
import EnergyFlowCards from '../components/EnergyFlowCards';
import SystemStatusCard from '../components/SystemStatusCard';
import api from '../lib/api';

interface DashboardProps {
  onLoadingChange: (loading: boolean) => void;
  settings: BatterySettings & ElectricitySettings;
}

export default function DashboardPage({
  onLoadingChange,
  settings
}: DashboardProps) {
  // Define a proper type for dashboard data
  interface DashboardData {
    // Error handling fields
    error?: string;
    message?: string;
    detail?: string;
    
    hourlyData: Array<{
      hour: number;
      batterySocEnd?: number;
      batteryAction?: number;
      batteryMode?: string;
      solarProduction?: number;
      homeConsumption?: number;
      gridImport?: number;
      gridImported?: number;
      gridExport?: number;
      grid_export?: number;
      gridExported?: number;
      batteryCharged?: number;
      battery_charged?: number;
      batteryDischarged?: number;
      battery_discharged?: number;
      dataSource?: string;
      data_source?: string;
      isActual?: boolean;
      buyPrice?: number;
      sellPrice?: number;
    }>;
    currentHour?: number;
    dataSources?: Record<string, any>;
    summary?: {
      gridOnlyCost?: number;  // Updated name
      optimizedCost?: number;
      savings?: number;
    };
    totals?: Record<string, number>;
    strategicIntentSummary?: Record<string, number>;
    actualHoursCount?: number;
    predictedHoursCount?: number;
    totalDailySavings?: number;
    actual_savings_so_far?: number;
    actual_hours_count?: number;
    predicted_remaining_savings?: number;
    predicted_hours_count?: number;
    batteryCapacity?: number;
  }

  const [dashboardData, setDashboardData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());
  const [debugInfo, setDebugInfo] = useState<string[]>([]);
  const [showDebug, setShowDebug] = useState(false);
  const [isInitialLoad, setIsInitialLoad] = useState(true);

  // Memoize the fetchData function to avoid recreation on each render
  const fetchData = useCallback(async (isManualRefresh = false) => {
    // Don't show loading state on background refreshes
    if (isInitialLoad || isManualRefresh) {
      onLoadingChange(true);
    }
    setError(null);

    const debugMessages: string[] = [];
    debugMessages.push(`🔄 Fetching dashboard data... (${isManualRefresh ? 'manual' : 'auto'})`);

    try {
      // ✅ CRITICAL FIX: Don't clear data to prevent blinking
      // setDashboardData(null); // ← REMOVED THIS LINE

      debugMessages.push(`📡 Calling unified /api/dashboard endpoint...`);
      const response = await api.get('/api/dashboard');
      
      if (response?.data) {
        // Check if this is an error response with incomplete data
        if (response.data.error === 'incomplete_data') {
          // Still set the data to what we have (may be partial or empty)
          setDashboardData(response.data);
          
          // Log the error but don't treat it as a fatal error
          debugMessages.push(`⚠️ WARNING: ${response.data.message}`);
          debugMessages.push(`⚠️ Detail: ${response.data.detail}`);
          
          // Show a warning but continue loading the page
          setError(`Warning: ${response.data.message} Some dashboard features might not display correctly.`);
        } else {
          // Normal successful response
          setDashboardData(response.data);
          
          const hourlyDataCount = response.data.hourlyData?.length || 0;
          const actualCount = response.data.actualHoursCount || 0;
          const predictedCount = response.data.predictedHoursCount || 0;
          
          debugMessages.push(`✅ Dashboard data loaded successfully`);
          debugMessages.push(`📊 Total hours: ${hourlyDataCount} (${actualCount} actual + ${predictedCount} predicted)`);
          debugMessages.push(`💰 Daily savings: ${((response.data.summary?.gridOnlyCost || 0) - (response.data.summary?.optimizedCost || 0)).toFixed(2)} SEK`);
          debugMessages.push(`🔋 Battery capacity: ${response.data.batteryCapacity || 'N/A'} kWh`);
          
          // Log strategic intent summary if available
          if (response.data.strategicIntentSummary) {
            const intents = Object.entries(response.data.strategicIntentSummary)
              .map(([intent, count]) => `${intent}: ${count}`)
              .join(', ');
            debugMessages.push(`🎯 Strategic intents: ${intents}`);
          }
        }
      } else {
        throw new Error('No data received from dashboard endpoint');
      }

      setLastUpdate(new Date());
      debugMessages.push(`✅ Data fetch completed at ${new Date().toLocaleTimeString()}`);

    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Unknown error occurred';
      debugMessages.push(`❌ Error: ${errorMessage}`);
      setError(errorMessage);
      console.error('Dashboard data fetch failed:', err);
    } finally {
      setDebugInfo(debugMessages);
      onLoadingChange(false);
      setIsInitialLoad(false);
    }
  }, [isInitialLoad, onLoadingChange]); // Add dependencies

  useEffect(() => {
    fetchData();
    const interval = setInterval(() => fetchData(), 60000); // Auto-refresh every minute
    return () => clearInterval(interval);
  }, [fetchData]); // Add fetchData dependency (which includes onLoadingChange)

  // Check if we have valid dashboard data
  const hasValidData = dashboardData && dashboardData.hourlyData && dashboardData.hourlyData.length > 0;
  const hasPartialData = dashboardData && dashboardData.error === 'incomplete_data';
  const currentHour = new Date().getHours();

  // Create Sankey data
  const sankeyData = hasValidData ? {
    hourlyData: dashboardData.hourlyData,
    currentHour: dashboardData.currentHour,
    dataSources: dashboardData.dataSources,
    totals: dashboardData.totals
  } : null;

  return (
    <div className="space-y-6">
      {/* Warning Banner for Incomplete Data */}
      {hasPartialData && (
        <div className="bg-yellow-50 border-l-4 border-yellow-400 p-4 mb-4 rounded">
          <div className="flex items-center">
            <div className="flex-shrink-0">
              <AlertCircle className="h-5 w-5 text-yellow-400" aria-hidden="true" />
            </div>
            <div className="ml-3">
              <p className="text-sm text-yellow-700">
                {dashboardData?.message || "Some data is missing. The dashboard may display incomplete information."}
              </p>
            </div>
          </div>
        </div>
      )}
      
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
              <div key={`debug-${i}`} className="text-gray-600 dark:text-gray-300">{msg}</div>
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
          {/* System Status Cards - New section at the top */}
          <div className="space-y-6">
            <div>
              <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">System Status</h2>
              <SystemStatusCard />
            </div>
          </div>

          {/* Energy Flow Cards - Restructured section */}
          <div className="space-y-6">
            <div>
              <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">Energy Flows</h2>
              <EnergyFlowCards />
            </div>
          </div>
          
          {/* Charts Section */}
          <div className="space-y-8">
            <div>
              <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">Performance Charts</h2>
              
              {/* Energy Flow Chart */}
              <div className="mb-8">
                <EnergyFlowChart 
                  dailyViewData={dashboardData.hourlyData}
                  currentHour={currentHour}
                />
              </div>

              {/* Battery Level Chart */}
              <div className="mb-8">
                <BatteryLevelChart 
                  hourlyData={dashboardData.hourlyData} 
                  settings={settings} 
                />
              </div>

              {/* Energy Sankey Diagram */}
              <div className="mb-8">
                <EnergySankeyChart energyData={sankeyData} />
              </div>
            </div>
          </div>
          
          {/* Dashboard Overview */}
          <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
            <h2 className="text-xl font-semibold mb-4 text-gray-900 dark:text-white">Dashboard Overview</h2>
            
            <p className="mb-3 text-gray-700 dark:text-gray-300">
              Your dashboard provides a comprehensive overview of your battery system performance 
              with dedicated sections for status monitoring, energy flows, and detailed analytics.
            </p>
            <ul className="space-y-2 text-sm text-gray-600 dark:text-gray-400">
              <li>• <strong className="text-gray-900 dark:text-white">System Status:</strong> Cost savings, battery state, and system health monitoring</li>
              <li>• <strong className="text-gray-900 dark:text-white">Energy Flows:</strong> Pure energy flow data across solar, consumption, grid, battery, and balance</li>
              <li>• <strong className="text-gray-900 dark:text-white">Performance Charts:</strong> Detailed visualizations of energy flows, battery levels, and system flows</li>
            </ul>
            
            {/* Data Source Summary */}
            <div className="mt-4 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-blue-900 dark:text-blue-100">
                  📊 Data: {dashboardData.actualHoursCount} actual + {dashboardData.predictedHoursCount} predicted hours
                </span>
                <span className="text-sm text-blue-700 dark:text-blue-300">
                  💰 Total savings: {((dashboardData.summary?.gridOnlyCost || 0) - (dashboardData.summary?.optimizedCost || 0)).toFixed(2)} SEK
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
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            Try Again
          </button>
        </div>
      )}
    </div>
  );
}