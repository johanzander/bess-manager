import React from 'react';
import { Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Line, ComposedChart } from 'recharts';
import { HourlyData } from '../types';

interface EnergyFlowChartProps {
  hourlyData: HourlyData[];
}

export const EnergyFlowChart: React.FC<EnergyFlowChartProps> = ({ hourlyData }) => {
  // Transform data to ensure all needed fields exist
  const chartData = hourlyData.map(hour => {
    const consumption = hour.consumption || 0;
    const solarProduction = hour.solarProduction || 0;
    
    // Get battery data either from direct fields or action
    const batteryAction = hour.action || 0;
    const batteryDischarge = hour.batteryDischarge || (batteryAction < 0 ? -batteryAction : 0);
    
    // Get grid import directly or calculate it
    // If we have direct gridImport data, use it
    const gridImport = hour.gridImport !== undefined ? hour.gridImport : 
                     Math.max(0, consumption - solarProduction - batteryDischarge);
    
    return {
      ...hour,
      hour: hour.hour || `${hour}`,
      // Ensure all values are present and normalized
      solarProduction,
      consumption,
      batteryDischarge,
      gridImport,
      // Format the data for display
      solarProductionFormatted: solarProduction.toFixed(1),
      batteryDischargeFormatted: batteryDischarge.toFixed(1),
      gridImportFormatted: gridImport.toFixed(1),
      consumptionFormatted: consumption.toFixed(1),
      priceFormatted: hour.price.toFixed(2)
    };
  });

  // Find the max value for y axis scaling
  const maxValue = Math.max(
    ...chartData.map(d => Math.max(
      d.consumption || 0,
      (d.solarProduction || 0) + (d.batteryDischarge || 0) + (d.gridImport || 0), // Maximum possible stack height
      (d.price || 0) * 5 // Scale price up for visibility
    ))
  );

  return (
    <div className="bg-white p-6 rounded-lg shadow">
      <h2 className="text-xl font-semibold mb-4">Energy Flow Overview</h2>
      <div className="h-80">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData}>
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
            <Tooltip
              formatter={(value, name, props) => {
                // Use pre-formatted values for better display
                const item = props.payload;
                if (item) {
                  switch (name) {
                    case 'solarProduction': return [item.solarProductionFormatted + ' kWh', 'Solar'];
                    case 'batteryDischarge': return [item.batteryDischargeFormatted + ' kWh', 'Battery'];
                    case 'gridImport': return [item.gridImportFormatted + ' kWh', 'Grid'];
                    case 'consumption': return [item.consumptionFormatted + ' kWh', 'Consumption'];
                    case 'price': return [`Buy: ${item.priceFormatted} / Sell: ${(Number(item.price) * 0.8).toFixed(2)} SEK/kWh`, 'Price'];
                    default: return [value, name];
                  }
                }
                // Fallback if item not available
                return [value, name];
              }}
              labelFormatter={(label) => `Hour: ${label}`}
            />
            <Legend />

            {/* ENERGY SOURCES - Stacked bars */}
            <Bar 
              dataKey="solarProduction" 
              name="Solar" 
              stackId="sources"
              fill="#fbbf24" 
            />
            <Bar 
              dataKey="batteryDischarge" 
              name="Battery" 
              stackId="sources"
              fill="#10b981" 
            />
            <Bar 
              dataKey="gridImport" 
              name="Grid" 
              stackId="sources"
              fill="#60a5fa" 
            />
           
            {/* CONSUMPTION - Represented as a line */}
            <Line
              type="monotone"
              dataKey="consumption"
              stroke="#374151"
              strokeWidth={3}
              dot={{ r: 1 }}
              name="Consumption"
            />
            
            {/* PRICE - On secondary axis */}
            <Line
              yAxisId="price"
              type="monotone"
              dataKey="price"
              stroke="#ef4444"
              strokeWidth={2}
              dot={{ r: 0 }}
              name="Price"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-3 text-sm text-gray-600">
        <p>This chart shows how your energy needs (black line) are met by different sources (stacked bars). 
        The stacked bars represent energy from solar (yellow), battery discharge (green), and grid import (blue). 
        The red line shows electricity price throughout the day.</p>
      </div>
    </div>
  );
};