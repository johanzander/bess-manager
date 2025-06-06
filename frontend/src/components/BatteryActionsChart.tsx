// src/components/battery/BatteryActionsChart.tsx
import React from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine, Cell } from 'recharts';
import { HourlyData } from '../types';

interface BatteryActionsChartProps {
  hourlyData: HourlyData[];
}

export const BatteryActionsChart: React.FC<BatteryActionsChartProps> = ({ hourlyData }) => {
  // Get current hour for styling
  const currentHour = new Date().getHours();
  
  // Prepare data to handle both camelCase and snake_case field names
  const processedData = hourlyData.map((hour, index) => {
    // Use either action, batteryAction, or battery_action field
    const actionValue = hour.action !== undefined ? hour.action : 
                       (hour.batteryAction !== undefined ? hour.batteryAction : 
                       (hour.battery_action !== undefined ? hour.battery_action : 0));
    
    // Determine if this is actual or predicted data
    const hourNum = typeof hour.hour === 'string' && hour.hour.includes(':') 
      ? parseInt(hour.hour.split(':')[0])
      : typeof hour.hour === 'number'
        ? hour.hour 
        : index;
    
    const isActual = hourNum < currentHour;
    const isPredicted = hourNum >= currentHour;
    const isCurrent = hourNum === currentHour;
    
    return {
      ...hour,
      hour: hour.hour || `${index}:00`,
      action: actionValue,  // Ensure action field exists for the chart
      isActual,
      isPredicted,
      isCurrent,
      hourNum
    };
  });

  return (
    <div className="bg-white p-6 rounded-lg shadow">
      <h2 className="text-xl font-semibold mb-4">Battery Actions</h2>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={processedData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="hour" interval={2} />
            <YAxis domain={[-7, 7]} />
            <Tooltip 
              formatter={(value, _name, props) => {
                const isActual = props.payload.isActual;
                const prefix = isActual ? '[Actual] ' : '[Predicted] ';
                return [Number(value).toFixed(1) + ' kWh', prefix + 'Battery Action'];
              }}
            />
            <Legend />
            <ReferenceLine y={0} stroke="#666666" />
            <ReferenceLine y={6} stroke="#ef4444" strokeDasharray="3 3" label="Max Charge" />
            <ReferenceLine y={-6} stroke="#ef4444" strokeDasharray="3 3" label="Max Discharge" />
            <Bar dataKey="action" name="Charge/Discharge (kWh)">
              {processedData.map((entry, index) => {
                let fillColor;
                if (entry.action >= 0) {
                  // Charging - green
                  fillColor = '#16a34a';
                } else {
                  // Discharging - red
                  fillColor = '#dc2626';
                }
                
                // Reduce opacity for predicted data
                const opacity = entry.isActual ? 1 : 0.6;
                
                return (
                  <Cell 
                    key={`cell-${index}`} 
                    fill={fillColor}
                    fillOpacity={opacity}
                    stroke={entry.isCurrent ? '#7c3aed' : 'none'}
                    strokeWidth={entry.isCurrent ? 2 : 0}
                  />
                );
              })}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      
      {/* Legend for actual/predicted data */}
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
        <div className="flex items-center">
          <div className="w-4 h-4 border-2 border-purple-600 mr-2"></div>
          <span>Current Hour</span>
        </div>
      </div>
    </div>
  );
};