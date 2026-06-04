import { useState, useEffect, useCallback } from 'react';
import api from '../lib/api';

interface RuntimeFailure {
  id: string;
  timestamp: string;
  operation: string;
  category: string;
  error_message: string;
  error_type: string;
  retry_count: number;
}

export const useRuntimeFailures = () => {
  const [failures, setFailures] = useState<RuntimeFailure[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchFailures = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await api.get('/api/runtime-failures');
      setFailures(response.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch runtime failures');
      console.error('Error fetching runtime failures:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  const dismissFailure = useCallback(async (failureId: string) => {
    try {
      await api.post(`/api/runtime-failures/${failureId}/dismiss`);
      // Remove the dismissed failure from local state
      setFailures(prev => prev.filter(f => f.id !== failureId));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to dismiss failure');
      console.error('Error dismissing failure:', err);
      // Refetch to ensure consistency
      fetchFailures();
    }
  }, [fetchFailures]);

  const dismissAllFailures = useCallback(async () => {
    try {
      await api.post('/api/runtime-failures/dismiss-all');
      // Clear all failures from local state
      setFailures([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to dismiss all failures');
      console.error('Error dismissing all failures:', err);
      // Refetch to ensure consistency
      fetchFailures();
    }
  }, [fetchFailures]);

  // Fetch failures on mount
  useEffect(() => {
    fetchFailures();
  }, [fetchFailures]);

  // Set up periodic refresh every 30 seconds
  useEffect(() => {
    const interval = setInterval(fetchFailures, 30000);
    return () => clearInterval(interval);
  }, [fetchFailures]);

  return {
    failures,
    loading,
    error,
    dismissFailure,
    dismissAllFailures,
    refetch: fetchFailures,
  };
};