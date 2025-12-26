import { useState, useEffect, useCallback } from 'react';
import api from '../lib/api';
import { PredictionSnapshot, SnapshotComparison, SnapshotToSnapshotComparison } from '../types';

interface UsePredictionSnapshotsResult {
  snapshots: PredictionSnapshot[];
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

interface UseSnapshotComparisonResult {
  comparison: SnapshotComparison | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export const usePredictionSnapshots = (): UsePredictionSnapshotsResult => {
  const [snapshots, setSnapshots] = useState<PredictionSnapshot[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchSnapshots = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await api.get('/api/prediction-analysis/snapshots');
      setSnapshots(response.data.snapshots || []);
    } catch (err) {
      console.error('Failed to fetch prediction snapshots:', err);
      const errorMessage = err instanceof Error ? err.message : 'Failed to load snapshots';
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSnapshots();
  }, [fetchSnapshots]);

  return {
    snapshots,
    loading,
    error,
    refetch: fetchSnapshots
  };
};

export const useSnapshotComparison = (snapshotPeriod: number | null): UseSnapshotComparisonResult => {
  const [comparison, setComparison] = useState<SnapshotComparison | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchComparison = useCallback(async () => {
    if (snapshotPeriod === null) {
      setComparison(null);
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const response = await api.get('/api/prediction-analysis/comparison', {
        params: { snapshot_period: snapshotPeriod }
      });
      setComparison(response.data);
    } catch (err) {
      console.error('Failed to fetch snapshot comparison:', err);
      const errorMessage = err instanceof Error ? err.message : 'Failed to load comparison';
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  }, [snapshotPeriod]);

  useEffect(() => {
    fetchComparison();
  }, [fetchComparison]);

  return {
    comparison,
    loading,
    error,
    refetch: fetchComparison
  };
};

interface UseSnapshotToSnapshotComparisonResult {
  comparison: SnapshotToSnapshotComparison | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export const useSnapshotToSnapshotComparison = (
  periodA: number | null,
  periodB: number | null
): UseSnapshotToSnapshotComparisonResult => {
  const [comparison, setComparison] = useState<SnapshotToSnapshotComparison | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchComparison = useCallback(async () => {
    if (periodA === null || periodB === null) {
      setComparison(null);
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const response = await api.get('/api/prediction-analysis/snapshot-comparison', {
        params: { period_a: periodA, period_b: periodB }
      });
      setComparison(response.data);
    } catch (err) {
      console.error('Failed to fetch snapshot-to-snapshot comparison:', err);
      const errorMessage = err instanceof Error ? err.message : 'Failed to load comparison';
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  }, [periodA, periodB]);

  useEffect(() => {
    fetchComparison();
  }, [fetchComparison]);

  return {
    comparison,
    loading,
    error,
    refetch: fetchComparison
  };
};
