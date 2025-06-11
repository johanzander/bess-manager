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

  // Calculate energy flows from hourly data (NOT from totals)
  const calculateEnergyFlows = (data: any) => {
    if (!data?.hourlyData || !Array.isArray(data.hourlyData)) {
      console.error('Missing or invalid hourly data:', data);
      return null;
    }

    // Use totals for basic values
    const totals = data.totals || {};
    const solarProduction = totals.total_solar || 0;
    const homeConsumption = totals.total_consumption || 0;
    const gridImports = totals.total_grid_import || 0;
    const gridExports = totals.total_grid_export || 0;
    const totalCharged = totals.total_battery_charged || 0; // Note: "charged" not "charge"
    const totalDischarged = totals.total_battery_discharged || 0;

    // Calculate detailed flows from hourly data
    let solarToBattery = 0;
    let gridToBattery = 0;
    let batteryToHome = 0;
    let batteryToGrid = 0;
    let solarToHome = 0;
    let solarToGrid = 0;
    let gridToHome = 0;

    // Process each hour to calculate flows
    data.hourlyData.forEach((hour: any) => {
      const hourSolar = hour.solar_production || 0;
      const hourConsumption = hour.home_consumption || 0;
      const hourGridImport = hour.grid_import || 0;
      const hourGridExport = hour.grid_export || 0;
      const hourBatteryCharged = hour.battery_charged || 0;
      const hourBatteryDischarged = hour.battery_discharged || 0;

      // For each hour, determine energy flows based on energy balance
      // Solar can go to: Home, Battery, Grid (export)
      // Grid can go to: Home, Battery
      // Battery can go to: Home, Grid (export)

      // Calculate solar flows for this hour
      if (hourSolar > 0) {
        // Priority: 1) Home consumption, 2) Battery charging, 3) Grid export
        const directSolarToHome = Math.min(hourSolar, hourConsumption);
        const remainingSolar = hourSolar - directSolarToHome;
        
        const solarToBatteryThisHour = Math.min(remainingSolar, hourBatteryCharged);
        const solarToGridThisHour = Math.max(0, remainingSolar - solarToBatteryThisHour);
        
        solarToHome += directSolarToHome;
        solarToBattery += solarToBatteryThisHour;
        solarToGrid += solarToGridThisHour;
      }

      // Calculate grid flows for this hour
      if (hourGridImport > 0) {
        // Grid can charge battery or supply home
        const gridToBatteryThisHour = Math.max(0, hourBatteryCharged - (hourSolar - Math.min(hourSolar, hourConsumption)));
        const gridToHomeThisHour = hourGridImport - gridToBatteryThisHour;
        
        gridToBattery += Math.max(0, gridToBatteryThisHour);
        gridToHome += Math.max(0, gridToHomeThisHour);
      }

      // Calculate battery discharge flows
      if (hourBatteryDischarged > 0) {
        // Battery discharge can go to home or grid
        const unmetHomeConsumption = Math.max(0, hourConsumption - (hourSolar + hourGridImport - hourBatteryCharged));
        const batteryToHomeThisHour = Math.min(hourBatteryDischarged, unmetHomeConsumption);
        const batteryToGridThisHour = hourBatteryDischarged - batteryToHomeThisHour;
        
        batteryToHome += batteryToHomeThisHour;
        batteryToGrid += batteryToGridThisHour;
      }
    });

    // Validate and adjust flows to ensure energy balance
    // Ensure solar flows don't exceed production
    const totalSolarFlows = solarToHome + solarToBattery + solarToGrid;
    if (totalSolarFlows > solarProduction && solarProduction > 0) {
      const scale = solarProduction / totalSolarFlows;
      solarToHome *= scale;
      solarToBattery *= scale;
      solarToGrid *= scale;
    }

    // Ensure battery flows don't exceed totals
    if (solarToBattery + gridToBattery > totalCharged && totalCharged > 0) {
      const chargeScale = totalCharged / (solarToBattery + gridToBattery);
      solarToBattery *= chargeScale;
      gridToBattery *= chargeScale;
    }

    if (batteryToHome + batteryToGrid > totalDischarged && totalDischarged > 0) {
      const dischargeScale = totalDischarged / (batteryToHome + batteryToGrid);
      batteryToHome *= dischargeScale;
      batteryToGrid *= dischargeScale;
    }

    // Ensure home consumption is met
    const totalToHome = solarToHome + gridToHome + batteryToHome;
    if (Math.abs(totalToHome - homeConsumption) > 0.1 && homeConsumption > 0) {
      // Adjust grid to home to balance
      gridToHome = Math.max(0, homeConsumption - solarToHome - batteryToHome);
    }

    const flows = {
      solarProduction,
      homeConsumption,
      gridImports,
      gridExports,
      totalCharged,
      totalDischarged,
      solarToHome,
      solarToBattery,
      solarToGrid,
      gridToHome,
      gridToBattery,
      batteryToHome,
      batteryToGrid,
      netGrid: gridImports - gridExports,
      selfConsumption: solarProduction > 0 ? ((solarToHome + solarToBattery) / solarProduction * 100) : 0
    };

    console.log('Calculated Energy Flows:', flows);
    return flows;
  };

  // Create Sankey diagram
  useEffect(() => {
    if (!plotlyLoaded || !plotRef.current || !energyData) return;

    const flows = calculateEnergyFlows(energyData);
    if (!flows) return;

    // Define nodes
    const nodes = ["Grid", "Solar", "Battery", "Home"];
    const nodeColors = ["#60a5fa", "#fbbf24", "#10b981", "#f87171"];

    // Define flows with minimum threshold
    const links: any = {
      source: [],
      target: [],
      value: [],
      color: [],
      label: []
    };

    const minFlow = 0.1; // Minimum flow to display

    // Grid to Home
    if (flows.gridToHome > minFlow) {
      links.source.push(0); // Grid
      links.target.push(3); // Home
      links.value.push(flows.gridToHome);
      links.color.push("rgba(96, 165, 250, 0.6)");
      links.label.push(`${flows.gridToHome.toFixed(1)} kWh`);
    }

    // Grid to Battery
    if (flows.gridToBattery > minFlow) {
      links.source.push(0); // Grid
      links.target.push(2); // Battery
      links.value.push(flows.gridToBattery);
      links.color.push("rgba(96, 165, 250, 0.6)");
      links.label.push(`${flows.gridToBattery.toFixed(1)} kWh`);
    }

    // Solar to Home
    if (flows.solarToHome > minFlow) {
      links.source.push(1); // Solar
      links.target.push(3); // Home
      links.value.push(flows.solarToHome);
      links.color.push("rgba(251, 191, 36, 0.6)");
      links.label.push(`${flows.solarToHome.toFixed(1)} kWh`);
    }

    // Solar to Battery
    if (flows.solarToBattery > minFlow) {
      links.source.push(1); // Solar
      links.target.push(2); // Battery
      links.value.push(flows.solarToBattery);
      links.color.push("rgba(251, 191, 36, 0.6)");
      links.label.push(`${flows.solarToBattery.toFixed(1)} kWh`);
    }

    // Solar to Grid
    if (flows.solarToGrid > minFlow) {
      links.source.push(1); // Solar
      links.target.push(0); // Grid
      links.value.push(flows.solarToGrid);
      links.color.push("rgba(251, 191, 36, 0.6)");
      links.label.push(`${flows.solarToGrid.toFixed(1)} kWh`);
    }

    // Battery to Home
    if (flows.batteryToHome > minFlow) {
      links.source.push(2); // Battery
      links.target.push(3); // Home
      links.value.push(flows.batteryToHome);
      links.color.push("rgba(16, 185, 129, 0.6)");
      links.label.push(`${flows.batteryToHome.toFixed(1)} kWh`);
    }

    // Battery to Grid
    if (flows.batteryToGrid > minFlow) {
      links.source.push(2); // Battery
      links.target.push(0); // Grid
      links.value.push(flows.batteryToGrid);
      links.color.push("rgba(16, 185, 129, 0.6)");
      links.label.push(`${flows.batteryToGrid.toFixed(1)} kWh`);
    }

    // Create the Sankey diagram
    const data = [{
      type: "sankey",
      orientation: "h",
      arrangement: "snap",
      node: {
        pad: 15,
        thickness: 30,
        line: { color: "black", width: 0.5 },
        label: nodes.map((node) => {
          // Add totals to node labels
          switch(node) {
            case "Grid": return `Grid\n(Net: ${flows.netGrid.toFixed(1)} kWh)`;
            case "Solar": return `Solar\n(${flows.solarProduction.toFixed(1)} kWh)`;
            case "Battery": return `Battery\n(${flows.totalCharged.toFixed(1)}/${flows.totalDischarged.toFixed(1)} kWh)`;
            case "Home": return `Home\n(${flows.homeConsumption.toFixed(1)} kWh)`;
            default: return node;
          }
        }),
        color: nodeColors
      },
      link: {
        source: links.source,
        target: links.target,
        value: links.value,
        color: links.color,
        label: links.label
      }
    }];

    const layout = {
      title: {
        text: "Daily Energy Flow (kWh)",
        font: { size: 16 }
      },
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
      <div className={`bg-white p-6 rounded-lg shadow ${className}`}>
        <h2 className="text-xl font-semibold mb-4">Energy Flow Overview</h2>
        <div className="flex items-center justify-center h-64 text-gray-500">
          <Info className="h-8 w-8 mr-2" />
          <span>No energy data available</span>
        </div>
      </div>
    );
  }

  const flows = calculateEnergyFlows(energyData);

  if (!flows) {
    return (
      <div className={`bg-white p-6 rounded-lg shadow ${className}`}>
        <h2 className="text-xl font-semibold mb-4">Energy Flow Overview</h2>
        <div className="flex items-center justify-center h-64 text-gray-500">
          <Info className="h-8 w-8 mr-2" />
          <span>Unable to calculate energy flows</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`bg-white p-6 rounded-lg shadow ${className}`}>
      <h2 className="text-xl font-semibold mb-4">Energy Flow Overview</h2>
      
      {/* Sankey Diagram */}
      <div ref={plotRef} className="w-full h-96 mb-6" />

      {/* Detailed Breakdown */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Home Energy Sources */}
        <div className="bg-white p-3 rounded border">
          <h5 className="font-medium text-gray-700 mb-2 flex items-center">
            <Home className="h-4 w-4 mr-1 text-red-500" />
            Home Energy Sources ({flows.homeConsumption.toFixed(1)} kWh total)
          </h5>
          <div className="space-y-1 text-sm">
            <div className="flex justify-between items-center">
              <span className="flex items-center">
                <div className="w-3 h-3 bg-yellow-400 rounded mr-2"></div>
                Direct Solar:
              </span>
              <span className="font-medium">{flows.solarToHome.toFixed(1)} kWh ({(flows.solarToHome / flows.homeConsumption * 100).toFixed(0)}%)</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="flex items-center">
                <div className="w-3 h-3 bg-green-500 rounded mr-2"></div>
                From Battery:
              </span>
              <span className="font-medium">{flows.batteryToHome.toFixed(1)} kWh ({(flows.batteryToHome / flows.homeConsumption * 100).toFixed(0)}%)</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="flex items-center">
                <div className="w-3 h-3 bg-blue-500 rounded mr-2"></div>
                From Grid:
              </span>
              <span className="font-medium">{flows.gridToHome.toFixed(1)} kWh ({(flows.gridToHome / flows.homeConsumption * 100).toFixed(0)}%)</span>
            </div>
          </div>
        </div>

        {/* Solar Distribution */}
        <div className="bg-white p-3 rounded border">
          <h5 className="font-medium text-gray-700 mb-2 flex items-center">
            <Sun className="h-4 w-4 mr-1 text-yellow-500" />
            Solar Distribution ({flows.solarProduction.toFixed(1)} kWh total)
          </h5>
          <div className="space-y-1 text-sm">
            <div className="flex justify-between items-center">
              <span className="flex items-center">
                <div className="w-3 h-3 bg-red-400 rounded mr-2"></div>
                To Home:
              </span>
              <span className="font-medium">{flows.solarToHome.toFixed(1)} kWh ({flows.solarProduction > 0 ? (flows.solarToHome / flows.solarProduction * 100).toFixed(0) : 0}%)</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="flex items-center">
                <div className="w-3 h-3 bg-green-500 rounded mr-2"></div>
                To Battery:
              </span>
              <span className="font-medium">{flows.solarToBattery.toFixed(1)} kWh ({flows.solarProduction > 0 ? (flows.solarToBattery / flows.solarProduction * 100).toFixed(0) : 0}%)</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="flex items-center">
                <div className="w-3 h-3 bg-blue-500 rounded mr-2"></div>
                To Grid:
              </span>
              <span className="font-medium">{flows.solarToGrid.toFixed(1)} kWh ({flows.solarProduction > 0 ? (flows.solarToGrid / flows.solarProduction * 100).toFixed(0) : 0}%)</span>
            </div>
          </div>
        </div>

        {/* Battery Operations */}
        <div className="bg-white p-3 rounded border">
          <h5 className="font-medium text-gray-700 mb-2 flex items-center">
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
              <span className="font-medium">{flows.solarToBattery.toFixed(1)} kWh ({flows.totalCharged > 0 ? (flows.solarToBattery / flows.totalCharged * 100).toFixed(0) : 0}%)</span>
            </div>
            <div className="flex justify-between items-center pl-3">
              <span className="flex items-center">
                <div className="w-3 h-3 bg-blue-500 rounded mr-2"></div>
                From Grid:
              </span>
              <span className="font-medium">{flows.gridToBattery.toFixed(1)} kWh ({flows.totalCharged > 0 ? (flows.gridToBattery / flows.totalCharged * 100).toFixed(0) : 0}%)</span>
            </div>
            
            {/* Discharging Section */}
            <div className="mt-2 mb-1 font-medium text-red-600">Discharging ({flows.totalDischarged.toFixed(1)} kWh):</div>
            <div className="flex justify-between items-center pl-3">
              <span className="flex items-center">
                <div className="w-3 h-3 bg-red-400 rounded mr-2"></div>
                To Home:
              </span>
              <span className="font-medium">{flows.batteryToHome.toFixed(1)} kWh ({flows.totalDischarged > 0 ? (flows.batteryToHome / flows.totalDischarged * 100).toFixed(0) : 0}%)</span>
            </div>
            <div className="flex justify-between items-center pl-3">
              <span className="flex items-center">
                <div className="w-3 h-3 bg-blue-400 rounded mr-2"></div>
                To Grid:
              </span>
              <span className="font-medium">{flows.batteryToGrid.toFixed(1)} kWh ({flows.totalDischarged > 0 ? (flows.batteryToGrid / flows.totalDischarged * 100).toFixed(0) : 0}%)</span>
            </div>
            
            {/* Efficiency row */}
            <div className="flex justify-between items-center border-t mt-2 pt-1">
              <span>Round-trip Efficiency:</span>
              <span className="font-medium">{flows.totalCharged > 0 ? (flows.totalDischarged / flows.totalCharged * 100).toFixed(0) : 0}%</span>
            </div>
          </div>
        </div>
      </div>

      <div className="mt-3 text-sm text-gray-600">
        <p>
          <strong>Interactive diagram:</strong> Node labels show totals, flow thickness represents energy amounts. 
          The detailed breakdown above shows exactly where every kWh came from and went to.
        </p>
      </div>
    </div>
  );
};