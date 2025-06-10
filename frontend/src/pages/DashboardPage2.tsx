import React, { useState, useEffect } from 'react';
import { Activity, Clock, RefreshCw, AlertCircle, Battery, TrendingUp, Zap, DollarSign } from 'lucide-react';
import api from '../lib/api';

const fetchDashboardData = async () => {
  try {
    // Use Promise.allSettled to handle partial failures gracefully
    const [dailyViewResponse, energyResponse, inverterResponse, systemInfoResponse] = await Promise.allSettled([
      api.get('/api/v2/daily_view'),
      api.get('/api/energy/balance'), 
      api.get('/api/growatt/inverter_status'), // FIXED: Use actual inverter status endpoint
      api.get('/api/system/info')
    ]);

    const result: any = {};

    // Handle daily view data
    if (dailyViewResponse.status === 'fulfilled') {
      result.dailyViewData = dailyViewResponse.value.data;
    } else {
      console.warn('Failed to fetch daily view:', dailyViewResponse.reason);
      // Provide minimal fallback
      result.dailyViewData = {
        current_hour: new Date().getHours(),
        total_daily_savings: 0,
        actual_cost: 0,
        predicted_cost: 0,
        base_cost: 0,
        actual_hours_count: new Date().getHours(),
        predicted_hours_count: 24 - new Date().getHours(),
        hourly_data: Array.from({ length: 24 }, (_, hour) => ({
          hour,
          home_consumed: 0,
          solar_generated: 0,
          electricity_price: 1.0
        }))
      };
    }

    // Handle energy data
    if (energyResponse.status === 'fulfilled') {
      result.energyData = energyResponse.value.data;
    } else {
      console.warn('Failed to fetch energy data:', energyResponse.reason);
      result.energyData = {
        current: {
          battery_soc: 0,
          battery_soe: 0,
          battery_power: 0,
          solar_power: 0,
          load_power: 0,
          grid_power: 0
        },
        hourlyData: []
      };
    }

    // FIXED: Handle real inverter status data
    if (inverterResponse.status === 'fulfilled') {
      result.inverterStatus = inverterResponse.value.data;
    } else {
      console.warn('Failed to fetch inverter status:', inverterResponse.reason);
      // Fallback to constructed data from energy API
      const currentHour = result.dailyViewData.current_hour;
      const batteryPower = result.energyData?.current?.battery_power || 0;
      
      result.inverterStatus = {
        battery_soc: result.energyData?.current?.battery_soc || 0,
        battery_soe: result.energyData?.current?.battery_soe || 0,
        total_capacity: 10.0, // Should come from settings
        current_power: batteryPower,
        power_direction: batteryPower > 0.1 ? 'charging' : 
                        batteryPower < -0.1 ? 'discharging' : 'idle',
        current_mode: 'Grid-First', // Should come from inverter settings
        next_change_hour: Math.min(currentHour + 1, 23),
        next_action: 'Idle',
        grid_charge_enabled: true,
        battery_charge_power: batteryPower > 0 ? batteryPower : 0,
        battery_discharge_power: batteryPower < 0 ? Math.abs(batteryPower) : 0,
        charge_stop_soc: 100,
        discharge_stop_soc: 10,
        discharge_power_rate: 100,
        max_charging_power: 6000,
        max_discharging_power: 6000
      };
    }

    // Handle system info
    if (systemInfoResponse.status === 'fulfilled') {
      result.systemInfo = systemInfoResponse.value.data;
    }

    // Extract price data from daily view
    const hourlyPrices = result.dailyViewData.hourly_data?.map(h => h.electricity_price) || [1.0];
    const currentHour = result.dailyViewData.current_hour;
    
    result.priceData = {
      current_price: result.dailyViewData.hourly_data?.[currentHour]?.electricity_price || 1.0,
      min_price: Math.min(...hourlyPrices),
      max_price: Math.max(...hourlyPrices),
      avg_price: hourlyPrices.reduce((sum, price) => sum + price, 0) / hourlyPrices.length,
      peak_start: 17,
      peak_end: 19
    };

    return result;
    
  } catch (error) {
    console.error('Error fetching dashboard data:', error);
    throw error;
  }
};

