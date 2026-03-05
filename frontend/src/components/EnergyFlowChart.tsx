import React, { useState, useEffect } from 'react';
import { ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, ReferenceArea } from 'recharts';
import { HourlyData } from '../types';
import { periodToTimeRange } from '../utils/timeUtils';
import { DataResolution } from '../hooks/useUserPreferences';


const CustomTooltip = ({ active, payload, label, resolution }: any) => {
  if (active && payload && payload.length) {
    const data = payload[0].payload;
    if (label === 0) {
      // Skip tooltip for the empty starting point
      return null;
    }

    // Get time range from period number stored in data
    const periodNum = data.periodNum;
    const isTomorrow = data.isTomorrow;
    // For tomorrow data, use the period number relative to tomorrow
    // In quarter-hourly mode, periods are offset by 96; in hourly, by 24
    const tomorrowOffset = resolution === 'quarter-hourly' ? 96 : 24;
    const displayPeriodNum = isTomorrow ? periodNum - tomorrowOffset : periodNum;
    const timeRange = periodToTimeRange(displayPeriodNum, resolution);
    const dayLabel = isTomorrow ? 'Tomorrow' : '';

    // Map chart dataKeys to their corresponding FormattedValue fields
    const getFormattedText = (dataKey: string): string => {
      switch (dataKey) {
        case 'solar':
          return data.solarProductionFormatted?.text || 'N/A';
        case 'home':
          return data.homeConsumptionFormatted?.text || 'N/A';
        case 'batteryOut':
          return data.batteryDischargedFormatted?.text || 'N/A';
        case 'batteryIn':
          return data.batteryChargedFormatted?.text || 'N/A';
        case 'gridIn':
          return data.gridImportedFormatted?.text || 'N/A';
        case 'gridOut':
          return data.gridExportedFormatted?.text || 'N/A';
        default:
          return 'N/A';
      }
    };

    // Filter out entries with zero values and price (since we handle price separately)
    // Also separate into sources and consumption
    const energyEntries = payload.filter((entry: any) =>
      entry.dataKey !== 'price' && Math.abs(entry.value) > 0
    );
    const sources = energyEntries.filter((entry: any) => entry.value > 0);
    const consumption = energyEntries.filter((entry: any) => entry.value < 0);

    if (energyEntries.length === 0) {
      return null; // Don't show tooltip if all energy values are zero
    }

    const statusLabel = data.isActual ? '(Actual)' : '(Predicted)';

    return (
      <div className="bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg p-3 shadow-lg">
        <p className="font-semibold mb-2 text-gray-900 dark:text-white">
          {dayLabel ? `${dayLabel} ` : ''}Hour {timeRange} {statusLabel}
        </p>
        <div className="space-y-1 text-sm">
          {sources.length > 0 && (
            <>
              <p className="font-medium text-gray-700 dark:text-gray-300">Energy Sources:</p>
              {sources.map((entry: any, index: number) => (
                <p key={index} style={{ color: entry.color }} className="ml-2">
                  {entry.name}: {getFormattedText(entry.dataKey)}
                </p>
              ))}
            </>
          )}
          {consumption.length > 0 && (
            <>
              <p className="font-medium text-gray-700 dark:text-gray-300 mt-2">Energy Consumption:</p>
              {consumption.map((entry: any, index: number) => (
                <p key={index} style={{ color: entry.color }} className="ml-2">
                  {entry.name}: {getFormattedText(entry.dataKey)}
                </p>
              ))}
            </>
          )}
          {data.buyPriceFormatted && (
            <p className="text-gray-600 dark:text-gray-400 mt-2">
              Price: {data.buyPriceFormatted.text}
            </p>
          )}
        </div>
      </div>
    );
  }
  return null;
};export const EnergyFlowChart: React.FC<{
  dailyViewData: HourlyData[];
  tomorrowData?: HourlyData[] | null;
  currentHour: number;
  resolution: DataResolution;
}> = ({ dailyViewData, tomorrowData, resolution }) => {
  
  // Helper function to get currency unit from price data
  const getCurrencyUnit = () => {
    const firstPriceData = dailyViewData.find(hour => hour.buyPrice?.unit);
    return firstPriceData?.buyPrice?.unit || '???';
  };

  // Get the actual currency unit for the chart label
  const currencyUnit = getCurrencyUnit();

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
    solar: '#fbbf24',        // Yellow
    battery: '#10b981',      // Green  
    grid: '#3b82f6',         // Blue (for both import and export)
    home: '#ef4444',         // Red
    gridExport: '#3b82f6',   // Same blue as grid import
    text: isDarkMode ? '#d1d5db' : '#374151',
    gridLines: isDarkMode ? '#374151' : '#e5e7eb',
  };

  // Extract values from FormattedValue objects or fallback to raw numbers
  const getValue = (field: any) => {
    if (typeof field === 'object' && field?.value !== undefined) {
      return field.value;
    }
    return field || 0;
  };

  // Shift timeline - data for hour 0 (00:00-01:00) should appear at position 1
  // Support both hourly (24 periods) and quarterly (96 periods) data
  const numDataPoints = dailyViewData?.length || 24;
  const chartData: any[] = Array.from({ length: numDataPoints + 1 }, (_, index) => {
    if (index === 0) {
      // Add empty data point at the start (before 00:00)
      return {
        hour: 0,
        periodNum: 0,
        solar: 0,
        batteryOut: 0,
        gridIn: 0,
        home: 0,
        batteryIn: 0,
        gridOut: 0,
        isActual: true,
        isTomorrow: false,
        price: null,
      };
    }
    const dataIndex = index - 1;
    const dailyViewHour = dailyViewData?.[dataIndex];
    const isActual = dailyViewHour?.dataSource === 'actual';
    const periodNum = dataIndex;

    // Map unified API data format to chart format
    const solarProduction = getValue(dailyViewHour?.solarProduction);
    const homeConsumption = getValue(dailyViewHour?.homeConsumption);
    const batteryCharged = getValue(dailyViewHour?.batteryCharged) || 0;
    const batteryDischarged = getValue(dailyViewHour?.batteryDischarged) || 0;
    const gridImported = getValue(dailyViewHour?.gridImported) || 0;
    const gridExported = getValue(dailyViewHour?.gridExported) || 0;

    // Calculate x-axis position
    const hourPosition = resolution === 'quarter-hourly' ? (periodNum / 4) + 1 : index;

    return {
      hour: hourPosition,
      periodNum,
      solar: solarProduction,
      batteryOut: batteryDischarged,
      gridIn: gridImported,
      home: -homeConsumption,
      batteryIn: batteryCharged > 0 ? -batteryCharged : 0,
      gridOut: gridExported > 0 ? -gridExported : 0,
      isActual,
      isTomorrow: false,
      price: getValue(dailyViewHour?.buyPrice) || null,
      // Include FormattedValue objects for tooltip
      solarProductionFormatted: dailyViewHour?.solarProduction,
      homeConsumptionFormatted: dailyViewHour?.homeConsumption,
      batteryChargedFormatted: dailyViewHour?.batteryCharged,
      batteryDischargedFormatted: dailyViewHour?.batteryDischarged,
      gridImportedFormatted: dailyViewHour?.gridImported,
      gridExportedFormatted: dailyViewHour?.gridExported,
      buyPriceFormatted: dailyViewHour?.buyPrice,
    };
  });

  // Append tomorrow's data with hour offset 24+
  const hasTomorrowData = tomorrowData && tomorrowData.length > 0;
  if (hasTomorrowData) {
    for (const [idx, hourData] of tomorrowData.entries()) {
      const periodNum = hourData.period ?? idx;
      const hourPosition = resolution === 'quarter-hourly'
        ? 24 + (periodNum / 4) + (1 / 4)
        : 24 + periodNum + 1;

      const solarProduction = getValue(hourData?.solarProduction);
      const homeConsumption = getValue(hourData?.homeConsumption);
      const batteryCharged = getValue(hourData?.batteryCharged) || 0;
      const batteryDischarged = getValue(hourData?.batteryDischarged) || 0;
      const gridImported = getValue(hourData?.gridImported) || 0;
      const gridExported = getValue(hourData?.gridExported) || 0;

      // Store period num with offset so tooltip can detect tomorrow
      const tomorrowPeriodOffset = resolution === 'quarter-hourly' ? 96 : 24;
      chartData.push({
        hour: hourPosition,
        periodNum: tomorrowPeriodOffset + periodNum,
        solar: solarProduction,
        batteryOut: batteryDischarged,
        gridIn: gridImported,
        home: -homeConsumption,
        batteryIn: batteryCharged > 0 ? -batteryCharged : 0,
        gridOut: gridExported > 0 ? -gridExported : 0,
        isActual: false,
        isTomorrow: true,
        price: getValue(hourData?.buyPrice) || null,
        // Include FormattedValue objects for tooltip
        solarProductionFormatted: hourData?.solarProduction,
        homeConsumptionFormatted: hourData?.homeConsumption,
        batteryChargedFormatted: hourData?.batteryCharged,
        batteryDischargedFormatted: hourData?.batteryDischarged,
        gridImportedFormatted: hourData?.gridImported,
        gridExportedFormatted: hourData?.gridExported,
        buyPriceFormatted: hourData?.buyPrice,
      } as any);
    }
  }

  // Compute max hour for X-axis domain
  const maxHour = hasTomorrowData
    ? Math.ceil(Math.max(...chartData.map(d => d.hour)))
    : (resolution === 'quarter-hourly' ? 24.25 : 24);

  // Explicit tick positions at whole hours
  const xAxisTicks = Array.from({ length: Math.ceil(maxHour) + 1 }, (_, i) => i);

  // Find predicted hours range for shading
  const firstPredictedIdx = chartData.findIndex(d => !d.isActual && !d.isTomorrow);
  const lastTodayIdx = chartData.findIndex(d => d.isTomorrow);
  const firstPredictedHour = firstPredictedIdx > -1 ? chartData[firstPredictedIdx].hour : null;
  const lastTodayHour = lastTodayIdx > -1 ? chartData[lastTodayIdx - 1]?.hour : maxHour;

  return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
      <div style={{ width: '100%', height: '400px' }}>
        <ResponsiveContainer>
          <ComposedChart
            data={chartData}
            margin={{ top: 20, right: 30, left: 20, bottom: 60 }}
          >
            <defs>
              {/* Solid colors for actual data */}
              <linearGradient id="solarActualGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colors.solar} stopOpacity="0.8"/>
                <stop offset="100%" stopColor={colors.solar} stopOpacity="0.1"/>
              </linearGradient>
              <linearGradient id="batteryActualGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colors.battery} stopOpacity="0.8"/>
                <stop offset="100%" stopColor={colors.battery} stopOpacity="0.1"/>
              </linearGradient>
              <linearGradient id="gridActualGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colors.grid} stopOpacity="0.8"/>
                <stop offset="100%" stopColor={colors.grid} stopOpacity="0.1"/>
              </linearGradient>
              <linearGradient id="homeActualGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colors.home} stopOpacity="0.8"/>
                <stop offset="100%" stopColor={colors.home} stopOpacity="0.1"/>
              </linearGradient>
              <linearGradient id="gridExportActualGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colors.gridExport} stopOpacity="0.8"/>
                <stop offset="100%" stopColor={colors.gridExport} stopOpacity="0.1"/>
              </linearGradient>
              <linearGradient id="batteryChargeActualGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colors.battery} stopOpacity="0.8"/>
                <stop offset="100%" stopColor={colors.battery} stopOpacity="0.1"/>
              </linearGradient>
              
              {/* Reduced opacity colors for predicted data */}
              <linearGradient id="solarPredictedGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colors.solar} stopOpacity="0.3"/>
                <stop offset="100%" stopColor={colors.solar} stopOpacity="0.05"/>
              </linearGradient>
              <linearGradient id="batteryPredictedGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colors.battery} stopOpacity="0.3"/>
                <stop offset="100%" stopColor={colors.battery} stopOpacity="0.05"/>
              </linearGradient>
              <linearGradient id="gridPredictedGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colors.grid} stopOpacity="0.3"/>
                <stop offset="100%" stopColor={colors.grid} stopOpacity="0.05"/>
              </linearGradient>
              <linearGradient id="homePredictedGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colors.home} stopOpacity="0.3"/>
                <stop offset="100%" stopColor={colors.home} stopOpacity="0.05"/>
              </linearGradient>
              <linearGradient id="gridExportPredictedGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colors.gridExport} stopOpacity="0.3"/>
                <stop offset="100%" stopColor={colors.gridExport} stopOpacity="0.05"/>
              </linearGradient>
              <linearGradient id="batteryChargePredictedGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colors.battery} stopOpacity="0.3"/>
                <stop offset="100%" stopColor={colors.battery} stopOpacity="0.05"/>
              </linearGradient>
            </defs>
            
            <CartesianGrid strokeDasharray="5 5" stroke={colors.gridLines} strokeOpacity={0.3} strokeWidth={0.5} />
            <XAxis
              dataKey="hour"
              stroke={colors.text}
              tick={{ fontSize: 12 }}
              domain={[0, maxHour]}
              ticks={xAxisTicks}
              interval={0}
              label={{ value: 'Hour of Day', position: 'insideBottom', offset: -10 }}
              tickFormatter={(hour: number) => {
                return (Math.floor(hour) % 24).toString().padStart(2, '0');
              }}
            />
            <YAxis 
              stroke={colors.text}
              tick={{ fontSize: 12 }}
              label={{ 
                value: 'Energy (kWh)', 
                angle: -90, 
                position: 'insideLeft', 
                style: { textAnchor: 'middle', dominantBaseline: 'central' }
              }}
            />
            <YAxis 
              yAxisId="price"
              orientation="right"
              stroke={colors.text}
              tick={{ fontSize: 11 }}
              tickFormatter={(value) => value.toLocaleString('sv-SE', {minimumFractionDigits: 2, maximumFractionDigits: 2})}
              label={{ 
                value: `Electricity Price (${currencyUnit}/kWh)`, 
                angle: 90, 
                position: 'insideRight',
                style: { textAnchor: 'middle', dominantBaseline: 'central' }
              }}
            />
            <Tooltip content={<CustomTooltip resolution={resolution} />} />
            
            {/* Reference line at zero to separate sources from consumption */}
            <ReferenceLine y={0} stroke={colors.text} strokeWidth={2} />

            {/* Midnight separator when tomorrow data exists */}
            {hasTomorrowData && (
              <ReferenceLine
                x={24}
                stroke={colors.text}
                strokeDasharray="4 4"
                strokeWidth={1.5}
                label={{ value: 'Tomorrow', position: 'top', fill: colors.text, fontSize: 11 }}
              />
            )}
            
            {/* ENERGY SOURCES - Single series, style by isActual */}
            <Area
              type="monotone"
              dataKey="solar"
              stackId="sources"
              stroke={colors.solar}
              fill="url(#solarActualGradient)"
              strokeWidth={2}
              name="Solar Production"
              isAnimationActive={false}
              dot={false}
              connectNulls
            />
            <Area
              type="monotone"
              dataKey="batteryOut"
              stackId="sources"
              stroke={colors.battery}
              fill="url(#batteryActualGradient)"
              strokeWidth={2}
              name="Battery Discharge"
              isAnimationActive={false}
              dot={false}
              connectNulls
            />
            <Area
              type="monotone"
              dataKey="gridIn"
              stackId="sources"
              stroke={colors.grid}
              fill="url(#gridActualGradient)"
              strokeWidth={2}
              name="Grid Import"
              isAnimationActive={false}
              dot={false}
              connectNulls
            />
            {/* ENERGY CONSUMPTION - Single series, style by isActual */}
            <Area
              type="monotone"
              dataKey="home"
              stackId="consumption"
              stroke={colors.home}
              fill="url(#homeActualGradient)"
              strokeWidth={2}
              name="Home Load"
              isAnimationActive={false}
              dot={false}
              connectNulls
            />
            <Area
              type="monotone"
              dataKey="batteryIn"
              stackId="consumption"
              stroke={colors.battery}
              fill="url(#batteryChargeActualGradient)"
              strokeWidth={2}
              name="Battery Charge"
              isAnimationActive={false}
              dot={false}
              connectNulls
            />
            <Area
              type="monotone"
              dataKey="gridOut"
              stackId="consumption"
              stroke={colors.gridExport}
              fill="url(#gridExportActualGradient)"
              strokeWidth={2}
              name="Grid Export"
              isAnimationActive={false}
              dot={false}
              connectNulls
            />
            {/* Overlay for predicted hours (today only) */}
            {firstPredictedHour !== null && (
              <ReferenceArea
                x1={firstPredictedHour}
                x2={lastTodayHour}
                fill={isDarkMode ? 'rgba(120,120,120,0.12)' : 'rgba(120,120,120,0.10)'}
                ifOverflow="hidden"
              />
            )}
            
            {/* Price line on secondary Y-axis */}
            <Line
              type="stepAfter"
              dataKey="price"
              yAxisId="price"
              stroke="#9CA3AF"
              strokeWidth={1.5}
              dot={false}
              strokeDasharray="3 3"
              name="Electricity Price"
              connectNulls={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Custom Legend - showing main categories and actual/predicted distinction */}
      <div className="flex flex-wrap justify-center gap-6 mt-1 text-sm">
        <div className="flex items-center">
          <div className="w-4 h-3 rounded mr-2" style={{ backgroundColor: colors.solar }}></div>
          <span className="text-gray-700 dark:text-gray-300">Solar Production</span>
        </div>
        <div className="flex items-center">
          <div className="w-4 h-3 rounded mr-2" style={{ backgroundColor: colors.battery }}></div>
          <span className="text-gray-700 dark:text-gray-300">Battery Charge / Discharge</span>
        </div>
        <div className="flex items-center">
          <div className="w-4 h-3 rounded mr-2" style={{ backgroundColor: colors.grid }}></div>
          <span className="text-gray-700 dark:text-gray-300">Grid Import / Export</span>
        </div>
        <div className="flex items-center">
          <div className="w-4 h-3 rounded mr-2" style={{ backgroundColor: colors.home }}></div>
          <span className="text-gray-700 dark:text-gray-300">Home Load</span>
        </div>
        <div className="flex items-center">
          <div className="w-4 h-1" style={{ backgroundColor: '#9CA3AF', borderStyle: 'dashed', borderWidth: '1px 0' }}></div>
          <span className="text-gray-700 dark:text-gray-300 ml-2">Electricity Price</span>
        </div>
        <div className="flex items-center text-xs text-gray-600 dark:text-gray-400 ml-4">
          <div className="flex items-center mr-3">
            <div className="w-4 h-3 rounded mr-1 border border-gray-400" style={{ backgroundColor: 'transparent', borderStyle: 'solid', borderWidth: 1 }}></div>
            <span>Actual hours</span>
          </div>
          <div className="flex items-center mr-3">
            <div className="w-4 h-3 rounded mr-1" style={{ background: isDarkMode ? 'rgba(120,120,120,0.12)' : 'rgba(120,120,120,0.10)' }}></div>
            <span>Predicted hours</span>
          </div>
        </div>
      </div>
    </div>
  );
};