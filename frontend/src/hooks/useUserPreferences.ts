import { useState } from 'react';

export type DataResolution = 'hourly' | 'quarter-hourly';

interface UserPreferences {
  dataResolution: DataResolution;
}

const PREFERENCES_KEY = 'bess_user_preferences';

const defaultPreferences: UserPreferences = {
  dataResolution: 'quarter-hourly'
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

  return {
    preferences,
    setPreferences,
    dataResolution: preferences.dataResolution,
    setDataResolution
  };
}
