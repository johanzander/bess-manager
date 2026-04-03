import React from 'react';
import { AlertTriangle, AlertCircle, X, ExternalLink } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

interface CriticalIssue {
  component: string;
  description: string;
  status: string;
}

interface AlertBannerProps {
  hasCriticalErrors: boolean;
  hasWarnings: boolean;
  criticalIssues: CriticalIssue[];
  totalCriticalIssues: number;
  onDismiss?: () => void;
  className?: string;
}

const AlertBanner: React.FC<AlertBannerProps> = ({
  hasCriticalErrors,
  hasWarnings,
  criticalIssues,
  onDismiss,
  className = ''
}) => {
  const navigate = useNavigate();

  if (!hasCriticalErrors && !hasWarnings) {
    return null;
  }

  const errors = criticalIssues.filter(i => i.status === 'ERROR');
  const warnings = criticalIssues.filter(i => i.status === 'WARNING');

  const handleViewDetails = () => {
    navigate('/system-health');
  };

  if (hasCriticalErrors) {
    return (
      <div className={`bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-6 ${className}`}>
        <div className="flex items-start space-x-3">
          <AlertTriangle className="h-5 w-5 text-red-600 dark:text-red-400 mt-0.5 flex-shrink-0" />

          <div className="flex-1 min-w-0">
            <h3 className="text-sm font-semibold text-red-800 dark:text-red-300 mb-1">
              Critical System Issues Detected
            </h3>

            <div className="text-sm text-red-700 dark:text-red-300 mb-3">
              {criticalIssues.length === 1 ? (
                <p>1 critical component is not functioning properly and may affect system operation.</p>
              ) : (
                <p>{criticalIssues.length} critical components are not functioning properly and may affect system operation.</p>
              )}
            </div>

            {errors.length > 0 && (
              <div className="mb-3">
                <ul className="space-y-1">
                  {errors.slice(0, 3).map((issue, index) => (
                    <li key={index} className="text-sm text-red-600 dark:text-red-400 flex items-center">
                      <span className="w-1.5 h-1.5 bg-red-500 rounded-full mr-2 flex-shrink-0"></span>
                      <span className="font-medium">{issue.component}:</span>
                      <span className="ml-1 truncate">{issue.description}</span>
                    </li>
                  ))}
                  {errors.length > 3 && (
                    <li className="text-sm text-red-600 dark:text-red-400 italic">
                      ... and {errors.length - 3} more issue{errors.length - 3 !== 1 ? 's' : ''}
                    </li>
                  )}
                </ul>
              </div>
            )}

            {warnings.length > 0 && (
              <div className="mb-3 border-t border-red-200 dark:border-red-700 pt-2">
                <p className="text-xs font-medium text-red-600 dark:text-red-400 mb-1">Also: {warnings.length} warning{warnings.length !== 1 ? 's' : ''}</p>
                <ul className="space-y-1">
                  {warnings.slice(0, 2).map((issue, index) => (
                    <li key={index} className="text-sm text-red-500 dark:text-red-400 flex items-center">
                      <span className="w-1.5 h-1.5 bg-red-400 rounded-full mr-2 flex-shrink-0"></span>
                      <span className="font-medium">{issue.component}:</span>
                      <span className="ml-1 truncate">{issue.description}</span>
                    </li>
                  ))}
                  {warnings.length > 2 && (
                    <li className="text-sm text-red-500 dark:text-red-400 italic">
                      ... and {warnings.length - 2} more
                    </li>
                  )}
                </ul>
              </div>
            )}

            <div className="flex flex-wrap gap-2">
              <button
                onClick={handleViewDetails}
                className="inline-flex items-center px-3 py-1.5 text-sm font-medium text-red-800 dark:text-red-300 bg-red-100 dark:bg-red-800/30 hover:bg-red-200 dark:hover:bg-red-800/50 rounded-md transition-colors duration-200"
              >
                <ExternalLink className="h-3.5 w-3.5 mr-1" />
                View Details & Fix
              </button>
            </div>
          </div>

          {onDismiss && (
            <button
              onClick={onDismiss}
              className="p-1 text-red-400 dark:text-red-500 hover:text-red-600 dark:hover:text-red-300 transition-colors duration-200"
              aria-label="Dismiss alert"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    );
  }

  // Warnings only (no critical errors)
  return (
    <div className={`bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-4 mb-6 ${className}`}>
      <div className="flex items-start space-x-3">
        <AlertCircle className="h-5 w-5 text-amber-600 dark:text-amber-400 mt-0.5 flex-shrink-0" />

        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-amber-800 dark:text-amber-300 mb-1">
            Sensor Configuration Warnings
          </h3>

          <div className="text-sm text-amber-700 dark:text-amber-300 mb-3">
            {warnings.length === 1 ? (
              <p>1 configured sensor is not responding. Data from this sensor will be missing.</p>
            ) : (
              <p>{warnings.length} configured sensors are not responding. Data from these sensors will be missing.</p>
            )}
          </div>

          <div className="mb-3">
            <ul className="space-y-1">
              {warnings.slice(0, 3).map((issue, index) => (
                <li key={index} className="text-sm text-amber-600 dark:text-amber-400 flex items-center">
                  <span className="w-1.5 h-1.5 bg-amber-500 rounded-full mr-2 flex-shrink-0"></span>
                  <span className="font-medium">{issue.component}:</span>
                  <span className="ml-1 truncate">{issue.description}</span>
                </li>
              ))}
              {warnings.length > 3 && (
                <li className="text-sm text-amber-600 dark:text-amber-400 italic">
                  ... and {warnings.length - 3} more
                </li>
              )}
            </ul>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              onClick={handleViewDetails}
              className="inline-flex items-center px-3 py-1.5 text-sm font-medium text-amber-800 dark:text-amber-300 bg-amber-100 dark:bg-amber-800/30 hover:bg-amber-200 dark:hover:bg-amber-800/50 rounded-md transition-colors duration-200"
            >
              <ExternalLink className="h-3.5 w-3.5 mr-1" />
              View Details
            </button>
          </div>
        </div>

        {onDismiss && (
          <button
            onClick={onDismiss}
            className="p-1 text-amber-400 dark:text-amber-500 hover:text-amber-600 dark:hover:text-amber-300 transition-colors duration-200"
            aria-label="Dismiss alert"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  );
};

export default AlertBanner;
