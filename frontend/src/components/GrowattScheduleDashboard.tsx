// src/components/GrowattScheduleDashboard.tsx
import React, { useState, useEffect } from 'react';
import { 
  Battery, 
  Zap, 
  Power, 
  Clock, 
  Settings, 
  RefreshCw, 
  AlertCircle,
  CheckCircle,
  Activity,
  Grid3X3,
  Play,
  Pause,
  Square
} from 'lucide-react';
import api from '../lib/api';

// Types matching the backend data structure
interface InverterStatus {
  battery_soc: number;
  battery_charge_power: number;
  battery_discharge_power: number;
  grid_charge_enabled: boolean;
  charging_power_rate: number;
  discharging_power_rate: number;
  charge_stop_soc: number;
  discharge_stop_soc: number;
  current_mode: string;
  current_power: number;
  power_direction: string;
  current_time: string;
  current_hour: number;
}

interface TOUInterval {
  segment_id: number;
  batt_mode: string;
  start_time: string;
  end_time: string;
  enabled: boolean;
  duration_hours: number;
  start_hour: number;
  end_hour: number;
}

interface ScheduleHour {
  hour: number;
  time_range: string;
  is_current: boolean;
  is_past: boolean;
  is_future: boolean;
  time_context: string;
  tou_interval: TOUInterval | null;
  battery_mode: string;
  grid_charge: boolean;
  discharge_rate: number;
  state: string;
  action: string;
  action_color: string;
  segment_id: number | null;
  interval_enabled: boolean;
}

interface TOUSettings {
  raw_tou_segments: any[];
  processed_tou_settings: TOUInterval[];
  total_intervals: number;
  active_intervals: number;
  last_updated: string;
}

interface DetailedSchedule {
  schedule_data: ScheduleHour[];
  current_hour: number;
  last_updated: string;
  tou_intervals_count: number;
  summary: {
    charge_hours: number;
    discharge_hours: number;
    idle_hours: number;
    active_hours: number;
    mode_distribution: Record<string, number>;
    efficiency_metrics: {
      utilization_rate: number;
      charge_discharge_ratio: number;
    };
  };
}

