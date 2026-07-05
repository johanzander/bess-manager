import React, { useState } from 'react';
import { AlertTriangle, AlertCircle, CheckCircle, X, ExternalLink } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useReportProblem } from './ReportProblemContext';

interface CriticalIssue {
  component: string;
  description: string;
  status: string;
}

interface HealthRecovery {
  component: string;
  previousStatus: string;
  timestamp: string;
}

interface AlertBannerProps {
  hasCriticalErrors: boolean;
  hasWarnings: boolean;
  criticalIssues: CriticalIssue[];
  totalCriticalIssues: number;
  recoveries?: HealthRecovery[];
  onAcknowledgeRecoveries?: () => void;
  onRecheck?: () => void;
  isRechecking?: boolean;
  className?: string;
}

const VISIBLE_ISSUE_LIMIT = 3;

interface IssueListProps {
  issues: CriticalIssue[];
  dotClassName: string;
  textClassName: string;
  toggleClassName: string;
}

const IssueList: React.FC<IssueListProps> = ({ issues, dotClassName, textClassName, toggleClassName }) => {
  const [expanded, setExpanded] = useState(false);
  const visibleIssues = expanded ? issues : issues.slice(0, VISIBLE_ISSUE_LIMIT);
  const hiddenCount = issues.length - VISIBLE_ISSUE_LIMIT;

  return (
    <div>
      <ul className="space-y-1">
        {visibleIssues.map((issue, index) => (
          <li key={index} className={`text-sm ${textClassName} flex items-center`}>
            <span className={`w-1.5 h-1.5 ${dotClassName} rounded-full mr-2 flex-shrink-0`}></span>
            <span className="font-medium">{issue.component}:</span>
            <span className="ml-1 truncate">{issue.description}</span>
          </li>
        ))}
      </ul>
      {hiddenCount > 0 && (
        <button
          onClick={() => setExpanded((prev) => !prev)}
          className={`text-sm italic underline mt-1 ${toggleClassName}`}
        >
          {expanded ? 'Show less' : `Show all (${issues.length})`}
        </button>
      )}
    </div>
  );
};

const AlertBanner: React.FC<AlertBannerProps> = ({
  hasCriticalErrors,
  hasWarnings,
  criticalIssues,
  recoveries = [],
  onAcknowledgeRecoveries,
  onRecheck,
  isRechecking = false,
  className = ''
}) => {
  const navigate = useNavigate();
  const { openReportProblem } = useReportProblem();

  if (!hasCriticalErrors && !hasWarnings && recoveries.length === 0) {
    return null;
  }

  const errors = criticalIssues.filter(i => i.status === 'ERROR');
  const warnings = criticalIssues.filter(i => i.status === 'WARNING');

  const handleViewDetails = () => {
    navigate('/system-health');
  };

  const handleReport = () => {
    const issueLines = criticalIssues
      .map(i => `- ${i.component} [${i.status}]: ${i.description}`)
      .join('\n');
    openReportProblem({
      title: hasCriticalErrors
        ? 'Critical system issues detected'
        : 'Sensor configuration warnings',
      description: `The system reported the following issues:\n\n${issueLines}`,
    });
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
                <IssueList
                  issues={errors}
                  dotClassName="bg-red-500"
                  textClassName="text-red-600 dark:text-red-400"
                  toggleClassName="text-red-600 dark:text-red-400"
                />
              </div>
            )}

            {warnings.length > 0 && (
              <div className="mb-3 border-t border-red-200 dark:border-red-700 pt-2">
                <p className="text-xs font-medium text-red-600 dark:text-red-400 mb-1">Also: {warnings.length} warning{warnings.length !== 1 ? 's' : ''}</p>
                <IssueList
                  issues={warnings}
                  dotClassName="bg-red-400"
                  textClassName="text-red-500 dark:text-red-400"
                  toggleClassName="text-red-500 dark:text-red-400"
                />
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
              <button
                onClick={handleReport}
                className="inline-flex items-center px-3 py-1.5 text-sm font-medium text-red-800 dark:text-red-300 bg-red-100 dark:bg-red-800/30 hover:bg-red-200 dark:hover:bg-red-800/50 rounded-md transition-colors duration-200"
              >
                <AlertCircle className="h-3.5 w-3.5 mr-1" />
                Report Problem
              </button>
              {onRecheck && (
                <button
                  onClick={onRecheck}
                  disabled={isRechecking}
                  className="inline-flex items-center px-3 py-1.5 text-sm font-medium text-red-800 dark:text-red-300 bg-red-100 dark:bg-red-800/30 hover:bg-red-200 dark:hover:bg-red-800/50 rounded-md transition-colors duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isRechecking ? 'Rechecking…' : 'Recheck now'}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (hasWarnings) {
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
              <IssueList
                issues={warnings}
                dotClassName="bg-amber-500"
                textClassName="text-amber-600 dark:text-amber-400"
                toggleClassName="text-amber-600 dark:text-amber-400"
              />
            </div>

            <div className="flex flex-wrap gap-2">
              <button
                onClick={handleViewDetails}
                className="inline-flex items-center px-3 py-1.5 text-sm font-medium text-amber-800 dark:text-amber-300 bg-amber-100 dark:bg-amber-800/30 hover:bg-amber-200 dark:hover:bg-amber-800/50 rounded-md transition-colors duration-200"
              >
                <ExternalLink className="h-3.5 w-3.5 mr-1" />
                View Details
              </button>
              {onRecheck && (
                <button
                  onClick={onRecheck}
                  disabled={isRechecking}
                  className="inline-flex items-center px-3 py-1.5 text-sm font-medium text-amber-800 dark:text-amber-300 bg-amber-100 dark:bg-amber-800/30 hover:bg-amber-200 dark:hover:bg-amber-800/50 rounded-md transition-colors duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isRechecking ? 'Rechecking…' : 'Recheck now'}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }

  // No active issues — a pending recovery from an earlier error/warning.
  return (
    <div className={`bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-4 mb-6 ${className}`}>
      <div className="flex items-start space-x-3">
        <CheckCircle className="h-5 w-5 text-amber-600 dark:text-amber-400 mt-0.5 flex-shrink-0" />

        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-amber-800 dark:text-amber-300 mb-1">
            Recovered From an Earlier Issue
          </h3>

          <ul className="space-y-1">
            {recoveries.map((recovery, index) => (
              <li key={index} className="text-sm text-amber-700 dark:text-amber-300">
                <span className="font-medium">{recovery.component}</span> recovered from {recovery.previousStatus.toLowerCase()}
              </li>
            ))}
          </ul>
        </div>

        {onAcknowledgeRecoveries && (
          <button
            onClick={onAcknowledgeRecoveries}
            className="p-1 text-amber-400 dark:text-amber-500 hover:text-amber-600 dark:hover:text-amber-300 transition-colors duration-200"
            aria-label="Dismiss"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  );
};

export default AlertBanner;
