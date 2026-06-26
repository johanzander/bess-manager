import React, { useState } from 'react';
import { Battery, ChevronDown, ChevronRight, Zap } from 'lucide-react';
import { useDashboardData } from '../hooks/useDashboardData';
import { DataResolution } from '../hooks/useUserPreferences';
import { periodToTimeString, periodToEndTime } from '../utils/timeUtils';

interface EnergyFlowTableProps {
  resolution: DataResolution;
}

const FLOWS = [
  { key: 'solarToHome',    label: 'Sol→Home',  headerBg: 'bg-yellow-100 dark:bg-yellow-900/30', cellBg: 'bg-yellow-50 dark:bg-yellow-900/20', activeColor: 'text-yellow-600 dark:text-yellow-400' },
  { key: 'solarToBattery', label: 'Sol→Bat',   headerBg: 'bg-yellow-100 dark:bg-yellow-900/30', cellBg: 'bg-yellow-50 dark:bg-yellow-900/20', activeColor: 'text-yellow-600 dark:text-yellow-400' },
  { key: 'solarToGrid',    label: 'Sol→Grid',  headerBg: 'bg-yellow-100 dark:bg-yellow-900/30', cellBg: 'bg-yellow-50 dark:bg-yellow-900/20', activeColor: 'text-green-600 dark:text-green-400' },
  { key: 'gridToHome',     label: 'Grid→Home', headerBg: 'bg-blue-100 dark:bg-blue-900/30',   cellBg: 'bg-blue-50 dark:bg-blue-900/20',   activeColor: 'text-red-600 dark:text-red-400' },
  { key: 'gridToBattery',  label: 'Grid→Bat',  headerBg: 'bg-blue-100 dark:bg-blue-900/30',   cellBg: 'bg-blue-50 dark:bg-blue-900/20',   activeColor: 'text-red-600 dark:text-red-400' },
  { key: 'batteryToHome',  label: 'Bat→Home',  headerBg: 'bg-orange-100 dark:bg-orange-900/30', cellBg: 'bg-orange-50 dark:bg-orange-900/20', activeColor: 'text-orange-600 dark:text-orange-400' },
  { key: 'batteryToGrid',  label: 'Bat→Grid',  headerBg: 'bg-orange-100 dark:bg-orange-900/30', cellBg: 'bg-orange-50 dark:bg-orange-900/20', activeColor: 'text-green-600 dark:text-green-400' },
] as const;

