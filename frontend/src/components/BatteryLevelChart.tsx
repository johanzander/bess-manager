import React from 'react';
import { XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine, Bar, ComposedChart, Area, Line } from 'recharts';
import { BatterySettings } from '../types';

interface BatteryLevelChartProps {
  hourlyData: any[]; // Daily view hourly data
  settings: BatterySettings;
}

export const BatteryLevelChart: React.FC<BatteryLevelChartProps> = ({ hourlyData, settings }) => {
  // Transform daily view data to chart format
  const chartData = hourlyData.map((hour, index) => {
    // Map daily view fields to chart fields
    const batteryAction = hour.battery_action || 0;
    const batteryLevel = hour.battery_soc_end || hour.batteryLevel || 0;
    const price = hour.electricity_price || hour.buy_price || hour.price || 0;
    const hourNum = typeof hour.hour === 'number' ? hour.hour : index;
    
    return {
      hour: `${hourNum}:00`,
      hourNum,
      batteryLevel: batteryLevel,
      action: batteryAction,
      price: price,
      // Split action into charge and discharge for visualization
      batteryCharge: batteryAction > 0 ? batteryAction : 0,
      batteryDischarge: batteryAction < 0 ? -batteryAction : 0,
      // Additional fields from daily view
      dataSource: hour.data_source || 'unknown'
    };
  });
    
  // Calculate max charge/discharge value for y-axis scaling
  const maxAction = Math.max(
    ...chartData.map(d => Math.max(
      Math.abs(d.batteryCharge || 0), 
      Math.abs(d.batteryDischarge || 0)
    )),
    1
  );

  // Calculate max price for y-axis scaling
  const maxPrice = Math.max(...chartData.map(h => h.price), 1);

  return (
    <div className="bg-white p-6 rounded-lg shadow">
      <h2 className="text-xl font-semibold mb-4">Battery SOC and Actions</h2>
      <div className="h-80">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="hour" interval={2} />
            <YAxis 
              yAxisId="left" 
              domain={[0, Math.min(settings.totalCapacity + 5, Math.ceil(settings.totalCapacity * 1.15))]} 
              tickFormatter={(value) => value.toFixed(0)}
              label={{ value: 'Battery SOC (kWh)', angle: -90, position: 'insideLeft', dy: 50 }}
            />
            <YAxis 
              yAxisId="right" 
              orientation="right" 
              domain={[0, Math.ceil(maxPrice * 1.2 * 10) / 10]}
              tickFormatter={(value) => value.toFixed(2)}
              label={{ value: 'Price (SEK/kWh)', angle: 90, position: 'insideRight', dx: 0, dy: -50 }}
            />
            <YAxis 
              yAxisId="action"
              orientation="right"
              axisLine={false}
              tickLine={false}
              tick={false}
              domain={[-maxAction * 1.2, maxAction * 1.2]}
            />
            
            <Tooltip 
              formatter={(value, name) => {
                if (name === 'price') return [`${Number(value).toFixed(2)} SEK/kWh`, 'Electricity Price'];
                if (name === 'batteryLevel') return [`${Number(value).toFixed(2)} kWh`, 'Battery SOC'];
                if (name === 'action') return [`${Number(value).toFixed(2)} kWh`, 'Battery Action'];
                return [Number(value).toFixed(2), name];
              }}
              labelFormatter={(label) => `Hour: ${label}`}
            />
            <Legend />
            
            {/* Add reference lines for battery limits */}
            <ReferenceLine 
              yAxisId="left" 
              y={settings.reservedCapacity || 0} 
              stroke="#ef4444" 
              strokeDasharray="3 3" 
              label={`Min (${(settings.reservedCapacity || 0).toFixed(1)} kWh)`}
            />
            <ReferenceLine 
              yAxisId="left" 
              y={settings.totalCapacity || 30} 
              stroke="#ef4444" 
              strokeDasharray="3 3" 
              label={`Max (${(settings.totalCapacity || 30).toFixed(1)} kWh)`}
            />
            <ReferenceLine yAxisId="action" y={0} stroke="#666666" />
            
            {/* Battery SOC as filled area */}
            <Area
              yAxisId="left"
              type="monotone"
              dataKey="batteryLevel"
              stroke="#16a34a"
              strokeWidth={2}
              fill="#16a34a"
              fillOpacity={0.1}
              name="Battery SOC"
            />
            
            {/* Price as line */}
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="price"
              stroke="#2563eb"
              strokeWidth={3}
              name="Electricity Price"
              dot={{ fill: '#2563eb', r: 1 }}
            />
            
            {/* Battery actions as bars */}
            <Bar 
              yAxisId="action" 
              dataKey="action" 
              name="Battery Action" 
              radius={[2, 2, 2, 2]}
            >
              {chartData.map((entry, index) => {
                // Color based on charge/discharge and data source
                let fillColor;
                if (entry.action >= 0) {
                  fillColor = '#16a34a'; // Green for charging
                } else {
                  fillColor = '#dc2626'; // Red for discharging
                }
                
                // Adjust opacity based on data source
                const opacity = entry.dataSource === 'actual' ? 0.9 : 0.6;
                
                return (
                  <rect 
                    key={`cell-${index}`} 
                    fill={fillColor}
                    fillOpacity={opacity}
                  />
                );
              })}
            </Bar>
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      
      {/* Legend for data types */}
      <div className="mt-4 flex items-center justify-center space-x-6 text-sm">
        <div className="flex items-center">
          <div className="w-4 h-4 bg-green-600 mr-2"></div>
          <span>Charging (Actual)</span>
        </div>
        <div className="flex items-center">
          <div className="w-4 h-4 bg-green-600 opacity-60 mr-2"></div>
          <span>Charging (Predicted)</span>
        </div>
        <div className="flex items-center">
          <div className="w-4 h-4 bg-red-600 mr-2"></div>
          <span>Discharging (Actual)</span>
        </div>
        <div className="flex items-center">
          <div className="w-4 h-4 bg-red-600 opacity-60 mr-2"></div>
          <span>Discharging (Predicted)</span>
        </div>
      </div>

    </div>
  );
};