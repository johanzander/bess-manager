import React, { useState, useEffect } from 'react';
import { Clock, Sun, Battery, TrendingUp } from 'lucide-react';
import api from '../lib/api';
import FormattedValueComponent from './FormattedValue';
import { FormattedValue } from '../types';

interface BatteryDecision {
  hour: number;
  action: 'charge' | 'discharge' | 'hold';
  buyPriceValue: number;
  solarProductionValue: number;
  solarBalanceValue: number;
  batterySocStartValue: number;
  batterySocEndValue: number;
  primaryReason: string;
  economicContext: string;
  opportunityScoreValue: number;
  hourlySavingsValue: number;
  isActual: boolean;
  isCurrentHour: boolean;

  // Formatted fields using canonical naming
  buyPrice: FormattedValue;
  actionValue: FormattedValue;
  solarProduction: FormattedValue;
  solarBalance: FormattedValue;
  batterySocStart: FormattedValue;
  batterySocEnd: FormattedValue;
  opportunityScore: FormattedValue;
  hourlySavings: FormattedValue;
}

interface DashboardResponse {
  currentHour: number;
  totalDailySavings: number;
  hourlyData: Array<{
    hour: number;
    isActual?: boolean;
    dataSource?: string;
    // All data provided via FormattedValue objects - canonical naming
    buyPrice?: FormattedValue;
    batteryAction?: FormattedValue;
    solarProduction?: FormattedValue;
    solarBalance?: FormattedValue;
    batterySocStart?: FormattedValue;
    batterySocEnd?: FormattedValue;
    opportunityScore?: FormattedValue;
    hourlySavings?: FormattedValue;
    homeConsumption?: FormattedValue;
  }>;
}

