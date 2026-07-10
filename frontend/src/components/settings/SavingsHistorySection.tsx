import React, { useState, useEffect } from 'react';
import { fetchSavingsHistoryDiskUsage, clearSavingsHistory, SavingsHistoryDiskUsage } from '../../api/scheduleApi';

const formatBytes = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

export const SavingsHistorySection: React.FC = () => {
  const [usage, setUsage] = useState<SavingsHistoryDiskUsage | null>(null);
  const [confirmingClear, setConfirmingClear] = useState(false);

  useEffect(() => {
    fetchSavingsHistoryDiskUsage()
      .then(setUsage)
      .catch(() => {});
  }, []);

  const handleClearHistory = async () => {
    if (!confirmingClear) {
      setConfirmingClear(true);
      return;
    }
    try {
      const result = await clearSavingsHistory();
      setUsage(result);
    } finally {
      setConfirmingClear(false);
    }
  };

  return (
    <div className="flex items-center justify-between">
      <p className="text-sm text-gray-700 dark:text-gray-300">
        Savings History: {usage?.dayCount ?? 0} days recorded
        {usage ? ` (${formatBytes(usage.totalBytes)})` : ''}
      </p>
      <button
        onClick={handleClearHistory}
        className="px-3 py-1.5 text-xs font-medium text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-lg hover:bg-red-100 dark:hover:bg-red-900/30"
      >
        {confirmingClear ? 'Confirm Clear' : 'Clear History'}
      </button>
    </div>
  );
};

export default SavingsHistorySection;
