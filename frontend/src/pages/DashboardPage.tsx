import { useState, useEffect } from 'react';
import { EnhancedSummaryCards } from '../components/EnhancedSummaryCards';
import { SummaryCards } from '../components/SummaryCards';
import { BatteryLevelChart } from '../components/BatteryLevelChart';
import { BatteryScheduleChart } from '../components/BatteryScheduleChart';
import { BatteryActionsChart } from '../components/BatteryActionsChart';
import { EnhancedEnergyFlowChart } from '../components/EnhancedEnergyFlowChart';
import { EnergyFlowChart } from '../components/EnergyFlowChart';
import { EnergyBalanceChart } from '../components/EnergyBalanceChart';
import { EnergySankeyChart } from '../components/EnergySankeyChart';
import { BatterySettings, ElectricitySettings, ScheduleData } from '../types';
import { Activity, Clock, RefreshCw, AlertCircle } from 'lucide-react';
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
  const [energyData, setEnergyData] = useState<any | null>(null);
  const [dailyViewData, setDailyViewData] = useState<any | null>(null);
  const [systemInfo, setSystemInfo] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [noDataAvailable, setNoDataAvailable] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());
  const [refreshing, setRefreshing] = useState(false);
  const [debugInfo, setDebugInfo] = useState<string[]>([]);
  const [showDebug, setShowDebug] = useState(false);

  // Manual schedule creation function
  const createSchedule = async () => {
    try {
      setRefreshing(true);
      setDebugInfo(prev => [...prev, `🔄 Manually triggering schedule creation...`]);
      
      // Try to create a new schedule
      const response = await api.get('/api/schedule?date=' + new Date().toISOString().split('T')[0]);
      
      if (response.data) {
        setDebugInfo(prev => [...prev, `✅ Schedule created successfully`]);
        // Refresh all data after creating schedule
        await fetchData(true);
      } else {
        setDebugInfo(prev => [...prev, `❌ Schedule creation returned empty data`]);
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Unknown error';
      setDebugInfo(prev => [...prev, `❌ Schedule creation failed: ${errorMessage}`]);
      setError(`Failed to create schedule: ${errorMessage}`);
    } finally {
      setRefreshing(false);
    }
  };

  const fetchData = async (isRefresh: boolean = false) => {
    try {
      if (isRefresh) {
        setRefreshing(true);
      } else {
        onLoadingChange(true);
      }
      setNoDataAvailable(false);
      setError(null);
      const debugMessages: string[] = [];
  
      console.log('Fetching dashboard data...');
      debugMessages.push(`Starting data fetch at ${new Date().toLocaleTimeString()}`);
  
      // Try multiple schedule endpoints as fallbacks
      const scheduleEndpoints = [
        '/api/schedule/detailed',
        '/api/schedule/current', 
        '/api/schedule'
      ];
      
      let scheduleResult = null;
      let scheduleError = null;
      
      // Try each schedule endpoint until one works
      for (const endpoint of scheduleEndpoints) {
        try {
          debugMessages.push(`Trying schedule endpoint: ${endpoint}`);
          const response = await api.get(endpoint);
          
          if (response.data) {
            scheduleResult = response.data;
            debugMessages.push(`✅ Success with ${endpoint}`);
            break;
          } else {
            debugMessages.push(`⚠️ ${endpoint} returned empty data`);
          }
        } catch (err) {
          const errorMsg = err instanceof Error ? err.message : 'Unknown error';
          debugMessages.push(`❌ ${endpoint} failed: ${errorMsg}`);
          scheduleError = err;
        }
      }

      // Fetch other data in parallel  
      const [energyResponse, dailyViewResponse, systemInfoResponse] = await Promise.allSettled([
        api.get('/api/energy/balance'),
        api.get('/api/v2/daily_view'),
        api.get('/api/system/info')
      ]);
      
      // Handle schedule data
      if (scheduleResult) {
        // Check if schedule data has the expected structure
        if (scheduleResult.schedule && scheduleResult.schedule.hourlyData) {
          // Handle /api/schedule/current format
          setScheduleData(scheduleResult.schedule);
          debugMessages.push(`📊 Schedule data: ${scheduleResult.schedule.hourlyData.length} hours`);
        } else if (scheduleResult.hourlyData) {
          // Handle /api/schedule/detailed format (camelCase)
          setScheduleData(scheduleResult);
          debugMessages.push(`📊 Schedule data: ${scheduleResult.hourlyData.length} hours`);
        } else if (scheduleResult.hourly_data) {
          // Handle /api/schedule/detailed format (snake_case) - THIS IS THE ACTUAL FORMAT
          debugMessages.push(`🔧 Converting snake_case API response to camelCase...`);
          debugMessages.push(`📋 Original keys: ${Object.keys(scheduleResult).join(', ')}`);
          
          // Make sure hour is properly formatted as a string in the hourly data
          const formattedHourlyData = scheduleResult.hourly_data.map((hourData: any) => {
            // Check if the hour needs formatting
            if (typeof hourData.hour === 'number') {
              return {
                ...hourData,
                hour: `${hourData.hour}:00` // Format number as "hour:00"
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
          debugMessages.push(`✅ Conversion complete - now has hourlyData field`);
        } else {
          debugMessages.push(`⚠️ Schedule data has unexpected format: ${JSON.stringify(Object.keys(scheduleResult))}`);
          setNoDataAvailable(true);
        }
      } else {
        debugMessages.push(`❌ No schedule data from any endpoint`);
        const errorMsg = scheduleError instanceof Error ? scheduleError.message : 'All endpoints failed';
        setError(`Failed to fetch schedule data: ${errorMsg}`);
        setNoDataAvailable(true);
      }

      // Handle energy balance data
      if (energyResponse.status === 'fulfilled') {
        const newEnergyData = energyResponse.value.data;
        setEnergyData(newEnergyData);
        debugMessages.push(`🔋 Energy data: ${newEnergyData.hourlyData?.length || 0} hours`);
      } else {
        const reason = energyResponse.reason instanceof Error ? energyResponse.reason.message : 'Unknown error';
        debugMessages.push(`⚠️ Energy balance failed: ${reason}`);
      }

      // Handle daily view data
      if (dailyViewResponse.status === 'fulfilled') {
        const newDailyViewData = dailyViewResponse.value.data;
        setDailyViewData(newDailyViewData);
        debugMessages.push(`📈 Daily view data: current hour ${newDailyViewData.current_hour}`);
      } else {
        const reason = dailyViewResponse.reason instanceof Error ? dailyViewResponse.reason.message : 'Unknown error';
        debugMessages.push(`⚠️ Daily view failed: ${reason}`);
      }

      // Handle system info
      if (systemInfoResponse.status === 'fulfilled') {
        const newSystemInfo = systemInfoResponse.value.data;
        setSystemInfo(newSystemInfo);
        debugMessages.push(`ℹ️ System: ${newSystemInfo.system_type}, ${newSystemInfo.system_class}`);
      } else {
        const reason = systemInfoResponse.reason instanceof Error ? systemInfoResponse.reason.message : 'Unknown error';
        debugMessages.push(`⚠️ System info failed: ${reason}`);
      }
      
      setDebugInfo(debugMessages);
      setLastUpdate(new Date());
      
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Unknown error occurred';
      setError(errorMessage);
      setDebugInfo(prev => [...prev, `💥 Fatal error: ${errorMessage}`]);
      console.error('Data fetch error:', err);
    } finally {
      onLoadingChange(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchData();
    
    // Set up auto-refresh every 2 minutes
    const interval = setInterval(() => fetchData(true), 2 * 60 * 1000);
    return () => clearInterval(interval);
  }, [onLoadingChange]);

  // Get current hour for highlighting
  const currentHour = dailyViewData?.current_hour || new Date().getHours();

  // Show loading only if we're actively loading and have no data
  if ((scheduleData === null && energyData === null && !error) || noDataAvailable) {
    let message = 'Loading dashboard data...';
    
    if (error) {
      message = `Error: ${error}`;
    } else if (noDataAvailable) {
      message = `No schedule data available. The system may be starting up or no battery schedule has been created yet.`;
    }

    return (
      <div className="p-6 bg-gray-50 flex items-center justify-center min-h-screen">
        <div className="bg-white p-6 rounded-lg shadow max-w-2xl w-full">
          <div className="text-center mb-6">
            <h2 className="text-xl font-semibold text-gray-800 mb-2">System Initializing</h2>
            <p className="text-gray-600 mb-4">{message}</p>
            
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <button
                onClick={() => fetchData(true)}
                disabled={refreshing}
                className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50"
              >
                <RefreshCw className={`h-4 w-4 inline mr-1 ${refreshing ? 'animate-spin' : ''}`} />
                Refresh Data
              </button>
              
              <button
                onClick={createSchedule}
                disabled={refreshing}
                className="px-4 py-2 bg-green-500 text-white rounded hover:bg-green-600 disabled:opacity-50"
              >
                Create Schedule
              </button>
            </div>
          </div>

          {/* System Info */}
          {systemInfo && (
            <div className="mb-4 p-4 bg-gray-50 rounded-lg">
              <h3 className="font-medium text-gray-800 mb-2">System Information</h3>
              <div className="text-sm text-gray-600 space-y-1">
                <div>Type: <span className="font-medium">{systemInfo.system_type}</span></div>
                <div>Class: <span className="font-medium">{systemInfo.system_class}</span></div>
                {systemInfo.simple_system_info && (
                  <>
                    <div>Events: <span className="font-medium">{systemInfo.simple_system_info.historical_events_count}</span></div>
                    <div>Schedules: <span className="font-medium">{systemInfo.simple_system_info.stored_schedules_count}</span></div>
                  </>
                )}
              </div>
            </div>
          )}

          {/* Debug Information */}
          {debugInfo.length > 0 && (
            <div className="p-4 bg-gray-100 rounded-lg">
              <h3 className="font-medium text-gray-800 mb-2">Debug Information</h3>
              <div className="text-sm font-mono text-gray-700 max-h-40 overflow-y-auto">
                {debugInfo.map((msg, index) => (
                  <div key={index} className="mb-1">{msg}</div>
                ))}
              </div>
            </div>
          )}

          <div className="mt-4 text-center">
            <p className="text-sm text-gray-500">
              If issues persist, check the <span className="font-medium">System Health</span> tab for detailed diagnostics.
            </p>
          </div>
        </div>
      </div>
    );
  }

  // If we have some data, render the dashboard even if not all data is available
  const hasScheduleData = scheduleData && scheduleData.hourlyData && scheduleData.hourlyData.length > 0;
  const hasEnergyData = energyData && energyData.hourlyData;

  return (
    <div className="p-6 space-y-8 bg-gray-50">
      {/* Header with live status */}
      <div className="bg-white p-6 rounded-lg shadow">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 flex items-center">
              <Activity className="h-6 w-6 mr-2 text-blue-600" />
              Energy Dashboard
            </h1>
            <p className="text-gray-600 mt-1">
              Live monitoring and overview of your energy system performance
            </p>
          </div>
          <div className="flex items-center space-x-4">
            <div className="text-sm text-gray-500">
              <Clock className="h-4 w-4 inline mr-1" />
              Last updated: {lastUpdate.toLocaleTimeString()}
            </div>
            <div className="text-sm text-gray-600">
              Current hour: <span className="font-medium text-blue-600">{currentHour}:00</span>
            </div>
            <button
              onClick={() => fetchData(true)}
              disabled={refreshing}
              className="flex items-center px-3 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50"
            >
              <RefreshCw className={`h-4 w-4 mr-1 ${refreshing ? 'animate-spin' : ''}`} />
              Refresh
            </button>
            <button
              onClick={() => setShowDebug(!showDebug)}
              className="flex items-center px-3 py-2 bg-gray-500 text-white rounded hover:bg-gray-600"
            >
              Debug
            </button>
            {!hasScheduleData && (
              <button
                onClick={createSchedule}
                disabled={refreshing}
                className="flex items-center px-3 py-2 bg-green-500 text-white rounded hover:bg-green-600 disabled:opacity-50"
              >
                Create Schedule
              </button>
            )}
          </div>
        </div>
        
        {/* Current status indicators */}
        <div className="mt-4 grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="bg-blue-50 p-3 rounded-lg">
            <div className="text-sm text-gray-600">System Status</div>
            <div className="text-lg font-bold text-blue-600">
              {hasScheduleData ? 'Active' : 'Starting Up'}
            </div>
          </div>
          
          <div className="bg-green-50 p-3 rounded-lg">
            <div className="text-sm text-gray-600">Daily Savings</div>
            <div className="text-lg font-bold text-green-600">
              {dailyViewData ? `${dailyViewData.total_daily_savings.toFixed(1)} SEK` : 
               hasScheduleData && scheduleData.summary ? `${scheduleData.summary.savings.toFixed(1)} SEK` : 'N/A'}
            </div>
          </div>
          
          <div className="bg-yellow-50 p-3 rounded-lg">
            <div className="text-sm text-gray-600">Current Battery</div>
            <div className="text-lg font-bold text-yellow-600">
              {hasScheduleData && currentHour < scheduleData.hourlyData.length && scheduleData.hourlyData[currentHour] ? 
                `${scheduleData.hourlyData[currentHour]?.batteryLevel?.toFixed(0) || 'N/A'}%` : 
                'N/A'}
            </div>
          </div>
          
          <div className="bg-purple-50 p-3 rounded-lg">
            <div className="text-sm text-gray-600">Data Quality</div>
            <div className="text-lg font-bold text-purple-600">
              {dailyViewData ? 
                `${Math.round((dailyViewData.actual_hours_count / (dailyViewData.actual_hours_count + dailyViewData.predicted_hours_count)) * 100)}%`
                : hasScheduleData ? '100%' : 'N/A'}
            </div>
          </div>
        </div>
      </div>

      {/* Error indicator */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex items-center">
            <AlertCircle className="h-5 w-5 text-red-500 mr-2" />
            <div>
              <span className="text-red-700 font-medium">Error Loading Data</span>
              <p className="text-red-600 text-sm mt-1">{error}</p>
              <button
                onClick={() => fetchData(true)}
                className="mt-2 text-sm text-red-600 underline hover:text-red-800"
              >
                Try again
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Debug Information Panel */}
      {showDebug && (
        <div className="bg-white p-4 rounded-lg shadow">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-medium text-gray-800">Debug Information</h3>
            <button
              onClick={() => setDebugInfo([])}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Clear
            </button>
          </div>
          
          {debugInfo.length > 0 ? (
            <div className="bg-gray-100 p-3 rounded-lg">
              <div className="text-sm font-mono text-gray-700 max-h-60 overflow-y-auto space-y-1">
                {debugInfo.map((msg, index) => (
                  <div key={index} className="whitespace-pre-wrap">{msg}</div>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-500 italic">No debug information available. Try refreshing to see fetch details.</p>
          )}

          {systemInfo && (
            <div className="mt-3 p-3 bg-blue-50 rounded-lg">
              <h4 className="font-medium text-blue-800 mb-2">System Status</h4>
              <div className="text-sm text-blue-700 space-y-1">
                <div>System Type: <span className="font-medium">{systemInfo.system_type}</span></div>
                <div>System Class: <span className="font-medium">{systemInfo.system_class}</span></div>
                <div>Has Compatibility Wrapper: <span className="font-medium">{systemInfo.has_compatibility_wrapper ? 'Yes' : 'No'}</span></div>
                {systemInfo.simple_system_info && (
                  <>
                    <div>Historical Events: <span className="font-medium">{systemInfo.simple_system_info.historical_events_count}</span></div>
                    <div>Stored Schedules: <span className="font-medium">{systemInfo.simple_system_info.stored_schedules_count}</span></div>
                    <div>Current Date: <span className="font-medium">{systemInfo.simple_system_info.current_date || 'Not set'}</span></div>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      )}
      
      {/* Enhanced Summary Cards - only show if we have schedule data */}
      {hasScheduleData && (
        <EnhancedSummaryCards 
          summary={scheduleData.summary} 
          hourlyData={scheduleData.hourlyData} 
        />
      )}
      
      {/* Energy Flow Sankey Diagram - only show if we have energy data */}
      {hasEnergyData && (
        <EnergySankeyChart energyData={energyData} />
      )}
      
      {/* Enhanced Energy Flow Chart - only show if we have both datasets */}
      {hasEnergyData && dailyViewData && dailyViewData.hourly_data && (
        <EnhancedEnergyFlowChart 
          dailyViewData={dailyViewData.hourly_data}
          energyBalanceData={energyData.hourlyData}
          currentHour={currentHour}
        />
      )}
      
      {/* Battery Level Chart - only show if we have schedule data */}
      {hasScheduleData && (
        <div className="mb-8">
          <BatteryLevelChart hourlyData={scheduleData.hourlyData} settings={settings} />
        </div>
      )}

      {/* All the previously unused components - now added */}
      {hasScheduleData && (
        <>
          {/* Original SummaryCards */}
          <SummaryCards summary={scheduleData.summary} hourlyData={scheduleData.hourlyData} />
          
          {/* BatteryScheduleChart */}
          <BatteryScheduleChart 
            hourlyData={scheduleData.hourlyData} 
            settings={settings} 
          />
          
          {/* BatteryActionsChart */}
          <BatteryActionsChart hourlyData={scheduleData.hourlyData} />
          
          {/* EnergyFlowChart */}
          <EnergyFlowChart hourlyData={scheduleData.hourlyData} />
          
          {/* EnergyBalanceChart */}
          <EnergyBalanceChart hourlyData={scheduleData.hourlyData} />
        </>
      )}

      {/* Data availability notice */}
      {(!hasScheduleData || !hasEnergyData) && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <div className="flex items-center">
            <AlertCircle className="h-5 w-5 text-yellow-500 mr-2" />
            <div>
              <span className="text-yellow-700 font-medium">Partial Data Available</span>
              <p className="text-yellow-600 text-sm mt-1">
                {!hasScheduleData && "Schedule data is not available. "}
                {!hasEnergyData && "Energy balance data is not available. "}
                Some charts may not be displayed until all data sources are active.
              </p>
            </div>
          </div>
        </div>
      )}
      
      <div className="bg-white p-6 rounded-lg shadow">
        <h2 className="text-xl font-semibold mb-4">Dashboard Overview</h2>
        
        {hasScheduleData ? (
          <>
            <p className="mb-3 text-gray-700">
              Your dashboard provides a real-time overview of your battery system performance 
              and energy flows throughout the day.
            </p>
            
            <div className="space-y-2">
              <div className="flex items-start">
                <div className="w-3 h-3 bg-green-500 rounded-full mt-1.5 mr-2"></div>
                <p className="text-gray-700">
                  <span className="font-medium">Quick Status:</span> At-a-glance view of system status, 
                  daily savings, current battery level, and data quality.
                </p>
              </div>
              
              <div className="flex items-start">
                <div className="w-3 h-3 bg-blue-500 rounded-full mt-1.5 mr-2"></div>
                <p className="text-gray-700">
                  <span className="font-medium">Energy Flow Diagram:</span> Shows total daily energy flows 
                  between grid, solar, battery, and home with exact amounts.
                </p>
              </div>
              
              <div className="flex items-start">
                <div className="w-3 h-3 bg-purple-500 rounded-full mt-1.5 mr-2"></div>
                <p className="text-gray-700">
                  <span className="font-medium">Predictions vs Reality:</span> Hourly comparison of predicted 
                  energy flows against actual measurements with accuracy indicators.
                </p>
              </div>
              
              <div className="flex items-start">
                <div className="w-3 h-3 bg-yellow-500 rounded-full mt-1.5 mr-2"></div>
                <p className="text-gray-700">
                  <span className="font-medium">Battery Level:</span> Shows the battery state of charge 
                  throughout the day alongside electricity prices and battery actions.
                </p>
              </div>
            </div>
            
            <div className="mt-4 bg-blue-50 border border-blue-200 rounded-md p-3">
              <p className="text-blue-800 text-sm">
                <span className="font-medium">Navigation tip:</span> For detailed decision analysis, visit 
                <span className="font-medium"> Insights</span>. For financial breakdown, visit 
                <span className="font-medium"> Savings</span>. For system diagnostics, visit 
                <span className="font-medium"> System Health</span>.
              </p>
            </div>
          </>
        ) : (
          <>
            <p className="mb-3 text-gray-700">
              Your dashboard will show real-time energy system performance once the battery scheduling system is active.
            </p>
            <div className="bg-yellow-50 border border-yellow-200 rounded-md p-4">
              <h4 className="font-medium text-yellow-800 mb-2">🔄 System Starting Up</h4>
              <p className="text-yellow-700 text-sm mb-2">
                The battery management system may be initializing. This typically happens when:
              </p>
              <ul className="text-yellow-700 text-sm space-y-1 ml-4">
                <li>• The system is starting up for the first time</li>
                <li>• Battery schedule is being calculated</li>
                <li>• Waiting for electricity price data</li>
                <li>• Home Assistant connections are being established</li>
              </ul>
              <p className="text-yellow-700 text-sm mt-2">
                Please wait a few minutes and refresh, or check the <span className="font-medium">System Health</span> tab for diagnostics.
              </p>
            </div>
          </>
        )}
      </div>
      
      <div className="mt-6 flex justify-end">
        <button
          onClick={() => setShowDebug(!showDebug)}
          className="px-4 py-2 bg-gray-500 text-white rounded hover:bg-gray-600"
        >
          Toggle Debug Info
        </button>
      </div>
    </div>
  );
}