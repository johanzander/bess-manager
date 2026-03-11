import React, { useState, useEffect } from 'react';
import { AlertTriangle, X, CheckCircle } from 'lucide-react';

interface RuntimeFailure {
  id: string;
  timestamp: string;
  operation: string;
  category: string;
  error_message: string;
  error_type: string;
  retry_count: number;
  context?: Record<string, unknown>;
}

interface RuntimeFailureAlertsProps {
  failures: RuntimeFailure[];
  onDismiss: (failureId: string) => void;
  onDismissAll: () => void;
}

export const RuntimeFailureAlerts: React.FC<RuntimeFailureAlertsProps> = ({
  failures,
  onDismiss,
  onDismissAll,
}) => {
  const [expandedFailures, setExpandedFailures] = useState<Set<string>>(new Set());

  const toggleExpanded = (failureId: string) => {
    const newExpanded = new Set(expandedFailures);
    if (newExpanded.has(failureId)) {
      newExpanded.delete(failureId);
    } else {
      newExpanded.add(failureId);
    }
    setExpandedFailures(newExpanded);
  };

  const formatTimestamp = (timestamp: string) => {
    try {
      return new Date(timestamp).toLocaleString();
    } catch {
      return timestamp;
    }
  };

  const getCategoryColor = (category: string) => {
    switch (category) {
      case 'battery_control':
        return 'border-orange-500 bg-orange-50 dark:bg-orange-950/30';
      case 'inverter_control':
        return 'border-red-500 bg-red-50 dark:bg-red-950/30';
      case 'sensor_read':
        return 'border-yellow-500 bg-yellow-50 dark:bg-yellow-950/30';
      default:
        return 'border-gray-500 bg-gray-50 dark:bg-gray-800';
    }
  };

  if (failures.length === 0) {
    return null;
  }

  return (
    <div className="mb-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-5 w-5 text-red-500" />
          <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            Runtime Errors ({failures.length})
          </h3>
        </div>
        {failures.length > 1 && (
          <button
            onClick={onDismissAll}
            className="px-3 py-1 text-sm bg-red-100 hover:bg-red-200 text-red-700 dark:bg-red-900/50 dark:hover:bg-red-900/70 dark:text-red-300 rounded-md transition-colors"
          >
            Dismiss All
          </button>
        )}
      </div>

      <div className="space-y-3">
        {failures.map((failure) => (
          <div
            key={failure.id}
            className={`border-l-4 p-4 rounded-r-md ${getCategoryColor(failure.category)}`}
          >
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-2">
                  <AlertTriangle className="h-4 w-4 text-red-500 flex-shrink-0" />
                  <span className="font-medium text-gray-900 dark:text-gray-100">{failure.operation}</span>
                  <span className="text-xs px-2 py-1 bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-300 rounded">
                    {failure.category.replace('_', ' ')}
                  </span>
                </div>

                <div className="text-sm text-gray-600 dark:text-gray-400 mb-2">
                  <div>Time: {formatTimestamp(failure.timestamp)}</div>
                  <div>Error: {failure.error_type}</div>
                  {failure.retry_count > 0 && (
                    <div>Retries: {failure.retry_count}</div>
                  )}
                </div>

                {expandedFailures.has(failure.id) && (
                  <div className="mt-3 p-3 bg-white dark:bg-gray-800 rounded border dark:border-gray-700 text-sm">
                    <strong className="dark:text-gray-200">Details:</strong>
                    <pre className="mt-1 whitespace-pre-wrap font-mono text-xs dark:text-gray-300">
                      {failure.error_message}
                    </pre>
                    {failure.context && Object.keys(failure.context).length > 0 && (
                      <div className="mt-3">
                        <strong className="dark:text-gray-200">Parameters:</strong>
                        <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                          {Object.entries(failure.context).map(([key, value]) => (
                            <React.Fragment key={key}>
                              <dt className="font-mono text-gray-500 dark:text-gray-400">{key}</dt>
                              <dd className="font-mono dark:text-gray-300">{String(value)}</dd>
                            </React.Fragment>
                          ))}
                        </dl>
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2 ml-4">
                <button
                  onClick={() => toggleExpanded(failure.id)}
                  className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 p-1"
                  title={expandedFailures.has(failure.id) ? 'Hide details' : 'Show details'}
                >
                  {expandedFailures.has(failure.id) ? '−' : '+'}
                </button>
                <button
                  onClick={() => onDismiss(failure.id)}
                  className="text-gray-500 hover:text-red-600 dark:text-gray-400 dark:hover:text-red-400 p-1"
                  title="Dismiss this error"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};