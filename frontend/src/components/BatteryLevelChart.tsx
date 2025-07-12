import React from 'react';
import { XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine, Bar, ComposedChart, Area, Line } from 'recharts';
import { BatterySettings } from '../types';

interface BatteryLevelChartProps {
  hourlyData: any[];
  settings: BatterySettings;
}

export const BatteryLevelChart: React.FC<BatteryLevelChartProps> = ({ hourlyData, settings }) => {
  // Dark mode detection for chart colors only
  const isDarkMode = document.documentElement.classList.contains('dark');
  
  const colors = {
    grid: isDarkMode ? '#374151' : '#e5e7eb',
    text: isDarkMode ? '#d1d5db' : '#374151',
    background: isDarkMode ? '#1f2937' : '#ffffff',
    tooltip: isDarkMode ? '#374151' : '#ffffff',
    tooltipBorder: isDarkMode ? '#4b5563' : '#d1d5db'
  };

  // Transform daily view data to chart format
  const chartData = hourlyData.map((hour, index) => {
    // Check for missing keys and provide warnings
    if (hour.batteryAction === undefined) {
      console.warn(`Missing key: batteryAction at index ${index}`);
    }
    if (hour.batterySocEnd === undefined) {
      console.warn(`Missing key: batterySocEnd at index ${index}`);
    }
    if (hour.buyPrice === undefined) {
      console.warn(`Missing key: buyPrice at index ${index}`);
    }
    if (hour.dataSource === undefined) {
      console.warn(`Missing key: dataSource at index ${index}`);
    }
    
    const batteryAction = hour.batteryAction ?? 0;
    const batterySocPercent = hour.batterySocEnd ?? 0;  // Use clear SOC field
    const price = hour.buyPrice ?? 0;
    const hourNum = typeof hour.hour === 'number' ? hour.hour : index;
    const dataSource = hour.dataSource ?? 'unknown';
    
    return {
      hour: `${hourNum}:00`,
      hourNum,
      batterySocPercent: batterySocPercent,
      action: batteryAction,
      price: price,
      dataSource: dataSource,
      isActual: dataSource === 'actual',
      isPredicted: dataSource === 'predicted'
    };
  });
    
  const maxAction = Math.max(...chartData.map(d => Math.abs(d.action || 0)), 1);
  const maxPrice = Math.max(...chartData.map(h => h.price), 1);

  return (
    <div className="bg-green-50 dark:bg-green-900/10 border-green-200 dark:border-green-800 border-2 rounded-xl p-6 transition-all duration-200 hover:shadow-lg">
      <h2 className="text-xl font-semibold mb-4 text-green-900 dark:text-green-100">
        Battery SOC and Actions
      </h2>
      <div className="h-80">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke={colors.grid} />
            <XAxis 
              dataKey="hour" 
              interval={2} 
              tick={{ fill: colors.text, fontSize: 12 }}
              axisLine={{ stroke: colors.text }}
              tickLine={{ stroke: colors.text }}
            />
            
            {/* Left Y-axis for Battery SOC (%) */}
            <YAxis 
              yAxisId="left" 
              domain={[0, 100]} 
              tickFormatter={(value) => `${value.toFixed(0)}%`}
              label={{ 
                value: 'Battery SOC (%)', 
                angle: -90, 
                position: 'insideLeft', 
                style: { textAnchor: 'middle', fill: colors.text } 
              }}
              tick={{ fill: colors.text, fontSize: 12 }}
              axisLine={{ stroke: colors.text }}
              tickLine={{ stroke: colors.text }}
            />
            
            {/* Right Y-axis for Electricity Price (SEK/kWh) */}
            <YAxis 
              yAxisId="right" 
              orientation="right" 
              domain={[0, Math.ceil(maxPrice * 1.2 * 10) / 10]}
              tickFormatter={(value) => `${value.toFixed(2)}`}
              label={{ 
                value: 'Price (SEK/kWh)', 
                angle: 90, 
                position: 'insideRight', 
                style: { textAnchor: 'middle', fill: colors.text } 
              }}
              tick={{ fill: colors.text, fontSize: 12 }}
              axisLine={{ stroke: colors.text }}
              tickLine={{ stroke: colors.text }}
            />
            
            {/* Third Y-axis for Battery Actions (kWh) */}
            <YAxis 
              yAxisId="action"
              orientation="right"
              domain={[-maxAction * 1.2, maxAction * 1.2]}
              tickFormatter={(value) => `${value.toFixed(1)}`}
              axisLine={{ stroke: '#8884d8', strokeWidth: 2 }}
              tickLine={{ stroke: '#8884d8' }}
              tick={{ fill: '#8884d8', fontSize: 12 }}
              label={{ 
                value: 'Battery Action (kWh)', 
                angle: 90, 
                position: 'outside',
                offset: 40,
                style: { textAnchor: 'middle', fill: '#8884d8' } 
              }}
            />
            
            <Tooltip 
              contentStyle={{
                backgroundColor: colors.tooltip,
                border: `1px solid ${colors.tooltipBorder}`,
                borderRadius: '8px',
                color: colors.text
              }}
              formatter={(value, name) => {
                if (name === 'price') return [`${Number(value).toFixed(2)} SEK/kWh`, 'Electricity Price'];
                if (name === 'batterySocPercent') return [`${Number(value).toFixed(1)}%`, 'Battery SOC'];
                if (name === 'action') {
                  const actionValue = Number(value);
                  const actionType = actionValue >= 0 ? 'Charging' : 'Discharging';
                  return [`${Math.abs(actionValue).toFixed(2)} kWh ${actionType}`, 'Battery Action'];
                }
                return [Number(value).toFixed(2), name];
              }}
              labelFormatter={(label) => `Hour: ${label}`}
              labelStyle={{ color: colors.text }}
            />
            <Legend wrapperStyle={{ color: colors.text }} />
            
            <ReferenceLine 
              yAxisId="left" 
              y={(settings.reservedCapacity || 0) / (settings.totalCapacity || 30) * 100} 
              stroke="#ef4444" 
              strokeDasharray="3 3" 
              label={{ value: "Min SOC", style: { fill: colors.text } }}
            />
            <ReferenceLine yAxisId="action" y={0} stroke={colors.grid} strokeDasharray="2 2" />
            
            <Area
              yAxisId="left"
              type="monotone"
              dataKey="batterySocPercent"
              stroke="#16a34a"
              strokeWidth={2}
              fill="#16a34a"
              fillOpacity={0.1}
              name="Battery SOC"
            />
            
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="price"
              stroke="#2563eb"
              strokeWidth={3}
              name="Electricity Price"
              dot={{ fill: '#2563eb', r: 1 }}
            />
            
            <Bar 
              yAxisId="action" 
              dataKey="action" 
              name="Battery Action" 
              radius={[2, 2, 2, 2]}
              shape={(props: any) => {
                const { payload, x, y, width, height } = props;
                const action = payload.action || 0;
                const isActual = payload.isActual;
                
                const fillColor = action >= 0 ? '#16a34a' : '#dc2626';
                const opacity = isActual ? 0.9 : 0.6;
                
                return (
                  <rect 
                    x={x} 
                    y={action >= 0 ? y : y + height} 
                    width={width} 
                    height={Math.abs(height)} 
                    fill={fillColor}
                    fillOpacity={opacity}
                    rx={2}
                    ry={2}
                  />
                );
              }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      
      <div className="mt-3 text-sm text-green-800 dark:text-green-200 opacity-70">
        <p>
          <strong>Green area:</strong> Battery state of charge (SOC) throughout the day.
          <strong>Blue line:</strong> Electricity price variations.
          <strong>Bars:</strong> Battery charging (green) and discharging (red) actions. 
          Solid bars show actual data, semi-transparent bars show predicted actions.
        </p>
      </div>
    </div>
  );
};