const FinancialSummaryCard = ({ dailyViewData }) => {
  const currentHour = new Date().getHours();
  
  // FIXED: At 23:55, actualHours should be 24 (hours 0-23 completed)
  // and predicted should be 0 (no future hours remaining)
  const actualHours = Math.min(currentHour + 1, 24); // +1 because current hour is completing
  const predictedHours = Math.max(24 - actualHours, 0);
  
  const progressPercentage = (actualHours / 24) * 100;
  
  // Calculate costs from hourly data if not directly available
  const actualCost = dailyViewData?.hourly_data?.
    filter(h => h.data_source === 'actual')?.
    reduce((sum, h) => sum + (h.hourly_cost || 0) + (h.battery_cycle_cost || 0), 0) || 0;
    
  const predictedCost = dailyViewData?.hourly_data?.
    filter(h => h.data_source === 'predicted')?.
    reduce((sum, h) => sum + (h.hourly_cost || 0) + (h.battery_cycle_cost || 0), 0) || 0;
    
  const optimizedCost = actualCost + predictedCost;
  
  // Calculate base cost (what it would cost without optimization)
  const baseCost = dailyViewData?.hourly_data?.
    reduce((sum, h) => sum + (h.home_consumed || 0) * (h.electricity_price || h.buy_price || 1), 0) || 0;
    
  const savings = dailyViewData?.total_daily_savings || 0;

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <div className="flex items-center mb-6">
        <div className="bg-gray-50 rounded-full flex items-center justify-center w-10 h-10 mr-3">
          <DollarSign className="h-5 w-5 text-gray-600" />
        </div>
        <h3 className="text-lg font-medium text-gray-900">Daily Cost & Savings</h3>
      </div>
      
      <div className="space-y-4 mb-6">
        <div className="flex justify-between items-center">
          <span className="text-sm text-gray-600">Optimized cost</span>
          <span className="text-2xl font-bold text-green-600">{optimizedCost.toFixed(2)} SEK</span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-sm text-gray-600">Base cost</span>
          <span className="text-sm text-gray-900">{baseCost.toFixed(2)} SEK</span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-sm text-gray-600">Savings</span>
          <span className="text-2xl font-bold text-green-600">{savings.toFixed(2)} SEK</span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-sm text-gray-600">Savings %</span>
          <span className="text-lg font-semibold text-green-600">
            {baseCost > 0 ? ((savings / baseCost) * 100).toFixed(1) : '0'}%
          </span>
        </div>
      </div>

      <div className="pt-4 border-t border-gray-200">
        <div className="flex justify-between text-xs text-gray-500 mb-2">
          <span>00:00</span>
          <span>24:00</span>
        </div>
        
        <div className="relative mb-3">
          <div className="w-full h-4 bg-gray-200 rounded-full overflow-hidden">
            <div className="h-full bg-blue-600 transition-all duration-1000" style={{ width: `${progressPercentage}%` }} />
          </div>
          {/* FIXED: Removed red time digits, kept only the red line */}
          <div className="absolute top-0 h-4 w-0.5 bg-red-500" style={{ left: `${Math.min(Math.max(progressPercentage, 8), 92)}%` }} />
        </div>
        
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <div className="font-medium text-gray-900">{actualCost.toFixed(2)} SEK</div>
            {/* FIXED: Show correct range based on actualHours */}
            <div className="text-xs text-gray-500">
              Actual (0-{actualHours === 24 ? '23' : (actualHours - 1).toString()}h)
            </div>
          </div>
          <div className="text-right">
            <div className="font-medium text-gray-900">{predictedCost.toFixed(2)} SEK</div>
            {/* FIXED: Show correct range for predicted hours */}
            <div className="text-xs text-gray-500">
              {predictedHours > 0 ? `Predicted (${actualHours}-23h)` : 'All hours completed'}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

const BatteryStatusCard = ({ inverterStatus }) => {
  // FIXED: Use real data from API instead of fallback
  const socPercentage = inverterStatus?.battery_soc || 0;
  const batterySOE = inverterStatus?.battery_soe || 0;
  const totalCapacity = inverterStatus?.total_capacity || 
                       (batterySOE > 0 && socPercentage > 0 ? (batterySOE / socPercentage) * 100 : 10.0);
  
  // FIXED: Use actual power values from inverter status
  const chargePower = inverterStatus?.battery_charge_power || 0;
  const dischargePower = inverterStatus?.battery_discharge_power || 0;
  
  const isCharging = chargePower > 100; // > 100W to avoid noise
  const isDischarging = dischargePower > 100;
  const batteryPower = isCharging ? chargePower : isDischarging ? dischargePower : 0;

  const getStatus = () => {
    if (isCharging) return 'Charging';
    if (isDischarging) return 'Discharging';
    return 'Idle';
  };

  const getBatteryColor = () => {
    if (socPercentage > 60) return '#4CAF50';
    if (socPercentage > 30) return '#FF9800';
    return '#F44336';
  };

  const formatPower = (power: number): string => {
    if (Math.abs(power) >= 1000) {
      return `${(power / 1000).toFixed(1)} kW`;
    }
    return `${power.toFixed(0)} W`;
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <div className="flex items-center mb-6">
        <div className="bg-gray-50 rounded-full flex items-center justify-center w-10 h-10 mr-3">
          <Battery className="h-5 w-5 text-gray-600" />
        </div>
        <h3 className="text-lg font-medium text-gray-900">Battery</h3>
      </div>
      
      <div className="flex items-start space-x-6 mb-6">
        <div className="relative flex-shrink-0">
          <svg width="48" height="72" viewBox="0 0 48 72" className="drop-shadow-sm">
            <rect x="8" y="8" width="32" height="56" rx="4" fill="#E5E7EB" stroke="#9CA3AF" strokeWidth="2"/>
            <rect x="18" y="0" width="12" height="8" rx="2" fill="#9CA3AF"/>
            <rect x="10" y={64 - (socPercentage * 0.52)} width="28" height={socPercentage * 0.52} rx="2" fill={getBatteryColor()}/>
            {isCharging && (
              <text x="24" y="40" textAnchor="middle" dominantBaseline="middle" fontSize="20" fill="white" className="animate-pulse">⚡</text>
            )}
          </svg>
        </div>
        
        <div className="flex-1">
          <div className="text-2xl font-bold text-gray-900 leading-none mb-1">{socPercentage.toFixed(0)}%</div>
          <div className="text-xs text-gray-500 mb-4">
            {batterySOE.toFixed(1)} / {totalCapacity.toFixed(1)} kWh
          </div>
          
          <div className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium ${
            isCharging ? 'bg-blue-100 text-blue-800' :
            isDischarging ? 'bg-orange-100 text-orange-800' :
            'bg-gray-100 text-gray-800'
          }`}>
            {getStatus()}
            <span className="ml-2 font-bold">
              {isCharging ? '+' : isDischarging ? '-' : '±'}{formatPower(batteryPower)}
            </span>
          </div>
        </div>
      </div>

      <div className="space-y-3">
        <div className="flex justify-between items-center py-2">
          <span className="text-sm text-gray-600">
            {isCharging ? 'Charging Rate' : isDischarging ? 'Discharging Rate' : 'Power Rate'}
          </span>
          <span className="text-sm font-medium text-gray-900">
            {isCharging || isDischarging ? 
              `${((batteryPower / 1000 / totalCapacity) * 100).toFixed(1)}%` : '0%'}
          </span>
        </div>
        <div className="flex justify-between items-center py-2">
          <span className="text-sm text-gray-600">Grid Charge</span>
          <span className="text-sm font-medium text-gray-900">
            {inverterStatus?.grid_charge_enabled ? 'Enabled' : 'Disabled'}
          </span>
        </div>
        <div className="flex justify-between items-center py-2">
          <span className="text-sm text-gray-600">Charge Stop</span>
          <span className="text-sm font-medium text-gray-900">
            {inverterStatus?.charge_stop_soc?.toFixed(0) || '100'}%
          </span>
        </div>
        <div className="flex justify-between items-center py-2">
          <span className="text-sm text-gray-600">Discharge Stop</span>
          <span className="text-sm font-medium text-gray-900">
            {inverterStatus?.discharge_stop_soc?.toFixed(0) || '10'}%
          </span>
        </div>
        <div className="flex justify-between items-center py-2">
          <span className="text-sm text-gray-600">Discharge Rate</span>
          <span className="text-sm font-medium text-gray-900">
            {inverterStatus?.discharge_power_rate?.toFixed(0) || '100'}%
          </span>
        </div>
      </div>
    </div>
  );
};

const PowerFlowCard = ({ inverterStatus, energyData }) => {
  const solarPower = energyData?.current?.solar_power || 0;
  const loadPower = energyData?.current?.load_power || 0;
  const batteryPower = Math.abs(inverterStatus?.current_power || inverterStatus?.battery_charge_power || inverterStatus?.battery_discharge_power || 0);
  const gridPower = energyData?.current?.grid_power || 0;
  const isCharging = (inverterStatus?.battery_charge_power || 0) > 100;

  return (
    <div className="bg-gradient-to-br from-slate-50 to-blue-50 rounded-xl shadow-sm border border-gray-200 p-6">
      <div className="flex items-center mb-6">
        <div className="bg-gray-50 rounded-full flex items-center justify-center w-10 h-10 mr-3">
          <Zap className="h-5 w-5 text-gray-600" />
        </div>
        <h3 className="text-lg font-medium text-gray-900">Live Power Flow</h3>
      </div>
      
      <div className="relative h-40">
        <div className="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2">
          <div className="w-20 h-20 bg-white rounded-2xl shadow-xl border-4 border-blue-200 flex items-center justify-center relative">
            <div className="text-center">
              <div className="text-3xl mb-1">🏠</div>
              <div className="text-sm font-bold text-gray-900">{(loadPower / 1000).toFixed(1)}kW</div>
            </div>
            <div className="absolute inset-0 rounded-2xl border-2 border-blue-300 animate-ping opacity-75"></div>
          </div>
        </div>

        <div className="absolute top-0 left-1/2 transform -translate-x-1/2">
          <div className="w-16 h-12 bg-gradient-to-br from-yellow-400 via-orange-400 to-red-500 rounded-lg shadow-lg border-2 border-yellow-300 flex items-center justify-center">
            <div className="text-center text-white">
              <div className="text-lg">☀</div>
              <div className="text-xs font-bold">{(solarPower / 1000).toFixed(1)}kW</div>
            </div>
          </div>
        </div>

        <div className="absolute bottom-0 left-8">
          <div className={`w-16 h-12 rounded-lg shadow-lg border-2 flex items-center justify-center ${
            isCharging ? 'bg-gradient-to-br from-blue-500 to-blue-700 border-blue-400' : 'bg-gradient-to-br from-orange-500 to-red-600 border-orange-400'
          }`}>
            <div className="text-center text-white">
              <div className="text-lg">🔋</div>
              <div className="text-xs font-bold">{(batteryPower / 1000).toFixed(1)}kW</div>
            </div>
          </div>
        </div>

        <div className="absolute bottom-0 right-8">
          <div className="w-16 h-12 bg-gradient-to-br from-gray-600 to-gray-800 rounded-lg shadow-lg border-2 flex items-center justify-center">
            <div className="text-center text-white">
              <div className="text-lg">⚡</div>
              <div className="text-xs font-bold">{Math.abs(gridPower / 1000).toFixed(1)}kW</div>
            </div>
          </div>
        </div>

        <svg className="absolute inset-0 w-full h-full">
          <path d="M 50 30 Q 50 50 50 70" stroke="#fbbf24" strokeWidth="6" fill="none" opacity="0.8" strokeLinecap="round" />
          <path d="M 40 130 Q 45 110 50 90" stroke={isCharging ? '#3b82f6' : '#f97316'} strokeWidth="6" fill="none" opacity="0.8" strokeLinecap="round" />
          <path d="M 60 130 Q 55 110 50 90" stroke="#6b7280" strokeWidth="6" fill="none" opacity="0.6" strokeLinecap="round" />
        </svg>
      </div>
    </div>
  );
};

const ElectricityPricesCard = ({ priceData, dailyViewData }) => {
  const currentPrice = priceData?.current_price || 0;
  const minPrice = priceData?.min_price || 0;
  const maxPrice = priceData?.max_price || 1;
  const avgPrice = priceData?.avg_price || 0;
  const currentHour = dailyViewData?.current_hour || 0;
  
  const hourlyPrices = dailyViewData?.hourly_data?.map(h => h.electricity_price) || 
                      Array.from({ length: 24 }, () => 0);
  const isPeakHour = currentHour >= (priceData?.peak_start || 17) && currentHour <= (priceData?.peak_end || 19);
  
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <div className="flex items-center mb-6">
        <div className="bg-gray-50 rounded-full flex items-center justify-center w-10 h-10 mr-3">
          <TrendingUp className="h-5 w-5 text-gray-600" />
        </div>
        <h3 className="text-lg font-medium text-gray-900">Electricity Price</h3>
      </div>
      
      <div className="text-center mb-4">
        <div className={`inline-flex items-center px-3 py-2 rounded-lg ${
          isPeakHour ? 'bg-red-100 border border-red-200' : 'bg-blue-50 border border-blue-200'
        }`}>
          <div className="text-2xl font-bold text-gray-900 mr-1">{currentPrice.toFixed(2)}</div>
          <div className="text-xs text-gray-600">SEK/kWh</div>
        </div>
        {isPeakHour && <div className="text-xs text-red-600 font-medium mt-1">Peak Hour</div>}
      </div>

      <div className="mb-4">
        <div className="h-12 bg-gray-50 rounded-lg p-1 relative overflow-hidden">
          <svg width="100%" height="100%" viewBox="0 0 96 40" className="absolute inset-0">
            {hourlyPrices.slice(0, 24).map((price, i) => {
              const barHeight = maxPrice > minPrice ? ((price - minPrice) / (maxPrice - minPrice)) * 32 : 16;
              const isCurrentHour = i === currentHour;
              
              return (
                <rect
                  key={i}
                  x={i * 4}
                  y={32 - barHeight}
                  width="3"
                  height={Math.max(barHeight, 1)}
                  fill={isCurrentHour ? '#ef4444' : price > avgPrice * 1.2 ? '#f59e0b' : price < avgPrice * 0.8 ? '#10b981' : '#6b7280'}
                  opacity={isCurrentHour ? 1 : 0.7}
                />
              );
            })}
          </svg>
        </div>
        <div className="flex justify-between text-xs text-gray-500 mt-1">
          <span>00</span>
          <span>12</span>
          <span>24</span>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 text-xs">
        <div className="text-center p-1 bg-green-50 rounded">
          <div className="text-green-700 font-medium">{minPrice.toFixed(2)}</div>
          <div className="text-green-600">Min</div>
        </div>
        <div className="text-center p-1 bg-gray-50 rounded">
          <div className="text-gray-700 font-medium">{avgPrice.toFixed(2)}</div>
          <div className="text-gray-600">Avg</div>
        </div>
        <div className="text-center p-1 bg-red-50 rounded">
          <div className="text-red-700 font-medium">{maxPrice.toFixed(2)}</div>
          <div className="text-red-600">Max</div>
        </div>
      </div>
    </div>
  );
};

const EnhancedEnergyFlowChart = ({ dailyViewData, energyData, currentHour }) => {
  if (!dailyViewData?.hourly_data) return null;
  
  const chartData = dailyViewData.hourly_data.map((dailyViewHour, hour) => {
    const actualData = energyData?.hourlyData?.find(h => h.hour === hour);
    const isActual = dailyViewHour.data_source === 'actual';
    
    return {
      hour,
      actualConsumption: isActual ? dailyViewHour.home_consumed : null,
      predictedConsumption: !isActual ? dailyViewHour.home_consumed : null,
      actualSolar: isActual ? dailyViewHour.solar_generated : 0,
      predictedSolar: !isActual ? dailyViewHour.solar_generated : 0,
      price: dailyViewHour.electricity_price || dailyViewHour.buy_price || 0,
      isActual
    };
  });

  const maxValue = Math.max(...chartData.map(d => Math.max(
    d.actualConsumption || 0, d.predictedConsumption || 0, d.actualSolar, d.predictedSolar
  )), 1);

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center">
          <div className="bg-gray-50 rounded-full flex items-center justify-center w-10 h-10 mr-3">
            <Activity className="h-5 w-5 text-gray-600" />
          </div>
          <h3 className="text-lg font-medium text-gray-900">Energy Flow: Predictions vs Reality</h3>
        </div>
        <div className="text-sm text-gray-600">Current Hour: {currentHour}:00</div>
      </div>
      
      <div className="h-64 relative">
        <svg width="100%" height="100%" viewBox="0 0 800 200">
          <polyline
            fill="none"
            stroke="#ef4444"
            strokeWidth="2"
            strokeDasharray="5,5"
            points={chartData.map((data, i) => 
              `${i * 33.33},${180 - (data.price / Math.max(...chartData.map(d => d.price), 1)) * 160}`
            ).join(' ')}
          />
          
          {chartData.map((data, i) => {
            const x = i * 33.33;
            const consumption = (data.isActual ? data.actualConsumption : data.predictedConsumption) || 0;
            const solar = data.isActual ? data.actualSolar : data.predictedSolar;
            const consumptionHeight = (consumption / maxValue) * 120;
            const solarHeight = (solar / maxValue) * 120;
            
            return (
              <g key={i}>
                <rect
                  x={x}
                  y={160 - consumptionHeight}
                  width="12"
                  height={consumptionHeight}
                  fill={data.isActual ? "#3b82f6" : "#93c5fd"}
                  opacity={data.isActual ? 1 : 0.7}
                />
                
                <rect
                  x={x + 15}
                  y={160 - solarHeight}
                  width="12"
                  height={solarHeight}
                  fill={data.isActual ? "#eab308" : "#fde047"}
                  opacity={data.isActual ? 1 : 0.7}
                />
                
                {i === currentHour && (
                  <line
                    x1={x + 13}
                    y1="0"
                    x2={x + 13}
                    y2="160"
                    stroke="#ef4444"
                    strokeWidth="2"
                    strokeDasharray="3,3"
                  />
                )}
                
                {i % 4 === 0 && (
                  <text x={x + 13} y="190" textAnchor="middle" fontSize="10" fill="#6b7280">
                    {i}:00
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      
      <div className="flex items-center justify-center space-x-6 mt-4 text-sm">
        <div className="flex items-center">
          <div className="w-4 h-4 bg-blue-500 mr-2"></div>
          <span>Consumption (Actual)</span>
        </div>
        <div className="flex items-center">
          <div className="w-4 h-4 bg-blue-300 mr-2"></div>
          <span>Consumption (Predicted)</span>
        </div>
        <div className="flex items-center">
          <div className="w-4 h-4 bg-yellow-500 mr-2"></div>
          <span>Solar (Actual)</span>
        </div>
        <div className="flex items-center">
          <div className="w-4 h-4 bg-yellow-300 mr-2"></div>
          <span>Solar (Predicted)</span>
        </div>
        <div className="flex items-center">
          <div className="w-2 h-2 border border-red-500 mr-2" style={{borderStyle: 'dashed'}}></div>
          <span>Electricity Price</span>
        </div>
      </div>
    </div>
  );
};

interface DashboardProps {
  onLoadingChange: (loading: boolean) => void;
  settings: any;
}

export default function DashboardPage({ onLoadingChange, settings }: DashboardProps) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState(new Date());

  const fetchData = async () => {
    try {
      setLoading(true);
      onLoadingChange(true);
      const dashboardData = await fetchDashboardData();
      setData(dashboardData);
      setLastUpdate(new Date());
      setError(null);
    } catch (err) {
      setError('Failed to fetch dashboard data');
      console.error(err);
    } finally {
      setLoading(false);
      onLoadingChange(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 2 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  if (loading && !data) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center bg-white rounded-lg p-8 shadow-sm">
          <RefreshCw className="h-8 w-8 animate-spin text-gray-600 mx-auto mb-4" />
          <p className="text-gray-600">Loading dashboard...</p>
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center bg-white rounded-lg p-8 shadow-sm">
          <AlertCircle className="h-8 w-8 text-red-600 mx-auto mb-4" />
          <p className="text-gray-600 mb-4">{error}</p>
          <button onClick={fetchData} className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
            Retry
          </button>
        </div>
      </div>
    );
  }

  const currentHour = data?.dailyViewData?.current_hour || 0;

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="mb-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 flex items-center">
              <Activity className="h-6 w-6 text-gray-700 mr-3" />
              Energy Dashboard
            </h1>
            <p className="text-gray-600 mt-1">Real-time monitoring of your BESS performance</p>
          </div>
          <div className="flex items-center space-x-4">
            <div className="text-sm text-gray-500 flex items-center">
              <Clock className="h-4 w-4 mr-1" />
              Updated: {lastUpdate.toLocaleTimeString()}
            </div>
            <button
              onClick={fetchData}
              disabled={loading}
              className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-xl hover:bg-blue-700 disabled:opacity-50 font-medium"
            >
              <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-6 mb-8">
        <FinancialSummaryCard dailyViewData={data?.dailyViewData} />
        <BatteryStatusCard inverterStatus={data?.inverterStatus} />
        <PowerFlowCard inverterStatus={data?.inverterStatus} energyData={data?.energyData} />
        <ElectricityPricesCard priceData={data?.priceData} dailyViewData={data?.dailyViewData} />
      </div>

      <div className="mb-8">
        <EnhancedEnergyFlowChart 
          dailyViewData={data?.dailyViewData}
          energyData={data?.energyData}
          currentHour={currentHour}
        />
      </div>

      {error && data && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-4">
          <div className="flex items-center">
            <AlertCircle className="h-5 w-5 text-yellow-500 mr-3" />
            <span className="text-yellow-700">Partial data: {error}</span>
          </div>
        </div>
      )}
    </div>
  );
}