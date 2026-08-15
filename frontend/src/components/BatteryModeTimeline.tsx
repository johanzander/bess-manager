import React, { useState, useEffect } from 'react';
import { useDashboardData } from '../hooks/useDashboardData';
import { DashboardHourlyData } from '../api/scheduleApi';
import { getIntent, isCurtailed, StrategicIntent } from '../utils/intent';

// Refresh cadence matches other components that self-fetch quarter-hourly
// dashboard data (EnergyFlowCards, SystemStatusCard).
const REFRESH_INTERVAL_MS = 60000;

// Must match the YAxis width and ComposedChart margin used in EnergyFlowChart and BatteryLevelChart
// so the timeline bar aligns horizontally with the chart plot areas.
// Both charts: margin.left=5 + YAxis.width=60 → plot starts at 65px
// Both charts: margin.right=5 + YAxis.width=60 → plot ends at W-65px
const CHART_LEFT_OFFSET = 65;
const CHART_RIGHT_OFFSET = 65;

// 'CURTAILED' is a display-only pseudo-intent (#501): a period the plan
// expects to curtail (export limit applied, cost 0) rather than sell at a
// profit -- see isCurtailed() (utils/intent.ts) for why this isn't gated on
// intent === SOLAR_EXPORT. It is never a value of StrategicIntent itself --
// only this timeline's own legend/config keys.
type LegendKey = StrategicIntent | 'CURTAILED';

const INTENT_CONFIG: Record<LegendKey, { label: string; color: string; darkColor: string }> = {
  GRID_CHARGING: { label: 'Charging from Grid', color: '#a855f7', darkColor: '#a855f7' },
  SOLAR_STORAGE: { label: 'Storing Solar', color: '#eab308', darkColor: '#facc15' },
  LOAD_SUPPORT: { label: 'Powering Home', color: '#3b82f6', darkColor: '#60a5fa' },
  BATTERY_EXPORT: { label: 'Selling to Grid', color: '#22c55e', darkColor: '#4ade80' },
  SOLAR_EXPORT: { label: 'Solar Export', color: '#84cc16', darkColor: '#a3e635' },
  CURTAILED: { label: 'Curtailed (No Export)', color: '#78716c', darkColor: '#a8a29e' },
  IDLE: { label: 'Standby', color: '#9ca3af', darkColor: '#6b7280' },
};

const INTENT_ORDER: LegendKey[] = ['GRID_CHARGING', 'SOLAR_STORAGE', 'LOAD_SUPPORT', 'BATTERY_EXPORT', 'SOLAR_EXPORT', 'CURTAILED', 'IDLE'];

interface BatteryModeTimelineProps {
  currentHour: number;
}

interface Segment {
  startHour: number;
  endHour: number;
  intent: StrategicIntent;
  legendKey: LegendKey;
  isTomorrow: boolean;
}

// Always builds segments at true quarter-hour granularity — the color bar
// must never go through hourly "dominant intent" aggregation, which can
// let a stale planned intent outvote what was actually observed (#486).
const STEP_HOURS = 0.25;

function buildSegments(
  hourlyData: DashboardHourlyData[],
  tomorrowData: DashboardHourlyData[] | null | undefined
): Segment[] {
  const segments: Segment[] = [];

  for (let i = 0; i < hourlyData.length; i++) {
    const h = hourlyData[i];
    const intent = getIntent(h);
    const legendKey: LegendKey = isCurtailed(h) ? 'CURTAILED' : intent;
    const startHour = i * STEP_HOURS;
    const endHour = startHour + STEP_HOURS;

    const last = segments[segments.length - 1];
    if (last && last.legendKey === legendKey && last.intent === intent && !last.isTomorrow && Math.abs(last.endHour - startHour) < 0.01) {
      last.endHour = endHour;
    } else {
      segments.push({ startHour, endHour, intent, legendKey, isTomorrow: false });
    }
  }

  if (tomorrowData && tomorrowData.length > 0) {
    for (let i = 0; i < tomorrowData.length; i++) {
      const th = tomorrowData[i];
      const intent = getIntent(th);
      const legendKey: LegendKey = isCurtailed(th) ? 'CURTAILED' : intent;
      const startHour = 24 + i * STEP_HOURS;
      const endHour = startHour + STEP_HOURS;

      const last = segments[segments.length - 1];
      if (last && last.legendKey === legendKey && last.intent === intent && last.isTomorrow && Math.abs(last.endHour - startHour) < 0.01) {
        last.endHour = endHour;
      } else {
        segments.push({ startHour, endHour, intent, legendKey, isTomorrow: true });
      }
    }
  }

  return segments;
}

function formatHour(hour: number): string {
  const h = Math.floor(hour) % 24;
  const m = Math.round((hour - Math.floor(hour)) * 60);
  return h.toString().padStart(2, '0') + ':' + m.toString().padStart(2, '0');
}

