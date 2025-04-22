// Update this file: frontend/src/hooks/useSettings.ts

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

  const updateBatterySettings = async (settings: BatterySettings) => {
    try {
      const response = await api.post('/api/settings/battery', settings);
      setBatterySettings(settings);
  
      // Fetch new schedule after settings update
      await api.get('/api/schedule');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update battery settings');
      console.error('Update battery settings error:', err);
    }
  };
  
  const updateElectricitySettings = async (settings: ElectricitySettings) => {
    try {
      const response = await api.post('/api/settings/electricity', settings);
      setElectricitySettings(settings);
  
      // Fetch new schedule after settings update
      await api.get('/api/schedule');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update electricity settings');
      console.error('Update electricity settings error:', err);
    }
  };

  return {
    batterySettings,
    electricitySettings,
    updateBatterySettings,
    updateElectricitySettings,
    isLoading,
    error
  };
}