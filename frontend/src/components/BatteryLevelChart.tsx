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

  // Extract values from FormattedValue objects or fallback to raw numbers
  const getValue = (field: any) => {
    if (typeof field === 'object' && field?.value !== undefined) {
      return field.value;
    }
    return field || 0;
  };

  // Transform daily view data to chart format
  // Helper function to get currency unit from price data
  const getCurrencyUnit = () => {
    const firstPriceData = hourlyData.find(hour => hour.buyPrice?.unit);
    return firstPriceData?.buyPrice?.unit || '???';
  };

  // Get the actual currency unit for the chart label
  const currencyUnit = getCurrencyUnit();

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

    if (hour.batteryAction === undefined) {
      throw new Error(`MISSING DATA: batteryAction is required but missing at index ${index}`);
    }
    const batteryAction = getValue(hour.batteryAction);
    const batterySocPercent = getValue(hour.batterySocEnd); // Extract from FormattedValue
    const price = getValue(hour.buyPrice); // Extract from FormattedValue
    const hourNum = typeof hour.hour === 'string' ? parseInt(hour.hour, 10) : (hour.hour || index);
    if (hour.dataSource === undefined) {
      throw new Error(`MISSING DATA: dataSource is required but missing at index ${index}`);
    }
    const dataSource = hour.dataSource;
    
    return {
      hour: hourNum + 0.5,  // Center the bar in the middle of the hour period
      hourNum,
      hourLabel: `${hourNum.toString().padStart(2, '0')}:00`,  // Keep original for tooltip
      batterySocPercent: batterySocPercent,
      action: batteryAction,
      price: price,
      dataSource: dataSource,
      isActual: dataSource === 'actual',
      isPredicted: dataSource === 'predicted',
      // Include FormattedValue objects for tooltip
      batterySocEndFormatted: hour.batterySocEnd,
      batteryActionFormatted: hour.batteryAction,
      buyPriceFormatted: hour.buyPrice
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
              tickFormatter={(value) => `${Math.round(value)}%`}
              label={{ 
                value: 'Battery SOC (%)', 
                angle: -90, 
                position: 'insideLeft', 
                style: { textAnchor: 'middle', dominantBaseline: 'central' }
              }}
            />
            
            {/* Right Y-axis for Electricity Price */}
            <YAxis 
              yAxisId="right" 
              orientation="right" 
              stroke={colors.text}
              domain={[0, Math.ceil(maxPrice * 1.2 * 10) / 10]}
              tick={{ fontSize: 11 }}
              tickFormatter={(value) => value.toLocaleString('sv-SE', {minimumFractionDigits: 2, maximumFractionDigits: 2})}
              label={{ 
                value: `Electricity Price (${currencyUnit}/kWh)`, 
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
              tickFormatter={(value) => value.toLocaleString('sv-SE', {minimumFractionDigits: 1, maximumFractionDigits: 1})}
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
              formatter={(value, name, props) => {
                const payload = props?.payload;
                if (name === 'Electricity Price') return [payload?.buyPriceFormatted?.text || 'N/A', 'Electricity Price'];
                if (name === 'Battery SOC') return [payload?.batterySocEndFormatted?.text || 'N/A', 'Battery SOC'];
                if (name === 'Battery Action') {
                  const actionValue = Number(value);
                  const formattedText = payload?.batteryActionFormatted?.text || 'N/A';
                  if (actionValue >= 0) {
                    return [formattedText, 'Battery Charging'];
                  } else {
                    return [formattedText, 'Battery Discharging'];
                  }
                }
                return ['N/A', name];
              }}
              labelFormatter={(label) => {
                // label should be the hour value from the data
                const hourNum = Math.floor(Number(label));
                const endHour = (hourNum + 1) % 24;
                return `${hourNum.toString().padStart(2, '0')}:00 - ${endHour.toString().padStart(2, '0')}:00`;
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