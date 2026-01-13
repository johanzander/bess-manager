import React, { useState } from 'react';
import { AlertTriangle, X, ChevronDown, ChevronUp } from 'lucide-react';
import { RuntimeFailure } from '../types';

interface RuntimeFailureAlertsProps {
  failures: RuntimeFailure[];
  onDismiss: (failureId: string) => void;
  onDismissAll: () => void;
  className?: string;
}

const RuntimeFailureAlerts: React.FC<RuntimeFailureAlertsProps> = ({
  failures,
  onDismiss,
  onDismissAll,
  className = ''
}) => {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  if (failures.length === 0) {
    return null;
  }

  const toggleExpanded = (id: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const getCategoryLabel = (category: string): string => {
    const labels: Record<string, string> = {
      'TOU_SEGMENT': 'TOU Schedule',
      'POWER_RATE': 'Power Rate',
      'GRID_CHARGE': 'Grid Charging',
      'SOC_LIMIT': 'SOC Limit',
      'SENSOR_READ': 'Sensor Read',
      'API_OPERATION': 'API Operation'
    };
    return labels[category] || category;
  };

  const formatTimestamp = (timestamp: string): string => {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins} minute${diffMins !== 1 ? 's' : ''} ago`;

    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours} hour${diffHours !== 1 ? 's' : ''} ago`;

    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays} day${diffDays !== 1 ? 's' : ''} ago`;
  };

  return (
    <div className={`space-y-3 ${className}`}>
      {failures.map(failure => {
        const isExpanded = expandedIds.has(failure.id);

        return (
          <div
            key={failure.id}
            className="bg-amber-50 dark:bg-amber-900/20 border-l-4 border-amber-400 dark:border-amber-600 p-4 rounded shadow-sm"
          >
            <div className="flex items-start">
              <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-400 mt-0.5 flex-shrink-0" />

              <div className="ml-3 flex-1 min-w-0">
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <h4 className="text-sm font-semibold text-amber-800 dark:text-amber-300">
                      {getCategoryLabel(failure.category)} Failed
                    </h4>
                    <p className="text-sm text-amber-700 dark:text-amber-400 mt-1">
                      {failure.operation}
                    </p>
                    <p className="text-xs text-amber-600 dark:text-amber-500 mt-1">
                      {formatTimestamp(failure.timestamp)}
                    </p>
                  </div>

                  <button
                    onClick={() => onDismiss(failure.id)}
                    className="ml-3 text-amber-600 dark:text-amber-400 hover:text-amber-800 dark:hover:text-amber-200 transition-colors"
                    aria-label="Dismiss notification"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>

                {/* Expandable error details */}
                <button
                  onClick={() => toggleExpanded(failure.id)}
                  className="mt-2 flex items-center text-xs text-amber-700 dark:text-amber-400 hover:text-amber-900 dark:hover:text-amber-200 transition-colors"
                >
                  {isExpanded ? (
                    <>
                      <ChevronUp className="h-3 w-3 mr-1" />
                      Hide details
                    </>
                  ) : (
                    <>
                      <ChevronDown className="h-3 w-3 mr-1" />
                      Show error details
                    </>
                  )}
                </button>

                {isExpanded && (
                  <div className="mt-2 p-3 bg-amber-100 dark:bg-amber-900/40 rounded text-xs">
                    <p className="font-semibold text-amber-800 dark:text-amber-300 mb-1">
                      Error Message:
                    </p>
                    <p className="text-amber-700 dark:text-amber-400 font-mono whitespace-pre-wrap break-words">
                      {failure.errorMessage}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })}

      {/* Dismiss All button */}
      {failures.length > 1 && (
        <div className="flex justify-end">
          <button
            onClick={onDismissAll}
            className="text-sm text-amber-700 dark:text-amber-400 hover:text-amber-900 dark:hover:text-amber-200 font-medium transition-colors"
          >
            Dismiss All ({failures.length})
          </button>
        </div>
      )}
    </div>
  );
};

export default RuntimeFailureAlerts;
