import React, { useState, useEffect } from 'react';
import api from '../lib/api';
import { 
  DollarSign, 
  Battery, 
  Heart,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  CheckCircle,
  Zap
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
  systemHealth?: {
    status: 'healthy' | 'warning' | 'error';
    uptime: number;
    lastOptimization: string;
    activeSessions: number;
    actualHours: number;
    totalHours: number;
  };
}

// StatusCard component
interface StatusCardProps {
  title: string;
  icon: React.ComponentType<any>;
  color: 'blue' | 'green' | 'red' | 'yellow' | 'purple';
  keyMetric: string;
  keyValue: number | string;
  keyUnit: string;
  metrics: {
    label: string;
    value: number | string;
    unit?: string;
    icon?: React.ComponentType<any>;
    color?: string;
  }[];
  status?: {
    icon: React.ComponentType<any>;
    text: string;
    color?: string;
  };
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
          {typeof keyValue === 'number' ? keyValue.toFixed(2) : keyValue}
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
                ? metric.label === "Percentage Saved" 
                  ? metric.value.toFixed(1) 
                  : metric.value.toFixed(2) 
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
        
        // Simply use the values from the backend without calculation
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
        
        // Debug log to see all available fields in the currentHourData
        if (currentHourData) {
          console.log("Current hour data fields:", Object.keys(currentHourData));
        }
        
        // Check for missing keys in hourly data
        if (currentHourData && currentHourData.batteryAction === undefined) {
          console.warn('Missing key: batteryAction in currentHourData');
        }
        
        const batteryPower = Math.abs(currentHourData?.batteryAction ?? 0);
        const batteryStatus = currentHourData?.batteryAction > 0.1 ? 'charging' : 
                            currentHourData?.batteryAction < -0.1 ? 'discharging' : 'idle';
        
        // Check for missing keys in system health data
        if (dashboardData.actualHoursCount === undefined) {
          console.warn('Missing key: actualHoursCount in dashboardData');
        }
        if (dashboardData.hourlyData === undefined) {
          console.warn('Missing key: hourlyData in dashboardData');
        }
        
        // System health indicators
        const actualHours = dashboardData.actualHoursCount ?? 0;
        const totalHours = dashboardData.hourlyData?.length ?? 24;
        const systemUptime = (actualHours / totalHours) * 100;
        
        const transformedData: SystemStatusData = {
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
            // The backend "battery_mode" is converted to "batteryMode" by the API
            batteryMode: currentHourData?.batteryMode || 'load-first'
          },
          systemHealth: {
            status: systemUptime > 90 ? 'healthy' : systemUptime > 70 ? 'warning' : 'error',
            uptime: systemUptime,
            lastOptimization: dashboardData.lastOptimization ?? 'Unknown',
            activeSessions: 1, // TODO: Get actual session count
            actualHours: actualHours,
            totalHours: totalHours
          }
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
      title: "Cost & Savings",
      icon: DollarSign,
      color: "blue" as const, // Changed to blue to match the cost theme
      keyMetric: "Today's Costs",
      keyValue: statusData.costAndSavings?.todaysCost || 0,
      keyUnit: "SEK",
      status: {
        icon: (statusData.costAndSavings?.todaysSavings || 0) >= 0 ? TrendingUp : TrendingDown,
        text: `${((statusData.costAndSavings?.percentageSaved || 0)).toFixed(1)}% saved`,
        color: (statusData.costAndSavings?.todaysSavings || 0) >= 0 ? 'green' : 'red' as const
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
          color: (statusData.costAndSavings?.todaysSavings || 0) >= 0 ? 'green' : 'red'
        },
        {
          label: "Percentage Saved",
          value: statusData.costAndSavings?.percentageSaved || 0,
          unit: "%",
          icon: TrendingUp,
          color: (statusData.costAndSavings?.percentageSaved || 0) >= 0 ? 'green' : 'red'
        }
      ]
    },
    {
      title: "Battery Status",
      icon: Battery,
      color: "blue" as const,
      keyMetric: "State of Charge",
      keyValue: statusData.batteryStatus?.soc || 0,
      keyUnit: "%",
      status: {
        icon: statusData.batteryStatus?.status === 'charging' ? TrendingUp :
              statusData.batteryStatus?.status === 'discharging' ? TrendingDown : CheckCircle,
        text: statusData.batteryStatus?.status === 'charging' ? 
          `Charging ${(statusData.batteryStatus?.power || 0).toFixed(1)}kW` :
          statusData.batteryStatus?.status === 'discharging' ? 
          `Discharging ${(statusData.batteryStatus?.power || 0).toFixed(1)}kW` : 
          'Idle',
        color: statusData.batteryStatus?.status === 'charging' ? 'green' :
               statusData.batteryStatus?.status === 'discharging' ? 'yellow' : 'blue' as const
      },
      metrics: [
        {
          label: "State of Energy",
          value: statusData.batteryStatus?.soe || 0,
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
          label: statusData.batteryStatus?.status === 'charging' ? 'Charging' :
                 statusData.batteryStatus?.status === 'discharging' ? 'Discharging' : 'Power',
          value: Math.abs(statusData.batteryStatus?.power || 0),
          unit: "kW",
          icon: statusData.batteryStatus?.status === 'charging' ? TrendingUp :
                statusData.batteryStatus?.status === 'discharging' ? TrendingDown : Zap,
          color: statusData.batteryStatus?.status === 'charging' ? 'green' :
                 statusData.batteryStatus?.status === 'discharging' ? 'yellow' : 'blue' as const
        }
      ]
    },
    {
      title: "System Health",
      icon: Heart,
      color: statusData.systemHealth?.status === 'healthy' ? "green" : 
             statusData.systemHealth?.status === 'warning' ? "yellow" : "red" as 'blue' | 'green' | 'red' | 'yellow' | 'purple',
      keyMetric: "Hours With Actual Data",
      keyValue: statusData.systemHealth?.uptime || 0,
      keyUnit: "%",
      status: {
        icon: statusData.systemHealth?.status === 'healthy' ? CheckCircle :
              statusData.systemHealth?.status === 'warning' ? AlertTriangle : TrendingDown,
        text: statusData.systemHealth?.status === 'healthy' ? 'Healthy' :
              statusData.systemHealth?.status === 'warning' ? 'Warning' : 'Error',
        color: statusData.systemHealth?.status === 'healthy' ? 'green' :
               statusData.systemHealth?.status === 'warning' ? 'yellow' : 'red'
      },
      metrics: [
        {
          label: "Data Available",
          value: `${statusData.systemHealth?.actualHours || 0} of ${statusData.systemHealth?.totalHours || 24}`,
          unit: "hours",
          icon: CheckCircle
        },
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