import React, { useState, useEffect } from 'react';
import { 
  Battery, 
  Zap, 
  Power, 
  Settings, 
  RefreshCw,
  AlertTriangle,
  Target,
} from 'lucide-react';
import api from '../lib/api';

// Types for inverter data
interface InverterStatus {
  battery_soc: number;
  battery_soe: number;
  battery_charge_power: number;
  battery_discharge_power: number;
  grid_charge_enabled: boolean;
  charge_stop_soc: number;
  discharge_stop_soc: number;
  discharge_power_rate: number;
  max_charging_power: number;
  max_discharging_power: number;
  timestamp: string;
}

// Updated to use dashboard data structure
interface ScheduleHour {
  hour: number;
  batteryAction: number;
  strategicIntent?: string;
  batterySocEnd: number;
  buyPrice: number;
  isActual: boolean;
  isPredicted: boolean;
  dataSource: string;
}

interface DashboardData {
  currentHour: number;
  hourlyData: ScheduleHour[];
  strategicIntentSummary: Record<string, number>;
  date: string;
}

interface GrowattSchedule {
  current_hour: number;
  tou_intervals: TOUInterval[];
  schedule_data: ScheduleHour[];
  strategic_intent_periods: StrategicPeriod[];
  last_updated: string;
}

interface StrategicPeriod {
  start_time: string;
  end_time: string;
  strategic_intent: string;
  battery_mode: string;
  grid_charge: boolean;
  charge_power_rate: number;
  discharge_power_rate: number;
  hours_span: number;
  description: string;
}

