import React, { useState, useEffect } from 'react';
import {
  Battery,
  Zap,
  RefreshCw,
  Clock,
  Settings,
  TrendingUp,
  Calendar,
  TrendingDown,
  CheckCircle,
  AlertTriangle,
  Home,
  Sun,
  ChevronRight
} from 'lucide-react';
import api from '../lib/api';

interface InverterStatus {
  batterySoc: number;
  batterySoe: number;
  batteryChargePower: number;
  batteryDischargePower: number;
  pvPower: number;
  consumption: number;
  gridPower: number;
  chargeStopSoc: number;
  dischargeStopSoc: number;
  chargePowerRate: number;
  dischargePowerRate: number;
  dischargeInhibitActive?: boolean;
  maxChargingPower: number;
  maxDischargingPower: number;
  gridChargeEnabled: boolean;
  cycleCost: number;
  systemStatus: string;
  lastUpdated: string;
  inverterPlatform?: string;
  // Formatted fields
  batterySoeCapacityFormatted?: string;
}

interface TOUInterval {
  segmentId: number;
  startTime: string;
  endTime: string;
  battMode: string;
  enabled: boolean;
  isEmpty?: boolean;
  isDefault?: boolean;
  isExpired?: boolean;
  pendingWrite?: boolean;
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
  // Action display fields
  action?: string;
  actionColor?: string;
  // Formatted fields
  batterySocEndFormatted?: string;
}

interface PeriodGroup {
  startTime: string;
  endTime: string;
  mode: string;
  dominantIntent: string;
  intentCounts: Record<string, number>;
  periodCount: number;
  durationMinutes: number;
  chargePowerRate: number;
  dischargePowerRate: number;
  gridCharge: boolean;
  totalActionKwh?: number;
  socEndPct?: number;
  socDeltaKwh?: number | null;
}

interface InverterSchedule {
  currentHour: number;
  inverterPlatform?: string;
  touIntervals: TOUInterval[];
  scheduleData: ScheduleHour[];
  periodGroups: PeriodGroup[];
  tomorrowPeriodGroups: PeriodGroup[] | null;
  batteryCapacity: number;
  lastUpdated: string;
}

// StatusCard component for focused cards
interface StatusCardProps {
  title: string;
  keyMetric: string;
  keyValue: number | string;
  keyUnit: string;
  status: {
    icon: React.ComponentType<{ className?: string }>;
    text: string;
    color: 'green' | 'red' | 'yellow' | 'blue';
  };
  metrics: Array<{
    label: string;
    value: number | string;
    unit: string;
    icon?: React.ComponentType<{ className?: string }>;
    color?: 'green' | 'red' | 'yellow' | 'blue';
    dimmed?: boolean;
    badge?: { text: string; color: 'yellow' | 'red' };
  }>;
  color: 'blue' | 'green' | 'yellow' | 'red' | 'purple';
  icon: React.ComponentType<{ className?: string }>;
  className?: string;
}

const StatusCard: React.FC<StatusCardProps> = ({
  title,
  icon: Icon,
  color,
  keyMetric,
  keyValue,
  keyUnit,
  metrics,
  status,
  className = ""
}) => {
  const colorClasses = {
    blue: 'bg-blue-50 border-blue-200 dark:bg-blue-900/20 dark:border-blue-800',
    green: 'bg-green-50 border-green-200 dark:bg-green-900/20 dark:border-green-800',
    red: 'bg-red-50 border-red-200 dark:bg-red-900/20 dark:border-red-800',
    yellow: 'bg-yellow-50 border-yellow-200 dark:bg-yellow-900/20 dark:border-yellow-800',
    purple: 'bg-purple-50 border-purple-200 dark:bg-purple-900/20 dark:border-purple-800'
  };

  const iconColorClasses = {
    blue: 'text-blue-600 dark:text-blue-400',
    green: 'text-green-600 dark:text-green-400',
    red: 'text-red-600 dark:text-red-400',
    yellow: 'text-yellow-600 dark:text-yellow-400',
    purple: 'text-purple-600 dark:text-purple-400'
  };

  const metricColorClasses: Record<string, string> = {
    green: 'text-green-600 dark:text-green-400',
    red: 'text-red-600 dark:text-red-400',
    yellow: 'text-yellow-600 dark:text-yellow-400',
    blue: 'text-blue-600 dark:text-blue-400'
  };

  return (
    <div className={`border rounded-lg p-6 ${colorClasses[color]} ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center">
          <Icon className={`h-6 w-6 ${iconColorClasses[color]} mr-3`} />
          <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{title}</h3>
        </div>
        {status && (
          <div className={`flex items-center text-sm px-2 py-1 rounded-md ${
            status.color === 'green' ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400' :
            status.color === 'red' ? 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400' :
            status.color === 'yellow' ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400' :
            'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-400'
          }`}>
            <status.icon className="h-4 w-4 mr-1" />
            <span className="font-medium">{status.text}</span>
          </div>
        )}
      </div>

      {/* Key Metric */}
      <div className="mb-6">
        {(keyMetric || keyValue) ? (
          <>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">{keyMetric}</p>
            <p className="text-3xl font-bold text-gray-900 dark:text-gray-100">
              {keyValue}
              {keyUnit && <span className="text-lg font-normal text-gray-600 dark:text-gray-400 ml-2">{keyUnit}</span>}
            </p>
          </>
        ) : (
          <>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-2 invisible">Placeholder</p>
            <p className="text-3xl font-bold text-gray-900 dark:text-gray-100 invisible">Placeholder</p>
          </>
        )}
      </div>

      {/* Metrics */}
      <div className="space-y-3">
        {metrics.map((metric, index) => (
          <div
            key={index}
            className={`flex items-center justify-between ${metric.dimmed ? 'opacity-40' : ''}`}
          >
            <div className="flex items-center">
              {metric.icon && <metric.icon className="h-4 w-4 mr-2 text-gray-500 dark:text-gray-400" />}
              <span className="text-sm text-gray-700 dark:text-gray-300">{metric.label}</span>
            </div>
            <div className="flex items-center gap-2">
              {metric.badge && (
                <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${
                  metric.badge.color === 'yellow'
                    ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400'
                    : 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
                }`}>
                  {metric.badge.text}
                </span>
              )}
              <span className={`text-sm font-semibold ${
                metric.color ? metricColorClasses[metric.color] : 'text-gray-900 dark:text-gray-100'
              }`}>
                {metric.value}
                {metric.unit && <span className="opacity-70 ml-1">{metric.unit}</span>}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

