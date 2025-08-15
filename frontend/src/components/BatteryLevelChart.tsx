import React, { useState, useEffect } from 'react';
import { XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Bar, ComposedChart, Area, Line } from 'recharts';
import { HourlyData } from '../types';

interface BatteryLevelChartProps {
  hourlyData: HourlyData[];
  settings: any; // Adjust type as needed
}

export const BatteryLevelChart: React.FC<BatteryLevelChartProps> = ({ hourlyData }) => {
  // Reactive dark mode detection
  const [isDarkMode, setIsDarkMode] = useState(
    document.documentElement.classList.contains('dark')
  );

  // Listen for dark mode changes
  useEffect(() => {
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
          const newIsDarkMode = document.documentElement.classList.contains('dark');
          if (newIsDarkMode !== isDarkMode) {
            setIsDarkMode(newIsDarkMode);
          }
        }
      });
    });

    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class'],
    });

    return () => observer.disconnect();
  }, [isDarkMode]);

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
    const hourNum = typeof hour.hour === 'string' ? parseInt(hour.hour, 10) : (hour.hour || index);
    const dataSource = hour.dataSource ?? 'unknown';
    
    return {
      hour: hourNum + 0.5,  // Center the bar in the middle of the hour period
      hourNum,
      hourLabel: `${hourNum.toString().padStart(2, '0')}:00`,  // Keep original for tooltip
      batterySocPercent: batterySocPercent,
      action: batteryAction,
      price: price,
      dataSource: dataSource,
      isActual: dataSource === 'actual',
      isPredicted: dataSource === 'predicted'
    };
  });
    
  const maxAction = Math.max(...chartData.map(d => Math.abs(d.action || 0)), 1);
  const maxPrice = Math.max(...chartData.map(h => h.price), 1);  // Already uses canonical buyPrice internally

  return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
      <div className="h-80">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData}>
            <CartesianGrid strokeDasharray="5 5" stroke={colors.grid} strokeOpacity={0.3} strokeWidth={0.5} />
            <XAxis 
              dataKey="hour" 
              interval={0}
              tick={{ fill: colors.text, fontSize: 12 }}
              axisLine={{ stroke: colors.text }}
              tickLine={{ stroke: colors.text }}
              tickFormatter={(value) => `${Math.floor(value).toString().padStart(2, '0')}:00`}
            />
            
            {/* Left Y-axis for Battery SOC (%) */}
            <YAxis 
              yAxisId="left" 
              stroke={colors.text}
              domain={[0, 100]} 
              tick={{ fontSize: 12 }}
              tickFormatter={(value) => `${value.toFixed(0)}%`}
              label={{ 
                value: 'Battery SOC (%)', 
                angle: -90, 
                position: 'insideLeft', 
                style: { textAnchor: 'middle', dominantBaseline: 'central' }
              }}
            />
            
            {/* Right Y-axis for Electricity Price (SEK/kWh) */}
            <YAxis 
              yAxisId="right" 
              orientation="right" 
              stroke={colors.text}
              domain={[0, Math.ceil(maxPrice * 1.2 * 10) / 10]}
              tick={{ fontSize: 11 }}
              tickFormatter={(value) => `${value.toFixed(2)}`}
              label={{ 
                value: 'Electricity Price (SEK/kWh)', 
                angle: 90, 
                position: 'insideRight', 
                style: { textAnchor: 'middle', dominantBaseline: 'central' }
              }}
            />
            
            {/* Third Y-axis for Battery Actions (kWh) */}
            <YAxis 
              yAxisId="action"
              orientation="right"
              stroke={colors.text}
              domain={[-maxAction * 1.2, maxAction * 1.2]}
              tick={{ fontSize: 12 }}
              tickFormatter={(value) => `${value.toFixed(1)}`}
              label={{ 
                value: 'Battery Action (kWh)', 
                angle: 90, 
                position: 'outside',
                offset: 40,
                style: { textAnchor: 'middle', dominantBaseline: 'central' }
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
                if (name === 'Electricity Price') return [`${Number(value).toFixed(2)} SEK/kWh`, 'Electricity Price'];
                if (name === 'Battery SOC') return [`${Number(value).toFixed(0)}%`, 'Battery SOC'];
                if (name === 'Battery Action') {
                  const actionValue = Number(value);
                  if (actionValue >= 0) {
                    return [`${actionValue.toFixed(2)} kWh`, 'Battery Charging'];
                  } else {
                    return [`${Math.abs(actionValue).toFixed(2)} kWh`, 'Battery Discharging'];
                  }
                }
                return [Number(value).toFixed(2), name];
              }}
              labelFormatter={(label, payload) => {
                if (payload && payload.length > 0) {
                  const data = payload[0].payload;
                  const startHour = data.hourNum;
                  const endHour = (startHour + 1) % 24;
                  return `${startHour.toString().padStart(2, '0')}:00 - ${endHour.toString().padStart(2, '0')}:00`;
                }
                return `Hour: ${label}`;
              }}
              labelStyle={{ color: colors.text }}
            />
            
            <ReferenceLine yAxisId="action" y={0} stroke={colors.grid} strokeDasharray="2 2" />
            
            {/* Hourly vertical grid lines */}
            {Array.from({ length: 25 }, (_, i) => (
              <ReferenceLine 
                key={`hour-${i}`}
                x={i} 
                yAxisId="left"
                stroke={colors.grid} 
                strokeOpacity={0.3} 
                strokeWidth={0.5}
                strokeDasharray="5 5" 
              />
            ))}
            
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
              stroke="#9CA3AF"
              strokeWidth={1.5}
              strokeDasharray="3 3"
              name="Electricity Price"
              dot={false}
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

      {/* Custom Legend */}
      <div className="flex flex-wrap justify-center gap-6 mt-1 text-sm">
        <div className="flex items-center">
          <div className="w-4 h-3 rounded mr-2" style={{ backgroundColor: '#16a34a' }}></div>
          <span className="text-gray-700 dark:text-gray-300">Battery SOC</span>
        </div>
        <div className="flex items-center">
          <div className="w-4 h-3 rounded mr-2" style={{ backgroundColor: '#16a34a' }}></div>
          <span className="text-gray-700 dark:text-gray-300">Battery Charging</span>
        </div>
        <div className="flex items-center">
          <div className="w-4 h-3 rounded mr-2" style={{ backgroundColor: '#dc2626' }}></div>
          <span className="text-gray-700 dark:text-gray-300">Battery Discharging</span>
        </div>
        <div className="flex items-center">
          <div className="w-4 h-1" style={{ backgroundColor: '#9CA3AF', borderStyle: 'dashed', borderWidth: '1px 0' }}></div>
          <span className="text-gray-700 dark:text-gray-300 ml-2">Electricity Price</span>
        </div>
      </div>
    </div>
  );
};