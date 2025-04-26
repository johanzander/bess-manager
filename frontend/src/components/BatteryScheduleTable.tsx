import React from 'react';
import { HourlyData, ScheduleSummary, BatterySettings } from '../types';

interface BatteryScheduleTableProps {
  hourlyData: HourlyData[];
  settings: BatterySettings;
  summary: ScheduleSummary;
}

export const BatteryScheduleTable: React.FC<BatteryScheduleTableProps> = ({
  hourlyData,
  summary,
}) => {
  return (
    <div className="bg-white p-6 rounded-lg shadow overflow-x-auto">
      <h2 className="text-xl font-semibold mb-4">Energy Optimization Schedule</h2>
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th rowSpan={2} className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border">
              Hour
            </th>
            <th colSpan={3} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase tracking-wider border bg-red-50">
              Grid-Only Case
            </th>
            <th colSpan={4} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase tracking-wider border bg-yellow-50">
              Solar-Only Case
            </th>
            <th colSpan={5} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase tracking-wider border bg-green-50">
              Solar + Battery Case
            </th>
          </tr>
          <tr className="bg-gray-50">
            {/* Grid-Only Case Headers */}
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border bg-red-50">
              Price (SEK/kWh)
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border bg-red-50">
              Cons. (kWh)
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border bg-red-50">
              Cost (SEK)
            </th>
            
            {/* Solar-Only Case Headers */}
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border bg-yellow-50">
              Solar (kWh)
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border bg-yellow-50">
              Grid (kWh)
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border bg-yellow-50">
              Cost (SEK)
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border bg-yellow-50">
              Savings (SEK)
            </th>
            
            {/* Solar + Battery Case Headers */}
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border bg-green-50">
              Batt Level (kWh)
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border bg-green-50">
              Batt Action (kWh)
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border bg-green-50">
              Grid (kWh)
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border bg-green-50">
              Cost (SEK)
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border bg-green-50">
              Extra Savings (SEK)
            </th>
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {hourlyData.map((hour, index) => {
            // Solar-only metrics - if not directly in data, calculate them
            const solarProduction = hour.solarProduction || hour.solarCharged || 0;
            
            const directSolarUsed = hour.directSolarUsed || 
              Math.min(hour.consumption, solarProduction);
              
            const solarOnlyGridNeeded = hour.solarOnlyGridNeeded || 
              Math.max(0, hour.consumption - directSolarUsed);
              
            const solarOnlyCost = hour.solarOnlyCost ?? 
              (hour.price * solarOnlyGridNeeded);
              
            const solarOnlySavings = hour.solarOnlySavings || 
              (hour.baseCost - solarOnlyCost);
            
            // Battery metrics
            const gridUsed = hour.gridUsed || 
              Math.max(0, hour.consumption - Math.max(0, -hour.action));
              
            // Calculate the additional savings from battery
            const batterySavings = hour.savings - solarOnlySavings;
            
            return (
              <tr key={index} className={index % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                  {hour.hour}
                </td>
                
                {/* Grid-Only Case Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                  {hour.price.toFixed(2)}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                  {hour.consumption.toFixed(1)}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                  {hour.baseCost.toFixed(2)}
                </td>
                
                {/* Solar-Only Case Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                  {solarProduction.toFixed(1)}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                  {solarOnlyGridNeeded.toFixed(1)}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                  {solarOnlyCost.toFixed(2)}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                  {solarOnlySavings.toFixed(2)}
                </td>
                
                {/* Solar + Battery Case Data */}
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                  {hour.batteryLevel.toFixed(1)}
                </td>
                <td className="px-3 py-2 whitespace-nowrap border">
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
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                  {gridUsed.toFixed(1)}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                  {hour.totalCost.toFixed(2)}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                  {batterySavings.toFixed(2)}
                </td>
              </tr>
            );
          })}
          
          {/* Totals Row */}
          <tr className="bg-gray-100 font-semibold">
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
              TOTAL
            </td>
            {/* Grid-Only Case Totals - No Average Price */}
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
              {/* No average price displayed here */}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
              {hourlyData.reduce((sum, h) => sum + h.consumption, 0).toFixed(1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
              {summary.baseCost.toFixed(2)}
            </td>
            
            {/* Solar-Only Case Totals */}
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
              {/* Total Solar Production */}
              {(summary.totalSolarProduction || 
                hourlyData.reduce((sum, h) => sum + (h.solarProduction || h.solarCharged || 0), 0)).toFixed(1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
              {hourlyData.reduce((sum, h) => {
                const solarProd = h.solarProduction || h.solarCharged || 0;
                const directSolar = Math.min(h.consumption, solarProd);
                return sum + (h.solarOnlyGridNeeded || Math.max(0, h.consumption - directSolar));
              }, 0).toFixed(1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
              {(summary.solarOnlyCost || 0).toFixed(2)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
              {(summary.solarOnlySavings || 0).toFixed(2)}
            </td>
            
            {/* Solar + Battery Case Totals */}
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
              {/* Battery level is not averaged/summed */}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
              C: {(summary.totalBatteryCharge || 
                 hourlyData.reduce((sum, h) => sum + (h.action > 0 ? h.action : 0), 0)).toFixed(1)}
              <br />
              D: {(summary.totalBatteryDischarge || 
                 Math.abs(hourlyData.reduce((sum, h) => sum + (h.action < 0 ? h.action : 0), 0))).toFixed(1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
              {hourlyData.reduce((sum, h) => {
                return sum + (h.gridUsed || Math.max(0, h.consumption - Math.max(0, -h.action)));
              }, 0).toFixed(1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
              {summary.optimizedCost.toFixed(2)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
              {(summary.batterySavings || 0).toFixed(2)}
            </td>
          </tr>
          
          {/* Final Summary Row */}
          <tr className="bg-blue-50 font-semibold">
            <td colSpan={3} className="px-3 py-2 text-sm text-right border">
              Total Energy Cost:
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm border">
              {summary.baseCost.toFixed(2)} SEK
            </td>
            <td colSpan={3} className="px-3 py-2 text-sm text-right border">
              Solar-Only Savings:
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm border">
              {(summary.solarOnlySavings || 0).toFixed(2)} SEK
              <br />
              ({((summary.solarOnlySavings || 0) / summary.baseCost * 100).toFixed(1)}%)
            </td>
            <td colSpan={3} className="px-3 py-2 text-sm text-right border">
              Battery Savings:
            </td>
            <td colSpan={2} className="px-3 py-2 whitespace-nowrap text-sm border">
              {(summary.batterySavings || 0).toFixed(2)} SEK 
              <br />
              ({((summary.batterySavings || 0) / summary.baseCost * 100).toFixed(1)}%)
            </td>
          </tr>
          <tr className="bg-green-100 font-bold">
            <td colSpan={8} className="px-3 py-2 text-right text-sm border">
              Total Combined Savings (Solar + Battery):
            </td>
            <td colSpan={5} className="px-3 py-2 text-sm border">
              {summary.savings.toFixed(2)} SEK ({(summary.savings / summary.baseCost * 100).toFixed(1)}%)
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
};