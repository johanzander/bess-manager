import React from 'react';
import { ScheduleSummary, HourlyData } from '../types';

interface SummaryCardsProps {
  summary: ScheduleSummary;
  hourlyData: HourlyData[];
}

export const SummaryCards: React.FC<SummaryCardsProps> = ({ summary, hourlyData }) => {
  // Calculate percentages for visual representation
  const solarSavingsPercent = ((summary.solarOnlySavings || 0) / summary.baseCost) * 100;
  const batterySavingsPercent = ((summary.batterySavings || 0) / summary.baseCost) * 100;
  const totalSavingsPercent = (summary.savings / summary.baseCost) * 100;
  
  // Calculate solar production if not provided
  const totalSolarProduction = summary.totalSolarProduction || 
    hourlyData.reduce((sum, h) => sum + (h.solarProduction || 0), 0);
  
  // Calculate battery activity if not provided
  const totalBatteryCharge = summary.totalBatteryCharge || 
    hourlyData.reduce((sum, h) => sum + (h.action > 0 ? h.action : 0), 0);
  
  const totalBatteryDischarge = summary.totalBatteryDischarge || 
    hourlyData.reduce((sum, h) => sum + (h.action < 0 ? Math.abs(h.action) : 0), 0);
  
  return (
    <div>
      {/* Cost Savings Overview */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
        <div className="bg-white p-6 rounded-lg shadow">
          <h3 className="text-lg font-medium text-gray-900 mb-2">Grid-Only Cost</h3>
          <p className="text-3xl font-bold text-gray-600">{summary.baseCost.toFixed(2)} SEK</p>
          <p className="text-sm text-gray-500 mt-2">Without solar or battery</p>
        </div>
    
        <div className="bg-white p-6 rounded-lg shadow relative overflow-hidden">
          <div className="relative z-10">
            <h3 className="text-lg font-medium text-gray-900 mb-2">Solar-Only Cost</h3>
            <p className="text-3xl font-bold text-yellow-600">
              {(summary.solarOnlyCost || (summary.baseCost - (summary.solarOnlySavings || 0))).toFixed(2)} SEK
            </p>
            <p className="text-sm text-gray-500 mt-2">
              Saves {solarSavingsPercent.toFixed(1)}% with solar generation
            </p>
          </div>
          {/* Visual indicator of savings */}
          <div 
            className="absolute bottom-0 left-0 h-1 bg-yellow-400"
            style={{ width: `${solarSavingsPercent}%` }}
          ></div>
        </div>
    
        <div className="bg-white p-6 rounded-lg shadow relative overflow-hidden">
          <div className="relative z-10">
            <h3 className="text-lg font-medium text-gray-900 mb-2">Optimized Cost</h3>
            <p className="text-3xl font-bold text-green-600">{summary.optimizedCost.toFixed(2)} SEK</p>
            <p className="text-sm text-gray-500 mt-2">
              Additional {batterySavingsPercent.toFixed(1)}% saved with battery
            </p>
          </div>
          {/* Visual indicator of total savings */}
          <div 
            className="absolute bottom-0 left-0 h-1 bg-green-500"
            style={{ width: `${totalSavingsPercent}%` }}
          ></div>
        </div>
      </div>
      
      {/* Savings Breakdown */}
      <div className="bg-white p-6 rounded-lg shadow mb-6">
        <h3 className="text-lg font-medium text-gray-900 mb-4">Savings Breakdown</h3>
        <div className="flex flex-col md:flex-row items-center justify-between">
          <div className="mb-4 md:mb-0">
            <div className="flex items-center mb-2">
              <div className="w-4 h-4 bg-yellow-400 rounded-full mr-2"></div>
              <span className="text-sm text-gray-700">Solar Savings</span>
            </div>
            <p className="text-2xl font-bold text-yellow-600">{(summary.solarOnlySavings || 0).toFixed(2)} SEK</p>
          </div>
          
          <div className="h-8 w-1 bg-gray-200 hidden md:block"></div>
          
          <div className="mb-4 md:mb-0">
            <div className="flex items-center mb-2">
              <div className="w-4 h-4 bg-blue-400 rounded-full mr-2"></div>
              <span className="text-sm text-gray-700">Battery Savings</span>
            </div>
            <p className="text-2xl font-bold text-blue-600">{(summary.batterySavings || 0).toFixed(2)} SEK</p>
          </div>
          
          <div className="h-8 w-1 bg-gray-200 hidden md:block"></div>
          
          <div>
            <div className="flex items-center mb-2">
              <div className="w-4 h-4 bg-green-500 rounded-full mr-2"></div>
              <span className="text-sm text-gray-700">Total Savings</span>
            </div>
            <p className="text-2xl font-bold text-green-600">{summary.savings.toFixed(2)} SEK</p>
            <p className="text-sm text-gray-500">{totalSavingsPercent.toFixed(1)}% of grid-only cost</p>
          </div>
        </div>
      </div>
      
      {/* Energy Flows */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-white p-6 rounded-lg shadow">
          <h3 className="text-lg font-medium text-gray-900 mb-2">Solar Production</h3>
          <p className="text-3xl font-bold text-yellow-600">{totalSolarProduction.toFixed(1)} kWh</p>
          <p className="text-sm text-gray-500 mt-2">Energy generated from solar</p>
        </div>
    
        <div className="bg-white p-6 rounded-lg shadow">
          <h3 className="text-lg font-medium text-gray-900 mb-2">Battery Activity</h3>
          <div className="flex justify-between items-center">
            <div>
              <p className="text-sm text-gray-600">Charged</p>
              <p className="text-xl font-bold text-green-600">+{totalBatteryCharge.toFixed(1)} kWh</p>
            </div>
            <div className="text-2xl text-gray-300">|</div>
            <div>
              <p className="text-sm text-gray-600">Discharged</p>
              <p className="text-xl font-bold text-red-600">-{totalBatteryDischarge.toFixed(1)} kWh</p>
            </div>
          </div>
          <p className="text-sm text-gray-500 mt-2">
            Estimated cycles: {(summary.cycleCount || (totalBatteryCharge + totalBatteryDischarge) / 30).toFixed(1)}
          </p>
        </div>
    
        <div className="bg-white p-6 rounded-lg shadow">
          <h3 className="text-lg font-medium text-gray-900 mb-2">Operation Costs</h3>
          <div className="flex justify-between items-center">
            <div>
              <p className="text-sm text-gray-600">Grid</p>
              <p className="text-xl font-bold text-blue-600">{summary.gridCosts.toFixed(2)} SEK</p>
            </div>
            <div className="text-2xl text-gray-300">+</div>
            <div>
              <p className="text-sm text-gray-600">Battery Wear</p>
              <p className="text-xl font-bold text-purple-600">{summary.batteryCosts.toFixed(2)} SEK</p>
            </div>
          </div>
          <p className="text-sm text-gray-500 mt-2">Total: {summary.optimizedCost.toFixed(2)} SEK</p>
        </div>
      </div>
    </div>
  );
};