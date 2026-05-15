import React, { useState, useEffect, useMemo } from 'react';
import { ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { useConsumptionForecastComparison } from '../hooks/useConsumptionForecastComparison';
// @ts-expect-error lucide-react .d.ts is too large for TS to resolve all exports
import { AlertCircle, BarChart3, ChevronDown, ChevronUp } from 'lucide-react';
import { StrategyForecast } from '../types';
import { niceYAxis } from '../utils/chartUtils';

interface ChartDataPoint {
  hour: number;
  actual: number | null;
  [key: string]: number | null;
}

const STRATEGY_LABELS: Record<string, string> = {
  sensor: '48h Avg Sensor',
  fixed: 'Fixed Value',
  influxdb_7d_avg: 'InfluxDB 7-day Avg',
  ha_statistics: 'HA Statistics',
};

const STRATEGY_COLORS: Record<string, string> = {
  sensor: '#ef4444',
  fixed: '#f59e0b',
  influxdb_7d_avg: '#3b82f6',
  ha_statistics: '#8b5cf6',
};

const ACTUAL_COLOR = '#10b981';

const ForecastTooltip = ({ active, payload }: any) => {
  if (!active || !payload?.length) return null;
  const data = payload[0].payload as ChartDataPoint;
  const hour = data.hour as number;
  const endHour = hour + 1;

  return (
    <div className="bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg p-3 shadow-lg">
      <p className="font-semibold text-gray-900 dark:text-white mb-1">
        {hour.toString().padStart(2, '0')}:00 - {endHour.toString().padStart(2, '0')}:00
      </p>
      <div className="space-y-1 text-sm">
        {payload.map((entry: any) => (
          <p key={entry.dataKey} style={{ color: entry.color }}>
            {entry.name}: {entry.value != null ? `${entry.value.toFixed(2)} kWh` : 'N/A'}
          </p>
        ))}
      </div>
    </div>
  );
};

const ConsumptionForecastComparison: React.FC = () => {
  const { comparison, loading, error } = useConsumptionForecastComparison();
  const [expanded, setExpanded] = useState(false);

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

  const availableStrategies = useMemo(() => {
    if (!comparison) return [];
    return comparison.strategies.filter((s) => s.available);
  }, [comparison]);

  const hasActual = comparison ? comparison.actualHoursAvailable > 0 : false;

  const chartData: ChartDataPoint[] = useMemo(() => {
    if (!comparison || !availableStrategies.length) return [];
    const points: ChartDataPoint[] = [];
    for (let hour = 0; hour < 24; hour++) {
      const point: ChartDataPoint = {
        hour,
        actual: comparison.actualHourlyProfile[hour]?.value ?? null,
      };
      for (const strat of availableStrategies) {
        point[strat.name] = strat.hourlyProfile[hour]?.value ?? null;
      }
      points.push(point);
    }
    return points;
  }, [comparison, availableStrategies]);

  const yAxis = useMemo(() => {
    if (!chartData.length) return niceYAxis(0, 1);
    let max = 0.1;
    for (const point of chartData) {
      if (point.actual != null && point.actual > max) max = point.actual;
      for (const strat of availableStrategies) {
        const v = point[strat.name];
        if (v != null && v > max) max = v;
      }
    }
    return niceYAxis(0, max);
  }, [chartData, availableStrategies]);

  // Sort strategies by MAE (best first) for display
  const sortedStrategies = useMemo(() => {
    return [...availableStrategies].sort((a, b) => {
      if (a.mae == null && b.mae == null) return 0;
      if (a.mae == null) return 1;
      if (b.mae == null) return -1;
      return a.mae.value - b.mae.value;
    });
  }, [availableStrategies]);

  if (loading) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700 p-6">
        <div className="text-gray-600 dark:text-gray-300">Loading forecast comparison...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700 rounded-lg p-4">
        <div className="flex items-center">
          <AlertCircle className="h-5 w-5 text-red-600 dark:text-red-400 mr-2" />
          <p className="text-red-800 dark:text-red-200 text-sm">{error}</p>
        </div>
      </div>
    );
  }

  if (!comparison) return null;

  const xAxisTicks = Array.from({ length: 25 }, (_, i) => i);

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700">
      {/* Collapsible header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-6 text-left hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors rounded-lg"
      >
        <div className="flex items-center">
          <BarChart3 className="h-5 w-5 text-purple-500 mr-2" />
          <div>
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              Consumption Forecast Comparison
            </h3>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {availableStrategies.length} strategies vs actual consumption
              {hasActual && ` (${comparison.actualHoursAvailable}h of data)`}
            </p>
          </div>
        </div>
        {expanded ? (
          <ChevronUp className="h-5 w-5 text-gray-400" />
        ) : (
          <ChevronDown className="h-5 w-5 text-gray-400" />
        )}
      </button>

      {expanded && (
        <div className="px-6 pb-6 space-y-4">
          {/* Metrics cards — sorted by MAE */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {sortedStrategies.map((strat, idx) => {
              const color = STRATEGY_COLORS[strat.name] || '#6b7280';
              const label = STRATEGY_LABELS[strat.name] || strat.name;
              const isBest = hasActual && idx === 0 && strat.mae != null;

              return (
                <div
                  key={strat.name}
                  className={`rounded-lg p-3 ${
                    isBest
                      ? 'ring-2 ring-green-500 ring-offset-1 dark:ring-offset-gray-800 bg-green-50 dark:bg-green-900/20'
                      : strat.isActive
                        ? 'bg-gray-100 dark:bg-gray-700'
                        : 'bg-gray-50 dark:bg-gray-700/50'
                  }`}
                >
                  <div className="flex items-center gap-1.5 mb-1">
                    <div
                      className="w-2.5 h-2.5 rounded-full"
                      style={{ backgroundColor: color }}
                    />
                    <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                      {label}
                      {strat.isActive && (
                        <span className="ml-1 text-[10px] font-medium text-gray-400 dark:text-gray-500">
                          (active)
                        </span>
                      )}
                    </p>
                  </div>
                  <p className="text-lg font-semibold" style={{ color }}>
                    {strat.totalKwh?.text ?? 'N/A'}
                  </p>
                  {strat.mae != null ? (
                    <p className="text-xs text-gray-500 dark:text-gray-400">
                      MAE: {strat.mae.text}
                      {isBest && <span className="ml-1 text-green-600 dark:text-green-400 font-medium">best</span>}
                    </p>
                  ) : (
                    <p className="text-xs text-gray-400 dark:text-gray-500">
                      No actual data yet
                    </p>
                  )}
                </div>
              );
            })}
          </div>

          {/* Unavailable strategies note */}
          {comparison.strategies.some((s) => !s.available) && (
            <p className="text-xs text-gray-400 dark:text-gray-500">
              Unavailable:{' '}
              {comparison.strategies
                .filter((s) => !s.available)
                .map((s) => STRATEGY_LABELS[s.name] || s.name)
                .join(', ')}
            </p>
          )}

          {/* Chart */}
          {chartData.length > 0 && (
            <div style={{ width: '100%', height: '300px' }}>
              <ResponsiveContainer>
                <ComposedChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 30 }}>
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
                    domain={[0, yAxis.ceiling]}
                    ticks={yAxis.ticks}
                    stroke={colors.text}
                    tick={{ fill: colors.text, fontSize: 11 }}
                    label={{ value: 'kWh', angle: -90, position: 'insideLeft', style: { textAnchor: 'middle', fill: colors.text }, fontSize: 12 }}
                  />
                  <Tooltip content={<ForecastTooltip />} />

                  {/* Actual consumption as bold bar */}
                  {hasActual && (
                    <Bar
                      dataKey="actual"
                      fill={ACTUAL_COLOR}
                      fillOpacity={0.25}
                      stroke={ACTUAL_COLOR}
                      strokeWidth={1}
                      name="Actual"
                      isAnimationActive={false}
                    />
                  )}

                  {/* All strategies as lines */}
                  {availableStrategies.map((strat) => (
                    <Line
                      key={strat.name}
                      type="monotone"
                      dataKey={strat.name}
                      stroke={STRATEGY_COLORS[strat.name] || '#6b7280'}
                      strokeWidth={strat.isActive ? 2.5 : 1.5}
                      strokeDasharray={strat.isActive ? undefined : '6 3'}
                      name={STRATEGY_LABELS[strat.name] || strat.name}
                      isAnimationActive={false}
                      dot={false}
                      connectNulls
                    />
                  ))}
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Legend */}
          <div className="flex flex-wrap justify-center gap-4 text-sm">
            {hasActual && (
              <div className="flex items-center">
                <div className="w-4 h-3 rounded mr-2" style={{ backgroundColor: ACTUAL_COLOR, opacity: 0.4 }} />
                <span className="text-gray-600 dark:text-gray-400">Actual</span>
              </div>
            )}
            {availableStrategies.map((strat) => {
              const color = STRATEGY_COLORS[strat.name] || '#6b7280';
              const label = STRATEGY_LABELS[strat.name] || strat.name;
              return (
                <div key={strat.name} className="flex items-center">
                  <div
                    className="w-4 h-0 mr-2"
                    style={{
                      borderTop: strat.isActive
                        ? `2.5px solid ${color}`
                        : `1.5px dashed ${color}`,
                    }}
                  />
                  <span className="text-gray-600 dark:text-gray-400">{label}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

export default ConsumptionForecastComparison;