export const EnergyFlowTable: React.FC<EnergyFlowTableProps> = ({ resolution }) => {
  const { data: dashboardData, loading, error } = useDashboardData(undefined, resolution);
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());

  const toggleRow = (period: number) => {
    setExpandedRows(prev => {
      const next = new Set(prev);
      if (next.has(period)) next.delete(period); else next.add(period);
      return next;
    });
  };

  const getNumericValue = (field: any): number => {
    if (typeof field === 'object' && field?.value !== undefined) return field.value;
    return field || 0;
  };
  const getDisplayValue = (field: any): string => {
    if (typeof field === 'object' && field?.display !== undefined) return field.display;
    if (typeof field === 'number') return field.toFixed(2);
    return field || 'N/A';
  };
  const getUnit = (field: any): string => {
    if (typeof field === 'object' && field?.unit !== undefined) {
      return field.unit === 'Wh' ? 'kWh' : field.unit;
    }
    return '???';
  };

  if (loading) {
    return (
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
        <div className="flex items-center justify-center h-32">
          <div className="animate-spin h-8 w-8 border-2 border-blue-500 rounded-full border-t-transparent"></div>
          <span className="ml-2 text-gray-900 dark:text-white">Loading energy flows...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md p-4">
          <h3 className="text-red-800 dark:text-red-200 font-medium">Error Loading Data</h3>
          <p className="text-red-600 dark:text-red-300 mt-1">{error}</p>
          <button onClick={() => window.location.reload()} className="mt-2 px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700">
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!dashboardData?.hourlyData) {
    return (
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
        <div className="text-center text-gray-500 dark:text-gray-400">No data available</div>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow overflow-x-auto">
      <div className="mb-4">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-1">Hourly Energy Flows</h2>
        <p className="text-sm text-gray-600 dark:text-gray-300">
          Click any row to expand the full energy flow breakdown for that hour.
        </p>
      </div>

      <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
        <thead className="bg-gray-50 dark:bg-gray-700">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600">Hour</th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600">Price</th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600">Solar</th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600">Consumption</th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600">Battery Action</th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600">Battery Level</th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600">Grid Import</th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600">Grid Export</th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600">Actual Cost</th>
            <th className="px-3 py-2 text-center text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider border border-gray-300 dark:border-gray-600">Savings</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
          {dashboardData.hourlyData.map((hour: any, index: number) => {
            const isCurrentPeriod = hour.period === dashboardData.currentPeriod;
            const isActual = hour.dataSource === 'actual';
            const isExpanded = expandedRows.has(hour.period);

            let rowClass = 'cursor-pointer ';
            let firstCellClass = 'px-3 py-2 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-white border-t border-r border-b border-gray-300 dark:border-gray-600 ';

            if (isCurrentPeriod) {
              rowClass += 'bg-purple-50 dark:bg-purple-900/20 hover:bg-purple-100 dark:hover:bg-purple-900/30';
              firstCellClass += 'border-l-4 border-l-purple-400';
            } else if (isActual) {
              rowClass += 'bg-gray-50 dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600';
              firstCellClass += 'border-l-4 border-l-green-400';
            } else {
              rowClass += 'bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700';
              firstCellClass += 'border-l border-l-gray-300 dark:border-l-gray-600';
            }

            return (
              <React.Fragment key={index}>
                <tr className={rowClass} onClick={() => toggleRow(hour.period)}>
                  <td className={firstCellClass}>
                    <div className="flex items-center gap-1">
                      {isExpanded
                        ? <ChevronDown className="h-3 w-3 text-gray-400 flex-shrink-0" />
                        : <ChevronRight className="h-3 w-3 text-gray-400 flex-shrink-0" />}
                      <div>
                        <div>{periodToTimeString(hour.period, resolution)}</div>
                        <div className="text-xs text-gray-400 dark:text-gray-500">{periodToEndTime(hour.period, resolution)}</div>
                      </div>
                      {isCurrentPeriod && (
                        <span className="ml-1 text-xs bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 px-1 py-0.5 rounded">Now</span>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                    <div className="font-medium">{getDisplayValue(hour.buyPrice)}</div>
                    <div className="text-xs text-gray-500 dark:text-gray-400">{getUnit(hour.buyPrice)}</div>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                    <div className={`font-medium ${getNumericValue(hour.solarProduction) > 0 ? 'text-yellow-600 dark:text-yellow-400' : 'text-gray-400 dark:text-gray-500'}`}>
                      {getDisplayValue(hour.solarProduction)}
                    </div>
                    <div className="text-xs text-gray-500 dark:text-gray-400">{getUnit(hour.solarProduction)}</div>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                    <div className="font-medium">{getDisplayValue(hour.homeConsumption)}</div>
                    <div className="text-xs text-gray-500 dark:text-gray-400">{getUnit(hour.homeConsumption)}</div>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                    <div className="flex flex-col items-center space-y-1">
                      {getNumericValue(hour.batteryCharged) > 0.01 && (
                        <span className="text-sm font-medium text-blue-600 dark:text-blue-400 bg-blue-100 dark:bg-blue-900/30 px-2 py-1 rounded flex items-center">
                          <Zap className="h-3 w-3 mr-1" />+{getDisplayValue(hour.batteryCharged)}
                        </span>
                      )}
                      {getNumericValue(hour.batteryDischarged) > 0.01 && (
                        <span className="text-sm font-medium text-orange-600 dark:text-orange-400 bg-orange-100 dark:bg-orange-900/30 px-2 py-1 rounded flex items-center">
                          <Zap className="h-3 w-3 mr-1" />-{getDisplayValue(hour.batteryDischarged)}
                        </span>
                      )}
                      {getNumericValue(hour.batteryCharged) <= 0.01 && getNumericValue(hour.batteryDischarged) <= 0.01 && (
                        <span className="text-sm text-gray-500 dark:text-gray-400">—</span>
                      )}
                    </div>
                    <div className="text-xs text-gray-500 dark:text-gray-400">kWh</div>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                    <div className="font-medium">{getDisplayValue(hour.batterySocEnd)}</div>
                    <div className="text-xs text-gray-500 dark:text-gray-400">{getDisplayValue(hour.batterySoeEnd) || 'N/A'}</div>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                    <div className={`font-medium ${getNumericValue(hour.gridImported) > 0 ? 'text-red-600 dark:text-red-400' : 'text-gray-400 dark:text-gray-500'}`}>
                      {getDisplayValue(hour.gridImported)}
                    </div>
                    <div className="text-xs text-gray-500 dark:text-gray-400">{getUnit(hour.gridImported)}</div>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                    <div className="flex flex-col items-center">
                      <div className={`font-medium ${getNumericValue(hour.gridExported) > 0 ? 'text-green-600 dark:text-green-400' : 'text-gray-400 dark:text-gray-500'}`}>
                        {getDisplayValue(hour.gridExported)}
                      </div>
                      <div className="text-xs text-gray-500 dark:text-gray-400">{getUnit(hour.gridExported)}</div>
                      {(hour.batteryToGrid?.value ?? 0) > 0.05 && (
                        <span className="mt-1 text-xs font-medium bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 px-1.5 py-0.5 rounded flex items-center gap-0.5">
                          <Battery className="h-3 w-3" />{hour.batteryToGrid?.display}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-white border border-gray-300 dark:border-gray-600 text-center">
                    <div className={`font-medium ${Math.abs(getNumericValue(hour.hourlyCost)) < 0.01 ? 'text-gray-900 dark:text-white' : getNumericValue(hour.hourlyCost) > 0 ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'}`}>
                      {getDisplayValue(hour.hourlyCost)}
                    </div>
                    <div className="text-xs text-gray-500 dark:text-gray-400">{getUnit(hour.hourlyCost)}</div>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-sm border border-gray-300 dark:border-gray-600 text-center">
                    <div className={`font-medium ${Math.abs(getNumericValue(hour.hourlySavings)) < 0.01 ? 'text-gray-900 dark:text-white' : getNumericValue(hour.hourlySavings) > 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                      {getDisplayValue(hour.hourlySavings)}
                    </div>
                    <div className="text-xs text-gray-500 dark:text-gray-400">{getUnit(hour.hourlySavings)}</div>
                  </td>
                </tr>

                {isExpanded && (
                  <tr>
                    <td colSpan={10} className="px-4 py-3 bg-indigo-50 dark:bg-indigo-900/10 border-b border-l border-r border-gray-300 dark:border-gray-600">
                      <div className="grid grid-cols-7 gap-2 text-xs">
                        {FLOWS.map(({ key, label, cellBg, activeColor }) => {
                          const value = (hour as any)[key];
                          const isActive = (value?.value ?? 0) > 0.05;
                          return (
                            <div key={key} className={`text-center p-2 rounded ${cellBg}`}>
                              <div className="text-gray-500 dark:text-gray-400 mb-1 font-medium">{label}</div>
                              <div className={`font-semibold ${isActive ? activeColor : 'text-gray-400 dark:text-gray-500'}`}>
                                {value?.display || '0.0'}
                              </div>
                              <div className="text-gray-400 dark:text-gray-500">kWh</div>
                            </div>
                          );
                        })}
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
