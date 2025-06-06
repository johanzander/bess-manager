// frontend/src/hooks/useSettings.ts

import { useState, useEffect } from 'react';
import { BatterySettings, ElectricitySettings } from '../types';
import api from '../lib/api';

export function useSettings() {
  const [batterySettings, setBatterySettings] = useState<BatterySettings | null>(null);
  const [electricitySettings, setElectricitySettings] = useState<ElectricitySettings | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadSettings() {
      try {
        const [batteryRes, electricityRes] = await Promise.all([
          api.get('/api/settings/battery'),
          api.get('/api/settings/electricity')
        ]);

        setBatterySettings(batteryRes.data);
        setElectricitySettings(electricityRes.data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load settings');
        console.error('Settings fetch error:', err);
      } finally {
        setIsLoading(false);
      }
    }

    loadSettings();
  }, []);

  return {
    batterySettings,
    electricitySettings,
    isLoading,
    error
  };
}