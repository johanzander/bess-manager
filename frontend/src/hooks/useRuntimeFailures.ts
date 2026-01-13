import { useState, useEffect, useCallback } from 'react';
import { RuntimeFailure, RuntimeFailuresResponse } from '../types';
import api from '../api';

/**
 * Hook for fetching and managing runtime API failures.
 *
 * Polls for failures every 30 seconds and provides methods to dismiss
 * individual failures or all failures at once.
 */
export function useRuntimeFailures() {
  const [failures, setFailures] = useState<RuntimeFailure[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchFailures = useCallback(async () => {
    try {
      const response = await api.get<RuntimeFailuresResponse>('/api/runtime-failures');
      setFailures(response.data.failures);
      setError(null);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to load runtime failures';
      setError(errorMessage);
      console.error('Runtime failures fetch error:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const dismissFailure = useCallback(async (failureId: string) => {
    try {
      await api.post(`/api/runtime-failures/${failureId}/dismiss`);
      // Optimistic update
      setFailures(prev => prev.filter(f => f.id !== failureId));
    } catch (err) {
      console.error('Failed to dismiss failure:', err);
      // Refetch to restore state
      fetchFailures();
    }
  }, [fetchFailures]);

  const dismissAll = useCallback(async () => {
    try {
      await api.post('/api/runtime-failures/dismiss-all');
      // Optimistic update
      setFailures([]);
    } catch (err) {
      console.error('Failed to dismiss all failures:', err);
      // Refetch to restore state
      fetchFailures();
    }
  }, [fetchFailures]);

  useEffect(() => {
    fetchFailures();
    // Poll every 30 seconds
    const interval = setInterval(fetchFailures, 30000);
    return () => clearInterval(interval);
  }, [fetchFailures]);

  return {
    failures,
    isLoading,
    error,
    dismissFailure,
    dismissAll,
    refetch: fetchFailures
  };
}
