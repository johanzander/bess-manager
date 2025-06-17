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
  Wrench,
  Zap
} from 'lucide-react';

// System status data structure
interface SystemStatusData {
  costAndSavings?: {
    todaysCost: number;
    todaysSavings: number;
    baseCost: number;
    percentageSaved: number;
  };
  batteryStatus?: {
    soc: number;
    soe: number;
    capacity: number;
    power: number;
    status: 'charging' | 'discharging' | 'idle';
    batteryCost: number;
    health: number;
  };
  systemHealth?: {
    status: 'healthy' | 'warning' | 'error';
    uptime: number;
    lastOptimization: string;
    activeSessions: number;
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
    color?: 'green' | 'red' | 'yellow' | 'blue';
  }[];
  status?: {
    icon: React.ComponentType<any>;
    text: string;
    color?: 'green' | 'red' | 'yellow';
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

  const metricColorClasses = {
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
              {typeof metric.value === 'number' ? metric.value.toFixed(2) : metric.value}
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

const SystemStatusCard: React.FC<SystemStatusCardProps> = ({ className = "" }) => {
  const [statusData, setStatusData] = useState<SystemStatusData>({});
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchStatusData = async () => {
      try {
        setIsLoading(true);
        
        // Fetch dashboard data first (required)
        const dashboardResponse = await api.get('/api/dashboard');
        const dashboardData = dashboardResponse.data;
        
        // Try to fetch inverter data (optional, fallback to dashboard if fails)
        let inverterData = null;
        try {
          const inverterResponse = await api.get('/api/growatt/inverter_status');
          inverterData = inverterResponse.data;
        } catch (inverterError) {
          console.warn('Could not fetch inverter status, using dashboard data only:', inverterError);
          // Will use dashboard data for SOC instead
        }
        
        // Get current battery SOC from inverter endpoint (preferred) or dashboard (fallback)
        const currentSOC = inverterData?.battery_soc || dashboardData.currentBatterySoc || 0;
        const currentSOE = inverterData?.battery_soe || 
                          dashboardData.currentBatterySoe || 
                          (currentSOC / 100) * (dashboardData.batteryCapacity || 0);
        const batteryCapacity = dashboardData.batteryCapacity || 0;
        
        // Calculate costs from dashboard data
        const batteryCycleCost = dashboardData.summary?.batteryCycleCost || 0;
        const baseCost = dashboardData.summary?.baseCost || 0;
        const optimizedCost = dashboardData.summary?.optimizedCost || 0;
        const dailySavings = dashboardData.totalDailySavings || 0;
        
        // Get current battery power and status
        const currentHour = new Date().getHours();
        const currentHourData = dashboardData.hourlyData?.find((h: any) => h.hour === currentHour);
        const batteryPower = Math.abs(currentHourData?.batteryAction || 0);
        const batteryStatus = currentHourData?.batteryAction > 0.1 ? 'charging' : 
                            currentHourData?.batteryAction < -0.1 ? 'discharging' : 'idle';
        
        // System health indicators
        const actualHours = dashboardData.actualHoursCount || 0;
        const totalHours = dashboardData.hourlyData?.length || 24;
        const systemUptime = (actualHours / totalHours) * 100;
        
        const transformedData: SystemStatusData = {
          costAndSavings: {
            todaysCost: optimizedCost,
            todaysSavings: dailySavings,
            baseCost: baseCost,
            percentageSaved: baseCost > 0 ? (dailySavings / baseCost) * 100 : 0
          },
          batteryStatus: {
            soc: currentSOC,
            soe: currentSOE,
            capacity: batteryCapacity,
            power: batteryPower,
            status: batteryStatus,
            batteryCost: batteryCycleCost,
            health: 95 // TODO: Get actual battery health from system
          },
          systemHealth: {
            status: systemUptime > 90 ? 'healthy' : systemUptime > 70 ? 'warning' : 'error',
            uptime: systemUptime,
            lastOptimization: dashboardData.lastOptimization || 'Unknown',
            activeSessions: 1 // TODO: Get actual session count
          }
        };
        
        setStatusData(transformedData);
        setError(null);
        console.log('SystemStatusCard: Data loaded successfully', {
          dashboardAvailable: !!dashboardData,
          inverterAvailable: !!inverterData,
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
      color: "green" as const,
      keyMetric: "Today's Savings",
      keyValue: statusData.costAndSavings?.todaysSavings || 0,
      keyUnit: "SEK",
      status: {
        icon: statusData.costAndSavings?.todaysSavings >= 0 ? TrendingUp : TrendingDown,
        text: `${(statusData.costAndSavings?.percentageSaved || 0).toFixed(1)}% saved`,
        color: statusData.costAndSavings?.todaysSavings >= 0 ? 'green' : 'red' as const
      },
      metrics: [
        {
          label: "Optimized Cost",
          value: statusData.costAndSavings?.todaysCost || 0,
          unit: "SEK",
          icon: DollarSign,
          color: 'blue' as const
        },
        {
          label: "Base Cost",
          value: statusData.costAndSavings?.baseCost || 0,
          unit: "SEK",
          icon: DollarSign
        },
        {
          label: "Percentage Saved",
          value: statusData.costAndSavings?.percentageSaved || 0,
          unit: "%",
          icon: TrendingUp,
          color: statusData.costAndSavings?.percentageSaved >= 0 ? 'green' : 'red' as const
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
          icon: Zap,
          color: 'blue' as const
        },
        {
          label: "Capacity",
          value: statusData.batteryStatus?.capacity || 0,
          unit: "kWh",
          icon: Battery
        },
        {
          label: "Battery Wear Cost",
          value: statusData.batteryStatus?.batteryCost || 0,
          unit: "SEK",
          icon: Wrench,
          color: 'yellow' as const
        },
        {
          label: "Battery Health",
          value: statusData.batteryStatus?.health || 0,
          unit: "%",
          icon: Heart,
          color: statusData.batteryStatus?.health >= 90 ? 'green' : 
                 statusData.batteryStatus?.health >= 70 ? 'yellow' : 'red' as const
        }
      ]
    },
    {
      title: "System Health",
      icon: Heart,
      color: statusData.systemHealth?.status === 'healthy' ? "green" : 
             statusData.systemHealth?.status === 'warning' ? "yellow" : "red",
      keyMetric: "System Uptime",
      keyValue: statusData.systemHealth?.uptime || 0,
      keyUnit: "%",
      status: {
        icon: statusData.systemHealth?.status === 'healthy' ? CheckCircle :
              statusData.systemHealth?.status === 'warning' ? AlertTriangle : TrendingDown,
        text: statusData.systemHealth?.status === 'healthy' ? 'Healthy' :
              statusData.systemHealth?.status === 'warning' ? 'Warning' : 'Error',
        color: statusData.systemHealth?.status === 'healthy' ? 'green' :
               statusData.systemHealth?.status === 'warning' ? 'yellow' : 'red' as const
      },
      metrics: [
        {
          label: "Last Optimization",
          value: statusData.systemHealth?.lastOptimization || 'Unknown',
          icon: TrendingUp
        },
        {
          label: "Active Sessions",
          value: statusData.systemHealth?.activeSessions || 0,
          icon: Zap,
          color: 'blue' as const
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