// Helper function for battery mode formatting
const formatBatteryMode = (mode: string): string => {
  switch (mode.toLowerCase()) {
    case 'load_first':
      return 'Load First';
    case 'battery_first':
      return 'Battery First';
    case 'grid_first':
      return 'Grid First';
    default:
      return mode.charAt(0).toUpperCase() + mode.slice(1);
  }
};

interface BatterySettings {
  totalCapacity: number;
  reservedCapacity: number;
  minSoc: number;
  maxSoc: number;
  minSoeKwh: number;
  maxSoeKwh: number;
  maxChargePowerKw: number;
  maxDischargePowerKw: number;
  cycleCostPerKwh: number;
  chargingPowerRate: number;
  dischargingPowerRate: number;
  efficiencyCharge: number;
  efficiencyDischarge: number;
  estimatedConsumption: number;
}

interface DashboardData {
  hourlyData: Array<{
    period: number;
    strategicIntent?: string;
    batteryAction?: number;
    batteryCharged?: number;
    batteryDischarged?: number;
    batterySocEnd?: number;
    batterySoeEnd?: number;
    solarProduction?: number;
    dataSource?: string;
    isActual?: boolean;
    batteryChargedFormatted?: string;
    batteryDischargedFormatted?: string;
    batterySocEndFormatted?: string;
    batteryActionFormatted?: string;
  }>;
  realTimePower?: {
    solarPower?: number;
    gridPower?: number;
    batteryPower?: number;
    homePower?: number;
    solarPowerFormatted?: string;
    gridPowerFormatted?: string;
    batteryPowerFormatted?: string;
    homePowerFormatted?: string;
    batteryChargePowerFormatted?: string;
    batteryDischargePowerFormatted?: string;
    netBatteryPowerFormatted?: string;
  };
}

