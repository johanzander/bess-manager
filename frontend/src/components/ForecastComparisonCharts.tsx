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
}

const SolarTooltip = ({ active, payload }: any) => {
  if (!active || !payload?.length) return null;
  const data = payload[0].payload as ChartDataPoint;
  const hour = Math.floor(data.hour);
  const endHour = hour + 1;

  return (
    <div className="bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg p-3 shadow-lg">
      <p className="font-semibold text-gray-900 dark:text-white mb-1">
        {hour.toString().padStart(2, '0')}:00 - {endHour.toString().padStart(2, '0')}:00
      </p>
      <div className="space-y-1 text-sm">
        <p className="text-yellow-600 dark:text-yellow-400">
          Actual: {data.actualSolar.toFixed(3)} kWh
        </p>
        <p className="text-yellow-600 dark:text-yellow-400" style={{ opacity: 0.7 }}>
          Predicted: {data.predictedSolar.toFixed(3)} kWh
        </p>
        <p className={`font-medium ${
          Math.abs(data.actualSolar - data.predictedSolar) < 0.05
            ? 'text-gray-500'
            : data.actualSolar >= data.predictedSolar
              ? 'text-green-600 dark:text-green-400'
              : 'text-red-600 dark:text-red-400'
        }`}>
          Diff: {(data.actualSolar - data.predictedSolar) >= 0 ? '+' : ''}
          {(data.actualSolar - data.predictedSolar).toFixed(3)} kWh
        </p>
      </div>
    </div>
  );
};

const ConsumptionTooltip = ({ active, payload }: any) => {
  if (!active || !payload?.length) return null;
  const data = payload[0].payload as ChartDataPoint;
  const hour = Math.floor(data.hour);
  const endHour = hour + 1;

  return (
    <div className="bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg p-3 shadow-lg">
      <p className="font-semibold text-gray-900 dark:text-white mb-1">
        {hour.toString().padStart(2, '0')}:00 - {endHour.toString().padStart(2, '0')}:00
      </p>
      <div className="space-y-1 text-sm">
        <p className="text-red-600 dark:text-red-400">
          Actual: {data.actualConsumption.toFixed(3)} kWh
        </p>
        <p className="text-red-600 dark:text-red-400" style={{ opacity: 0.7 }}>
          Predicted: {data.predictedConsumption.toFixed(3)} kWh
        </p>
        <p className={`font-medium ${
          Math.abs(data.actualConsumption - data.predictedConsumption) < 0.05
            ? 'text-gray-500'
            : data.actualConsumption <= data.predictedConsumption
              ? 'text-green-600 dark:text-green-400'
              : 'text-red-600 dark:text-red-400'
        }`}>
          Diff: {(data.actualConsumption - data.predictedConsumption) >= 0 ? '+' : ''}
          {(data.actualConsumption - data.predictedConsumption).toFixed(3)} kWh
        </p>
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
    }));
  }, [comparison.periodDeviations]);

  const xAxisTicks = Array.from({ length: 25 }, (_, i) => i);

  const solarMax = Math.max(
    ...chartData.map(d => Math.max(d.actualSolar, d.predictedSolar)),
    0.1
  );
  const consumptionMax = Math.max(
    ...chartData.map(d => Math.max(d.actualConsumption, d.predictedConsumption)),
    0.1
  );

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Solar Production Chart */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700 p-6">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">Solar Production</h3>
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">Predicted vs actual solar output</p>
        <div style={{ width: '100%', height: '300px' }}>
          <ResponsiveContainer>
            <ComposedChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 30 }}>
              <defs>
                <linearGradient id="solarActualFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#fbbf24" stopOpacity={0.6} />
                  <stop offset="100%" stopColor="#fbbf24" stopOpacity={0.05} />
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
                domain={[0, Math.ceil(solarMax * 10) / 10]}
                stroke={colors.text}
                tick={{ fill: colors.text, fontSize: 11 }}
                label={{ value: 'kWh', angle: -90, position: 'insideLeft', style: { textAnchor: 'middle', fill: colors.text }, fontSize: 12 }}
              />
              <Tooltip content={<SolarTooltip />} />
              <Area
                type="monotone"
                dataKey="actualSolar"
                fill="url(#solarActualFill)"
                stroke="#fbbf24"
                strokeWidth={2}
                name="Actual Solar"
                isAnimationActive={false}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="predictedSolar"
                stroke="#fbbf24"
                strokeWidth={2}
                strokeDasharray="6 4"
                strokeOpacity={0.7}
                name="Predicted Solar"
                isAnimationActive={false}
                dot={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <div className="flex justify-center gap-6 mt-2 text-sm">
          <div className="flex items-center">
            <div className="w-4 h-3 rounded mr-2" style={{ backgroundColor: '#fbbf24' }} />
            <span className="text-gray-600 dark:text-gray-400">Actual</span>
          </div>
          <div className="flex items-center">
            <div className="w-4 h-0 mr-2" style={{ borderTop: '2px dashed #fbbf24' }} />
            <span className="text-gray-600 dark:text-gray-400">Predicted</span>
          </div>
        </div>
      </div>

      {/* Consumption Chart */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700 p-6">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">Home Consumption</h3>
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">Predicted vs actual consumption</p>
        <div style={{ width: '100%', height: '300px' }}>
          <ResponsiveContainer>
            <ComposedChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 30 }}>
              <defs>
                <linearGradient id="consumptionActualFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#ef4444" stopOpacity={0.6} />
                  <stop offset="100%" stopColor="#ef4444" stopOpacity={0.05} />
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
                domain={[0, Math.ceil(consumptionMax * 10) / 10]}
                stroke={colors.text}
                tick={{ fill: colors.text, fontSize: 11 }}
                label={{ value: 'kWh', angle: -90, position: 'insideLeft', style: { textAnchor: 'middle', fill: colors.text }, fontSize: 12 }}
              />
              <Tooltip content={<ConsumptionTooltip />} />
              <Area
                type="monotone"
                dataKey="actualConsumption"
                fill="url(#consumptionActualFill)"
                stroke="#ef4444"
                strokeWidth={2}
                name="Actual Consumption"
                isAnimationActive={false}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="predictedConsumption"
                stroke="#ef4444"
                strokeWidth={2}
                strokeDasharray="6 4"
                strokeOpacity={0.7}
                name="Predicted Consumption"
                isAnimationActive={false}
                dot={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <div className="flex justify-center gap-6 mt-2 text-sm">
          <div className="flex items-center">
            <div className="w-4 h-3 rounded mr-2" style={{ backgroundColor: '#ef4444' }} />
            <span className="text-gray-600 dark:text-gray-400">Actual</span>
          </div>
          <div className="flex items-center">
            <div className="w-4 h-0 mr-2" style={{ borderTop: '2px dashed #ef4444' }} />
            <span className="text-gray-600 dark:text-gray-400">Predicted</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ForecastComparisonCharts;
