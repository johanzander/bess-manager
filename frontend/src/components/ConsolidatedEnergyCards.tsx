import React, { useState, useEffect } from 'react';
import api from '../lib/api';
import { 
  DollarSign, 
  Sun, 
  Home, 
  Battery, 
  Grid,
  TrendingUp,
  TrendingDown,
  Minus,
  Wrench
} from 'lucide-react';

// Energy data structure
interface EnergyData {
  costAndSavings?: {
    todaysCost: number;
    todaysSavings: number;
    baseCost: number;
    percentageSaved: number;
  };
  solarGeneration?: {
    production: number;
    toHome: number;
    toGrid: number;
    toBattery: number;
  };
  homeConsumption?: {
    consumption: number;
    fromSolar: number;
    fromGrid: number;
    fromBattery: number;
  };
  batteryStatus?: {
    soc: number;
    soe: number;
    chargedToday: number;
    dischargedToday: number;
    status: 'charging' | 'discharging' | 'idle';
    power: number;
    batteryCost: number;
  };
  grid?: {
    importEnergy: number;
    exportEnergy: number;
    netImport: number;
    importCost: number;
    exportEarnings: number;
    toGrid: number;
    fromGrid: number;
  };
}

// EnergyFlowCard component (UNCHANGED)
interface EnergyFlowCardProps {
  title: string;
  icon: React.ComponentType<any>;
  color: 'blue' | 'yellow' | 'green' | 'purple' | 'orange';
  keyMetric: string;
  keyValue: number | string;
  keyUnit: string;
  minorMetrics: {
    label: string;
    value: number | string;
    unit?: string;
    icon?: React.ComponentType<any>;
  }[];
  status?: {
    icon: React.ComponentType<any>;
    text: string;
  };
  className?: string;
}

