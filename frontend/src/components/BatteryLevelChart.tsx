import React from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine } from 'recharts';
import { HourlyData, BatterySettings } from '../types';

interface BatteryLevelChartProps {
  hourlyData: HourlyData[];
  settings: BatterySettings;
}

export const BatteryLevelChart: React.FC<BatteryLevelChartProps> = ({ hourlyData, settings }) => {
    return (
      <div className="bg-white p-6 rounded-lg shadow">
        <h2 className="text-xl font-semibold mb-4">Battery Level and Electricity Price</h2>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={hourlyData}>
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
              <Tooltip />
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
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="price"
                stroke="#2563eb"
                name="Price (SEK/kWh)"
                strokeWidth={2}
              />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="batteryLevel"
                stroke="#16a34a"
                name="Battery Level (kWh)"
                strokeWidth={2}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    );
  };