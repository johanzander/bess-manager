import React from 'react';
import { HourlyData, ScheduleSummary, BatterySettings } from '../types';

interface EnhancedSummary {
  gridOnlyCost: number;
  solarOnlyCost: number;
  batterySolarCost: number;
  solarSavings: number;
  batterySavings: number;
  totalSavings: number;
  solarProduction: number;
  directSolarUse: number;
  solarExcess: number;
  totalCharged: number;
  totalDischarged: number;
  estimatedBatteryCycles: number;
  totalConsumption?: number;
  totalImport?: number;
}

interface BatteryScheduleTableProps {
  hourlyData: HourlyData[];
  settings: BatterySettings;
  summary: ScheduleSummary;
  energyProfile?: {
    solar: number[];
    consumption: number[];
    battery_soc: number[];
    actualHours: number;
  };
  enhancedSummary?: EnhancedSummary;
}

export const BatteryScheduleTable: React.FC<BatteryScheduleTableProps> = ({
  hourlyData,
  settings,
  summary,
  energyProfile,
  enhancedSummary
}) => {
  return (
    <div className="bg-white p-6 rounded-lg shadow overflow-x-auto">
      <h2 className="text-xl font-semibold mb-4">Battery Schedule</h2>
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th rowSpan={2} className="px-3 py-2 text-left text-xs font-medium text-gray-800 uppercase tracking-wider border">
              Hour
            </th>
            <th colSpan={3} className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border bg-blue-100">
              Grid-Only Case
            </th>
            <th colSpan={5} className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border bg-yellow-100">
              Solar-Only Case
            </th>
            <th colSpan={5} className="px-3 py-2 text-center text-xs font-medium text-gray-800 uppercase tracking-wider border bg-green-100">
              Solar+Battery Case
            </th>
          </tr>
          <tr className="bg-gray-50">
            {/* Grid-Only Headers */}
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-800 uppercase tracking-wider border bg-blue-100">
              Price
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-800 uppercase tracking-wider border bg-blue-100">
              Cons.
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-800 uppercase tracking-wider border bg-blue-100">
              Cost
            </th>
            
            {/* Solar-Only Headers */}
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-800 uppercase tracking-wider border bg-yellow-100">
              Solar
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-800 uppercase tracking-wider border bg-yellow-100">
              Direct
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-800 uppercase tracking-wider border bg-yellow-100">
              Export
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-800 uppercase tracking-wider border bg-yellow-100">
              Import
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-800 uppercase tracking-wider border bg-yellow-100">
              Cost
            </th>
            
            {/* Solar+Battery Headers */}
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-800 uppercase tracking-wider border bg-green-100">
              SOE
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-800 uppercase tracking-wider border bg-green-100">
              Action
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-800 uppercase tracking-wider border bg-green-100">
              Grid
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-800 uppercase tracking-wider border bg-green-100">
              Cost
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-800 uppercase tracking-wider border bg-green-100">
              Savings
            </th>
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {hourlyData.map((hour, index) => {
            // Use the values directly from the API - prioritize API values over calculations
            const solarProduction = hour.solarProduction !== undefined 
              ? hour.solarProduction 
              : (energyProfile?.solar?.[index] || 0);
              
            const directSolar = hour.directSolar !== undefined
              ? hour.directSolar
              : Math.min(hour.consumption || settings.estimatedConsumption, solarProduction);
              
            const exportSolar = hour.exportSolar !== undefined
              ? hour.exportSolar
              : Math.max(0, solarProduction - directSolar);
              
            const importFromGrid = hour.importFromGrid !== undefined
              ? hour.importFromGrid
              : Math.max(0, (hour.consumption || settings.estimatedConsumption) - directSolar);
              
            const solarOnlyCost = hour.solarOnlyCost !== undefined
              ? hour.solarOnlyCost
              : hour.price * importFromGrid;
              
            const gridOnlyCost = hour.gridOnlyCost !== undefined
              ? hour.gridOnlyCost
              : hour.baseCost || (hour.price * (hour.consumption || settings.estimatedConsumption));
              
            const batterySavings = hour.batterySavings !== undefined
              ? hour.batterySavings
              : solarOnlyCost - hour.totalCost;
            
            return (
              <tr key={index} className={index % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                  {hour.hour}
                </td>
                
                {/* Grid-Only Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-blue-50">
                  {hour.price.toFixed(2)}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-blue-50">
                  {(hour.consumption || settings.estimatedConsumption).toFixed(1)}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-blue-50">
                  {gridOnlyCost.toFixed(2)}
                </td>
                
                {/* Solar-Only Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50">
                  {solarProduction.toFixed(1)}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50">
                  {directSolar.toFixed(1)}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50">
                  {exportSolar.toFixed(1)}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50">
                  {importFromGrid.toFixed(1)}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50">
                  {solarOnlyCost.toFixed(2)}
                </td>
                
                {/* Solar+Battery Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50">
                  {hour.batteryLevel.toFixed(1)}
                </td>
                <td className="px-3 py-2 whitespace-nowrap border bg-green-50">
                  <span className={`px-2 inline-flex text-sm leading-5 font-semibold rounded-full ${
                    hour.action > 0
                      ? 'bg-green-100 text-green-800'
                      : hour.action < 0
                      ? 'bg-red-100 text-red-800'
                      : 'bg-gray-100 text-gray-800'
                  }`}>
                    {hour.action.toFixed(1)}
                  </span>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50">
                  {/* Grid consumption for battery+solar case */}
                  {(hour.batteryGridConsumption !== undefined 
                    ? hour.batteryGridConsumption 
                    : Math.max(0, hour.action > 0 
                      ? importFromGrid + hour.action 
                      : importFromGrid + hour.action)).toFixed(1)}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50">
                  {hour.totalCost.toFixed(2)}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50">
                  {(gridOnlyCost - hour.totalCost).toFixed(2)}
                </td>
              </tr>
            );
          })}
          
          {/* Totals Row */}
          <tr className="bg-gray-100 font-semibold">
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
              TOTAL
            </td>
            
            {/* Grid-Only Totals */}
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-blue-50"></td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-blue-50">
              {enhancedSummary?.totalConsumption?.toFixed(1) || 
               hourlyData.reduce((sum, h) => sum + (h.consumption || settings.estimatedConsumption), 0).toFixed(1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-blue-50">
              {enhancedSummary?.gridOnlyCost.toFixed(2) || summary.baseCost.toFixed(2)}
            </td>
            
            {/* Solar-Only Totals */}
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50">
              {enhancedSummary?.solarProduction.toFixed(1) || 
               hourlyData.reduce((sum, h) => sum + (h.solarProduction || 0), 0).toFixed(1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50">
              {enhancedSummary?.directSolarUse.toFixed(1) || 
               hourlyData.reduce((sum, h) => sum + (h.directSolar || 0), 0).toFixed(1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50">
              {enhancedSummary?.solarExcess.toFixed(1) || 
               hourlyData.reduce((sum, h) => sum + (h.exportSolar || 0), 0).toFixed(1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50">
              {enhancedSummary?.totalImport?.toFixed(1) || 
               hourlyData.reduce((sum, h) => sum + (h.importFromGrid || 0), 0).toFixed(1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-yellow-50">
              {enhancedSummary?.solarOnlyCost.toFixed(2) || 
               hourlyData.reduce((sum, h) => sum + (h.solarOnlyCost || 0), 0).toFixed(2)}
            </td>
            
            {/* Solar+Battery Totals */}
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50"></td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50">
              C: {enhancedSummary?.totalCharged.toFixed(1) || 
                  hourlyData.reduce((sum, h) => sum + (h.action > 0 ? h.action : 0), 0).toFixed(1)}
              <br />
              D: {enhancedSummary?.totalDischarged.toFixed(1) || 
                  Math.abs(hourlyData.reduce((sum, h) => sum + (h.action < 0 ? h.action : 0), 0)).toFixed(1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50">
              {summary.gridCosts.toFixed(2)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50">
              {enhancedSummary?.batterySolarCost.toFixed(2) || summary.optimizedCost.toFixed(2)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border bg-green-50">
              {enhancedSummary?.totalSavings.toFixed(2) || summary.savings.toFixed(2)}
            </td>
          </tr>
        </tbody>
      </table>
      
      {/* Enhanced Summary Section */}
      {enhancedSummary && (
        <div className="mt-6 bg-gray-50 p-4 rounded-lg">
          <h3 className="text-lg font-semibold mb-2">Enhanced Savings Summary</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <p className="mb-1">Grid-Only Cost: <span className="font-semibold">{enhancedSummary.gridOnlyCost.toFixed(2)} SEK</span></p>
              <p className="mb-1">Solar-Only Cost: <span className="font-semibold">{enhancedSummary.solarOnlyCost.toFixed(2)} SEK</span></p>
              <p className="mb-1">Solar+Battery Cost: <span className="font-semibold">{enhancedSummary.batterySolarCost.toFixed(2)} SEK</span></p>
              <p className="mb-1">Solar Savings: <span className="font-semibold">{enhancedSummary.solarSavings.toFixed(2)} SEK ({(enhancedSummary.solarSavings / enhancedSummary.gridOnlyCost * 100).toFixed(1)}%)</span></p>
              <p className="mb-1">Additional Battery Savings: <span className="font-semibold">{enhancedSummary.batterySavings.toFixed(2)} SEK ({(enhancedSummary.batterySavings / enhancedSummary.gridOnlyCost * 100).toFixed(1)}%)</span></p>
              <p className="font-semibold mb-1">Total Combined Savings: <span className="text-green-600">{enhancedSummary.totalSavings.toFixed(2)} SEK ({(enhancedSummary.totalSavings / enhancedSummary.gridOnlyCost * 100).toFixed(1)}%)</span></p>
            </div>
            <div>
              <p className="mb-1">Total Solar Production: <span className="font-semibold">{enhancedSummary.solarProduction.toFixed(1)} kWh</span></p>
              <p className="mb-1">- Direct Solar Use: <span className="font-semibold">{enhancedSummary.directSolarUse.toFixed(1)} kWh</span></p>
              <p className="mb-1">- Excess Solar Sold: <span className="font-semibold">{enhancedSummary.solarExcess.toFixed(1)} kWh</span></p>
              <p className="mb-1">Total Energy Charged: <span className="font-semibold">{enhancedSummary.totalCharged.toFixed(1)} kWh</span></p>
              <p className="mb-1">Total Energy Discharged: <span className="font-semibold">{enhancedSummary.totalDischarged.toFixed(1)} kWh</span></p>
              <p className="mb-1">Estimated Battery Cycles: <span className="font-semibold">{enhancedSummary.estimatedBatteryCycles?.toFixed(1) || "0.0"}</span></p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};