// src/pages/OptimizationDashboard.jsx
import React, { useState, useEffect } from 'react';
import MainDashboard from '../components/MainDashboard';
import { fetchScheduleData, fetchEnergyProfile } from '../api/scheduleApi';
import { BatterySettings } from '../types';

interface OptimizationDashboardProps {
  selectedDate: Date;
  onLoadingChange: (isLoading: boolean) => void;
  settings: BatterySettings;
}

const OptimizationDashboard: React.FC<OptimizationDashboardProps> = ({
  selectedDate,
  onLoadingChange,
  settings
}) => {
  const [scheduleData, setScheduleData] = useState(null);
  const [energyProfile, setEnergyProfile] = useState(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  // Format date for API
  const formatDate = (date: Date) => {
    return date.toISOString().split('T')[0];
  };

  // Fetch schedule data when date changes
  useEffect(() => {
    const loadData = async () => {
      setIsLoading(true);
      onLoadingChange(true);
      setError(null);

      try {
        // Fetch schedule with detailed data
        const formattedDate = formatDate(selectedDate);
        const scheduleResponse = await fetchScheduleData(formattedDate);
        setScheduleData(scheduleResponse);

        // Fetch energy profile data
        const energyProfileResponse = await fetchEnergyProfile(formattedDate);
        setEnergyProfile(energyProfileResponse);
      } catch (err) {
        console.error('Failed to fetch data:', err);
        setError('Failed to load schedule data. Please try again.');
      } finally {
        setIsLoading(false);
        onLoadingChange(false);
      }
    };

    loadData();
  }, [selectedDate, onLoadingChange]);

  // Handle date change
  const handleDateChange = (date: Date) => {
    // This will be passed to parent component to update selected date
    // which will trigger the useEffect hook to fetch new data
  };

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-40">
        <div className="animate-spin h-8 w-8 border-4 border-blue-500 rounded-full border-t-transparent"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-100 border-l-4 border-red-500 text-red-700 p-4 mb-4">
        <p>{error}</p>
      </div>
    );
  }

  if (!scheduleData) {
    return (
      <div className="bg-white shadow-md rounded p-6">
        <p>No schedule data available for the selected date.</p>
      </div>
    );
  }

  return (
    <MainDashboard
      selectedDate={selectedDate}
      onDateChange={handleDateChange}
      hourlyData={scheduleData.hourlyData}
      summary={scheduleData.summary}
      settings={settings}
      isLoading={isLoading}
      energyProfile={energyProfile?.energyProfile}
    />
  );
};

export default OptimizationDashboard;