import { useState, useEffect, useCallback } from 'react';
import { fetchDashboardData, DashboardResponse } from '../api/scheduleApi';

interface UseDashboardDataResult {
  data: DashboardResponse | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

/**
 * Shared hook for dashboard data fetching.
 * Centralizes all /api/dashboard calls to prevent duplicate requests.
 */
export const useDashboardData = (date?: string): UseDashboardDataResult => {
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await fetchDashboardData(date);
      setData(result);
    } catch (err) {
      console.error('Failed to fetch dashboard data:', err);
      const errorMessage = err instanceof Error ? err.message : 'Failed to load dashboard data';
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  }, [date]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const refetch = useCallback(() => {
    fetchData();
  }, [fetchData]);

  return {
    data,
    loading,
    error,
    refetch
  };
};

export default useDashboardData;