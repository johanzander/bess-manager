import { useState, useEffect } from 'react';
import { EnhancedSummaryCards } from '../components/EnhancedSummaryCards';
import { BatteryLevelChart } from '../components/BatteryLevelChart';
import { EnhancedEnergyFlowChart } from '../components/EnhancedEnergyFlowChart';
import { EnergySankeyChart } from '../components/EnergySankeyChart';
import { BatterySettings, ElectricitySettings, ScheduleData } from '../types';
import { Clock, AlertCircle } from 'lucide-react';
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
      setError(`Schedule creation failed: ${errorMessage}`);
    } finally {
      setRefreshing(false);
    }
  };

  const fetchData = async (isRefresh = false) => {
    if (!isRefresh) {
      onLoadingChange(true);
    }
    
    setError(null);
    const debugMessages: string[] = [];
    let scheduleResult = null;
    let scheduleError = null;

    try {
      // Try multiple schedule endpoints
      const scheduleEndpoints = ['/api/v2/daily_view', '/api/schedule/detailed', '/api/schedule/current'];
      
      for (const endpoint of scheduleEndpoints) {
        try {
          debugMessages.push(`🔍 Trying ${endpoint}...`);
          const response = await api.get(endpoint);
          scheduleResult = response.data;
          debugMessages.push(`✅ ${endpoint} succeeded`);
          break;
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
        const errorMsg = scheduleError instanceof Error ? scheduleError.message : 'Unknown error';
        setError(`Failed to load schedule data: ${errorMsg}`);
        setNoDataAvailable(true);
      }

      // Handle energy balance data
      if (energyResponse.status === 'fulfilled') {
        setEnergyData(energyResponse.value.data);
        debugMessages.push(`📊 Energy balance data: ${energyResponse.value.data.hourlyData?.length || 0} hours`);
      } else {
        debugMessages.push(`❌ Energy balance failed: ${energyResponse.reason?.message || 'Unknown error'}`);
      }

      // Handle daily view data  
      if (dailyViewResponse.status === 'fulfilled') {
        setDailyViewData(dailyViewResponse.value.data);
        debugMessages.push(`📊 Daily view data: ${dailyViewResponse.value.data.hourly_data?.length || 0} hours`);
      } else {
        debugMessages.push(`❌ Daily view failed: ${dailyViewResponse.reason?.message || 'Unknown error'}`);
      }

      // Handle system info data
      if (systemInfoResponse.status === 'fulfilled') {
        setSystemInfo(systemInfoResponse.value.data);
        debugMessages.push(`📊 System info loaded successfully`);
      } else {
        debugMessages.push(`❌ System info failed: ${systemInfoResponse.reason?.message || 'Unknown error'}`);
      }

      setLastUpdate(new Date());
      
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

  // Determine what data we have available
  const hasScheduleData = scheduleData && scheduleData.hourlyData && scheduleData.hourlyData.length > 0;
  const hasEnergyData = energyData && energyData.hourlyData && energyData.hourlyData.length > 0;
  const currentHour = new Date().getHours();

  return (
    <div className="space-y-6">
      {/* System Status Header */}
      <div className="bg-white p-4 rounded-lg shadow">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
            <div className="flex items-center text-sm text-gray-500">
              <Clock className="h-4 w-4 mr-1" />
              Last updated: {lastUpdate.toLocaleTimeString()}
            </div>
          </div>
          <div className="flex items-center space-x-2">
            {showDebug && (
              <button
                onClick={() => setShowDebug(false)}
                className="px-3 py-2 text-sm bg-gray-100 text-gray-700 rounded hover:bg-gray-200"
              >
                Hide Debug
              </button>
            )}
          </div>
        </div>

        {/* Debug Information */}
        {showDebug && (
          <div className="mt-4 p-3 bg-gray-50 rounded text-sm">
            <h4 className="font-medium mb-2">Debug Information:</h4>
            <div className="space-y-1 text-xs font-mono">
              {debugInfo.map((msg, idx) => (
                <div key={idx}>{msg}</div>
              ))}
            </div>
          </div>
        )}

        {/* System Status */}
        {systemInfo && (
          <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>System Status: <span className="font-medium text-green-600">Active</span></div>
            <div>Data Sources: <span className="font-medium">{hasScheduleData && hasEnergyData ? 'Complete' : 'Partial'}</span></div>
            <div>Controller Connected: <span className="font-medium">{systemInfo.controller_available ? 'Yes' : 'No'}</span></div>
            {systemInfo.simple_system_info && (
              <>
                <div>Historical Events: <span className="font-medium">{systemInfo.simple_system_info.historical_events_count}</span></div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Error Message */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex items-center">
            <AlertCircle className="h-5 w-5 text-red-500 mr-2" />
            <span className="text-red-700">{error}</span>
          </div>
        </div>
      )}

      {/* CHART 1: Enhanced Summary Cards - Financial overview & key metrics */}
      {hasEnergyData && dailyViewData && (
        <EnhancedSummaryCards 
          dailyViewData={dailyViewData}
          energyData={energyData}
        />
      )}
      
      {/* CHART 2: Energy Sankey Diagram - Daily energy flow overview */}
      {hasEnergyData && (
        <EnergySankeyChart energyData={energyData} />
      )}
      
      {/* CHART 3: Enhanced Energy Flow Chart - Hourly details + predictions vs actuals */}
      {hasEnergyData && dailyViewData && dailyViewData.hourly_data && (
        <EnhancedEnergyFlowChart 
          dailyViewData={dailyViewData.hourly_data}
          energyBalanceData={energyData.hourlyData}
          currentHour={currentHour}
        />
      )}
      
      {/* CHART 4: Battery Level Chart - SOC + prices + actions */}
      {dailyViewData && dailyViewData.hourly_data && (
        <BatteryLevelChart hourlyData={dailyViewData.hourly_data} settings={settings} />
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
      
      {/* Dashboard Overview */}
      <div className="bg-white p-6 rounded-lg shadow">
        <h2 className="text-xl font-semibold mb-4">Dashboard Overview</h2>
        
        {hasScheduleData ? (
          <>
            <p className="mb-3 text-gray-700">
              Your dashboard provides a comprehensive overview of your battery system performance 
              with 4 essential charts covering all key metrics.
            </p>
            
            <div className="space-y-2">
              <div className="flex items-start">
                <div className="w-3 h-3 bg-green-500 rounded-full mt-1.5 mr-2"></div>
                <p className="text-gray-700">
                  <span className="font-medium">Summary Cards:</span> Financial overview with daily savings, 
                  battery cycles, grid balance, and data quality metrics.
                </p>
              </div>
              
              <div className="flex items-start">
                <div className="w-3 h-3 bg-blue-500 rounded-full mt-1.5 mr-2"></div>
                <p className="text-gray-700">
                  <span className="font-medium">Energy Flow Diagram:</span> Interactive overview showing 
                  complete daily energy flows between grid, solar, battery, and home.
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
                  <span className="font-medium">Battery Level:</span> Shows battery state of charge, 
                  electricity prices, and battery actions throughout the day.
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
          <div className="text-center py-8">
            <AlertCircle className="h-12 w-12 text-gray-400 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-900 mb-2">No Data Available</h3>
            <p className="text-gray-600 mb-4">
              Dashboard data is not currently available. This could be due to system initialization or connectivity issues.
            </p>
            <button
              onClick={fetchData}
              className="inline-flex items-center px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
            >
              Try Again
            </button>
          </div>
        )}
      </div>
    </div>
  );
}