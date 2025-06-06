// src/components/TableBatteryDecisionExplorer.tsx
import React, { useMemo } from 'react';
import { Battery, TrendingUp, TrendingDown, Sun, Clock, Minus } from 'lucide-react';

interface DecisionData {
  hour: number;
  action: 'charge' | 'discharge' | 'hold';
  actionValue: number;
  buyPrice: number;
  sellPrice: number;
  priceDiff: number;
  effectiveDiff: number;
  solarGenerated: number;
  homeConsumed: number;
  solarBalance: number;
  socStart: number;
  socEnd: number;
  primaryReason: string;
  economicContext: string;
  opportunityScore: number;
  savings: number;
  dataSource: string;
}

interface TableBatteryDecisionExplorerProps {
  dailyViewData: any[];
  currentHour: number;
  className?: string;
}

export const TableBatteryDecisionExplorer: React.FC<TableBatteryDecisionExplorerProps> = ({
  dailyViewData,
  currentHour,
  className = ""
}) => {
  
  // Analyze decisions and provide reasoning
  const decisionAnalysis = useMemo(() => {
    if (!dailyViewData?.length) return [];

    // Calculate price context for the day
    const prices = dailyViewData.map(h => h.electricity_price || 0);
    const sortedPrices = [...prices].sort((a, b) => a - b);
    
    return dailyViewData.map((hour, _index): DecisionData => {
      const actionValue = hour.battery_action || 
                         (hour.battery_charged > 0 ? hour.battery_charged : 
                          hour.battery_discharged > 0 ? -hour.battery_discharged : 0);
      
      let action: 'charge' | 'discharge' | 'hold' = 'hold';
      if (actionValue > 0.1) action = 'charge';
      else if (actionValue < -0.1) action = 'discharge';

      const buyPrice = hour.electricity_price || 0;
      const sellPrice = buyPrice * 0.6; // Typical sell price is ~60% of buy price
      const priceDiff = buyPrice - sellPrice;
      
      // Calculate effective arbitrage considering round-trip efficiency and cycle costs
      const roundTripEfficiency = 0.85; // 85% round-trip efficiency
      const cycleCost = 0.40; // SEK per kWh cycle cost
      const effectiveDiff = priceDiff * roundTripEfficiency - cycleCost;
      
      const pricePercentile = (sortedPrices.indexOf(buyPrice) / sortedPrices.length) * 100;

      const solarGenerated = hour.solar_generated || 0;
      const homeConsumed = hour.home_consumed || 0;
      const solarBalance = solarGenerated - homeConsumed;

      // Determine primary reasoning
      let primaryReason = 'Hold position';
      let economicContext = '';
      let opportunityScore = 0.5;

      if (action === 'charge') {
        if (pricePercentile <= 30 && solarBalance > 1) {
          primaryReason = 'Optimal: Low price + excess solar';
          economicContext = `Cheap electricity (${pricePercentile.toFixed(0)}th percentile) + ${solarBalance.toFixed(1)} kWh solar surplus`;
          opportunityScore = 0.9;
        } else if (pricePercentile <= 30) {
          primaryReason = 'Price arbitrage opportunity';
          economicContext = `Low price (${pricePercentile.toFixed(0)}th percentile), effective diff: ${effectiveDiff.toFixed(2)} SEK/kWh`;
          opportunityScore = 0.8;
        } else if (solarBalance > 1) {
          primaryReason = 'Solar excess storage';
          economicContext = `${solarBalance.toFixed(1)} kWh excess solar, avoiding export at low price`;
          opportunityScore = 0.7;
        } else if (effectiveDiff > 0) {
          primaryReason = 'Positive arbitrage expected';
          economicContext = `Effective diff: ${effectiveDiff.toFixed(2)} SEK/kWh after costs`;
          opportunityScore = 0.6;
        } else {
          primaryReason = 'Scheduled charging (suboptimal)';
          economicContext = `Negative effective diff: ${effectiveDiff.toFixed(2)} SEK/kWh`;
          opportunityScore = 0.3;
        }
      } else if (action === 'discharge') {
        if (pricePercentile >= 70) {
          primaryReason = 'High price arbitrage';
          economicContext = `Expensive electricity (${pricePercentile.toFixed(0)}th percentile), strong arbitrage`;
          opportunityScore = 0.9;
        } else if (solarBalance < -1) {
          primaryReason = 'Solar deficit coverage';
          economicContext = `${Math.abs(solarBalance).toFixed(1)} kWh solar deficit, using stored energy`;
          opportunityScore = 0.8;
        } else if (effectiveDiff > 0) {
          primaryReason = 'Arbitrage opportunity';
          economicContext = `Effective diff: ${effectiveDiff.toFixed(2)} SEK/kWh profit expected`;
          opportunityScore = 0.7;
        } else {
          primaryReason = 'Scheduled discharge (suboptimal)';
          economicContext = `Negative effective diff: ${effectiveDiff.toFixed(2)} SEK/kWh`;
          opportunityScore = 0.4;
        }
      } else {
        if (pricePercentile >= 70 && hour.battery_soc_start < 20) {
          primaryReason = 'Cannot discharge: Low SOC';
          economicContext = 'Battery too low during high-price period';
          opportunityScore = 0.3;
        } else if (pricePercentile <= 30 && hour.battery_soc_start > 90) {
          primaryReason = 'Cannot charge: Battery full';
          economicContext = 'Battery at capacity during cheap prices';
          opportunityScore = 0.4;
        } else if (Math.abs(effectiveDiff) < 0.1) {
          primaryReason = 'Optimal hold: Marginal value';
          economicContext = `Effective diff: ${effectiveDiff.toFixed(2)} SEK/kWh - below action threshold`;
          opportunityScore = 0.8;
        } else if (effectiveDiff < 0) {
          primaryReason = 'Optimal hold: Negative value';
          economicContext = `Effective diff: ${effectiveDiff.toFixed(2)} SEK/kWh - action would lose money`;
          opportunityScore = 0.8;
        } else {
          primaryReason = 'Hold: Unknown constraint';
          economicContext = `Positive value (${effectiveDiff.toFixed(2)} SEK/kWh) but constraints prevent action`;
          opportunityScore = 0.5;
        }
      }

      return {
        hour: hour.hour,
        action,
        actionValue: Math.abs(actionValue),
        buyPrice,
        sellPrice,
        priceDiff,
        effectiveDiff,
        solarGenerated,
        homeConsumed,
        solarBalance,
        socStart: hour.battery_soc_start || 0,
        socEnd: hour.battery_soc_end || 0,
        primaryReason,
        economicContext,
        opportunityScore,
        savings: hour.hourly_savings || 0,
        dataSource: hour.data_source || 'unknown'
      };
    });
  }, [dailyViewData]);

  const getActionIcon = (action: string) => {
    const iconClass = "h-4 w-4";
    if (action === 'charge') return <TrendingUp className={`${iconClass} text-green-600`} />;
    if (action === 'discharge') return <TrendingDown className={`${iconClass} text-blue-600`} />;
    return <Minus className={`${iconClass} text-gray-400`} />;
  };

  const getScoreColor = (score: number) => {
    if (score >= 0.8) return 'text-green-600';
    if (score >= 0.6) return 'text-yellow-600';
    return 'text-red-600';
  };

  return (
    <div className={`bg-white p-6 rounded-lg shadow ${className}`}>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold flex items-center">
          <Battery className="h-5 w-5 mr-2 text-purple-600" />
          Battery Decision Analysis Table
        </h2>
        <div className="text-sm text-gray-600">
          Current hour: {currentHour}:00
        </div>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-green-50 p-3 rounded-lg text-center">
          <div className="text-lg font-bold text-green-600">
            {decisionAnalysis.filter(d => d.action === 'charge').length}
          </div>
          <div className="text-sm text-gray-600">Charging Hours</div>
        </div>
        <div className="bg-blue-50 p-3 rounded-lg text-center">
          <div className="text-lg font-bold text-blue-600">
            {decisionAnalysis.filter(d => d.action === 'discharge').length}
          </div>
          <div className="text-sm text-gray-600">Discharging Hours</div>
        </div>
        <div className="bg-gray-50 p-3 rounded-lg text-center">
          <div className="text-lg font-bold text-gray-600">
            {decisionAnalysis.filter(d => d.action === 'hold').length}
          </div>
          <div className="text-sm text-gray-600">Hold Hours</div>
        </div>
        <div className="bg-purple-50 p-3 rounded-lg text-center">
          <div className="text-lg font-bold text-purple-600">
            {(decisionAnalysis.reduce((sum, d) => sum + d.opportunityScore, 0) / decisionAnalysis.length * 100).toFixed(0)}%
          </div>
          <div className="text-sm text-gray-600">Avg Decision Score</div>
        </div>
      </div>

      {/* Decision Table */}
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Hour</th>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Buy/Sell Price</th>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Price Diff</th>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Effective Diff</th>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Battery Action</th>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">SOC (kWh)</th>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Solar Balance</th>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Decision Logic</th>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Score</th>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Savings</th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {decisionAnalysis.map((decision) => (
              <tr
                key={decision.hour}
                className={`
                  ${decision.hour === currentHour ? 'bg-purple-50 ring-2 ring-purple-200' : ''}
                  ${decision.hour < currentHour ? 'bg-gray-50' : ''}
                  ${decision.dataSource === 'actual' ? 'border-l-4 border-green-400' : 'border-l-4 border-gray-200'}
                `}
              >
                {/* Hour */}
                <td className="px-3 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                  <div className="flex items-center">
                    <Clock className="h-4 w-4 mr-1 text-gray-400" />
                    {decision.hour}:00
                    {decision.dataSource === 'actual' && (
                      <span className="ml-2 text-xs bg-green-100 text-green-700 px-2 py-1 rounded">
                        Actual
                      </span>
                    )}
                  </div>
                </td>

                {/* Buy/Sell Price */}
                <td className="px-3 py-4 whitespace-nowrap text-sm text-gray-900">
                  <div>
                    <div className="font-medium">{decision.buyPrice.toFixed(3)}</div>
                    <div className="text-gray-500">{decision.sellPrice.toFixed(3)}</div>
                  </div>
                </td>

                {/* Price Diff */}
                <td className="px-3 py-4 whitespace-nowrap text-sm text-gray-900">
                  <span className="font-medium">{decision.priceDiff.toFixed(3)}</span>
                </td>

                {/* Effective Diff */}
                <td className="px-3 py-4 whitespace-nowrap text-sm">
                  <span className={`font-medium ${
                    decision.effectiveDiff > 0 ? 'text-green-600' : 'text-red-600'
                  }`}>
                    {decision.effectiveDiff.toFixed(3)}
                  </span>
                </td>

                {/* Battery Action */}
                <td className="px-3 py-4 whitespace-nowrap text-sm">
                  <div className="flex items-center">
                    {getActionIcon(decision.action)}
                    <div className="ml-2">
                      <div className={`font-medium ${
                        decision.action === 'charge' ? 'text-green-600' :
                        decision.action === 'discharge' ? 'text-blue-600' : 'text-gray-600'
                      }`}>
                        {decision.action === 'charge' ? `Charge (+${decision.actionValue.toFixed(1)} kW)` :
                         decision.action === 'discharge' ? `Discharge (${decision.actionValue.toFixed(1)} kW)` :
                         'Hold (0.0 kW)'}
                      </div>
                    </div>
                  </div>
                </td>

                {/* SOC */}
                <td className="px-3 py-4 whitespace-nowrap text-sm text-gray-900">
                  <div>
                    <div className="font-medium">{decision.socStart.toFixed(1)}</div>
                    <div className="text-gray-500">→ {decision.socEnd.toFixed(1)}</div>
                  </div>
                </td>

                {/* Solar Balance */}
                <td className="px-3 py-4 whitespace-nowrap text-sm">
                  <div>
                    <div className="flex items-center">
                      <Sun className="h-3 w-3 mr-1 text-yellow-500" />
                      <span className="text-xs">{decision.solarGenerated.toFixed(1)}</span>
                    </div>
                    <div className={`font-medium ${
                      decision.solarBalance > 0 ? 'text-green-600' : 
                      decision.solarBalance < 0 ? 'text-red-600' : 'text-gray-600'
                    }`}>
                      {decision.solarBalance > 0 ? '+' : ''}{decision.solarBalance.toFixed(1)}
                    </div>
                  </div>
                </td>

                {/* Decision Logic */}
                <td className="px-3 py-4 text-sm text-gray-900 max-w-xs">
                  <div>
                    <div className="font-medium text-gray-800 mb-1">
                      {decision.primaryReason}
                    </div>
                    <div className="text-xs text-gray-600">
                      {decision.economicContext}
                    </div>
                  </div>
                </td>

                {/* Score */}
                <td className="px-3 py-4 whitespace-nowrap text-sm">
                  <div className="flex items-center">
                    <span className={`font-medium ${getScoreColor(decision.opportunityScore)}`}>
                      {(decision.opportunityScore * 100).toFixed(0)}%
                    </span>
                  </div>
                </td>

                {/* Savings */}
                <td className="px-3 py-4 whitespace-nowrap text-sm">
                  <span className={`font-medium ${
                    decision.savings >= 0 ? 'text-green-600' : 'text-red-600'
                  }`}>
                    {decision.savings >= 0 ? '+' : ''}{decision.savings.toFixed(2)} SEK
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div className="mt-6 bg-gray-50 p-4 rounded-lg">
        <h4 className="font-medium text-gray-800 mb-3">Understanding the Table</h4>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
          <div>
            <h5 className="font-medium text-gray-700 mb-2">Key Columns:</h5>
            <ul className="space-y-1 text-gray-600">
              <li><strong>Effective Diff:</strong> Price difference minus round-trip losses and cycle costs</li>
              <li><strong>Solar Balance:</strong> Solar production minus home consumption (+ = excess, - = deficit)</li>
              <li><strong>Decision Logic:</strong> Primary reason for the battery action taken</li>
              <li><strong>Score:</strong> How optimal the decision was (80%+ = excellent, 60-79% = good, &lt;60% = suboptimal)</li>
            </ul>
          </div>
          <div>
            <h5 className="font-medium text-gray-700 mb-2">Visual Indicators:</h5>
            <ul className="space-y-1 text-gray-600">
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