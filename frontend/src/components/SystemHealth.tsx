import React, { useState, useEffect } from 'react';
import { CheckCircle, AlertCircle, XCircle, Info, ChevronDown, ChevronUp } from 'lucide-react';
import api from '../lib/api';
import { SystemHealthData } from '../types';

type StatusType = "OK" | "WARNING" | "ERROR" | "UNKNOWN";

interface StatusIconProps {
  status: StatusType;
}

const StatusIcon: React.FC<StatusIconProps> = ({ status }) => {
  switch (status) {
    case 'OK':
      return <CheckCircle className="h-5 w-5 text-green-500" />;
    case 'WARNING':
      return <AlertCircle className="h-5 w-5 text-amber-500" />;
    case 'ERROR':
      return <XCircle className="h-5 w-5 text-red-500" />;
    default:
      return <Info className="h-5 w-5 text-gray-400" />;
  }
};

const SystemHealthComponent: React.FC = () => {
  const [healthData, setHealthData] = useState<SystemHealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedComponents, setExpandedComponents] = useState<Record<string, boolean>>({});

  useEffect(() => {
    const fetchHealthData = async () => {
      try {
        setLoading(true);
        const response = await api.get<SystemHealthData>('/api/system/health');
        setHealthData(response.data);
        
        // Auto-expand components with issues
        const expandedState: Record<string, boolean> = {};
        response.data.checks.forEach(component => {
          if (component.status !== 'OK') {
            expandedState[component.name] = true;
          }
        });
        setExpandedComponents(expandedState);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch system health data');
        console.error('Error fetching health data:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchHealthData();
    
    // Refresh every 5 minutes
    const intervalId = setInterval(fetchHealthData, 5 * 60 * 1000);
    return () => clearInterval(intervalId);
  }, []);

  const toggleExpand = (componentName: string) => {
    setExpandedComponents(prev => ({
      ...prev,
      [componentName]: !prev[componentName]
    }));
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="flex flex-col items-center">
          <div className="animate-spin h-8 w-8 border-4 border-blue-600 rounded-full border-t-transparent"></div>
          <p className="mt-4 text-gray-600">Loading system health information...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 p-6 rounded-lg border border-red-200">
        <h2 className="text-lg font-semibold text-red-800 mb-2">Error</h2>
        <p className="text-red-600">{error}</p>
      </div>
    );
  }

  // Count status types with proper typing
  const statusCounts: Record<StatusType, number> = {
    OK: 0,
    WARNING: 0,
    ERROR: 0,
    UNKNOWN: 0
  };

  healthData?.checks.forEach(component => {
    statusCounts[component.status] += 1;
  });

  // Sort components - required with errors first, then required with warnings, then optional with issues, then OK components
  const sortedComponents = [...(healthData?.checks || [])].sort((a, b) => {
    // First priority: required components with issues
    if (a.required && !b.required) return -1;
    if (!a.required && b.required) return 1;
    
    // Second priority: error status
    const statusPriority: Record<StatusType, number> = { 
      ERROR: 0, 
      WARNING: 1, 
      OK: 2, 
      UNKNOWN: 3 
    };
    return statusPriority[a.status] - statusPriority[b.status];
  });

  return (
    <div className="bg-white rounded-lg shadow overflow-hidden">
      <div className="p-6 border-b border-gray-200">
        <div className="flex justify-between items-center">
          <h2 className="text-xl font-semibold text-gray-900">System Health Status</h2>
          <div className="flex space-x-3">
            <div className="flex items-center">
              <CheckCircle className="h-5 w-5 text-green-500 mr-1" />
              <span className="text-sm font-medium">{statusCounts.OK}</span>
            </div>
            <div className="flex items-center">
              <AlertCircle className="h-5 w-5 text-amber-500 mr-1" />
              <span className="text-sm font-medium">{statusCounts.WARNING}</span>
            </div>
            <div className="flex items-center">
              <XCircle className="h-5 w-5 text-red-500 mr-1" />
              <span className="text-sm font-medium">{statusCounts.ERROR}</span>
            </div>
          </div>
        </div>
        <p className="mt-2 text-sm text-gray-600">
          Last updated: {healthData ? new Date(healthData.timestamp).toLocaleString() : ''}
        </p>
        <p className="text-sm text-gray-600">
          System mode: <span className="font-medium">{healthData?.system_mode}</span>
        </p>
      </div>

      <div className="divide-y divide-gray-200">
        {sortedComponents.map((component) => (
          <div key={component.name} className="overflow-hidden">
            <div 
              className={`flex items-center justify-between p-4 cursor-pointer transition-colors ${
                component.status === 'ERROR' 
                  ? 'bg-red-50 hover:bg-red-100' 
                  : component.status === 'WARNING' 
                    ? 'bg-amber-50 hover:bg-amber-100' 
                    : 'hover:bg-gray-50'
              }`}
              onClick={() => toggleExpand(component.name)}
            >
              <div className="flex items-center space-x-3">
                <StatusIcon status={component.status} />
                <div>
                  <h3 className="font-medium text-gray-900">
                    {component.name}
                    {component.required && 
                      <span className="ml-2 px-2 py-0.5 text-xs rounded-full bg-blue-100 text-blue-800">
                        Required
                      </span>
                    }
                  </h3>
                  <p className="text-sm text-gray-500">{component.description}</p>
                </div>
              </div>
              <div className="flex items-center">
                <span className={`mr-2 px-2 py-1 text-xs rounded-full ${
                  component.status === 'OK' 
                    ? 'bg-green-100 text-green-800' 
                    : component.status === 'WARNING' 
                      ? 'bg-amber-100 text-amber-800' 
                      : 'bg-red-100 text-red-800'
                }`}>
                  {component.status}
                </span>
                {expandedComponents[component.name] ? 
                  <ChevronUp className="h-5 w-5 text-gray-400" /> : 
                  <ChevronDown className="h-5 w-5 text-gray-400" />
                }
              </div>
            </div>
            
            {expandedComponents[component.name] && (
              <div className="bg-gray-50 px-4 py-3 border-t border-gray-200">
                {component.checks && component.checks.length > 0 ? (
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead>
                        <tr>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Check</th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Entity ID</th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Value</th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Error</th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {component.checks.map((check, index) => (
                          <tr key={index} className={
                            check.status === 'ERROR' 
                              ? 'bg-red-50' 
                              : check.status === 'WARNING' 
                                ? 'bg-amber-50' 
                                : ''
                          }>
                            <td className="px-3 py-2 whitespace-nowrap">
                              <StatusIcon status={check.status} />
                            </td>
                            <td className="px-3 py-2 whitespace-nowrap text-sm font-medium text-gray-900">
                              {check.name}
                            </td>
                            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-500">
                              {check.entity_id || '-'}
                            </td>
                            <td className="px-3 py-2 whitespace-nowrap text-sm text-gray-500">
                              {check.value !== null && check.value !== undefined 
                                ? (typeof check.value === 'object' 
                                  ? JSON.stringify(check.value).substring(0, 50) 
                                  : String(check.value).substring(0, 50))
                                : '-'}
                            </td>
                            <td className="px-3 py-2 whitespace-nowrap text-sm text-red-500">
                              {check.error || '-'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="text-sm italic text-gray-500">No detailed checks available</p>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};

export default SystemHealthComponent;