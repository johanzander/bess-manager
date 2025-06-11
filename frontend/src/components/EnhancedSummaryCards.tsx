import React, { useEffect } from 'react';
import { TrendingUp, Battery, Zap, DollarSign } from 'lucide-react';

interface EnhancedSummaryCardsProps {
  dailyViewData: any; // Data from /api/v2/daily_view
  energyData: any;    // Data from /api/energy/balance
}

export const EnhancedSummaryCards: React.FC<EnhancedSummaryCardsProps> = ({ dailyViewData, energyData }) => {
  // Debug: Log the actual data structure
  useEffect(() => {
    console.log('EnhancedSummaryCards - DailyView data:', dailyViewData);
    console.log('EnhancedSummaryCards - Energy data:', energyData);
  }, [dailyViewData, energyData]);

  // Get financial data from dailyView (same as working savings page)
  const totalDailySavings = dailyViewData?.total_daily_savings || dailyViewData?.totalDailySavings || 0;
  const actualSavingsSoFar = dailyViewData?.actual_savings_so_far || dailyViewData?.actualSavingsSoFar || 0;
  const predictedRemainingSavings = dailyViewData?.predicted_remaining_savings || dailyViewData?.predictedRemainingSavings || 0;
  
  // Get energy data from energyData.totals (same as working savings page)
  const totals = energyData?.totals || {};
  const totalSolarProduction = totals.total_solar || 0;
  const totalConsumption = totals.total_consumption || 0;
  const totalGridImport = totals.total_grid_import || 0;
  const totalGridExport = totals.total_grid_export || 0;
  const totalBatteryCharge = totals.total_battery_charged || totals.total_battery_charge || 0;
  const totalBatteryDischarge = totals.total_battery_discharged || totals.total_battery_discharge || 0;
  const hoursRecorded = totals.hours_recorded || 0;

  // Calculate cycle count (using 30kWh as default)
  const batteryCapacity = 30;
  const cycleCount = totalBatteryCharge / batteryCapacity;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      {/* Card 1: Financial Summary */}
      <div className="bg-white p-5 rounded-lg shadow">
        <h3 className="text-lg font-medium text-gray-900 mb-2 flex items-center">
          <DollarSign className="h-5 w-5 mr-2 text-green-500" />
          Financial Summary
        </h3>
        
        <div className="space-y-3">
          <div className="flex justify-between items-center">
            <span className="text-sm text-gray-600">Total Savings:</span>
            <span className="text-xl font-bold text-green-600">
              {totalDailySavings.toFixed(2)} SEK
            </span>
          </div>
          
          <div className="flex justify-between items-center">
            <span className="text-sm text-gray-600">Actual So Far:</span>
            <span className="text-base font-medium text-green-700">
              {actualSavingsSoFar.toFixed(2)} SEK
            </span>
          </div>
          
          <div className="flex justify-between items-center">
            <span className="text-sm text-gray-600">Predicted Remaining:</span>
            <span className="text-base font-medium text-blue-600">
              {predictedRemainingSavings.toFixed(2)} SEK
            </span>
          </div>
          
          <div className="text-xs text-gray-500 pt-2 border-t border-gray-100">
            Daily optimization vs base grid cost
          </div>
        </div>
      </div>
      
      {/* Card 2: Energy Balance */}
      <div className="bg-white p-5 rounded-lg shadow">
        <h3 className="text-lg font-medium text-gray-900 mb-2 flex items-center">
          <Zap className="h-5 w-5 mr-2 text-yellow-500" />
          Energy Balance
        </h3>
        
        <div className="space-y-3">
          <div className="flex justify-between items-center">
            <span className="text-sm text-gray-600">Solar Production:</span>
            <span className="text-base font-medium text-yellow-600">
              {totalSolarProduction.toFixed(1)} kWh
            </span>
          </div>
          
          <div className="flex justify-between items-center">
            <span className="text-sm text-gray-600">Home Consumption:</span>
            <span className="text-base font-medium text-blue-600">
              {totalConsumption.toFixed(1)} kWh
            </span>
          </div>
          
          <div className="flex justify-between items-center">
            <span className="text-sm text-gray-600">Grid Balance:</span>
            <span className={`text-base font-medium ${
              (totalGridImport - totalGridExport) > 0 ? 'text-red-600' : 'text-green-600'
            }`}>
              {(totalGridImport - totalGridExport).toFixed(1)} kWh
            </span>
          </div>
          
          <div className="text-xs text-gray-500 pt-2 border-t border-gray-100">
            Average: {hoursRecorded > 0 ? (totalConsumption / hoursRecorded).toFixed(1) : 0} kWh/h over {hoursRecorded} hours<br/>
            Net grid: {totalGridImport.toFixed(1)} in, {totalGridExport.toFixed(1)} out
          </div>
        </div>
      </div>
      
      {/* Card 3: Battery Performance */}
      <div className="bg-white p-5 rounded-lg shadow">
        <h3 className="text-lg font-medium text-gray-900 mb-2 flex items-center">
          <Battery className="h-5 w-5 mr-2 text-green-500" />
          Battery Performance
        </h3>
        
        <div className="space-y-3">
          <div className="flex justify-between items-center">
            <span className="text-sm text-gray-600">Total Charged:</span>
            <span className="text-base font-medium text-green-600">
              {totalBatteryCharge.toFixed(1)} kWh
            </span>
          </div>
          
          <div className="flex justify-between items-center">
            <span className="text-sm text-gray-600">Total Discharged:</span>
            <span className="text-base font-medium text-purple-600">
              {totalBatteryDischarge.toFixed(1)} kWh
            </span>
          </div>
          
          <div className="flex justify-between items-center">
            <span className="text-sm text-gray-600">Daily Cycles:</span>
            <span className="text-base font-medium text-blue-600">
              {cycleCount.toFixed(2)}
            </span>
          </div>
          
          <div className="text-xs text-gray-500 pt-2 border-t border-gray-100">
            Based on {hoursRecorded} hours of recorded data
          </div>
        </div>
      </div>
      
      {/* Card 4: Grid Performance */}
      <div className="bg-white p-5 rounded-lg shadow">
        <h3 className="text-lg font-medium text-gray-900 mb-2 flex items-center">
          <Zap className="h-5 w-5 mr-2 text-blue-500" />
          Grid Performance
        </h3>
        
        <div className="space-y-3">
          <div className="flex justify-between items-center">
            <span className="text-sm text-gray-600">Net Grid:</span>
            <span className={`text-base font-medium ${
              (totalGridImport - totalGridExport) > 0 ? 'text-red-600' : 'text-green-600'
            }`}>
              {Math.abs(totalGridImport - totalGridExport).toFixed(1)} kWh
            </span>
          </div>
          
          <div className="flex justify-between items-center">
            <span className="text-sm text-gray-600">Solar Self-Use:</span>
            <span className="text-base font-medium text-yellow-600">
              {totalSolarProduction > 0 ? (((totalSolarProduction - totalGridExport) / totalSolarProduction) * 100).toFixed(0) : 0}%
            </span>
          </div>
          
          <div className="flex justify-between items-center">
            <span className="text-sm text-gray-600">Energy Independence:</span>
            <span className="text-base font-medium text-green-600">
              {totalConsumption > 0 ? (100 - ((totalGridImport / totalConsumption) * 100)).toFixed(0) : 0}%
            </span>
          </div>
          
          <div className="text-xs text-gray-500 pt-2 border-t border-gray-100">
            {(totalGridImport - totalGridExport) > 0 ? 'Net consumer' : 'Net producer'}
          </div>
        </div>
      </div>
    </div>
  );
};