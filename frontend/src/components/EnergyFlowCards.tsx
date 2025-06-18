import React, { useState, useEffect } from 'react';
import api from '../lib/api';
import { 
  Sun, 
  Home, 
  Battery, 
  Grid
} from 'lucide-react';

// Pure energy flow data structure
interface EnergyFlowData {
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
  gridFlow?: {
    importEnergy: number;
    exportEnergy: number;
    netImport: number;
    toGrid: number;
    fromGrid: number;
    // Detailed breakdown
    gridToHome: number;
    gridToBattery: number;
    solarToGrid: number;
    batteryToGrid: number;
  };
  batteryFlow?: {
    chargedToday: number;
    dischargedToday: number;
    netFlow: number;
    power: number;
    status: 'charging' | 'discharging' | 'idle';
    // Detailed breakdown
    solarToBattery: number;
    gridToBattery: number;
    batteryToHome: number;
    batteryToGrid: number;
  };
  balance?: {
    solarUtilization: number;
    gridIndependence: number;
    batteryEfficiency: number;
  };
}

// Reusable EnergyFlowCard component with support for nested flows
interface EnergyFlowCardProps {
  title: string;
  icon: React.ComponentType<any>;
  color: 'blue' | 'yellow' | 'green' | 'purple' | 'orange';
  keyMetric: string;
  keyValue: number | string;
  keyUnit: string;
  flows?: {
    label: string;
    value: number;
    unit: string;
    direction: 'to' | 'from';
    icon?: React.ComponentType<any>;
  }[];
  sections?: {
    title: string;
    total: number;
    unit: string;
    color: 'green' | 'red' | 'blue' | 'yellow';
    items: {
      label: string;
      value: number;
      percentage: number;
      icon?: React.ComponentType<any>;
    }[];
  }[];
  status?: {
    icon: React.ComponentType<any>;
    text: string;
  };
  className?: string;
}

const colorVariants = {
  blue: {
    border: 'border-blue-200 dark:border-blue-800',
    bg: 'bg-blue-50 dark:bg-blue-900/10',
    icon: 'text-blue-600 dark:text-blue-400',
    title: 'text-blue-900 dark:text-blue-100'
  },
  yellow: {
    border: 'border-yellow-200 dark:border-yellow-800',
    bg: 'bg-yellow-50 dark:bg-yellow-900/10',
    icon: 'text-yellow-600 dark:text-yellow-400',
    title: 'text-yellow-900 dark:text-yellow-100'
  },
  green: {
    border: 'border-green-200 dark:border-green-800',
    bg: 'bg-green-50 dark:bg-green-900/10',
    icon: 'text-green-600 dark:text-green-400',
    title: 'text-green-900 dark:text-green-100'
  },
  purple: {
    border: 'border-purple-200 dark:border-purple-800',
    bg: 'bg-purple-50 dark:bg-purple-900/10',
    icon: 'text-purple-600 dark:text-purple-400',
    title: 'text-purple-900 dark:text-purple-100'
  },
  orange: {
    border: 'border-orange-200 dark:border-orange-800',
    bg: 'bg-orange-50 dark:bg-orange-900/10',
    icon: 'text-orange-600 dark:text-orange-400',
    title: 'text-orange-900 dark:text-orange-100'
  }
};

