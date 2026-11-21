import React from 'react';

export interface WaterfallStep {
  label: string;
  from: number;
  to: number;
  kind: 'total' | 'saving' | 'gap';
}

const COLOR: Record<WaterfallStep['kind'], string> = {
  total: 'bg-gray-500 dark:bg-gray-400',
  saving: 'bg-emerald-500',
  gap: 'bg-amber-400',
};

/**
 * Cost steps from grid-only down to hindsight. Totals are bars from the axis
 * start; savings and the missed gap float between their two totals. The axis
 * starts above zero so euro differences stay visible, and says so.
 */
const CostWaterfall: React.FC<{
  steps: WaterfallStep[];
  format: (value: number) => string;
}> = ({ steps, format }) => {
  const values = steps.flatMap(step => [step.from, step.to]);
  const high = Math.max(...values);
  const low = Math.min(...values);
  const axisStart = Math.max(0, low - (high - low) * 0.35);
  const scale = (value: number) => (100 * (value - axisStart)) / (high - axisStart);
  return (
    <div className="space-y-1.5" role="list" aria-label="Cost waterfall">
      {steps.map(step => {
        const left = scale(Math.min(step.from, step.to));
        const width = Math.max(0.4, Math.abs(scale(step.to) - scale(step.from)));
        return (
          <div
            key={step.label}
            role="listitem"
            className="grid grid-cols-[minmax(7rem,13rem)_1fr_7rem] items-center gap-3 text-sm"
          >
            <span className={step.kind === 'total' ? 'font-semibold' : ''}>{step.label}</span>
            <div className="relative h-6 rounded bg-gray-100 dark:bg-gray-700">
              <div
                className={`absolute inset-y-0 rounded ${COLOR[step.kind]}`}
                style={
                  step.kind === 'total'
                    ? { left: 0, width: `${scale(step.to)}%` }
                    : { left: `${left}%`, width: `${width}%` }
                }
              />
            </div>
            <span className="text-right tabular-nums font-semibold">
              {step.kind === 'total' ? format(step.to) : `−${format(step.from - step.to)}`}
            </span>
          </div>
        );
      })}
      <p className="text-xs text-gray-500 dark:text-gray-400">
        Axis starts at {format(axisStart)} so the differences are visible.
      </p>
    </div>
  );
};

export default CostWaterfall;
