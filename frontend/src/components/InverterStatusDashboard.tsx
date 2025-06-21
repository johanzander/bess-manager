import React, { useState, useEffect } from 'react';
import { 
  Battery, 
  Zap, 
  RefreshCw, 
  Clock, 
  Settings, 
  TrendingUp,
  AlertTriangle,
  Calendar
} from 'lucide-react';
import api from '../lib/api';

// FIXED: Updated interface to match actual API response
interface InverterStatus {
  batterySoc: number;
  batterySoe: number;
  batteryChargePower: number;    // ✅ Separate charge power (kW)
  batteryDischargePower: number; // ✅ Separate discharge power (kW)
  pvPower: number;
  consumption: number;
  gridPower: number;
  chargeStopSoc: number;
  dischargeStopSoc: number;
  dischargePowerRate: number;
  maxChargingPower: number;
  maxDischargingPower: number;
  gridChargeEnabled: boolean;
  cycleCost: number;
  systemStatus: string;
  lastUpdated: string;
  // ❌ Removed: batteryMode (not provided by this API)
}

interface TOUInterval {
  segmentId: number;
  startTime: string;
  endTime: string;
  battMode: string;
  enabled: boolean;
}

interface ScheduleHour {
  hour: number;
  strategicIntent: string;
  batteryAction: number;
  batteryCharged: number;
  batteryDischarged: number;
  batterySocEnd: number;
  batteryMode: string;           // ✅ Battery mode comes from schedule data
  chargePowerRate: number;
  dischargePowerRate: number;
  gridCharge: boolean;
  isActual: boolean;
  isPredicted: boolean;
}

interface GrowattSchedule {
  currentHour: number;
  touIntervals: TOUInterval[];
  scheduleData: ScheduleHour[];
  batteryCapacity: number;
  lastUpdated: string;
}