const InverterStatusDashboard: React.FC = () => {
  const [inverterStatus, setInverterStatus] = useState<InverterStatus | null>(null);
  const [dashboardData, setDashboardData] = useState<DashboardData | null>(null);
  const [growattSchedule, setGrowattSchedule] = useState<GrowattSchedule | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());

  // Fetch inverter status (use real API call)
  const fetchInverterStatus = async (): Promise<InverterStatus> => {
    const response = await api.get('/api/growatt/inverter_status');
    return response.data;
  };

  // Updated to use consolidated dashboard endpoint and detailed schedule
  const fetchDashboardData = async (): Promise<DashboardData> => {
    const response = await api.get('/api/dashboard');
    return response.data;
  };

  const fetchGrowattSchedule = async (): Promise<GrowattSchedule> => {
    const response = await api.get('/api/growatt/detailed_schedule');
    return response.data;
  };
  
  // Load all data
  const loadData = async (): Promise<void> => {
    try {
      setError(null);
      const [statusData, scheduleDashboard] = await Promise.all([
        fetchInverterStatus(),
        fetchDashboardData()
      ]);
      setInverterStatus(statusData);
      setDashboardData(scheduleDashboard);
      
      // Mock growatt schedule until backend endpoint exists
      setGrowattSchedule({
        current_hour: scheduleDashboard.currentHour,
        tou_intervals: [],
        schedule_data: [],
        strategic_intent_periods: [],
        last_updated: new Date().toISOString()
      });
      
      setLastUpdate(new Date());
    } catch (err) {
      console.error('Error loading data:', err);
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 60000); // Refresh every minute
    return () => clearInterval(interval);
  }, []);

  // Handle grid charge toggle
  const handleGridChargeToggle = async () => {
    if (!inverterStatus) return;
    
    try {
      const newState = !inverterStatus.grid_charge_enabled;
      await api.post('/api/growatt/grid_charge', { enabled: newState });
      
      // Update local state immediately for responsiveness
      setInverterStatus(prev => prev ? { ...prev, grid_charge_enabled: newState } : null);
      
      // Refresh data after a short delay
      setTimeout(loadData, 1000);
    } catch (err) {
      console.error('Error toggling grid charge:', err);
      setError('Failed to toggle grid charge');
    }
  };

  const currentHour = new Date().getHours();
  const currentHourData = dashboardData?.hourlyData?.find(h => h.hour === currentHour);

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center bg-white rounded-lg p-8 shadow-sm">
          <RefreshCw className="h-8 w-8 animate-spin text-gray-600 mx-auto mb-4" />
          <p className="text-gray-600">Loading inverter status...</p>
        </div>
      </div>
    );
  }

  if (error && !inverterStatus) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center bg-white rounded-lg p-8 shadow-sm">
          <AlertTriangle className="h-8 w-8 text-red-500 mx-auto mb-4" />
          <p className="text-red-600 mb-4">{error}</p>
          <button
            onClick={loadData}
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        
        {/* Header */}
        <div className="bg-white rounded-lg p-6 shadow-sm">
          <div className="flex justify-between items-center">
            <div>
              <h1 className="text-2xl font-bold text-gray-900 flex items-center">
                <Zap className="h-6 w-6 mr-2 text-blue-600" />
                Inverter Status Dashboard
              </h1>
              <p className="text-gray-600 mt-1">Real-time battery and inverter monitoring</p>
            </div>
            <div className="flex items-center space-x-3">
              <div className="text-sm text-gray-500">
                Last updated: {lastUpdate.toLocaleTimeString()}
              </div>
              <button
                onClick={loadData}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center space-x-2"
              >
                <RefreshCw className="h-4 w-4" />
                <span>Refresh</span>
              </button>
            </div>
          </div>
        </div>

        {/* Error Display */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <div className="flex items-center">
              <AlertTriangle className="h-5 w-5 text-red-500 mr-2" />
              <span className="text-red-700">{error}</span>
            </div>
          </div>
        )}

        {/* Main Status Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          
          {/* Battery SOC */}
          <div className="bg-white rounded-lg p-6 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900">Battery SOC</h3>
              <Battery className={`h-6 w-6 ${
                (inverterStatus?.battery_soc || 0) > 80 ? 'text-green-600' :
                (inverterStatus?.battery_soc || 0) > 40 ? 'text-yellow-600' : 'text-red-600'
              }`} />
            </div>
            <div className="text-3xl font-bold text-gray-900 mb-2">
              {inverterStatus?.battery_soc?.toFixed(1) || 'N/A'}%
            </div>
            <div className="text-sm text-gray-600">
              SOE: {inverterStatus?.battery_soe?.toFixed(1) || 'N/A'} kWh
            </div>
          </div>

          {/* Battery Power */}
          <div className="bg-white rounded-lg p-6 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900">Battery Power</h3>
              <Power className="h-6 w-6 text-blue-600" />
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600">Charging:</span>
                <span className="text-green-600 font-medium">
                  {inverterStatus?.battery_charge_power?.toFixed(1) || '0'} kW
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600">Discharging:</span>
                <span className="text-red-600 font-medium">
                  {inverterStatus?.battery_discharge_power?.toFixed(1) || '0'} kW
                </span>
              </div>
            </div>
          </div>

          {/* Grid Charge Status */}
          <div className="bg-white rounded-lg p-6 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900">Grid Charge</h3>
              <Settings className="h-6 w-6 text-gray-600" />
            </div>
            <div className="flex items-center justify-between">
              <span className={`px-3 py-1 rounded-full text-sm font-medium ${
                inverterStatus?.grid_charge_enabled ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'
              }`}>
                {inverterStatus?.grid_charge_enabled ? 'Enabled' : 'Disabled'}
              </span>
              <button
                onClick={handleGridChargeToggle}
                className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
                  inverterStatus?.grid_charge_enabled
                    ? 'bg-red-600 hover:bg-red-700 text-white'
                    : 'bg-green-600 hover:bg-green-700 text-white'
                }`}
              >
                {inverterStatus?.grid_charge_enabled ? 'Disable' : 'Enable'}
              </button>
            </div>
          </div>

          {/* Current Strategy */}
          <div className="bg-white rounded-lg p-6 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900">Current Strategy</h3>
              <Target className="h-6 w-6 text-purple-600" />
            </div>
            {currentHourData ? (
              <div className="space-y-2">
                <div className="px-3 py-1 rounded text-sm font-medium bg-gray-100 text-gray-800">
                  {typeof currentHourData.batteryAction === 'number' ? 
                    (currentHourData.batteryAction > 0 ? 'CHARGE' : 
                     currentHourData.batteryAction < 0 ? 'DISCHARGE' : 'IDLE') :
                    currentHourData.batteryAction || 'IDLE'}
                </div>
                <div className="px-3 py-1 rounded text-xs bg-gray-100 text-gray-800">
                  {currentHourData.strategicIntent || 'NO_INTENT'}
                </div>
              </div>
            ) : (
              <div className="text-gray-500 text-sm">No strategy data</div>
            )}
          </div>
        </div>

        {/* Detailed Settings and Schedules */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          
          {/* Battery Settings */}
          <div className="bg-white rounded-lg p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Battery Settings</h3>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-gray-600">Charge Stop SOC:</span>
                <span className="font-medium">{inverterStatus?.charge_stop_soc || 'N/A'}%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Discharge Stop SOC:</span>
                <span className="font-medium">{inverterStatus?.discharge_stop_soc || 'N/A'}%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Discharge Power Rate:</span>
                <span className="font-medium">{inverterStatus?.discharge_power_rate || 'N/A'}%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Max Charging Power:</span>
                <span className="font-medium">{inverterStatus?.max_charging_power || 'N/A'} kW</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Max Discharging Power:</span>
                <span className="font-medium">{inverterStatus?.max_discharging_power || 'N/A'} kW</span>
              </div>
            </div>
          </div>

          {/* TOU Settings */}
          <div className="bg-white rounded-lg p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">TOU Settings</h3>
            {growattSchedule?.tou_intervals ? (
              <div className="space-y-2">
                {growattSchedule.tou_intervals.map((interval, index) => (
                  <div key={index} className="flex justify-between items-center p-2 bg-gray-50 rounded">
                    <div>
                      <span className="font-medium">#{interval.segment_id}</span>
                      <span className="ml-2 text-sm text-gray-600">
                        {interval.start_time} - {interval.end_time}
                      </span>
                    </div>
                    <div className="flex items-center space-x-2">
                      <span className="px-2 py-1 rounded text-xs bg-blue-100 text-blue-800">
                        {interval.batt_mode}
                      </span>
                      <span className="px-2 py-1 rounded text-xs bg-green-100 text-green-800">
                        {interval.enabled ? 'Active' : 'Disabled'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-gray-500 text-sm">No TOU intervals configured</div>
            )}
          </div>
        </div>

        {/* Strategic Intent Intervals */}
        <div className="bg-white rounded-lg p-6 shadow-sm">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Strategic Intent Intervals</h3>
          {growattSchedule?.strategic_intent_periods ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Intent</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Mode</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Grid Charge</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Charge Power</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Discharge Power</th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {growattSchedule.strategic_intent_periods.map((period, index) => (
                    <tr key={index}>
                      <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-900">
                        {period.start_time} - {period.end_time} ({period.hours_span}h)
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-900">
                        {period.strategic_intent}
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-900">
                        {period.battery_mode}
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-900">
                        {period.grid_charge ? 'Yes' : 'No'}
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-900">
                        {period.charge_power_rate}%
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-900">
                        {period.discharge_power_rate}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-gray-500 text-sm">No strategic intent periods available</div>
          )}
        </div>

        {/* Hourly Schedule Table */}
        {dashboardData?.hourlyData && (
          <div className="bg-white rounded-lg p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">24-Hour Schedule</h3>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Hour</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Strategic Intent</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Energy Action</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Power Rate</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Grid Charge</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">SOC</th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {dashboardData.hourlyData.map((hour, index) => {
                    const isCurrentHour = hour.hour === dashboardData.currentHour;
                    
                    // Row styling based on actual/predicted/current (restored original)
                    let rowClass = 'border-l-4 ';
                    if (isCurrentHour) {
                      rowClass += 'bg-purple-50 border-purple-400';
                    } else if (hour.isActual) {
                      rowClass += 'bg-gray-50 border-green-400';
                    } else {
                      rowClass += 'bg-white border-gray-200';
                    }
                    
                    return (
                      <tr key={index} className={rowClass}>
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                          <div className="flex items-center">
                            {hour.hour.toString().padStart(2, '0')}:00
                            {hour.isActual && (
                              <span className="ml-2 text-xs bg-green-100 text-green-700 px-2 py-1 rounded">
                                Actual
                              </span>
                            )}
                            {!hour.isActual && !isCurrentHour && (
                              <span className="ml-2 text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded">
                                Predicted
                              </span>
                            )}
                            {isCurrentHour && (
                              <span className="ml-2 text-xs bg-purple-100 text-purple-700 px-2 py-1 rounded">
                                Current
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                          <div className={`px-3 py-1 rounded-full text-sm ${
                            hour.strategicIntent === 'SOLAR_STORAGE' ? 'bg-yellow-100 text-yellow-800' :
                            hour.strategicIntent === 'LOAD_SUPPORT' ? 'bg-blue-100 text-blue-800' :
                            hour.strategicIntent === 'EXPORT_ARBITRAGE' ? 'bg-green-100 text-green-800' :
                            hour.strategicIntent === 'GRID_CHARGING' ? 'bg-purple-100 text-purple-800' :
                            'bg-gray-100 text-gray-800'
                          }`}>
                            {hour.strategicIntent?.replace('_', ' ') || 'IDLE'}
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                          {hour.batteryCharged > 0 && (
                            <div className="flex items-center text-green-600">
                              <span className="text-xs mr-1">⚡</span>
                              <span className="font-medium">Charge {hour.batteryCharged.toFixed(1)}kWh</span>
                            </div>
                          )}
                          {hour.batteryDischarged > 0 && (
                            <div className="flex items-center text-orange-600">
                              <span className="text-xs mr-1">⚡</span>
                              <span className="font-medium">Discharge {hour.batteryDischarged.toFixed(1)}kWh</span>
                            </div>
                          )}
                          {hour.batteryCharged === 0 && hour.batteryDischarged === 0 && (
                            <div className="flex items-center text-gray-500">
                              <span className="text-xs mr-1">⏸️</span>
                              <span>Idle</span>
                            </div>
                          )}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                          {hour.batteryCharged > 0 ? `${hour.batteryCharged.toFixed(1)}kW` : ''}
                          {hour.batteryDischarged > 0 ? `${hour.batteryDischarged.toFixed(1)}kW` : ''}
                          {hour.batteryCharged === 0 && hour.batteryDischarged === 0 ? '0kW' : ''}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                          <div className={`px-2 py-1 rounded text-xs font-medium ${
                            hour.gridCharge ? 'bg-red-100 text-red-800' : 'bg-gray-100 text-gray-800'
                          }`}>
                            {hour.gridCharge ? '✓ Enabled' : '✗ Disabled'}
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                          <div className="flex items-center">
                            <div className={`w-3 h-3 rounded-full mr-2 ${
                              (hour.batterySocEnd || 0) > 80 ? 'bg-green-500' :
                              (hour.batterySocEnd || 0) > 40 ? 'bg-yellow-500' : 'bg-red-500'
                            }`}></div>
                            <span className="font-medium">{hour.batterySocEnd?.toFixed(1) || 'N/A'}%</span>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

      </div>
    </div>
  );
};

export default InverterStatusDashboard;