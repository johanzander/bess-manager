// Shared look and number format of the Performance view and its parts.
export const panel = 'min-w-0 bg-white dark:bg-gray-800 rounded-lg shadow p-5 space-y-3';

export const number = (value: number | null | undefined, unit: string) =>
  value == null
    ? 'N/A'
    : `${value.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 })} ${unit}`;
