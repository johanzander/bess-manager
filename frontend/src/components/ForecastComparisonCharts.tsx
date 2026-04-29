import React, { useState, useEffect, useMemo } from 'react';
import { ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { SnapshotComparison } from '../types';

interface ForecastComparisonChartsProps {
  comparison: SnapshotComparison;
}

interface ChartDataPoint {
  hour: number;
  periodNum: number;
  actualSolar: number;
  predictedSolar: number;
  actualConsumption: number;
  predictedConsumption: number;
  actualBattery: number;
  predictedBattery: number;
  actualGridImport: number;
  predictedGridImport: number;
  actualGridExport: number;
  predictedGridExport: number;
}

const ComparisonTooltip = ({ active, payload, color, actualKey, predictedKey, label }: any) => {
  if (!active || !payload?.length) return null;
  const data = payload[0].payload as ChartDataPoint;
  const hour = Math.floor(data.hour);
  const endHour = hour + 1;
  const actual = data[actualKey as keyof ChartDataPoint] as number;
  const predicted = data[predictedKey as keyof ChartDataPoint] as number;
  const diff = actual - predicted;

  return (
    <div className="bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg p-3 shadow-lg">
      <p className="font-semibold text-gray-900 dark:text-white mb-1">
        {hour.toString().padStart(2, '0')}:00 - {endHour.toString().padStart(2, '0')}:00
      </p>
      <div className="space-y-1 text-sm">
        <p style={{ color }}>Actual: {actual.toFixed(3)} kWh</p>
        <p style={{ color, opacity: 0.7 }}>{label === 'forecast' ? 'Predicted' : 'Planned'}: {predicted.toFixed(3)} kWh</p>
        <p className={`font-medium ${
          Math.abs(diff) < 0.05 ? 'text-gray-500' : diff >= 0
            ? 'text-green-600 dark:text-green-400'
            : 'text-red-600 dark:text-red-400'
        }`}>
          Diff: {diff >= 0 ? '+' : ''}{diff.toFixed(3)} kWh
        </p>
      </div>
    </div>
  );
};

interface SingleChartProps {
  data: ChartDataPoint[];
  title: string;
  subtitle: string;
  color: string;
  actualKey: string;
  predictedKey: string;
  gradientId: string;
  label: 'forecast' | 'schedule';
  xAxisTicks: number[];
  isDarkMode: boolean;
  colors: { text: string; gridLines: string };
}

const SingleChart: React.FC<SingleChartProps> = ({
  data, title, subtitle, color, actualKey, predictedKey, gradientId, label,
  xAxisTicks, isDarkMode, colors,
}) => {
  const maxVal = Math.max(
    ...data.map(d => Math.max(
      d[actualKey as keyof ChartDataPoint] as number,
      d[predictedKey as keyof ChartDataPoint] as number,
    )),
    0.1,
  );
  const predictedLabel = label === 'forecast' ? 'Predicted' : 'Planned';

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700 p-6">
      <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">{title}</h3>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">{subtitle}</p>
      <div style={{ width: '100%', height: '250px' }}>
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 30 }}>
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.6} />
                <stop offset="100%" stopColor={color} stopOpacity={0.05} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={colors.gridLines} strokeOpacity={isDarkMode ? 0.12 : 0.3} strokeWidth={0.5} />
            <XAxis
              dataKey="hour"
              type="number"
              domain={[0, 24]}
              ticks={xAxisTicks}
              interval={0}
              stroke={colors.text}
              tick={{ fill: colors.text, fontSize: 11 }}
              tickFormatter={(h: number) => Math.floor(h).toString().padStart(2, '0')}
              label={{ value: 'Hour of Day', position: 'insideBottom', offset: -10, fill: colors.text, fontSize: 12 }}
            />
            <YAxis
              width={50}
              domain={[0, Math.ceil(maxVal * 10) / 10]}
              stroke={colors.text}
              tick={{ fill: colors.text, fontSize: 11 }}
              label={{ value: 'kWh', angle: -90, position: 'insideLeft', style: { textAnchor: 'middle', fill: colors.text }, fontSize: 12 }}
            />
            <Tooltip content={<ComparisonTooltip color={color} actualKey={actualKey} predictedKey={predictedKey} label={label} />} />
            <Area
              type="monotone"
              dataKey={actualKey}
              fill={`url(#${gradientId})`}
              stroke={color}
              strokeWidth={2}
              name="Actual"
              isAnimationActive={false}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey={predictedKey}
              stroke={color}
              strokeWidth={2}
              strokeDasharray="6 4"
              strokeOpacity={0.7}
              name={predictedLabel}
              isAnimationActive={false}
              dot={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="flex justify-center gap-6 mt-2 text-sm">
        <div className="flex items-center">
          <div className="w-4 h-3 rounded mr-2" style={{ backgroundColor: color }} />
          <span className="text-gray-600 dark:text-gray-400">Actual</span>
        </div>
        <div className="flex items-center">
          <div className="w-4 h-0 mr-2" style={{ borderTop: `2px dashed ${color}` }} />
          <span className="text-gray-600 dark:text-gray-400">{predictedLabel}</span>
        </div>
      </div>
    </div>
  );
};

