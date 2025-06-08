import React, { useState, useEffect } from 'react';
import { 
  Battery, 
  Zap, 
  Power, 
  Settings, 
  Clock, 
  ArrowUp, 
  ArrowDown, 
  Minus,
  RefreshCw,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Calendar,
  Activity,
  Target,
  DollarSign,
  List,
  BarChart3
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

interface TOUInterval {
  segment_id: number;
  start_time: string;
  end_time: string;
  batt_mode: string;
  enabled: boolean;
  grid_charge?: boolean;
  discharge_rate?: number;
  strategic_intent?: string;
  action?: string;
  action_color?: string;
}

interface ScheduleHour {
  hour: number;
  mode: string;
  battery_mode: string;
  grid_charge: boolean;
  discharge_rate: number;
  state: string;
  strategic_intent: string;
  action: string;
  action_color: string;
  battery_action: number;
  soc: number;
  price: number;
  grid_power: number;
  is_current: boolean;
}

interface GrowattSchedule {
  current_hour: number;
  tou_intervals: TOUInterval[];
  schedule_data: ScheduleHour[];
  last_updated: string;
  summary: {
    charge_hours: number;
    discharge_hours: number;
    idle_hours: number;
    active_hours: number;
    mode_distribution: Record<string, number>;
    intent_distribution: Record<string, number>;
    efficiency_metrics: {
      utilization_rate: number;
      charge_discharge_ratio: number;
    };
  };
}

// Consolidated schedule period interface
interface SchedulePeriod {
  id: string;
  start_time: string;
  end_time: string;
  hours_span: number;
  battery_mode: string;
  strategic_intent: string;
  grid_charge: boolean;
  discharge_rate: number;
  is_active: boolean;
  description: string;
  action_summary: string;
}

const InverterStatusDashboard: React.FC = () => {
  const [inverterStatus, setInverterStatus] = useState<InverterStatus | null>(null);
  const [growattSchedule, setGrowattSchedule] = useState<GrowattSchedule | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());

  // Fetch inverter status
  const fetchInverterStatus = async (): Promise<InverterStatus> => {
    const response = await api.get('/api/growatt/inverter_status');
    return response.data;
  };

  // Fetch Growatt schedule
  const fetchGrowattSchedule = async (): Promise<GrowattSchedule> => {
    const response = await api.get('/api/growatt/detailed_schedule');
    return response.data;
  };
  
  // Load all data
  const loadData = async (): Promise<void> => {
    try {
      setError(null);
      const [statusData, scheduleData] = await Promise.all([
        fetchInverterStatus(),
        fetchGrowattSchedule()
      ]);
      setInverterStatus(statusData);
      setGrowattSchedule(scheduleData);
      setLastUpdate(new Date());
    } catch (err) {
      console.error('Error loading data:', err);
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setLoading(false);
    }
  };

  // Initial load
  useEffect(() => {
    loadData();
  }, []);

  // Auto-refresh every 30 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      loadData();
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  // Manual refresh
  const handleRefresh = async (): Promise<void> => {
    setLoading(true);
    await loadData();
  };

  // Helper functions
  const formatPower = (power: number): string => {
    if (Math.abs(power) >= 1000) {
      return `${(power / 1000).toFixed(1)} kW`;
    }
    return `${power.toFixed(0)} W`;
  };

  const getBatteryColor = (soc: number): string => {
    if (soc >= 80) return 'text-green-600';
    if (soc >= 50) return 'text-yellow-600';
    if (soc >= 20) return 'text-orange-600';
    return 'text-red-600';
  };

  const getStrategicIntentIcon = (intent: string): React.ReactNode => {
    switch (intent) {
      case 'GRID_CHARGING':
        return <Power className="h-4 w-4 text-blue-600" />;
      case 'SOLAR_STORAGE':
        return <Battery className="h-4 w-4 text-green-600" />;
      case 'LOAD_SUPPORT':
        return <Activity className="h-4 w-4 text-orange-600" />;
      case 'EXPORT_ARBITRAGE':
        return <DollarSign className="h-4 w-4 text-red-600" />;
      default:
        return <Target className="h-4 w-4 text-gray-600" />;
    }
  };

  const getStrategicIntentColor = (intent: string): string => {
    switch (intent) {
      case 'GRID_CHARGING':
        return 'bg-blue-100 text-blue-800 border-blue-200';
      case 'SOLAR_STORAGE':
        return 'bg-green-100 text-green-800 border-green-200';
      case 'LOAD_SUPPORT':
        return 'bg-orange-100 text-orange-800 border-orange-200';
      case 'EXPORT_ARBITRAGE':
        return 'bg-red-100 text-red-800 border-red-200';
      default:
        return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };

  const getStrategicIntentDescription = (intent: string): string => {
    switch (intent) {
      case 'GRID_CHARGING':
        return 'Storing cheap grid energy for later use';
      case 'SOLAR_STORAGE':
        return 'Storing excess solar energy';
      case 'LOAD_SUPPORT':
        return 'Supporting home consumption';
      case 'EXPORT_ARBITRAGE':
        return 'Exporting for profit';
      default:
        return 'No significant activity';
    }
  };

  const getModeColor = (mode: string): string => {
    switch (mode.toLowerCase()) {
      case 'battery-first':
        return 'bg-blue-100 text-blue-800 border-blue-200';
      case 'grid-first':
        return 'bg-purple-100 text-purple-800 border-purple-200';
      case 'load-first':
        return 'bg-green-100 text-green-800 border-green-200';
      default:
        return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };

  // Convert schedule data to consolidated periods
  const getConsolidatedPeriods = (): SchedulePeriod[] => {
    if (!growattSchedule) return [];

    const periods: SchedulePeriod[] = [];
    const currentHour = growattSchedule.current_hour;

    // Group consecutive hours with same settings
    let currentPeriod: SchedulePeriod | null = null;
    
    for (const hourData of growattSchedule.schedule_data) {
      const needsNewPeriod = !currentPeriod || 
        currentPeriod.battery_mode !== hourData.battery_mode ||
        currentPeriod.strategic_intent !== hourData.strategic_intent ||
        currentPeriod.grid_charge !== hourData.grid_charge ||
        currentPeriod.discharge_rate !== hourData.discharge_rate;

      if (needsNewPeriod) {
        // Save previous period
        if (currentPeriod) {
          periods.push(currentPeriod);
        }

        // Start new period
        const startHour = hourData.hour;
        const isActive = startHour <= currentHour;
        
        // Determine action summary - distinguish between programmed actions and natural behavior
        let actionSummary = 'Natural Operation';
        if (hourData.grid_charge) {
          actionSummary = 'Forced Grid Charging';
        } else if (hourData.discharge_rate > 0) {
          actionSummary = `Forced Discharge (${hourData.discharge_rate}%)`;
        } else if (hourData.strategic_intent === 'SOLAR_STORAGE') {
          actionSummary = 'Solar Priority';
        } else if (hourData.strategic_intent === 'LOAD_SUPPORT') {
          actionSummary = 'Load Support Priority';
        } else if (hourData.strategic_intent === 'EXPORT_ARBITRAGE') {
          actionSummary = 'Export Priority';
        } else if (hourData.strategic_intent === 'GRID_CHARGING') {
          actionSummary = 'Grid Charge Priority';
        }

        currentPeriod = {
          id: `period-${periods.length}`,
          start_time: `${startHour.toString().padStart(2, '0')}:00`,
          end_time: `${startHour.toString().padStart(2, '0')}:59`, // Will be updated
          hours_span: 1,
          battery_mode: hourData.battery_mode,
          strategic_intent: hourData.strategic_intent,
          grid_charge: hourData.grid_charge,
          discharge_rate: hourData.discharge_rate,
          is_active: isActive,
          description: getStrategicIntentDescription(hourData.strategic_intent),
          action_summary: actionSummary
        };
      } else {
        // Extend current period
        if (currentPeriod) {
          currentPeriod.end_time = `${hourData.hour.toString().padStart(2, '0')}:59`;
          currentPeriod.hours_span += 1;
          
          // Update active status if any hour in period is current/past
          if (hourData.hour <= currentHour) {
            currentPeriod.is_active = true;
          }
        }
      }
    }

    // Add final period
    if (currentPeriod) {
      periods.push(currentPeriod);
    }

    return periods;
  };

  const consolidatedPeriods = getConsolidatedPeriods();

  if (loading && !inverterStatus && !growattSchedule) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 p-6">
        <div className="max-w-7xl mx-auto">
          <div className="bg-white rounded-xl shadow-lg p-8 text-center">
            <div className="animate-spin h-12 w-12 border-4 border-blue-500 rounded-full border-t-transparent mx-auto mb-4"></div>
            <h2 className="text-xl font-semibold text-gray-900 mb-2">Loading Inverter Data</h2>
            <p className="text-gray-600">Fetching real-time status and schedule with strategic intents...</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        
        {/* Header */}
        <div className="bg-white rounded-xl shadow-lg p-6">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between">
            <div className="mb-4 sm:mb-0">
              <h1 className="text-3xl font-bold text-gray-900 flex items-center">
                <Zap className="h-8 w-8 text-blue-600 mr-3" />
                Inverter Control Center
              </h1>
              <p className="text-gray-600 mt-1">Real-time inverter status and strategic battery management</p>
            </div>
            
            <div className="flex items-center space-x-4">
              <div className="text-sm text-gray-500">
                Last updated: {lastUpdate.toLocaleTimeString()}
              </div>
              <button
                onClick={handleRefresh}
                disabled={loading}
                className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
                Refresh
              </button>
            </div>
          </div>
        </div>

        {/* Error Display */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-4">
            <div className="flex items-center">
              <AlertTriangle className="h-5 w-5 text-red-600 mr-2" />
              <span className="text-red-800 font-medium">Error: {error}</span>
            </div>
          </div>
        )}

        {/* Real-time Inverter Status */}
        <div className="bg-white rounded-xl shadow-lg overflow-hidden">
          <div className="bg-gradient-to-r from-blue-600 to-blue-700 px-6 py-4">
            <h2 className="text-xl font-bold text-white flex items-center">
              <Activity className="h-6 w-6 mr-2" />
              Real-time Inverter Status
            </h2>
          </div>
          
          {inverterStatus ? (
            <div className="p-6">
              {/* Battery Status Row */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                <div className="bg-gradient-to-br from-green-50 to-green-100 rounded-xl p-6 border border-green-200">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-semibold text-gray-900">Battery Status</h3>
                    <Battery className={`h-8 w-8 ${getBatteryColor(inverterStatus.battery_soc)}`} />
                  </div>
                  <div className="space-y-3">
                    <div className="flex justify-between items-center">
                      <span className="text-gray-600">State of Charge:</span>
                      <span className={`text-2xl font-bold ${getBatteryColor(inverterStatus.battery_soc)}`}>
                        {inverterStatus.battery_soc.toFixed(1)}%
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-gray-600">State of Energy:</span>
                      <span className="text-lg font-semibold text-gray-900">
                        {inverterStatus.battery_soe.toFixed(1)} kWh
                      </span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-3">
                      <div 
                        className={`h-3 rounded-full transition-all duration-300 ${
                          inverterStatus.battery_soc >= 80 ? 'bg-green-500' :
                          inverterStatus.battery_soc >= 50 ? 'bg-yellow-500' :
                          inverterStatus.battery_soc >= 20 ? 'bg-orange-500' : 'bg-red-500'
                        }`}
                        style={{ width: `${Math.max(0, Math.min(100, inverterStatus.battery_soc))}%` }}
                      ></div>
                    </div>
                  </div>
                </div>

                <div className="bg-gradient-to-br from-blue-50 to-blue-100 rounded-xl p-6 border border-blue-200">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-semibold text-gray-900">Power Flow</h3>
                    <Power className="h-8 w-8 text-blue-600" />
                  </div>
                  <div className="space-y-3">
                    <div className="flex justify-between items-center">
                      <span className="text-gray-600">Charge Power:</span>
                      <span className="text-lg font-semibold text-green-600">
                        {formatPower(inverterStatus.battery_charge_power)}
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-gray-600">Discharge Power:</span>
                      <span className="text-lg font-semibold text-red-600">
                        {formatPower(inverterStatus.battery_discharge_power)}
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-gray-600">Grid Charging:</span>
                      <span className={`text-lg font-semibold ${inverterStatus.grid_charge_enabled ? 'text-green-600' : 'text-gray-400'}`}>
                        {inverterStatus.grid_charge_enabled ? 'Enabled' : 'Disabled'}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="bg-gradient-to-br from-purple-50 to-purple-100 rounded-xl p-6 border border-purple-200">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-semibold text-gray-900">Limits & Rates</h3>
                    <Settings className="h-8 w-8 text-purple-600" />
                  </div>
                  <div className="space-y-3">
                    <div className="flex justify-between items-center">
                      <span className="text-gray-600">Charge Stop:</span>
                      <span className="text-lg font-semibold text-gray-900">
                        {inverterStatus.charge_stop_soc.toFixed(0)}%
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-gray-600">Discharge Stop:</span>
                      <span className="text-lg font-semibold text-gray-900">
                        {inverterStatus.discharge_stop_soc.toFixed(0)}%
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-gray-600">Discharge Rate:</span>
                      <span className="text-lg font-semibold text-gray-900">
                        {inverterStatus.discharge_power_rate.toFixed(0)}%
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Power Limits */}
              <div className="bg-gray-50 rounded-xl p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4">Maximum Power Capabilities</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="flex justify-between items-center p-4 bg-white rounded-lg shadow-sm">
                    <span className="text-gray-600 flex items-center">
                      <ArrowUp className="h-5 w-5 text-green-600 mr-2" />
                      Max Charging Power:
                    </span>
                    <span className="text-xl font-bold text-green-600">
                      {formatPower(inverterStatus.max_charging_power)}
                    </span>
                  </div>
                  <div className="flex justify-between items-center p-4 bg-white rounded-lg shadow-sm">
                    <span className="text-gray-600 flex items-center">
                      <ArrowDown className="h-5 w-5 text-red-600 mr-2" />
                      Max Discharging Power:
                    </span>
                    <span className="text-xl font-bold text-red-600">
                      {formatPower(inverterStatus.max_discharging_power)}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="p-6 text-center text-gray-500">
              <XCircle className="h-12 w-12 mx-auto mb-4 text-gray-400" />
              <p>Inverter status data not available</p>
            </div>
          )}
        </div>

        {/* Strategic Battery Schedule - List View */}
        <div className="bg-white rounded-xl shadow-lg overflow-hidden">
          <div className="bg-gradient-to-r from-green-600 to-green-700 px-6 py-4">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-bold text-white flex items-center">
                <List className="h-6 w-6 mr-2" />
                Strategic Battery Schedule & TOU Settings
              </h2>
              {growattSchedule && (
                <div className="text-green-100 text-sm">
                  Current Hour: {growattSchedule.current_hour}:00
                </div>
              )}
            </div>
          </div>
          
          {growattSchedule ? (
            <div className="p-6">
              {/* Schedule Summary */}
              <div className="mb-6 grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="bg-green-50 p-4 rounded-lg text-center border border-green-200">
                  <div className="text-2xl font-bold text-green-600">{growattSchedule.summary.charge_hours}</div>
                  <div className="text-sm text-gray-600">Charge Hours</div>
                </div>
                <div className="bg-red-50 p-4 rounded-lg text-center border border-red-200">
                  <div className="text-2xl font-bold text-red-600">{growattSchedule.summary.discharge_hours}</div>
                  <div className="text-sm text-gray-600">Discharge Hours</div>
                </div>
                <div className="bg-gray-50 p-4 rounded-lg text-center border border-gray-200">
                  <div className="text-2xl font-bold text-gray-600">{growattSchedule.summary.idle_hours}</div>
                  <div className="text-sm text-gray-600">Idle Hours</div>
                </div>
                <div className="bg-blue-50 p-4 rounded-lg text-center border border-blue-200">
                  <div className="text-2xl font-bold text-blue-600">{growattSchedule.summary.efficiency_metrics.utilization_rate.toFixed(1)}%</div>
                  <div className="text-sm text-gray-600">Utilization Rate</div>
                </div>
              </div>

              {/* Strategic Intent Distribution */}
              {growattSchedule.summary.intent_distribution && (
                <div className="mb-6 bg-gradient-to-r from-indigo-50 to-purple-50 rounded-xl p-6 border border-indigo-200">
                  <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center">
                    <Target className="h-5 w-5 mr-2 text-indigo-600" />
                    Strategic Intent Distribution
                  </h3>
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                    {Object.entries(growattSchedule.summary.intent_distribution).map(([intent, count]) => (
                      <div key={intent} className={`p-3 rounded-lg border text-center ${getStrategicIntentColor(intent)}`}>
                        <div className="flex items-center justify-center mb-1">
                          {getStrategicIntentIcon(intent)}
                          <span className="ml-1 text-lg font-bold">{count}</span>
                        </div>
                        <div className="text-xs font-medium">{intent.replace('_', ' ')}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Consolidated Schedule Periods - List View */}
              <div>
                <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center">
                  <BarChart3 className="h-5 w-5 mr-2" />
                  Schedule Periods ({consolidatedPeriods.length} periods)
                </h3>
                
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          Time Period
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          Duration
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          Strategic Intent
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          Battery Mode
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          Programmed Action
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          Current Reality
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          Grid Charge
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          Discharge Rate
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          Status
                        </th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                      {consolidatedPeriods.map((period) => (
                        <tr 
                          key={period.id} 
                          className={`${period.is_active ? 'bg-blue-50' : 'bg-white'} hover:bg-gray-50`}
                        >
                          <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                            <div className="flex items-center">
                              <Clock className="h-4 w-4 text-gray-400 mr-2" />
                              {period.start_time} - {period.end_time}
                            </div>
                          </td>
                          
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            <span className="bg-gray-100 text-gray-800 px-2 py-1 rounded text-xs font-medium">
                              {period.hours_span}h
                            </span>
                          </td>
                          
                          <td className="px-6 py-4 whitespace-nowrap">
                            <div className="flex flex-col">
                              <span className={`inline-flex items-center px-2 py-1 text-xs font-semibold rounded-full border ${getStrategicIntentColor(period.strategic_intent)}`}>
                                {getStrategicIntentIcon(period.strategic_intent)}
                                <span className="ml-1">{period.strategic_intent.replace('_', ' ')}</span>
                              </span>
                              <span className="text-xs text-gray-500 mt-1 italic">
                                {period.description}
                              </span>
                            </div>
                          </td>
                          
                          <td className="px-6 py-4 whitespace-nowrap">
                            <span className={`inline-flex px-2 py-1 text-xs font-semibold rounded border ${getModeColor(period.battery_mode)}`}>
                              {period.battery_mode}
                            </span>
                          </td>
                          
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            <div className="font-medium">
                              {period.action_summary}
                            </div>
                          </td>
                          
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            {period.is_active && period.start_time.startsWith(growattSchedule.current_hour.toString().padStart(2, '0')) ? (
                              <div className="flex flex-col">
                                <div className="flex items-center">
                                  {(inverterStatus?.battery_charge_power ?? 0) > 100 ? (
                                    <ArrowUp className="h-4 w-4 text-green-600 mr-1" />
                                  ) : (inverterStatus?.battery_discharge_power ?? 0) > 100 ? (
                                    <ArrowDown className="h-4 w-4 text-red-600 mr-1" />
                                  ) : (
                                    <Minus className="h-4 w-4 text-gray-600 mr-1" />
                                  )}
                                  <span className={`font-medium ${
                                    (inverterStatus?.battery_charge_power ?? 0) > 100 ? 'text-green-600' :
                                    (inverterStatus?.battery_discharge_power ?? 0) > 100 ? 'text-red-600' :
                                    'text-gray-600'
                                  }`}>
                                    {(inverterStatus?.battery_charge_power ?? 0) > 100 ? (
                                      `Charging ${formatPower(inverterStatus?.battery_charge_power ?? 0)}`
                                    ) : (inverterStatus?.battery_discharge_power ?? 0) > 100 ? (
                                      `Discharging ${formatPower(inverterStatus?.battery_discharge_power ?? 0)}`
                                    ) : (
                                      'Idle'
                                    )}
                                  </span>
                                </div>
                                <div className="text-xs text-gray-500">
                                  Real-time: {inverterStatus?.grid_charge_enabled ? 'Grid charging enabled' : 'Natural operation'}
                                </div>
                              </div>
                            ) : (
                              <span className="text-gray-400 text-sm">
                                {period.is_active ? 'Different hour' : 'Not active'}
                              </span>
                            )}
                          </td>
                          
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            <span className={`flex items-center ${period.grid_charge ? 'text-green-600' : 'text-gray-400'}`}>
                              {period.grid_charge ? <CheckCircle className="h-4 w-4 mr-1" /> : <XCircle className="h-4 w-4 mr-1" />}
                              {period.grid_charge ? 'Enabled' : 'Disabled'}
                            </span>
                          </td>
                          
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            <span className={`font-medium ${period.discharge_rate > 0 ? 'text-red-600' : 'text-gray-400'}`}>
                              {period.discharge_rate}%
                            </span>
                          </td>
                          
                          <td className="px-6 py-4 whitespace-nowrap">
                            <span className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                              period.is_active 
                                ? 'bg-blue-100 text-blue-800' 
                                : 'bg-gray-100 text-gray-800'
                            }`}>
                              {period.is_active ? 'Active' : 'Upcoming'}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                
                {/* Current Period Highlight */}
                {consolidatedPeriods.length > 0 && (
                  <div className="mt-4 bg-blue-50 border border-blue-200 rounded-lg p-4">
                    <h4 className="font-medium text-blue-800 mb-2 flex items-center">
                      <Activity className="h-4 w-4 mr-2" />
                      Current Status Summary
                    </h4>
                    {(() => {
                      const currentPeriod = consolidatedPeriods.find(p => 
                        p.is_active && p.start_time.startsWith(growattSchedule.current_hour.toString().padStart(2, '0'))
                      );
                      return (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          <div>
                            <h5 className="font-medium text-blue-800 text-sm mb-1">Programmed Strategy:</h5>
                            <div className="text-sm text-blue-700">
                              {currentPeriod ? (
                                <>
                                  <span className="font-medium">{currentPeriod.start_time} - {currentPeriod.end_time}</span>
                                  {' • '}
                                  <span>{currentPeriod.strategic_intent.replace('_', ' ')}</span>
                                  {' • '}
                                  <span>{currentPeriod.action_summary}</span>
                                </>
                              ) : (
                                'No matching period found'
                              )}
                            </div>
                          </div>
                          <div>
                            <h5 className="font-medium text-blue-800 text-sm mb-1">Actual Performance:</h5>
                            <div className="text-sm text-blue-700">
                              <span className="font-medium">
                                {inverterStatus && (inverterStatus.battery_charge_power ?? 0) > 100 ? (
                                  `⚡ Charging at ${formatPower(inverterStatus.battery_charge_power ?? 0)}`
                                ) : inverterStatus && (inverterStatus.battery_discharge_power ?? 0) > 100 ? (
                                  `⚡ Discharging at ${formatPower(inverterStatus.battery_discharge_power ?? 0)}`
                                ) : (
                                  '😴 Battery idle'
                                )}
                              </span>
                              <br />
                              <span>
                                SOC: {inverterStatus?.battery_soc.toFixed(1)}% • 
                                Grid Charge: {inverterStatus?.grid_charge_enabled ? 'ON' : 'OFF'}
                              </span>
                            </div>
                          </div>
                        </div>
                      );
                    })()}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="p-6 text-center text-gray-500">
              <Calendar className="h-12 w-12 mx-auto mb-4 text-gray-400" />
              <p>Schedule data not available</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="text-center text-gray-500 text-sm">
          Data refreshes automatically every 30 seconds • Strategic intents captured at optimization time
        </div>
      </div>
    </div>
  );
};

export default InverterStatusDashboard;