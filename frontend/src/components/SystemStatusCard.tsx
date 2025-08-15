import React, { useState, useEffect } from 'react';
import api from '../lib/api';
import { 
  DollarSign, 
  Battery, 
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  CheckCircle,
  Zap,
  Home
} from 'lucide-react';

// System status data structure
interface SystemStatusData {
  costAndSavings?: {
    todaysCost: number;
    todaysSavings: number;
    gridOnlyCost: number;
    percentageSaved: number;
  };
  batteryStatus?: {
    soc: number;
    soe: number;
    power: number;
    status: 'charging' | 'discharging' | 'idle';
    batteryMode?: string; // Current operating mode (e.g., "load-first", "battery-first")
  };
  realTimePower?: {
    solarPower: number;        // kW - Total solar DC production (converted from watts)
    homeLoad: number;          // kW - Home consumption (converted from watts)
    gridImport: number;        // kW - Grid import power (converted from watts)
    gridExport: number;        // kW - Grid export power (converted from watts)
    batteryCharge: number;     // kW - Battery charging power (converted from watts)
    batteryDischarge: number;  // kW - Battery discharging power (converted from watts)
    netBattery: number;        // kW - Net battery power: + = charging, - = discharging
    netGrid: number;           // kW - Net grid power: + = importing, - = exporting
  };
}

// StatusCard component
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
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">{keyMetric}</p>
        <p className="text-3xl font-bold text-gray-900 dark:text-gray-100">
          {typeof keyValue === 'number' ? keyValue.toFixed(1) : keyValue}
          <span className="text-lg font-normal text-gray-600 dark:text-gray-400 ml-2">{keyUnit}</span>
        </p>
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
              {typeof metric.value === 'number' 
                ? metric.value.toFixed(1)
                : metric.value}
              {metric.unit && <span className="opacity-70 ml-1">{metric.unit}</span>}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};

interface SystemStatusCardProps {
  className?: string;
}

// Helper functions for battery mode formatting
const formatBatteryMode = (mode: string): string => {
  switch (mode.toLowerCase()) {
    case 'load-first':
      return 'Load First';
    case 'battery-first':
      return 'Battery First';
    case 'grid-first':
      return 'Grid First';
    default:
      return mode.charAt(0).toUpperCase() + mode.slice(1);
  }
};

