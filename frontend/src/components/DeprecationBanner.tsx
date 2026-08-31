import React, { useState } from 'react';
import { Info, X, ExternalLink } from 'lucide-react';

const DISMISS_KEY = 'bess.influxdbDeprecationDismissed';

const MIGRATION_URL =
  'https://github.com/johanzander/bess-manager/blob/main/docs/INSTALLATION.md#migrating-from-the-influxdb-add-on';

function readDismissed(): boolean {
  try {
    return localStorage.getItem(DISMISS_KEY) === '1';
  } catch {
    return false;
  }
}

/**
 * One-time notice for installs that still have an `influxdb:` block in the
 * add-on options (issue #722). BESS no longer reads InfluxDB — history now
 * comes from Home Assistant's recorder — and the option is removed a release
 * or so from now. Dismissal is per-browser (localStorage), not server state.
 */
const DeprecationBanner: React.FC<{ show: boolean }> = ({ show }) => {
  const [dismissed, setDismissed] = useState(readDismissed);

  if (!show || dismissed) return null;

  const dismiss = () => {
    try {
      localStorage.setItem(DISMISS_KEY, '1');
    } catch {
      /* private mode / storage blocked — banner just reappears next load */
    }
    setDismissed(true);
  };

  return (
    <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-4 mb-6">
      <div className="flex items-start space-x-3">
        <Info className="h-5 w-5 text-amber-600 dark:text-amber-400 mt-0.5 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-amber-800 dark:text-amber-300 mb-1">
            InfluxDB support is going away
          </h3>
          <div className="text-sm text-amber-700 dark:text-amber-300 space-y-1">
            <p>
              BESS now reads historical energy data from Home Assistant&apos;s built-in
              recorder. The <code>influxdb</code> add-on option is no longer used and will
              be removed in an update about a month from now.
            </p>
            <p>
              No action is needed for most installs. If you set your{' '}
              <code>recorder:</code> config to <strong>exclude</strong> the BESS sensors,
              or run <code>purge_keep_days</code> below&nbsp;2, widen it so at least two
              days of history is kept. Your InfluxDB database and the{' '}
              <code>influxdb:</code> integration that writes to it are unaffected.
            </p>
          </div>
          <div className="mt-3">
            <a
              href={MIGRATION_URL}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center px-3 py-1.5 text-sm font-medium text-amber-800 dark:text-amber-300 bg-amber-100 dark:bg-amber-800/30 hover:bg-amber-200 dark:hover:bg-amber-800/50 rounded-md transition-colors duration-200"
            >
              <ExternalLink className="h-3.5 w-3.5 mr-1" />
              Migration notes
            </a>
          </div>
        </div>
        <button
          onClick={dismiss}
          className="p-1 text-amber-400 dark:text-amber-500 hover:text-amber-600 dark:hover:text-amber-300 transition-colors duration-200"
          aria-label="Dismiss"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
};

export default DeprecationBanner;
