import { useState, useEffect, useCallback } from 'react';
import api from '../lib/api';

interface HealthRecovery {
  id: string;
  timestamp: string;
  component: string;
  previousStatus: string;
}

export const useHealthRecoveries = () => {
  const [recoveries, setRecoveries] = useState<HealthRecovery[]>([]);
  const [error, setError] = useState<string | null>(null);

  const fetchRecoveries = useCallback(async () => {
    try {
      setError(null);
      const response = await api.get('/api/health-recoveries');
      setRecoveries(response.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch health recoveries');
      console.error('Error fetching health recoveries:', err);
    }
  }, []);

  const acknowledgeRecoveries = useCallback(async () => {
    try {
      await api.post('/api/health-recoveries/acknowledge');
      setRecoveries([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to acknowledge health recoveries');
      console.error('Error acknowledging health recoveries:', err);
      fetchRecoveries();
    }
  }, [fetchRecoveries]);

  useEffect(() => {
    fetchRecoveries();
  }, [fetchRecoveries]);

  useEffect(() => {
    const interval = setInterval(fetchRecoveries, 30000);
    return () => clearInterval(interval);
  }, [fetchRecoveries]);

  return {
    recoveries,
    error,
    acknowledgeRecoveries,
    refetch: fetchRecoveries,
  };
};
