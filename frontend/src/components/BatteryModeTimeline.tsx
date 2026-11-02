import React, { useState, useEffect } from 'react';
import { useDashboardData } from '../hooks/useDashboardData';
import { DashboardHourlyData } from '../api/scheduleApi';
import { useUserPreferences, ScheduleLayout } from '../hooks/useUserPreferences';
import { getIntent, isCurtailed, StrategicIntent } from '../utils/intent';

// Refresh cadence matches other components that self-fetch quarter-hourly
// dashboard data (EnergyFlowCards, SystemStatusCard).
const REFRESH_INTERVAL_MS = 60000;

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

// Four ways to read the same plan: one bar for the whole day (Bar), the day
// split into six-hour rows (Rows), an agenda of blocks (List), or the bar with
// the next few blocks under it (Bar + Next). The choice is a user preference.
const LAYOUTS: { key: ScheduleLayout; label: string }[] = [
  { key: 'bar', label: 'Bar' },
  { key: 'rows', label: 'Rows' },
  { key: 'list', label: 'List' },
  { key: 'combo', label: 'Bar + Next' },
];

interface BatteryModeTimelineProps {
  currentHour: number;
  // ISO date (YYYY-MM-DD) of a historical day to show; omit for today's live view.
  date?: string;
}

interface Segment {
  startHour: number;
  endHour: number;
  intent: StrategicIntent;
  legendKey: LegendKey;
  isTomorrow: boolean;
  isActual: boolean;
  socStart: number | null;
  socEnd: number | null;
  importKwh: number;
  exportKwh: number;
}

// Always builds segments at true quarter-hour granularity — the color bar
// must never go through hourly "dominant intent" aggregation, which can
// let a stale planned intent outvote what was actually observed (#486).
const STEP_HOURS = 0.25;

function value(v: { value?: number } | undefined | null): number | null {
  return v && typeof v.value === 'number' ? v.value : null;
}

function appendPeriods(
  segments: Segment[],
  periods: DashboardHourlyData[],
  offsetHours: number,
  isTomorrow: boolean
) {
  for (let i = 0; i < periods.length; i++) {
    const p = periods[i];
    const intent = getIntent(p);
    const legendKey: LegendKey = isCurtailed(p) ? 'CURTAILED' : intent;
    const isActual = p.dataSource === 'actual';
    const startHour = offsetHours + i * STEP_HOURS;
    const endHour = startHour + STEP_HOURS;

    const last = segments[segments.length - 1];
    // Also split where actuals end, so the segment in progress starts at "now".
    if (
      last &&
      last.legendKey === legendKey &&
      last.intent === intent &&
      last.isTomorrow === isTomorrow &&
      last.isActual === isActual &&
      Math.abs(last.endHour - startHour) < 0.01
    ) {
      last.endHour = endHour;
      last.socEnd = value(p.batterySocEnd) ?? last.socEnd;
      last.importKwh += value(p.gridImported) ?? 0;
      last.exportKwh += value(p.gridExported) ?? 0;
    } else {
      segments.push({
        startHour,
        endHour,
        intent,
        legendKey,
        isTomorrow,
        isActual,
        socStart: value(p.batterySocStart),
        socEnd: value(p.batterySocEnd),
        importKwh: value(p.gridImported) ?? 0,
        exportKwh: value(p.gridExported) ?? 0,
      });
    }
  }
}

function buildSegments(
  hourlyData: DashboardHourlyData[],
  tomorrowData: DashboardHourlyData[] | null | undefined
): Segment[] {
  const segments: Segment[] = [];
  appendPeriods(segments, hourlyData, 0, false);
  if (tomorrowData && tomorrowData.length > 0) {
    appendPeriods(segments, tomorrowData, 24, true);
  }
  return segments;
}

function formatHour(hour: number): string {
  const h = Math.floor(hour) % 24;
  const m = Math.round((hour - Math.floor(hour)) * 60);
  return h.toString().padStart(2, '0') + ':' + m.toString().padStart(2, '0');
}

