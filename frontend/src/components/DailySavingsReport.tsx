import React, { useState, useEffect } from 'react';
import { BatteryScheduleTable } from './BatteryScheduleTable';
import { BatterySettings, HourlyData, ScheduleSummary, EnhancedSummary, EnergyProfile } from '../types';
import api from '../lib/api';

interface DailySavingsReportProps {
  selectedDate: Date;
  settings: BatterySettings;
}

const DailySavingsReport: React.FC<DailySavingsReportProps> = ({ selectedDate, settings }) => {
  const [hourlyData, setHourlyData] = useState<HourlyData[]>([]);
  const [summary, setSummary] = useState<ScheduleSummary | null>(null);
  const [enhancedSummary, setEnhancedSummary] = useState<EnhancedSummary | undefined>(undefined);
  const [energyProfile, setEnergyProfile] = useState<EnergyProfile | undefined>(undefined);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchDailySavingsReport = async () => {
      setLoading(true);
      setError(null);
      
      try {
        const response = await api.get('/api/report/daily_savings');
        const data = response.data;
        
        // Set basic data
        setHourlyData(data.hourlyData);
        setSummary({
          baseCost: data.summary.baseCost,
          optimizedCost: data.summary.optimizedCost,
          gridCosts: data.summary.gridCosts,
          batteryCosts: data.summary.batteryCosts,
          savings: data.summary.savings,
        });
        
        // Set energy profile if available
        if (data.energyProfile) {
          setEnergyProfile(data.energyProfile);
        }
        
        // Build enhanced summary if available in the response
        if (
          data.summary.gridOnlyCost !== undefined &&
          data.summary.solarOnlyCost !== undefined &&
          data.summary.solarOnlySavings !== undefined
        ) {
          setEnhancedSummary({
            gridOnlyCost: data.summary.gridOnlyCost,
            solarOnlyCost: data.summary.solarOnlyCost,
            batterySolarCost: data.summary.optimizedCost,
            solarSavings: data.summary.solarOnlySavings,
            batterySavings: data.summary.batterySavings || 0,
            totalSavings: data.summary.savings,
            solarProduction: data.summary.totalSolarProduction || 0,
            directSolarUse: data.summary.totalDirectSolar || 0,
            solarExcess: data.summary.totalExcessSolar || 0,
            totalCharged: data.summary.totalBatteryCharge || 0,
            totalDischarged: data.summary.totalBatteryDischarge || 0,
            estimatedBatteryCycles: data.summary.cycleCount || 0,
            totalConsumption: data.hourlyData.reduce((sum, h) => sum + h.consumption, 0),
            totalImport: data.summary.totalGridImport || 0,
          });
        }
      } catch (err) {
        console.error('Error fetching daily savings report:', err);
        setError(err instanceof Error ? err.message : 'Unknown error occurred');
      } finally {
        setLoading(false);
      }
    };
    
    fetchDailySavingsReport();
  }, [selectedDate]); // Re-fetch when selected date changes

  if (loading) {
    return (
      <div className="bg-white p-6 rounded-lg shadow flex items-center justify-center h-64">
        <div className="flex flex-col items-center">
          <div className="animate-spin h-8 w-8 border-4 border-blue-500 rounded-full border-t-transparent"></div>
          <p className="mt-4 text-gray-600">Loading daily savings report...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white p-6 rounded-lg shadow">
        <h2 className="text-xl font-semibold mb-4 text-red-600">Error Loading Report</h2>
        <p className="text-gray-700">{error}</p>
        <p className="mt-4 text-gray-600">
          This may happen if there is no current battery schedule available. 
          Try selecting a different date or check if the battery system is operating correctly.
        </p>
      </div>
    );
  }

  if (!summary || hourlyData.length === 0) {
    return (
      <div className="bg-white p-6 rounded-lg shadow">
        <h2 className="text-xl font-semibold mb-4">No Report Available</h2>
        <p className="text-gray-600">No daily savings report is available for the selected date.</p>
      </div>
    );
  }

  // Render the battery schedule table with the report data
  return (
    <BatteryScheduleTable
      hourlyData={hourlyData}
      summary={summary}
      settings={settings}
      energyProfile={energyProfile}
      enhancedSummary={enhancedSummary}
    />
  );
};

export default DailySavingsReport;