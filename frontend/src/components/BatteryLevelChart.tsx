import React from 'react';
import { Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine, Bar, ComposedChart } from 'recharts';
import { HourlyData, BatterySettings } from '../types';

interface BatteryLevelChartProps {
  hourlyData: HourlyData[];
  settings: BatterySettings;
}

export const BatteryLevelChart: React.FC<BatteryLevelChartProps> = ({ hourlyData, settings }) => {
    // Add battery actions as separate series for better visualization
    const chartData = hourlyData.map(hour => {
      const batteryAction = hour.action || 0;
      return {
        ...hour,
        // Split action into charge and discharge for visualization
        batteryCharge: batteryAction > 0 ? batteryAction : 0,
        batteryDischarge: batteryAction < 0 ? -batteryAction : 0,
      };
    });
    
    // Calculate max charge/discharge value for y-axis scaling
    const maxAction = Math.max(
      ...chartData.map(d => Math.max(
        Math.abs(d.batteryCharge || 0), 
        Math.abs(d.batteryDischarge || 0)
      ))
    );

    return (
      <div className="bg-white p-6 rounded-lg shadow">
        <h2 className="text-xl font-semibold mb-4">Battery Level and Actions</h2>
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="hour" interval={2} />
              <YAxis 
                yAxisId="left" 
                domain={[0, Math.min(settings.totalCapacity + 5, Math.ceil(settings.totalCapacity * 1.15))]} 
                tickFormatter={(value) => value.toFixed(0)}
                label={{ value: 'Battery Level (kWh)', angle: -90, position: 'insideLeft', dy: 50 }}
              />
              <YAxis 
                yAxisId="right" 
                orientation="right" 
                domain={[0, Math.ceil(Math.max(...hourlyData.map(h => h.price)) * 1.2 / 0.5) * 0.5]}
                tickFormatter={(value) => value.toFixed(2)}
                label={{ value: 'Price (SEK/kWh)', angle: 90, position: 'insideRight', dx: 0, dy: -50 }}
              />
              <YAxis 
                yAxisId="action"
                orientation="right"
                axisLine={false}
                tickLine={false}
                domain={[0, Math.ceil(maxAction * 1.2)]}
                hide={true}
              />
              <Tooltip 
                formatter={(value, name) => {
                  switch(name) {
                    case 'batteryLevel': 
                      return [`${Number(value).toFixed(1)} kWh`, 'Battery Level'];
                    case 'price': 
                      return [`Buy: ${Number(value).toFixed(2)} / Sell: ${(Number(value) * 0.8).toFixed(2)} SEK/kWh`, 'Price'];
                    case 'batteryCharge': 
                      return [`+${Number(value).toFixed(1)} kWh`, 'Charging'];
                    case 'batteryDischarge': 
                      return [`-${Number(value).toFixed(1)} kWh`, 'Discharging'];
                    default: 
                      return [value, name];
                  }
                }}
              />
              <Legend />
              <ReferenceLine 
                yAxisId="left" 
                y={settings.reservedCapacity} 
                stroke="#ef4444" 
                strokeDasharray="3 3" 
                label={`Min Level (${settings.reservedCapacity} kWh)`}
              />
              <ReferenceLine 
                yAxisId="left" 
                y={settings.totalCapacity} 
                stroke="#ef4444" 
                strokeDasharray="3 3" 
                label={`Max Level (${settings.totalCapacity} kWh)`}
              />
              
              {/* Price line */}
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="price"
                stroke="#2563eb"
                name="Price (SEK/kWh)"
                strokeWidth={2}
                dot={{ r: 0 }}
              />
              
              {/* Battery level line */}
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="batteryLevel"
                stroke="#16a34a"
                name="Battery Level (kWh)"
                strokeWidth={2}
                dot={{ r: 1 }}
              />
              
              {/* Battery charge bars (positive) */}
              <Bar 
                yAxisId="action"
                dataKey="batteryCharge"
                name="Charging"
                fill="#10b981"
                opacity={0.7}
                radius={[4, 4, 0, 0]}
              />
              
              {/* Battery discharge bars (negative) - display as positive but with different color */}
              <Bar
                yAxisId="action"
                dataKey="batteryDischarge"
                name="Discharging"
                fill="#ef4444"
                opacity={0.7}
                radius={[4, 4, 0, 0]}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-3 text-sm text-gray-600">
          <p>This chart shows battery level (green line) alongside electricity price (blue line). 
             Green bars indicate battery charging, red bars indicate discharging. 
             The dashed lines show minimum and maximum battery capacity.</p>
        </div>
      </div>
    );
  };