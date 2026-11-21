import React from 'react';
import { HourlyStrategyRow } from '../../utils/performance';

/**
 * Day x hour grid of the grid-cost difference (actual minus hindsight). Red
 * hours are where hindsight was cheaper, blue where actual was; grey hours are
 * unknown. Colour depth is relative to the largest hour in the period.
 */
const MissedValueHeatmap: React.FC<{
  rows: HourlyStrategyRow[];
  timeZone: string;
  format: (value: number) => string;
}> = ({ rows, timeZone, format }) => {
  const hourOf = (iso: string) =>
    Number(new Date(iso).toLocaleString('en-GB', { timeZone, hour: '2-digit', hour12: false })) %
    24;
  const days = [...new Set(rows.map(row => row.date))];
  const cell = new Map(rows.map(row => [`${row.date}|${hourOf(row.hour)}`, row]));
  const largest = Math.max(1e-9, ...rows.map(row => Math.abs(row.costDifference ?? 0)));
  return (
    <div className="overflow-x-auto">
      <div className="min-w-[640px] space-y-px text-xs">
        <div className="grid grid-cols-[4rem_repeat(24,1fr)] gap-px text-gray-500 dark:text-gray-400">
          <span />
          {Array.from({ length: 24 }, (_, hour) => (
            <span key={hour} className="text-center">
              {hour % 3 === 0 ? String(hour).padStart(2, '0') : ''}
            </span>
          ))}
        </div>
        {days.map(day => (
          <div key={day} className="grid grid-cols-[4rem_repeat(24,1fr)] gap-px">
            <span className="text-gray-600 dark:text-gray-300">{day.slice(5)}</span>
            {Array.from({ length: 24 }, (_, hour) => {
              const row = cell.get(`${day}|${hour}`);
              const value = row?.costDifference;
              const depth = value == null ? 0 : Math.min(1, Math.abs(value) / largest);
              return (
                <span
                  key={hour}
                  className="h-4 rounded-sm"
                  style={{
                    backgroundColor:
                      value == null
                        ? 'rgba(156,163,175,0.25)'
                        : value >= 0
                          ? `rgba(239,68,68,${0.1 + 0.85 * depth})`
                          : `rgba(59,130,246,${0.1 + 0.85 * depth})`,
                  }}
                  title={
                    value == null
                      ? `${day} ${hour}:00 unknown`
                      : `${day} ${hour}:00 · ${value >= 0 ? 'hindsight' : 'actual'} ${format(Math.abs(value))} cheaper`
                  }
                />
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
};

export default MissedValueHeatmap;
