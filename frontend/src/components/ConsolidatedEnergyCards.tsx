// src/components/ConsolidatedEnergyCards.tsx
import React, { useState, useEffect } from 'react';
import api from '../lib/api';
import { 
  DollarSign, 
  Sun, 
  Home, 
  Battery, 
  Zap,
  TrendingUp,
  TrendingDown,
  Minus,
  ArrowRight,
  ArrowLeft,
  AlertCircle,
  Percent,
  Calculator,
  Wrench,
  CreditCard,
  PiggyBank
} from 'lucide-react';

// Types for your data structure
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
    wearCost: number;
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

interface EnergyFlowCardProps {
  title: string;
  icon: React.ComponentType<any>;
  color: 'blue' | 'yellow' | 'green' | 'purple' | 'orange';
  keyMetric: string;
  keyValue: string | number;
  keyUnit: string;
  minorMetrics: Array<{
    label: string;
    value: string | number;
    unit?: string;
    icon?: React.ComponentType<any>;
  }>;
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

  // Fetch data from your API using api.get (axios pattern)
  useEffect(() => {
    const fetchEnergyData = async () => {
      try {
        const response = await api.get('/api/schedule/current');
        const apiData = response.data;
        
        // Debug: Log the API response to see the actual structure
        console.log('=== API Response Debug ===');
        console.log('Full API Response:', apiData);
        console.log('Hourly Data Length:', apiData.hourlyData?.length);
        console.log('First Hour Sample:', apiData.hourlyData?.[0]);
        console.log('Summary:', apiData.summary);
        console.log('Total Daily Savings:', apiData.totalDailySavings);
        
        // Debug: Log detailed flows to verify energy balance
        console.log('=== Energy Balance Check ===');
        console.log('Battery capacity:', apiData.batteryCapacity || 'N/A', 'kWh');
        console.log('Solar production:', apiData.totals?.totalSolar || 'N/A');
        console.log('Solar to home:', apiData.totals?.totalSolarToHome || 'N/A');
        console.log('Solar to battery:', apiData.totals?.totalSolarToBattery || 'N/A');
        console.log('Solar to grid:', apiData.totals?.totalSolarToGrid || 'N/A');
        console.log('Home consumption:', apiData.totals?.totalConsumption || 'N/A');
        console.log('Grid to home:', apiData.totals?.totalGridToHome || 'N/A');
        console.log('Battery to home:', apiData.totals?.totalBatteryToHome || 'N/A');
        
        // Transform your API response using the CORRECT field names and PROPER detailed flows
        // Based on the actual API structure from your enhanced daily view
        const summary = apiData.summary || {};
        const hourlyData = apiData.hourlyData || [];
        
        // FIXED: Use correct field names after camelCase conversion
        // Calculate battery wear cost and grid costs
        const batteryWearCost = hourlyData.reduce((acc: number, hour: any) => 
          acc + (hour.batteryCycleCost || 0), 0);  // FIXED: batteryCost -> batteryCycleCost
        
        const gridImportCost = hourlyData.reduce((acc: number, hour: any) => 
          acc + ((hour.gridImport || 0) * (hour.buyPrice || 0)), 0);  // FIXED: gridImported -> gridImport
          
        const gridExportEarnings = hourlyData.reduce((acc: number, hour: any) => 
          acc + ((hour.gridExport || 0) * (hour.sellPrice || 0)), 0);  // FIXED: gridExported -> gridExport

        // FIXED: Use correct field names in totals calculation with ALL detailed flows
        const totals = hourlyData.reduce((acc: any, hour: any) => {
          acc.solarProduction += hour.solarProduction || 0;       // FIXED: solarGenerated -> solarProduction
          acc.homeConsumption += hour.homeConsumption || 0;       // FIXED: homeConsumed -> homeConsumption
          acc.gridImport += hour.gridImport || 0;                 // FIXED: gridImported -> gridImport
          acc.gridExport += hour.gridExport || 0;                 // FIXED: gridExported -> gridExport
          acc.batteryCharged += hour.batteryCharged || 0;
          acc.batteryDischarged += hour.batteryDischarged || 0;
          
          // FIXED: Add all detailed flow fields for proper energy balance
          acc.solarToHome += hour.solarToHome || 0;               // FIXED: directSolar -> solarToHome
          acc.solarToBattery += hour.solarToBattery || 0;         // FIXED: solarCharged -> solarToBattery
          acc.solarToGrid += hour.solarToGrid || 0;               // NEW: Need this for solar flow breakdown
          acc.gridToHome += hour.gridToHome || 0;                 // NEW: Need this for home consumption breakdown  
          acc.gridToBattery += hour.gridToBattery || 0;
          acc.batteryToHome += hour.batteryToHome || 0;           // NEW: Need this for home consumption breakdown
          acc.batteryToGrid += hour.batteryToGrid || 0;           // NEW: Need this to separate from solar export
          return acc;
        }, {
          solarProduction: 0,
          homeConsumption: 0,
          gridImport: 0,
          gridExport: 0,
          batteryCharged: 0,
          batteryDischarged: 0,
          solarToHome: 0,
          solarToBattery: 0,
          solarToGrid: 0,        // NEW
          gridToHome: 0,         // NEW
          gridToBattery: 0,
          batteryToHome: 0,      // NEW
          batteryToGrid: 0       // NEW
        });
        
        // Debug: Validate energy balance calculations
        console.log('=== Calculated Totals ===');
        console.log('Solar flows total:', (totals.solarToHome + totals.solarToBattery + totals.solarToGrid).toFixed(1), 'vs solar production:', totals.solarProduction.toFixed(1));
        console.log('Home consumption sources total:', (totals.solarToHome + totals.gridToHome + totals.batteryToHome).toFixed(1), 'vs home consumption:', totals.homeConsumption.toFixed(1));
        console.log('Grid export total:', (totals.solarToGrid + totals.batteryToGrid).toFixed(1), 'vs grid export:', totals.gridExport.toFixed(1));
        console.log('Grid import total:', (totals.gridToHome + totals.gridToBattery).toFixed(1), 'vs grid import:', totals.gridImport.toFixed(1));
        
        // Debug: Verify SOE calculation
        const currentSOC = apiData.hourlyData?.find((h: any) => h.hour === new Date().getHours())?.batteryLevel || 50;
        const calculatedSOE = (currentSOC / 100) * (apiData.batteryCapacity || 30);
        console.log('=== Battery SOE Check ===');
        console.log('Current SOC:', currentSOC.toFixed(1), '%');
        console.log('Battery capacity:', apiData.batteryCapacity || 'N/A', 'kWh');
        console.log('Calculated SOE:', calculatedSOE.toFixed(1), 'kWh');
        
        const transformedData: EnergyData = {
          costAndSavings: {
            todaysCost: (summary.baseCost || 0) - (apiData.totalDailySavings || 0),
            todaysSavings: apiData.totalDailySavings || 0,
            baseCost: summary.baseCost || 0,
            percentageSaved: summary.baseCost ? 
              ((apiData.totalDailySavings / summary.baseCost) * 100) : 0
          },
          solarGeneration: {
            production: totals.solarProduction,
            toHome: totals.solarToHome,                    // FIXED: Use actual solar->home flow
            toGrid: totals.solarToGrid,                    // FIXED: Use actual solar->grid flow (not total grid export)
            toBattery: totals.solarToBattery               // FIXED: Use actual solar->battery flow
          },
          homeConsumption: {
            consumption: totals.homeConsumption,
            fromSolar: totals.solarToHome,                 // FIXED: Use actual solar->home flow
            fromGrid: totals.gridToHome,                   // FIXED: Use actual grid->home flow (not total grid import)
            fromBattery: totals.batteryToHome              // FIXED: Use actual battery->home flow
          },
          batteryStatus: {
            soc: apiData.hourlyData?.find((h: any) => h.hour === new Date().getHours())?.batteryLevel || 50,  // FIXED: batterySocEnd -> batteryLevel
            soe: ((apiData.hourlyData?.find((h: any) => h.hour === new Date().getHours())?.batteryLevel || 50) / 100) * (apiData.batteryCapacity || 30), // FIXED: Use actual battery capacity
            chargedToday: totals.batteryCharged,
            dischargedToday: totals.batteryDischarged,
            status: getCurrentBatteryStatus(apiData),
            power: Math.abs(apiData.hourlyData?.find((h: any) => h.hour === new Date().getHours())?.batteryAction || 0),
            wearCost: batteryWearCost
          },
          grid: {
            importEnergy: totals.gridImport,               // This is correct - total grid import
            exportEnergy: totals.gridExport,               // This is correct - total grid export  
            netImport: totals.gridImport - totals.gridExport,
            importCost: gridImportCost,
            exportEarnings: gridExportEarnings,
            // FIXED: Add detailed flows for consistent To/From pattern
            toGrid: totals.solarToGrid + totals.batteryToGrid,  // Total energy going to grid
            fromGrid: totals.gridToHome + totals.gridToBattery  // Total energy coming from grid
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
      <div className="flex items-center justify-center p-8 border border-red-200 dark:border-red-800 rounded-xl bg-red-50 dark:bg-red-900/10">
        <div className="text-center">
          <AlertCircle className="h-8 w-8 text-red-600 dark:text-red-400 mx-auto mb-2" />
          <span className="text-red-700 dark:text-red-300">Error loading energy data</span>
        </div>
        <p className="text-red-600 dark:text-red-400 mt-2">{error}</p>
      </div>
    );
  }

  const cards = [
    {
      title: "Cost & Savings",
      icon: DollarSign,
      color: "blue" as const,
      keyMetric: "Today's Cost",
      keyValue: currentData.costAndSavings?.todaysCost || 0,
      keyUnit: "SEK",
      minorMetrics: [
        {
          label: "Base Cost",
          value: currentData.costAndSavings?.baseCost || 0,
          unit: "SEK",
          icon: Calculator
        },
        {
          label: "Savings Today",
          value: currentData.costAndSavings?.todaysSavings || 0,
          unit: "SEK",
          icon: TrendingDown
        },
        {
          label: "Cost Reduction",
          value: currentData.costAndSavings?.percentageSaved || 0,
          unit: "%",
          icon: Percent
        }
      ]
    },
    {
      title: "Solar Generation",
      icon: Sun,
      color: "yellow" as const,
      keyMetric: "Solar Production",
      keyValue: currentData.solarGeneration?.production || 0,
      keyUnit: "kWh",
      minorMetrics: [
        {
          label: "To Home",
          value: currentData.solarGeneration?.toHome || 0,
          unit: "kWh",
          icon: ArrowRight
        },
        {
          label: "To Grid",
          value: currentData.solarGeneration?.toGrid || 0,
          unit: "kWh",
          icon: TrendingUp
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
      color: "green" as const,
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
          icon: Zap
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
      title: "Grid",
      icon: Zap,
      color: "orange" as const,
      keyMetric: "From Grid",
      keyValue: currentData.grid?.fromGrid || 0,
      keyUnit: "kWh",
      minorMetrics: [
        {
          label: "To Grid",
          value: currentData.grid?.toGrid || 0,
          unit: "kWh",
          icon: TrendingUp
        },
        {
          label: "Import Cost",
          value: currentData.grid?.importCost || 0,
          unit: "SEK",
          icon: CreditCard
        },
        {
          label: "Export Earnings",
          value: currentData.grid?.exportEarnings || 0,
          unit: "SEK",
          icon: PiggyBank
        }
      ]
    },
    {
      title: "Battery Status",
      icon: Battery,
      color: "purple" as const,
      keyMetric: "State of Charge",
      keyValue: `${(currentData.batteryStatus?.soc || 0).toFixed(0)}%`,
      keyUnit: `${(currentData.batteryStatus?.soe || 0).toFixed(1)} kWh`,
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
          value: currentData.batteryStatus?.wearCost || 0,
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