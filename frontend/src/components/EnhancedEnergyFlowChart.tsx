import React from 'react';
import { Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Line, ComposedChart, Cell } from 'recharts';

export const EnhancedEnergyFlowChart: React.FC<{
  dailyViewData: any[];
  energyBalanceData: any[];
  currentHour: number;
}> = ({ dailyViewData, energyBalanceData, currentHour }) => {
  // Combine and process data for visualization
  const chartData = Array.from({ length: 24 }, (_, hour) => {
    const dailyViewHour = dailyViewData?.find(h => h.hour === hour);
    const energyBalanceHour = energyBalanceData?.find(h => h.hour === hour);
    
    // Calculate isActual based on current hour and data source
    const isActual = hour < currentHour || (dailyViewHour?.data_source === 'actual');
    const isPredicted = hour >= currentHour || (dailyViewHour?.data_source === 'predicted');
    
    // Use actual data from energy balance for past hours, predicted from daily view for future
    let actualData = null;
    let predictedData = null;
    
    if (energyBalanceHour && isActual) {
      actualData = {
        solar: energyBalanceHour.system_production || 0,
        consumption: energyBalanceHour.load_consumption || 0,
        gridImport: energyBalanceHour.import_from_grid || 0,
        gridExport: energyBalanceHour.export_to_grid || 0,
        batteryCharge: energyBalanceHour.battery_charge || 0,
        batteryDischarge: energyBalanceHour.battery_discharge || 0,
      };
    }
    
    if (dailyViewHour) {
      const data = {
        solar: dailyViewHour.solar_generated || 0,
        consumption: dailyViewHour.home_consumed || 0,
        gridImport: dailyViewHour.grid_imported || 0,
        gridExport: dailyViewHour.grid_exported || 0,
        batteryCharge: dailyViewHour.battery_charged || 0,
        batteryDischarge: dailyViewHour.battery_discharged || 0,
      };
      
      if (isPredicted) {
        predictedData = data;
      } else if (!actualData) {
        // Use daily view as backup for actual data
        actualData = data;
      }
    }
    
    // Calculate prediction accuracy for past hours where we have both
    let accuracy = null;
    if (actualData && dailyViewHour && isActual) {
      const solarError = actualData.solar > 0 
        ? Math.abs(actualData.solar - (dailyViewHour.solar_generated || 0)) / actualData.solar * 100
        : 0;
      
      const consumptionError = actualData.consumption > 0
        ? Math.abs(actualData.consumption - (dailyViewHour.home_consumed || 0)) / actualData.consumption * 100
        : 0;
        
      accuracy = Math.max(0, 100 - (solarError + consumptionError) / 2);
    }
    
    return {
      hour,
      
      // Actual data (for past hours only)
      actualSolar: actualData?.solar || 0,
      actualConsumption: hour < currentHour ? (actualData?.consumption || 0) : null,
      actualGridImport: actualData?.gridImport || 0,
      actualBatteryDischarge: actualData?.batteryDischarge || 0,
      
      // Predicted data (for current and future hours, starting one hour early for overlap)
      predictedSolar: predictedData?.solar || 0,
      predictedConsumption: hour >= Math.max(0, currentHour - 1) ? (predictedData?.consumption || 0) : null,
      predictedGridImport: predictedData?.gridImport || 0,
      predictedBatteryDischarge: predictedData?.batteryDischarge || 0,
      
      // Meta information
      isActual,
      isPredicted,
      accuracy,
      price: dailyViewHour?.electricity_price || 0,
      
      // For display
      dataType: isActual ? 'Actual' : 'Predicted',
      accuracyColor: accuracy !== null 
        ? accuracy > 90 ? '#22c55e' 
          : accuracy > 70 ? '#eab308' 
          : '#ef4444'
        : '#6b7280'
    };
  });

  // Find the last actual consumption value to ensure line continuity
  const lastActualHour = currentHour > 0 ? currentHour - 1 : -1;
  const lastActualConsumption = lastActualHour >= 0 
    ? chartData.find(d => d.hour === lastActualHour)?.actualConsumption 
    : null;

  // Ensure predicted line starts from the last actual consumption value
  const continuousChartData = chartData.map((data) => {
    if (data.hour === lastActualHour && lastActualConsumption !== null) {
      // At the transition hour, set predicted consumption to match actual
      return {
        ...data,
        predictedConsumption: lastActualConsumption
      };
    }
    return data;
  });

  const maxValue = Math.max(
    ...continuousChartData.map(d => Math.max(
      d.actualConsumption,
      d.predictedConsumption,
      d.actualSolar + d.actualBatteryDischarge + d.actualGridImport,
      d.predictedSolar + d.predictedBatteryDischarge + d.predictedGridImport
    )),
    1 // Minimum value to avoid division by zero
  );

  // Custom tooltip to show comparison
  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0]?.payload;
      if (!data) return null;
      
      return (
        <div className="bg-white p-3 border border-gray-300 rounded-lg shadow-lg">
          <p className="font-medium text-gray-900">{`Hour: ${label}:00`}</p>
          <p className="text-sm text-gray-600 mb-2">{`Type: ${data.dataType}`}</p>
          
          {data.isActual ? (
            <div className="space-y-1">
              <p className="text-green-600">Solar: {data.actualSolar.toFixed(1)} kWh</p>
              <p className="text-blue-600">Grid: {data.actualGridImport.toFixed(1)} kWh</p>
              <p className="text-purple-600">Battery: {data.actualBatteryDischarge.toFixed(1)} kWh</p>
              <p className="text-gray-800">Consumption: {data.actualConsumption?.toFixed(1) || 0} kWh</p>
              {data.predictedConsumption !== null && data.predictedConsumption !== undefined && (
                <p className="text-gray-600">Consumption (pred): {data.predictedConsumption.toFixed(1)} kWh</p>
              )}
              {data.accuracy !== null && (
                <p className="text-sm font-medium" style={{ color: data.accuracyColor }}>
                  Prediction Accuracy: {data.accuracy.toFixed(1)}%
                </p>
              )}
            </div>
          ) : (
            <div className="space-y-1">
              <p className="text-green-600">Solar (pred): {data.predictedSolar.toFixed(1)} kWh</p>
              <p className="text-blue-600">Grid (pred): {data.predictedGridImport.toFixed(1)} kWh</p>
              <p className="text-purple-600">Battery (pred): {data.predictedBatteryDischarge.toFixed(1)} kWh</p>
              <p className="text-gray-800">Consumption (pred): {data.predictedConsumption?.toFixed(1) || 0} kWh</p>
            </div>
          )}
          
          <p className="text-sm text-gray-500 mt-2">Price: {data.price.toFixed(2)} SEK/kWh</p>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="bg-white p-6 rounded-lg shadow">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold">Energy Flow: Predictions vs Reality</h2>
        <div className="flex items-center space-x-4 text-sm">
          <div className="flex items-center">
            <div className="w-3 h-3 bg-gray-100 border-2 border-gray-400 rounded mr-2"></div>
            <span>Actual Data</span>
          </div>
          <div className="flex items-center">
            <div className="w-3 h-3 bg-gray-50 border-2 border-gray-300 rounded mr-2 opacity-70"></div>
            <span>Predicted Data</span>
          </div>
        </div>
      </div>
      
      <div className="h-96">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={continuousChartData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis 
              dataKey="hour"
              interval={2}
              tick={{ fontSize: 12 }}
            />
            <YAxis 
              domain={[0, Math.ceil(maxValue * 1.1)]}
              label={{ value: 'Energy (kWh)', angle: -90, position: 'insideLeft', dx: -10 }}
              tick={{ fontSize: 12 }}
            />
            <YAxis 
              yAxisId="price"
              orientation="right"
              domain={[0, 'auto']}
              label={{ value: 'Price (SEK/kWh)', angle: 90, position: 'insideRight', dx: 10 }}
              tick={{ fontSize: 12 }}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend />

            {/* ACTUAL DATA - Stacked bars (solid) */}
            <Bar 
              dataKey="actualSolar" 
              name="Solar (Actual)" 
              stackId="actual"
              fill="#22c55e"
              stroke="#16a34a"
              strokeWidth={1}
            >
              {continuousChartData.map((entry, index) => (
                <Cell key={`actual-solar-${index}`} 
                      fillOpacity={entry.isActual ? 0.9 : 0} />
              ))}
            </Bar>
            
            <Bar 
              dataKey="actualBatteryDischarge" 
              name="Battery (Actual)" 
              stackId="actual"
              fill="#8b5cf6"
              stroke="#7c3aed"
              strokeWidth={1}
            >
              {continuousChartData.map((entry, index) => (
                <Cell key={`actual-battery-${index}`} 
                      fillOpacity={entry.isActual ? 0.9 : 0} />
              ))}
            </Bar>
            
            <Bar 
              dataKey="actualGridImport" 
              name="Grid (Actual)" 
              stackId="actual"
              fill="#3b82f6"
              stroke="#2563eb"
              strokeWidth={1}
            >
              {continuousChartData.map((entry, index) => (
                <Cell key={`actual-grid-${index}`} 
                      fillOpacity={entry.isActual ? 0.9 : 0} />
              ))}
            </Bar>

            {/* PREDICTED DATA - Stacked bars (semi-transparent) */}
            <Bar 
              dataKey="predictedSolar" 
              name="Solar (Predicted)" 
              stackId="predicted"
              fill="#22c55e"
              stroke="#16a34a"
              strokeWidth={1}
              strokeDasharray="3 3"
            >
              {continuousChartData.map((entry, index) => (
                <Cell key={`pred-solar-${index}`} 
                      fillOpacity={entry.isPredicted ? 0.4 : 0} />
              ))}
            </Bar>
            
            <Bar 
              dataKey="predictedBatteryDischarge" 
              name="Battery (Predicted)" 
              stackId="predicted"
              fill="#8b5cf6"
              stroke="#7c3aed"
              strokeWidth={1}
              strokeDasharray="3 3"
            >
              {continuousChartData.map((entry, index) => (
                <Cell key={`pred-battery-${index}`} 
                      fillOpacity={entry.isPredicted ? 0.4 : 0} />
              ))}
            </Bar>
            
            <Bar 
              dataKey="predictedGridImport" 
              name="Grid (Predicted)" 
              stackId="predicted"
              fill="#3b82f6"
              stroke="#2563eb"
              strokeWidth={1}
              strokeDasharray="3 3"
            >
              {continuousChartData.map((entry, index) => (
                <Cell key={`pred-grid-${index}`} 
                      fillOpacity={entry.isPredicted ? 0.4 : 0} />
              ))}
            </Bar>

            {/* CONSUMPTION - Line overlay for actual data */}
            <Line
              type="monotone"
              dataKey="actualConsumption"
              stroke="#374151"
              strokeWidth={3}
              dot={{ r: 2, fill: '#374151' }}
              name="Consumption (Actual)"
              connectNulls={false}
            />

            {/* CONSUMPTION - Line overlay for predicted data */}
            <Line
              type="monotone"
              dataKey="predictedConsumption"
              stroke="#374151"
              strokeWidth={2}
              strokeDasharray="5 5"
              dot={{ r: 1, fill: '#374151' }}
              name="Consumption (Predicted)"
              connectNulls={false}
            />
            
            {/* PRICE - Secondary axis */}
            <Line
              yAxisId="price"
              type="monotone"
              dataKey="price"
              stroke="#ef4444"
              strokeWidth={2}
              dot={{ r: 0 }}
              name="Price"
              strokeDasharray="2 2"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Accuracy Summary */}
      <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-gray-50 p-3 rounded">
          <h4 className="font-medium text-gray-800 mb-2">Prediction Accuracy</h4>
          <div className="space-y-1">
            {continuousChartData.filter(d => d.accuracy !== null).slice(-6).map(d => (
              <div key={d.hour} className="flex justify-between items-center text-sm">
                <span>{d.hour}:00</span>
                <span className="font-medium" style={{ color: d.accuracyColor }}>
                  {d.accuracy!.toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-gray-50 p-3 rounded">
          <h4 className="font-medium text-gray-800 mb-2">Data Coverage</h4>
          <div className="text-sm space-y-1">
            <div className="flex justify-between">
              <span>Actual Hours:</span>
              <span className="font-medium">{continuousChartData.filter(d => d.isActual).length}</span>
            </div>
            <div className="flex justify-between">
              <span>Predicted Hours:</span>
              <span className="font-medium">{continuousChartData.filter(d => d.isPredicted).length}</span>
            </div>
            <div className="flex justify-between">
              <span>Current Hour:</span>
              <span className="font-medium">{currentHour}:00</span>
            </div>
          </div>
        </div>

        <div className="bg-gray-50 p-3 rounded">
          <h4 className="font-medium text-gray-800 mb-2">Energy Balance</h4>
          <div className="text-sm space-y-1">
            <div className="flex justify-between">
              <span>Solar Today:</span>
              <span className="font-medium text-green-600">
                {continuousChartData.reduce((sum, d) => sum + (d.isActual ? d.actualSolar : 0), 0).toFixed(1)} kWh
              </span>
            </div>
            <div className="flex justify-between">
              <span>Grid Import:</span>
              <span className="font-medium text-blue-600">
                {continuousChartData.reduce((sum, d) => sum + (d.isActual ? d.actualGridImport : 0), 0).toFixed(1)} kWh
              </span>
            </div>
            <div className="flex justify-between">
              <span>Battery Discharge:</span>
              <span className="font-medium text-purple-600">
                {continuousChartData.reduce((sum, d) => sum + (d.isActual ? d.actualBatteryDischarge : 0), 0).toFixed(1)} kWh
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="mt-3 text-sm text-gray-600">
        <p>
          <strong>Solid bars:</strong> Actual energy flows from completed hours. 
          <strong>Dashed bars:</strong> Predicted energy flows for future hours.
          The thick line shows actual consumption, dashed line shows predicted consumption.
          The red dashed line shows electricity price. Accuracy percentages show how close predictions were to reality.
        </p>
      </div>
    </div>
  );
};