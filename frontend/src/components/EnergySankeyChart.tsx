import React, { useEffect, useRef } from 'react';
import { Info } from 'lucide-react';

// We'll use React Plotly for the Sankey diagram
declare global {
  interface Window {
    Plotly: any;
  }
}

interface EnergySankeyChartProps {
  energyData: {
    totals: {
      totalSolarProduction: number;
      totalHomeConsumption: number;
      totalGridImport: number;
      totalGridExport: number;
      totalBatteryCharged: number;
      totalBatteryDischarged: number;
      // Detailed flow totals from API
      totalSolarToHome: number;
      totalSolarToBattery: number;
      totalSolarToGrid: number;
      totalGridToHome: number;
      totalGridToBattery: number;
      totalBatteryToHome: number;
      totalBatteryToGrid: number;
    };
  };
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

  // Get energy flows directly from API totals - deterministic, no fallbacks
  const getEnergyFlows = (data: any) => {
    if (!data?.totals) {
      console.error('Missing totals data:', data);
      return null;
    }

    // ✅ Use exact values from API totals - no calculations or fallbacks
    return {
      solarProduction: data.totals.totalSolarProduction || 0,
      homeConsumption: data.totals.totalHomeConsumption || 0,
      gridImport: data.totals.totalGridImport || 0,
      gridExport: data.totals.totalGridExport || 0,
      totalCharged: data.totals.totalBatteryCharged || 0,
      totalDischarged: data.totals.totalBatteryDischarged || 0,
      
      // Detailed flows directly from API totals
      solarToHome: data.totals.totalSolarToHome || 0,
      solarToBattery: data.totals.totalSolarToBattery || 0,
      solarToGrid: data.totals.totalSolarToGrid || 0,
      gridToHome: data.totals.totalGridToHome || 0,
      gridToBattery: data.totals.totalGridToBattery || 0,
      batteryToHome: data.totals.totalBatteryToHome || 0,
      batteryToGrid: data.totals.totalBatteryToGrid || 0
    };
  };

  // Create Plotly Sankey diagram
  useEffect(() => {
    if (!plotlyLoaded || !plotRef.current || !energyData) return;

    const flows = getEnergyFlows(energyData);
    if (!flows) return;

    // Define nodes
    const nodes = [
      { label: `Solar<br>${flows.solarProduction.toFixed(1)} kWh`, color: "#fbbf24" },
      { label: `Grid<br>±${Math.max(flows.gridImport, flows.gridExport).toFixed(1)} kWh`, color: "#3b82f6" },
      { label: `Battery<br>±${Math.max(flows.totalCharged, flows.totalDischarged).toFixed(1)} kWh`, color: "#10b981" },
      { label: `Home<br>${flows.homeConsumption.toFixed(1)} kWh`, color: "#ef4444" }
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

    // Create Sankey trace
    const trace = {
      type: "sankey",
      orientation: "h",
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
        color: links.map(() => 'rgba(128, 128, 128, 0.2)')
      }
    };

    const layout = {
      title: {
        text: "",
        font: { size: 16 }
      },
      font: { size: 12 },
      margin: { l: 0, r: 0, t: 20, b: 20 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      showlegend: false
    };

    const config = {
      displayModeBar: false,
      responsive: true
    };

    window.Plotly.newPlot(plotRef.current, [trace], layout, config);
  }, [plotlyLoaded, energyData]);

  if (!energyData) {
    return (
      <div className={`bg-purple-50 dark:bg-purple-900/10 border-purple-200 dark:border-purple-800 border-2 rounded-xl p-6 transition-all duration-200 hover:shadow-lg ${className}`}>
        <h2 className="text-xl font-semibold mb-4 text-purple-900 dark:text-purple-100">Daily Energy Flow Overview</h2>
        <div className="flex items-center justify-center h-64 text-purple-500 dark:text-purple-400">
          <Info className="h-8 w-8 mr-2" />
          <span>No data available</span>
        </div>
      </div>
    );
  }

  const flows = getEnergyFlows(energyData);

  if (!flows) {
    return (
      <div className={`bg-purple-50 dark:bg-purple-900/10 border-purple-200 dark:border-purple-800 border-2 rounded-xl p-6 transition-all duration-200 hover:shadow-lg ${className}`}>
        <h2 className="text-xl font-semibold mb-4 text-purple-900 dark:text-purple-100">Daily Energy Flow Overview</h2>
        <div className="flex items-center justify-center h-64 text-purple-500 dark:text-purple-400">
          <Info className="h-8 w-8 mr-2" />
          <span>Unable to calculate energy flows</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`bg-purple-50 dark:bg-purple-900/10 border-purple-200 dark:border-purple-800 border-2 rounded-xl p-6 transition-all duration-200 hover:shadow-lg ${className}`}>
      <h2 className="text-xl font-semibold mb-4 text-purple-900 dark:text-purple-100">Daily Energy Flow Overview</h2>
      
      {/* Sankey Diagram Only - No Cards */}
      <div ref={plotRef} className="w-full h-96" />
    </div>
  );
};