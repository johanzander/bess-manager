// src/components/DailyViewEnergyDashboard.tsx
import React, { useState, useEffect } from 'react';
import { Line, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine, ComposedChart } from 'recharts';
import { Battery, TrendingUp, Sun, Home, Grid, Activity, Clock, RefreshCw, AlertCircle } from 'lucide-react';
import api from '../lib/api';
import { EnergySankeyChart } from './EnergySankeyChart';

// Simple types to avoid interface conflicts

// API functions
const fetchEnergyBalance = async (): Promise<any> => {
  const response = await api.get('/api/energy/balance');
  return response.data;
};

const fetchDailyView = async (): Promise<any> => {
  const response = await api.get('/api/v2/daily_view');
  return response.data;
};

// Summary Cards Component
const SummaryCards: React.FC<{ 
  energyData: any; 
  dailyView: any; 
}> = ({ energyData, dailyView }) => {
  const cards = [
    {
      title: 'Total Daily Savings',
      value: dailyView.total_daily_savings.toFixed(2),
      unit: 'SEK',
      icon: TrendingUp,
      color: 'green',
      subtitle: `${dailyView.actual_savings_so_far.toFixed(2)} actual + ${dailyView.predicted_remaining_savings.toFixed(2)} predicted`
    },
    {
      title: 'Solar Production',
      value: energyData.totals.total_solar.toFixed(1),
      unit: 'kWh',
      icon: Sun,
      color: 'yellow',
      subtitle: `${energyData.totals.hours_recorded} hours recorded`
    },
    {
      title: 'Home Consumption',
      value: energyData.totals.total_consumption.toFixed(1),
      unit: 'kWh',
      icon: Home,
      color: 'blue',
      subtitle: `Average: ${(energyData.totals.total_consumption / Math.max(energyData.totals.hours_recorded, 1)).toFixed(1)} kWh/h`
    },
    {
      title: 'Battery Cycles',
      value: (energyData.totals.total_battery_charge / 30).toFixed(2),
      unit: 'cycles',
      icon: Battery,
      color: 'purple',
      subtitle: `${energyData.totals.total_battery_charge.toFixed(1)} kWh charged`
    },
    {
      title: 'Grid Balance',
      value: (energyData.totals.total_grid_import - energyData.totals.total_grid_export).toFixed(1),
      unit: 'kWh',
      icon: Grid,
      color: energyData.totals.total_grid_import > energyData.totals.total_grid_export ? 'red' : 'green',
      subtitle: `${energyData.totals.total_grid_import.toFixed(1)} in, ${energyData.totals.total_grid_export.toFixed(1)} out`
    },
    {
      title: 'Data Quality',
      value: `${dailyView.actual_hours_count}/${dailyView.actual_hours_count + dailyView.predicted_hours_count}`,
      unit: 'hours',
      icon: Activity,
      color: 'indigo',
      subtitle: `${((dailyView.actual_hours_count / (dailyView.actual_hours_count + dailyView.predicted_hours_count)) * 100).toFixed(0)}% actual data`
    }
  ];

  const getColorClasses = (color: string) => {
    const colors = {
      green: 'bg-green-50 text-green-700 border-green-200',
      yellow: 'bg-yellow-50 text-yellow-700 border-yellow-200',
      blue: 'bg-blue-50 text-blue-700 border-blue-200',
      purple: 'bg-purple-50 text-purple-700 border-purple-200',
      red: 'bg-red-50 text-red-700 border-red-200',
      indigo: 'bg-indigo-50 text-indigo-700 border-indigo-200'
    };
    return colors[color as keyof typeof colors] || colors.blue;
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
      {cards.map((card, index) => {
        const Icon = card.icon;
        return (
          <div key={index} className={`p-4 rounded-lg border ${getColorClasses(card.color)}`}>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium">{card.title}</h3>
              <Icon className="h-5 w-5" />
            </div>
            <div className="flex items-baseline space-x-2">
              <span className="text-2xl font-bold">{card.value}</span>
              <span className="text-sm opacity-75">{card.unit}</span>
            </div>
            <p className="text-xs mt-1 opacity-75">{card.subtitle}</p>
          </div>
        );
      })}
    </div>
  );
};

