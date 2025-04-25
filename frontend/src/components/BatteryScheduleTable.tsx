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
      <h2 className="text-xl font-semibold mb-4">Battery Schedule</h2>
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th rowSpan={2} className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border">
              Hour
            </th>
            <th colSpan={3} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase tracking-wider border bg-blue-50">
              Base Case
            </th>
            <th colSpan={6} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase tracking-wider border bg-green-50">
              Optimized Case
            </th>
          </tr>
          <tr className="bg-gray-50">
            {/* Base Case Headers */}
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border bg-blue-50">
              Price (SEK/kWh)
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border bg-blue-50">
              Cons. (kWh)
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border bg-blue-50">
              Cost (SEK)
            </th>
            {/* Optimized Case Headers */}
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border bg-green-50">
              SOE (kWh)
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border bg-green-50">
              Solar Charged (kWh)
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border bg-green-50">
              Charge (kWh)
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border bg-green-50">
              Import Cost (SEK)
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border bg-green-50">
              Battery Cost (SEK)
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border bg-green-50">
              Total Cost (SEK)
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border bg-green-50">
              Savings (SEK)
            </th>
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {hourlyData.map((hour, index) => (
            <tr key={index} className={index % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
              <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                {hour.hour}
              </td>
              {/* Base Case Data */}
              <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                {hour.price.toFixed(2)}
              </td>
              <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                {hour.consumption.toFixed(1)}
              </td>
              <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                {(hour.price * hour.consumption).toFixed(2)}
              </td>
              {/* Optimized Case Data */}
              <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                {hour.batteryLevel.toFixed(1)}
              </td>
              <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                <span className={`px-2 inline-flex text-sm leading-5 font-semibold rounded-full ${
                  hour.solarCharged > 0
                    ? 'bg-green-100 text-green-800'
                    : 'bg-gray-100 text-gray-800'
                }`}>
                  {hour.solarCharged.toFixed(1)}
                </span>
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
                {hour.gridCost.toFixed(2)}
              </td>
              <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                {hour.batteryCost.toFixed(2)}
              </td>
              <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                {hour.totalCost.toFixed(2)}
              </td>
              <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                {hour.savings.toFixed(2)}
              </td>
            </tr>
          ))}
          {/* Totals Row */}
          <tr className="bg-gray-100 font-semibold">
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
              TOTAL
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
              {hourlyData.reduce((sum, h) => sum + h.consumption, 0).toFixed(1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
              {summary.baseCost.toFixed(2)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
              {hourlyData.reduce((sum, h) => sum + h.solarCharged, 0).toFixed(1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
              C: {hourlyData.reduce((sum, h) => sum + (h.action > 0 ? h.action : 0), 0).toFixed(1)}
              <br />
              D: {Math.abs(hourlyData.reduce((sum, h) => sum + (h.action < 0 ? h.action : 0), 0)).toFixed(1)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                {summary.gridCosts.toFixed(2)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
                {summary.batteryCosts.toFixed(2)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
              {summary.optimizedCost.toFixed(2)}
            </td>
            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-900 border">
              {summary.savings.toFixed(2)}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
};