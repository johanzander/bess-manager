import React from 'react';
import { Sun, Grid, Home, Battery } from 'lucide-react';
import { useDashboardData } from '../hooks/useDashboardData';

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
  const { data: apiData, loading: isLoading, error } = useDashboardData();

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

  // Validate API data availability - no more transformation needed!
  if (!apiData?.summary) {
    throw new Error('MISSING DATA: apiData.summary is required for energy flow calculations');
  }

  const cards = [
    {
      title: "Solar Production",
      icon: Sun,
      color: "yellow" as const,
      keyMetric: "Total Production",
      keyValue: apiData.summary.totalSolarProduction?.text,
      keyUnit: "",
      flows: [
        {
          label: "Home",
          value: apiData.summary.totalSolarToHome?.value || 0,
          valueFormatted: apiData.summary.totalSolarToHome?.text,
          unit: "",
          direction: "to" as const,
          icon: Home
        },
        {
          label: "Grid",
          value: apiData.summary.totalSolarToGrid?.value || 0,
          valueFormatted: apiData.summary.totalSolarToGrid?.text,
          unit: "", 
          direction: "to" as const,
          icon: Grid
        },
        {
          label: "Battery",
          value: apiData.summary.totalSolarToBattery?.value || 0,
          valueFormatted: apiData.summary.totalSolarToBattery?.text,
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
      keyValue: apiData.summary.totalHomeConsumption?.text,
      keyUnit: "",
      flows: [
        {
          label: "Solar",
          value: apiData.summary.totalSolarToHome?.value || 0,
          valueFormatted: apiData.summary.totalSolarToHome?.text,
          unit: "",
          direction: "from" as const,
          icon: Sun
        },
        {
          label: "Grid",
          value: apiData.summary.totalGridToHome?.value || 0,
          valueFormatted: apiData.summary.totalGridToHome?.text,
          unit: "",
          direction: "from" as const,
          icon: Grid
        },
        {
          label: "Battery",
          value: apiData.summary.totalBatteryToHome?.value || 0,
          valueFormatted: apiData.summary.totalBatteryToHome?.text,
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
      keyValue: `${apiData.summary.totalGridImported?.text} / ${apiData.summary.totalGridExported?.text}`,
      keyUnit: "",
      // Special Grid sections
      sections: [
        {
          title: "Import",
          total: apiData.summary.totalGridImported?.value || 0,
          totalFormatted: apiData.summary.totalGridImported?.text,
          unit: "",
          color: "blue" as const,
          items: [
            {
              label: "To Home",
              value: apiData.summary.totalGridToHome?.value || 0,
              valueFormatted: apiData.summary.totalGridToHome?.text,
              percentage: apiData.summary?.gridToHomePercentage?.value || 0,
              percentageFormatted: apiData.summary?.gridToHomePercentage?.display,
              icon: Home
            },
            {
              label: "To Battery",
              value: apiData.summary.totalGridToBattery?.value || 0,
              valueFormatted: apiData.summary.totalGridToBattery?.text,
              percentage: apiData.summary?.gridToBatteryPercentage?.value || 0,
              percentageFormatted: apiData.summary?.gridToBatteryPercentage?.display,
              icon: Battery
            }
          ]
        },
        {
          title: "Export",
          total: apiData.summary.totalGridExported?.value || 0,
          totalFormatted: apiData.summary.totalGridExported?.text,
          unit: "",
          color: "green" as const,
          items: [
            {
              label: "From Solar",
              value: apiData.summary.totalSolarToGrid?.value || 0,
              valueFormatted: apiData.summary.totalSolarToGrid?.text,
              percentage: apiData.summary?.solarToGridPercentage?.value || 0,
              percentageFormatted: apiData.summary?.solarToGridPercentage?.display,
              icon: Sun
            },
            {
              label: "From Battery",
              value: apiData.summary.totalBatteryToGrid?.value || 0,
              valueFormatted: apiData.summary.totalBatteryToGrid?.text,
              percentage: apiData.summary?.batteryToGridPercentage?.value || 0,
              percentageFormatted: apiData.summary?.batteryToGridPercentage?.display,
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
      keyValue: `${apiData.summary.totalBatteryCharged?.text} / ${apiData.summary.totalBatteryDischarged?.text}`,
      keyUnit: "",
      // Special Battery sections
      sections: [
        {
          title: "Charged",
          total: apiData.summary.totalBatteryCharged?.value || 0,
          totalFormatted: apiData.summary.totalBatteryCharged?.text,
          unit: "",
          color: "green" as const,
          items: [
            {
              label: "From Solar",
              value: apiData.summary.totalSolarToBattery?.value || 0,
              valueFormatted: apiData.summary.totalSolarToBattery?.text,
              percentage: apiData.summary?.solarToBatteryPercentage?.value || 0,
              percentageFormatted: apiData.summary?.solarToBatteryPercentage?.display,
              icon: Sun
            },
            {
              label: "From Grid",
              value: apiData.summary.totalGridToBattery?.value || 0,
              valueFormatted: apiData.summary.totalGridToBattery?.text,
              percentage: apiData.summary?.gridToBatteryChargedPercentage?.value || 0,
              percentageFormatted: apiData.summary?.gridToBatteryChargedPercentage?.display,
              icon: Grid
            }
          ]
        },
        {
          title: "Discharged",
          total: apiData.summary.totalBatteryDischarged?.value || 0,
          totalFormatted: apiData.summary.totalBatteryDischarged?.text,
          unit: "",
          color: "red" as const,
          items: [
            {
              label: "To Home",
              value: apiData.summary.totalBatteryToHome?.value || 0,
              valueFormatted: apiData.summary.totalBatteryToHome?.text,
              percentage: apiData.summary?.batteryToHomePercentage?.value || 0,
              percentageFormatted: apiData.summary?.batteryToHomePercentage?.display,
              icon: Home
            },
            {
              label: "To Grid",
              value: apiData.summary.totalBatteryToGrid?.value || 0,
              valueFormatted: apiData.summary.totalBatteryToGrid?.text,
              percentage: apiData.summary?.batteryToGridDischargedPercentage?.value || 0,
              percentageFormatted: apiData.summary?.batteryToGridDischargedPercentage?.display,
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