const GrowattScheduleDashboard: React.FC = () => {
  const [inverterStatus, setInverterStatus] = useState<InverterStatus | null>(null);
  const [touSettings, setTouSettings] = useState<TOUSettings | null>(null);
  const [detailedSchedule, setDetailedSchedule] = useState<DetailedSchedule | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = async () => {
    try {
      setError(null);
      
      const [statusResponse, touResponse, scheduleResponse] = await Promise.allSettled([
        api.get('/api/growatt/inverter_status'),
        api.get('/api/growatt/tou_settings'),
        api.get('/api/growatt/detailed_schedule')
      ]);
      
      if (statusResponse.status === 'fulfilled') {
        setInverterStatus(statusResponse.value.data);
      } else {
        console.error('Failed to fetch inverter status:', statusResponse.reason);
      }
      
      if (touResponse.status === 'fulfilled') {
        setTouSettings(touResponse.value.data);
      } else {
        console.error('Failed to fetch TOU settings:', touResponse.reason);
      }
      
      if (scheduleResponse.status === 'fulfilled') {
        setDetailedSchedule(scheduleResponse.value.data);
      } else {
        console.error('Failed to fetch detailed schedule:', scheduleResponse.reason);
      }
      
      setLastUpdate(new Date());
      
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error occurred');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchData();
    
    // Refresh every 30 seconds
    const interval = setInterval(() => {
      setRefreshing(true);
      fetchData();
    }, 30 * 1000);
    
    return () => clearInterval(interval);
  }, []);

  // Pure presentation functions - no business logic
  const getModeIcon = (mode: string) => {
    switch (mode.toLowerCase()) {
      case 'charging': return <Play className="h-4 w-4 text-green-600" />;
      case 'discharging': return <Square className="h-4 w-4 text-blue-600" />;
      default: return <Pause className="h-4 w-4 text-gray-600" />;
    }
  };

  const getModeColor = (mode: string) => {
    switch (mode.toLowerCase()) {
      case 'charging': return 'text-green-600 bg-green-50';
      case 'discharging': return 'text-blue-600 bg-blue-50';
      default: return 'text-gray-600 bg-gray-50';
    }
  };

  const getActionColor = (color: string) => {
    switch (color) {
      case 'green': return 'text-green-700 bg-green-100';
      case 'blue': return 'text-blue-700 bg-blue-100';
      default: return 'text-gray-700 bg-gray-100';
    }
  };

  const getBatteryModeColor = (mode: string) => {
    switch (mode) {
      case 'battery-first': return 'text-purple-700 bg-purple-100';
      case 'grid-first': return 'text-orange-700 bg-orange-100';
      case 'load-first': return 'text-gray-700 bg-gray-100';
      default: return 'text-gray-700 bg-gray-100';
    }
  };

  if (loading && !inverterStatus) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin h-8 w-8 border-4 border-blue-500 rounded-full border-t-transparent mr-3"></div>
        <span>Loading Growatt data...</span>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6 bg-gray-50 min-h-screen">
      {/* Header */}
      <div className="bg-white p-6 rounded-lg shadow">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 flex items-center">
              <Settings className="h-6 w-6 mr-2 text-green-600" />
              Growatt Inverter Schedule
            </h1>
            <p className="text-gray-600 mt-1">
              Real-time inverter status, TOU settings, and battery schedule monitoring
            </p>
          </div>
          <div className="flex items-center space-x-4">
            <div className="text-sm text-gray-500">
              <Clock className="h-4 w-4 inline mr-1" />
              Last updated: {lastUpdate.toLocaleTimeString()}
            </div>
            <button
              onClick={() => {
                setRefreshing(true);
                fetchData();
              }}
              disabled={refreshing}
              className="flex items-center px-3 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50"
            >
              <RefreshCw className={`h-4 w-4 mr-1 ${refreshing ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </div>
        </div>
      </div>

      {/* Error Display */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex items-center">
            <AlertCircle className="h-5 w-5 text-red-500 mr-2" />
            <span className="text-red-700">{error}</span>
          </div>
        </div>
      )}

      {/* Real-time Inverter Status */}
      {inverterStatus && (
        <div className="bg-white p-6 rounded-lg shadow">
          <h2 className="text-xl font-semibold mb-4 flex items-center">
            <Activity className="h-5 w-5 mr-2 text-blue-600" />
            Real-time Inverter Status
          </h2>
          
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {/* Battery SOC */}
            <div className="bg-gradient-to-r from-green-50 to-green-100 p-4 rounded-lg border">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-medium text-gray-600">Battery SOC</h3>
                  <p className="text-2xl font-bold text-green-600">{inverterStatus.battery_soc}%</p>
                </div>
                <Battery className="h-8 w-8 text-green-500" />
              </div>
              <div className="mt-2">
                <div className="w-full bg-gray-200 rounded-full h-2">
                  <div 
                    className="bg-green-500 h-2 rounded-full transition-all duration-300"
                    style={{ width: `${inverterStatus.battery_soc}%` }}
                  ></div>
                </div>
              </div>
            </div>

            {/* Current Mode */}
            <div className={`p-4 rounded-lg border ${getModeColor(inverterStatus.current_mode)}`}>
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-medium text-gray-600">Current Mode</h3>
                  <p className="text-xl font-bold">{inverterStatus.current_mode}</p>
                  <p className="text-sm">{inverterStatus.current_power}W</p>
                </div>
                {getModeIcon(inverterStatus.current_mode)}
              </div>
            </div>

            {/* Grid Charge Status */}
            <div className="bg-blue-50 p-4 rounded-lg border">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-medium text-gray-600">Grid Charge</h3>
                  <p className="text-xl font-bold text-blue-600">
                    {inverterStatus.grid_charge_enabled ? 'Enabled' : 'Disabled'}
                  </p>
                  <p className="text-sm text-gray-600">Rate: {inverterStatus.charging_power_rate}%</p>
                </div>
                <Zap className={`h-8 w-8 ${inverterStatus.grid_charge_enabled ? 'text-blue-500' : 'text-gray-400'}`} />
              </div>
            </div>

            {/* Discharge Rate */}
            <div className="bg-purple-50 p-4 rounded-lg border">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-medium text-gray-600">Discharge Rate</h3>
                  <p className="text-xl font-bold text-purple-600">{inverterStatus.discharging_power_rate}%</p>
                  <p className="text-sm text-gray-600">SOC: {inverterStatus.discharge_stop_soc}% - {inverterStatus.charge_stop_soc}%</p>
                </div>
                <Power className="h-8 w-8 text-purple-500" />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Raw TOU Settings */}
      {touSettings && (
        <div className="bg-white p-6 rounded-lg shadow">
          <h2 className="text-xl font-semibold mb-4 flex items-center">
            <Grid3X3 className="h-5 w-5 mr-2 text-orange-600" />
            Time of Use (TOU) Settings ({touSettings.active_intervals}/{touSettings.total_intervals} active)
          </h2>
          
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Segment ID
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Time Range
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Battery Mode
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Duration
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {touSettings.processed_tou_settings.map((interval, index) => (
                  <tr key={index} className={index % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                    <td className="px-4 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                      {interval.segment_id}
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-900">
                      {interval.start_time} - {interval.end_time}
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap">
                      <span className={`px-2 py-1 text-xs font-medium rounded-full ${getBatteryModeColor(interval.batt_mode)}`}>
                        {interval.batt_mode}
                      </span>
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap">
                      <span className={`px-2 py-1 text-xs font-medium rounded-full ${
                        interval.enabled ? 'text-green-700 bg-green-100' : 'text-red-700 bg-red-100'
                      }`}>
                        {interval.enabled ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-500">
                      {interval.duration_hours} hours
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Detailed Schedule Table */}
      {detailedSchedule && (
        <div className="bg-white p-6 rounded-lg shadow">
          <h2 className="text-xl font-semibold mb-4 flex items-center">
            <Clock className="h-5 w-5 mr-2 text-green-600" />
            24-Hour Detailed Schedule (Current: {detailedSchedule.current_hour}:00)
          </h2>
          
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Hour
                  </th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    TOU Segment
                  </th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Battery Mode
                  </th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Grid Charge
                  </th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Discharge Rate
                  </th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Action
                  </th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    State
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {detailedSchedule.schedule_data.map((hour) => (
                  <tr 
                    key={hour.hour} 
                    className={`
                      ${hour.is_current ? 'bg-yellow-50 border-l-4 border-yellow-400' : ''}
                      ${hour.is_past ? 'bg-gray-50 opacity-75' : ''}
                      ${hour.is_future ? 'bg-white' : ''}
                    `}
                  >
                    <td className="px-3 py-4 whitespace-nowrap">
                      <div className="flex items-center">
                        <span className={`text-sm font-medium ${
                          hour.is_current ? 'text-yellow-800' : 
                          hour.is_past ? 'text-gray-500' : 'text-gray-900'
                        }`}>
                          {hour.time_range}
                        </span>
                        {hour.is_current && (
                          <span className="ml-2 px-2 py-1 text-xs bg-yellow-200 text-yellow-800 rounded-full">
                            Current
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-4 whitespace-nowrap text-sm text-gray-900">
                      {hour.segment_id || 'N/A'}
                    </td>
                    <td className="px-3 py-4 whitespace-nowrap">
                      <span className={`px-2 py-1 text-xs font-medium rounded-full ${getBatteryModeColor(hour.battery_mode)}`}>
                        {hour.battery_mode}
                      </span>
                    </td>
                    <td className="px-3 py-4 whitespace-nowrap">
                      <div className="flex items-center">
                        {hour.grid_charge ? (
                          <CheckCircle className="h-4 w-4 text-green-500 mr-1" />
                        ) : (
                          <span className="h-4 w-4 text-gray-300 mr-1">○</span>
                        )}
                        <span className="text-sm">{hour.grid_charge ? 'ON' : 'OFF'}</span>
                      </div>
                    </td>
                    <td className="px-3 py-4 whitespace-nowrap text-sm text-gray-900">
                      {hour.discharge_rate}%
                    </td>
                    <td className="px-3 py-4 whitespace-nowrap">
                      <span className={`px-2 py-1 text-xs font-medium rounded-full ${getActionColor(hour.action_color)}`}>
                        {hour.action}
                      </span>
                    </td>
                    <td className="px-3 py-4 whitespace-nowrap text-sm text-gray-500 capitalize">
                      {hour.state}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          
          {/* Legend */}
          <div className="mt-4 bg-gray-50 p-4 rounded-lg">
            <h4 className="text-sm font-medium text-gray-700 mb-2">Legend</h4>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
              <div>
                <h5 className="font-medium text-gray-600 mb-1">Battery Modes</h5>
                <div className="space-y-1">
                  <div className="flex items-center">
                    <span className="px-2 py-1 text-xs rounded-full bg-purple-100 text-purple-700 mr-2">battery-first</span>
                    <span>Prioritize battery usage</span>
                  </div>
                  <div className="flex items-center">
                    <span className="px-2 py-1 text-xs rounded-full bg-orange-100 text-orange-700 mr-2">grid-first</span>
                    <span>Prioritize grid charging</span>
                  </div>
                  <div className="flex items-center">
                    <span className="px-2 py-1 text-xs rounded-full bg-gray-100 text-gray-700 mr-2">load-first</span>
                    <span>Prioritize load demand</span>
                  </div>
                </div>
              </div>
              <div>
                <h5 className="font-medium text-gray-600 mb-1">Actions</h5>
                <div className="space-y-1">
                  <div className="flex items-center">
                    <span className="px-2 py-1 text-xs rounded-full bg-green-100 text-green-700 mr-2">CHARGE</span>
                    <span>Battery charging from grid</span>
                  </div>
                  <div className="flex items-center">
                    <span className="px-2 py-1 text-xs rounded-full bg-blue-100 text-blue-700 mr-2">DISCHARGE</span>
                    <span>Battery discharging to load</span>
                  </div>
                  <div className="flex items-center">
                    <span className="px-2 py-1 text-xs rounded-full bg-gray-100 text-gray-700 mr-2">IDLE</span>
                    <span>No battery action</span>
                  </div>
                </div>
              </div>
              <div>
                <h5 className="font-medium text-gray-600 mb-1">Row Colors</h5>
                <div className="space-y-1">
                  <div className="flex items-center">
                    <div className="w-4 h-4 bg-yellow-100 border-l-4 border-yellow-400 mr-2 rounded"></div>
                    <span>Current hour</span>
                  </div>
                  <div className="flex items-center">
                    <div className="w-4 h-4 bg-gray-100 mr-2 rounded"></div>
                    <span>Past hours</span>
                  </div>
                  <div className="flex items-center">
                    <div className="w-4 h-4 bg-white border mr-2 rounded"></div>
                    <span>Future hours</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Summary Statistics */}
      {detailedSchedule?.summary && (
        <div className="bg-white p-6 rounded-lg shadow">
          <h3 className="text-lg font-semibold mb-4">Schedule Summary & Analytics</h3>
          
          {/* Action Summary */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
            <div className="bg-green-50 p-4 rounded-lg text-center">
              <div className="text-2xl font-bold text-green-600">
                {detailedSchedule.summary.charge_hours}
              </div>
              <div className="text-sm text-gray-600">Charging Hours</div>
            </div>
            <div className="bg-blue-50 p-4 rounded-lg text-center">
              <div className="text-2xl font-bold text-blue-600">
                {detailedSchedule.summary.discharge_hours}
              </div>
              <div className="text-sm text-gray-600">Discharging Hours</div>
            </div>
            <div className="bg-gray-50 p-4 rounded-lg text-center">
              <div className="text-2xl font-bold text-gray-600">
                {detailedSchedule.summary.idle_hours}
              </div>
              <div className="text-sm text-gray-600">Idle Hours</div>
            </div>
            <div className="bg-purple-50 p-4 rounded-lg text-center">
              <div className="text-2xl font-bold text-purple-600">
                {detailedSchedule.tou_intervals_count}
              </div>
              <div className="text-sm text-gray-600">TOU Intervals</div>
            </div>
          </div>

          {/* Efficiency Metrics */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-blue-50 p-4 rounded-lg">
              <h4 className="font-medium text-gray-800 mb-2">Battery Utilization</h4>
              <div className="text-2xl font-bold text-blue-600">
                {detailedSchedule.summary.efficiency_metrics.utilization_rate.toFixed(1)}%
              </div>
              <div className="text-sm text-gray-600">Active usage (charge + discharge) hours</div>
            </div>
            <div className="bg-orange-50 p-4 rounded-lg">
              <h4 className="font-medium text-gray-800 mb-2">Charge/Discharge Ratio</h4>
              <div className="text-2xl font-bold text-orange-600">
                {detailedSchedule.summary.efficiency_metrics.charge_discharge_ratio.toFixed(2)}:1
              </div>
              <div className="text-sm text-gray-600">Balance between charging and discharging</div>
            </div>
          </div>

          {/* Mode Distribution */}
          <div className="mt-4">
            <h4 className="font-medium text-gray-800 mb-2">Battery Mode Distribution</h4>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              {Object.entries(detailedSchedule.summary.mode_distribution).map(([mode, hours]) => (
                <div key={mode} className="flex items-center justify-between p-2 bg-gray-50 rounded">
                  <span className={`px-2 py-1 text-xs rounded ${getBatteryModeColor(mode)}`}>
                    {mode}
                  </span>
                  <span className="font-medium">{hours}h</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default GrowattScheduleDashboard;