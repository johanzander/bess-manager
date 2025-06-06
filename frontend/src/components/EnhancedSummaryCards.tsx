import React from 'react';
import { ScheduleSummary, HourlyData } from '../types';

interface EnhancedSummaryCardsProps {
  summary: ScheduleSummary;
  hourlyData: HourlyData[];
}

export const EnhancedSummaryCards: React.FC<EnhancedSummaryCardsProps> = ({ summary, hourlyData }) => {
  // Ensure summary properties exist with safe defaults
  const baseCost = summary?.baseCost || 0;
  const savings = summary?.savings || 0;
  const solarOnlySavings = summary?.solarOnlySavings || 0;
  const batterySavings = summary?.batterySavings || 0;
  
  // Calculate percentages for visual representation
  const solarSavingsPercent = baseCost > 0 ? (solarOnlySavings / baseCost) * 100 : 0;
  const batterySavingsPercent = baseCost > 0 ? (batterySavings / baseCost) * 100 : 0;
  const totalSavingsPercent = baseCost > 0 ? (savings / baseCost) * 100 : 0;
  
  // Calculate solar production from hourly data if not provided in summary
  const totalSolarProduction = summary.totalSolarProduction || 
    hourlyData.reduce((sum, h) => sum + (h.solarProduction || 0), 0);
  
  // Calculate grid import/export from hourly data if not provided in summary
  const totalGridImport = summary.totalGridImport || 
    hourlyData.reduce((sum, h) => sum + (h.gridImport || 0), 0);
    
  const totalGridExport = summary.totalGridExport || 
    hourlyData.reduce((sum, h) => sum + (h.gridExport || 0), 0);
  
  // Calculate battery activity from hourly data if not provided in summary
  const totalBatteryCharge = summary.totalBatteryCharge || 
    hourlyData.reduce((sum, h) => {
      // Try batteryCharge field first, then fall back to action if positive
      const charge = h.batteryCharge || (h.action > 0 ? h.action : 0);
      return sum + charge;
    }, 0);
  
  const totalBatteryDischarge = summary.totalBatteryDischarge || 
    hourlyData.reduce((sum, h) => {
      // Try batteryDischarge field first, then fall back to action if negative
      const discharge = h.batteryDischarge || (h.action < 0 ? Math.abs(h.action) : 0);
      return sum + discharge;
    }, 0);
  
  // Calculate total consumption
  const totalConsumption = hourlyData.reduce((sum, h) => sum + (h.consumption || 0), 0);
  
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
      {/* Card 1: Cost Overview */}
      <div className="bg-white p-5 rounded-lg shadow">
        <h3 className="text-lg font-medium text-gray-900 mb-2">Cost Savings</h3>
        
        <div className="space-y-2">
          <div className="flex justify-between items-center">
            <span className="text-sm text-gray-500">Grid Only:</span>
            <span className="text-lg font-semibold text-gray-700">{baseCost.toFixed(2)} SEK</span>
          </div>
          
          <div className="flex justify-between items-center">
            <span className="text-sm text-gray-500">Optimized:</span>
            <span className="text-lg font-semibold text-green-600">{(summary?.optimizedCost || 0).toFixed(2)} SEK</span>
          </div>
          
          <div className="h-1 w-full bg-gray-200 rounded-full mt-2">
            <div 
              className="h-1 bg-green-500 rounded-full" 
              style={{ width: `${totalSavingsPercent}%` }}
            ></div>
          </div>
          
          <div className="flex justify-between items-center pt-1">
            <span className="flex items-center">
              <span className="w-3 h-3 bg-green-500 rounded-full mr-1"></span>
              <span className="text-sm font-medium">Total Savings</span>
            </span>
            <span className="text-sm font-semibold text-green-600">
              {savings.toFixed(2)} SEK ({totalSavingsPercent.toFixed(1)}%)
            </span>
          </div>
        </div>
      </div>
      
      {/* Card 2: Energy Flows - Simplified version with 4 key metrics */}
      <div className="bg-white p-5 rounded-lg shadow">
        <h3 className="text-lg font-medium text-gray-900 mb-2">Energy Flows</h3>
        
        <div className="grid grid-cols-2 gap-3">
          {/* Top row - Consumption and Production */}
          <div className="p-2 bg-gray-50 rounded">
            <div className="text-xs text-gray-500 mb-1">Consumption</div>
            <div className="text-lg font-medium">{totalConsumption.toFixed(1)} kWh</div>
          </div>
          
          <div className="p-2 bg-yellow-50 rounded">
            <div className="text-xs text-gray-500 mb-1">Solar Production</div>
            <div className="text-lg font-medium text-yellow-600">{totalSolarProduction.toFixed(1)} kWh</div>
          </div>
          
          {/* Bottom row - Grid and Battery */}
          <div className="p-2 bg-blue-50 rounded">
            <div className="text-xs text-gray-500 mb-1">Grid Import/Export</div>
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-blue-600">+{totalGridImport.toFixed(1)}</span>
              <span className="text-xs text-gray-400">|</span>
              <span className="text-sm font-medium text-green-600">-{totalGridExport.toFixed(1)}</span>
            </div>
          </div>
          
          <div className="p-2 bg-green-50 rounded">
            <div className="text-xs text-gray-500 mb-1">Battery Charge/Discharge</div>
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-green-600">+{totalBatteryCharge.toFixed(1)}</span>
              <span className="text-xs text-gray-400">|</span>
              <span className="text-sm font-medium text-red-600">-{totalBatteryDischarge.toFixed(1)}</span>
            </div>
          </div>
        </div>
        
        {/* Net energy balance */}
        <div className="mt-3 pt-2 border-t border-gray-100">
          <div className="flex justify-between items-center">
            <span className="text-sm text-gray-500">Net Battery:</span>
            <span className={`text-base font-medium ${(totalBatteryCharge - totalBatteryDischarge) >= 0 ? 'text-green-600' : 'text-red-600'}`}>
              {(totalBatteryCharge - totalBatteryDischarge).toFixed(1)} kWh
            </span>
          </div>
        </div>
      </div>
      
      {/* Card 3: Savings Breakdown */}
      <div className="bg-white p-5 rounded-lg shadow">
        <h3 className="text-lg font-medium text-gray-900 mb-2">Savings Breakdown</h3>
        
        <div className="space-y-3">
          <div className="flex items-center">
            <div className="w-3 h-3 bg-yellow-400 rounded-full mr-2"></div>
            <span className="text-sm text-gray-600">Solar Savings:</span>
            <span className="ml-auto text-base font-medium text-yellow-600">
              {solarOnlySavings.toFixed(2)} SEK ({solarSavingsPercent.toFixed(1)}%)
            </span>
          </div>
          
          <div className="flex items-center">
            <div className="w-3 h-3 bg-blue-400 rounded-full mr-2"></div>
            <span className="text-sm text-gray-600">Battery Savings:</span>
            <span className="ml-auto text-base font-medium text-blue-600">
              {batterySavings.toFixed(2)} SEK ({batterySavingsPercent.toFixed(1)}%)
            </span>
          </div>
          
          <div className="pt-2 pb-1">
            <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
              <div className="h-full bg-yellow-400 float-left" style={{ width: `${solarSavingsPercent}%` }}></div>
              <div className="h-full bg-blue-400 float-left" style={{ width: `${batterySavingsPercent}%` }}></div>
            </div>
          </div>
          
          <div className="flex items-center pt-1 border-t border-gray-100">
            <div className="w-3 h-3 bg-green-500 rounded-full mr-2"></div>
            <span className="text-sm font-medium text-gray-700">Total Savings:</span>
            <span className="ml-auto text-base font-semibold text-green-600">
              {savings.toFixed(2)} SEK
            </span>
          </div>
          
          <div className="text-xs text-gray-500 text-right pt-1">
            Estimated battery cycles: {(summary?.cycleCount || totalBatteryCharge / 30).toFixed(1)}
          </div>
        </div>
      </div>
    </div>
  );
};