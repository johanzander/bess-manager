import React, { useState, useEffect } from 'react';
import { Sun, Grid, Home, Battery } from 'lucide-react';
import api from '../lib/api';

interface FlowItem {
  label: string;
  value: number;
  valueFormatted: string;
  unit: string;
  direction: 'to' | 'from';
  icon: React.ElementType;
}

interface SectionItem {
  label: string;
  value: number;
  valueFormatted: string;
  percentage: number;
  percentageFormatted: string;
  icon: React.ElementType;
}

interface FlowSection {
  title: string;
  total: number;
  totalFormatted: string;
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
    solarProductionFormatted: string;
    toHome: number;
    toHomeFormatted: string;
    toGrid: number;
    toGridFormatted: string;
    toBattery: number;
    toBatteryFormatted: string;
  };
  homeConsumption?: {
    homeConsumption: number;
    homeConsumptionFormatted: string;
    fromSolar: number;
    fromSolarFormatted: string;
    fromGrid: number;
    fromGridFormatted: string;
    fromBattery: number;
    fromBatteryFormatted: string;
  };
  gridFlow?: {
    importEnergy: number;
    importEnergyFormatted: string;
    exportEnergy: number;
    exportEnergyFormatted: string;
    gridToHome: number;
    gridToHomeFormatted: string;
    gridToBattery: number;
    gridToBatteryFormatted: string;
    solarToGrid: number;
    solarToGridFormatted: string;
    batteryToGrid: number;
    batteryToGridFormatted: string;
  };
  batteryFlow?: {
    chargedToday: number;
    chargedTodayFormatted: string;
    dischargedToday: number;
    dischargedTodayFormatted: string;
    solarToBattery: number;
    solarToBatteryFormatted: string;
    gridToBattery: number;
    gridToBatteryFormatted: string;
    batteryToHome: number;
    batteryToHomeFormatted: string;
    batteryToGrid: number;
    batteryToGridFormatted: string;
  };
  efficiency?: {
    solarUtilization: number;
    gridIndependence: number;
    batteryEfficiency: number;
  };
  // Store API summary data for percentage formatting
  apiSummary?: Record<string, any>;
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
          {card.keyValue} {card.keyUnit}
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
                {flow.valueFormatted}
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
                  {section.totalFormatted}
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
                        {item.percentageFormatted}%
                      </span>
                      <span className="font-medium text-gray-900 dark:text-gray-100">
                        {item.valueFormatted}
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

        // Validate API response structure
        if (!apiData || typeof apiData !== 'object' || apiData.detail) {
          throw new Error(`Invalid dashboard data: ${apiData?.detail || 'Unknown error'}`);
        }

        console.log('=== ENERGYFLOWCARDS DEBUG ===');
        console.log('Full API Response:', apiData);
        console.log('apiData.totals:', apiData.totals);
        console.log('apiData.summary:', apiData.summary);
        if (apiData.totals) {
          console.log('Available totals keys:', Object.keys(apiData.totals));
        }
        if (apiData.summary) {
          console.log('Available summary keys:', Object.keys(apiData.summary));
        }

        // Use only canonical camelCase field names from totals
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
            solarProductionFormatted: apiData.summary?.totalSolarProduction?.text,
            toHome: totals.solarToHome,
            toHomeFormatted: apiData.summary?.totalSolarToHome?.text,
            toGrid: totals.solarToGrid,
            toGridFormatted: apiData.summary?.totalSolarToGrid?.text,
            toBattery: totals.solarToBattery,
            toBatteryFormatted: apiData.summary?.totalSolarToBattery?.text
          },
          homeConsumption: {
            homeConsumption: totals.homeConsumption,
            homeConsumptionFormatted: apiData.summary?.totalHomeConsumption?.text,
            fromSolar: totals.solarToHome,
            fromSolarFormatted: apiData.summary?.totalSolarToHome?.text,
            fromGrid: totals.gridToHome,
            fromGridFormatted: apiData.summary?.totalGridToHome?.text,
            fromBattery: totals.batteryToHome,
            fromBatteryFormatted: apiData.summary?.totalBatteryToHome?.text
          },
          gridFlow: {
            importEnergy: totals.gridImport,
            importEnergyFormatted: apiData.summary?.totalGridImported?.text,
            exportEnergy: totals.gridExport,
            exportEnergyFormatted: apiData.summary?.totalGridExported?.text,
            gridToHome: totals.gridToHome,
            gridToHomeFormatted: apiData.summary?.totalGridToHome?.display,
            gridToBattery: totals.gridToBattery,
            gridToBatteryFormatted: apiData.summary?.totalGridToBattery?.display,
            solarToGrid: totals.solarToGrid,
            solarToGridFormatted: apiData.summary?.totalSolarToGrid?.display,
            batteryToGrid: totals.batteryToGrid,
            batteryToGridFormatted: apiData.summary?.totalBatteryToGrid?.display
          },
          batteryFlow: {
            chargedToday: totals.batteryCharged,
            chargedTodayFormatted: apiData.summary?.totalBatteryCharged?.text,
            dischargedToday: totals.batteryDischarged,
            dischargedTodayFormatted: apiData.summary?.totalBatteryDischarged?.text,
            solarToBattery: totals.solarToBattery,
            solarToBatteryFormatted: apiData.summary?.totalSolarToBattery?.display,
            gridToBattery: totals.gridToBattery,
            gridToBatteryFormatted: apiData.summary?.totalGridToBattery?.display,
            batteryToHome: totals.batteryToHome,
            batteryToHomeFormatted: apiData.summary?.totalBatteryToHome?.display,
            batteryToGrid: totals.batteryToGrid,
            batteryToGridFormatted: apiData.summary?.totalBatteryToGrid?.display
          },
          efficiency: {
            solarUtilization: 0,  // Not used in UI, backend should provide if needed
            gridIndependence: 0,  // Not used in UI, backend should provide if needed
            batteryEfficiency: 0  // Not used in UI, backend should provide if needed
          },
          // Store the API summary data for use in cards
          apiSummary: apiData.summary || {}
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
      keyValue: energyData.solarGeneration?.solarProductionFormatted,
      keyUnit: "",
      flows: [
        {
          label: "Home",
          value: energyData.solarGeneration?.toHome || 0,
          valueFormatted: energyData.solarGeneration?.toHomeFormatted,
          unit: "",
          direction: "to" as const,
          icon: Home
        },
        {
          label: "Grid",
          value: energyData.solarGeneration?.toGrid || 0,
          valueFormatted: energyData.solarGeneration?.toGridFormatted,
          unit: "", 
          direction: "to" as const,
          icon: Grid
        },
        {
          label: "Battery",
          value: energyData.solarGeneration?.toBattery || 0,
          valueFormatted: energyData.solarGeneration?.toBatteryFormatted,
          unit: "",
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
      keyValue: energyData.homeConsumption?.homeConsumptionFormatted,
      keyUnit: "",
      flows: [
        {
          label: "Solar",
          value: energyData.homeConsumption?.fromSolar || 0,
          valueFormatted: energyData.homeConsumption?.fromSolarFormatted,
          unit: "",
          direction: "from" as const,
          icon: Sun
        },
        {
          label: "Grid",
          value: energyData.homeConsumption?.fromGrid || 0,
          valueFormatted: energyData.homeConsumption?.fromGridFormatted,
          unit: "",
          direction: "from" as const,
          icon: Grid
        },
        {
          label: "Battery",
          value: energyData.homeConsumption?.fromBattery || 0,
          valueFormatted: energyData.homeConsumption?.fromBatteryFormatted,
          unit: "",
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
      keyValue: `${energyData.gridFlow?.importEnergyFormatted} / ${energyData.gridFlow?.exportEnergyFormatted}`,
      keyUnit: "",
      // Special Grid sections
      sections: [
        {
          title: "Import",
          total: energyData.gridFlow?.importEnergy || 0,
          totalFormatted: energyData.gridFlow?.importEnergyFormatted,
          unit: "",
          color: "blue" as const,
          items: [
            {
              label: "To Home",
              value: energyData.gridFlow?.gridToHome || 0,
              valueFormatted: energyData.gridFlow?.gridToHomeFormatted,
              percentage: energyData.apiSummary?.gridToHomePercentage?.value || 0,
              percentageFormatted: energyData.apiSummary?.gridToHomePercentage?.display,
              icon: Home
            },
            {
              label: "To Battery",
              value: energyData.gridFlow?.gridToBattery || 0,
              valueFormatted: energyData.gridFlow?.gridToBatteryFormatted,
              percentage: energyData.apiSummary?.gridToBatteryPercentage?.value || 0,
              percentageFormatted: energyData.apiSummary?.gridToBatteryPercentage?.display,
              icon: Battery
            }
          ]
        },
        {
          title: "Export",
          total: energyData.gridFlow?.exportEnergy || 0,
          totalFormatted: energyData.gridFlow?.exportEnergyFormatted,
          unit: "",
          color: "green" as const,
          items: [
            {
              label: "From Solar",
              value: energyData.gridFlow?.solarToGrid || 0,
              valueFormatted: energyData.gridFlow?.solarToGridFormatted,
              percentage: energyData.apiSummary?.solarToGridPercentage?.value || 0,
              percentageFormatted: energyData.apiSummary?.solarToGridPercentage?.display,
              icon: Sun
            },
            {
              label: "From Battery",
              value: energyData.gridFlow?.batteryToGrid || 0,
              valueFormatted: energyData.gridFlow?.batteryToGridFormatted,
              percentage: energyData.apiSummary?.batteryToGridPercentage?.value || 0,
              percentageFormatted: energyData.apiSummary?.batteryToGridPercentage?.display,
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
      keyValue: `${energyData.batteryFlow?.chargedTodayFormatted} / ${energyData.batteryFlow?.dischargedTodayFormatted}`,
      keyUnit: "",
      // Special Battery sections
      sections: [
        {
          title: "Charged",
          total: energyData.batteryFlow?.chargedToday || 0,
          totalFormatted: energyData.batteryFlow?.chargedTodayFormatted,
          unit: "",
          color: "green" as const,
          items: [
            {
              label: "From Solar",
              value: energyData.batteryFlow?.solarToBattery || 0,
              valueFormatted: energyData.batteryFlow?.solarToBatteryFormatted,
              percentage: energyData.apiSummary?.solarToBatteryPercentage?.value || 0,
              percentageFormatted: energyData.apiSummary?.solarToBatteryPercentage?.display,
              icon: Sun
            },
            {
              label: "From Grid",
              value: energyData.batteryFlow?.gridToBattery || 0,
              valueFormatted: energyData.batteryFlow?.gridToBatteryFormatted,
              percentage: energyData.apiSummary?.gridToBatteryChargedPercentage?.value || 0,
              percentageFormatted: energyData.apiSummary?.gridToBatteryChargedPercentage?.display,
              icon: Grid
            }
          ]
        },
        {
          title: "Discharged",
          total: energyData.batteryFlow?.dischargedToday || 0,
          totalFormatted: energyData.batteryFlow?.dischargedTodayFormatted,
          unit: "",
          color: "red" as const,
          items: [
            {
              label: "To Home",
              value: energyData.batteryFlow?.batteryToHome || 0,
              valueFormatted: energyData.batteryFlow?.batteryToHomeFormatted,
              percentage: energyData.apiSummary?.batteryToHomePercentage?.value || 0,
              percentageFormatted: energyData.apiSummary?.batteryToHomePercentage?.display,
              icon: Home
            },
            {
              label: "To Grid",
              value: energyData.batteryFlow?.batteryToGrid || 0,
              valueFormatted: energyData.batteryFlow?.batteryToGridFormatted,
              percentage: energyData.apiSummary?.batteryToGridDischargedPercentage?.value || 0,
              percentageFormatted: energyData.apiSummary?.batteryToGridDischargedPercentage?.display,
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