import { useState, useEffect, useCallback } from 'react';
import api from '../lib/api';
import { ConsumptionForecastComparison } from '../types';

interface UseConsumptionForecastComparisonResult {
  comparison: ConsumptionForecastComparison | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export const useConsumptionForecastComparison = (): UseConsumptionForecastComparisonResult => {
  const [comparison, setComparison] = useState<ConsumptionForecastComparison | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchComparison = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await api.get('/api/consumption-forecast-comparison');
      setComparison(response.data);
    } catch (err: any) {
      console.error('Failed to fetch consumption forecast comparison:', err);
      const errorMessage = err?.response?.data?.detail
        ?? (err instanceof Error ? err.message : 'Failed to load forecast comparison');
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchComparison();
  }, [fetchComparison]);

  return {
    comparison,
    loading,
    error,
    refetch: fetchComparison,
  };
};
