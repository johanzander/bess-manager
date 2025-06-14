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
  const [scheduleData, setScheduleData] = useState<ScheduleData | null>(null);
  const [dailyViewData, setDailyViewData] = useState<any | null>(null);
  // REMOVED: energyData state - no longer needed
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
      setScheduleData(null);
      setDailyViewData(null);

      // Try multiple schedule endpoints with error handling
      let scheduleResult = null;

      // Try different schedule endpoints
      const scheduleEndpoints = [
        '/api/schedule/current',
        '/api/schedule/detailed',
        '/api/schedule'
      ];

      for (const endpoint of scheduleEndpoints) {
        try {
          debugMessages.push(`🔍 Trying ${endpoint}...`);
          const scheduleResponse = await api.get(endpoint);
          if (scheduleResponse?.data) {
            scheduleResult = scheduleResponse.data;
            debugMessages.push(`✅ ${endpoint} successful`);
            break;
          }
        } catch (err) {
          const errorMsg = err instanceof Error ? err.message : 'Unknown error';
          debugMessages.push(`❌ ${endpoint} failed: ${errorMsg}`);
        }
      }

      // SIMPLIFIED: Only fetch daily view - schedule data provides everything we need
      const [dailyViewResponse] = await Promise.allSettled([
        api.get('/api/v2/daily_view')
      ]);
      
      // Handle schedule data
      if (scheduleResult) {
        if (scheduleResult.schedule && scheduleResult.schedule.hourlyData) {
          setScheduleData(scheduleResult.schedule);
          debugMessages.push(`📊 Schedule data: ${scheduleResult.schedule.hourlyData.length} hours`);
        } else if (scheduleResult.hourlyData) {
          setScheduleData(scheduleResult);
          debugMessages.push(`📊 Schedule data: ${scheduleResult.hourlyData.length} hours`);
        } else if (scheduleResult.hourly_data) {
          debugMessages.push(`🔧 Converting snake_case API response to camelCase...`);
          const formattedHourlyData = scheduleResult.hourly_data.map((hourData: any) => {
            if (typeof hourData.hour === 'number') {
              return {
                ...hourData,
                hour: `${hourData.hour}:00`
              };
            }
            return hourData;
          });
          
          const convertedData = {
            ...scheduleResult,
            hourlyData: formattedHourlyData,
            currentHour: scheduleResult.current_hour,
            dataSources: scheduleResult.data_sources
          };
          
          setScheduleData(convertedData);
          debugMessages.push(`📊 Schedule data: ${scheduleResult.hourly_data.length} hours (converted from snake_case)`);
        }
      } else {
        debugMessages.push(`❌ No schedule data from any endpoint`);
      }

      // Handle daily view response
      if (dailyViewResponse.status === 'fulfilled' && dailyViewResponse.value?.data) {
        setDailyViewData(dailyViewResponse.value.data);
        debugMessages.push(`📅 Daily view data: ${dailyViewResponse.value.data.hourly_data?.length || 0} hours`);
      } else {
        debugMessages.push(`❌ Daily view failed: ${dailyViewResponse.status === 'rejected' ? dailyViewResponse.reason : 'No data'}`);
      }

      // REMOVED: Energy balance handling - no longer needed

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

  // SIMPLIFIED: Only check for schedule data - it contains everything we need
  const hasScheduleData = scheduleData && scheduleData.hourlyData && scheduleData.hourlyData.length > 0;
  const currentHour = new Date().getHours();

  // Helper function to extract actual energy data from schedule data
  const getActualEnergyData = () => {
    if (!scheduleData?.hourlyData) return [];
    
    // Filter for actual data only and convert to energy balance format for compatibility
    return scheduleData.hourlyData
      .filter((hour: any) => hour.dataSource === 'actual' || hour.data_source === 'actual')
      .map((hour: any) => ({
        hour: typeof hour.hour === 'string' ? parseInt(hour.hour.split(':')[0]) : hour.hour,
        system_production: hour.solarProduction || hour.solar_production || 0,
        load_consumption: hour.homeConsumption || hour.home_consumption || 0,
        import_from_grid: hour.gridImport || hour.grid_import || 0,
        export_to_grid: hour.gridExport || hour.grid_export || 0,
        battery_charge: hour.batteryCharged || hour.battery_charged || 0,
        battery_discharge: hour.batteryDischarged || hour.battery_discharged || 0,
      }));
  };

  // Create a synthetic energy data object for charts that expect it
  const syntheticEnergyData = {
    hourlyData: getActualEnergyData(),
    totals: scheduleData?.totals || {}
  };

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
            {showDebug && (
              <button
                onClick={() => setShowDebug(false)}
                className="px-3 py-2 text-sm bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded hover:bg-gray-200 dark:hover:bg-gray-600"
              >
                Hide Debug
              </button>
            )}
            {!showDebug && (
              <button
                onClick={() => setShowDebug(true)}
                className="px-3 py-2 text-sm bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded hover:bg-gray-200 dark:hover:bg-gray-600"
              >
                Show Debug
              </button>
            )}
          </div>
        </div>

        {/* Debug Information */}
        {showDebug && (
          <div className="mt-4 p-3 bg-gray-50 dark:bg-gray-700 rounded text-sm">
            <h4 className="font-medium mb-2 text-gray-900 dark:text-white">Debug Information:</h4>
            <div className="space-y-1 text-xs font-mono">
              {debugInfo.map((msg, idx) => (
                <div key={idx} className="text-gray-700 dark:text-gray-300">{msg}</div>
              ))}
            </div>
          </div>
        )}

      </div>

      {/* Error Message */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/10 border border-red-200 dark:border-red-800 rounded-lg p-4">
          <div className="flex items-center">
            <AlertCircle className="h-5 w-5 text-red-500 dark:text-red-400 mr-2" />
            <span className="text-red-700 dark:text-red-300">{error}</span>
          </div>
        </div>
      )}

      {/* SIMPLIFIED: Data availability notice - only show for missing schedule data */}
      {!hasScheduleData && (
        <div className="bg-yellow-50 dark:bg-yellow-900/10 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4">
          <div className="flex items-center">
            <AlertCircle className="h-5 w-5 text-yellow-500 dark:text-yellow-400 mr-2" />
            <div>
              <span className="text-yellow-700 dark:text-yellow-300 font-medium">Schedule Data Missing</span>
              <p className="text-yellow-600 dark:text-yellow-400 text-sm mt-1">
                Dashboard needs schedule data to display charts and analytics.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* #1 Main Energy Cards */}
      <ConsolidatedEnergyCards />
            
      {/* CHART 2: Enhanced Energy Flow Chart - SIMPLIFIED to use schedule data only */}
      {hasScheduleData && dailyViewData && dailyViewData.hourly_data && (
        <EnergyFlowChart 
          dailyViewData={dailyViewData.hourly_data}
          energyBalanceData={syntheticEnergyData.hourlyData} // Use actual data extracted from schedule
          currentHour={currentHour}
        />
      )}

      {/* CHART 3: Battery Level Chart - SOC + prices + actions */}
      {dailyViewData && dailyViewData.hourly_data && (
        <BatteryLevelChart hourlyData={dailyViewData.hourly_data} settings={settings} />
      )}

      {/* CHART 4: Energy Sankey Diagram - SIMPLIFIED to use schedule data */}
      {hasScheduleData && (
        <EnergySankeyChart energyData={scheduleData} />
      )}
      
      {/* Dashboard Overview */}
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
        <h2 className="text-xl font-semibold mb-4 text-gray-900 dark:text-white">Dashboard Overview</h2>
        
        {hasScheduleData ? (
          <>
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
            <p className="text-sm text-blue-600 dark:text-blue-400 mt-3">
              📊 Using unified schedule data for all charts - actual data marked as completed hours.
            </p>
          </>
        ) : (
          <div className="text-center py-8">
            <AlertCircle className="h-12 w-12 text-gray-400 dark:text-gray-500 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">No Schedule Data</h3>
            <p className="text-gray-600 dark:text-gray-400 mb-4">
              The dashboard needs schedule data to display charts and analytics.
            </p>
            <button
              onClick={() => fetchData(true)}
              className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
            >
              Retry Loading Data
            </button>
          </div>
        )}
      </div>
    </div>
  );
}