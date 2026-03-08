import React, { useState, useEffect } from 'react';
import { HourlyData } from '../types';
import { DataResolution } from '../hooks/useUserPreferences';

type StrategicIntent = 'GRID_CHARGING' | 'SOLAR_STORAGE' | 'LOAD_SUPPORT' | 'EXPORT_ARBITRAGE' | 'IDLE';

const INTENT_CONFIG: Record<StrategicIntent, { label: string; color: string; darkColor: string }> = {
  GRID_CHARGING: { label: 'Grid Charging', color: '#a855f7', darkColor: '#a855f7' },
  SOLAR_STORAGE: { label: 'Solar Storage', color: '#eab308', darkColor: '#facc15' },
  LOAD_SUPPORT: { label: 'Load Support', color: '#3b82f6', darkColor: '#60a5fa' },
  EXPORT_ARBITRAGE: { label: 'Export Arbitrage', color: '#22c55e', darkColor: '#4ade80' },
  IDLE: { label: 'Idle', color: '#9ca3af', darkColor: '#6b7280' },
};

const INTENT_ORDER: StrategicIntent[] = ['GRID_CHARGING', 'SOLAR_STORAGE', 'LOAD_SUPPORT', 'EXPORT_ARBITRAGE', 'IDLE'];

interface BatteryModeTimelineProps {
  hourlyData: HourlyData[];
  tomorrowData?: HourlyData[] | null;
  currentHour: number;
  resolution: DataResolution;
}

interface Segment {
  startHour: number;
  endHour: number;
  intent: StrategicIntent;
  isTomorrow: boolean;
}

function buildSegments(
  hourlyData: HourlyData[],
  tomorrowData: HourlyData[] | null | undefined,
  resolution: DataResolution
): Segment[] {
  const step = resolution === 'quarter-hourly' ? 0.25 : 1;
  const segments: Segment[] = [];

  // Process today's data
  for (let i = 0; i < hourlyData.length; i++) {
    const intent = (hourlyData[i].strategicIntent as StrategicIntent) || 'IDLE';
    const startHour = resolution === 'quarter-hourly' ? i * 0.25 : i;
    const endHour = startHour + step;

    // Merge with previous segment if same intent and same day
    const last = segments[segments.length - 1];
    if (last && last.intent === intent && !last.isTomorrow && Math.abs(last.endHour - startHour) < 0.01) {
      last.endHour = endHour;
    } else {
      segments.push({ startHour, endHour, intent, isTomorrow: false });
    }
  }

  // Process tomorrow's data
  if (tomorrowData && tomorrowData.length > 0) {
    for (let i = 0; i < tomorrowData.length; i++) {
      const intent = (tomorrowData[i].strategicIntent as StrategicIntent) || 'IDLE';
      const startHour = 24 + (resolution === 'quarter-hourly' ? i * 0.25 : i);
      const endHour = startHour + step;

      const last = segments[segments.length - 1];
      if (last && last.intent === intent && last.isTomorrow && Math.abs(last.endHour - startHour) < 0.01) {
        last.endHour = endHour;
      } else {
        segments.push({ startHour, endHour, intent, isTomorrow: true });
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
  hourlyData,
  tomorrowData,
  currentHour,
  resolution,
}) => {
  const [isDarkMode, setIsDarkMode] = useState(
    document.documentElement.classList.contains('dark')
  );

  useEffect(() => {
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
          setIsDarkMode(document.documentElement.classList.contains('dark'));
        }
      });
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  const segments = buildSegments(hourlyData, tomorrowData, resolution);
  const hasTomorrow = tomorrowData && tomorrowData.length > 0;
  const maxHour = hasTomorrow ? 48 : 24;

  // Determine which intents are actually used (for legend)
  const usedIntents = new Set(segments.map(s => s.intent));

  // Tick marks every 2 hours for readability
  const ticks: number[] = [];
  for (let h = 0; h <= maxHour; h += 2) {
    ticks.push(h);
  }

  // Layout constants
  const labelWidth = 80;
  const rightPad = 16;
  const barHeight = 28;
  const tickHeight = 6;

  const [tooltipData, setTooltipData] = useState<{ segment: Segment; x: number; y: number } | null>(null);

  return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
      <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Battery Mode Schedule</h3>

      <div className="relative">
        {/* SVG timeline */}
        <svg
          width="100%"
          viewBox={`0 0 1000 ${barHeight + 30}`}
          preserveAspectRatio="xMidYMid meet"
          className="overflow-visible"
        >
          {/* Bar segments */}
          {segments.map((seg, i) => {
            const barAreaWidth = 1000 - labelWidth - rightPad;
            const x = labelWidth + (seg.startHour / maxHour) * barAreaWidth;
            const width = ((seg.endHour - seg.startHour) / maxHour) * barAreaWidth;
            const config = INTENT_CONFIG[seg.intent];
            const color = isDarkMode ? config.darkColor : config.color;

            return (
              <rect
                key={i}
                x={x}
                y={0}
                width={Math.max(width - 0.5, 0.5)}
                height={barHeight}
                rx={i === 0 ? 4 : 0}
                ry={i === 0 ? 4 : 0}
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
            const barAreaWidth = 1000 - labelWidth - rightPad;
            const markerX = labelWidth + (currentHour / maxHour) * barAreaWidth;
            return (
              <g>
                <line
                  x1={markerX}
                  y1={-2}
                  x2={markerX}
                  y2={barHeight + 2}
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

          {/* Label */}
          <text
            x={labelWidth - 8}
            y={barHeight / 2}
            textAnchor="end"
            dominantBaseline="central"
            className="text-sm"
            fill={isDarkMode ? '#d1d5db' : '#374151'}
            fontSize={13}
          >
            Battery
          </text>

          {/* Time axis ticks and labels */}
          {ticks.map((hour) => {
            const barAreaWidth = 1000 - labelWidth - rightPad;
            const x = labelWidth + (hour / maxHour) * barAreaWidth;
            return (
              <g key={hour}>
                <line
                  x1={x}
                  y1={barHeight}
                  x2={x}
                  y2={barHeight + tickHeight}
                  stroke={isDarkMode ? '#6b7280' : '#9ca3af'}
                  strokeWidth={1}
                />
                <text
                  x={x}
                  y={barHeight + tickHeight + 12}
                  textAnchor="middle"
                  fill={isDarkMode ? '#9ca3af' : '#6b7280'}
                  fontSize={11}
                >
                  {(hour % 24).toString().padStart(2, '0')}:00
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
              {INTENT_CONFIG[tooltipData.segment.intent].label}
            </p>
            <p className="text-xs text-gray-600 dark:text-gray-400">
              {formatHour(tooltipData.segment.startHour)} - {formatHour(tooltipData.segment.endHour)}
              {tooltipData.segment.isTomorrow && ' (Tomorrow)'}
            </p>
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap justify-center gap-4 mt-3 text-sm">
        {INTENT_ORDER.filter(intent => usedIntents.has(intent)).map((intent) => {
          const config = INTENT_CONFIG[intent];
          const color = isDarkMode ? config.darkColor : config.color;
          return (
            <div key={intent} className="flex items-center">
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