function formatDuration(hours: number): string {
  const minutes = Math.round(hours * 60);
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

function segmentLabel(seg: Segment): string {
  // Curtailment doesn't replace the intent (a curtailed period can still be
  // charging, e.g. SOLAR_STORAGE) -- show both.
  return seg.legendKey === 'CURTAILED'
    ? `${INTENT_CONFIG[seg.intent].label} — Curtailed (No Export)`
    : INTENT_CONFIG[seg.legendKey].label;
}

function socText(seg: Segment): string | null {
  if (seg.socStart === null || seg.socEnd === null) return null;
  const a = Math.round(seg.socStart);
  const b = Math.round(seg.socEnd);
  return a === b ? `${a}%` : `${a}% → ${b}%`;
}

function gridText(seg: Segment): string | null {
  const parts: string[] = [];
  if (seg.importKwh >= 0.05) parts.push(`${seg.importKwh.toFixed(1)} kWh in`);
  if (seg.exportKwh >= 0.05) parts.push(`${seg.exportKwh.toFixed(1)} kWh out`);
  return parts.length ? parts.join(' · ') : null;
}

interface ViewProps {
  segments: Segment[];
  maxHour: number;
  nowHour: number | null; // null for a historical day
  isDarkMode: boolean;
}

function colorOf(seg: Segment, isDarkMode: boolean): string {
  const config = INTENT_CONFIG[seg.legendKey];
  return isDarkMode ? config.darkColor : config.color;
}

// Elapsed periods are dimmed so the eye lands on what is still to come.
function isPast(seg: Segment, nowHour: number | null): boolean {
  return nowHour !== null && seg.endHour <= nowHour;
}

const NowMarker: React.FC<{ leftPct: number }> = ({ leftPct }) => (
  <div
    className="absolute -top-1 -bottom-1 w-0.5 bg-gray-900 dark:bg-white pointer-events-none"
    style={{ left: `${leftPct}%` }}
    aria-hidden
  >
    <div className="absolute -top-1 -left-[3px] w-2 h-2 rounded-full bg-gray-900 dark:bg-white" />
  </div>
);

// Blocks select on hover and on click. Click never toggles off: a tap on a
// touch screen fires mouseenter and then click, so a toggle would select the
// block and immediately clear it again.
const SegmentDetail: React.FC<{ seg: Segment | null; isDarkMode: boolean }> = ({ seg, isDarkMode }) => {
  if (!seg) {
    return <p className="mt-2 text-xs text-gray-500 dark:text-gray-400 min-h-[2.5rem]">Tap a block for details</p>;
  }
  const soc = socText(seg);
  const grid = gridText(seg);
  return (
    <div className="mt-2 flex items-start gap-2 min-h-[2.5rem]">
      <span className="mt-1 w-3 h-3 rounded-sm shrink-0" style={{ backgroundColor: colorOf(seg, isDarkMode) }} />
      <div className="text-sm leading-tight">
        <p className="font-medium text-gray-900 dark:text-white">
          {segmentLabel(seg)}
          <span className="font-normal text-gray-500 dark:text-gray-400">
            {' '}· {formatHour(seg.startHour)}–{formatHour(seg.endHour)}{seg.isTomorrow && ' tomorrow'}
          </span>
        </p>
        <p className="text-xs text-gray-600 dark:text-gray-400">
          {[soc && `Battery ${soc}`, grid].filter(Boolean).join(' · ') || formatDuration(seg.endHour - seg.startHour)}
        </p>
      </div>
    </div>
  );
};

// --- Layout: Bar -------------------------------------------------------------
// One full-width bar with a fixed pixel height. On wide screens it keeps the
// 65px side insets so it lines up with the Energy Flow and SOC chart plot
// areas below; on a phone it uses the whole card width instead.
const BarView: React.FC<ViewProps & { showDetail?: boolean }> = ({ segments, maxHour, nowHour, isDarkMode, showDetail = true }) => {
  const [selected, setSelected] = useState<Segment | null>(null);
  const tickStep = maxHour > 24 ? 6 : 3;
  const ticks: number[] = [];
  for (let h = 0; h <= maxHour; h += 1) ticks.push(h);

  return (
    <div className="md:px-[65px]">
      <div className="relative">
        <div className="h-10 rounded-md overflow-hidden flex" onMouseLeave={() => setSelected(null)}>
          {segments.map((seg, i) => (
            <button
              key={i}
              type="button"
              data-segment
              aria-label={`${segmentLabel(seg)} ${formatHour(seg.startHour)} to ${formatHour(seg.endHour)}`}
              className={`h-full shrink-0 focus:outline-none ${selected === seg ? 'ring-2 ring-inset ring-white dark:ring-gray-900' : ''}`}
              style={{
                width: `${((seg.endHour - seg.startHour) / maxHour) * 100}%`,
                backgroundColor: colorOf(seg, isDarkMode),
                opacity: seg.isTomorrow ? 0.6 : isPast(seg, nowHour) ? 0.45 : 1,
              }}
              onMouseEnter={() => setSelected(seg)}
              onClick={() => setSelected(seg)}
            />
          ))}
        </div>
        {nowHour !== null && <NowMarker leftPct={(nowHour / maxHour) * 100} />}
      </div>
      <div className="relative h-5 mt-1">
        {ticks.map(hour => {
          const major = hour % tickStep === 0;
          return (
            <div
              key={hour}
              className={`absolute top-0 -translate-x-1/2 flex-col items-center ${major ? 'flex' : 'hidden md:flex'}`}
              style={{ left: `${(hour / maxHour) * 100}%` }}
            >
              <div className="w-px h-1 bg-gray-400 dark:bg-gray-500" />
              <span className="text-[11px] leading-none mt-0.5 text-gray-500 dark:text-gray-400 tabular-nums">
                {(hour % 24).toString().padStart(2, '0')}
              </span>
            </div>
          );
        })}
      </div>
      {showDetail && <SegmentDetail seg={selected} isDarkMode={isDarkMode} />}
    </div>
  );
};

// --- Layout: Rows ------------------------------------------------------------
// The day split into six-hour rows, each the full card width, so a
// quarter-hour block is ~14px wide on a phone instead of ~2px.
const ROW_HOURS = 6;

const RowsView: React.FC<ViewProps> = ({ segments, maxHour, nowHour, isDarkMode }) => {
  const [selected, setSelected] = useState<Segment | null>(null);
  const rows: number[] = [];
  for (let start = 0; start < maxHour; start += ROW_HOURS) rows.push(start);

  return (
    <div>
      <div className="space-y-2">
        {rows.map(rowStart => {
          const rowEnd = rowStart + ROW_HOURS;
          const rowSegs = segments.filter(s => s.endHour > rowStart && s.startHour < rowEnd);
          return (
            <React.Fragment key={rowStart}>
              {rowStart === 24 && (
                <p className="pt-2 text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400">Tomorrow</p>
              )}
              <div className="flex items-start gap-2">
                <span className="w-10 shrink-0 pt-2 text-xs tabular-nums text-gray-500 dark:text-gray-400">
                  {formatHour(rowStart)}
                </span>
                <div className="flex-1">
                  <div className="relative h-8 rounded bg-gray-100 dark:bg-gray-700">
                    <div className="absolute inset-0 rounded overflow-hidden">
                      {rowSegs.map((seg, i) => {
                        const a = Math.max(seg.startHour, rowStart);
                        const b = Math.min(seg.endHour, rowEnd);
                        return (
                          <button
                            key={i}
                            type="button"
                            data-segment
                            aria-label={`${segmentLabel(seg)} ${formatHour(seg.startHour)} to ${formatHour(seg.endHour)}`}
                            className={`absolute top-0 bottom-0 border-r border-white/40 dark:border-gray-800/40 focus:outline-none ${selected === seg ? 'ring-2 ring-inset ring-white dark:ring-gray-900' : ''}`}
                            style={{
                              left: `${((a - rowStart) / ROW_HOURS) * 100}%`,
                              width: `${((b - a) / ROW_HOURS) * 100}%`,
                              backgroundColor: colorOf(seg, isDarkMode),
                              opacity: isPast(seg, nowHour) ? 0.45 : 1,
                            }}
                            onMouseEnter={() => setSelected(seg)}
                            onClick={() => setSelected(seg)}
                          />
                        );
                      })}
                    </div>
                    {nowHour !== null && nowHour >= rowStart && nowHour < rowEnd && (
                      <NowMarker leftPct={((nowHour - rowStart) / ROW_HOURS) * 100} />
                    )}
                  </div>
                  <div className="relative h-3.5">
                    {Array.from({ length: ROW_HOURS - 1 }, (_, k) => rowStart + k + 1).map(hour => (
                      <span
                        key={hour}
                        className="absolute top-0.5 -translate-x-1/2 text-[10px] leading-none tabular-nums text-gray-400 dark:text-gray-500"
                        style={{ left: `${((hour - rowStart) / ROW_HOURS) * 100}%` }}
                      >
                        {(hour % 24).toString().padStart(2, '0')}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </React.Fragment>
          );
        })}
      </div>
      <SegmentDetail seg={selected} isDarkMode={isDarkMode} />
    </div>
  );
};

// --- Layout: List ------------------------------------------------------------
// An agenda: what the battery is doing now and what it plans next, one line
// per block, with the SOC change and grid energy that explain it. Elapsed
// blocks fold away behind a toggle.
const ListView: React.FC<ViewProps & { limit?: number }> = ({ segments, nowHour, isDarkMode, limit }) => {
  const [showPast, setShowPast] = useState(false);
  const [showAll, setShowAll] = useState(false);

  const past = segments.filter(s => isPast(s, nowHour));
  const upcoming = segments.filter(s => !isPast(s, nowHour));
  const visible = limit && !showAll ? upcoming.slice(0, limit) : upcoming;
  const hidden = upcoming.length - visible.length;

  const renderRow = (seg: Segment, i: number, list: Segment[]) => {
    const isNow = nowHour !== null && seg.startHour <= nowHour && nowHour < seg.endHour;
    const firstTomorrow = seg.isTomorrow && (i === 0 || !list[i - 1].isTomorrow);
    const soc = socText(seg);
    const grid = gridText(seg);
    return (
      <React.Fragment key={`${seg.startHour}-${seg.legendKey}`}>
        {firstTomorrow && (
          <li className="pt-3 pb-1 text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400">Tomorrow</li>
        )}
        <li
          data-segment
          className={`flex items-stretch gap-3 py-2 ${isNow ? 'bg-gray-50 dark:bg-gray-700/50 -mx-2 px-2 rounded-md' : ''} ${isPast(seg, nowHour) ? 'opacity-60' : ''}`}
        >
          <div className="w-1 rounded-full shrink-0" style={{ backgroundColor: colorOf(seg, isDarkMode) }} />
          <div className="w-[5.75rem] shrink-0 text-sm tabular-nums text-gray-700 dark:text-gray-300">
            {formatHour(seg.startHour)}–{formatHour(seg.endHour)}
            <div className="text-xs text-gray-500 dark:text-gray-400">{formatDuration(seg.endHour - seg.startHour)}</div>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-gray-900 dark:text-white">
              {segmentLabel(seg)}
              {isNow && (
                <span className="ml-2 align-middle text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded bg-gray-900 text-white dark:bg-white dark:text-gray-900">
                  Now
                </span>
              )}
            </p>
            {grid && <p className="text-xs text-gray-500 dark:text-gray-400">{grid}</p>}
          </div>
          {soc && <div className="shrink-0 text-xs tabular-nums text-gray-600 dark:text-gray-400 pt-0.5">{soc}</div>}
        </li>
      </React.Fragment>
    );
  };

  return (
    <div>
      {past.length > 0 && !limit && (
        <>
          <button
            type="button"
            className="text-xs text-blue-600 dark:text-blue-400 mb-1"
            onClick={() => setShowPast(!showPast)}
          >
            {showPast ? 'Hide' : 'Show'} earlier today ({past.length})
          </button>
          {showPast && (
            <ul className="divide-y divide-gray-100 dark:divide-gray-700 mb-2">
              {past.map((s, i) => renderRow(s, i, past))}
            </ul>
          )}
        </>
      )}
      <ul className="divide-y divide-gray-100 dark:divide-gray-700">
        {visible.map((s, i) => renderRow(s, i, visible))}
      </ul>
      {limit && (hidden > 0 || showAll) && (
        <button
          type="button"
          className="mt-1 text-xs text-blue-600 dark:text-blue-400"
          onClick={() => setShowAll(!showAll)}
        >
          {showAll ? 'Show less' : `Show ${hidden} more`}
        </button>
      )}
    </div>
  );
};

const Legend: React.FC<{ segments: Segment[]; isDarkMode: boolean }> = ({ segments, isDarkMode }) => {
  const used = new Set(segments.map(s => s.legendKey));
  return (
    <div className="flex flex-wrap justify-center gap-x-4 gap-y-1.5 mt-3 text-xs md:text-sm">
      {INTENT_ORDER.filter(key => used.has(key)).map(key => {
        const config = INTENT_CONFIG[key];
        return (
          <div key={key} className="flex items-center">
            <div
              className="w-3 h-3 rounded-sm mr-1.5"
              style={{ backgroundColor: isDarkMode ? config.darkColor : config.color }}
            />
            <span className="text-gray-700 dark:text-gray-300">{config.label}</span>
          </div>
        );
      })}
    </div>
  );
};

export const BatteryModeTimeline: React.FC<BatteryModeTimelineProps> = ({
  currentHour,
  date,
}) => {
  const [isDarkMode, setIsDarkMode] = useState(
    document.documentElement.classList.contains('dark')
  );
  const { scheduleLayout: layout, setScheduleLayout: setLayout } = useUserPreferences();

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDarkMode(document.documentElement.classList.contains('dark'));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  // A historical day is static, so skip the periodic refetch (0) for it.
  const { data, loading, error } = useDashboardData(date, 'quarter-hourly', date ? 0 : REFRESH_INTERVAL_MS);

  // useDashboardData sets loading=true on every periodic refetch too, not
  // just the first one — gate the skeleton on "no data yet" so a background
  // 60s refresh doesn't blank out an already-rendered timeline (#486).
  if (loading && !data) {
    return (
      <div className="bg-white dark:bg-gray-800 p-4 md:p-6 rounded-lg shadow animate-pulse">
        <div className="h-9 bg-gray-200 dark:bg-gray-700 rounded" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="bg-white dark:bg-gray-800 p-4 md:p-6 rounded-lg shadow text-red-600 text-center">
        {error || 'Failed to load schedule'}
      </div>
    );
  }

  const tomorrowData = data.tomorrowData;
  const segments = buildSegments(data.hourlyData, tomorrowData);
  const view: ViewProps = {
    segments,
    maxHour: tomorrowData && tomorrowData.length > 0 ? 48 : 24,
    nowHour: date ? null : currentHour,
    isDarkMode,
  };

  return (
    <div className="bg-white dark:bg-gray-800 p-4 md:p-6 rounded-lg shadow">
      <div className="flex justify-end mb-3">
        <div className="inline-flex rounded-md bg-gray-100 dark:bg-gray-700 p-0.5 text-xs" role="tablist" aria-label="Schedule layout">
          {LAYOUTS.map(l => (
            <button
              key={l.key}
              type="button"
              role="tab"
              aria-selected={layout === l.key}
              className={`px-2.5 py-1 rounded ${
                layout === l.key
                  ? 'bg-white dark:bg-gray-900 text-gray-900 dark:text-white shadow-sm'
                  : 'text-gray-600 dark:text-gray-300'
              }`}
              onClick={() => setLayout(l.key)}
            >
              {l.label}
            </button>
          ))}
        </div>
      </div>

      {layout === 'bar' && <BarView {...view} />}
      {layout === 'rows' && <RowsView {...view} />}
      {layout === 'list' && <ListView {...view} />}
      {layout === 'combo' && (
        <>
          <BarView {...view} showDetail={false} />
          <div className="mt-4">
            <ListView {...view} limit={4} />
          </div>
        </>
      )}

      {layout !== 'list' && <Legend segments={segments} isDarkMode={isDarkMode} />}
    </div>
  );
};
