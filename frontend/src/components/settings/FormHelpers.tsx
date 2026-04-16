import React from 'react';

export function numField(
  label: string,
  value: number,
  onChange: (_: number) => void,
  opts: { min?: number; max?: number; step?: number; unit?: string; readOnly?: boolean } = {},
) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
        {label}{opts.unit ? ` (${opts.unit})` : ''}
      </span>
      <input
        type="number"
        min={opts.min}
        max={opts.max}
        step={opts.step ?? 'any'}
        value={value}
        readOnly={opts.readOnly}
        onChange={e => { const n = parseFloat(e.target.value); if (!Number.isNaN(n)) onChange(n); }}
        className={`mt-1 block w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500
          ${opts.readOnly
            ? 'bg-gray-50 dark:bg-gray-700/50 border-gray-200 dark:border-gray-600 text-gray-500 dark:text-gray-400 cursor-default'
            : 'bg-white dark:bg-gray-700 border-gray-300 dark:border-gray-600 text-gray-900 dark:text-white'}`}
      />
    </label>
  );
}

export function SectionCard({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100 dark:border-gray-700/60">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-white">{title}</h3>
        {description && (
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{description}</p>
        )}
      </div>
      <div className="px-5 py-4 space-y-4">{children}</div>
    </div>
  );
}

export function txtInput(
  label: string,
  value: string,
  onChange: (_: string) => void,
  placeholder = '',
  opts: { readOnly?: boolean } = {},
) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">{label}</span>
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        readOnly={opts.readOnly}
        onChange={e => { if (!opts.readOnly) onChange(e.target.value); }}
        className={`mt-1 block w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500
          ${opts.readOnly
            ? 'bg-gray-50 dark:bg-gray-700/50 border-gray-200 dark:border-gray-600 text-gray-500 dark:text-gray-400 cursor-default'
            : 'bg-white dark:bg-gray-700 border-gray-300 dark:border-gray-600 text-gray-900 dark:text-white'}`}
      />
    </label>
  );
}

export function radioGroup<T extends string>(
  label: string,
  options: { value: T; label: string }[],
  value: T,
  onChange: (_: T) => void,
) {
  return (
    <div className="space-y-1">
      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">{label}</span>
      <div className="flex flex-wrap gap-x-5 gap-y-1 pt-1">
        {options.map(opt => (
          <label key={opt.value} className="flex items-center space-x-2 cursor-pointer">
            <input
              type="radio"
              name={label}
              value={opt.value}
              checked={value === opt.value}
              onChange={() => onChange(opt.value)}
              className="text-blue-500"
            />
            <span className="text-sm text-gray-700 dark:text-gray-300">{opt.label}</span>
          </label>
        ))}
      </div>
    </div>
  );
}

export function toggle(label: string, value: boolean, onChange: (_: boolean) => void) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">{label}</span>
      <button
        type="button"
        onClick={() => onChange(!value)}
        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 ${value ? 'bg-blue-500' : 'bg-gray-300 dark:bg-gray-600'}`}
      >
        <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${value ? 'translate-x-6' : 'translate-x-1'}`} />
      </button>
    </div>
  );
}
