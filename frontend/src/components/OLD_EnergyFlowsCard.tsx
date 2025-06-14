import React, { useMemo } from 'react';
import { BatteryIcon, Home, Grid3X3, Sun } from 'lucide-react';

interface EnergyFlowsCardProps {
  hourlyData: any[];
  settings?: any;
}

export const EnergyFlowsCard: React.FC<EnergyFlowsCardProps> = ({ hourlyData, settings }) => {
  const energyFlows = useMemo(() => {
    if (!hourlyData || hourlyData.length === 0) return null;

    const actualData = hourlyData.filter(h => h.data_source === 'actual' || h.isActual);
    const predictedData = hourlyData.filter(h => h.data_source === 'predicted' || h.isPredicted);
    
    const calculateTotals = (data: any[]) => ({
      solarGeneration: data.reduce((sum, h) => sum + (h.solar_generated || h.solar_production || 0), 0),
      homeConsumption: data.reduce((sum, h) => sum + (h.home_consumed || h.consumption || 0), 0),
      batteryCharged: data.reduce((sum, h) => sum + Math.max(0, h.battery_charged || 0), 0),
      batteryDischarged: data.reduce((sum, h) => sum + Math.max(0, h.battery_discharged || 0), 0),
      gridImport: data.reduce((sum, h) => sum + Math.max(0, h.grid_imported || 0), 0),
      gridExport: data.reduce((sum, h) => sum + Math.max(0, h.grid_exported || 0), 0),
    });

    const actual = calculateTotals(actualData);
    const predicted = calculateTotals(predictedData);
    const total = calculateTotals(hourlyData);

    return { actual, predicted, total };
  }, [hourlyData]);

  if (!energyFlows) {
    return (
      <div className="bg-white p-6 rounded-lg shadow">
        <h2 className="text-xl font-semibold mb-4">Energy Flows</h2>
        <div className="text-center text-gray-500">No data available</div>
      </div>
    );
  }

  const { actual, predicted, total } = energyFlows;

  return (
    <div className="bg-white p-6 rounded-lg shadow">
      <h2 className="text-xl font-semibold mb-4">Energy Flows</h2>
      
      {/* Four Energy Flow Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {/* Solar Generation Card */}
        <div className="bg-yellow-50 p-4 rounded-lg border border-yellow-200">
          <div className="flex items-center justify-between mb-2">
            <Sun className="h-5 w-5 text-yellow-600" />
            <span className="text-sm font-medium text-yellow-800">Solar Generation</span>
          </div>
          <div className="text-lg font-bold text-yellow-900">
            {total.solarGeneration.toFixed(1)} kWh
          </div>
          <div className="text-xs text-yellow-700 mt-1">
            Actual: {actual.solarGeneration.toFixed(1)} | Predicted: {predicted.solarGeneration.toFixed(1)}
          </div>
        </div>

        {/* Home Consumption Card */}
        <div className="bg-blue-50 p-4 rounded-lg border border-blue-200">
          <div className="flex items-center justify-between mb-2">
            <Home className="h-5 w-5 text-blue-600" />
            <span className="text-sm font-medium text-blue-800">Home Consumption</span>
          </div>
          <div className="text-lg font-bold text-blue-900">
            {total.homeConsumption.toFixed(1)} kWh
          </div>
          <div className="text-xs text-blue-700 mt-1">
            Actual: {actual.homeConsumption.toFixed(1)} | Predicted: {predicted.homeConsumption.toFixed(1)}
          </div>
        </div>

        {/* Battery Storage Card */}
        <div className="bg-green-50 p-4 rounded-lg border border-green-200">
          <div className="flex items-center justify-between mb-2">
            <BatteryIcon className="h-5 w-5 text-green-600" />
            <span className="text-sm font-medium text-green-800">Battery Storage</span>
          </div>
          <div className="text-lg font-bold text-green-900">
            {(total.batteryCharged - total.batteryDischarged).toFixed(1)} kWh
          </div>
          <div className="text-xs text-green-700 mt-1">
            Charged: {total.batteryCharged.toFixed(1)} | Discharged: {total.batteryDischarged.toFixed(1)}
          </div>
        </div>

        {/* Grid Card (Import + Export) */}
        <div className="bg-purple-50 p-4 rounded-lg border border-purple-200">
          <div className="flex items-center justify-between mb-2">
            <Grid3X3 className="h-5 w-5 text-purple-600" />
            <span className="text-sm font-medium text-purple-800">Grid</span>
          </div>
          <div className="text-lg font-bold text-purple-900">
            {(total.gridImport - total.gridExport).toFixed(1)} kWh
          </div>
          <div className="text-xs text-purple-700 mt-1">
            Import: {total.gridImport.toFixed(1)} | Export: {total.gridExport.toFixed(1)}
          </div>
        </div>
      </div>
    </div>
  );
};