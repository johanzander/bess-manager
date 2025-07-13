import React, { useState, useEffect } from 'react';
import { Sun, Grid, Home, Battery } from 'lucide-react';
import api from '../lib/api';

interface FlowItem {
  label: string;
  value: number;
  unit: string;
  direction: 'to' | 'from';
  icon: React.ElementType;
}

interface SectionItem {
  label: string;
  value: number;
  percentage: number;
  icon: React.ElementType;
}

interface FlowSection {
  title: string;
  total: number;
  unit: string;
  color: 'blue' | 'green' | 'red' | 'yellow' | 'purple';
  items: SectionItem[];
}

interface EnergyFlowCard {
  title: string;
  icon: React.ElementType;
  color: 'blue' | 'green' | 'red' | 'yellow' | 'purple';
  keyMetric: string;
  keyValue: number | string;
  keyUnit: string;
  flows?: FlowItem[];
  sections?: FlowSection[];
}

interface EnergyFlowData {
  solarGeneration?: {
    solarProduction: number;
    toHome: number;
    toGrid: number;
    toBattery: number;
  };
  homeConsumption?: {
    homeConsumption: number;
    fromSolar: number;
    fromGrid: number;
    fromBattery: number;
  };
  gridFlow?: {
    importEnergy: number;
    exportEnergy: number;
    gridToHome: number;
    gridToBattery: number;
    solarToGrid: number;
    batteryToGrid: number;
  };
  batteryFlow?: {
    chargedToday: number;
    dischargedToday: number;
    solarToBattery: number;
    gridToBattery: number;
    batteryToHome: number;
    batteryToGrid: number;
  };
  efficiency?: {
    solarUtilization: number;
    gridIndependence: number;
    batteryEfficiency: number;
  };
}

const colorClasses = {
  blue: 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20',
  green: 'text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20',
  red: 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20',
  yellow: 'text-yellow-600 dark:text-yellow-400 bg-yellow-50 dark:bg-yellow-900/20',
  purple: 'text-purple-600 dark:text-purple-400 bg-purple-50 dark:bg-purple-900/20'
};

