import React from 'react';
import { PerformanceResult } from '../../types';
import { coverageRuns, CoverageStatus } from '../../utils/performance';

const STYLE: Record<CoverageStatus, { label: string; color: string }> = {
  observed: { label: 'Observed', color: 'bg-emerald-500' },
  backup: { label: 'Backup use (below reserve)', color: 'bg-purple-500' },
  restart: { label: 'Restart placeholder', color: 'bg-gray-600' },
  unknown: { label: 'Unknown / not recorded', color: 'bg-gray-300 dark:bg-gray-600' },
  invalid: { label: 'Invalid record', color: 'bg-red-500' },
};

/** One thin timeline of every expected quarter, coloured by how it was used. */
const CoverageStrip: React.FC<{ data: PerformanceResult }> = ({ data }) => {
  const runs = coverageRuns(data);
  const total = runs.reduce((sum, run) => sum + run.quarters, 0);
  if (!total) return null;
  const counts = runs.reduce<Partial<Record<CoverageStatus, number>>>((all, run) => {
    all[run.status] = (all[run.status] ?? 0) + run.quarters;
    return all;
  }, {});
  return (
    <div className="space-y-1">
      <div
        className="flex h-3 w-full overflow-hidden rounded"
        role="img"
        aria-label={`Coverage: ${counts.observed ?? 0} of ${total} quarters observed`}
      >
        {runs.map(run => (
          <div
            key={run.start}
            className={STYLE[run.status].color}
            style={{ width: `${(100 * run.quarters) / total}%` }}
            title={`${STYLE[run.status].label}: ${run.quarters} quarter(s) from ${run.start}`}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-600 dark:text-gray-300">
        {(Object.keys(STYLE) as CoverageStatus[])
          .filter(status => counts[status])
          .map(status => (
            <span key={status} className="flex items-center gap-1">
              <span className={`inline-block h-2 w-3 rounded-sm ${STYLE[status].color}`} />
              {STYLE[status].label} {counts[status]}
            </span>
          ))}
      </div>
    </div>
  );
};

export default CoverageStrip;
