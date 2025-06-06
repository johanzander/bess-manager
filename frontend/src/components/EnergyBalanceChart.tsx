import React from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine } from 'recharts';
import { HourlyData } from '../types';

interface EnergyBalanceChartProps {
  hourlyData: HourlyData[];
}

export const EnergyBalanceChart: React.FC<EnergyBalanceChartProps> = ({ hourlyData }) => {
  // Process data for the chart
  const chartData = hourlyData.map(hour => {
    const homeConsumption = hour.consumption || 0;
    const solarProduction = hour.solarProduction || 0;
    const batteryAction = hour.action || 0;
    
    // Battery data - either from direct fields or action
    const batteryCharge = hour.batteryCharge || (batteryAction > 0 ? batteryAction : 0);
    const batteryDischarge = hour.batteryDischarge || (batteryAction < 0 ? -batteryAction : 0);
    
    // Grid data - either from direct fields or calculated
    const gridImport = hour.gridImport || 0;
    const gridExport = hour.gridExport || 0;
    
    // Calculate derived values if not directly available
    
    // Consumption by source (negative values for chart)
    const consumptionFromGrid = -gridImport;
    const consumptionFromBattery = -batteryDischarge;
    
    // Calculate consumption from solar
    // Home can consume directly from solar, but we need to calculate how much
    const directSolarToHome = Math.min(solarProduction, homeConsumption);
    const consumptionFromSolar = -directSolarToHome;
    
    // Production by target (positive values)
    // Some solar production goes to home, some to battery, some to grid
    const solarToGrid = gridExport;
    const solarToHome = directSolarToHome;
    const solarToBattery = hour.solarToBattery || 
                          // If not available, estimate from the solar production minus what went to home and grid
                          Math.max(0, solarProduction - directSolarToHome - gridExport);
    
    return {
      hour: hour.hour,
      // Production stack (all positive, above x-axis)
      solarToGrid,
      solarToHome,
      solarToBattery,
      // Consumption stack (all negative, below x-axis)
      consumptionFromGrid,
      consumptionFromSolar,
      consumptionFromBattery,
      // Absolute values for tooltip
      solarToGridAbs: solarToGrid,
      solarToHomeAbs: solarToHome,
      solarToBatteryAbs: solarToBattery,
      consumptionFromGridAbs: Math.abs(consumptionFromGrid),
      consumptionFromSolarAbs: Math.abs(consumptionFromSolar),
      consumptionFromBatteryAbs: Math.abs(consumptionFromBattery),
      // Original values for reference
      solarProduction,
      gridImport,
      gridExport,
      batteryCharge,
      batteryDischarge,
      homeConsumption
    };
  });

  // Find the max values for scaling
  const maxPositive = Math.max(
    ...chartData.map(d => 
      (d.solarToGrid || 0) + (d.solarToHome || 0) + (d.solarToBattery || 0)
    ),
    0.1 // Ensure at least some positive space even if values are zero
  );
  
  const maxNegative = Math.max(
    ...chartData.map(d => 
      Math.abs((d.consumptionFromGrid || 0)) + 
      Math.abs((d.consumptionFromSolar || 0)) + 
      Math.abs((d.consumptionFromBattery || 0))
    ),
    0.1 // Ensure at least some negative space even if values are zero
  );
  
  // Scale for better visualization - make positive and negative sides symmetric
  const maxValue = Math.max(maxPositive, maxNegative);
  const yAxisMax = Math.ceil(maxValue * 1.1);
  const yAxisMin = -Math.ceil(maxValue * 1.1);

  return (
    <div className="bg-white p-6 rounded-lg shadow">
      <h2 className="text-xl font-semibold mb-4">Energy Balance</h2>
      <div className="h-80">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart 
            data={chartData}
            margin={{ top: 10, right: 30, left: 0, bottom: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis 
              dataKey="hour"
              interval={2}
              tick={{ fontSize: 12 }}
            />
            <YAxis 
              domain={[yAxisMin, yAxisMax]}
              label={{ value: 'Energy (kWh)', angle: -90, position: 'insideLeft', dx: -10 }}
              tick={{ fontSize: 12 }}
              tickFormatter={(value) => Math.abs(value).toString()}
            />
            <Tooltip
              formatter={(value, name, props) => {
                // Display absolute values with the right unit
                const absValue = Math.abs(Number(value)).toFixed(2);
                
                switch (name) {
                  // Production targets
                  case 'solarToGrid': return [`${absValue} kWh`, 'To Grid'];
                  case 'solarToHome': return [`${absValue} kWh`, 'To Home'];
                  case 'solarToBattery': return [`${absValue} kWh`, 'To Battery'];
                  
                  // Consumption sources
                  case 'consumptionFromGrid': return [`${absValue} kWh`, 'From Grid'];
                  case 'consumptionFromSolar': return [`${absValue} kWh`, 'From Solar'];
                  case 'consumptionFromBattery': return [`${absValue} kWh`, 'From Battery'];
                  
                  default: return [value, name];
                }
              }}
              labelFormatter={(label) => `Hour: ${label}`}
            />
            <Legend />
            
            {/* Zero line reference */}
            <ReferenceLine y={0} stroke="#666" strokeWidth={2} />
            
            {/* PRODUCTION TARGETS - ABOVE X-AXIS */}
            <Bar 
              dataKey="solarToGrid" 
              name="To Grid" 
              stackId="production"
              fill="#3b82f6" // Blue
              radius={[4, 4, 0, 0]}
            />
            <Bar 
              dataKey="solarToHome" 
              name="To Home" 
              stackId="production"
              fill="#fbbf24" // Yellow
              radius={[4, 4, 0, 0]}
            />
            <Bar 
              dataKey="solarToBattery" 
              name="To Battery" 
              stackId="production"
              fill="#10b981" // Green
              radius={[4, 4, 0, 0]}
            />
            
            {/* CONSUMPTION SOURCES - BELOW X-AXIS */}
            <Bar 
              dataKey="consumptionFromGrid" 
              name="From Grid" 
              stackId="consumption"
              fill="#f97316" // Orange
              radius={[0, 0, 4, 4]} 
            />
            <Bar 
              dataKey="consumptionFromSolar" 
              name="From Solar" 
              stackId="consumption"
              fill="#a3e635" // Light Green
              radius={[0, 0, 4, 4]} 
            />
            <Bar 
              dataKey="consumptionFromBattery" 
              name="From Battery" 
              stackId="consumption"
              fill="#14b8a6" // Teal
              radius={[0, 0, 4, 4]} 
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-3 text-sm text-gray-600">
        <p><strong>Production (Above):</strong> Shows where your energy goes - to grid (blue), to home (yellow), to battery (green).</p>
        <p><strong>Consumption (Below):</strong> Shows where your energy comes from - from grid (orange), from solar (light green), from battery (teal).</p>
      </div>
    </div>
  );
};