const InverterStatusDashboard: React.FC = () => {
  const [inverterStatus, setInverterStatus] = useState<InverterStatus | null>(null);
  const [growattSchedule, setGrowattSchedule] = useState<GrowattSchedule | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());
  const [isInitialLoad, setIsInitialLoad] = useState(true);

  const fetchInverterStatus = async (): Promise<InverterStatus> => {
    const response = await api.get('/api/growatt/inverter_status');
    return response.data;
  };

  const fetchGrowattSchedule = async (): Promise<GrowattSchedule> => {
    const response = await api.get('/api/growatt/detailed_schedule');
    return response.data;
  };
  
  const loadData = async (isManualRefresh = false): Promise<void> => {
    try {
      if (isInitialLoad || isManualRefresh) {
        setLoading(true);
      }
      setError(null);
      
      const [statusData, scheduleData] = await Promise.all([
        fetchInverterStatus(),
        fetchGrowattSchedule()
      ]);
      
      setInverterStatus(statusData);
      setGrowattSchedule(scheduleData);
      setLastUpdate(new Date());
      
      if (isInitialLoad) {
        setIsInitialLoad(false);
      }
    } catch (err) {
      console.error('Error loading data:', err);
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setLoading(false);
    }
  };

  // Generate complete 24-hour TOU schedule with ALL 9 possible segments plus defaults
  const generateCompleteTOUSchedule = (touIntervals: TOUInterval[]) => {
    const schedule: Array<TOUInterval & { isDefault?: boolean; isEmpty?: boolean }> = [];
    
    // Create all 9 possible TOU segments (Growatt supports up to 9)
    for (let segmentId = 1; segmentId <= 9; segmentId++) {
      const existingSegment = touIntervals.find(interval => interval.segmentId === segmentId);
      
      if (existingSegment) {
        // Use the actual configured segment
        schedule.push(existingSegment);
      } else {
        // Create empty/disabled segment placeholder
        schedule.push({
          segmentId: segmentId,
          startTime: '00:00',
          endTime: '00:00',
          battMode: 'load-first',
          enabled: false,
          isEmpty: true
        });
      }
    }
    
    // Create hourly coverage map to find gaps for default segments
    const coverage = new Array(24).fill(false);
    
    // Mark hours covered by actual (non-empty) TOU intervals
    touIntervals.forEach(interval => {
      const startHour = parseInt(interval.startTime.split(':')[0]);
      const endHour = parseInt(interval.endTime.split(':')[0]);
      
      for (let h = startHour; h <= endHour; h++) {
        coverage[h] = true;
      }
    });
    
    // Add default segments for uncovered hours
    let defaultStart = null;
    for (let hour = 0; hour < 24; hour++) {
      if (!coverage[hour]) {
        if (defaultStart === null) {
          defaultStart = hour;
        }
      } else {
        if (defaultStart !== null) {
          schedule.push({
            segmentId: -1,
            startTime: `${defaultStart.toString().padStart(2, '0')}:00`,
            endTime: `${(hour - 1).toString().padStart(2, '0')}:59`,
            battMode: 'load-first',
            enabled: true,
            isDefault: true
          });
          defaultStart = null;
        }
      }
    }
    
    // Handle final default segment
    if (defaultStart !== null) {
      schedule.push({
        segmentId: -1,
        startTime: `${defaultStart.toString().padStart(2, '0')}:00`,
        endTime: '23:59',
        battMode: 'load-first',
        enabled: true,
        isDefault: true
      });
    }
    
    // Sort: segments 1-9 in numerical order, then default segments by time
    return schedule.sort((a, b) => {
      // If both are default segments, sort by time
      if (a.isDefault && b.isDefault) {
        const aStart = parseInt(a.startTime.split(':')[0]);
        const bStart = parseInt(b.startTime.split(':')[0]);
        return aStart - bStart;
      }
      
      // Default segments go last
      if (a.isDefault) return 1;
      if (b.isDefault) return -1;
      
      // TOU segments (both empty and configured) sort by segment ID
      return a.segmentId - b.segmentId;
    });
  };

  // ✅ FIX 1: Calculate net battery power from separate charge/discharge values
  const calculateBatteryPower = (chargePower: number, dischargePower: number): number => {
    // If discharging, return negative value; if charging, return positive value
    if (dischargePower > 0.01) {
      return -dischargePower; // Discharging (negative)
    } else if (chargePower > 0.01) {
      return chargePower; // Charging (positive)
    }
    return 0; // Idle
  };

  // ✅ FIX 2: Get current battery mode from schedule data instead of inverter status
  const getCurrentBatteryMode = (): string => {
    if (!growattSchedule?.scheduleData) return 'load-first';
    
    const currentHour = new Date().getHours();
    const currentHourData = growattSchedule.scheduleData.find(h => h.hour === currentHour);
    return currentHourData?.batteryMode || 'load-first';
  };

  // ✅ Calculate actual values from the API response
  const netBatteryPower = inverterStatus ? 
    calculateBatteryPower(
      inverterStatus.batteryChargePower || 0, 
      inverterStatus.batteryDischargePower || 0
    ) : 0;

  const currentBatteryMode = getCurrentBatteryMode();

  // Rest of existing functions...
  const getBatteryModeDisplay = (mode: string) => {
    const modes: Record<string, { label: string; color: string }> = {
      'load-first': { label: 'Load First', color: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300' },
      'battery-first': { label: 'Battery First', color: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300' },
      'grid-first': { label: 'Grid First', color: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-300' }
    };
    
    const modeInfo = modes[mode] || { label: mode, color: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300' };
    return (
      <span className={`px-2 py-1 rounded text-xs font-medium ${modeInfo.color}`}>
        {modeInfo.label}
      </span>
    );
  };

  const getIntentColor = (intent: string) => {
    const colors: Record<string, string> = {
      'SOLAR_STORAGE': 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300',
      'LOAD_SUPPORT': 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300',
      'EXPORT_ARBITRAGE': 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300',
      'GRID_CHARGING': 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-300',
      'IDLE': 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'
    };
    return colors[intent] || colors['IDLE'];
  };

  useEffect(() => {
    loadData(false);
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-96">
        <div className="flex items-center space-x-2">
          <RefreshCw className="h-5 w-5 animate-spin text-blue-500" />
          <span className="text-gray-600 dark:text-gray-400">Loading inverter data...</span>
        </div>
      </div>
    );
  }

  const currentHourData = growattSchedule?.scheduleData?.find(h => h.hour === growattSchedule.currentHour);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
        <div className="p-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Inverter Status</h1>
              <p className="text-gray-600 dark:text-gray-400">Real-time system monitoring and control</p>
            </div>
            <button
              onClick={() => loadData(true)}
              disabled={loading}
              className="flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg transition-colors"
            >
              <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
              {loading ? 'Refreshing...' : 'Refresh'}
            </button>
          </div>
        </div>
      </div>

      {/* ✅ FIXED: First 4 Cards using calculated values */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {/* Current Strategy */}
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Current Strategy</h3>
            <TrendingUp className="h-6 w-6 text-green-600" />
          </div>
          {currentHourData ? (
            <div className="space-y-2">
              <div className={`px-3 py-1 rounded text-sm font-medium ${getIntentColor(currentHourData.strategicIntent || 'IDLE')}`}>
                {currentHourData.strategicIntent?.replace('_', ' ') || 'IDLE'}
              </div>
              <div className="text-sm text-gray-600 dark:text-gray-400">
                Hour {currentHourData.hour}:00 - Target SOC: {currentHourData.batterySocEnd?.toFixed(1)}%
              </div>
            </div>
          ) : (
            <div className="text-gray-500 dark:text-gray-400 text-sm">No strategy data</div>
          )}
        </div>

        {/* ✅ FIXED: System Status using calculated battery mode */}
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">System Status</h3>
            <Settings className="h-6 w-6 text-gray-600" />
          </div>
          <div className="space-y-2">
            <div className="text-lg font-medium text-gray-900 dark:text-white">
              {inverterStatus?.systemStatus || 'Online'}
            </div>
            <div className="text-sm text-gray-600 dark:text-gray-400">
              Mode: {getBatteryModeDisplay(currentBatteryMode)}
            </div>
          </div>
        </div>

        {/* Battery SOC/SOE */}
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Battery Level</h3>
            <Battery className={`h-6 w-6 ${
              (inverterStatus?.batterySoc || 0) > 80 ? 'text-green-600' :
              (inverterStatus?.batterySoc || 0) > 40 ? 'text-yellow-600' : 'text-red-600'
            }`} />
          </div>
          <div className="space-y-3">
            <div>
              <div className="text-3xl font-bold text-gray-900 dark:text-white">
                {inverterStatus?.batterySoc?.toFixed(1) || 'N/A'}%
              </div>
              <div className="text-sm text-gray-600 dark:text-gray-400">
                SOC ({(inverterStatus?.batterySoe || 0).toFixed(1)} kWh)
              </div>
            </div>
            <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
              <div 
                className={`h-2 rounded-full transition-all duration-300 ${
                  (inverterStatus?.batterySoc || 0) > 80 ? 'bg-green-600' :
                  (inverterStatus?.batterySoc || 0) > 40 ? 'bg-yellow-600' : 'bg-red-600'
                }`}
                style={{ width: `${Math.min(100, Math.max(0, inverterStatus?.batterySoc || 0))}%` }}
              ></div>
            </div>
          </div>
        </div>

        {/* ✅ FIXED: Battery Power using calculated net power */}
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Battery Power</h3>
            <Zap className="h-6 w-6 text-blue-600" />
          </div>
          <div className="space-y-3">
            <div>
              <div className="text-3xl font-bold text-gray-900 dark:text-white">
                {Math.abs(netBatteryPower).toFixed(1)}kW
              </div>
              <div className="text-sm text-gray-600 dark:text-gray-400">
                {Math.abs(netBatteryPower * 1000).toFixed(0)}W
              </div>
            </div>
            <div className={`text-sm font-medium ${
              netBatteryPower > 0.01 ? 'text-green-600' :
              netBatteryPower < -0.01 ? 'text-orange-600' : 'text-gray-500'
            }`}>
              {netBatteryPower > 0.01 ? 'Charging' :
               netBatteryPower < -0.01 ? 'Discharging' : 'Idle'}
            </div>
          </div>
        </div>
      </div>

      {/* 24-Hour Schedule */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
        <div className="p-6">
          <div className="flex items-center mb-6">
            <Calendar className="h-5 w-5 text-blue-600 mr-2" />
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">24-Hour Schedule Overview</h3>
          </div>
          
          {growattSchedule?.scheduleData ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                <thead className="bg-gray-50 dark:bg-gray-700">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                      Hour
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider" colSpan={3}>
                      Strategic Intent & Goals
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider" colSpan={3}>
                      Inverter Settings
                    </th>
                  </tr>
                  <tr className="bg-gray-50 dark:bg-gray-700">
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-400 dark:text-gray-400">Time</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-400 dark:text-gray-400">Intent</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-400 dark:text-gray-400">Action</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-400 dark:text-gray-400">Target SOC</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-400 dark:text-gray-400">Mode</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-400 dark:text-gray-400">Power Rate</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-400 dark:text-gray-400">Grid Charge</th>
                  </tr>
                </thead>
                <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
                  {growattSchedule.scheduleData.map((hour, index) => {
                    const isCurrentHour = hour.hour === growattSchedule.currentHour;
                    
                    return (
                      <tr key={index} className={`${
                        isCurrentHour ? 'bg-blue-50 dark:bg-blue-900/20' : ''
                      } ${hour.isPredicted ? 'opacity-75' : ''}`}>
                        <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                          <div className="flex items-center">
                            {isCurrentHour && <div className="w-2 h-2 bg-blue-500 rounded-full mr-2"></div>}
                            <span className="font-medium">{hour.hour}:00</span>
                            {hour.isPredicted && <span className="ml-1 text-xs text-gray-500">★</span>}
                          </div>
                        </td>
                        <td className="px-4 py-4 whitespace-nowrap text-sm">
                          <div className={`px-2 py-1 rounded text-xs font-medium ${getIntentColor(hour.strategicIntent || 'IDLE')}`}>
                            {hour.strategicIntent?.replace('_', ' ') || 'IDLE'}
                          </div>
                        </td>
                        <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                          {hour.batteryCharged > 0 && (
                            <div className="flex items-center text-green-600">
                              <span className="text-xs mr-1">⚡</span>
                              <span className="font-medium">+{hour.batteryCharged.toFixed(1)}kWh</span>
                            </div>
                          )}
                          {hour.batteryDischarged > 0 && (
                            <div className="flex items-center text-orange-600">
                              <span className="text-xs mr-1">⚡</span>
                              <span className="font-medium">-{hour.batteryDischarged.toFixed(1)}kWh</span>
                            </div>
                          )}
                          {hour.batteryCharged === 0 && hour.batteryDischarged === 0 && (
                            <div className="flex items-center text-gray-500 dark:text-gray-400">
                              <span className="text-xs mr-1">⏸️</span>
                              <span>Idle</span>
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                          <div className="flex items-center">
                            <div className={`w-3 h-3 rounded-full mr-2 ${
                              (hour.batterySocEnd || 0) > 80 ? 'bg-green-500' :
                              (hour.batterySocEnd || 0) > 40 ? 'bg-yellow-500' : 'bg-red-500'
                            }`}></div>
                            <span className="font-medium">{hour.batterySocEnd?.toFixed(1) || 'N/A'}%</span>
                          </div>
                        </td>
                        <td className="px-4 py-4 whitespace-nowrap text-sm">
                          {getBatteryModeDisplay(hour.batteryMode)}
                        </td>
                        <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                          <div className="space-y-1">
                            {hour.chargePowerRate > 0 && (
                              <div className="text-green-600">C: {hour.chargePowerRate}%</div>
                            )}
                            {hour.dischargePowerRate > 0 && (
                              <div className="text-orange-600">D: {hour.dischargePowerRate}%</div>
                            )}
                            {hour.chargePowerRate === 0 && hour.dischargePowerRate === 0 && (
                              <div className="text-gray-500 dark:text-gray-400">0%</div>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-4 whitespace-nowrap text-sm">
                          <div className={`px-2 py-1 rounded text-xs font-medium ${
                            hour.gridCharge 
                              ? 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300' 
                              : 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'
                          }`}>
                            {hour.gridCharge ? '✓ Enabled' : '✗ Disabled'}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-gray-500 dark:text-gray-400 text-sm">No schedule data available</div>
          )}
        </div>
      </div>

      {/* TOU Intervals - All 9 segments plus defaults in chronological order */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
        <div className="p-6">
          <div className="flex items-center mb-4">
            <Clock className="h-5 w-5 text-blue-600 mr-2" />
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Time of Use (TOU) Intervals</h3>
          </div>
          {growattSchedule?.touIntervals ? (
            <div className="space-y-2">
              {generateCompleteTOUSchedule(growattSchedule.touIntervals).map((interval, index) => (
                <div key={index} className={`flex justify-between items-center p-3 rounded-lg ${
                  interval.isEmpty
                    ? 'bg-gray-100 dark:bg-gray-700/50 opacity-40'
                    : interval.isDefault 
                    ? 'bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600' 
                    : interval.enabled 
                    ? 'bg-gray-50 dark:bg-gray-700'
                    : 'bg-gray-100 dark:bg-gray-700/50 opacity-60'
                }`}>
                  <div className="flex items-center space-x-4">
                    <div className="font-medium text-gray-900 dark:text-white">
                      {interval.isEmpty 
                        ? `Segment #${interval.segmentId}` 
                        : interval.isDefault 
                        ? 'Default' 
                        : `Segment #${interval.segmentId}`}
                    </div>
                    <div className="text-sm text-gray-600 dark:text-gray-400">
                      {interval.isEmpty 
                        ? 'Not configured' 
                        : `${interval.startTime} - ${interval.endTime}`}
                    </div>
                  </div>
                  <div className="flex items-center space-x-3">
                    {!interval.isEmpty && getBatteryModeDisplay(interval.battMode)}
                    <span className={`px-2 py-1 rounded text-xs font-medium ${
                      interval.isEmpty
                        ? 'bg-gray-100 text-gray-500 dark:bg-gray-600 dark:text-gray-400'
                        : interval.isDefault
                        ? 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300'
                        : interval.enabled 
                        ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300' 
                        : 'bg-gray-100 text-gray-800 dark:bg-gray-600 dark:text-gray-300'
                    }`}>
                      {interval.isEmpty 
                        ? 'Empty' 
                        : interval.isDefault 
                        ? 'Default' 
                        : (interval.enabled ? 'Active' : 'Disabled')}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-gray-500 dark:text-gray-400 text-sm">No TOU intervals configured</div>
          )}
        </div>
      </div>

      {/* Battery Configuration - Last and compact */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
        <div className="p-6">
          <div className="flex items-center mb-4">
            <Settings className="h-5 w-5 text-blue-600 mr-2" />
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Battery Configuration</h3>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-gray-600 dark:text-gray-400">Charge Stop SOC:</span>
                <span className="font-medium text-gray-900 dark:text-white">{inverterStatus?.chargeStopSoc || 'N/A'}%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600 dark:text-gray-400">Discharge Stop SOC:</span>
                <span className="font-medium text-gray-900 dark:text-white">{inverterStatus?.dischargeStopSoc || 'N/A'}%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600 dark:text-gray-400">Total Capacity:</span>
                <span className="font-medium text-gray-900 dark:text-white">{growattSchedule?.batteryCapacity || 'N/A'} kWh</span>
              </div>
            </div>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-gray-600 dark:text-gray-400">Max Charging Power:</span>
                <span className="font-medium text-gray-900 dark:text-white">
                  {inverterStatus?.maxChargingPower ? 
                    `${(inverterStatus.maxChargingPower / 1000).toFixed(1)} kW` : 'N/A'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600 dark:text-gray-400">Max Discharging Power:</span>
                <span className="font-medium text-gray-900 dark:text-white">
                  {inverterStatus?.maxDischargingPower ? 
                    `${(inverterStatus.maxDischargingPower / 1000).toFixed(1)} kW` : 'N/A'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600 dark:text-gray-400">Cycle Cost:</span>
                <span className="font-medium text-gray-900 dark:text-white">
                  {inverterStatus?.cycleCost ? `${inverterStatus.cycleCost} SEK/kWh` : 'N/A'}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default InverterStatusDashboard;