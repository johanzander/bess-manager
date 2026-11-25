import React from 'react';

export interface CostScenario {
  label: string;
  cost: number;
  description: string;
  tone: 'baseline' | 'actual' | 'hindsight';
}

const COLOR: Record<CostScenario['tone'], string> = {
  baseline: 'bg-gray-400',
  actual: 'bg-blue-500',
  hindsight: 'bg-emerald-500',
};

/** Every total uses the same zero, including net-revenue periods below zero. */
const CostComparison: React.FC<{
  scenarios: CostScenario[];
  format: (value: number) => string;
  batteryBenefit: number | null;
}> = ({ scenarios, format, batteryBenefit }) => {
  const low = Math.min(0, ...scenarios.map(row => row.cost));
  const high = Math.max(0, ...scenarios.map(row => row.cost));
  const range = high - low || 1;
  const extraCost = batteryBenefit != null && batteryBenefit < 0;
  return (
    <>
      <div className="space-y-5" role="list" aria-label="Scenario costs">
        {scenarios.map(row => (
          <div key={row.label} role="listitem" className="space-y-1.5">
            <div className="flex items-baseline justify-between gap-3 text-sm font-semibold">
              <span>{row.label}</span>
              <span className="shrink-0 tabular-nums">{format(row.cost)}</span>
            </div>
            <div
              className="relative h-3 rounded-full bg-gray-100 dark:bg-gray-700"
              aria-hidden="true"
            >
              {low < 0 && (
                <div
                  className="absolute inset-y-0 border-l border-gray-500 dark:border-gray-300"
                  style={{ left: `${(-low / range) * 100}%` }}
                />
              )}
              <div
                className={`absolute inset-y-0 rounded-full ${COLOR[row.tone]}`}
                style={{
                  left: `${((Math.min(0, row.cost) - low) / range) * 100}%`,
                  width: `${(Math.abs(row.cost) / range) * 100}%`,
                }}
              />
            </div>
            <p className="text-sm text-gray-600 dark:text-gray-300">{row.description}</p>
          </div>
        ))}
      </div>
      <p className="text-xs text-gray-500 dark:text-gray-400">
        Same scale from zero.{low < 0 ? ' Bars left of zero show net revenue.' : ''}
      </p>
      <div className="flex flex-wrap items-baseline justify-between gap-3 border-t border-gray-200 dark:border-gray-700 pt-4">
        <h3 className="font-semibold">
          Estimated battery {extraCost ? 'extra cost' : 'benefit'} vs solar only
        </h3>
        <p
          className={`text-xl font-semibold tabular-nums ${extraCost ? 'text-red-600 dark:text-red-400' : 'text-emerald-600 dark:text-emerald-400'}`}
        >
          {batteryBenefit == null ? 'N/A' : format(Math.abs(batteryBenefit))}
        </p>
      </div>
    </>
  );
};

export default CostComparison;
