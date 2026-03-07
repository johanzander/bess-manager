import React, { useState, useEffect } from 'react';
import { XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, ReferenceArea, ComposedChart, Area, Line } from 'recharts';
import { HourlyData } from '../types';
import { periodToTimeString, periodToTimeRange } from '../utils/timeUtils';
import { DataResolution } from '../hooks/useUserPreferences';

interface BatteryLevelChartProps {
  hourlyData: HourlyData[];
  tomorrowData?: HourlyData[] | null;
  settings: any; // Adjust type as needed
  resolution: DataResolution;
}

export const BatteryLevelChart: React.FC<BatteryLevelChartProps> = ({ hourlyData, tomorrowData, resolution }) => {
  // Reactive dark mode detection — uses prefers-color-scheme to match Tailwind's 'media' strategy
  const [isDarkMode, setIsDarkMode] = useState(
    window.matchMedia('(prefers-color-scheme: dark)').matches
  );

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e: MediaQueryListEvent) => setIsDarkMode(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

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
    const rawSoc = getValue(hour.batterySocEnd);
    const isActual = hour.dataSource === 'actual';
    // Treat zero SOC on predicted periods as missing data to avoid flat 0% lines
    const batterySocPercent = (rawSoc === 0 && !isActual) ? null : rawSoc;
    const rawPrice = getValue(hour.buyPrice);
    const price = rawPrice || null; // Treat zero/missing price as null for visual gaps
    const periodNum = hour.period ?? index;
    if (hour.dataSource === undefined) {
      throw new Error(`MISSING DATA: dataSource is required but missing at index ${index}`);
    }
    const dataSource = hour.dataSource;

    // Period END positioning: matches EnergyFlowChart convention
    let xPosition: number;
    if (resolution === 'quarter-hourly') {
      xPosition = (periodNum + 1) / 4;
    } else {
      xPosition = periodNum + 1;
    }

    return {
      hour: xPosition,
      periodNum,
      hourLabel: periodToTimeString(periodNum, resolution),
      batterySocPercent: batterySocPercent,
      action: batteryAction,
      charging: batteryAction > 0 ? batteryAction : 0,
      discharging: batteryAction < 0 ? batteryAction : 0,
      price: price,
      dataSource: dataSource,
      isActual: dataSource === 'actual',
      isPredicted: dataSource === 'predicted',
      isTomorrow: false,
      // Include FormattedValue objects for tooltip
      batterySocEndFormatted: hour.batterySocEnd,
      batteryActionFormatted: hour.batteryAction,
      buyPriceFormatted: hour.buyPrice
    };
  });

  // Zero anchor at x=0: gives stepBefore a left edge so bars render from 0→1 for period 0
  chartData.unshift({ hour: 0, periodNum: -1, batterySocPercent: chartData[0]?.batterySocPercent ?? 0, action: 0, charging: 0, discharging: 0, price: chartData[0]?.price ?? 0, dataSource: 'actual', isActual: true, isPredicted: false, isTomorrow: false });

  // Append tomorrow's data with hour offset 24+
  const hasTomorrowData = tomorrowData && tomorrowData.length > 0;
  if (hasTomorrowData) {
    for (const [idx, hour] of tomorrowData.entries()) {
      if (hour.batteryAction === undefined) {
        console.warn(`Missing key: batteryAction in tomorrow data at index ${idx}`);
        continue;
      }
      const batteryAction = getValue(hour.batteryAction);
      const rawSocTmrw = getValue(hour.batterySocEnd);
      const batterySocPercent = rawSocTmrw === 0 ? null : rawSocTmrw;
      const rawPriceTmrw = getValue(hour.buyPrice);
      const price = rawPriceTmrw || null;
      // Normalize period numbers: API may return 96-191 (continuation from today) or 0-95
      const rawPeriodNum = hour.period ?? idx;
      const tomorrowPeriodsPerDay = resolution === 'quarter-hourly' ? 96 : 24;
      const periodNum = rawPeriodNum >= tomorrowPeriodsPerDay ? rawPeriodNum - tomorrowPeriodsPerDay : rawPeriodNum;
      const dataSource = hour.dataSource ?? 'predicted';

      let xPosition: number;
      if (resolution === 'quarter-hourly') {
        xPosition = 24 + (periodNum + 1) / 4;
      } else {
        xPosition = 24 + periodNum + 1;
      }

      chartData.push({
        hour: xPosition,
        periodNum,
        hourLabel: periodToTimeString(periodNum, resolution),
        batterySocPercent,
        action: batteryAction,
        charging: batteryAction > 0 ? batteryAction : 0,
        discharging: batteryAction < 0 ? batteryAction : 0,
        price,
        dataSource,
        isActual: false,
        isPredicted: true,
        isTomorrow: true,
        batterySocEndFormatted: hour.batterySocEnd,
        batteryActionFormatted: hour.batteryAction,
        buyPriceFormatted: hour.buyPrice
      });
    }
  }

  // Period 23 is at x=24 (period END), so today-only maxHour is naturally 24
  const maxHourValue = hasTomorrowData
    ? Math.ceil(Math.max(...chartData.map(d => d.hour)))
    : 24;
  const xAxisTicks = Array.from({ length: maxHourValue + 1 }, (_, i) => i);

  // Find predicted hours range for today (same logic as EnergyFlowChart)
  const firstPredictedIdx = chartData.findIndex(d => !d.isActual && !d.isTomorrow);
  const lastTodayIdx = chartData.findIndex(d => d.isTomorrow);
  const firstPredictedHour = firstPredictedIdx > -1 ? chartData[firstPredictedIdx].hour : null;
  const lastTodayHour = lastTodayIdx > -1 ? chartData[lastTodayIdx - 1]?.hour : maxHourValue;

  const maxAction = Math.max(...chartData.map(d => Math.abs(d.action || 0)), 1);
  const maxPrice = Math.max(...chartData.map(h => h.price ?? 0), 1);

  return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
      <div className="h-80">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
            <CartesianGrid strokeDasharray="5 5" stroke={colors.grid} strokeOpacity={isDarkMode ? 0.15 : 0.3} strokeWidth={0.5} />
            <XAxis
              dataKey="hour"
              interval={0}
              tick={{ fill: colors.text, fontSize: 12 }}
              axisLine={{ stroke: colors.text }}
              tickLine={{ stroke: colors.text }}
              ticks={xAxisTicks}
              tickFormatter={(value: number) => {
                return `${(Math.floor(value) % 24).toString().padStart(2, '0')}`;
              }}
            />
            
            {/* Left Y-axis for Battery SOC (%) */}
            <YAxis
              yAxisId="left"
              width={60}
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
              width={60}
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
              width={60}
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
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const data = payload[0].payload;
                if (data.periodNum === -1) return null;
                const timeRange = periodToTimeRange(data.periodNum, resolution);
                const label = data.isTomorrow ? `Tomorrow ${timeRange}` : timeRange;
                return (
                  <div style={{ backgroundColor: colors.tooltip, border: `1px solid ${colors.tooltipBorder}`, borderRadius: '8px', padding: '10px', color: colors.text }}>
                    <p style={{ fontWeight: 'bold', marginBottom: 4 }}>{label}</p>
                    <p style={{ color: '#16a34a' }}>Battery SOC : {data.batterySocEndFormatted?.text ?? `${data.batterySocPercent} %`}</p>
                    <p style={{ color: '#9CA3AF' }}>Electricity Price : {data.buyPriceFormatted?.text ?? `${data.price}`}</p>
                    {data.action > 0 && <p style={{ color: '#16a34a' }}>Battery Charging : {(data.batteryActionFormatted?.text ?? `${data.action}`).replace(/^-0(\b|\.)/, '0$1')}</p>}
                    {data.action < 0 && <p style={{ color: '#dc2626' }}>Battery Discharging : {(data.batteryActionFormatted?.text ?? `${data.action}`).replace(/^-0(\b|\.)/, '0$1')}</p>}
                  </div>
                );
              }}
            />
            
            <ReferenceLine yAxisId="action" y={0} stroke={colors.grid} strokeDasharray="2 2" />

            {/* Hourly vertical grid lines - extend for tomorrow data */}
            {Array.from({ length: maxHourValue + 1 }, (_, i) => (
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

            {/* Overlay for predicted hours (today only) */}
            {firstPredictedHour !== null && (
              <ReferenceArea
                yAxisId="left"
                x1={firstPredictedHour}
                x2={lastTodayHour}
                fill={isDarkMode ? 'rgba(120,120,120,0.12)' : 'rgba(120,120,120,0.10)'}
                ifOverflow="hidden"
              />
            )}

            {/* Grey background for tomorrow's data */}
            {hasTomorrowData && (
              <ReferenceArea
                yAxisId="left"
                x1={24}
                x2={maxHourValue}
                fill={isDarkMode ? 'rgba(120,120,120,0.12)' : 'rgba(120,120,120,0.08)'}
              />
            )}

            {/* Today/tomorrow divider */}
            {hasTomorrowData && (
              <ReferenceLine
                x={24}
                yAxisId="left"
                stroke="#9CA3AF"
                strokeWidth={1}
                strokeDasharray="0"
                label={{ value: 'Tomorrow', position: 'insideTopRight', fontSize: 11, fill: '#9CA3AF' }}
              />
            )}

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
              type="stepAfter"
              dataKey="price"
              stroke="#9CA3AF"
              strokeWidth={1.5}
              strokeDasharray="3 3"
              name="Electricity Price"
              dot={false}
              connectNulls={false}
            />
            
            <Area
              yAxisId="action"
              type="stepBefore"
              dataKey="charging"
              stroke="#16a34a"
              strokeWidth={1}
              fill="#16a34a"
              fillOpacity={0.7}
              name="Battery Charging"
              dot={false}
              connectNulls={false}
            />
            <Area
              yAxisId="action"
              type="stepBefore"
              dataKey="discharging"
              stroke="#dc2626"
              strokeWidth={1}
              fill="#dc2626"
              fillOpacity={0.7}
              name="Battery Discharging"
              dot={false}
              connectNulls={false}
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
        <div className="flex items-center text-xs text-gray-600 dark:text-gray-400 ml-4">
          <div className="flex items-center mr-3">
            <div className="w-4 h-3 rounded mr-1 border border-gray-400" style={{ backgroundColor: 'transparent' }}></div>
            <span>Actual hours</span>
          </div>
          <div className="flex items-center mr-3">
            <div className="w-4 h-3 rounded mr-1" style={{ background: isDarkMode ? 'rgba(120,120,120,0.25)' : 'rgba(120,120,120,0.15)' }}></div>
            <span>Predicted hours</span>
          </div>
        </div>
      </div>
    </div>
  );
};