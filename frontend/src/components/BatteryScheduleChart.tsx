import React from 'react';
import { Cell, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine, ComposedChart, Line, Area } from 'recharts';
import { HourlyData, BatterySettings, EnergyProfile } from '../types';

interface BatteryScheduleChartProps {
  hourlyData: HourlyData[];
  settings: BatterySettings;
  energyProfile?: EnergyProfile;
}

export const BatteryScheduleChart: React.FC<BatteryScheduleChartProps> = ({ 
  hourlyData, 
  settings,
  energyProfile 
}) => {
  // Prepare data for the chart
  const chartData = hourlyData.map((hour, index) => {
    // Get the hour from "00:00" format to just the number
    const hourNum = parseInt(hour.hour.split(':')[0]);
    
    return {
      hour: hour.hour,
      hourNum,
      price: hour.price,
      batteryLevel: hour.batteryLevel,
      action: hour.action,
      solarProduction: energyProfile?.solar?.[index] || 0,
      consumption: hour.consumption || settings.estimatedConsumption,
      gridCost: hour.gridCost,
      batteryCost: hour.batteryCost,
      totalCost: hour.totalCost,
      baseCost: hour.baseCost,
      savings: hour.savings
    };
  });

  return (
    <div className="bg-white p-6 rounded-lg shadow">
      <h2 className="text-xl font-semibold mb-4">Battery Schedule Overview</h2>
      <div className="h-80">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="hour" interval={2} />
            <YAxis 
              yAxisId="left" 
              domain={[0, Math.min(settings.totalCapacity + 5, Math.ceil(settings.totalCapacity * 1.15))]} 
              tickFormatter={(value) => value.toFixed(0)}
              label={{ value: 'Energy (kWh)', angle: -90, position: 'insideLeft', dy: 50 }}
            />
            <YAxis 
              yAxisId="right" 
              orientation="right" 
              domain={[
                Math.min(...chartData.map(d => Math.min(d.price, -1))), 
                Math.max(...chartData.map(d => Math.max(d.price * 2, 2)))
              ]}
              tickFormatter={(value) => value.toFixed(2)}
              label={{ value: 'Price (SEK/kWh)', angle: 90, position: 'insideRight', dx: 0, dy: -50 }}
            />
            <Tooltip 
              formatter={(value, name) => {
                if (name === 'price') return [`${Number(value).toFixed(2)} SEK/kWh`, 'Price'];
                if (name === 'batteryLevel') return [`${Number(value).toFixed(1)} kWh`, 'Battery Level'];
                if (name === 'action') return [`${Number(value).toFixed(1)} kWh`, 'Battery Action'];
                if (name === 'solarProduction') return [`${Number(value).toFixed(1)} kWh`, 'Solar Production'];
                if (name === 'consumption') return [`${Number(value).toFixed(1)} kWh`, 'Consumption'];
                return [value, name];
              }}
              labelFormatter={(label) => `Hour: ${label}`}
            />
            <Legend />
            
            {/* Add reference lines */}
            <ReferenceLine 
              yAxisId="left" 
              y={settings.reservedCapacity} 
              stroke="#ef4444" 
              strokeDasharray="3 3" 
              label={`Min (${settings.reservedCapacity.toFixed(1)} kWh)`}
            />
            <ReferenceLine 
              yAxisId="left" 
              y={settings.totalCapacity} 
              stroke="#ef4444" 
              strokeDasharray="3 3" 
              label={`Max (${settings.totalCapacity.toFixed(1)} kWh)`}
            />
            <ReferenceLine yAxisId="right" y={0} stroke="#666666" />
            
            {/* Battery level as line */}
            <Line
              yAxisId="left"
              type="monotone"
              dataKey="batteryLevel"
              stroke="#16a34a"
              strokeWidth={2}
              name="Battery Level"
              dot={{ fill: '#16a34a', r: 1 }}
            />
            
            {/* Price as line */}
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="price"
              stroke="#2563eb"
              strokeWidth={2}
              name="Price"
              dot={{ fill: '#2563eb', r: 1 }}
            />
            
            {/* Solar production as area */}
            <Area
              yAxisId="left"
              type="monotone"
              dataKey="solarProduction"
              fill="#fcd34d"
              stroke="#f59e0b"
              fillOpacity={0.3}
              name="Solar Production"
            />
            
            {/* Battery actions as bars */}
            <Bar 
              yAxisId="left" 
              dataKey="action" 
              name="Battery Action" 
              fill="#16a34a"
              radius={[4, 4, 0, 0]}
            >
              {chartData.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.action >= 0 ? '#16a34a' : '#dc2626'} />
              ))}
            </Bar>
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};