export const BatteryModeTimeline: React.FC<BatteryModeTimelineProps> = ({
  currentHour,
}) => {
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

  const { data, loading, error } = useDashboardData(undefined, 'quarter-hourly', REFRESH_INTERVAL_MS);

  const [tooltipData, setTooltipData] = useState<{ segment: Segment; x: number; y: number } | null>(null);

  // useDashboardData sets loading=true on every periodic refetch too, not
  // just the first one — gate the skeleton on "no data yet" so a background
  // 60s refresh doesn't blank out an already-rendered timeline (#486).
  if (loading && !data) {
    return (
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow animate-pulse">
        <div className="h-9 bg-gray-200 dark:bg-gray-700 rounded" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow text-red-600 text-center">
        {error || 'Failed to load schedule'}
      </div>
    );
  }

  const hourlyData = data.hourlyData;
  const tomorrowData = data.tomorrowData;

  const segments = buildSegments(hourlyData, tomorrowData);
  const hasTomorrow = tomorrowData && tomorrowData.length > 0;
  const maxHour = hasTomorrow ? 48 : 24;

  const usedIntents = new Set(segments.map(s => s.legendKey));

  // Tick marks every hour
  const ticks: number[] = [];
  for (let h = 0; h <= maxHour; h += 1) {
    ticks.push(h);
  }

  const barHeight = 28;
  const tickHeight = 6;
  const svgHeight = barHeight + 20; // bar + tick + label

  const tickColor = isDarkMode ? '#6b7280' : '#9ca3af';

  return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
      <div className="relative" style={{ paddingLeft: CHART_LEFT_OFFSET, paddingRight: CHART_RIGHT_OFFSET }}>
        {/* Bar SVG — fills the padded area, aligning with chart plot areas */}
        <svg
          width="100%"
          viewBox={`0 0 1000 ${svgHeight}`}
          preserveAspectRatio="xMidYMid meet"
          className="overflow-visible"
        >
          {segments.map((seg, i) => {
            const x = (seg.startHour / maxHour) * 1000;
            const width = ((seg.endHour - seg.startHour) / maxHour) * 1000;
            const config = INTENT_CONFIG[seg.legendKey];
            const color = isDarkMode ? config.darkColor : config.color;
            const isFirst = i === 0;
            const isLast = i === segments.length - 1;

            return (
              <rect
                key={i}
                x={x}
                y={0}
                width={Math.max(width - 0.5, 0.5)}
                height={barHeight}
                rx={isFirst || isLast ? 4 : 0}
                ry={isFirst || isLast ? 4 : 0}
                fill={color}
                opacity={seg.isTomorrow ? 0.5 : 0.85}
                className="cursor-pointer"
                onMouseEnter={(e: React.MouseEvent<SVGRectElement>) => {
                  const rect = e.currentTarget.getBoundingClientRect();
                  setTooltipData({ segment: seg, x: rect.left + rect.width / 2, y: rect.top });
                }}
                onMouseLeave={() => setTooltipData(null)}
              />
            );
          })}

          {/* Current hour marker */}
          {(() => {
            const markerX = (currentHour / maxHour) * 1000;
            return (
              <g>
                <line
                  x1={markerX} y1={-2}
                  x2={markerX} y2={barHeight + 2}
                  stroke={isDarkMode ? '#f9fafb' : '#111827'}
                  strokeWidth={2}
                />
                <polygon
                  points={`${markerX - 4},-4 ${markerX + 4},-4 ${markerX},1`}
                  fill={isDarkMode ? '#f9fafb' : '#111827'}
                />
              </g>
            );
          })()}

          {/* Time axis ticks and labels */}
          {ticks.map((hour) => {
            const x = (hour / maxHour) * 1000;
            return (
              <g key={hour}>
                <line
                  x1={x} y1={barHeight}
                  x2={x} y2={barHeight + tickHeight}
                  stroke={tickColor}
                  strokeWidth={1}
                />
                <text
                  x={x}
                  y={barHeight + tickHeight + 12}
                  textAnchor="middle"
                  fill={tickColor}
                  fontSize={11}
                >
                  {(hour % 24).toString().padStart(2, '0')}
                </text>
              </g>
            );
          })}
        </svg>

        {/* Tooltip */}
        {tooltipData && (
          <div
            className="fixed z-50 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg p-3 shadow-lg pointer-events-none"
            style={{
              left: tooltipData.x,
              top: tooltipData.y - 8,
              transform: 'translate(-50%, -100%)',
            }}
          >
            <p className="font-semibold text-gray-900 dark:text-white text-sm">
              {/* Curtailment doesn't replace the intent (a curtailed period
                  can still be charging, e.g. SOLAR_STORAGE) -- show both. */}
              {tooltipData.segment.legendKey === 'CURTAILED'
                ? `${INTENT_CONFIG[tooltipData.segment.intent].label} — Curtailed (No Export)`
                : INTENT_CONFIG[tooltipData.segment.legendKey].label}
            </p>
            <p className="text-xs text-gray-600 dark:text-gray-400">
              {formatHour(tooltipData.segment.startHour)} – {formatHour(tooltipData.segment.endHour)}
              {tooltipData.segment.isTomorrow && ' (Tomorrow)'}
            </p>
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap justify-center gap-4 mt-3 text-sm">
        {INTENT_ORDER.filter(key => usedIntents.has(key)).map((key) => {
          const config = INTENT_CONFIG[key];
          const color = isDarkMode ? config.darkColor : config.color;
          return (
            <div key={key} className="flex items-center">
              <div
                className="w-4 h-3 rounded-sm mr-2"
                style={{ backgroundColor: color }}
              />
              <span className="text-gray-700 dark:text-gray-300">{config.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};