const InverterStatusDashboard: React.FC = () => {
  const [inverterStatus, setInverterStatus] = useState<InverterStatus | null>(null);
  const [inverterSchedule, setInverterSchedule] = useState<InverterSchedule | null>(null);
  const [batterySettings, setBatterySettings] = useState<BatterySettings | null>(null);
  const [dashboardData, setDashboardData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());
  const [isInitialLoad, setIsInitialLoad] = useState(true);
  const [showTomorrow, setShowTomorrow] = useState(false);

  // Helper function to extract values from FormattedValue objects
  const getValue = (field: any) => {
    if (typeof field === 'object' && field?.value !== undefined) {
      return field.value;
    }
    return field || 0;
  };

  // Helper function to get display text from FormattedValue objects
  const getDisplayText = (field: any) => {
    if (typeof field === 'object' && field?.text !== undefined) {
      return field.text;
    }
    if (typeof field === 'object' && field?.display !== undefined) {
      return field.display;
    }
    return field?.toString() || '-';
  };

  const fetchInverterStatus = async (): Promise<InverterStatus> => {
    const response = await api.get('/api/inverter/status');
    return response.data;
  };

  const fetchInverterSchedule = async (): Promise<InverterSchedule> => {
    const response = await api.get('/api/inverter/schedule');
    return response.data;
  };

  const fetchBatterySettings = async (): Promise<BatterySettings> => {
    const response = await api.get('/api/settings');
    return response.data.battery;
  };

  const fetchDashboardData = async (): Promise<DashboardData> => {
    const response = await api.get('/api/dashboard', {
      params: { resolution: 'hourly' }
    });
    return response.data;
  };
  
  const loadData = async (isManualRefresh = false): Promise<void> => {
    try {
      if (isInitialLoad || isManualRefresh) {
        setLoading(true);
      }
      setError(null);
      
      const results = await Promise.allSettled([
        fetchInverterStatus(),
        fetchInverterSchedule(),
        fetchBatterySettings(),
        fetchDashboardData()
      ]);

      if (results[0].status === 'fulfilled') {
        setInverterStatus(results[0].value);
      } else {
        console.warn('Failed to fetch inverter status:', results[0].reason);
      }
      if (results[1].status === 'fulfilled') {
        setInverterSchedule(results[1].value);
      } else {
        console.warn('Failed to fetch schedule:', results[1].reason);
      }
      if (results[2].status === 'fulfilled') {
        setBatterySettings(results[2].value);
      } else {
        console.warn('Failed to fetch battery settings:', results[2].reason);
      }
      if (results[3].status === 'fulfilled') {
        setDashboardData(results[3].value);
      } else {
        console.warn('Failed to fetch dashboard data:', results[3].reason);
      }

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

  // Generate TOU schedule showing actual inverter configuration
  const generateInverterTOUSchedule = (touIntervals: TOUInterval[]) => {
    const schedule: Array<TOUInterval & { isEmpty?: boolean }> = [];

    // Create all 9 possible TOU segments (Growatt supports up to 9)
    for (let segmentId = 1; segmentId <= 9; segmentId++) {
      const existingSegment = touIntervals.find(interval => interval.segmentId === segmentId);

      if (existingSegment) {
        // Use the actual configured segment from inverter
        schedule.push(existingSegment);
      } else {
        // Create empty segment placeholder
        schedule.push({
          segmentId: segmentId,
          startTime: '00:00',
          endTime: '00:00',
          battMode: 'load_first',
          enabled: false,
          isEmpty: true
        });
      }
    }

    // Sort by segment ID (inverter order)
    return schedule.sort((a, b) => a.segmentId - b.segmentId);
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
    if (!inverterSchedule?.scheduleData) return 'load_first';
    
    const currentHour = new Date().getHours();
    const currentHourData = inverterSchedule.scheduleData.find(h => h.hour === currentHour);
    return currentHourData?.batteryMode || 'load_first';
  };

  // ✅ Calculate actual values from the API response
  const netBatteryPower = inverterStatus ? 
    calculateBatteryPower(
      inverterStatus.batteryChargePower || 0, 
      inverterStatus.batteryDischargePower || 0
    ) : 0;

  const currentBatteryMode = getCurrentBatteryMode();

  // Merge dashboard data with schedule data to get correct strategic intents
  const getMergedHourData = (hour: number) => {
    const scheduleHour = inverterSchedule?.scheduleData?.find(h => h.hour === hour);
    const dashboardHour = dashboardData?.hourlyData?.find(h => h.period === hour);

    if (!scheduleHour && !dashboardHour) return null;
    
    // Base data from whichever source is available
    if (!scheduleHour) {
      throw new Error(`MISSING DATA: scheduleHour is required but missing for hour ${hour}`);
    }
    const baseData = scheduleHour;

    return {
      ...baseData,
      // Use dashboard data for strategic intent first (actual data), then schedule data
      strategicIntent: dashboardHour?.strategicIntent || scheduleHour?.strategicIntent || baseData.strategicIntent,
      batteryAction: dashboardHour?.batteryAction !== undefined ? getValue(dashboardHour.batteryAction) : (scheduleHour?.batteryAction !== undefined ? scheduleHour.batteryAction : getValue(baseData.batteryAction)),
      batteryCharged: dashboardHour?.batteryCharged !== undefined ? getValue(dashboardHour.batteryCharged) : getValue(baseData.batteryCharged),
      batteryDischarged: dashboardHour?.batteryDischarged !== undefined ? getValue(dashboardHour.batteryDischarged) : getValue(baseData.batteryDischarged),
      batterySocEnd: scheduleHour?.batterySocEnd !== undefined ? scheduleHour.batterySocEnd : (dashboardHour?.batterySocEnd !== undefined ? getValue(dashboardHour.batterySocEnd) : getValue(baseData.batterySocEnd)),
      dataSource: dashboardHour?.dataSource || 'predicted',
      isActual: dashboardHour?.dataSource === 'actual',
      // Use schedule data for display fields when available, with formatted fallbacks from dashboard
      action: scheduleHour?.action || 'IDLE',
      actionColor: scheduleHour?.actionColor || 'gray',
      dischargePowerRate: scheduleHour?.dischargePowerRate || 0,
      chargePowerRate: scheduleHour?.chargePowerRate ?? 100,
      gridCharge: scheduleHour?.gridCharge || false,
      batteryMode: scheduleHour?.batteryMode || 'load_first',
      // Add formatted fields from dashboard data (they ARE the FormattedValue objects)
      batteryActionFormatted: dashboardHour?.batteryAction,
      batteryChargedFormatted: dashboardHour?.batteryCharged,
      batteryDischargedFormatted: dashboardHour?.batteryDischarged,
      batterySocEndFormatted: dashboardHour?.batterySocEnd
    };
  };

  // Rest of existing functions...
  const getBatteryModeDisplay = (mode: string) => {
    const modes: Record<string, { label: string; color: string }> = {
      'load_first': { label: 'Load First', color: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300' },
      'battery_first': { label: 'Battery First', color: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300' },
      'grid_first': { label: 'Grid First', color: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-300' }
    };
    
    if (!modes[mode]) {
      throw new Error(`MISSING DATA: Unknown battery mode '${mode}' - must be one of: ${Object.keys(modes).join(', ')}`);
    }
    const modeInfo = modes[mode];
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
      'BATTERY_EXPORT': 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300',
      'SOLAR_EXPORT': 'bg-lime-100 text-lime-800 dark:bg-lime-900 dark:text-lime-300',
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

  const currentHour = new Date().getHours();
  const currentHourData = getMergedHourData(currentHour);

  // Find current period group from 15-minute resolution data
  const getCurrentPeriodGroup = () => {
    if (!inverterSchedule?.periodGroups) return null;
    const now = new Date();
    const currentMinutes = now.getHours() * 60 + now.getMinutes();

    for (const group of inverterSchedule.periodGroups) {
      const [startH, startM] = group.startTime.split(':').map(Number);
      const [endH, endM] = group.endTime.split(':').map(Number);
      const groupStartMinutes = startH * 60 + startM;
      const groupEndMinutes = endH * 60 + endM;

      if (currentMinutes >= groupStartMinutes && currentMinutes <= groupEndMinutes) {
        return group;
      }
    }
    return null;
  };

  const currentPeriodGroup = getCurrentPeriodGroup();

  const formatDuration = (minutes: number): string => {
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    if (hours === 0) return `${mins}min`;
    if (mins === 0) return `${hours}h`;
    return `${hours}h ${mins}min`;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
        <div className="p-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Inverter and Battery Insights</h1>
            <p className="text-gray-600 dark:text-gray-400">Real-time energy and battery performance monitoring</p>
          </div>
        </div>
      </div>

      {/* Focused Status Cards */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Energy & Power Card */}
        <StatusCard
          title="Energy & Power"
          icon={Zap}
          color="green"
          keyMetric="State of Charge"
          keyValue={inverterStatus?.batterySoc}
          keyUnit="%"
          status={{
            icon: netBatteryPower > 0.01 ? TrendingUp :
                  netBatteryPower < -0.01 ? TrendingDown : CheckCircle,
            text: netBatteryPower > 0.01 ?
              'Charging' :
              netBatteryPower < -0.01 ?
              'Discharging' :
              'Idle',
            color: netBatteryPower > 0.01 ? 'green' :
                   netBatteryPower < -0.01 ? 'yellow' : 'blue'
          }}
          metrics={[
            {
              label: "State of Energy",
              value: getDisplayText(dashboardData?.hourlyData?.find(h => h.period === new Date().getHours())?.batterySoeEnd),
              unit: "",
              icon: Battery
            },
            {
              label: netBatteryPower > 0.01 ? 'Charging Power' :
                     netBatteryPower < -0.01 ? 'Discharging Power' : 'Battery Power',
              value: netBatteryPower > 0.01 ?
                inverterStatus?.batteryChargePower :
                netBatteryPower < -0.01 ?
                inverterStatus?.batteryDischargePower :
                0,
              unit: "W",
              icon: netBatteryPower > 0.01 ? TrendingUp :
                    netBatteryPower < -0.01 ? TrendingDown : Zap,
              color: netBatteryPower > 0.01 ? 'green' :
                     netBatteryPower < -0.01 ? 'yellow' : undefined
            },
            {
              label: "Solar Production",
              value: getDisplayText(dashboardData?.hourlyData?.find(h => h.period === new Date().getHours())?.solarProduction),
              unit: "",
              icon: Sun
            }
          ]}
        />

        {/* Current Strategy Card */}
        <StatusCard
          title="Current Strategy"
          icon={TrendingUp}
          color="green"
          keyMetric="Strategic Intent"
          keyValue={currentPeriodGroup?.dominantIntent?.replace(/_/g, ' ') || currentHourData?.strategicIntent?.replace('_', ' ') || 'IDLE'}
          keyUnit=""
          status={{
            icon: getValue(currentHourData?.batteryAction) ?
              (getValue(currentHourData?.batteryAction) > 0 ? TrendingUp : TrendingDown) : CheckCircle,
            text: currentPeriodGroup ? `${currentPeriodGroup.startTime} - ${currentPeriodGroup.endTime}` : `Hour ${currentHourData?.hour || 0}:00`,
            color: 'blue'
          }}
          metrics={[
            {
              label: "Current Mode",
              value: formatBatteryMode(currentPeriodGroup?.mode || currentBatteryMode),
              unit: "",
              icon: Battery
            },
            {
              label: "Battery Action",
              value: getDisplayText(dashboardData?.hourlyData?.find(h => h.period === new Date().getHours())?.batteryAction),
              unit: "",
              icon: getValue(dashboardData?.hourlyData?.find(h => h.period === new Date().getHours())?.batteryAction) && Math.abs(getValue(dashboardData?.hourlyData?.find(h => h.period === new Date().getHours())?.batteryAction)) > 0.01 ?
                (getValue(dashboardData?.hourlyData?.find(h => h.period === new Date().getHours())?.batteryAction) > 0 ? TrendingUp : TrendingDown) : Zap,
              color: getValue(dashboardData?.hourlyData?.find(h => h.period === new Date().getHours())?.batteryAction) && Math.abs(getValue(dashboardData?.hourlyData?.find(h => h.period === new Date().getHours())?.batteryAction)) > 0.01 ?
                (getValue(dashboardData?.hourlyData?.find(h => h.period === new Date().getHours())?.batteryAction) > 0 ? 'green' : 'yellow') : undefined
            },
            {
              label: "Target SOC",
              value: getDisplayText(dashboardData?.hourlyData?.find(h => h.period === new Date().getHours())?.batterySocEnd),
              unit: "",
              icon: CheckCircle
            }
          ]}
        />

        {/* Battery Settings Card */}
        <StatusCard
          title="Battery Settings"
          icon={Settings}
          color="green"
          keyMetric=""
          keyValue=""
          keyUnit=""
          status={{
            icon: inverterStatus?.gridChargeEnabled ? CheckCircle : AlertTriangle,
            text: inverterStatus?.gridChargeEnabled ? 'Grid Charge ON' : 'Grid Charge OFF',
            color: inverterStatus?.gridChargeEnabled ? 'green' : 'yellow'
          }}
          metrics={[
            {
              label: "Charge Stop SOC",
              value: inverterStatus?.chargeStopSoc || 0,
              unit: "%",
              icon: Battery
            },
            {
              label: "Discharge Stop SOC",
              value: inverterStatus?.dischargeStopSoc || 0,
              unit: "%",
              icon: Battery
            },
            {
              label: "Charge Power Rate",
              value: inverterStatus?.chargePowerRate || 0,
              unit: "%",
              icon: TrendingUp
            },
            {
              label: "Discharge Power Rate",
              value: inverterStatus?.dischargePowerRate || 0,
              unit: "%",
              icon: TrendingDown,
              dimmed: inverterStatus?.dischargeInhibitActive,
              badge: inverterStatus?.dischargeInhibitActive
                ? { text: 'Inhibited', color: 'yellow' as const }
                : undefined,
            }
          ]}
        />
      </div>

      {/* Period-Based Schedule (Grouped View) */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
        <div className="p-6">
          <div className="flex items-center mb-6">
            <Calendar className="h-5 w-5 text-blue-600 mr-2" />
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Schedule Overview (15-min Resolution)</h3>
          </div>

          {inverterSchedule?.periodGroups && inverterSchedule.periodGroups.length > 0 ? (() => {
            const schedulePlatform = inverterSchedule.inverterPlatform ?? 'growatt_server_min';
            const isTouBased = schedulePlatform !== 'solax_modbus_native';
            const totalCols = isTouBased ? 10 : 6;
            return (
            <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
              <table className="min-w-full border-collapse">
                <thead>
                  <tr>
                    <th rowSpan={2} className="px-3 py-2 text-center text-xs font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-700 align-bottom">
                      <div className="flex items-center justify-center gap-1">
                        <Clock className="h-3.5 w-3.5" />
                        Time Period
                      </div>
                    </th>
                    <th rowSpan={2} className="px-3 py-2 text-center text-xs font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-700 align-bottom">
                      Duration
                    </th>
                    <th colSpan={4} className="px-3 py-2 text-center text-xs font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-700">
                      Optimization Plan
                    </th>
                    {isTouBased && (
                      <th colSpan={4} className="px-3 py-2 text-center text-xs font-semibold text-indigo-700 dark:text-indigo-300 uppercase tracking-wider border border-gray-200 dark:border-gray-700 bg-indigo-50 dark:bg-indigo-900/20">
                        Inverter Configuration
                      </th>
                    )}
                  </tr>
                  <tr>
                    <th className="px-3 py-2 text-center text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-700">
                      Intent
                    </th>
                    <th className="px-3 py-2 text-center text-xs font-semibold text-amber-600 dark:text-amber-400 uppercase tracking-wider border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-700">
                      Solar
                    </th>
                    <th className="px-3 py-2 text-center text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-700">
                      Grid / Discharge
                    </th>
                    <th className="px-3 py-2 text-center text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-700">
                      Target SOC
                    </th>
                    {isTouBased && (<>
                      <th className="px-3 py-2 text-center text-xs font-semibold text-indigo-600 dark:text-indigo-400 uppercase tracking-wider border border-gray-200 dark:border-gray-700 bg-indigo-50/70 dark:bg-indigo-900/10">
                        Mode
                      </th>
                      <th className="px-3 py-2 text-center text-xs font-semibold text-indigo-600 dark:text-indigo-400 uppercase tracking-wider border border-gray-200 dark:border-gray-700 bg-indigo-50/70 dark:bg-indigo-900/10">
                        Charge %
                      </th>
                      <th className="px-3 py-2 text-center text-xs font-semibold text-indigo-600 dark:text-indigo-400 uppercase tracking-wider border border-gray-200 dark:border-gray-700 bg-indigo-50/70 dark:bg-indigo-900/10">
                        Discharge %
                      </th>
                      <th className="px-3 py-2 text-center text-xs font-semibold text-indigo-600 dark:text-indigo-400 uppercase tracking-wider border border-gray-200 dark:border-gray-700 bg-indigo-50/70 dark:bg-indigo-900/10">
                        Grid Charge
                      </th>
                    </>)}
                  </tr>
                </thead>

                {/* Today's rows */}
                <tbody className="bg-white dark:bg-gray-800">
                  {inverterSchedule.periodGroups.map((group, index) => {
                    const now = new Date();
                    const currentMinutes = now.getHours() * 60 + now.getMinutes();
                    const [startH, startM] = group.startTime.split(':').map(Number);
                    const [endH, endM] = group.endTime.split(':').map(Number);
                    const groupStartMinutes = startH * 60 + startM;
                    const groupEndMinutes = endH * 60 + endM;
                    const isCurrentPeriod = currentMinutes >= groupStartMinutes && currentMinutes <= groupEndMinutes;
                    const isPast = group.socEndPct == null && !isCurrentPeriod;
                    const cell = 'px-3 py-2.5 whitespace-nowrap text-sm border border-gray-200 dark:border-gray-700';
                    const invCell = `${cell} bg-indigo-50/20 dark:bg-indigo-900/5`;

                    return (
                      <tr
                        key={index}
                        className={
                          isCurrentPeriod
                            ? 'bg-blue-50 dark:bg-blue-900/20'
                            : isPast
                              ? 'opacity-40 bg-gray-50 dark:bg-gray-800/50'
                              : 'hover:bg-gray-50 dark:hover:bg-gray-700/30'
                        }
                      >
                        <td className={`${cell} text-center ${isCurrentPeriod ? 'border-l-4 border-l-blue-400' : ''}`}>
                          <div className="flex items-center justify-center gap-2">
                            <span className="font-medium text-gray-900 dark:text-white">
                              {group.startTime} - {group.endTime}
                            </span>
                            {isCurrentPeriod && (
                              <span className="px-1.5 py-0.5 text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300 rounded">
                                Now
                              </span>
                            )}
                          </div>
                        </td>
                        <td className={`${cell} text-center text-gray-600 dark:text-gray-400`}>{formatDuration(group.durationMinutes)}</td>
                        <td className={`${cell} text-center`}>
                          <span className={`px-2 py-0.5 rounded text-xs font-medium ${getIntentColor(group.dominantIntent)}`}>
                            {group.dominantIntent.replace(/_/g, ' ')}
                          </span>
                        </td>
                        {/* Solar column: SOLAR_STORAGE and passive IDLE gains */}
                        <td className={`${cell} text-center`}>
                          {!isPast && (group.dominantIntent === 'SOLAR_STORAGE' || group.dominantIntent === 'IDLE') &&
                           group.socDeltaKwh != null && group.socDeltaKwh > 0.1 ? (
                            <span className="text-amber-500 dark:text-amber-400 font-medium">
                              +{group.socDeltaKwh.toFixed(1)} kWh
                            </span>
                          ) : (
                            <span className="text-gray-300 dark:text-gray-600">—</span>
                          )}
                        </td>
                        {/* Grid / Discharge column */}
                        <td className={`${cell} text-center`}>
                          {!isPast && group.dominantIntent === 'GRID_CHARGING' &&
                           group.socDeltaKwh != null && group.socDeltaKwh > 0.1 ? (
                            <span className="text-green-600 dark:text-green-400 font-medium">
                              +{group.socDeltaKwh.toFixed(1)} kWh
                            </span>
                          ) : !isPast && group.totalActionKwh !== undefined && group.totalActionKwh < -0.05 ? (
                            <span className="text-orange-500 dark:text-orange-400 font-medium">
                              {group.totalActionKwh.toFixed(1)} kWh
                            </span>
                          ) : (
                            <span className="text-gray-300 dark:text-gray-600">—</span>
                          )}
                        </td>
                        <td className={`${cell} text-center`}>
                          {group.socEndPct != null ? (
                            <span className="text-gray-700 dark:text-gray-300 font-medium">{Math.round(group.socEndPct)}%</span>
                          ) : (
                            <span className="text-gray-300 dark:text-gray-600">—</span>
                          )}
                        </td>
                        {isTouBased && (<>
                          <td className={`${invCell} text-center`}>{getBatteryModeDisplay(group.mode)}</td>
                          <td className={`${invCell} text-center`}>
                            {group.chargePowerRate > 0 ? (
                              <span className="text-green-600 dark:text-green-400 font-medium">{group.chargePowerRate}%</span>
                            ) : (
                              <span className="text-gray-300 dark:text-gray-600">—</span>
                            )}
                          </td>
                          <td className={`${invCell} text-center`}>
                            {group.dischargePowerRate > 0 ? (
                              <span className="text-orange-500 dark:text-orange-400 font-medium">{group.dischargePowerRate}%</span>
                            ) : (
                              <span className="text-gray-300 dark:text-gray-600">—</span>
                            )}
                          </td>
                          <td className={`${invCell} text-center`}>
                            {group.gridCharge ? (
                              <span className="text-green-600 dark:text-green-400 font-medium">Yes</span>
                            ) : (
                              <span className="text-gray-300 dark:text-gray-600">—</span>
                            )}
                          </td>
                        </>)}
                      </tr>
                    );
                  })}
                </tbody>

                {/* Tomorrow toggle row + rows — same table keeps columns aligned */}
                {inverterSchedule.tomorrowPeriodGroups && inverterSchedule.tomorrowPeriodGroups.length > 0 && (
                  <>
                    <tbody>
                      <tr className="bg-indigo-50 dark:bg-indigo-900/20 border-t-2 border-indigo-200 dark:border-indigo-700">
                        <td colSpan={totalCols} className="px-3 py-2.5 border border-gray-200 dark:border-gray-700">
                          <button
                            onClick={() => setShowTomorrow(!showTomorrow)}
                            className="flex items-center gap-2 text-sm font-medium text-indigo-700 dark:text-indigo-300 hover:text-indigo-900 dark:hover:text-indigo-100 transition-colors"
                          >
                            <ChevronRight className={`h-4 w-4 transition-transform ${showTomorrow ? 'rotate-90' : ''}`} />
                            Tomorrow&apos;s Planned Schedule ({inverterSchedule.tomorrowPeriodGroups.length} segments)
                          </button>
                        </td>
                      </tr>
                    </tbody>
                    {showTomorrow && (
                      <tbody className="bg-white dark:bg-gray-800 opacity-75">
                        {inverterSchedule.tomorrowPeriodGroups.map((group, index) => {
                          const cell = 'px-3 py-2.5 whitespace-nowrap text-sm border border-gray-200 dark:border-gray-700';
                          const invCell = `${cell} bg-indigo-50/20 dark:bg-indigo-900/5`;
                          return (
                            <tr key={`tomorrow-${index}`} className="hover:bg-gray-50 dark:hover:bg-gray-700/30">
                              <td className={`${cell} text-center`}>
                                <span className="font-medium text-gray-900 dark:text-white">
                                  {group.startTime} - {group.endTime}
                                </span>
                              </td>
                              <td className={`${cell} text-center text-gray-600 dark:text-gray-400`}>{formatDuration(group.durationMinutes)}</td>
                              <td className={`${cell} text-center`}>
                                <span className={`px-2 py-0.5 rounded text-xs font-medium ${getIntentColor(group.dominantIntent)}`}>
                                  {group.dominantIntent.replace(/_/g, ' ')}
                                </span>
                              </td>
                              {/* Solar column */}
                              <td className={`${cell} text-center`}>
                                {(group.dominantIntent === 'SOLAR_STORAGE' || group.dominantIntent === 'IDLE') &&
                                 group.socDeltaKwh != null && group.socDeltaKwh > 0.1 ? (
                                  <span className="text-amber-500 dark:text-amber-400 font-medium">
                                    +{group.socDeltaKwh.toFixed(1)} kWh
                                  </span>
                                ) : (
                                  <span className="text-gray-300 dark:text-gray-600">—</span>
                                )}
                              </td>
                              {/* Grid / Discharge column */}
                              <td className={`${cell} text-center`}>
                                {group.dominantIntent === 'GRID_CHARGING' &&
                                 group.socDeltaKwh != null && group.socDeltaKwh > 0.1 ? (
                                  <span className="text-green-600 dark:text-green-400 font-medium">
                                    +{group.socDeltaKwh.toFixed(1)} kWh
                                  </span>
                                ) : group.totalActionKwh !== undefined && group.totalActionKwh < -0.05 ? (
                                  <span className="text-orange-500 dark:text-orange-400 font-medium">
                                    {group.totalActionKwh.toFixed(1)} kWh
                                  </span>
                                ) : (
                                  <span className="text-gray-300 dark:text-gray-600">—</span>
                                )}
                              </td>
                              <td className={`${cell} text-center`}>
                                {group.socEndPct != null ? (
                                  <span className="text-gray-700 dark:text-gray-300 font-medium">{Math.round(group.socEndPct)}%</span>
                                ) : (
                                  <span className="text-gray-300 dark:text-gray-600">—</span>
                                )}
                              </td>
                              {isTouBased && (<>
                                <td className={`${invCell} text-center`}>{getBatteryModeDisplay(group.mode)}</td>
                                <td className={`${invCell} text-center`}>
                                  {group.chargePowerRate > 0 ? (
                                    <span className="text-green-600 dark:text-green-400 font-medium">{group.chargePowerRate}%</span>
                                  ) : (
                                    <span className="text-gray-300 dark:text-gray-600">—</span>
                                  )}
                                </td>
                                <td className={`${invCell} text-center`}>
                                  {group.dischargePowerRate > 0 ? (
                                    <span className="text-orange-500 dark:text-orange-400 font-medium">{group.dischargePowerRate}%</span>
                                  ) : (
                                    <span className="text-gray-300 dark:text-gray-600">—</span>
                                  )}
                                </td>
                                <td className={`${invCell} text-center`}>
                                  {group.gridCharge ? (
                                    <span className="text-green-600 dark:text-green-400 font-medium">Yes</span>
                                  ) : (
                                    <span className="text-gray-300 dark:text-gray-600">—</span>
                                  )}
                                </td>
                              </>)}
                            </tr>
                          );
                        })}
                      </tbody>
                    )}
                  </>
                )}
              </table>
            </div>
          );
          })() : (
            <div className="text-gray-500 dark:text-gray-400 text-sm">No schedule data available</div>
          )}
        </div>
      </div>

      {/* Hardware Schedule Section — platform-aware */}
      {(() => {
        const platform = inverterSchedule?.inverterPlatform ?? inverterStatus?.inverterPlatform ?? 'growatt_server_min';
        const isSolax = platform === 'solax_modbus_native';

        return (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
            <div className="p-6">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center">
                  <Clock className="h-5 w-5 text-blue-600 mr-2" />
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                    {isSolax ? 'VPP Control' : 'Time of Use (TOU) Intervals'}
                  </h3>
                </div>
                <span className="text-xs px-2 py-1 rounded-full font-medium bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300">
                  {platform === 'growatt_server_min' ? 'Growatt MIN'
                    : platform === 'growatt_server_sph' ? 'Growatt SPH'
                    : platform === 'solax_modbus_native' ? 'SolaX Modbus'
                    : platform === 'solax_modbus_growatt_min' ? 'SolaX/Growatt MIN'
                    : platform === 'solax_modbus_growatt_sph' ? 'SolaX/Growatt SPH'
                    : platform === 'huawei_solar_luna2000' ? 'Huawei LUNA2000'
                    : platform}
                </span>
              </div>

              {isSolax ? (
                <div className="rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 p-4">
                  <p className="text-sm font-medium text-blue-800 dark:text-blue-300 mb-1">Per-period VPP commands</p>
                  <p className="text-sm text-blue-700 dark:text-blue-400">
                    SolaX uses real-time power commands instead of a stored schedule.
                    Commands are issued at each 15-minute period boundary and kept active
                    via autorepeat. The strategic intent timeline above shows what the
                    optimizer has planned.
                  </p>
                </div>
              ) : (
                inverterSchedule?.touIntervals ? (
                  <div className="space-y-2">
                    {inverterSchedule.touIntervals.map((interval, index) => (
                      <div key={index} className={`flex justify-between items-center p-3 rounded-lg ${
                        interval.isExpired
                          ? 'bg-gray-50 dark:bg-gray-800/30 border border-gray-200 dark:border-gray-700 opacity-40'
                          : interval.isDefault
                          ? 'bg-gray-50 dark:bg-gray-800/30 border border-gray-200 dark:border-gray-700 opacity-50'
                          : interval.isEmpty
                          ? 'bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 opacity-60'
                          : interval.enabled
                          ? 'bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800'
                          : 'bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800'
                      }`}>
                        <div className="flex items-center space-x-4">
                          <div className={`font-medium ${
                            interval.isExpired ? 'text-gray-400 dark:text-gray-500' : 'text-gray-900 dark:text-white'
                          }`}>
                            {interval.isDefault ? 'Default' : `Segment #${interval.segmentId}`}
                          </div>
                          <div className={`text-sm ${
                            interval.isExpired ? 'text-gray-400 dark:text-gray-500 line-through' : 'text-gray-600 dark:text-gray-400'
                          }`}>
                            {interval.isExpired
                              ? `${interval.startTime} - ${interval.endTime}`
                              : interval.isEmpty
                              ? 'Not configured'
                              : `${interval.startTime} - ${interval.endTime}`}
                          </div>
                        </div>
                        <div className="flex items-center space-x-3">
                          {!interval.isExpired && !interval.isEmpty && getBatteryModeDisplay(interval.battMode)}
                          <span className={`px-2 py-1 rounded text-xs font-medium ${
                            interval.isExpired
                              ? 'bg-gray-100 text-gray-400 dark:bg-gray-700 dark:text-gray-500'
                              : interval.pendingWrite
                              ? 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-300'
                              : interval.isDefault
                              ? 'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400'
                              : interval.isEmpty
                              ? 'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400'
                              : interval.enabled
                              ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300'
                              : 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300'
                          }`}>
                            {interval.isExpired ? 'Expired'
                              : interval.pendingWrite ? 'Pending Write'
                              : interval.isDefault ? 'Load First'
                              : interval.isEmpty ? 'Empty'
                              : (interval.enabled ? 'Active' : 'Disabled')}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-gray-500 dark:text-gray-400 text-sm">No TOU intervals configured</div>
                )
              )}
            </div>
          </div>
        );
      })()}

    </div>
  );
};

export default InverterStatusDashboard;