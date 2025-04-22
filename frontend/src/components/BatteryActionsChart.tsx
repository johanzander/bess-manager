// src/components/battery/BatteryActionsChart.tsx
import React from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine, Cell } from 'recharts';
import { HourlyData } from '../types';

interface BatteryActionsChartProps {
  hourlyData: HourlyData[];
}

export const BatteryActionsChart: React.FC<BatteryActionsChartProps> = ({ hourlyData }) => {
  return (
    <div className="bg-white p-6 rounded-lg shadow">
      <h2 className="text-xl font-semibold mb-4">Battery Actions</h2>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={hourlyData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="hour" interval={2} />
            <YAxis domain={[-7, 7]} />
            <Tooltip />
            <Legend />
            <ReferenceLine y={0} stroke="#666666" />
            <ReferenceLine y={6} stroke="#ef4444" strokeDasharray="3 3" label="Max Charge" />
            <ReferenceLine y={-6} stroke="#ef4444" strokeDasharray="3 3" label="Max Discharge" />
            <Bar dataKey="action" name="Charge/Discharge (kWh)">
              {hourlyData.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.action >= 0 ? '#16a34a' : '#dc2626'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};