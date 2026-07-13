import { useState, useEffect } from 'react';
import { fetchAvailableDashboardDates } from '../api/scheduleApi';

/**
 * ISO dates (YYYY-MM-DD) that have dashboard data available, for greying out
 * unavailable days in a date picker instead of erroring on selection.
 */
export const useAvailableDashboardDates = (): Set<string> | null => {
  const [dates, setDates] = useState<Set<string> | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchAvailableDashboardDates()
      .then((isoDates) => {
        if (!cancelled) setDates(new Set(isoDates));
      })
      .catch((err) => {
        console.error('Failed to fetch available dashboard dates:', err);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return dates;
};

export default useAvailableDashboardDates;
