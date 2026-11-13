import { useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { intentLabel } from '../utils/intent';
import { useForceMode } from './ForceModeContext';

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export default function ForceModeBanner() {
  const { state, clear } = useForceMode();
  const [error, setError] = useState<string | null>(null);

  const handleClear = async () => {
    try {
      await clear();
      setError(null);
    } catch (err) {
      console.error('Failed to clear force mode:', err);
      setError('Failed to return to automatic');
    }
  };

  if (!state?.active || !state.mode) return null;

  return (
    <div className="bg-amber-100 dark:bg-amber-900/30 border-b border-amber-300 dark:border-amber-700 px-4 py-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
      <div className="flex items-start gap-2 text-sm min-w-0">
        <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" />
        <p>
          <span className="font-medium text-amber-700 dark:text-amber-300">
            Force mode: {intentLabel(state.mode)}
          </span>
          <span className="text-gray-600 dark:text-gray-400">
            {' — optimizer plan overridden'}
            {state.activatedAt && ` since ${formatTime(state.activatedAt)}`}
          </span>
          {error && <span className="ml-2 text-red-600 dark:text-red-400">{error}</span>}
        </p>
      </div>
      <button
        onClick={handleClear}
        className="px-3 py-1 text-xs font-medium text-white bg-amber-600 rounded-md hover:bg-amber-500 whitespace-nowrap"
      >
        Return to automatic
      </button>
    </div>
  );
}
