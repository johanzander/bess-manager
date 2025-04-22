// Update or create: frontend/src/api/scheduleApi.ts
import api from '../lib/api';

export const fetchScheduleData = async (date: string) => {
  const response = await api.get('/api/schedule', { params: { date } });
  return response.data;
};

export const fetchEnergyProfile = async (date: string) => {
  const response = await api.get('/api/energy/profile', { params: { date } });
  return response.data;
};