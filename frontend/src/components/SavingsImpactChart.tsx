import React, { useState, useEffect, useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import { SnapshotComparison } from '../types';

interface SavingsImpactChartProps {
  comparison: SnapshotComparison;
}

interface HourlyDeviation {
  hourLabel: string;
  solarDeviation: number;
  consumptionDeviation: number;
  batteryDeviation: number;
  gridImportDeviation: number;
  gridExportDeviation: number;
}

// Colors aligned with dashboard EnergyFlowChart
const COLORS = {
  solar: '#fbbf24',         // Yellow
  battery: '#10b981',       // Green
  gridImport: '#3b82f6',    // Blue
  gridExport: '#60a5fa',    // Light blue
  home: '#ef4444',          // Red
};

const DeviationTooltip = ({ active, payload }: any) => {
  if (!active || !payload?.length) return null;
  const data = payload[0].payload as HourlyDeviation;

  const formatDeviation = (
    label: string, value: number, color: string,
  ): React.ReactElement => {
    const direction = value >= 0 ? 'more' : 'less';

    return (
      <div className="flex items-center gap-2">
        <div className="w-2.5 h-2.5 rounded" style={{ backgroundColor: color }} />
        <span className="text-gray-700 dark:text-gray-300">
          {label}: {value >= 0 ? '+' : ''}{value.toFixed(2)} kWh ({direction} than planned)
        </span>
      </div>
    );
  };

  return (
    <div className="bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg p-3 shadow-lg">
      <p className="font-semibold text-gray-900 dark:text-white mb-2">
        {data.hourLabel}:00 - {(parseInt(data.hourLabel) + 1).toString().padStart(2, '0')}:00
      </p>
      <div className="space-y-1 text-sm">
        {formatDeviation('Solar', data.solarDeviation, COLORS.solar)}
        {formatDeviation('Consumption', data.consumptionDeviation, COLORS.home)}
        {formatDeviation('Battery', data.batteryDeviation, COLORS.battery)}
        {formatDeviation('Grid Import', data.gridImportDeviation, COLORS.gridImport)}
        {formatDeviation('Grid Export', data.gridExportDeviation, COLORS.gridExport)}
      </div>
    </div>
  );
};

const SavingsImpactChart: React.FC<SavingsImpactChartProps> = ({ comparison }) => {
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

  const hourlyData: HourlyDeviation[] = useMemo(() => {
    const buckets = new Map<number, {
      solarDeviation: number;
      consumptionDeviation: number;
      batteryDeviation: number;
      gridImportDeviation: number;
      gridExportDeviation: number;
    }>();

    for (const dev of comparison.periodDeviations) {
      const hour = Math.floor(dev.period / 4);
      const existing = buckets.get(hour) || {
        solarDeviation: 0, consumptionDeviation: 0, batteryDeviation: 0,
        gridImportDeviation: 0, gridExportDeviation: 0,
      };
      existing.solarDeviation += dev.solarDeviation.value;
      existing.consumptionDeviation += dev.consumptionDeviation.value;
      existing.batteryDeviation += dev.batteryActionDeviation.value;
      existing.gridImportDeviation += dev.gridImportDeviation.value;
      existing.gridExportDeviation += dev.gridExportDeviation.value;
      buckets.set(hour, existing);
    }

    // Fixed 00-24 x-axis
    return Array.from({ length: 24 }, (_, hour) => {
      const data = buckets.get(hour);
      return {
        hourLabel: hour.toString().padStart(2, '0'),
        solarDeviation: data?.solarDeviation ?? 0,
        consumptionDeviation: data?.consumptionDeviation ?? 0,
        batteryDeviation: data?.batteryDeviation ?? 0,
        gridImportDeviation: data?.gridImportDeviation ?? 0,
        gridExportDeviation: data?.gridExportDeviation ?? 0,
      };
    });
  }, [comparison.periodDeviations]);

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700 p-6">
      <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">Forecast Deviation by Hour</h3>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
        How each energy flow deviated from plan (actual minus planned)
      </p>
      <div style={{ width: '100%', height: '300px' }}>
        <ResponsiveContainer>
          <BarChart data={hourlyData} margin={{ top: 10, right: 10, left: 0, bottom: 30 }}>
            <CartesianGrid stroke={colors.gridLines} strokeOpacity={isDarkMode ? 0.12 : 0.3} strokeWidth={0.5} />
            <XAxis
              dataKey="hourLabel"
              stroke={colors.text}
              tick={{ fill: colors.text, fontSize: 11 }}
              label={{ value: 'Hour of Day', position: 'insideBottom', offset: -10, fill: colors.text, fontSize: 12 }}
            />
            <YAxis
              width={60}
              stroke={colors.text}
              tick={{ fill: colors.text, fontSize: 11 }}
              label={{ value: 'kWh', angle: -90, position: 'insideLeft', style: { textAnchor: 'middle', fill: colors.text }, fontSize: 12 }}
            />
            <Tooltip content={<DeviationTooltip />} />
            <ReferenceLine y={0} stroke={colors.text} strokeWidth={1} />
            <Bar dataKey="solarDeviation" name="Solar" fill={COLORS.solar} fillOpacity={0.8} isAnimationActive={false} />
            <Bar dataKey="consumptionDeviation" name="Consumption" fill={COLORS.home} fillOpacity={0.8} isAnimationActive={false} />
            <Bar dataKey="batteryDeviation" name="Battery" fill={COLORS.battery} fillOpacity={0.8} isAnimationActive={false} />
            <Bar dataKey="gridImportDeviation" name="Grid Import" fill={COLORS.gridImport} fillOpacity={0.8} isAnimationActive={false} />
            <Bar dataKey="gridExportDeviation" name="Grid Export" fill={COLORS.gridExport} fillOpacity={0.8} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="flex flex-wrap justify-center gap-4 mt-2 text-sm">
        <div className="flex items-center">
          <div className="w-3 h-3 rounded mr-1.5" style={{ backgroundColor: COLORS.solar }} />
          <span className="text-gray-600 dark:text-gray-400">Solar</span>
        </div>
        <div className="flex items-center">
          <div className="w-3 h-3 rounded mr-1.5" style={{ backgroundColor: COLORS.home }} />
          <span className="text-gray-600 dark:text-gray-400">Consumption</span>
        </div>
        <div className="flex items-center">
          <div className="w-3 h-3 rounded mr-1.5" style={{ backgroundColor: COLORS.battery }} />
          <span className="text-gray-600 dark:text-gray-400">Battery</span>
        </div>
        <div className="flex items-center">
          <div className="w-3 h-3 rounded mr-1.5" style={{ backgroundColor: COLORS.gridImport }} />
          <span className="text-gray-600 dark:text-gray-400">Grid Import</span>
        </div>
        <div className="flex items-center">
          <div className="w-3 h-3 rounded mr-1.5" style={{ backgroundColor: COLORS.gridExport }} />
          <span className="text-gray-600 dark:text-gray-400">Grid Export</span>
        </div>
      </div>
      <div className="text-center text-xs text-gray-500 dark:text-gray-400 mt-1">
        Positive = more than planned &middot; Negative = less than planned
      </div>
    </div>
  );
};

export default SavingsImpactChart;
