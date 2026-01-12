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
  Sun
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

interface GrowattSchedule {
  currentHour: number;
  touIntervals: TOUInterval[];
  scheduleData: ScheduleHour[];
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
          <div key={index} className="flex items-center justify-between">
            <div className="flex items-center">
              {metric.icon && <metric.icon className="h-4 w-4 mr-2 text-gray-500 dark:text-gray-400" />}
              <span className="text-sm text-gray-700 dark:text-gray-300">{metric.label}</span>
            </div>
            <span className={`text-sm font-semibold ${
              metric.color ? metricColorClasses[metric.color] : 'text-gray-900 dark:text-gray-100'
            }`}>
              {metric.value}
              {metric.unit && <span className="opacity-70 ml-1">{metric.unit}</span>}
            </span>
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
    hour: number;
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
  const [growattSchedule, setGrowattSchedule] = useState<GrowattSchedule | null>(null);
  const [batterySettings, setBatterySettings] = useState<BatterySettings | null>(null);
  const [dashboardData, setDashboardData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());
  const [isInitialLoad, setIsInitialLoad] = useState(true);

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
    const response = await api.get('/api/growatt/inverter_status');
    return response.data;
  };

  const fetchGrowattSchedule = async (): Promise<GrowattSchedule> => {
    const response = await api.get('/api/growatt/detailed_schedule');
    return response.data;
  };

  const fetchBatterySettings = async (): Promise<BatterySettings> => {
    const response = await api.get('/api/settings/battery');
    return response.data;
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
      
      const [statusData, scheduleData, batteryData, dashboardDataResult] = await Promise.all([
        fetchInverterStatus(),
        fetchGrowattSchedule(),
        fetchBatterySettings(),
        fetchDashboardData()
      ]);
      
      setInverterStatus(statusData);
      setGrowattSchedule(scheduleData);
      setBatterySettings(batteryData);
      setDashboardData(dashboardDataResult);
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
    if (!growattSchedule?.scheduleData) return 'load_first';
    
    const currentHour = new Date().getHours();
    const currentHourData = growattSchedule.scheduleData.find(h => h.hour === currentHour);
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
    const scheduleHour = growattSchedule?.scheduleData?.find(h => h.hour === hour);
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
      chargePowerRate: scheduleHour?.chargePowerRate || 100,
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

  const currentHour = new Date().getHours();
  const currentHourData = getMergedHourData(currentHour);

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
          keyValue={currentHourData?.strategicIntent?.replace('_', ' ') || 'IDLE'}
          keyUnit=""
          status={{
            icon: getValue(currentHourData?.batteryAction) ?
              (getValue(currentHourData?.batteryAction) > 0 ? TrendingUp : TrendingDown) : CheckCircle,
            text: `Hour ${currentHourData?.hour || 0}:00`,
            color: 'blue'
          }}
          metrics={[
            {
              label: "Current Mode",
              value: formatBatteryMode(currentBatteryMode),
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
              value: batterySettings?.chargingPowerRate || 0,
              unit: "%",
              icon: TrendingUp
            },
            {
              label: "Discharge Power Rate",
              value: inverterStatus?.dischargePowerRate || 0,
              unit: "%",
              icon: TrendingDown
            }
          ]}
        />
      </div>

      {/* 24-Hour Schedule */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
        <div className="p-6">
          <div className="flex items-center mb-6">
            <Calendar className="h-5 w-5 text-blue-600 mr-2" />
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">24-Hour Schedule Overview</h3>
          </div>
          
          {growattSchedule?.scheduleData && dashboardData?.hourlyData ? (
            <div className="overflow-x-auto bg-white dark:bg-gray-800 rounded-lg shadow">
              <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                <thead className="bg-gray-50 dark:bg-gray-700">
                  <tr>
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                      <div className="flex items-center">
                        <Clock className="h-4 w-4 mr-1" />
                        Time
                      </div>
                    </th>
                    <th className="px-3 py-3 text-center text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider border-r border-gray-300 dark:border-gray-600" colSpan={3}>
                      <div className="flex items-center justify-center">
                        <TrendingUp className="h-4 w-4 mr-1" />
                        Algorithm Strategy
                      </div>
                    </th>
                    <th className="px-3 py-3 text-center text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider" colSpan={3}>
                      <div className="flex items-center justify-center">
                        <Settings className="h-4 w-4 mr-1" />
                        Inverter Settings
                      </div>
                    </th>
                  </tr>
                  <tr className="bg-gray-50 dark:bg-gray-700">
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 dark:text-gray-400">Hour</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 dark:text-gray-400">Intent</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 dark:text-gray-400">Target SOC</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 dark:text-gray-400 border-r border-gray-300 dark:border-gray-600">Action</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 dark:text-gray-400">Mode</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 dark:text-gray-400">Power Rate</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-400 dark:text-gray-400">Grid Charge</th>
                  </tr>
                </thead>
                <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
                  {Array.from({length: 24}, (_, hour) => getMergedHourData(hour)).map((hour, index) => {
                    if (!hour) return null;
                    const isCurrentHour = hour.hour === growattSchedule?.currentHour;
                    
                    return (
                      <tr key={index} className={`${
                        isCurrentHour ? 'bg-blue-50 dark:bg-blue-900/20' : ''
                      } ${!hour.isActual ? 'opacity-75' : ''}`}>
                        <td className="px-3 py-4 whitespace-nowrap text-sm">
                          <div className="flex items-center">
                            <div>
                              <div className="font-medium text-gray-900 dark:text-white text-right">
                                <div>{hour.hour.toString().padStart(2, '0')}:00</div>
                                <div className="text-xs text-gray-400 dark:text-gray-500 font-normal">-{hour.hour.toString().padStart(2, '0')}:59</div>
                              </div>
                              <div className="text-xs text-gray-500 dark:text-gray-400">
                                {isCurrentHour ? 'Current' : 
                                 hour.isActual ? 'Actual' : 'Predicted'}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="px-3 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                          <span className="font-medium">
                            {hour.strategicIntent?.replace('_', ' ') || 'IDLE'}
                          </span>
                        </td>
                        <td className="px-3 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                          <span className="font-medium">{getDisplayText(hour.batterySocEndFormatted)}</span>
                        </td>
                        <td className="px-3 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                          {(() => {
                            const batteryAction = hour.batteryAction || 0;
                            const formattedAction = getDisplayText(hour.batteryActionFormatted);

                            // Prioritize actual battery action value over schedule action
                            if (batteryAction > 0.01) {
                              return (
                                <div className="flex items-center text-green-600">
                                  <span className="text-xs mr-1">⚡</span>
                                  <span className="font-medium">
                                    {formattedAction || `Charge ${batteryAction.toFixed(1)} kWh`}
                                  </span>
                                </div>
                              );
                            }

                            if (batteryAction < -0.01) {
                              return (
                                <div className="flex items-center text-orange-600">
                                  <span className="text-xs mr-1">⚡</span>
                                  <span className="font-medium">
                                    {formattedAction || `Discharge ${Math.abs(batteryAction).toFixed(1)} kWh`}
                                  </span>
                                </div>
                              );
                            }

                            return (
                              <div className="flex items-center text-gray-500 dark:text-gray-400">
                                <span className="text-xs mr-1">⏸️</span>
                                <span>Idle</span>
                              </div>
                            );
                          })()}
                        </td>
                        <td className="px-3 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                          <span className="font-medium">
                            {hour.isActual ? 'N/A' : (
                              hour.batteryMode === 'load_first' ? 'Load First' :
                              hour.batteryMode === 'battery_first' ? 'Battery First' :
                              hour.batteryMode === 'grid_first' ? 'Grid First' : hour.batteryMode
                            )}
                          </span>
                        </td>
                        <td className="px-3 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                          <div className="space-y-1">
                            {hour.isActual ? (
                              <div className="text-gray-500 dark:text-gray-400">N/A</div>
                            ) : (
                              <>
                                {hour.action === 'CHARGE' && hour.chargePowerRate > 0 && (
                                  <div className="text-green-600">C: {hour.chargePowerRate}%</div>
                                )}
                                {(hour.action === 'DISCHARGE' || hour.action === 'EXPORT') && hour.dischargePowerRate > 0 && (
                                  <div className="text-orange-600">D: {hour.dischargePowerRate}%</div>
                                )}
                                {(hour.action === 'IDLE' || hour.chargePowerRate === 0 || hour.dischargePowerRate === 0) && (
                                  <div className="text-gray-500 dark:text-gray-400">0%</div>
                                )}
                              </>
                            )}
                          </div>
                        </td>
                        <td className="px-3 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                          <span className="font-medium">
                            {hour.isActual ? 'N/A' : (hour.gridCharge ? '✓ Enabled' : '✗ Disabled')}
                          </span>
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
              {growattSchedule.touIntervals.map((interval, index) => (
                <div key={index} className={`flex justify-between items-center p-3 rounded-lg ${
                  interval.isDefault
                    ? 'bg-gray-50 dark:bg-gray-800/30 border border-gray-200 dark:border-gray-700 opacity-50'
                    : interval.isEmpty
                    ? 'bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 opacity-60'
                    : interval.enabled
                    ? 'bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800'
                    : 'bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800'
                }`}>
                  <div className="flex items-center space-x-4">
                    <div className="font-medium text-gray-900 dark:text-white">
                      {interval.isDefault
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
                      interval.isDefault
                        ? 'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400'
                        : interval.isEmpty
                        ? 'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400'
                        : interval.enabled
                        ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300'
                        : 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300'
                    }`}>
                      {interval.isDefault
                        ? 'Load First'
                        : interval.isEmpty
                        ? 'Empty'
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

    </div>
  );
};

export default InverterStatusDashboard;