const ForecastComparisonCharts: React.FC<ForecastComparisonChartsProps> = ({ comparison }) => {
  const [isDarkMode, setIsDarkMode] = useState(
    document.documentElement.classList.contains('dark')
  );

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDarkMode(document.documentElement.classList.contains('dark'));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  const colors = {
    text: isDarkMode ? '#9CA3AF' : '#374151',
    gridLines: isDarkMode ? '#374151' : '#e5e7eb',
  };

  const chartData: ChartDataPoint[] = useMemo(() => {
    return comparison.periodDeviations.map((dev) => ({
      hour: (dev.period + 0.5) / 4,
      periodNum: dev.period,
      actualSolar: dev.actualSolar.value,
      predictedSolar: dev.predictedSolar.value,
      actualConsumption: dev.actualConsumption.value,
      predictedConsumption: dev.predictedConsumption.value,
      actualBattery: dev.actualBatteryAction.value,
      predictedBattery: dev.predictedBatteryAction.value,
      actualGridImport: dev.actualGridImport.value,
      predictedGridImport: dev.predictedGridImport.value,
      actualGridExport: dev.actualGridExport.value,
      predictedGridExport: dev.predictedGridExport.value,
    }));
  }, [comparison.periodDeviations]);

  const xAxisTicks = Array.from({ length: 25 }, (_, i) => i);

  return (
    <div className="space-y-6">
      {/* Forecast Accuracy charts (inputs) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SingleChart
          data={chartData} title="Solar Production" subtitle="Predicted vs actual solar output"
          color="#fbbf24" actualKey="actualSolar" predictedKey="predictedSolar"
          gradientId="solarActualFill" label="forecast"
          xAxisTicks={xAxisTicks} isDarkMode={isDarkMode} colors={colors}
        />
        <SingleChart
          data={chartData} title="Home Consumption" subtitle="Predicted vs actual consumption"
          color="#ef4444" actualKey="actualConsumption" predictedKey="predictedConsumption"
          gradientId="consumptionActualFill" label="forecast"
          xAxisTicks={xAxisTicks} isDarkMode={isDarkMode} colors={colors}
        />
      </div>

      {/* Schedule Deviation charts (outputs) */}
      <div>
        <h3 className="text-base font-semibold text-gray-700 dark:text-gray-300 mb-3">Schedule Deviation</h3>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <SingleChart
            data={chartData} title="Battery Charge/Discharge" subtitle="Planned vs actual battery action"
            color="#10b981" actualKey="actualBattery" predictedKey="predictedBattery"
            gradientId="batteryActualFill" label="schedule"
            xAxisTicks={xAxisTicks} isDarkMode={isDarkMode} colors={colors}
          />
          <SingleChart
            data={chartData} title="Grid Import" subtitle="Planned vs actual grid import"
            color="#3b82f6" actualKey="actualGridImport" predictedKey="predictedGridImport"
            gradientId="gridImportActualFill" label="schedule"
            xAxisTicks={xAxisTicks} isDarkMode={isDarkMode} colors={colors}
          />
          <SingleChart
            data={chartData} title="Grid Export" subtitle="Planned vs actual grid export"
            color="#60a5fa" actualKey="actualGridExport" predictedKey="predictedGridExport"
            gradientId="gridExportActualFill" label="schedule"
            xAxisTicks={xAxisTicks} isDarkMode={isDarkMode} colors={colors}
          />
        </div>
      </div>
    </div>
  );
};

export default ForecastComparisonCharts;
