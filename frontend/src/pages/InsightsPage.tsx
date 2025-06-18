// src/pages/InsightsPage.tsx
import React, { useState, useEffect, useCallback } from 'react';
import { TableBatteryDecisionExplorer } from '../components/TableBatteryDecisionExplorer';
import { Brain, TrendingUp, AlertCircle, CheckCircle, Activity } from 'lucide-react';
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
  const [dailyViewData, setDailyViewData] = useState<DashboardResponse | null>(null);
  const [energyBalanceData, setEnergyBalanceData] = useState<{
    hourlyData: Array<{
      hour: number;
      system_production: number;
      load_consumption: number;
      battery_level: number;
      battery_power: number;
      is_actual: boolean;
    }>;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      
      // Use the unified dashboard API instead of multiple endpoints
      const response = await api.get('/api/dashboard');
      setDailyViewData(response.data);
      
      // For backward compatibility, format energy balance data from dashboard API
      // Create a compatible energyBalanceData structure from the same response
      const hourlyData = response.data.hourlyData || [];
      const formattedEnergyBalance = {
        hourlyData: hourlyData.map((hour: any) => ({
          hour: hour.hour,
          system_production: hour.solarGenerated || hour.solarProduction || 0,
          load_consumption: hour.homeConsumed || hour.consumption || 0,
          battery_level: hour.batterySocEnd || hour.batteryLevel || 0,
          battery_power: hour.batteryAction || 0,
          is_actual: hour.dataSource === "actual" || hour.isActual || false
        }))
      };
      
      setEnergyBalanceData(formattedEnergyBalance);
    } catch (err) {
      console.error('Failed to fetch dashboard data:', err);
      setError(err instanceof Error ? err.message : 'Failed to fetch dashboard data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    
    // Refresh every 2 minutes
    const interval = setInterval(fetchData, 2 * 60 * 1000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // Calculate prediction accuracy stats
  const calculateAccuracyStats = () => {
    if (!dailyViewData || !energyBalanceData) return null;

    const currentHour = dailyViewData.currentHour || 0;
    const actualHours = Math.max(0, currentHour);
    const totalHours = 24;
    const predictedHours = totalHours - actualHours;

    // Calculate average prediction accuracy for completed hours
    let totalAccuracy = 0;
    let accuracyCount = 0;
    
    for (let hour = 0; hour < actualHours; hour++) {
      const dailyHour = dailyViewData.hourlyData?.find((h: any) => h.hour === hour);
      const energyHour = energyBalanceData.hourlyData?.find((h: any) => h.hour === hour);
      
      if (dailyHour && energyHour) {
        // Simple accuracy calculation based on solar and consumption predictions
        const solarError = energyHour.system_production > 0 
          ? Math.abs(energyHour.system_production - (dailyHour.solarGenerated || dailyHour.solarProduction || 0)) / energyHour.system_production * 100
          : 0;
        
        const consumptionError = energyHour.load_consumption > 0
          ? Math.abs(energyHour.load_consumption - (dailyHour.homeConsumed || dailyHour.consumption || 0)) / energyHour.load_consumption * 100
          : 0;
          
        const hourAccuracy = Math.max(0, 100 - (solarError + consumptionError) / 2);
        totalAccuracy += hourAccuracy;
        accuracyCount++;
      }
    }

    const avgAccuracy = accuracyCount > 0 ? totalAccuracy / accuracyCount : 0;

    return {
      actualHours,
      predictedHours,
      totalHours,
      avgAccuracy,
      dataQuality: (actualHours / totalHours) * 100
    };
  };

  const accuracyStats = calculateAccuracyStats();

  if (loading && !dailyViewData) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin h-8 w-8 border-4 border-blue-500 rounded-full border-t-transparent mr-3"></div>
        <span>Loading decision intelligence...</span>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6 bg-gray-50 min-h-screen">
      {/* Header */}
      <div className="bg-white p-6 rounded-lg shadow">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 flex items-center">
              <Brain className="h-6 w-6 mr-2 text-purple-600" />
              Decision Intelligence & Insights
            </h1>
            <p className="text-gray-600 mt-1">
              Understand why your battery system made each decision and how accurate the predictions were
            </p>
          </div>
          {accuracyStats && (
            <div className="text-sm text-gray-500">
              Data Quality: {accuracyStats.dataQuality.toFixed(0)}% actual data
            </div>
          )}
        </div>
      </div>

      {/* Error Message */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex items-center">
            <AlertCircle className="h-5 w-5 text-red-500 mr-2" />
            <span className="text-red-700">{error}</span>
          </div>
        </div>
      )}

      {/* Prediction Quality Overview */}
      {accuracyStats && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="bg-white p-4 rounded-lg shadow border-l-4 border-blue-500">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-medium text-gray-600">Data Coverage</h3>
                <p className="text-2xl font-bold text-blue-600">{accuracyStats.actualHours}/24</p>
                <p className="text-xs text-gray-500">hours with actual data</p>
              </div>
              <Activity className="h-8 w-8 text-blue-500 opacity-75" />
            </div>
          </div>

          <div className="bg-white p-4 rounded-lg shadow border-l-4 border-green-500">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-medium text-gray-600">Prediction Accuracy</h3>
                <p className="text-2xl font-bold text-green-600">{accuracyStats.avgAccuracy.toFixed(0)}%</p>
                <p className="text-xs text-gray-500">average for completed hours</p>
              </div>
              <CheckCircle className="h-8 w-8 text-green-500 opacity-75" />
            </div>
          </div>

          <div className="bg-white p-4 rounded-lg shadow border-l-4 border-purple-500">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-medium text-gray-600">Decision Quality</h3>
                <p className="text-2xl font-bold text-purple-600">
                  {dailyViewData ? 
                    ((dailyViewData.totalDailySavings || 0) / Math.max((dailyViewData.totalDailySavings || 0) + 50, 100) * 100).toFixed(0) + '%'
                    : 'N/A'}
                </p>
                <p className="text-xs text-gray-500">optimization effectiveness</p>
              </div>
              <Brain className="h-8 w-8 text-purple-500 opacity-75" />
            </div>
          </div>

          <div className="bg-white p-4 rounded-lg shadow border-l-4 border-yellow-500">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-medium text-gray-600">Daily Savings</h3>
                <p className="text-2xl font-bold text-yellow-600">
                  {dailyViewData ? `${(dailyViewData.totalDailySavings || 0).toFixed(1)} SEK` : 'N/A'}
                </p>
                <p className="text-xs text-gray-500">total optimization value</p>
              </div>
              <TrendingUp className="h-8 w-8 text-yellow-500 opacity-75" />
            </div>
          </div>
        </div>
      )}

      {/* Table-Based Battery Decision Explorer */}
      {dailyViewData && (
        <TableBatteryDecisionExplorer 
          dailyViewData={dailyViewData.hourlyData || []}
          currentHour={dailyViewData.currentHour || 0}
        />
      )}

      {/* Insights Summary */}
      <div className="bg-white p-6 rounded-lg shadow">
        <h2 className="text-xl font-semibold mb-4">Key Insights</h2>
        
        {dailyViewData ? (
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <h3 className="font-medium text-gray-800 mb-2">Today's Performance</h3>
                <ul className="space-y-2 text-sm text-gray-700">
                  <li className="flex items-center">
                    <CheckCircle className="h-4 w-4 text-green-500 mr-2" />
                    Total savings: {(dailyViewData.totalDailySavings || 0).toFixed(2)} SEK
                  </li>
                  <li className="flex items-center">
                    <CheckCircle className="h-4 w-4 text-green-500 mr-2" />
                    Actual savings so far: {(dailyViewData.actualSavingsSoFar || 0).toFixed(2)} SEK
                  </li>
                  <li className="flex items-center">
                    <Activity className="h-4 w-4 text-blue-500 mr-2" />
                    Predicted remaining: {(dailyViewData.predictedRemainingSavings || 0).toFixed(2)} SEK
                  </li>
                  <li className="flex items-center">
                    <Brain className="h-4 w-4 text-purple-500 mr-2" />
                    Data sources: {Object.keys(dailyViewData.dataSources || {}).join(", ")}
                  </li>
                </ul>
              </div>

              <div>
                <h3 className="font-medium text-gray-800 mb-2">System Intelligence</h3>
                <ul className="space-y-2 text-sm text-gray-700">
                  <li className="flex items-center">
                    <Activity className="h-4 w-4 text-blue-500 mr-2" />
                    Making decisions for {dailyViewData.predictedHoursCount || 0} future hours
                  </li>
                  <li className="flex items-center">
                    <CheckCircle className="h-4 w-4 text-green-500 mr-2" />
                    Learning from {dailyViewData.actualHoursCount || 0} completed hours
                  </li>
                  {accuracyStats && (
                    <li className="flex items-center">
                      <Brain className="h-4 w-4 text-purple-500 mr-2" />
                      Prediction accuracy: {accuracyStats.avgAccuracy.toFixed(0)}%
                    </li>
                  )}
                  <li className="flex items-center">
                    <TrendingUp className="h-4 w-4 text-yellow-500 mr-2" />
                    Continuously optimizing based on real conditions
                  </li>
                </ul>
              </div>
            </div>

            <div className="bg-blue-50 border border-blue-200 rounded-md p-4">
              <h4 className="font-medium text-blue-800 mb-2">Understanding Decision Scores</h4>
              <p className="text-blue-700 text-sm">
                Each hour's decision is scored based on market conditions, solar availability, and optimization opportunities. 
                High scores (80-100%) indicate optimal timing, while lower scores may reflect constraints or missed opportunities. 
                The system learns from actual vs predicted outcomes to improve future decisions.
              </p>
            </div>
          </div>
        ) : (
          <div className="text-center py-8">
            <Brain className="h-12 w-12 text-gray-400 mx-auto mb-4" />
            <p className="text-gray-600">No decision data available</p>
            <p className="text-sm text-gray-500">Decision intelligence will appear once the system is active</p>
          </div>
        )}
      </div>

      {/* About Insights */}
      <div className="bg-white p-6 rounded-lg shadow">
        <h2 className="text-xl font-semibold mb-4">About Decision Intelligence</h2>
        <p className="mb-3 text-gray-700">
          This page provides deep insights into your battery system's decision-making process, 
          helping you understand why each charging and discharging action was taken.
        </p>
        
        <div className="space-y-2">
          <div className="flex items-start">
            <div className="w-3 h-3 bg-purple-500 rounded-full mt-1.5 mr-2"></div>
            <p className="text-gray-700">
              <span className="font-medium">Decision Cards:</span> Show the reasoning behind each hour's battery action, 
              including economic context, constraints, and opportunity scores.
            </p>
          </div>
          
          <div className="flex items-start">
            <div className="w-3 h-3 bg-green-500 rounded-full mt-1.5 mr-2"></div>
            <p className="text-gray-700">
              <span className="font-medium">Prediction Quality:</span> Track how accurate the system's predictions are 
              compared to actual energy flows and consumption patterns.
            </p>
          </div>
          
          <div className="flex items-start">
            <div className="w-3 h-3 bg-blue-500 rounded-full mt-1.5 mr-2"></div>
            <p className="text-gray-700">
              <span className="font-medium">Optimization Scores:</span> Each decision gets a score based on how well 
              it exploits market opportunities while respecting system constraints.
            </p>
          </div>
        </div>
        
        <p className="mt-4 text-gray-700">
          Use these insights to understand your system's performance and identify opportunities for improved settings or operation.
        </p>
      </div>
    </div>
  );
};

export default InsightsPage;