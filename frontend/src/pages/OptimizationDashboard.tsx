import { useState, useEffect, useCallback } from 'react';
import { SummaryCards } from '../components/SummaryCards';
import { BatteryLevelChart } from '../components/BatteryLevelChart';
import { BatteryActionsChart } from '../components/BatteryActionsChart';
import { BatteryScheduleTable } from '../components/BatteryScheduleTable';
import { BatterySettings, ElectricitySettings, ScheduleData } from '../types';
import api from '../lib/api';
import DailySavingsReport from '../components/DailySavingsReport';

interface DashboardProps {
  selectedDate: Date;
  onLoadingChange: (loading: boolean) => void;
  settings: BatterySettings & ElectricitySettings;
}

export default function OptimizationDashboard({
  selectedDate,
  onLoadingChange,
  settings
}: DashboardProps) {
  const [data, setData] = useState<ScheduleData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [noDataAvailable, setNoDataAvailable] = useState(false);

  const fetchScheduleData = useCallback(async () => {
    try {
      onLoadingChange(true);
      setNoDataAvailable(false);
      setError(null);
  
      console.log('Fetching schedule data with settings:', settings);
  
      const params = {
        date: selectedDate.toISOString().split('T')[0],
      };
  
      // Use the detailed endpoint to get enhanced reporting data
      const response = await api.get('/api/schedule/detailed', { params });
      const scheduleData: ScheduleData = response.data;
  
      if (!scheduleData.hourlyData || scheduleData.hourlyData.length === 0) {
        setNoDataAvailable(true);
        return;
      }
  
      console.log('Fetched enhanced schedule data:', scheduleData);
  
      setData(scheduleData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error occurred');
      console.error('Schedule fetch error:', err);
    } finally {
      onLoadingChange(false);
    }
  }, [settings, selectedDate, onLoadingChange]);

  useEffect(() => {
    fetchScheduleData();
  }, [fetchScheduleData]);

  if (!data || error || noDataAvailable) {
    let message = 'Loading schedule data...';
    
    if (error) {
      message = `Error: ${error}`;
    } else if (noDataAvailable) {
      message = `No price data available for ${selectedDate.toLocaleDateString()}`;
    }

    return (
      <div className="p-6 bg-gray-50 flex items-center justify-center min-h-screen">
        <div className="bg-white p-4 rounded-lg shadow">
          <p className="text-lg text-gray-600">{message}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-8 bg-gray-50">
      <div className="mb-8">
        <SummaryCards summary={data.summary} hourlyData={data.hourlyData} />
      </div>
      
      <div className="mb-8">
        <BatteryLevelChart hourlyData={data.hourlyData} settings={settings} />
      </div>
      
      <div className="mb-8">
        <BatteryActionsChart hourlyData={data.hourlyData} />
      </div>

      {/* Daily Savings Report */}
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-gray-800 mb-4">Daily Savings Report</h2>
        <DailySavingsReport 
          selectedDate={selectedDate} 
          settings={settings}
        />
      </div>
      
    </div>
  );
}