// Battery SOC Chart
const BatterySOCChart: React.FC<{ 
  energyData: any; 
  dailyView: any; 
}> = ({ energyData, dailyView }) => {
  const combinedData = Array.from({ length: 24 }, (_, hour) => {
    const energyHour = energyData.hourlyData.find((h: { hour: number; }) => h.hour === hour);
    const dailyViewHour = dailyView.hourly_data.find((h: { hour: number; }) => h.hour === hour);
    
    return {
      hour,
      batterySoc: energyHour?.battery_soc || 0,
      electricityPrice: dailyViewHour?.electricity_price || 0,
      dataSource: dailyViewHour?.data_source || 'unknown',
      isActual: dailyViewHour?.data_source === 'actual'
    };
  });

  return (
    <div className="bg-white p-6 rounded-lg shadow">
      <h3 className="text-lg font-semibold mb-4 flex items-center">
        <Battery className="h-5 w-5 mr-2 text-green-600" />
        Battery State of Charge & Electricity Price
      </h3>
      
      <div className="h-80">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={combinedData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="hour" interval={2} />
            <YAxis yAxisId="battery" domain={[0, 100]} label={{ value: 'SOC (%)', angle: -90, position: 'insideLeft' }} />
            <YAxis yAxisId="price" orientation="right" label={{ value: 'Price (SEK/kWh)', angle: 90, position: 'insideRight' }} />
            <Tooltip 
              formatter={(value, name, props) => {
                const isActual = props.payload.isActual;
                const prefix = isActual ? '[Actual] ' : '[Predicted] ';
                return [Number(value).toFixed(2), prefix + name];
              }}
              labelFormatter={(hour) => `Hour: ${hour}:00`}
            />
            <Legend />
            
            <ReferenceLine yAxisId="battery" x={dailyView.current_hour} stroke="#ef4444" strokeDasharray="3 3" label="Current Hour" />
            
            <Line
              yAxisId="battery"
              type="monotone"
              dataKey="batterySoc"
              stroke="#16a34a"
              strokeWidth={3}
              name="Battery SOC (%)"
              dot={(props) => (
                <circle 
                  {...props} 
                  fill={props.payload.isActual ? "#16a34a" : "#86efac"} 
                  strokeWidth={props.payload.isActual ? 2 : 1}
                  r={props.payload.isActual ? 4 : 3}
                />
              )}
            />
            
            <Line
              yAxisId="price"
              type="monotone"
              dataKey="electricityPrice"
              stroke="#2563eb"
              strokeWidth={2}
              name="Price (SEK/kWh)"
              strokeDasharray="3 3"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      
      <div className="mt-4 grid grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 bg-green-500 rounded-full"></div>
          <span>Actual SOC Data</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 bg-green-300 rounded-full"></div>
          <span>Predicted SOC Data</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 bg-blue-500 rounded-full"></div>
          <span>Electricity Price</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 bg-red-500 rounded-full"></div>
          <span>Current Hour</span>
        </div>
      </div>
    </div>
  );
};

// Savings Timeline
const SavingsTimeline: React.FC<{ dailyView: any }> = ({ dailyView }) => {
  const chartData = dailyView.hourly_data.map((hour: { hour: any; hourly_savings: any; data_source: string; }, index: number) => ({
    hour: hour.hour,
    hourlySavings: hour.hourly_savings,
    cumulativeSavings: dailyView.hourly_data.slice(0, index + 1).reduce((sum: any, h: { hourly_savings: any; }) => sum + h.hourly_savings, 0),
    isActual: hour.data_source === 'actual'
  }));

  return (
    <div className="bg-white p-6 rounded-lg shadow">
      <h3 className="text-lg font-semibold mb-4 flex items-center">
        <TrendingUp className="h-5 w-5 mr-2 text-green-600" />
        Savings Timeline
      </h3>
      
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="hour" interval={2} />
            <YAxis yAxisId="cumulative" label={{ value: 'Cumulative (SEK)', angle: -90, position: 'insideLeft' }} />
            <YAxis yAxisId="hourly" orientation="right" label={{ value: 'Hourly (SEK)', angle: 90, position: 'insideRight' }} />
            <Tooltip 
              formatter={(value, name, props) => {
                const isActual = props.payload.isActual;
                const prefix = isActual ? '[Actual] ' : '[Predicted] ';
                return [Number(value).toFixed(2), prefix + name];
              }}
            />
            <Legend />
            
            <ReferenceLine yAxisId="cumulative" x={dailyView.current_hour} stroke="#ef4444" strokeDasharray="3 3" label="Current Hour" />
            
            <Line
              yAxisId="cumulative"
              type="monotone"
              dataKey="cumulativeSavings"
              stroke="#16a34a"
              strokeWidth={3}
              name="Cumulative Savings"
              dot={(props) => (
                <circle 
                  {...props} 
                  fill={props.payload.isActual ? "#16a34a" : "#86efac"} 
                  strokeWidth={props.payload.isActual ? 2 : 1}
                  r={props.payload.isActual ? 4 : 3}
                />
              )}
            />
            
            <Bar 
              yAxisId="hourly"
              dataKey="hourlySavings"
              name="Hourly Savings"
              fill="#10b981"
              opacity={0.6}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

// Main Dashboard Component
const DailyViewEnergyDashboard: React.FC = () => {
  const [energyData, setEnergyData] = useState<any | null>(null);
  const [dailyView, setDailyView] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const [energyResponse, dailyViewResponse] = await Promise.allSettled([
        fetchEnergyBalance(),
        fetchDailyView()
      ]);
      
      if (energyResponse.status === 'fulfilled') {
        setEnergyData(energyResponse.value);
      } else {
        console.error('Failed to fetch energy balance:', energyResponse.reason);
      }
      
      if (dailyViewResponse.status === 'fulfilled') {
        setDailyView(dailyViewResponse.value);
      } else {
        console.error('Failed to fetch daily view:', dailyViewResponse.reason);
      }
      
      if (energyResponse.status === 'rejected' && dailyViewResponse.status === 'rejected') {
        setError('Failed to fetch both energy balance and daily view data');
      }
      
      setLastUpdate(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error occurred');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    
    const interval = setInterval(fetchData, 2 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  if (loading && !energyData && !dailyView) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin h-8 w-8 border-4 border-blue-500 rounded-full border-t-transparent mr-3"></div>
        <span>Loading dashboard data...</span>
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
              <Activity className="h-6 w-6 mr-2 text-blue-600" />
              Daily View & Energy Balance Dashboard
            </h1>
            <p className="text-gray-600 mt-1">
              Real-time energy flows, battery state, and savings analysis
            </p>
          </div>
          <div className="flex items-center space-x-4">
            <div className="text-sm text-gray-500">
              <Clock className="h-4 w-4 inline mr-1" />
              Last updated: {lastUpdate.toLocaleTimeString()}
            </div>
            <button
              onClick={fetchData}
              disabled={loading}
              className="flex items-center px-3 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50"
            >
              <RefreshCw className={`h-4 w-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </div>
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

      {/* Summary Cards */}
      {energyData && dailyView && (
        <SummaryCards energyData={energyData} dailyView={dailyView} />
      )}

      {/* Energy Flow Sankey Diagram */}
      {energyData && (
        <EnergySankeyChart energyData={energyData} />
      )}

      {/* Battery SOC Chart */}
      {energyData && dailyView && (
        <BatterySOCChart energyData={energyData} dailyView={dailyView} />
      )}

      {/* Savings Timeline */}
      {dailyView && (
        <SavingsTimeline dailyView={dailyView} />
      )}

      {/* Data Status */}
      <div className="bg-white p-4 rounded-lg shadow">
        <h3 className="text-md font-semibold mb-2">Data Status</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
          <div className="flex items-center justify-between">
            <span>Energy Balance Data:</span>
            <span className={`px-2 py-1 rounded text-xs ${
              energyData ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
            }`}>
              {energyData ? 'Available' : 'Not Available'}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span>Daily View Data:</span>
            <span className={`px-2 py-1 rounded text-xs ${
              dailyView ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
            }`}>
              {dailyView ? 'Available' : 'Not Available'}
            </span>
          </div>
          {energyData && (
            <div className="flex items-center justify-between">
              <span>Hours Recorded:</span>
              <span className="font-semibold">{energyData.totals.hours_recorded}/24</span>
            </div>
          )}
          {dailyView && (
            <div className="flex items-center justify-between">
              <span>Current Hour:</span>
              <span className="font-semibold">{dailyView.current_hour}:00</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default DailyViewEnergyDashboard;