const EnergyFlowCard: React.FC<EnergyFlowCardProps> = ({
  title,
  icon: Icon,
  color,
  keyMetric,
  keyValue,
  keyUnit,
  flows,
  sections,
  status,
  className = ""
}) => {
  const styles = colorVariants[color];

  return (
    <div className={`${styles.border} ${styles.bg} border-2 rounded-xl p-4 transition-all duration-200 hover:shadow-lg ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center">
          <Icon className={`h-5 w-5 mr-2 ${styles.icon}`} />
          <h3 className={`font-semibold ${styles.title}`}>{title}</h3>
        </div>
        {status && (
          <div className="flex items-center text-xs text-gray-600 dark:text-gray-400">
            <status.icon className="h-3 w-3 mr-1" />
            <span>{status.text}</span>
          </div>
        )}
      </div>

      {/* Key Metric */}
      <div className="mb-4">
        <p className="text-xs text-gray-600 dark:text-gray-400 mb-1">{keyMetric}</p>
        <p className="text-2xl font-bold text-gray-900 dark:text-gray-100">
          {typeof keyValue === 'number' ? keyValue.toFixed(1) : keyValue}
          <span className="text-sm font-normal text-gray-600 dark:text-gray-400 ml-1">{keyUnit}</span>
        </p>
      </div>

      {/* Special sections for Battery and Grid */}
      {(title === "Battery" || title === "Grid") && sections && (
        <div className="space-y-3 text-sm">
          <div>
            <div className="font-medium text-gray-700 dark:text-gray-300 mb-1 text-xs">
              {sections[0]?.title}
            </div>
            <div className="space-y-1 pl-3">
              {sections[0]?.items?.map((item, index) => (
                <div key={index} className="flex justify-between">
                  <div className="flex items-center">
                    {item.icon && <item.icon className="h-3 w-3 mr-1 text-gray-500 dark:text-gray-400" />}
                    <span className="text-gray-700 dark:text-gray-300">{item.label}</span>
                  </div>
                  <span className="font-medium text-gray-900 dark:text-gray-100">
                    {item.value?.toFixed(1) || '0.0'} kWh
                  </span>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="font-medium text-gray-700 dark:text-gray-300 mb-1 text-xs">
              {sections[1]?.title}
            </div>
            <div className="space-y-1 pl-3">
              {sections[1]?.items?.map((item, index) => (
                <div key={index} className="flex justify-between">
                  <div className="flex items-center">
                    {item.icon && <item.icon className="h-3 w-3 mr-1 text-gray-500 dark:text-gray-400" />}
                    <span className="text-gray-700 dark:text-gray-300">{item.label}</span>
                  </div>
                  <span className="font-medium text-gray-900 dark:text-gray-100">
                    {item.value?.toFixed(1) || '0.0'} kWh
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Normal flows for other cards */}
      {title !== "Battery" && title !== "Grid" && flows && (
        <div className="space-y-2">
          {flows.map((flow, index) => (
            <div key={index} className="flex items-center justify-between text-sm">
              <div className="flex items-center">
                {flow.icon && <flow.icon className="h-3 w-3 mr-1 text-gray-500 dark:text-gray-400" />}
                <span className="text-gray-700 dark:text-gray-300">
                  {flow.direction === 'to' ? 'To' : 'From'} {flow.label}
                </span>
              </div>
              <span className="font-medium text-gray-900 dark:text-gray-100">
                {flow.value.toFixed(1)}
                <span className="opacity-70 ml-1">{flow.unit}</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

interface EnergyFlowCardsProps {
  className?: string;
}

const EnergyFlowCards: React.FC<EnergyFlowCardsProps> = ({ className = "" }) => {
  const [energyData, setEnergyData] = useState<EnergyFlowData>({});
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchEnergyData = async () => {
      try {
        setIsLoading(true);
        const response = await api.get('/api/dashboard');
        const apiData = response.data;
        
        // 🔍 DEBUGGING: Log what we actually receive
        console.log('=== ENERGYFLOWCARDS DEBUG ===');
        console.log('Full API Response:', apiData);
        console.log('apiData.totals:', apiData.totals);
        if (apiData.totals) {
          console.log('Available totals keys:', Object.keys(apiData.totals));
          
          // Check specific battery fields
          const batteryFieldsToCheck = [
            'totalBatteryCharge', 'total_battery_charge',
            'totalBatteryDischarge', 'total_battery_discharge',
            'totalSolarToBattery', 'total_solar_to_battery',
            'totalGridToBattery', 'total_grid_to_battery',
            'totalBatteryToHome', 'total_battery_to_home',
            'totalBatteryToGrid', 'total_battery_to_grid'
          ];
          
          batteryFieldsToCheck.forEach(field => {
            const value = apiData.totals[field];
            if (value !== undefined) {
              console.log(`✅ ${field}: ${value}`);
            } else {
              console.log(`❌ ${field}: undefined`);
            }
          });
        }

        // ✅ Use correct field names (try both camelCase and snake_case)
        const totals = {
          solarProduction: apiData.totals?.totalSolar || apiData.totals?.total_solar || 0,
          homeConsumption: apiData.totals?.totalConsumption || apiData.totals?.total_consumption || 0,
          gridImport: apiData.totals?.totalGridImport || apiData.totals?.total_grid_import || 0,
          gridExport: apiData.totals?.totalGridExport || apiData.totals?.total_grid_export || 0,
          
          // ✅ Battery totals - key fix with fallbacks
          batteryCharged: apiData.totals?.totalBatteryCharge || apiData.totals?.total_battery_charge || 0,
          batteryDischarged: apiData.totals?.totalBatteryDischarge || apiData.totals?.total_battery_discharge || 0,
          
          // ✅ Battery flow details  
          solarToHome: apiData.totals?.totalSolarToHome || apiData.totals?.total_solar_to_home || 0,
          solarToBattery: apiData.totals?.totalSolarToBattery || apiData.totals?.total_solar_to_battery || 0,
          solarToGrid: apiData.totals?.totalSolarToGrid || apiData.totals?.total_solar_to_grid || 0,
          gridToHome: apiData.totals?.totalGridToHome || apiData.totals?.total_grid_to_home || 0,
          gridToBattery: apiData.totals?.totalGridToBattery || apiData.totals?.total_grid_to_battery || 0,
          batteryToHome: apiData.totals?.totalBatteryToHome || apiData.totals?.total_battery_to_home || 0,
          batteryToGrid: apiData.totals?.totalBatteryToGrid || apiData.totals?.total_battery_to_grid || 0
        };
        
        console.log('✅ Final totals used:', totals);
        console.log('✅ Battery operations check:', {
          charged: totals.batteryCharged,
          discharged: totals.batteryDischarged,
          solarToBattery: totals.solarToBattery,
          gridToBattery: totals.gridToBattery,
          batteryToHome: totals.batteryToHome,
          batteryToGrid: totals.batteryToGrid
        });
        console.log('=== END DEBUG ===');

        // Get current battery power and status from hourly data
        const currentHour = new Date().getHours();
        const currentHourData = apiData.hourlyData?.find((h: any) => h.hour === currentHour);
        const batteryPower = Math.abs(currentHourData?.batteryAction || 0);
        const batteryStatus = currentHourData?.batteryAction > 0.1 ? 'charging' : 
                            currentHourData?.batteryAction < -0.1 ? 'discharging' : 'idle';

        // ✅ Calculate battery totals from flows since the direct totals are 0
        const calculatedChargedToday = totals.solarToBattery + totals.gridToBattery;
        const calculatedDischargedToday = totals.batteryToHome + totals.batteryToGrid;

        console.log('Battery calculations:', {
          directCharged: totals.batteryCharged,
          directDischarged: totals.batteryDischarged,
          calculatedCharged: calculatedChargedToday,
          calculatedDischarged: calculatedDischargedToday
        });

        const transformedData: EnergyFlowData = {
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
          gridFlow: {
            importEnergy: totals.gridImport,
            exportEnergy: totals.gridExport,
            netImport: totals.gridImport - totals.gridExport,
            toGrid: totals.solarToGrid + totals.batteryToGrid,
            fromGrid: totals.gridToHome + totals.gridToBattery,
            gridToHome: totals.gridToHome,
            gridToBattery: totals.gridToBattery,
            solarToGrid: totals.solarToGrid,
            batteryToGrid: totals.batteryToGrid
          },
          batteryFlow: {
            chargedToday: calculatedChargedToday, // Use calculated value
            dischargedToday: calculatedDischargedToday, // Use calculated value
            netFlow: calculatedChargedToday - calculatedDischargedToday,
            power: batteryPower,
            status: batteryStatus,
            solarToBattery: totals.solarToBattery,
            gridToBattery: totals.gridToBattery,
            batteryToHome: totals.batteryToHome,
            batteryToGrid: totals.batteryToGrid
          },
          balance: {
            solarUtilization: totals.solarProduction > 0 ? 
              ((totals.solarToHome + totals.solarToBattery) / totals.solarProduction) * 100 : 0,
            gridIndependence: totals.homeConsumption > 0 ? 
              ((totals.solarToHome + totals.batteryToHome) / totals.homeConsumption) * 100 : 0,
            batteryEfficiency: totals.batteryCharged > 0 ? 
              (totals.batteryDischarged / totals.batteryCharged) * 100 : 0
          }
        };
        
        setEnergyData(transformedData);
        setError(null);
        console.log('✅ EnergyFlowCards: Data loaded successfully', transformedData);
      } catch (err) {
        console.error('Failed to fetch energy flow data:', err);
        setError('Failed to load energy flow data');
      } finally {
        setIsLoading(false);
      }
    };

    fetchEnergyData(); // ONE TIME ONLY - NO REFRESH INTERVAL
  }, []);

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="border rounded-lg p-4 bg-gray-50 animate-pulse">
            <div className="h-6 bg-gray-200 rounded mb-3"></div>
            <div className="h-8 bg-gray-200 rounded mb-3"></div>
            <div className="space-y-2">
              <div className="h-4 bg-gray-200 rounded"></div>
              <div className="h-4 bg-gray-200 rounded"></div>
              <div className="h-4 bg-gray-200 rounded"></div>
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-red-600 text-center p-4">
        {error}
      </div>
    );
  }

  const cards = [
    {
      title: "Solar Production",
      icon: Sun,
      color: "yellow" as const,
      keyMetric: "Total Production",
      keyValue: energyData.solarGeneration?.production || 0,
      keyUnit: "kWh",
      flows: [
        {
          label: "Home",
          value: energyData.solarGeneration?.toHome || 0,
          unit: "kWh",
          direction: "to" as const,
          icon: Home
        },
        {
          label: "Grid",
          value: energyData.solarGeneration?.toGrid || 0,
          unit: "kWh", 
          direction: "to" as const,
          icon: Grid
        },
        {
          label: "Battery",
          value: energyData.solarGeneration?.toBattery || 0,
          unit: "kWh",
          direction: "to" as const,
          icon: Battery
        }
      ]
    },
    {
      title: "Home Consumption", 
      icon: Home,
      color: "blue" as const,
      keyMetric: "Total Consumption",
      keyValue: energyData.homeConsumption?.consumption || 0,
      keyUnit: "kWh",
      flows: [
        {
          label: "Solar",
          value: energyData.homeConsumption?.fromSolar || 0,
          unit: "kWh",
          direction: "from" as const,
          icon: Sun
        },
        {
          label: "Grid",
          value: energyData.homeConsumption?.fromGrid || 0,
          unit: "kWh",
          direction: "from" as const,
          icon: Grid
        },
        {
          label: "Battery",
          value: energyData.homeConsumption?.fromBattery || 0,
          unit: "kWh",
          direction: "from" as const,
          icon: Battery
        }
      ]
    },
    {
      title: "Grid",
      icon: Grid,
      color: "purple" as const,
      keyMetric: "Import / Export",
      keyValue: `${(energyData.gridFlow?.importEnergy || 0).toFixed(1)} / ${(energyData.gridFlow?.exportEnergy || 0).toFixed(1)}`,
      keyUnit: "kWh",
      // Special Grid sections
      sections: [
        {
          title: "Import",
          total: energyData.gridFlow?.importEnergy || 0,
          unit: "kWh",
          color: "blue" as const,
          items: [
            {
              label: "To Home",
              value: energyData.gridFlow?.gridToHome || 0,
              percentage: (energyData.gridFlow?.importEnergy || 0) > 0 ? 
                ((energyData.gridFlow?.gridToHome || 0) / (energyData.gridFlow?.importEnergy || 1)) * 100 : 0,
              icon: Home
            },
            {
              label: "To Battery",
              value: energyData.gridFlow?.gridToBattery || 0,
              percentage: (energyData.gridFlow?.importEnergy || 0) > 0 ? 
                ((energyData.gridFlow?.gridToBattery || 0) / (energyData.gridFlow?.importEnergy || 1)) * 100 : 0,
              icon: Battery
            }
          ]
        },
        {
          title: "Export",
          total: energyData.gridFlow?.exportEnergy || 0,
          unit: "kWh",
          color: "green" as const,
          items: [
            {
              label: "From Solar",
              value: energyData.gridFlow?.solarToGrid || 0,
              percentage: (energyData.gridFlow?.exportEnergy || 0) > 0 ? 
                ((energyData.gridFlow?.solarToGrid || 0) / (energyData.gridFlow?.exportEnergy || 1)) * 100 : 0,
              icon: Sun
            },
            {
              label: "From Battery",
              value: energyData.gridFlow?.batteryToGrid || 0,
              percentage: (energyData.gridFlow?.exportEnergy || 0) > 0 ? 
                ((energyData.gridFlow?.batteryToGrid || 0) / (energyData.gridFlow?.exportEnergy || 1)) * 100 : 0,
              icon: Battery
            }
          ]
        }
      ]
    },
    {
      title: "Battery",
      icon: Battery,
      color: "green" as const,
      keyMetric: "Charged / Discharged",
      keyValue: `${(energyData.batteryFlow?.chargedToday || 0).toFixed(1)} / ${(energyData.batteryFlow?.dischargedToday || 0).toFixed(1)}`,
      keyUnit: "kWh",
      // Special Battery sections
      sections: [
        {
          title: "Charged",
          total: energyData.batteryFlow?.chargedToday || 0,
          unit: "kWh",
          color: "green" as const,
          items: [
            {
              label: "From Solar",
              value: energyData.batteryFlow?.solarToBattery || 0,
              percentage: energyData.batteryFlow?.chargedToday > 0 ? 
                (energyData.batteryFlow.solarToBattery / energyData.batteryFlow.chargedToday) * 100 : 0,
              icon: Sun
            },
            {
              label: "From Grid",
              value: energyData.batteryFlow?.gridToBattery || 0,
              percentage: energyData.batteryFlow?.chargedToday > 0 ? 
                (energyData.batteryFlow.gridToBattery / energyData.batteryFlow.chargedToday) * 100 : 0,
              icon: Grid
            }
          ]
        },
        {
          title: "Discharged",
          total: energyData.batteryFlow?.dischargedToday || 0,
          unit: "kWh",
          color: "red" as const,
          items: [
            {
              label: "To Home",
              value: energyData.batteryFlow?.batteryToHome || 0,
              percentage: energyData.batteryFlow?.dischargedToday > 0 ? 
                (energyData.batteryFlow.batteryToHome / energyData.batteryFlow.dischargedToday) * 100 : 0,
              icon: Home
            },
            {
              label: "To Grid",
              value: energyData.batteryFlow?.batteryToGrid || 0,
              percentage: energyData.batteryFlow?.dischargedToday > 0 ? 
                (energyData.batteryFlow.batteryToGrid / energyData.batteryFlow.dischargedToday) * 100 : 0,
              icon: Grid
            }
          ]
        }
      ]
      // ✅ Removed status completely
    }
  ];

  return (
    <div className={`grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 ${className}`}>
      {cards.map((card, index) => (
        <EnergyFlowCard
          key={index}
          title={card.title}
          icon={card.icon}
          color={card.color}
          keyMetric={card.keyMetric}
          keyValue={card.keyValue}
          keyUnit={card.keyUnit}
          flows={card.flows}
          sections={card.sections}
          status={card.status}
        />
      ))}
    </div>
  );
};

export default EnergyFlowCards;