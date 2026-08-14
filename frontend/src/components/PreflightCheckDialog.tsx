import { useState, useEffect } from 'react';
import { CheckCircle, XCircle, AlertTriangle } from 'lucide-react';
import api from '../lib/api';

interface PreflightCheck {
  name: string;
  status: 'pending' | 'ok' | 'warning' | 'error';
  description?: string;
}

/** Map a backend health-check component onto a dialog row status.
 *
 * Only `error` blocks live control. Optional components (`required === false`)
 * can never block, but a genuinely failing one still has to look different
 * from a healthy one — `check_historical_data_access()` reports
 * `required: false` with `status: "ERROR"` when InfluxDB is misconfigured, and
 * that used to render as a green check.
 *
 * A required component reporting WARNING does not block: `determine_health_status`
 * returns ERROR whenever any required method is not working, so WARNING on a
 * required component can only mean an *optional* member of it failed. Blocking
 * on that would stop a user leaving demo mode over e.g. a NaN solar forecast
 * (#558, where "Energy Prediction" became required under the sensor strategy
 * while its solar-forecast member stayed optional).
 */
function toRowStatus(status: string, required?: boolean): 'ok' | 'warning' | 'error' {
  if (status === 'OK') return 'ok';
  if (required === false) {
    // Not configuring an optional component is a deliberate choice, not a fault.
    return status === 'NOT_CONFIGURED' ? 'ok' : 'warning';
  }
  return status === 'ERROR' ? 'error' : 'warning';
}

interface PreflightCheckDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

export default function PreflightCheckDialog({ open, onClose, onConfirm }: PreflightCheckDialogProps) {
  const [checks, setChecks] = useState<PreflightCheck[]>([]);
  const [loading, setLoading] = useState(true);
  const [allPassed, setAllPassed] = useState(false);
  const [enabling, setEnabling] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setAllPassed(false);

    api.get('/api/system-health')
      .then(({ data }) => {
        const results: PreflightCheck[] = (data.checks || []).map((c: { name: string; status: string; description?: string; required?: boolean }) => ({
          name: c.name,
          status: toRowStatus(c.status, c.required),
          description: c.description,
        }));
        setChecks(results);
        setAllPassed(results.every(c => c.status !== 'error'));
      })
      .catch(() => {
        setChecks([{ name: 'System Health', status: 'error', description: 'Unable to run health checks' }]);
        setAllPassed(false);
      })
      .finally(() => setLoading(false));
  }, [open]);

  if (!open) return null;

  const hasWarning = checks.some(c => c.status === 'warning');

  const handleConfirm = async () => {
    setEnabling(true);
    try {
      await api.patch('/api/settings', { demoMode: { enabled: false } });
      onConfirm();
    } catch {
      // Error handled by caller
    } finally {
      setEnabling(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="w-full max-w-md mx-4 bg-white dark:bg-gray-800 rounded-xl shadow-xl border border-gray-200 dark:border-gray-700 p-6"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Enable Live Control</h3>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          {loading ? 'Running pre-flight checks...' : 'Pre-flight check results'}
        </p>

        <div className="mt-4 space-y-2">
          {loading ? (
            <div className="flex items-center gap-2 text-gray-400">
              <div className="h-4 w-4 border-2 border-gray-400 rounded-full border-t-transparent animate-spin" />
              <span className="text-sm">Checking system health...</span>
            </div>
          ) : (
            checks.map((check) => (
              <div key={check.name} className="flex items-center gap-2">
                {check.status === 'ok' ? (
                  <CheckCircle className="h-4 w-4 text-green-500" />
                ) : check.status === 'warning' ? (
                  <AlertTriangle className="h-4 w-4 text-amber-500" />
                ) : (
                  <XCircle className="h-4 w-4 text-red-500" />
                )}
                <span className="text-sm text-gray-700 dark:text-gray-200">{check.name}</span>
              </div>
            ))
          )}
        </div>

        {!loading && allPassed && !hasWarning && (
          <div className="mt-4 p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-700 rounded-lg text-xs text-green-700 dark:text-green-400">
            All checks passed. The system will start controlling your inverter on the next optimization cycle.
          </div>
        )}

        {!loading && allPassed && hasWarning && (
          <div className="mt-4 p-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 rounded-lg text-xs text-amber-700 dark:text-amber-400">
            Required checks passed, but some optional components reported problems. Live control can be enabled — see Settings → System for details.
          </div>
        )}

        {!loading && !allPassed && (
          <div className="mt-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700 rounded-lg text-xs text-red-700 dark:text-red-400">
            Some checks failed. Resolve the issues before enabling live control.
          </div>
        )}

        <div className="flex gap-3 mt-6">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 text-sm text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-700 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={loading || !allPassed || enabling}
            className="flex-1 px-4 py-2 text-sm font-semibold text-white bg-green-600 rounded-lg hover:bg-green-500 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {enabling ? 'Enabling...' : 'Enable Live Control'}
          </button>
        </div>
      </div>
    </div>
  );
}