const SystemStatusCard: React.FC<SystemStatusCardProps> = ({ className = "" }) => {
  const [statusData, setStatusData] = useState<SystemStatusData>({});
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchStatusData = async () => {
      try {
        setIsLoading(true);
        
        // Fetch dashboard data (now includes battery state)
        const dashboardResponse = await api.get('/api/dashboard');
        const dashboardData = dashboardResponse.data;
        
        // Fetch actual inverter status for correct battery mode and other real-time data
        const inverterResponse = await api.get('/api/growatt/inverter_status');
        const inverterStatusData = inverterResponse.data;
        
        // Check for required battery data
        if (dashboardData.batterySoc === undefined) {
          console.warn('BACKEND ISSUE: Missing batterySoc in dashboardData');
        }
        if (dashboardData.batterySoe === undefined) {
          console.warn('BACKEND ISSUE: Missing batterySoe in dashboardData');
        }
        if (dashboardData.batteryCapacity === undefined) {
          console.warn('BACKEND ISSUE: Missing batteryCapacity in dashboardData');
        }
        
        // Current battery state - these are dashboard-level fields (not hourly)
        const currentSOC = dashboardData.batterySoc ?? 0;
        const currentSOE = dashboardData.batterySoe ?? 0;
        const batteryCapacity = dashboardData.batteryCapacity ?? 0;
        
        // Check for missing keys in summary data
        if (dashboardData.summary?.batteryCycleCost === undefined) {
          console.warn('Missing key: summary.batteryCycleCost in dashboardData');
        }
        if (dashboardData.summary?.gridOnlyCost === undefined) {
          console.warn('Missing key: summary.gridOnlyCost in dashboardData');
        }
        if (dashboardData.summary?.optimizedCost === undefined) {
          console.warn('Missing key: summary.optimizedCost in dashboardData');
        }
        if (dashboardData.totalDailySavings === undefined) {
          console.warn('Missing key: totalDailySavings in dashboardData');
        }
        
        // Calculate costs from dashboard data
        const gridOnlyCost = dashboardData.summary?.gridOnlyCost ?? 0;
        const optimizedCost = dashboardData.summary?.optimizedCost ?? 0;
        const dailySavings = gridOnlyCost - optimizedCost; // Calculate correctly as grid-only minus optimized
        
        // Get current battery power and status
        const currentHour = new Date().getHours();
        const currentHourData = dashboardData.hourlyData?.find((h: any) => h.hour === currentHour);
        
        // Get actual battery mode from inverter status (not schedule)
        const actualBatteryMode = inverterStatusData.batteryMode || 'load-first';
        
        // Debug log to see all available fields in the currentHourData
        if (currentHourData) {
          console.log("Current hour data fields:", Object.keys(currentHourData));
        }
        console.log("Actual inverter battery mode:", actualBatteryMode);
        
        // Check for missing keys in hourly data
        if (currentHourData && currentHourData.batteryAction === undefined) {
          console.warn('Missing key: batteryAction in currentHourData');
        }
        
        const batteryPower = Math.abs(currentHourData?.batteryAction ?? 0);
        const batteryStatus = currentHourData?.batteryAction > 0.1 ? 'charging' : 
                            currentHourData?.batteryAction < -0.1 ? 'discharging' : 'idle';

    // Get real-time power data from dashboard response (in watts)
    const realTimePowerDataW = dashboardData.realTimePower || {
      solarPowerW: 0,
      homeLoadPowerW: 0,
      gridImportPowerW: 0,
      gridExportPowerW: 0,
      batteryChargePowerW: 0,
      batteryDischargePowerW: 0,
      netBatteryPowerW: 0,
      netGridPowerW: 0,
      acPowerW: 0,
      selfPowerW: 0,
    };

    // Convert to kW for display (preserving precision until display)
    const realTimePowerData = {
      solarPower: realTimePowerDataW.solarPowerW / 1000,           // Total solar production
      homeLoad: realTimePowerDataW.homeLoadPowerW / 1000,         // Home consumption
      gridImport: realTimePowerDataW.gridImportPowerW / 1000,     // Grid import
      gridExport: realTimePowerDataW.gridExportPowerW / 1000,     // Grid export
      batteryCharge: realTimePowerDataW.batteryChargePowerW / 1000,     // Battery charging
      batteryDischarge: realTimePowerDataW.batteryDischargePowerW / 1000, // Battery discharging
      netBattery: realTimePowerDataW.netBatteryPowerW / 1000,     // Net battery power
      netGrid: realTimePowerDataW.netGridPowerW / 1000,           // Net grid power
    };        const transformedData: SystemStatusData = {
          costAndSavings: {
            todaysCost: optimizedCost,
            todaysSavings: dailySavings,
            gridOnlyCost: gridOnlyCost,
            percentageSaved: gridOnlyCost > 0 ? (dailySavings / gridOnlyCost) * 100 : 0
          },
          batteryStatus: {
            soc: currentSOC,
            soe: currentSOE,
            power: batteryPower,
            status: batteryStatus,
            // Use the actual inverter battery mode instead of optimization schedule
            batteryMode: actualBatteryMode
          },
          realTimePower: realTimePowerData
        };
        
        // Debug log to check hourly data structure
        console.log('SystemStatusCard: Current hour data', currentHourData);
        
        setStatusData(transformedData);
        setError(null);
        console.log('SystemStatusCard: Data loaded successfully', {
          dashboardAvailable: !!dashboardData,
          batteryDataAvailable: !!dashboardData.batterySoc,
          currentSOC,
          currentSOE,
          batteryCapacity
        });
      } catch (err) {
        console.error('Failed to fetch system status data:', err);
        const errorMessage = err instanceof Error ? err.message : 'Unknown error';
        setError(`Failed to load system status data: ${errorMessage}`);
      } finally {
        setIsLoading(false);
      }
    };

    fetchStatusData();
  }, []);

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="border rounded-lg p-6 bg-gray-50 animate-pulse">
            <div className="h-8 bg-gray-200 rounded mb-4"></div>
            <div className="h-10 bg-gray-200 rounded mb-6"></div>
            <div className="space-y-3">
              <div className="h-5 bg-gray-200 rounded"></div>
              <div className="h-5 bg-gray-200 rounded"></div>
              <div className="h-5 bg-gray-200 rounded"></div>
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-red-600 text-center p-4 border border-red-200 rounded-lg bg-red-50">
        <AlertTriangle className="h-6 w-6 mx-auto mb-2" />
        {error}
      </div>
    );
  }

  const cards = [
    {
      title: "Power Flow",
      icon: Zap,
      color: "blue" as const,
      keyMetric: "Solar Production",
      keyValue: statusData.realTimePower?.solarPower || 0,
      keyUnit: "kW",
      status: {
        icon: (statusData.realTimePower?.gridExport || 0) > 0.1 ? TrendingUp : 
              (statusData.realTimePower?.gridImport || 0) > 0.1 ? TrendingDown : CheckCircle,
        text: (statusData.realTimePower?.gridExport || 0) > 0.1 ? `${(statusData.realTimePower?.gridExport || 0).toFixed(1)}kW exporting` :
              (statusData.realTimePower?.gridImport || 0) > 0.1 ? `${(statusData.realTimePower?.gridImport || 0).toFixed(1)}kW importing` : 'Grid balanced',
        color: (statusData.realTimePower?.gridExport || 0) > 0.1 ? 'green' as const : 
               (statusData.realTimePower?.gridImport || 0) > 0.1 ? 'red' as const : 'green' as const
      },
      metrics: [
        {
          label: "Home Load",
          value: statusData.realTimePower?.homeLoad || 0,
          unit: "kW",
          icon: Home
        },
        {
          label: "Grid Flow",
          value: Math.abs(statusData.realTimePower?.netGrid || 0),
          unit: (statusData.realTimePower?.gridExport || 0) > 0.1 ? "kW Export ↑" : 
                (statusData.realTimePower?.gridImport || 0) > 0.1 ? "kW Import ↓" : "kW",
          icon: Zap,
          color: (statusData.realTimePower?.gridExport || 0) > 0.1 ? 'green' as const : 
                 (statusData.realTimePower?.gridImport || 0) > 0.1 ? 'red' as const : undefined
        },
        {
          label: "Battery",
          value: Math.abs(statusData.realTimePower?.netBattery || 0),
          unit: (statusData.realTimePower?.netBattery || 0) > 0.1 ? "kW Charging ↑" :
                (statusData.realTimePower?.netBattery || 0) < -0.1 ? "kW Discharging ↓" : "kW",
          icon: Battery,
          color: (statusData.realTimePower?.netBattery || 0) > 0.1 ? 'green' as const : 
                 (statusData.realTimePower?.netBattery || 0) < -0.1 ? 'yellow' as const : undefined
        }
      ]
    },
    {
      title: "Inverter & Battery",
      icon: Battery,
      color: "blue" as const,
      keyMetric: "State of Charge",
      keyValue: statusData.batteryStatus?.soc || 0,
      keyUnit: "%",
      status: {
        icon: (statusData.realTimePower?.netBattery || 0) > 0.1 ? TrendingUp :
              (statusData.realTimePower?.netBattery || 0) < -0.1 ? TrendingDown : CheckCircle,
        text: (statusData.realTimePower?.netBattery || 0) > 0.1 ? 
          `Charging ${Math.abs(statusData.realTimePower?.netBattery || 0).toFixed(1)}kW` :
          (statusData.realTimePower?.netBattery || 0) < -0.1 ? 
          `Discharging ${Math.abs(statusData.realTimePower?.netBattery || 0).toFixed(1)}kW` : 
          'Idle',
        color: (statusData.realTimePower?.netBattery || 0) > 0.1 ? 'green' as const :
               (statusData.realTimePower?.netBattery || 0) < -0.1 ? 'yellow' as const : 'blue' as const
      },
      metrics: [
        {
          label: "State of Energy",
          value: parseFloat((statusData.batteryStatus?.soe || 0).toFixed(1)),
          unit: "kWh",
          icon: Zap
          // Removed color to use default (black)
        },
        {
          label: "Current Mode",
          value: formatBatteryMode(statusData.batteryStatus?.batteryMode || 'Unknown'),
          unit: "",
          icon: Battery
          // Removed color to use default (black)
        },
        {
          label: (statusData.realTimePower?.netBattery || 0) > 0.1 ? 'Charging' :
                 (statusData.realTimePower?.netBattery || 0) < -0.1 ? 'Discharging' : 'Power',
          value: parseFloat((Math.abs(statusData.realTimePower?.netBattery || 0)).toFixed(1)),
          unit: "kW",
          icon: (statusData.realTimePower?.netBattery || 0) > 0.1 ? TrendingUp :
                (statusData.realTimePower?.netBattery || 0) < -0.1 ? TrendingDown : Zap,
          color: (statusData.realTimePower?.netBattery || 0) > 0.1 ? 'green' as const :
                 (statusData.realTimePower?.netBattery || 0) < -0.1 ? 'yellow' as const : 'blue' as const
        }
      ]
    },
    {
      title: "Today's Cost & Savings",
      icon: DollarSign,
      color: "blue" as const,
      keyMetric: "Today's Costs",
      keyValue: statusData.costAndSavings?.todaysCost || 0,
      keyUnit: "SEK",
      status: {
        icon: (statusData.costAndSavings?.todaysSavings || 0) >= 0 ? TrendingUp : TrendingDown,
        text: `${((statusData.costAndSavings?.percentageSaved || 0)).toFixed(1)}% saved`,
        color: (statusData.costAndSavings?.todaysSavings || 0) >= 0 ? 'green' as const : 'red' as const
      },
      metrics: [
        {
          label: "Grid-Only Cost",
          value: statusData.costAndSavings?.gridOnlyCost || 0,
          unit: "SEK",
          icon: DollarSign
        },
        {
          label: "Today's Savings",
          value: statusData.costAndSavings?.todaysSavings || 0,
          unit: "SEK",
          icon: DollarSign,
          color: (statusData.costAndSavings?.todaysSavings || 0) >= 0 ? 'green' as const : 'red' as const
        },
        {
          label: "Percentage Saved",
          value: statusData.costAndSavings?.percentageSaved || 0,
          unit: "%",
          icon: TrendingUp,
          color: (statusData.costAndSavings?.percentageSaved || 0) >= 0 ? 'green' as const : 'red' as const
        }
      ]
    }
  ];

  return (
    <div className={`grid grid-cols-1 lg:grid-cols-3 gap-6 ${className}`}>
      {cards.map((card, index) => (
        <StatusCard
          key={index}
          title={card.title}
          icon={card.icon}
          color={card.color}
          keyMetric={card.keyMetric}
          keyValue={card.keyValue}
          keyUnit={card.keyUnit}
          metrics={card.metrics}
          status={card.status}
        />
      ))}
    </div>
  );
};

export default SystemStatusCard;