const EnergyFlowCard: React.FC<{ card: EnergyFlowCard }> = ({ card }) => {
  const IconComponent = card.icon;
  
  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700 p-4">
      <div className="flex items-center gap-3 mb-4">
        <div className={`p-2 rounded-lg ${colorClasses[card.color]}`}>
          <IconComponent className="w-5 h-5" />
        </div>
        <div>
          <h3 className="font-semibold text-gray-900 dark:text-white">{card.title}</h3>
          <p className="text-sm text-gray-600 dark:text-gray-300">{card.keyMetric}</p>
        </div>
      </div>
      
      <div className="mb-4">
        <div className="text-2xl font-bold text-gray-900 dark:text-white">
          {typeof card.keyValue === 'number' ? `${card.keyValue.toFixed(1)} ${card.keyUnit}` : `${card.keyValue} ${card.keyUnit}`}
        </div>
      </div>

      {card.flows && (
        <div className="space-y-2">
          {card.flows.map((flow, index) => (
            <div key={index} className="flex items-center justify-between py-1">
              <div className="flex items-center gap-2">
                <flow.icon className="w-4 h-4 text-gray-400 dark:text-gray-500" />
                <span className="text-sm text-gray-600 dark:text-gray-300">
                  {flow.direction === 'to' ? 'To' : 'From'} {flow.label}
                </span>
              </div>
              <span className="font-medium text-gray-900 dark:text-gray-100">
                {flow.value.toFixed(1)} {flow.unit}
              </span>
            </div>
          ))}
        </div>
      )}

      {card.sections && (
        <div className="space-y-3">
          {card.sections.map((section, sectionIndex) => (
            <div key={sectionIndex}>
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  {section.title}
                </span>
                <span className="text-sm font-bold text-gray-900 dark:text-gray-100">
                  {section.total.toFixed(1)} {section.unit}
                </span>
              </div>
              <div className="space-y-1">
                {section.items.map((item, itemIndex) => (
                  <div key={itemIndex} className="flex items-center justify-between text-sm">
                    <div className="flex items-center gap-2">
                      <item.icon className="w-3 h-3 text-gray-400" />
                      <span className="text-gray-600 dark:text-gray-300">{item.label}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-gray-500 dark:text-gray-400">
                        {item.percentage.toFixed(0)}%
                      </span>
                      <span className="font-medium text-gray-900 dark:text-gray-100">
                        {item.value.toFixed(1)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
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
        
        console.log('=== ENERGYFLOWCARDS DEBUG ===');
        console.log('Full API Response:', apiData);
        console.log('apiData.totals:', apiData.totals);
        if (apiData.totals) {
          console.log('Available totals keys:', Object.keys(apiData.totals));
        }

        // Use only canonical camelCase field names
        const totals = {
          solarProduction: apiData.totals?.totalSolarProduction || 0,
          homeConsumption: apiData.totals?.totalHomeConsumption || 0,
          gridImport: apiData.totals?.totalGridImport || 0,
          gridExport: apiData.totals?.totalGridExport || 0,
          
          // Battery totals
          batteryCharged: apiData.totals?.totalBatteryCharged || 0,
          batteryDischarged: apiData.totals?.totalBatteryDischarged || 0,
          
          // ✅ Battery flow details - camelCase only
          solarToHome: apiData.totals?.totalSolarToHome || 0,
          solarToBattery: apiData.totals?.totalSolarToBattery || 0,
          solarToGrid: apiData.totals?.totalSolarToGrid || 0,
          gridToHome: apiData.totals?.totalGridToHome || 0,
          gridToBattery: apiData.totals?.totalGridToBattery || 0,
          batteryToHome: apiData.totals?.totalBatteryToHome || 0,
          batteryToGrid: apiData.totals?.totalBatteryToGrid || 0
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

        const transformedData: EnergyFlowData = {
          solarGeneration: {
            solarProduction: totals.solarProduction,  
            toHome: totals.solarToHome,
            toGrid: totals.solarToGrid,
            toBattery: totals.solarToBattery
          },
          homeConsumption: {
            homeConsumption: totals.homeConsumption,  
            fromSolar: totals.solarToHome,
            fromGrid: totals.gridToHome,
            fromBattery: totals.batteryToHome
          },
          gridFlow: {
            importEnergy: totals.gridImport,
            exportEnergy: totals.gridExport,
            gridToHome: totals.gridToHome,
            gridToBattery: totals.gridToBattery,
            solarToGrid: totals.solarToGrid,
            batteryToGrid: totals.batteryToGrid
          },
          batteryFlow: {
            chargedToday: totals.batteryCharged,
            dischargedToday: totals.batteryDischarged,
            solarToBattery: totals.solarToBattery,
            gridToBattery: totals.gridToBattery,
            batteryToHome: totals.batteryToHome,
            batteryToGrid: totals.batteryToGrid
          },
          efficiency: {
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
      keyValue: energyData.solarGeneration?.solarProduction || 0,
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
      keyValue: energyData.homeConsumption?.homeConsumption || 0,
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
              percentage: (energyData.batteryFlow?.chargedToday || 0) > 0 ? 
                ((energyData.batteryFlow?.solarToBattery || 0) / (energyData.batteryFlow?.chargedToday || 1)) * 100 : 0,
              icon: Sun
            },
            {
              label: "From Grid",
              value: energyData.batteryFlow?.gridToBattery || 0,
              percentage: (energyData.batteryFlow?.chargedToday || 0) > 0 ? 
                ((energyData.batteryFlow?.gridToBattery || 0) / (energyData.batteryFlow?.chargedToday || 1)) * 100 : 0,
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
              percentage: (energyData.batteryFlow?.dischargedToday || 0) > 0 ? 
                ((energyData.batteryFlow?.batteryToHome || 0) / (energyData.batteryFlow?.dischargedToday || 1)) * 100 : 0,
              icon: Home
            },
            {
              label: "To Grid",
              value: energyData.batteryFlow?.batteryToGrid || 0,
              percentage: (energyData.batteryFlow?.dischargedToday || 0) > 0 ? 
                ((energyData.batteryFlow?.batteryToGrid || 0) / (energyData.batteryFlow?.dischargedToday || 1)) * 100 : 0,
              icon: Grid
            }
          ]
        }
      ]
    }
  ];

  return (
    <div className={`grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 ${className}`}>
      {cards.map((card, index) => (
        <EnergyFlowCard key={index} card={card} />
      ))}
    </div>
  );
};

export default EnergyFlowCards;