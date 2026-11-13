import { useState } from 'react';
import { intentLabel } from '../utils/intent';
import { useForceMode } from './ForceModeContext';

export default function ForceModeControl() {
  const { state, setMode, clear } = useForceMode();
  const [pendingMode, setPendingMode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const apply = async (action: () => Promise<void>, failure: string) => {
    try {
      await action();
      setError(null);
    } catch (err) {
      console.error(failure, err);
      setError(failure);
    } finally {
      setPendingMode(null);
    }
  };

  if (!state) return null;

  return (
    <div className="bg-white dark:bg-gray-800 p-4 rounded-lg shadow space-y-3">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Force mode</h3>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Override the optimizer plan until you return to automatic
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex flex-wrap bg-gray-100 dark:bg-gray-700 rounded-lg p-1">
            {state.supportedModes.map((mode) => (
              <button
                key={mode}
                onClick={() => setPendingMode(mode)}
                className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  state.active && state.mode === mode
                    ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                    : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white'
                }`}
              >
                {intentLabel(mode)}
              </button>
            ))}
          </div>
          {state.active && (
            <button
              onClick={() => apply(clear, 'Failed to return to automatic')}
              className="px-3 py-2 text-sm text-gray-600 dark:text-gray-400 bg-gray-200 dark:bg-gray-700 rounded-md hover:bg-gray-300 dark:hover:bg-gray-600"
            >
              Return to automatic
            </button>
          )}
        </div>
      </div>
      {pendingMode && (
        <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-300 dark:border-yellow-700 rounded-lg p-4">
          <p className="text-sm text-yellow-800 dark:text-yellow-300 font-medium">
            Force {intentLabel(pendingMode)}?
          </p>
          <p className="text-xs text-gray-600 dark:text-gray-400 mt-1">
            The optimizer plan is overridden until you return to automatic. Selling to Grid and
            Charging from Grid run at maximum power until cleared.
          </p>
          <div className="flex gap-2 mt-3">
            <button
              onClick={() => setPendingMode(null)}
              className="px-3 py-1.5 text-xs text-gray-600 dark:text-gray-400 bg-gray-200 dark:bg-gray-700 rounded hover:bg-gray-300 dark:hover:bg-gray-600"
            >
              Cancel
            </button>
            <button
              onClick={() => apply(() => setMode(pendingMode), 'Failed to set force mode')}
              className="px-3 py-1.5 text-xs text-white bg-amber-600 rounded hover:bg-amber-500"
            >
              Force {intentLabel(pendingMode)}
            </button>
          </div>
        </div>
      )}
      {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
    </div>
  );
}