const EnergyFlowCard: React.FC<EnergyFlowCardProps> = ({
  title,
  icon: Icon,
  color,
  keyMetric,
  keyValue,
  keyUnit,
  minorMetrics,
  status,
  className = ""
}) => {
  // FIXED: Proper dark mode with clean colors and good contrast
  const colorClasses = {
    blue: {
      bg: "bg-blue-50 dark:bg-blue-900/10",
      border: "border-blue-200 dark:border-blue-800",
      icon: "text-blue-600 dark:text-blue-400",
      text: "text-blue-900 dark:text-blue-100",
      iconBg: "bg-blue-100 dark:bg-blue-800/20"
    },
    yellow: {
      bg: "bg-yellow-50 dark:bg-yellow-900/10",
      border: "border-yellow-200 dark:border-yellow-800", 
      icon: "text-yellow-600 dark:text-yellow-400",
      text: "text-yellow-900 dark:text-yellow-100",
      iconBg: "bg-yellow-100 dark:bg-yellow-800/20"
    },
    green: {
      bg: "bg-green-50 dark:bg-green-900/10",
      border: "border-green-200 dark:border-green-800",
      icon: "text-green-600 dark:text-green-400", 
      text: "text-green-900 dark:text-green-100",
      iconBg: "bg-green-100 dark:bg-green-800/20"
    },
    purple: {
      bg: "bg-purple-50 dark:bg-purple-900/10",
      border: "border-purple-200 dark:border-purple-800",
      icon: "text-purple-600 dark:text-purple-400",
      text: "text-purple-900 dark:text-purple-100", 
      iconBg: "bg-purple-100 dark:bg-purple-800/20"
    },
    orange: {
      bg: "bg-orange-50 dark:bg-orange-900/10",
      border: "border-orange-200 dark:border-orange-800",
      icon: "text-orange-600 dark:text-orange-400",
      text: "text-orange-900 dark:text-orange-100",
      iconBg: "bg-orange-100 dark:bg-orange-800/20"
    }
  };

  const colorClass = colorClasses[color];

  return (
    <div className={`
      ${colorClass.bg} ${colorClass.border}
      border rounded-xl p-6 transition-all duration-200 hover:shadow-lg
      ${className}
    `}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center space-x-3">
          <div className={`p-2 rounded-lg ${colorClass.iconBg}`}>
            <Icon className={`h-5 w-5 ${colorClass.icon}`} />
          </div>
          <h3 className={`text-lg font-semibold ${colorClass.text}`}>{title}</h3>
        </div>
        {status && (
          <div className="flex items-center space-x-1">
            <status.icon className={`h-4 w-4 ${colorClass.icon}`} />
            <span className={`text-sm font-medium ${colorClass.text}`}>
              {status.text}
            </span>
          </div>
        )}
      </div>

      {/* Key Metric */}
      <div className="mb-4">
        <div className="flex items-baseline space-x-2">
          <span className={`text-3xl font-bold ${colorClass.text}`}>
            {typeof keyValue === 'number' ?
              keyValue.toFixed(1) : keyValue}
          </span>
          <span className={`text-lg font-medium ${colorClass.text} opacity-80`}>
            {keyUnit}
          </span>
        </div>
        <p className={`text-sm ${colorClass.text} opacity-70 mt-1`}>{keyMetric}</p>
      </div>

      {/* Minor Metrics */}
      <div className="space-y-2">
        {minorMetrics.map((metric, index) => (
          <div key={index} className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              {metric.icon && <metric.icon className={`h-4 w-4 ${colorClass.icon} opacity-70`} />}
              <span className={`text-sm ${colorClass.text} opacity-80`}>
                {metric.label}
              </span>
            </div>
            <span className={`text-sm font-semibold ${colorClass.text}`}>
              {typeof metric.value === 'number' ? 
                (metric.label.includes('SOC') || metric.label.includes('Net') ? 
                  metric.value.toFixed(1) : 
                  metric.value.toFixed(1)
                ) : metric.value}
              {metric.unit && <span className="opacity-70 ml-1">{metric.unit}</span>}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};

interface ConsolidatedEnergyCardsProps {
  data?: EnergyData;
  isLoading?: boolean;
  error?: string;
}

const ConsolidatedEnergyCards: React.FC<ConsolidatedEnergyCardsProps> = ({ 
  data, 
  isLoading = false, 
  error 
}) => {
  const [energyData, setEnergyData] = useState<EnergyData>({});

  // Use unified dashboard API instead of old schedule endpoint
  useEffect(() => {
    const fetchEnergyData = async () => {
      try {
        // CHANGED: Use unified /api/dashboard instead of /api/schedule/current
        const response = await api.get('/api/dashboard');
        const apiData = response.data;
        
        // Transform API response using the CORRECT field names from unified dashboard API
        // Calculate battery wear cost and grid costs from hourly data
        const batteryCycleCost = apiData.summary?.batteryCycleCost || 0;
        const gridImportCost = apiData.summary?.totalGridImportCost || 0;
        const gridExportEarnings = apiData.summary?.totalGridExportEarnings || 0;
        const netCost = (apiData.summary?.totalGridImportCost || 0) - (apiData.summary?.totalGridExportEarnings || 0)

        // FIXED: Calculate totals from unified dashboard API totals field
        const totals = {
          solarProduction: apiData.totals?.totalSolar || 0,
          homeConsumption: apiData.totals?.totalConsumption || 0,
          gridImport: apiData.totals?.totalGridImport || 0,
          gridExport: apiData.totals?.totalGridExport || 0,
          batteryCharged: apiData.totals?.totalBatteryCharge || 0,
          batteryDischarged: apiData.totals?.totalBatteryDischarge || 0,
          solarToHome: apiData.totals?.totalSolarToHome || 0,
          solarToBattery: apiData.totals?.totalSolarToBattery || 0,
          solarToGrid: apiData.totals?.totalSolarToGrid || 0,
          gridToHome: apiData.totals?.totalGridToHome || 0,
          gridToBattery: apiData.totals?.totalGridToBattery || 0,
          batteryToHome: apiData.totals?.totalBatteryToHome || 0,
          batteryToGrid: apiData.totals?.totalBatteryToGrid || 0
        };
        
        // Debug: Verify SOE calculation
        const currentSOC = apiData.currentBatterySoc;
        const currentSOE = apiData.currentBatterySoe;
        
        // FIXED: Transform dashboard API data to EnergyData structure (EXACT SAME STRUCTURE, JUST FIXED DATA MAPPING)
        const transformedData: EnergyData = {
          costAndSavings: {
            todaysCost: apiData.summary?.optimizedCost || 0,
            todaysSavings: apiData.totalDailySavings || 0,
            baseCost: apiData.summary?.baseCost || 0,
            percentageSaved: apiData.summary?.baseCost > 0 ? 
              ((apiData.totalDailySavings || 0) / apiData.summary.baseCost) * 100 : 0
          },
          solarGeneration: {
            production: totals.solarProduction,
            toHome: totals.solarToHome,
            toGrid: totals.solarToGrid,
            toBattery: totals.solarToBattery
          },
          homeConsumption: {
            consumption: totals.homeConsumption,
            fromSolar: totals.solarToHome,
            fromGrid: totals.gridToHome,
            fromBattery: totals.batteryToHome
          },
          batteryStatus: {
            soc: currentSOC,
            soe: currentSOE,
            chargedToday: totals.batteryCharged,
            dischargedToday: totals.batteryDischarged,
            status: getCurrentBatteryStatus(apiData),
            power: Math.abs(apiData.hourlyData?.find((h: any) => h.hour === new Date().getHours())?.batteryAction || 0),
            batteryCost: batteryCycleCost
          },
          grid: {
            importEnergy: totals.gridImport,
            exportEnergy: totals.gridExport,
            netImport: totals.gridImport - totals.gridExport,
            importCost: gridImportCost,
            exportEarnings: gridExportEarnings,
            toGrid: totals.solarToGrid + totals.batteryToGrid,
            fromGrid: totals.gridToHome + totals.gridToBattery
          }
        };
        
        setEnergyData(transformedData);
      } catch (err) {
        console.error('Failed to fetch energy data:', err);
      }
    };

    fetchEnergyData();
    const interval = setInterval(fetchEnergyData, 30000); // Refresh every 30 seconds
    return () => clearInterval(interval);
  }, []);

  const getCurrentBatteryStatus = (apiData: any): 'charging' | 'discharging' | 'idle' => {
    const currentHour = new Date().getHours();
    const currentHourData = apiData.hourlyData?.find((h: any) => h.hour === currentHour);
    
    if (!currentHourData) return 'idle';
    
    const batteryAction = currentHourData.batteryAction || 0;
    if (batteryAction > 0.1) return 'charging';
    if (batteryAction < -0.1) return 'discharging';
    return 'idle';
  };

  const currentData = data || energyData;

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-6">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="animate-pulse">
            <div className="rounded-xl border border-gray-200 dark:border-gray-700 p-6 h-48 bg-gray-100 dark:bg-gray-800"></div>
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center p-8 border border-red-200 dark:border-red-800 rounded-xl bg-red-50 dark:bg-red-900/20">
        <span className="text-red-700 dark:text-red-300">{error}</span>
      </div>
    );
  }

  // UNCHANGED: Same exact card generation logic
  const cards = [
    {
      title: "Cost & Savings",
      icon: DollarSign,
      color: "green" as const,
      keyMetric: "Today's Cost",
      keyValue: currentData.costAndSavings?.todaysCost || 0,
      keyUnit: "SEK",
      minorMetrics: [
        {
          label: "Base Cost",
          value: currentData.costAndSavings?.baseCost || 0,
          unit: "SEK",
          icon: DollarSign
        },
        {
          label: "Today's Savings",
          value: currentData.costAndSavings?.todaysSavings || 0,
          unit: "SEK",
          icon: DollarSign
        },
        {
          label: "Percentage Saved",
          value: currentData.costAndSavings?.percentageSaved || 0,
          unit: "%",
          icon: TrendingUp
        },
      ]
    },
    {
      title: "Solar Production",
      icon: Sun,
      color: "yellow" as const,
      keyMetric: "Total Production",
      keyValue: currentData.solarGeneration?.production || 0,
      keyUnit: "kWh",
      minorMetrics: [
        {
          label: "To Home",
          value: currentData.solarGeneration?.toHome || 0,
          unit: "kWh",
          icon: Home
        },
        {
          label: "To Grid",
          value: currentData.solarGeneration?.toGrid || 0,
          unit: "kWh",
          icon: Grid
        },
        {
          label: "To Battery",
          value: currentData.solarGeneration?.toBattery || 0,
          unit: "kWh",
          icon: Battery
        }
      ]
    },
    {
      title: "Home Consumption",
      icon: Home,
      color: "blue" as const,
      keyMetric: "Total Consumption",
      keyValue: currentData.homeConsumption?.consumption || 0,
      keyUnit: "kWh",
      minorMetrics: [
        {
          label: "From Solar",
          value: currentData.homeConsumption?.fromSolar || 0,
          unit: "kWh",
          icon: Sun
        },
        {
          label: "From Grid",
          value: currentData.homeConsumption?.fromGrid || 0,
          unit: "kWh",
          icon: Grid
        },
        {
          label: "From Battery",
          value: currentData.homeConsumption?.fromBattery || 0,
          unit: "kWh",
          icon: Battery
        }
      ]
    },
    {
      title: "Grid Exchange",
      icon: Grid,
      color: "orange" as const,
      keyMetric: "Net Import",
      keyValue: currentData.grid?.netImport || 0,
      keyUnit: "kWh",
      minorMetrics: [
        {
          label: "Import Cost",
          value: currentData.grid?.importCost || 0,
          unit: "SEK",
          icon: TrendingDown
        },
        {
          label: "Export Earnings",
          value: currentData.grid?.exportEarnings || 0,
          unit: "SEK",
          icon: TrendingUp
        },
        {
          label: "Net Cost",
          value: (currentData.grid?.importCost || 0) - (currentData.grid?.exportEarnings || 0),
          unit: "SEK",
          icon: DollarSign
        }
      ]
    },
    {
      title: "Battery",
      icon: Battery,
      color: "purple" as const,
      keyMetric: "State of Charge",
      keyValue: currentData.batteryStatus?.soc || 0,
      keyUnit: "%",
      status: {
        icon: currentData.batteryStatus?.status === 'charging' ? TrendingUp :
              currentData.batteryStatus?.status === 'discharging' ? TrendingDown : Minus,
        text: currentData.batteryStatus?.status === 'charging' ? 
          `Charging ${(currentData.batteryStatus?.power || 0).toFixed(1)}kW` :
          currentData.batteryStatus?.status === 'discharging' ? 
          `Discharging ${(currentData.batteryStatus?.power || 0).toFixed(1)}kW` : 
          'Idle'
      },
      minorMetrics: [
        {
          label: "Charged Today",
          value: currentData.batteryStatus?.chargedToday || 0,
          unit: "kWh",
          icon: TrendingUp
        },
        {
          label: "Discharged Today",
          value: currentData.batteryStatus?.dischargedToday || 0,
          unit: "kWh",
          icon: TrendingDown
        },
        {
          label: "Battery Wear Cost",
          value: currentData.batteryStatus?.batteryCost || 0,
          unit: "SEK",
          icon: Wrench
        }
      ]
    }
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-6">
      {cards.map((card, index) => (
        <EnergyFlowCard
          key={index}
          title={card.title}
          icon={card.icon}
          color={card.color}
          keyMetric={card.keyMetric}
          keyValue={card.keyValue}
          keyUnit={card.keyUnit}
          minorMetrics={card.minorMetrics}
          status={card.status}
        />
      ))}
    </div>
  );
};

export default ConsolidatedEnergyCards;