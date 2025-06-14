import React from 'react';
import { Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Line, ComposedChart, Cell } from 'recharts';

export const EnergyFlowChart: React.FC<{
  dailyViewData: any[];
  energyBalanceData: any[];
  currentHour: number;
}> = ({ dailyViewData, energyBalanceData, currentHour }) => {
  
  // Dark mode detection for chart colors
  const isDarkMode = document.documentElement.classList.contains('dark');
  
  const colors = {
    grid: isDarkMode ? '#374151' : '#e5e7eb',
    text: isDarkMode ? '#d1d5db' : '#374151',
    background: isDarkMode ? '#1f2937' : '#ffffff',
    tooltip: isDarkMode ? '#374151' : '#ffffff',
    tooltipBorder: isDarkMode ? '#4b5563' : '#d1d5db',
    consumption: isDarkMode ? '#e5e7eb' : '#374151',
    price: isDarkMode ? '#fca5a5' : '#ef4444'
  };

  const chartData = Array.from({ length: 24 }, (_, hour) => {
    const dailyViewHour = dailyViewData?.find(h => h.hour === hour);
    const energyBalanceHour = energyBalanceData?.find(h => h.hour === hour);
    
    // Determine if we have actual data - check both sources
    const hasEnergyBalanceData = energyBalanceHour && (
      energyBalanceHour.system_production > 0 || 
      energyBalanceHour.load_consumption > 0 || 
      energyBalanceHour.import_from_grid > 0 ||
      energyBalanceHour.export_to_grid > 0 ||
      energyBalanceHour.battery_charge > 0 ||
      energyBalanceHour.battery_discharge > 0
    );
    
    const dailyViewIsActual = dailyViewHour?.data_source === 'actual';
    
    // isActual should be true if we have energy balance data OR if daily view says it's actual
    const isActual = hasEnergyBalanceData || dailyViewIsActual;
    const isPredicted = hour >= currentHour || (dailyViewHour?.data_source === 'predicted');
    
    // Use actual data from energy balance for past hours, or daily view if marked as actual
    let actualData = null;
    let predictedData = null;
    
    // Priority 1: Use energy balance data if available (most reliable for actual data)
    if (energyBalanceHour && hasEnergyBalanceData) {
      actualData = {
        solar: energyBalanceHour.system_production || 0,
        consumption: energyBalanceHour.load_consumption || 0,
        gridImport: energyBalanceHour.import_from_grid || 0,
        gridExport: energyBalanceHour.export_to_grid || 0,
        batteryCharge: energyBalanceHour.battery_charge || 0,
        batteryDischarge: energyBalanceHour.battery_discharge || 0,
      };
    }
    // Priority 2: Use daily view data if marked as actual and no energy balance data
    else if (dailyViewHour && dailyViewIsActual) {
      actualData = {
        solar: dailyViewHour.solar_generated || 0,
        consumption: dailyViewHour.home_consumed || 0,
        gridImport: dailyViewHour.grid_imported || 0,
        gridExport: dailyViewHour.grid_exported || 0,
        batteryCharge: dailyViewHour.battery_charged || 0,
        batteryDischarge: dailyViewHour.battery_discharged || 0,
      };
    }
    
    // Handle predicted data from daily view
    if (dailyViewHour) {
      const data = {
        solar: dailyViewHour.solar_generated || 0,
        consumption: dailyViewHour.home_consumed || 0,
        gridImport: dailyViewHour.grid_imported || 0,
        gridExport: dailyViewHour.grid_exported || 0,
        batteryCharge: dailyViewHour.battery_charged || 0,
        batteryDischarge: dailyViewHour.battery_discharged || 0,
      };
      
      // If this is predicted data OR if we don't have actual data, use as predicted
      if (dailyViewHour.data_source === 'predicted' || hour >= currentHour) {
        predictedData = data;
      }
    }
    
    // Calculate prediction accuracy for past hours where we have both actual and predicted
    let accuracy = null;
    if (actualData && dailyViewHour && isActual && dailyViewHour.data_source === 'actual') {
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
      isActual,
      isPredicted,
      actualData,
      predictedData,
      accuracy,
      price: dailyViewHour?.electricity_price || dailyViewHour?.buy_price || 0,
      hasEnergyBalance: hasEnergyBalanceData,
      dailyViewSource: dailyViewHour?.data_source || 'none'
    };
  });

  // Find the last actual consumption value to ensure line continuity
  const lastActualConsumptionData = chartData
    .filter(d => d.isActual && d.actualData?.consumption !== null && d.actualData?.consumption !== undefined)
    .sort((a, b) => b.hour - a.hour)[0]; // Get the latest hour with actual consumption
  
  const lastActualConsumption = lastActualConsumptionData?.actualData?.consumption;
  const lastActualHour = lastActualConsumptionData?.hour;

  // Process chart data with proper predicted data overlap
  const processedChartData = chartData.map((data) => {
    // Determine if this hour should show predicted data
    const shouldShowPredicted = data.hour >= Math.min(currentHour, (lastActualHour ?? currentHour));
    
    return {
      hour: data.hour,
      
      // Actual data - show if we have actual data
      actualSolar: data.isActual ? (data.actualData?.solar || 0) : 0,
      actualConsumption: data.isActual ? (data.actualData?.consumption || 0) : null,
      actualGridImport: data.isActual ? (data.actualData?.gridImport || 0) : 0,
      actualBatteryDischarge: data.isActual ? (data.actualData?.batteryDischarge || 0) : 0,
      
      // Predicted data - start at last actual hour to create overlap and remove gap
      predictedSolar: shouldShowPredicted && data.predictedData ? (data.predictedData.solar || 0) : 0,
      predictedConsumption: shouldShowPredicted && data.predictedData ? (data.predictedData.consumption || 0) : null,
      predictedGridImport: shouldShowPredicted && data.predictedData ? (data.predictedData.gridImport || 0) : 0,
      predictedBatteryDischarge: shouldShowPredicted && data.predictedData ? (data.predictedData.batteryDischarge || 0) : 0,
      
      // Meta information
      isActual: data.isActual,
      isPredicted: data.isPredicted,
      accuracy: data.accuracy,
      price: data.price,
      
      // For display
      dataType: data.isActual ? 'Actual' : 'Predicted',
      accuracyColor: data.accuracy !== null 
        ? data.accuracy > 90 ? '#22c55e' 
          : data.accuracy > 70 ? '#eab308' 
          : '#ef4444'
        : '#6b7280',
      
      // Debug info
      hasEnergyBalance: data.hasEnergyBalance,
      dailyViewSource: data.dailyViewSource
    };
  });

  // Ensure predicted line starts from the last actual consumption value
  const continuousChartData = processedChartData.map((data) => {
    // For the exact same hour as the last actual data, ensure the predicted line starts at the same value
    if (data.hour === lastActualHour && lastActualConsumption !== null && lastActualConsumption !== undefined) {
      return {
        ...data,
        predictedConsumption: lastActualConsumption // Start predicted line at exact same point
      };
    }
    // For subsequent predicted hours, use the predicted values or fill in missing data
    else if (data.predictedConsumption === null && data.hour > (lastActualHour ?? -1)) {
      // Find the daily view data for this hour to get predicted consumption
      const dailyViewHour = dailyViewData?.find(h => h.hour === data.hour);
      return {
        ...data,
        predictedConsumption: dailyViewHour?.home_consumed || 0
      };
    }
    return data;
  });

  const maxValue = Math.max(
    ...continuousChartData.map(d => Math.max(
      d.actualConsumption || 0,
      d.predictedConsumption || 0,
      (d.actualSolar || 0) + (d.actualBatteryDischarge || 0) + (d.actualGridImport || 0),
      (d.predictedSolar || 0) + (d.predictedBatteryDischarge || 0) + (d.predictedGridImport || 0)
    )),
    1 // Minimum value to avoid division by zero
  );

  // Custom tooltip with dark mode support
  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0]?.payload;
      if (!data) return null;
      
      return (
        <div 
          className="p-3 border rounded-lg shadow-lg"
          style={{
            backgroundColor: colors.tooltip,
            borderColor: colors.tooltipBorder,
            color: colors.text
          }}
        >
          <p className="font-medium" style={{ color: colors.text }}>{`Hour: ${label}:00`}</p>
          <p className="text-sm opacity-75 mb-2">{`Type: ${data.dataType}`}</p>
          
          {/* Debug info */}
          <div className="text-xs opacity-60 mb-2 border-b pb-1" style={{ borderColor: colors.tooltipBorder }}>
            <p>Has Energy Balance: {data.hasEnergyBalance ? 'Yes' : 'No'}</p>
            <p>Daily View Source: {data.dailyViewSource}</p>
          </div>
          
          {data.isActual ? (
            <div className="space-y-1">
              <p className="text-yellow-600">Solar: {data.actualSolar?.toFixed(1) || 0} kWh</p>
              <p className="text-blue-600">Grid: {data.actualGridImport?.toFixed(1) || 0} kWh</p>
              <p className="text-green-600">Battery: {data.actualBatteryDischarge?.toFixed(1) || 0} kWh</p>
              <p style={{ color: colors.text }}>Consumption: {data.actualConsumption?.toFixed(1) || 0} kWh</p>
              {data.predictedConsumption !== null && data.predictedConsumption !== undefined && (
                <p className="opacity-75">Consumption (pred): {data.predictedConsumption.toFixed(1)} kWh</p>
              )}
              {data.accuracy !== null && (
                <p className="text-sm font-medium" style={{ color: data.accuracyColor }}>
                  Prediction Accuracy: {data.accuracy.toFixed(1)}%
                </p>
              )}
            </div>
          ) : (
            <div className="space-y-1">
              <p className="text-yellow-600">Solar (pred): {data.predictedSolar?.toFixed(1) || 0} kWh</p>
              <p className="text-blue-600">Grid (pred): {data.predictedGridImport?.toFixed(1) || 0} kWh</p>
              <p className="text-green-600">Battery (pred): {data.predictedBatteryDischarge?.toFixed(1) || 0} kWh</p>
              <p style={{ color: colors.text }}>Consumption (pred): {data.predictedConsumption?.toFixed(1) || 0} kWh</p>
            </div>
          )}
          
          <p className="text-sm opacity-75 mt-2">Price: {data.price?.toFixed(2) || 0} SEK/kWh</p>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="bg-blue-50 dark:bg-blue-900/10 border-blue-200 dark:border-blue-800 border-2 rounded-xl p-6 transition-all duration-200 hover:shadow-lg">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold text-blue-900 dark:text-blue-100">
          Energy Flows
        </h2>
        <div className="flex items-center space-x-4 text-sm">
          <div className="flex items-center">
            <div 
              className="w-3 h-3 rounded mr-2"
              style={{ 
                backgroundColor: isDarkMode ? '#374151' : '#f3f4f6',
                border: `2px solid ${isDarkMode ? '#6b7280' : '#9ca3af'}`
              }}
            ></div>
            <span className="text-blue-800 dark:text-blue-200 opacity-80">
              Actual Data
            </span>
          </div>
          <div className="flex items-center">
            <div 
              className="w-3 h-3 rounded mr-2 opacity-70"
              style={{ 
                backgroundColor: isDarkMode ? '#1f2937' : '#f9fafb',
                border: `2px solid ${isDarkMode ? '#4b5563' : '#d1d5db'}`
              }}
            ></div>
            <span className="text-blue-800 dark:text-blue-200 opacity-80">
              Predicted Data
            </span>
          </div>
        </div>
      </div>

      <div className="h-96">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={continuousChartData}>
            <CartesianGrid strokeDasharray="3 3" stroke={colors.grid} />
            <XAxis 
              dataKey="hour"
              interval={2}
              tick={{ fontSize: 12, fill: colors.text }}
              axisLine={{ stroke: colors.text }}
              tickLine={{ stroke: colors.text }}
            />
            <YAxis 
              domain={[0, Math.ceil(maxValue * 1.1)]}
              label={{ 
                value: 'Energy (kWh)', 
                angle: -90, 
                position: 'insideLeft', 
                dx: -10,
                style: { textAnchor: 'middle', fill: colors.text }
              }}
              tick={{ fontSize: 12, fill: colors.text }}
              axisLine={{ stroke: colors.text }}
              tickLine={{ stroke: colors.text }}
            />
            <YAxis 
              yAxisId="price"
              orientation="right"
              domain={[0, 'auto']}
              label={{ 
                value: 'Price (SEK/kWh)', 
                angle: 90, 
                position: 'insideRight', 
                dx: 10,
                style: { textAnchor: 'middle', fill: colors.text }
              }}
              tick={{ fontSize: 12, fill: colors.text }}
              axisLine={{ stroke: colors.text }}
              tickLine={{ stroke: colors.text }}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend wrapperStyle={{ color: colors.text }} />

            {/* ACTUAL DATA - Stacked bars (solid) */}
            <Bar 
              dataKey="actualSolar" 
              name="Solar (Actual)" 
              stackId="energy"
              fill="#fbbf24"
              stroke="#f59e0b"
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
              stackId="energy"
              fill="#10b981"
              stroke="#059669"
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
              stackId="energy"
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
              stackId="energy"
              fill="#fbbf24"
              stroke="#f59e0b"
              strokeWidth={1}
              strokeDasharray="3 3"
            >
              {continuousChartData.map((entry, index) => (
                <Cell key={`pred-solar-${index}`} 
                      fillOpacity={entry.predictedSolar > 0 ? 0.4 : 0} />
              ))}
            </Bar>
            
            <Bar 
              dataKey="predictedBatteryDischarge" 
              name="Battery (Predicted)" 
              stackId="energy"
              fill="#10b981"
              stroke="#059669"
              strokeWidth={1}
              strokeDasharray="3 3"
            >
              {continuousChartData.map((entry, index) => (
                <Cell key={`pred-battery-${index}`} 
                      fillOpacity={entry.predictedBatteryDischarge > 0 ? 0.4 : 0} />
              ))}
            </Bar>
            
            <Bar 
              dataKey="predictedGridImport" 
              name="Grid (Predicted)" 
              stackId="energy"
              fill="#3b82f6"
              stroke="#2563eb"
              strokeWidth={1}
              strokeDasharray="3 3"
            >
              {continuousChartData.map((entry, index) => (
                <Cell key={`pred-grid-${index}`} 
                      fillOpacity={entry.predictedGridImport > 0 ? 0.4 : 0} />
              ))}
            </Bar>

            {/* CONSUMPTION - Line overlay for actual data */}
            <Line
              type="monotone"
              dataKey="actualConsumption"
              stroke={colors.consumption}
              strokeWidth={3}
              dot={{ r: 2, fill: colors.consumption }}
              name="Consumption (Actual)"
              connectNulls={false}
            />

            {/* CONSUMPTION - Line overlay for predicted data */}
            <Line
              type="monotone"
              dataKey="predictedConsumption"
              stroke={colors.consumption}
              strokeWidth={2}
              strokeDasharray="5 5"
              dot={{ r: 1, fill: colors.consumption }}
              name="Consumption (Predicted)"
              connectNulls={false}
            />
            
            {/* PRICE - Secondary axis */}
            <Line
              yAxisId="price"
              type="monotone"
              dataKey="price"
              stroke={colors.price}
              strokeWidth={2}
              dot={{ r: 0 }}
              name="Price"
              strokeDasharray="2 2"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-3 text-sm text-blue-800 dark:text-blue-200 opacity-70">
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