export const TableBatteryDecisionExplorer: React.FC = () => {
  const [dashboardData, setDashboardData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const response = await api.get('/api/dashboard');
        setDashboardData(response.data);
        setError(null);
      } catch (err) {
        console.error('Error fetching dashboard data:', err);
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  if (loading || !dashboardData) {
    return (
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg">
        <div className="flex items-center justify-center h-32">
          <div className="animate-spin h-8 w-8 border-2 border-blue-500 rounded-full border-t-transparent"></div>
          <span className="ml-2 text-gray-900 dark:text-white">Loading decision analysis...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg">
        <div className="text-center text-red-600 dark:text-red-400">
          Error loading decision data: {error}
        </div>
      </div>
    );
  }

  // Transform dashboard data into decision format
  const batteryDecisions: BatteryDecision[] = dashboardData.hourlyData.map((hour: any) => {
    // Extract raw values from FormattedValue objects for calculations
    const batteryAction = hour.batteryAction?.value || 0;
    let action: 'charge' | 'discharge' | 'hold' = 'hold';
    if (batteryAction > 0.1) action = 'charge';
    else if (batteryAction < -0.1) action = 'discharge';

    // Extract values from FormattedValue objects
    const solarProduction = hour.solarProduction?.value || 0;
    const homeConsumption = hour.homeConsumption?.value || 0;
    const solarBalance = solarProduction - homeConsumption;
    const price = hour.buyPrice?.value || 0;
    
    // Generate primary reason based on action and context
    let primaryReason = 'Grid balancing';
    let economicContext = hour.buyPrice?.text || 'N/A';

    if (action === 'charge') {
      if (solarBalance > 0) {
        primaryReason = 'Solar excess storage';
        economicContext = `${hour.solarProduction?.text || 'N/A'} excess solar`;
      } else if (price < 0.5) {
        primaryReason = 'Low price arbitrage';
        economicContext = `Low electricity price`;
      } else {
        primaryReason = 'Demand preparation';
        economicContext = `Preparing for evening demand`;
      }
    } else if (action === 'discharge') {
      if (price > 1.0) {
        primaryReason = 'High price arbitrage';
        economicContext = `High electricity price`;
      } else if (solarBalance < -1) {
        primaryReason = 'Solar deficit support';
        economicContext = `${hour.homeConsumption?.text || 'N/A'} deficit`;
      } else {
        primaryReason = 'Load support';
        economicContext = `Supporting home consumption`;
      }
    }

    // Calculate opportunity score based on price differential and solar conditions
    let opportunityScore = 0.7; // Base score
    if (action === 'charge' && solarBalance > 2) opportunityScore = 0.9;
    else if (action === 'charge' && price < 0.5) opportunityScore = 0.85;
    else if (action === 'discharge' && price > 1.0) opportunityScore = 0.9;
    else if (action === 'discharge' && solarBalance < -2) opportunityScore = 0.85;

    // Use hourly savings from data or calculate basic savings
    // Note: savings variable removed since we use canonical hourlySavings directly

    return {
      hour: hour.hour,
      action,
      buyPriceValue: price,
      solarProductionValue: solarProduction,
      solarBalanceValue: solarBalance,
      batterySocStartValue: hour.batterySocStart?.value || 50,
      batterySocEndValue: hour.batterySocEnd?.value || 50,
      primaryReason,
      economicContext,
      opportunityScoreValue: opportunityScore,
      hourlySavingsValue: hour.hourlySavings?.value || 0,
      isActual: hour.isActual || hour.dataSource === 'actual' || false,
      isCurrentHour: hour.hour === dashboardData.currentHour,

      // Backend MUST provide FormattedValue objects - canonical naming
      buyPrice: hour.buyPrice!,
      actionValue: hour.batteryAction!,
      solarProduction: hour.solarProduction!,
      solarBalance: hour.solarBalance!,
      batterySocStart: hour.batterySocStart!,
      batterySocEnd: hour.batterySocEnd!,
      opportunityScore: hour.opportunityScore!,
      hourlySavings: hour.hourlySavings!
    };
  });

  const getScoreColor = (score: number) => {
    if (score >= 0.8) return 'text-green-600 dark:text-green-400';
    if (score >= 0.6) return 'text-yellow-600 dark:text-yellow-400';
    return 'text-red-600 dark:text-red-400';
  };

  return (
    <div className="space-y-6">
      {/* Table */}
      <div className="overflow-x-auto bg-white dark:bg-gray-800 rounded-lg shadow">
        <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
          <thead className="bg-gray-50 dark:bg-gray-700">
            <tr>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                <div className="flex items-center">
                  <Clock className="h-4 w-4 mr-1" />
                  Time
                </div>
              </th>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Price
              </th>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                <div className="flex items-center">
                  <Battery className="h-4 w-4 mr-1" />
                  Action
                </div>
              </th>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                SOC Change
              </th>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                <div className="flex items-center">
                  <Sun className="h-4 w-4 mr-1" />
                  Solar Balance
                </div>
              </th>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Decision Logic
              </th>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                <div className="flex items-center">
                  <TrendingUp className="h-4 w-4 mr-1" />
                  Score
                </div>
              </th>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Savings
              </th>
            </tr>
          </thead>
          <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
            {batteryDecisions.map((decision, index) => (
              <tr 
                key={index} 
                className={`${
                  decision.isCurrentHour ? 'bg-purple-50 dark:bg-purple-900/20 border-l-4 border-purple-400' :
                  decision.isActual ? 'bg-gray-50 dark:bg-gray-700 border-l-4 border-green-400' :
                  'border-l-4 border-gray-200 dark:border-gray-600'
                } transition-colors`}
              >
                {/* Time */}
                <td className="px-3 py-4 whitespace-nowrap text-sm">
                  <div className="flex items-center">
                    <div>
                      <div className="font-medium text-gray-900 dark:text-white text-right">
                        <div>{decision.hour.toString().padStart(2, '0')}:00</div>
                        <div className="text-xs text-gray-400 dark:text-gray-500 font-normal">-{decision.hour.toString().padStart(2, '0')}:59</div>
                      </div>
                      <div className="text-xs text-gray-500 dark:text-gray-400">
                        {decision.isCurrentHour ? 'Current' : 
                         decision.isActual ? 'Actual' : 'Predicted'}
                      </div>
                    </div>
                  </div>
                </td>

                {/* Price */}
                <td className="px-3 py-4 whitespace-nowrap text-sm">
                  <div>
                    <FormattedValueComponent
                      data={dashboardData.hourlyData.find(h => h.hour === decision.hour)?.buyPrice || decision.buyPrice}
                      size="sm"
                      align="left"
                      color={
                        decision.buyPriceValue > 1.0 ? 'danger' :
                        decision.buyPriceValue < 0.5 ? 'success' : 'default'
                      }
                      className="font-medium"
                    />
                  </div>
                </td>

                {/* Action */}
                <td className="px-3 py-4 whitespace-nowrap text-sm">
                  <div>
                    <div className="flex items-center">
                      <div className={`font-medium ${
                        decision.action === 'charge' ? 'text-green-600 dark:text-green-400' :
                        decision.action === 'discharge' ? 'text-blue-600 dark:text-blue-400' : 'text-gray-600 dark:text-gray-400'
                      }`}>
                        {decision.action === 'charge' ? `Charge (${decision.actionValue.text})` :
                         decision.action === 'discharge' ? `Discharge (${decision.actionValue.text})` :
                         'Hold'}
                      </div>
                    </div>
                  </div>
                </td>

                {/* SOC */}
                <td className="px-3 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                  <div>
                    <div className="font-medium">{decision.batterySocStart.text}</div>
                    <div className="text-gray-500 dark:text-gray-400">→ {decision.batterySocEnd.text}</div>
                  </div>
                </td>

                {/* Solar Balance */}
                <td className="px-3 py-4 whitespace-nowrap text-sm">
                  <div>
                    <div className="flex items-center">
                      <Sun className="h-3 w-3 mr-1 text-yellow-500" />
                      <span className="text-xs text-gray-500 dark:text-gray-400">{decision.solarProduction.text}</span>
                    </div>
                    <div className={`font-medium ${
                      decision.solarBalanceValue > 0 ? 'text-green-600 dark:text-green-400' :
                      decision.solarBalanceValue < 0 ? 'text-red-600 dark:text-red-400' : 'text-gray-600 dark:text-gray-400'
                    }`}>
                      {decision.solarBalance.text}
                    </div>
                  </div>
                </td>

                {/* Decision Logic */}
                <td className="px-3 py-4 text-sm text-gray-900 dark:text-white max-w-xs">
                  <div>
                    <div className="font-medium text-gray-800 dark:text-gray-200 mb-1">
                      {decision.primaryReason}
                    </div>
                    <div className="text-xs text-gray-600 dark:text-gray-400">
                      {decision.economicContext}
                    </div>
                  </div>
                </td>

                {/* Score */}
                <td className="px-3 py-4 whitespace-nowrap text-sm">
                  <div className="flex items-center">
                    <span className={`font-medium ${getScoreColor(decision.opportunityScoreValue)}`}>
                      {decision.opportunityScore.text}
                    </span>
                  </div>
                </td>

                {/* Savings */}
                <td className="px-3 py-4 whitespace-nowrap text-sm">
                  <span className={`font-medium ${
                    decision.hourlySavingsValue >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
                  }`}>
                    {decision.hourlySavings.text}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div className="mt-6 bg-gray-50 dark:bg-gray-700 p-4 rounded-lg">
        <h4 className="font-medium text-gray-800 dark:text-gray-200 mb-3">Understanding the Table</h4>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
          <div>
            <h5 className="font-medium text-gray-700 dark:text-gray-300 mb-2">Key Columns:</h5>
            <ul className="space-y-1 text-gray-600 dark:text-gray-400">
              <li><strong>Effective Diff:</strong> Price difference minus round-trip losses and cycle costs</li>
              <li><strong>Solar Balance:</strong> Solar production minus home consumption (+ = excess, - = deficit)</li>
              <li><strong>Decision Logic:</strong> Primary reason for the battery action taken</li>
              <li><strong>Score:</strong> How optimal the decision was (80%+ = excellent, 60-79% = good, &lt;60% = suboptimal)</li>
            </ul>
          </div>
          <div>
            <h5 className="font-medium text-gray-700 dark:text-gray-300 mb-2">Visual Indicators:</h5>
            <ul className="space-y-1 text-gray-600 dark:text-gray-400">
              <li><strong>Purple highlight:</strong> Current hour</li>
              <li><strong>Gray background:</strong> Completed hours</li>
              <li><strong>Green left border:</strong> Actual data</li>
              <li><strong>Gray left border:</strong> Predicted data</li>
              <li><strong>Color coding:</strong> Green = profit/positive, Red = loss/negative, Yellow = marginal</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
};