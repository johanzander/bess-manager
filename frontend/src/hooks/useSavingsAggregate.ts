import { useState, useEffect, useCallback } from 'react';
import { fetchSavingsAggregate, SavingsBucket, SavingsAggregatePeriod } from '../api/scheduleApi';

interface UseSavingsAggregateResult {
  data: SavingsBucket[] | null;
  loading: boolean;
  error: string | null;
}

export const useSavingsAggregate = (
  period: SavingsAggregatePeriod,
  count?: number
): UseSavingsAggregateResult => {
  const [data, setData] = useState<SavingsBucket[] | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await fetchSavingsAggregate(period, count);
      setData(result.buckets);
    } catch (err) {
      console.error('Failed to fetch savings aggregate:', err);
      const errorMessage = err instanceof Error ? err.message : 'Failed to load savings history';
      setError(errorMessage);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [period, count]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return { data, loading, error };
};

export default useSavingsAggregate;
