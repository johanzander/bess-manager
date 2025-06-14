import React, { useEffect, useRef } from 'react';
import { Info, Zap, Home, Sun, Battery, Grid } from 'lucide-react';

// We'll use React Plotly for the Sankey diagram
declare global {
  interface Window {
    Plotly: any;
  }
}

interface EnergySankeyChartProps {
  energyData: any;
  className?: string;
}

export const EnergySankeyChart: React.FC<EnergySankeyChartProps> = ({ 
  energyData, 
  className = "" 
}) => {
  const plotRef = useRef<HTMLDivElement>(null);
  const [plotlyLoaded, setPlotlyLoaded] = React.useState(false);

  // Load Plotly dynamically
  useEffect(() => {
    if (typeof window !== 'undefined' && !window.Plotly) {
      const script = document.createElement('script');
      script.src = 'https://cdn.plot.ly/plotly-latest.min.js';
      script.onload = () => setPlotlyLoaded(true);
      document.head.appendChild(script);
    } else if (window.Plotly) {
      setPlotlyLoaded(true);
    }
  }, []);

  // Calculate energy flows from schedule data - UPDATED to match schedule structure
  const calculateEnergyFlows = (data: any) => {
    if (!data?.hourlyData || !Array.isArray(data.hourlyData)) {
      console.error('Missing or invalid hourly data:', data);
      return null;
    }

    const flows = data.hourlyData.reduce((acc: any, hour: any) => {
      // Use the schedule data field names (camelCase after conversion)
      acc.solarProduction += hour.solarProduction || hour.solar_production || 0;
      acc.homeConsumption += hour.homeConsumption || hour.home_consumption || 0;
      acc.gridImport += hour.gridImport || hour.grid_import || 0;
      acc.gridExport += hour.gridExport || hour.grid_export || 0;
      acc.totalCharged += Math.max(0, hour.batteryCharged || hour.battery_charged || 0);
      acc.totalDischarged += Math.max(0, hour.batteryDischarged || hour.battery_discharged || 0);
      
      // Calculate detailed flows from the schedule data
      const solarToHome = Math.min(hour.solarProduction || hour.solar_production || 0, hour.homeConsumption || hour.home_consumption || 0);
      const batteryToHome = Math.min(hour.batteryDischarged || hour.battery_discharged || 0, Math.max(0, (hour.homeConsumption || hour.home_consumption || 0) - solarToHome));
      const gridToHome = Math.max(0, (hour.homeConsumption || hour.home_consumption || 0) - solarToHome - batteryToHome);
      
      const solarToBattery = Math.max(0, Math.min(hour.batteryCharged || hour.battery_charged || 0, Math.max(0, (hour.solarProduction || hour.solar_production || 0) - solarToHome)));
      const gridToBattery = Math.max(0, (hour.batteryCharged || hour.battery_charged || 0) - solarToBattery);
      
      const solarToGrid = Math.max(0, (hour.solarProduction || hour.solar_production || 0) - solarToHome - solarToBattery);
      const batteryToGrid = Math.max(0, (hour.gridExport || hour.grid_export || 0) - solarToGrid);
      
      acc.solarToHome += solarToHome;
      acc.solarToBattery += solarToBattery;
      acc.solarToGrid += solarToGrid;
      acc.gridToHome += gridToHome;
      acc.gridToBattery += gridToBattery;
      acc.batteryToHome += batteryToHome;
      acc.batteryToGrid += batteryToGrid;
      
      return acc;
    }, {
      solarProduction: 0,
      homeConsumption: 0,
      totalCharged: 0,
      totalDischarged: 0,
      gridImport: 0,
      gridExport: 0,
      solarToHome: 0,
      solarToBattery: 0,
      solarToGrid: 0,
      gridToHome: 0,
      gridToBattery: 0,
      batteryToHome: 0,
      batteryToGrid: 0
    });

    return flows;
  };

  // Create Plotly Sankey diagram
  useEffect(() => {
    if (!plotlyLoaded || !plotRef.current || !energyData) return;

    const flows = calculateEnergyFlows(energyData);
    if (!flows) return;

    // Define nodes
    const nodes = [
      { label: `Solar<br>${flows.solarProduction.toFixed(1)} kWh`, color: "#fbbf24" },      // 0
      { label: `Grid<br>±${Math.max(flows.gridImport, flows.gridExport).toFixed(1)} kWh`, color: "#3b82f6" },        // 1
      { label: `Battery<br>±${Math.max(flows.totalCharged, flows.totalDischarged).toFixed(1)} kWh`, color: "#10b981" },    // 2
      { label: `Home<br>${flows.homeConsumption.toFixed(1)} kWh`, color: "#ef4444" }        // 3
    ];

    // Define links (source -> target)
    const links = [];
    
    // Only add links if flow > 0.01 kWh to avoid visual clutter
    if (flows.solarToHome > 0.01) links.push({ source: 0, target: 3, value: flows.solarToHome, label: "Solar→Home" });
    if (flows.solarToBattery > 0.01) links.push({ source: 0, target: 2, value: flows.solarToBattery, label: "Solar→Battery" });
    if (flows.solarToGrid > 0.01) links.push({ source: 0, target: 1, value: flows.solarToGrid, label: "Solar→Grid" });
    if (flows.gridToHome > 0.01) links.push({ source: 1, target: 3, value: flows.gridToHome, label: "Grid→Home" });
    if (flows.gridToBattery > 0.01) links.push({ source: 1, target: 2, value: flows.gridToBattery, label: "Grid→Battery" });
    if (flows.batteryToHome > 0.01) links.push({ source: 2, target: 3, value: flows.batteryToHome, label: "Battery→Home" });
    if (flows.batteryToGrid > 0.01) links.push({ source: 2, target: 1, value: flows.batteryToGrid, label: "Battery→Grid" });

    const data = [{
      type: "sankey",
      node: {
        pad: 15,
        thickness: 20,
        line: { color: "black", width: 0.5 },
        label: nodes.map(n => n.label),
        color: nodes.map(n => n.color)
      },
      link: {
        source: links.map(l => l.source),
        target: links.map(l => l.target),
        value: links.map(l => l.value),
        label: links.map(l => l.label)
      }
    }];

    const layout = {
      title: { text: "", font: { size: 11 } },
      font: { size: 11 },
      width: 800,
      height: 450,
      margin: { l: 0, r: 0, t: 40, b: 0 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)"
    };

    const config = {
      displayModeBar: false,
      responsive: true
    };

    window.Plotly.newPlot(plotRef.current, data, layout, config);

  }, [plotlyLoaded, energyData]);

  // Show loading or error states
  if (!energyData) {
    return (
      <div className="bg-purple-50 dark:bg-purple-900/10 border-purple-200 dark:border-purple-800 border-2 rounded-xl p-6 transition-all duration-200 hover:shadow-lg">
        <h2 className="text-xl font-semibold mb-4 text-purple-900 dark:text-purple-100">Daily Energy Flow Overview</h2>
        <div className="flex items-center justify-center h-64 text-purple-500 dark:text-purple-400">
          <Info className="h-8 w-8 mr-2" />
          <span>No energy data available</span>
        </div>
      </div>
    );
  }

  const flows = calculateEnergyFlows(energyData);

  if (!flows) {
    return (
      <div className="bg-purple-50 dark:bg-purple-900/10 border-purple-200 dark:border-purple-800 border-2 rounded-xl p-6 transition-all duration-200 hover:shadow-lg">
        <h2 className="text-xl font-semibold mb-4 text-purple-900 dark:text-purple-100">Daily Energy Flow Overview</h2>
        <div className="flex items-center justify-center h-64 text-purple-500 dark:text-purple-400">
          <Info className="h-8 w-8 mr-2" />
          <span>Unable to calculate energy flows</span>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-purple-50 dark:bg-purple-900/10 border-purple-200 dark:border-purple-800 border-2 rounded-xl p-6 transition-all duration-200 hover:shadow-lg">
      <h2 className="text-xl font-semibold mb-4 text-purple-900 dark:text-purple-100">Daily Energy Flow Overview</h2>
      
      {/* Sankey Diagram */}
      <div ref={plotRef} className="w-full h-96 mb-6" />

      {/* Detailed Breakdown */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">

        {/* Battery Operations */}
        <div className="bg-white dark:bg-gray-700 p-3 rounded border border-purple-200 dark:border-purple-700">
          <h5 className="font-medium text-purple-700 dark:text-purple-300 mb-2 flex items-center">
            <Battery className="h-4 w-4 mr-1 text-green-500" />
            Battery Operations
          </h5>
          <div className="text-sm space-y-1">
            {/* Charging Section */}
            <div className="mb-1 font-medium text-green-600">Charging ({flows.totalCharged.toFixed(1)} kWh):</div>
            <div className="flex justify-between items-center pl-3">
              <span className="flex items-center">
                <div className="w-3 h-3 bg-yellow-400 rounded mr-2"></div>
                From Solar:
              </span>
              <span className="font-medium text-purple-900 dark:text-purple-100">{flows.solarToBattery.toFixed(1)} kWh ({flows.totalCharged > 0 ? (flows.solarToBattery / flows.totalCharged * 100).toFixed(0) : 0}%)</span>
            </div>
            <div className="flex justify-between items-center pl-3">
              <span className="flex items-center">
                <div className="w-3 h-3 bg-blue-500 rounded mr-2"></div>
                From Grid:
              </span>
              <span className="font-medium text-purple-900 dark:text-purple-100">{flows.gridToBattery.toFixed(1)} kWh ({flows.totalCharged > 0 ? (flows.gridToBattery / flows.totalCharged * 100).toFixed(0) : 0}%)</span>
            </div>
            
            {/* Discharging Section */}
            <div className="mt-2 mb-1 font-medium text-red-600">Discharging ({flows.totalDischarged.toFixed(1)} kWh):</div>
            <div className="flex justify-between items-center pl-3">
              <span className="flex items-center">
                <div className="w-3 h-3 bg-red-400 rounded mr-2"></div>
                To Home:
              </span>
              <span className="font-medium text-purple-900 dark:text-purple-100">{flows.batteryToHome.toFixed(1)} kWh ({flows.totalDischarged > 0 ? (flows.batteryToHome / flows.totalDischarged * 100).toFixed(0) : 0}%)</span>
            </div>
            <div className="flex justify-between items-center pl-3">
              <span className="flex items-center">
                <div className="w-3 h-3 bg-blue-400 rounded mr-2"></div>
                To Grid:
              </span>
              <span className="font-medium text-purple-900 dark:text-purple-100">{flows.batteryToGrid.toFixed(1)} kWh ({flows.totalDischarged > 0 ? (flows.batteryToGrid / flows.totalDischarged * 100).toFixed(0) : 0}%)</span>
            </div>            
          </div>
        </div>

        {/* Home Consumption */}
        <div className="bg-white dark:bg-gray-700 p-3 rounded border border-purple-200 dark:border-purple-700">
          <h5 className="font-medium text-purple-700 dark:text-purple-300 mb-2 flex items-center">
            <Home className="h-4 w-4 mr-1 text-red-500" />
            Home Consumption
          </h5>
          <div className="text-sm space-y-1">
            <div className="flex justify-between items-center">
              <span className="flex items-center">
                <div className="w-3 h-3 bg-yellow-400 rounded mr-2"></div>
                From Solar:
              </span>
              <span className="font-medium text-purple-900 dark:text-purple-100">{flows.solarToHome.toFixed(1)} kWh ({flows.homeConsumption > 0 ? (flows.solarToHome / flows.homeConsumption * 100).toFixed(0) : 0}%)</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="flex items-center">
                <div className="w-3 h-3 bg-green-500 rounded mr-2"></div>
                From Battery:
              </span>
              <span className="font-medium text-purple-900 dark:text-purple-100">{flows.batteryToHome.toFixed(1)} kWh ({flows.homeConsumption > 0 ? (flows.batteryToHome / flows.homeConsumption * 100).toFixed(0) : 0}%)</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="flex items-center">
                <div className="w-3 h-3 bg-blue-500 rounded mr-2"></div>
                From Grid:
              </span>
              <span className="font-medium text-purple-900 dark:text-purple-100">{flows.gridToHome.toFixed(1)} kWh ({flows.homeConsumption > 0 ? (flows.gridToHome / flows.homeConsumption * 100).toFixed(0) : 0}%)</span>
            </div>
            <div className="flex justify-between items-center border-t border-purple-200 dark:border-purple-600 mt-2 pt-1">
              <span className="text-purple-700 dark:text-purple-300">Solar Coverage:</span>
              <span className="font-medium text-purple-900 dark:text-purple-100">{flows.homeConsumption > 0 ? ((flows.solarToHome + flows.batteryToHome) / flows.homeConsumption * 100).toFixed(0) : 0}%</span>
            </div>
          </div>
        </div>
      </div>

      <div className="mt-3 text-sm text-purple-600 dark:text-purple-400 opacity-70">
        <p>
          <strong>Interactive diagram:</strong> Node labels show totals, flow thickness represents energy amounts. 
          The detailed breakdown shows exactly where every kWh came from and went to based on your actual energy data.
        </p>
      </div>
    </div>
  );
};