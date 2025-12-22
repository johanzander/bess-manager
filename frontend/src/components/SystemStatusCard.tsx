import React, { useState, useEffect, useMemo } from 'react';
import api from '../lib/api';
import { useDashboardData } from '../hooks/useDashboardData';
import { FormattedValue } from '../types';
import { DashboardResponse } from '../api/scheduleApi';
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
          {keyValue}
          {keyUnit && <span className="text-lg font-normal text-gray-600 dark:text-gray-400 ml-2">{keyUnit}</span>}
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
              {metric.value}
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
  const { data: dashboardData, loading: dashboardLoading, error: dashboardError } = useDashboardData();
  const [inverterData, setInverterData] = useState<any>(null);
  const [inverterLoading, setInverterLoading] = useState(true);
  const [inverterError, setInverterError] = useState<string | null>(null);

  useEffect(() => {
    const fetchInverterData = async () => {
      try {
        setInverterLoading(true);
        const inverterResponse = await api.get('/api/growatt/inverter_status');
        setInverterData(inverterResponse.data);
        setInverterError(null);
      } catch (err) {
        console.error('Failed to fetch inverter data:', err);
        const errorMessage = err instanceof Error ? err.message : 'Unknown error';
        setInverterError(`Failed to load inverter data: ${errorMessage}`);
      } finally {
        setInverterLoading(false);
      }
    };

    fetchInverterData();
  }, []);

  const statusData = useMemo(() => {
    if (!dashboardData || !inverterData) return {};

    // Validate dashboard data structure
    if (typeof dashboardData !== 'object') {
      console.error(`Invalid dashboard data structure: Unknown error`);
      return {};
    }

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

    // Check for missing keys in summary data (comment out missing field check)
    // batteryCycleCost is not in the summary interface
    if (dashboardData.summary?.gridOnlyCost === undefined) {
      console.warn('Missing key: summary.gridOnlyCost in dashboardData');
    }
    if (dashboardData.summary?.optimizedCost === undefined) {
      console.warn('Missing key: summary.optimizedCost in dashboardData');
    }
    if (dashboardData.totalDailySavings === undefined) {
      console.warn('Missing key: totalDailySavings in dashboardData');
    }

    // Get current battery power and status from quarterly or hourly data
    const now = new Date();
    const currentHour = now.getHours();
    const currentMinute = now.getMinutes();

    // Calculate current period index (0-95) for quarterly resolution
    const currentPeriodIndex = currentHour * 4 + Math.floor(currentMinute / 15);

    // Find current period data - supports both hourly (24 periods) and quarterly (96 periods)
    const currentHourData = dashboardData.hourlyData?.length === 24
      ? dashboardData.hourlyData.find((h: any) => h.hour === currentHour)  // Hourly mode
      : dashboardData.hourlyData?.[currentPeriodIndex];  // Quarterly mode (direct array access)

    // Validate hourlyData exists
    if (!dashboardData.hourlyData || !Array.isArray(dashboardData.hourlyData)) {
      console.warn('BACKEND ISSUE: Missing or invalid hourlyData array in dashboardData');
    }

    // Get actual battery mode from inverter status (not schedule)
    if (!inverterData.batteryMode) {
      throw new Error('MISSING DATA: inverterData.batteryMode is required but missing');
    }
    const actualBatteryMode = inverterData.batteryMode;

    // Check for missing keys in hourly data
    if (currentHourData && currentHourData.batteryAction === undefined) {
      console.warn('Missing key: batteryAction in currentHourData');
    }

    if (!currentHourData) {
      throw new Error('MISSING DATA: currentHourData is required but not found in hourlyData');
    }
    if (currentHourData.batteryAction === undefined) {
      throw new Error('MISSING DATA: batteryAction is required but missing from currentHourData');
    }
    const batteryPower = Math.abs(currentHourData.batteryAction);
    const batteryStatus = currentHourData.batteryAction > 0.1 ? 'charging' :
                        currentHourData.batteryAction < -0.1 ? 'discharging' : 'idle';

    return {
      costAndSavings: {
        todaysCost: (() => {
          if (!dashboardData.summary?.optimizedCost) {
            throw new Error('MISSING DATA: summary.optimizedCost is required for cost display');
          }
          return dashboardData.summary.optimizedCost;
        })(),
        todaysSavings: (() => {
          if (!dashboardData.summary?.totalSavings) {
            throw new Error('MISSING DATA: summary.totalSavings is required for savings display');
          }
          return dashboardData.summary.totalSavings;
        })(),
        gridOnlyCost: (() => {
          if (!dashboardData.summary?.gridOnlyCost) {
            throw new Error('MISSING DATA: summary.gridOnlyCost is required for cost comparison');
          }
          return dashboardData.summary.gridOnlyCost;
        })(),
        percentageSaved: (() => {
          if (!dashboardData.summary?.totalSavingsPercentage) {
            throw new Error('MISSING DATA: summary.totalSavingsPercentage is required for percentage display');
          }
          return dashboardData.summary.totalSavingsPercentage;
        })()
      },
      batteryStatus: {
        soc: (() => {
          if (!dashboardData.batterySoc) {
            throw new Error('MISSING DATA: batterySoc is required for battery status display');
          }
          return dashboardData.batterySoc as any;
        })(),
        soe: (() => {
          if (!dashboardData.batterySoe) {
            throw new Error('MISSING DATA: batterySoe is required for battery energy display');
          }
          return dashboardData.batterySoe as any;
        })(),
        power: batteryPower,
        status: batteryStatus,
        // Use the actual inverter battery mode instead of optimization schedule
        batteryMode: actualBatteryMode
      },
      realTimePower: (() => {
        if (!dashboardData.realTimePower) {
          throw new Error('MISSING DATA: realTimePower is required for power flow display');
        }
        return dashboardData.realTimePower as any;
      })(),
      batteryCapacity: (() => {
        if (!dashboardData.batteryCapacity) {
          throw new Error('MISSING DATA: batteryCapacity is required for battery capacity display');
        }
        return dashboardData.batteryCapacity;
      })()
    };
  }, [dashboardData, inverterData]);

  const isLoading = dashboardLoading || inverterLoading;
  const error = dashboardError || inverterError;

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
      keyValue: statusData.realTimePower?.solarPower?.text || '0 W',
      keyUnit: "",
      status: {
        icon: (statusData.realTimePower?.gridExportPower?.value || 0) > 0.1 ? TrendingUp :
              (statusData.realTimePower?.gridImportPower?.value || 0) > 0.1 ? TrendingDown : CheckCircle,
        text: (statusData.realTimePower?.gridExportPower?.value || 0) > 0.1 ? `${statusData.realTimePower?.gridExportPower?.text} exporting` :
              (statusData.realTimePower?.gridImportPower?.value || 0) > 0.1 ? `${statusData.realTimePower?.gridImportPower?.text} importing` : 'Grid balanced',
        color: (statusData.realTimePower?.gridExportPower?.value || 0) > 0.1 ? 'green' as const :
               (statusData.realTimePower?.gridImportPower?.value || 0) > 0.1 ? 'red' as const : 'green' as const
      },
      metrics: [
        {
          label: "Home Load",
          value: statusData.realTimePower?.homeLoadPower?.text || '0 W',
          unit: "",
          icon: Home
        },
        {
          label: "Grid Flow",
          value: (statusData.realTimePower?.gridExportPower?.value || 0) > 0.1 ? `${statusData.realTimePower?.gridExportPower?.text} Export ↑` :
                 (statusData.realTimePower?.gridImportPower?.value || 0) > 0.1 ? `${statusData.realTimePower?.gridImportPower?.text} Import ↓` : '0 W',
          unit: "",
          icon: Zap,
          color: (statusData.realTimePower?.gridExportPower?.value || 0) > 0.1 ? 'green' as const :
                 (statusData.realTimePower?.gridImportPower?.value || 0) > 0.1 ? 'red' as const : undefined
        },
        {
          label: "Battery",
          value: (statusData.realTimePower?.netBatteryPower?.value || 0) > 0.1 ? `${statusData.realTimePower?.batteryChargePower?.text} Charging ↑` :
                 (statusData.realTimePower?.netBatteryPower?.value || 0) < -0.1 ? `${statusData.realTimePower?.batteryDischargePower?.text} Discharging ↓` : '0 W',
          unit: "",
          icon: Battery,
          color: (statusData.realTimePower?.netBatteryPower?.value || 0) > 0.1 ? 'green' as const :
                 (statusData.realTimePower?.netBatteryPower?.value || 0) < -0.1 ? 'yellow' as const : undefined
        }
      ]
    },
    {
      title: "Energy & Power",
      icon: Battery,
      color: "blue" as const,
      keyMetric: (statusData.realTimePower?.netBatteryPower?.value || 0) > 0.1 ?
        `Charging ${statusData.realTimePower?.batteryChargePower?.display}kW` :
        (statusData.realTimePower?.netBatteryPower?.value || 0) < -0.1 ?
        `Discharging ${statusData.realTimePower?.batteryDischargePower?.display}kW` :
        'Idle',
      keyValue: "",
      keyUnit: "",
      status: {
        icon: (statusData.realTimePower?.netBatteryPower?.value || 0) > 0.1 ? TrendingUp :
              (statusData.realTimePower?.netBatteryPower?.value || 0) < -0.1 ? TrendingDown : CheckCircle,
        text: (statusData.realTimePower?.netBatteryPower?.value || 0) > 0.1 ?
          `Charging ${statusData.realTimePower?.batteryChargePower?.text}` :
          (statusData.realTimePower?.netBatteryPower?.value || 0) < -0.1 ?
          `Discharging ${statusData.realTimePower?.batteryDischargePower?.text}` :
          'Idle',
        color: (statusData.realTimePower?.netBatteryPower?.value || 0) > 0.1 ? 'green' as const :
               (statusData.realTimePower?.netBatteryPower?.value || 0) < -0.1 ? 'yellow' as const : 'blue' as const
      },
      metrics: [
        {
          label: "State of Charge",
          value: (() => {
            if (!statusData.batteryStatus?.soc?.display) {
              throw new Error('MISSING DATA: batterySoc.display is required for SOC display');
            }
            return statusData.batteryStatus.soc.display;
          })(),
          unit: "%",
          icon: Battery
        },
        {
          label: "State of Energy",
          value: (() => {
            if (!statusData.batteryStatus?.soe?.display) {
              throw new Error('MISSING DATA: batterySoe.display is required for SOE display');
            }
            if (!statusData.batteryCapacity) {
              throw new Error('MISSING DATA: batteryCapacity is required for SOE display');
            }
            return `${statusData.batteryStatus.soe.display}/${statusData.batteryCapacity}`;
          })(),
          unit: "kWh",
          icon: Zap
        },
        {
          label: (statusData.realTimePower?.netBatteryPower?.value || 0) > 0.1 ? 'Charging Power' :
                 (statusData.realTimePower?.netBatteryPower?.value || 0) < -0.1 ? 'Discharging Power' : 'Battery Power',
          value: (statusData.realTimePower?.netBatteryPower?.value || 0) > 0.1 ? statusData.realTimePower?.batteryChargePower?.display :
                 (statusData.realTimePower?.netBatteryPower?.value || 0) < -0.1 ? statusData.realTimePower?.batteryDischargePower?.display :
                 statusData.realTimePower?.netBatteryPower?.display,
          unit: "kW",
          icon: (statusData.realTimePower?.netBatteryPower?.value || 0) > 0.1 ? TrendingUp :
                (statusData.realTimePower?.netBatteryPower?.value || 0) < -0.1 ? TrendingDown : Zap,
          color: (statusData.realTimePower?.netBatteryPower?.value || 0) > 0.1 ? 'green' as const :
                 (statusData.realTimePower?.netBatteryPower?.value || 0) < -0.1 ? 'yellow' as const : 'blue' as const
        },
        {
          label: "Solar Production",
          value: statusData.realTimePower?.solarPower?.display || "0.0",
          unit: "kW",
          icon: Zap
        }
      ]
    },
    {
      title: "Today's Cost & Savings",
      icon: DollarSign,
      color: "blue" as const,
      keyMetric: "Today's Costs",
      keyValue: statusData.costAndSavings?.todaysCost?.text,
      keyUnit: "",
      status: {
        icon: (statusData.costAndSavings?.todaysSavings?.value || 0) >= 0 ? TrendingUp : TrendingDown,
        text: `${statusData.costAndSavings?.percentageSaved?.text} saved`,
        color: (statusData.costAndSavings?.todaysSavings?.value || 0) >= 0 ? 'green' as const : 'red' as const
      },
      metrics: [
        {
          label: "Grid-Only Cost",
          value: statusData.costAndSavings?.gridOnlyCost?.text,
          unit: "",
          icon: DollarSign
        },
        {
          label: "Today's Savings",
          value: statusData.costAndSavings?.todaysSavings?.text,
          unit: "",
          icon: DollarSign,
          color: (statusData.costAndSavings?.todaysSavings?.value || 0) >= 0 ? 'green' as const : 'red' as const
        },
        {
          label: "Percentage Saved",
          value: statusData.costAndSavings?.percentageSaved?.text,
          unit: "",
          icon: TrendingUp,
          color: (statusData.costAndSavings?.percentageSaved?.value || 0) >= 0 ? 'green' as const : 'red' as const
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