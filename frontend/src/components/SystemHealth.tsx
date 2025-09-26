import React, { useState, useEffect } from 'react';
import { CheckCircle, XCircle, AlertCircle, ChevronDown, ChevronUp } from 'lucide-react';
import api from '../lib/api';
import { SystemHealthData, HealthStatus, ComponentHealthStatus, HealthCheckResult } from '../types';

const StatusIcon: React.FC<{ status: HealthStatus }> = ({ status }) => {
  switch (status) {
    case 'OK':
      return <CheckCircle className="h-5 w-5 text-green-500" />;
    case 'WARNING':
      return <AlertCircle className="h-5 w-5 text-amber-500" />;
    case 'ERROR':
      return <XCircle className="h-5 w-5 text-red-500" />;
    default:
      return <AlertCircle className="h-5 w-5 text-gray-500" />;
  }
};

// No fallback formatting - backend must provide display field with proper units

const SystemHealthComponent: React.FC = () => {
  const [healthData, setHealthData] = useState<SystemHealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedComponents, setExpandedComponents] = useState<Record<string, boolean>>({});

  const toggleExpand = (componentName: string) => {
    setExpandedComponents((prev: Record<string, boolean>) => ({
      ...prev,
      [componentName]: !prev[componentName]
    }));
  };

  useEffect(() => {
    const fetchHealthData = async () => {
      try {
        setLoading(true);
        const response = await api.get('/api/system-health');
        setHealthData(response.data);
        setError(null);
      } catch (err) {
        console.error('Error fetching health data:', err);
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchHealthData();
    // No automatic refresh - data loads once on component mount
  }, []);

  if (loading) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
        <div className="flex items-center justify-center h-32">
          <div className="animate-spin h-8 w-8 border-2 border-blue-500 rounded-full border-t-transparent"></div>
          <span className="ml-2 text-gray-900 dark:text-white">Loading system health...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
        <h2 className="text-lg font-semibold text-red-800 dark:text-red-400 mb-2">Error</h2>
        <p className="text-red-600 dark:text-red-300">{error}</p>
      </div>
    );
  }

  // Count status types with proper typing
  const statusCounts: Record<HealthStatus, number> = {
    OK: 0,
    WARNING: 0,
    ERROR: 0,
    UNKNOWN: 0
  };

  healthData?.checks.forEach((component: ComponentHealthStatus) => {
    statusCounts[component.status] += 1;
  });

  // Sort components - preserve logical order (price → control → monitoring) while prioritizing error states
  const sortedComponents = [...(healthData?.checks || [])].sort((a, b) => {
    // Get original indices to preserve backend order for components with same priority
    const aIndex = (healthData?.checks || []).indexOf(a);
    const bIndex = (healthData?.checks || []).indexOf(b);
    
    // First priority: ERROR status (critical issues need immediate attention)
    if (a.status === 'ERROR' && b.status !== 'ERROR') return -1;
    if (a.status !== 'ERROR' && b.status === 'ERROR') return 1;
    
    // Second priority: WARNING status for required components
    if (a.required && a.status === 'WARNING' && !(b.required && b.status === 'WARNING')) return -1;
    if (!(a.required && a.status === 'WARNING') && b.required && b.status === 'WARNING') return 1;
    
    // Otherwise preserve original order from backend (logical system flow)
    return aIndex - bIndex;
  });

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-hidden">
      <div className="p-6 border-b border-gray-200 dark:border-gray-700">
        <div className="flex justify-between items-center">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">System Status</h2>
          <div className="flex space-x-3">
            <div className="flex items-center">
              <CheckCircle className="h-5 w-5 text-green-500 mr-1" />
              <span className="text-sm font-medium text-gray-900 dark:text-white">{statusCounts.OK}</span>
            </div>
            <div className="flex items-center">
              <AlertCircle className="h-5 w-5 text-amber-500 mr-1" />
              <span className="text-sm font-medium text-gray-900 dark:text-white">{statusCounts.WARNING}</span>
            </div>
            <div className="flex items-center">
              <XCircle className="h-5 w-5 text-red-500 mr-1" />
              <span className="text-sm font-medium text-gray-900 dark:text-white">{statusCounts.ERROR}</span>
            </div>
          </div>
        </div>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">
          Last updated: {healthData ? new Date(healthData.timestamp).toLocaleString() : ''}
        </p>
      </div>

      <div className="divide-y divide-gray-200 dark:divide-gray-700">
        {sortedComponents.map((component) => (
          <div key={component.name} className="overflow-hidden">
            <div 
              className={`flex items-center justify-between p-4 cursor-pointer transition-colors ${
                component.status === 'ERROR' 
                  ? 'bg-red-50 dark:bg-red-900/20 hover:bg-red-100 dark:hover:bg-red-900/30' 
                  : component.status === 'WARNING' 
                    ? 'bg-amber-50 dark:bg-amber-900/20 hover:bg-amber-100 dark:hover:bg-amber-900/30' 
                    : 'hover:bg-gray-50 dark:hover:bg-gray-700'
              }`}
              onClick={() => toggleExpand(component.name)}
            >
              <div className="flex items-center space-x-3">
                <StatusIcon status={component.status} />
                <div>
                  <h3 className="font-medium text-gray-900 dark:text-white">
                    {component.name}
                    {component.required && 
                      <span className="ml-2 px-2 py-0.5 text-xs rounded-full bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-300">
                        Required
                      </span>
                    }
                  </h3>
                  <p className="text-sm text-gray-500 dark:text-gray-400">{component.description}</p>
                </div>
              </div>
              <div className="flex items-center">
                <span className={`mr-2 px-2 py-1 text-xs rounded-full ${
                  component.status === 'OK' 
                    ? 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300' 
                    : component.status === 'WARNING' 
                      ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300' 
                      : 'bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-300'
                }`}>
                  {component.status}
                </span>
                {expandedComponents[component.name] ? 
                  <ChevronUp className="h-5 w-5 text-gray-400 dark:text-gray-500" /> : 
                  <ChevronDown className="h-5 w-5 text-gray-400 dark:text-gray-500" />
                }
              </div>
            </div>
            
            {expandedComponents[component.name] && (
              <div className="bg-gray-50 dark:bg-gray-700 px-4 py-3 border-t border-gray-200 dark:border-gray-600">
                {component.checks && component.checks.length > 0 ? (
                  <div className="space-y-2">
                    <h4 className="font-medium text-gray-800 dark:text-gray-200 mb-2">Detailed Checks:</h4>
                    {component.checks.map((check: HealthCheckResult, index: number) => (
                      <div key={index} className="flex items-start space-x-2">
                        <StatusIcon status={check.status} />
                        <div className="flex-1">
                          <p className="text-sm font-medium text-gray-900 dark:text-white">{check.name}</p>
                          <p className="text-sm text-gray-600 dark:text-gray-300">{check.error || 'OK'}</p>
                          {check.entity_id && (
                            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                              Entity ID: <code className="bg-gray-100 dark:bg-gray-600 px-1 rounded text-xs">{check.entity_id}</code>
                            </p>
                          )}
                          {check.displayValue && (
                            <p className="text-xs text-gray-600 dark:text-gray-300 mt-1">
                              Value: <span className="font-medium">{check.displayValue}</span>
                            </p>
                          )}
                          {check.error && (
                            <p className="text-xs text-red-600 dark:text-red-400 mt-1">
                              Error: {check.error}
                            </p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-gray-600 dark:text-gray-300">No detailed checks available for this component.</p>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {(!healthData?.checks || healthData.checks.length === 0) && (
        <div className="p-6 text-center">
          <p className="text-gray-500 dark:text-gray-400">No health checks available</p>
        </div>
      )}
    </div>
  );
};

export default SystemHealthComponent;