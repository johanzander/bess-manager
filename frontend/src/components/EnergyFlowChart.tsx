import React, { useState, useEffect } from 'react';
import { ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import { HourlyData } from '../types';

interface ChartDataPoint {
  hour: number;
  // Actual data series (full opacity)
  solarActual: number;
  batteryOutActual: number;
  gridInActual: number;
  homeActual: number;
  batteryInActual: number;
  gridOutActual: number;
  // Predicted data series (reduced opacity)
  solarPredicted: number;
  batteryOutPredicted: number;
  gridInPredicted: number;
  homePredicted: number;
  batteryInPredicted: number;
  gridOutPredicted: number;
  // Price data
  price: number;
  // Meta data
  isActual: boolean;
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    const data = payload[0].payload;
    if (label === 0) {
      // Skip tooltip for the empty starting point
      return null;
    }
    
    const startHour = (label - 1) % 24; // Convert timeline position back to actual hour
    const endHour = label % 24;
    const timeRange = `${startHour.toString().padStart(2, '0')}:00-${endHour.toString().padStart(2, '0')}:00`;
    
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
    
    return (
      <div className="bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg p-3 shadow-lg">
        <p className="font-semibold mb-2 text-gray-900 dark:text-white">
          Hour {timeRange} {data.isActual ? '(Actual)' : '(Predicted)'}
        </p>
        <div className="space-y-1 text-sm">
          {sources.length > 0 && (
            <>
              <p className="font-medium text-gray-700 dark:text-gray-300">Energy Sources:</p>
              {sources.map((entry: any, index: number) => (
                <p key={index} style={{ color: entry.color }} className="ml-2">
                  {entry.name}: {Math.abs(entry.value).toFixed(2)} kWh
                </p>
              ))}
            </>
          )}
          {consumption.length > 0 && (
            <>
              <p className="font-medium text-gray-700 dark:text-gray-300 mt-2">Energy Consumption:</p>
              {consumption.map((entry: any, index: number) => (
                <p key={index} style={{ color: entry.color }} className="ml-2">
                  {entry.name}: {Math.abs(entry.value).toFixed(2)} kWh
                </p>
              ))}
            </>
          )}
          {data.price > 0 && (
            <p className="text-gray-600 dark:text-gray-400 mt-2">
              Price: {data.price.toFixed(2)} SEK/kWh
            </p>
          )}
        </div>
      </div>
    );
  }
  return null;
};export const EnergyFlowChart: React.FC<{
  dailyViewData: HourlyData[];
  currentHour: number;
}> = ({ dailyViewData }) => {
  
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

  // Shift timeline - data for hour 0 (00:00-01:00) should appear at position 1
  const chartData: ChartDataPoint[] = Array.from({ length: 25 }, (_, index) => {
    if (index === 0) {
      // Add empty data point at the start (before 00:00)
      return {
        hour: 0,
        solarActual: 0,
        batteryOutActual: 0,
        gridInActual: 0,
        homeActual: 0,
        batteryInActual: 0,
        gridOutActual: 0,
        solarPredicted: 0,
        batteryOutPredicted: 0,
        gridInPredicted: 0,
        homePredicted: 0,
        batteryInPredicted: 0,
        gridOutPredicted: 0,
        isActual: true,
        price: 0,
      };
    }
    
    const dataHour = index - 1; // Shift: index 1 = hour 0, index 2 = hour 1, etc.
    const dailyViewHour = dailyViewData?.find(h => {
      const hourValue = typeof h.hour === 'string' ? parseInt(h.hour, 10) : h.hour;
      return hourValue === dataHour;
    });
    const isActual = dailyViewHour?.dataSource === 'actual';
    
    return {
      hour: index, // Timeline position (1, 2, 3, ... 24)
      // Actual data (full opacity)
      solarActual: isActual ? (dailyViewHour?.solarProduction || 0) : 0,
      batteryOutActual: isActual ? (dailyViewHour?.batteryDischarged || 0) : 0,
      gridInActual: isActual ? (dailyViewHour?.gridImported || 0) : 0,
      homeActual: isActual ? -(dailyViewHour?.homeConsumption || 0) : 0,
      batteryInActual: isActual ? -(dailyViewHour?.batteryCharged || 0) : 0,
      gridOutActual: isActual ? -(dailyViewHour?.gridExported || 0) : 0,
      
      // Predicted data (reduced opacity)
      solarPredicted: !isActual ? (dailyViewHour?.solarProduction || 0) : 0,
      batteryOutPredicted: !isActual ? (dailyViewHour?.batteryDischarged || 0) : 0,
      gridInPredicted: !isActual ? (dailyViewHour?.gridImported || 0) : 0,
      homePredicted: !isActual ? -(dailyViewHour?.homeConsumption || 0) : 0,
      batteryInPredicted: !isActual ? -(dailyViewHour?.batteryCharged || 0) : 0,
      gridOutPredicted: !isActual ? -(dailyViewHour?.gridExported || 0) : 0,
      
      // Meta data
      isActual,
      price: dailyViewHour?.buyPrice || 0,
    };
  });

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
              label={{ value: 'Hour of Day', position: 'insideBottom', offset: -10 }}
              tickFormatter={(hour) => hour.toString().padStart(2, '0')}
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
              tickFormatter={(value) => `${value.toFixed(2)}`}
              label={{ 
                value: 'Electricity Price (SEK/kWh)', 
                angle: 90, 
                position: 'insideRight',
                style: { textAnchor: 'middle', dominantBaseline: 'central' }
              }}
            />
            <Tooltip content={<CustomTooltip />} />
            
            {/* Reference line at zero to separate sources from consumption */}
            <ReferenceLine y={0} stroke={colors.text} strokeWidth={2} />
            
            {/* ENERGY SOURCES - ACTUAL DATA (full opacity) */}
            <Area
              type="monotone"
              dataKey="solarActual"
              stackId="sources"
              stroke={colors.solar}
              fill="url(#solarActualGradient)"
              strokeWidth={2}
              name="Solar Production"
            />
            <Area
              type="monotone"
              dataKey="batteryOutActual"
              stackId="sources"
              stroke={colors.battery}
              fill="url(#batteryActualGradient)"
              strokeWidth={2}
              name="Battery Discharge"
            />
            <Area
              type="monotone"
              dataKey="gridInActual"
              stackId="sources"
              stroke={colors.grid}
              fill="url(#gridActualGradient)"
              strokeWidth={2}
              name="Grid Import"
            />
            
            {/* ENERGY SOURCES - PREDICTED DATA (reduced opacity) */}
            <Area
              type="monotone"
              dataKey="solarPredicted"
              stackId="sources"
              stroke={colors.solar}
              strokeOpacity={0.4}
              fill="url(#solarPredictedGradient)"
              strokeWidth={1}
              name="Solar Production (Predicted)"
            />
            <Area
              type="monotone"
              dataKey="batteryOutPredicted"
              stackId="sources"
              stroke={colors.battery}
              strokeOpacity={0.4}
              fill="url(#batteryPredictedGradient)"
              strokeWidth={1}
              name="Battery Discharge (Predicted)"
            />
            <Area
              type="monotone"
              dataKey="gridInPredicted"
              stackId="sources"
              stroke={colors.grid}
              strokeOpacity={0.4}
              fill="url(#gridPredictedGradient)"
              strokeWidth={1}
              name="Grid Import (Predicted)"
            />
            
            {/* ENERGY CONSUMPTION - ACTUAL DATA (full opacity) */}
            <Area
              type="monotone"
              dataKey="homeActual"
              stackId="consumption"
              stroke={colors.home}
              fill="url(#homeActualGradient)"
              strokeWidth={2}
              name="Home Load"
            />
            <Area
              type="monotone"
              dataKey="batteryInActual"
              stackId="consumption"
              stroke={colors.battery}
              fill="url(#batteryChargeActualGradient)"
              strokeWidth={2}
              name="Battery Charge"
            />
            <Area
              type="monotone"
              dataKey="gridOutActual"
              stackId="consumption"
              stroke={colors.gridExport}
              fill="url(#gridExportActualGradient)"
              strokeWidth={2}
              name="Grid Export"
            />
            
            {/* ENERGY CONSUMPTION - PREDICTED DATA (reduced opacity) */}
            <Area
              type="monotone"
              dataKey="homePredicted"
              stackId="consumption"
              stroke={colors.home}
              strokeOpacity={0.4}
              fill="url(#homePredictedGradient)"
              strokeWidth={1}
              name="Home Load (Predicted)"
            />
            <Area
              type="monotone"
              dataKey="batteryInPredicted"
              stackId="consumption"
              stroke={colors.battery}
              strokeOpacity={0.4}
              fill="url(#batteryChargePredictedGradient)"
              strokeWidth={1}
              name="Battery Charge (Predicted)"
            />
            <Area
              type="monotone"
              dataKey="gridOutPredicted"
              stackId="consumption"
              stroke={colors.gridExport}
              strokeOpacity={0.4}
              fill="url(#gridExportPredictedGradient)"
              strokeWidth={1}
              name="Grid Export (Predicted)"
            />
            
            {/* Price line on secondary Y-axis */}
            <Line
              type="monotone"
              dataKey="price"
              yAxisId="price"
              stroke="#9CA3AF"
              strokeWidth={1.5}
              dot={false}
              strokeDasharray="3 3"
              name="Electricity Price"
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
            <div className="w-3 h-2 rounded mr-1" style={{ backgroundColor: colors.solar, opacity: 0.8 }}></div>
            <span>Actual</span>
          </div>
          <div className="flex items-center">
            <div className="w-3 h-2 rounded mr-1" style={{ backgroundColor: colors.solar, opacity: 0.3 }}></div>
            <span>Predicted</span>
          </div>
        </div>
      </div>
    </div>
  );
};