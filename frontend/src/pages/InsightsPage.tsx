import React, { useState, useEffect } from 'react';
import { TableBatteryDecisionExplorer } from '../components/TableBatteryDecisionExplorer';
import { Brain } from 'lucide-react';
import api from '../lib/api';

interface DashboardResponse {
  hourlyData: Array<{
    hour: number;
    dataSource?: string;
    isActual?: boolean;
    solarGenerated?: number;
    solarProduction?: number;
    homeConsumed?: number;
    consumption?: number;
    batterySocEnd?: number;
    batteryLevel?: number;
    batteryAction?: number;
  }>;
  currentHour?: number;
  totalDailySavings?: number;
  actualSavingsSoFar?: number;
  predictedRemainingSavings?: number;
  actualHoursCount?: number;
  predictedHoursCount?: number;
  dataSources?: Record<string, any>;
}

const InsightsPage: React.FC = () => {
  const [dashboardData, setDashboardData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        setError(null);
        
        const response = await api.get('/api/dashboard');
        setDashboardData(response.data);
      } catch (err) {
        console.error('Failed to fetch dashboard data:', err);
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
        <div className="mb-4">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">Decision Intelligence & Analysis</h1>
          <p className="text-gray-600 dark:text-gray-300">
            Deep insights into battery optimization decisions, showing the economic reasoning and strategic thinking behind each action.
          </p>
        </div>
        
        <div className="p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
          <p className="text-sm text-blue-800 dark:text-blue-200">
            <strong>Understanding Battery Decisions:</strong> Each hour's battery action is the result of sophisticated optimization 
            algorithms that consider electricity prices, solar forecasts, consumption patterns, and battery constraints. 
            High scores (80-100%) indicate optimal timing, while lower scores may reflect constraints or missed opportunities. 
            The system learns from actual vs predicted outcomes to improve future decisions.
          </p>
        </div>
      </div>

      {/* Decision Explorer Table */}
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
        <div className="mb-6">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">Battery Decision Explorer</h2>
          <p className="text-sm text-gray-600 dark:text-gray-300 mb-4">
            Detailed breakdown of each hour's battery decision with economic context, optimization scores, and strategic reasoning.
          </p>
        </div>

        {loading ? (
          <div className="text-center py-8">
            <div className="animate-spin h-8 w-8 border-4 border-blue-500 border-t-transparent rounded-full mx-auto mb-4"></div>
            <p className="text-gray-600 dark:text-gray-300">Loading decision analysis...</p>
          </div>
        ) : error ? (
          <div className="text-center py-8">
            <Brain className="h-12 w-12 text-red-400 mx-auto mb-4" />
            <p className="text-red-600 dark:text-red-400">Error loading decision data</p>
            <p className="text-sm text-gray-500 dark:text-gray-400">{error}</p>
          </div>
        ) : dashboardData ? (
          <div>
            <div className="mb-4 p-3 bg-gray-50 dark:bg-gray-700 rounded-lg">
              <p className="text-sm text-gray-700 dark:text-gray-300">
                <strong>Today's Performance Summary:</strong> 
                {dashboardData.hourlyData.filter((h: any) => h.isActual).length} hours completed, 
                {dashboardData.hourlyData.filter((h: any) => !h.isActual).length} hours predicted. 
                Total daily savings: <span className="font-medium text-green-600 dark:text-green-400">
                  {dashboardData.totalDailySavings?.toFixed(2)} SEK
                </span>
              </p>
            </div>
            
            <TableBatteryDecisionExplorer />
            
            <div className="mt-4 text-xs text-gray-500 dark:text-gray-400">
              High scores (80-100%) indicate optimal timing, while lower scores may reflect constraints or missed opportunities. 
              The system learns from actual vs predicted outcomes to improve future decisions.
            </div>
          </div>
        ) : (
          <div className="text-center py-8">
            <Brain className="h-12 w-12 text-gray-400 mx-auto mb-4" />
            <p className="text-gray-600 dark:text-gray-300">No decision data available</p>
            <p className="text-sm text-gray-500 dark:text-gray-400">Decision intelligence will appear once the system is active</p>
          </div>
        )}
      </div>

      {/* About Insights */}
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">About Decision Intelligence</h2>
        <p className="mb-3 text-gray-700 dark:text-gray-300">
          This page provides deep insights into your battery system's decision-making process, 
          helping you understand why each charging and discharging action was taken.
        </p>
        
        <div className="space-y-2">
          <div className="flex items-start">
            <div className="w-3 h-3 bg-purple-500 rounded-full mt-1.5 mr-2"></div>
            <p className="text-gray-700 dark:text-gray-300">
              <span className="font-medium">Decision Cards:</span> Show the reasoning behind each hour's battery action, 
              including economic context, constraints, and opportunity scores.
            </p>
          </div>
          
          <div className="flex items-start">
            <div className="w-3 h-3 bg-green-500 rounded-full mt-1.5 mr-2"></div>
            <p className="text-gray-700 dark:text-gray-300">
              <span className="font-medium">Prediction Quality:</span> Track how accurate the system's predictions are 
              compared to actual energy flows and consumption patterns.
            </p>
          </div>
          
          <div className="flex items-start">
            <div className="w-3 h-3 bg-blue-500 rounded-full mt-1.5 mr-2"></div>
            <p className="text-gray-700 dark:text-gray-300">
              <span className="font-medium">Optimization Scores:</span> Each decision gets a score based on how well 
              it exploits market opportunities while respecting system constraints.
            </p>
          </div>
        </div>
        
        <p className="mt-4 text-gray-700 dark:text-gray-300">
          Use these insights to understand your system's performance and identify opportunities for improved settings or operation.
        </p>
      </div>
    </div>
  );
};

export default InsightsPage;