import { useState } from 'react';

export type DataResolution = 'hourly' | 'quarter-hourly';

interface UserPreferences {
  dataResolution: DataResolution;
  showSellPrice: boolean;
}

const PREFERENCES_KEY = 'bess_user_preferences';

const defaultPreferences: UserPreferences = {
  dataResolution: 'quarter-hourly',
  showSellPrice: false
};

export function useUserPreferences() {
  const [preferences, setPreferencesState] = useState<UserPreferences>(() => {
    const stored = localStorage.getItem(PREFERENCES_KEY);
    if (stored) {
      try {
        return { ...defaultPreferences, ...JSON.parse(stored) };
      } catch (e) {
        console.error('Failed to parse user preferences:', e);
        return defaultPreferences;
      }
    }
    return defaultPreferences;
  });

  const setPreferences = (newPreferences: Partial<UserPreferences>) => {
    setPreferencesState(prev => {
      const updated = { ...prev, ...newPreferences };
      localStorage.setItem(PREFERENCES_KEY, JSON.stringify(updated));
      return updated;
    });
  };

  const setDataResolution = (resolution: DataResolution) => {
    setPreferences({ dataResolution: resolution });
  };

  const setShowSellPrice = (showSellPrice: boolean) => {
    setPreferences({ showSellPrice });
  };

  return {
    preferences,
    setPreferences,
    dataResolution: preferences.dataResolution,
    setDataResolution,
    showSellPrice: preferences.showSellPrice,
    setShowSellPrice
  };
}
