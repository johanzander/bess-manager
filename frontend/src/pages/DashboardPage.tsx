import { useState, useEffect, useCallback } from 'react';
import { BatteryLevelChart } from '../components/BatteryLevelChart';
import { EnergyFlowChart } from '../components/EnergyFlowChart';
import { BatterySettings, ElectricitySettings } from '../types';
import { Clock, AlertCircle } from 'lucide-react';
import EnergyFlowCards from '../components/EnergyFlowCards';
import SystemStatusCard from '../components/SystemStatusCard';
import AlertBanner from '../components/AlertBanner';
import api from '../lib/api';
import { useUserPreferences } from '../hooks/useUserPreferences';

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
  const [isInitialLoad, setIsInitialLoad] = useState(true);

  // User preferences (resolution, etc.)
  const { dataResolution, setDataResolution } = useUserPreferences();

  // Health summary state for alert banner
  interface HealthSummary {
    hasCriticalErrors: boolean;
    criticalIssues: Array<{
      component: string;
      description: string;
      status: string;
    }>;
    totalCriticalIssues: number;
    timestamp: string;
    systemMode: string;
  }
  
  const [healthSummary, setHealthSummary] = useState<HealthSummary | null>(null);
  const [dismissedBanner, setDismissedBanner] = useState(false);

  // Historical data status state
  interface HistoricalDataStatus {
    isIncomplete: boolean;
    missingHours: number[];
    completedHours: number[];
    totalMissing: number;
    totalCompleted: number;
    message: string;
    timestamp: string;
  }

  const [historicalDataStatus, setHistoricalDataStatus] = useState<HistoricalDataStatus | null>(null);
  const [dismissedHistoricalWarning, setDismissedHistoricalWarning] = useState(false);

  // Handle banner dismissal
  const handleDismissBanner = useCallback(() => {
    setDismissedBanner(true);
  }, []);

  // Handle historical warning dismissal
  const handleDismissHistoricalWarning = useCallback(() => {
    setDismissedHistoricalWarning(true);
  }, []);

  // Memoize the fetchData function to avoid recreation on each render
  const fetchData = useCallback(async (isManualRefresh = false) => {
    // Don't show loading state on background refreshes
    if (isInitialLoad || isManualRefresh) {
      onLoadingChange(true);
    }
    setError(null);

    try {
      // Fetch dashboard data, health summary, and historical data status concurrently
      const [dashboardResponse, healthResponse, historicalResponse] = await Promise.all([
        api.get('/api/dashboard', { params: { resolution: dataResolution } }),
        api.get('/api/dashboard-health-summary'),
        api.get('/api/historical-data-status')
      ]);

      const response = dashboardResponse;
      
      if (response?.data) {
        // Check if this is an error response with incomplete data
        if (response.data.error === 'incomplete_data') {
          // Still set the data to what we have (may be partial or empty)
          setDashboardData(response.data);
          
          // Show a warning but continue loading the page
          setError(`Warning: ${response.data.message} Some dashboard features might not display correctly.`);
        } else {
          // Normal successful response
          setDashboardData(response.data);
        }
      } else {
        throw new Error('No data received from dashboard endpoint');
      }

      // Process health summary data
      if (healthResponse?.data) {
        setHealthSummary(healthResponse.data);
        // Reset dismissed banner if there are new critical issues
        if (healthResponse.data.hasCriticalErrors) {
          setDismissedBanner(false);
        }
      }

      // Process historical data status
      if (historicalResponse?.data) {
        setHistoricalDataStatus(historicalResponse.data);
        // Reset dismissed warning if data is incomplete
        if (historicalResponse.data.isIncomplete) {
          setDismissedHistoricalWarning(false);
        }
      }

      setLastUpdate(new Date());

    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Unknown error occurred';
      setError(errorMessage);
      console.error('Dashboard data fetch failed:', err);
    } finally {
      onLoadingChange(false);
      setIsInitialLoad(false);
    }
  }, [isInitialLoad, onLoadingChange, dataResolution]); // Add dependencies

  useEffect(() => {
    fetchData();
    const interval = setInterval(() => fetchData(), 60000); // Auto-refresh every minute
    return () => clearInterval(interval);
  }, [fetchData]); // Add fetchData dependency (which includes onLoadingChange)

  // Check if we have valid dashboard data
  const hasValidData = dashboardData && dashboardData.hourlyData && dashboardData.hourlyData.length > 0;
  const hasPartialData = dashboardData && dashboardData.error === 'incomplete_data';
  const currentHour = new Date().getHours();

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

      {/* Critical Sensor Alert Banner */}
      {healthSummary && healthSummary.hasCriticalErrors && !dismissedBanner && (
        <AlertBanner
          hasCriticalErrors={healthSummary.hasCriticalErrors}
          criticalIssues={healthSummary.criticalIssues}
          totalCriticalIssues={healthSummary.totalCriticalIssues}
          onDismiss={handleDismissBanner}
        />
      )}

      {/* Historical Data Warning Banner */}
      {historicalDataStatus && historicalDataStatus.isIncomplete && !dismissedHistoricalWarning && (
        <div className="bg-yellow-50 dark:bg-yellow-900/20 border-l-4 border-yellow-400 p-4 rounded shadow">
          <div className="flex items-start">
            <div className="flex-shrink-0">
              <AlertCircle className="h-5 w-5 text-yellow-400" aria-hidden="true" />
            </div>
            <div className="ml-3 flex-1">
              <h3 className="text-sm font-medium text-yellow-800 dark:text-yellow-200">
                Incomplete Historical Data
              </h3>
              <div className="mt-2 text-sm text-yellow-700 dark:text-yellow-300">
                <p>{historicalDataStatus.message}</p>
                <p className="mt-1">
                  Missing data for {historicalDataStatus.totalMissing} hour{historicalDataStatus.totalMissing !== 1 ? 's' : ''}: {historicalDataStatus.missingHours.join(', ')}
                </p>
                <p className="mt-2 text-xs">
                  This usually happens after system restart when InfluxDB is not configured.
                  The dashboard will skip these hours and only show data from the current hour onwards.
                  Optimization continues to work normally starting from the current hour.
                </p>
              </div>
            </div>
            <div className="ml-auto pl-3">
              <button
                onClick={handleDismissHistoricalWarning}
                className="inline-flex rounded-md bg-yellow-50 dark:bg-yellow-900/20 p-1.5 text-yellow-500 hover:bg-yellow-100 dark:hover:bg-yellow-900/40 focus:outline-none focus:ring-2 focus:ring-yellow-600 focus:ring-offset-2"
              >
                <span className="sr-only">Dismiss</span>
                <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                  <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      )}
      
      {/* System Status Header */}
      <div className="bg-white dark:bg-gray-800 p-4 rounded-lg shadow">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Dashboard</h1>
          <div className="flex items-center text-sm text-gray-500 dark:text-gray-400">
            <Clock className="h-4 w-4 mr-1" />
            Last updated: {lastUpdate.toLocaleTimeString()}
          </div>
        </div>

        {/* Resolution Selector */}
        <div className="mt-4 flex items-center justify-end">
          <div className="flex bg-gray-100 dark:bg-gray-700 rounded-lg p-1">
            <button
              onClick={() => setDataResolution('hourly')}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                dataResolution === 'hourly'
                  ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                  : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              60 min
            </button>
            <button
              onClick={() => setDataResolution('quarter-hourly')}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                dataResolution === 'quarter-hourly'
                  ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                  : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              15 min
            </button>
          </div>
        </div>
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
          {/* System Overview Cards - New section at the top */}
          <div className="space-y-6">
            <div>
              <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">System Overview</h2>
              <SystemStatusCard />
            </div>
          </div>

          {/* Energy Flow Cards - Restructured section */}
          <div className="space-y-6">
            <div>
              <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">Today&apos;s Energy Flows - Actuals & Predicted</h2>
              <EnergyFlowCards />
            </div>
          </div>
          
          {/* Charts Section */}
          <div className="space-y-8">
            <div>
              {/* Energy Flow Chart */}
              <div className="mb-8">
                <EnergyFlowChart
                  dailyViewData={dashboardData.hourlyData as any}
                  currentHour={currentHour}
                  resolution={dataResolution}
                />
              </div>
            </div>
          </div>
          
          {/* Battery SOC and Actions */}
          <div>
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">Battery SOC and Actions</h2>
            <div className="mb-8">
              <BatteryLevelChart
                hourlyData={dashboardData.hourlyData as any}
                settings={settings}
                resolution={dataResolution}
              />
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