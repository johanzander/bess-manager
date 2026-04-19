import React, { useState, useEffect, useMemo } from 'react';
import { ComposedChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Cell } from 'recharts';
import { SnapshotComparison } from '../types';

interface SavingsImpactChartProps {
  comparison: SnapshotComparison;
}

interface HourlyImpact {
  hour: number;
  savingsDeviation: number;
  dominantCause: string;
}

const CAUSE_COLORS: Record<string, string> = {
  SOLAR_HIGHER: '#fbbf24',
  SOLAR_LOWER: '#fbbf24',
  CONSUMPTION_HIGHER: '#ef4444',
  CONSUMPTION_LOWER: '#ef4444',
  BATTERY_MISMATCH: '#3b82f6',
  MINIMAL: '#9ca3af',
  MULTIPLE: '#9ca3af',
};

const getCauseColor = (cause: string): string => {
  return CAUSE_COLORS[cause] || '#9ca3af';
};

const ImpactTooltip = ({ active, payload }: any) => {
  if (!active || !payload?.length) return null;
  const data = payload[0].payload as HourlyImpact;
  const hour = data.hour;

  const causeLabels: Record<string, string> = {
    SOLAR_HIGHER: 'More solar than predicted',
    SOLAR_LOWER: 'Less solar than predicted',
    CONSUMPTION_HIGHER: 'Higher consumption than predicted',
    CONSUMPTION_LOWER: 'Lower consumption than predicted',
    BATTERY_MISMATCH: 'Battery control divergence',
    MINIMAL: 'Minimal deviation',
    MULTIPLE: 'Multiple factors',
  };

  return (
    <div className="bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg p-3 shadow-lg">
      <p className="font-semibold text-gray-900 dark:text-white mb-1">
        {hour.toString().padStart(2, '0')}:00 - {(hour + 1).toString().padStart(2, '0')}:00
      </p>
      <div className="space-y-1 text-sm">
        <p className={`font-medium ${
          data.savingsDeviation >= 0
            ? 'text-green-600 dark:text-green-400'
            : 'text-red-600 dark:text-red-400'
        }`}>
          {data.savingsDeviation >= 0 ? '+' : ''}{data.savingsDeviation.toFixed(2)} vs predicted
        </p>
        <p className="text-gray-500 dark:text-gray-400">
          {causeLabels[data.dominantCause] || data.dominantCause}
        </p>
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

  const hourlyData: HourlyImpact[] = useMemo(() => {
    const buckets = new Map<number, { totalDeviation: number; causes: Map<string, number> }>();

    for (const dev of comparison.periodDeviations) {
      const hour = Math.floor(dev.period / 4);
      const existing = buckets.get(hour) || { totalDeviation: 0, causes: new Map() };
      existing.totalDeviation += dev.savingsDeviation.value;
      const count = existing.causes.get(dev.deviationType) || 0;
      existing.causes.set(dev.deviationType, count + Math.abs(dev.savingsDeviation.value));
      buckets.set(hour, existing);
    }

    return Array.from(buckets.entries())
      .sort(([a], [b]) => a - b)
      .map(([hour, data]) => {
        let dominantCause = 'MINIMAL';
        let maxContribution = 0;
        for (const [cause, contribution] of data.causes) {
          if (contribution > maxContribution) {
            maxContribution = contribution;
            dominantCause = cause;
          }
        }
        return {
          hour,
          savingsDeviation: data.totalDeviation,
          dominantCause,
        };
      });
  }, [comparison.periodDeviations]);

  const currency = comparison.totalActualSavings.unit;

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700 p-6">
      <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">Savings Impact by Hour</h3>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
        How each hour&apos;s savings differed from prediction, colored by primary cause
      </p>
      <div style={{ width: '100%', height: '300px' }}>
        <ResponsiveContainer>
          <ComposedChart data={hourlyData} margin={{ top: 10, right: 10, left: 0, bottom: 30 }}>
            <CartesianGrid stroke={colors.gridLines} strokeOpacity={isDarkMode ? 0.12 : 0.3} strokeWidth={0.5} />
            <XAxis
              dataKey="hour"
              type="number"
              domain={[0, 23]}
              ticks={Array.from({ length: 24 }, (_, i) => i)}
              interval={0}
              stroke={colors.text}
              tick={{ fill: colors.text, fontSize: 11 }}
              tickFormatter={(h: number) => h.toString().padStart(2, '0')}
              label={{ value: 'Hour of Day', position: 'insideBottom', offset: -10, fill: colors.text, fontSize: 12 }}
            />
            <YAxis
              width={60}
              stroke={colors.text}
              tick={{ fill: colors.text, fontSize: 11 }}
              label={{ value: `${currency}`, angle: -90, position: 'insideLeft', style: { textAnchor: 'middle', fill: colors.text }, fontSize: 12 }}
            />
            <Tooltip content={<ImpactTooltip />} />
            <ReferenceLine y={0} stroke={colors.text} strokeWidth={1} />
            <Bar dataKey="savingsDeviation" name="Savings Deviation" isAnimationActive={false}>
              {hourlyData.map((entry, index) => (
                <Cell key={index} fill={getCauseColor(entry.dominantCause)} fillOpacity={0.8} />
              ))}
            </Bar>
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="flex flex-wrap justify-center gap-4 mt-2 text-sm">
        <div className="flex items-center">
          <div className="w-3 h-3 rounded mr-1.5" style={{ backgroundColor: '#fbbf24' }} />
          <span className="text-gray-600 dark:text-gray-400">Solar forecast</span>
        </div>
        <div className="flex items-center">
          <div className="w-3 h-3 rounded mr-1.5" style={{ backgroundColor: '#ef4444' }} />
          <span className="text-gray-600 dark:text-gray-400">Consumption forecast</span>
        </div>
        <div className="flex items-center">
          <div className="w-3 h-3 rounded mr-1.5" style={{ backgroundColor: '#3b82f6' }} />
          <span className="text-gray-600 dark:text-gray-400">Battery control</span>
        </div>
        <div className="flex items-center">
          <div className="w-3 h-3 rounded mr-1.5" style={{ backgroundColor: '#9ca3af' }} />
          <span className="text-gray-600 dark:text-gray-400">Minimal / Multiple</span>
        </div>
        <div className="text-gray-500 dark:text-gray-400 text-xs flex items-center">
          Above zero = better than predicted
        </div>
      </div>
    </div>
  );
};

export default SavingsImpactChart;
