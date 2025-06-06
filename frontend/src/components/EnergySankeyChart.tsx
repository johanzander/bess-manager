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

  // Calculate energy flows (ported from your Python code)
  const calculateEnergyFlows = (data: any) => {
    if (!data?.totals) {
      return null;
    }

    const totals = data.totals;
    
    // Calculate total energy values (exactly like your Python code)
    const gridImports = totals.total_grid_import || 0;
    const gridExports = totals.total_grid_export || 0;
    const solarProduction = totals.total_solar || 0;
    const homeConsumption = totals.total_consumption || 0;
    const totalCharged = totals.total_battery_charge || 0;
    const totalDischarged = totals.total_battery_discharged || 0;

    // Use exact values from backend when available, otherwise calculate
    const solarToBattery = totals.solar_to_battery !== undefined ? totals.solar_to_battery : 0;
    const gridToBattery = totals.grid_to_battery !== undefined ? totals.grid_to_battery : 0;
    
    // For debugging purposes
    console.log('Energy Flow Data:', {
      totals,
      solarProduction, 
      homeConsumption,
      totalCharged,
      solarToBattery,
      gridToBattery
    });
    
    // Calculate other flows based on the known values
    const solarToHome = Math.max(0, solarProduction - solarToBattery - (totals.export_to_grid || 0));
    const solarToGrid = Math.max(0, solarProduction - solarToHome - solarToBattery);
    
    const gridToHome = Math.max(0, gridImports - gridToBattery);

    const batteryToHome = Math.min(totalDischarged, Math.max(0, homeConsumption - solarToHome));
    const batteryToGrid = Math.max(0, totalDischarged - batteryToHome);

    return {
      gridImports,
      gridExports,
      solarProduction,
      homeConsumption,
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
      batteryCycles: totalCharged / 30, // Assuming 30kWh capacity
      selfConsumption: solarProduction > 0 ? ((solarToHome + solarToBattery) / solarProduction * 100) : 0
    };
  };

  // Create Sankey diagram
  useEffect(() => {
    if (!plotlyLoaded || !plotRef.current || !energyData) return;

    const flows = calculateEnergyFlows(energyData);
    if (!flows) return;

    // Define nodes (exactly like your Python code)
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

  const flows = calculateEnergyFlows(energyData);

  if (!flows) {
    return (
      <div className={`bg-white p-6 rounded-lg shadow ${className}`}>
        <h2 className="text-xl font-semibold mb-4 flex items-center">
          <Zap className="h-5 w-5 mr-2 text-blue-600" />
          Energy Flow Diagram
        </h2>
        <div className="flex items-center justify-center h-64 text-gray-500">
          <Info className="h-5 w-5 mr-2" />
          No energy data available for flow diagram
        </div>
      </div>
    );
  }

  return (
    <div className={`bg-white p-6 rounded-lg shadow ${className}`}>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold flex items-center">
          <Zap className="h-5 w-5 mr-2 text-blue-600" />
          Energy Flow Diagram
        </h2>
        <div className="text-sm text-gray-600">
          Total flows for today
        </div>
      </div>

      {/* Sankey Plot Container */}
      <div className="relative">
        <div ref={plotRef} className="w-full" style={{ minHeight: '450px' }} />
        
        {!plotlyLoaded && (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-50 rounded">
            <div className="text-center">
              <div className="animate-spin h-8 w-8 border-4 border-blue-500 rounded-full border-t-transparent mx-auto mb-2"></div>
              <p className="text-gray-600">Loading interactive diagram...</p>
            </div>
          </div>
        )}
      </div>

      {/* Detailed Flow Table */}
      <div className="mt-6 bg-gray-50 p-4 rounded-lg">
        <h4 className="font-medium text-gray-800 mb-3">Energy Flow Details</h4>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          
          {/* Energy Sources to Home */}
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

          {/* Grid Balance */}
          <div className="bg-white p-3 rounded border">
            <h5 className="font-medium text-gray-700 mb-2 flex items-center">
              <Grid className="h-4 w-4 mr-1 text-blue-500" />
              Grid Balance (Net: {flows.netGrid.toFixed(1)} kWh)
            </h5>
            <div className="space-y-1 text-sm">
              <div className="flex justify-between items-center">
                <span>Total Import:</span>
                <span className="font-medium text-red-600">{flows.gridImports.toFixed(1)} kWh</span>
              </div>
              <div className="flex justify-between items-center">
                <span>Total Export:</span>
                <span className="font-medium text-green-600">{flows.gridExports.toFixed(1)} kWh</span>
              </div>
              <div className="flex justify-between items-center border-t pt-1">
                <span>Net Consumption:</span>
                <span className={`font-medium ${flows.netGrid > 0 ? 'text-red-600' : 'text-green-600'}`}>
                  {flows.netGrid.toFixed(1)} kWh
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span>Self-Sufficiency:</span>
                <span className="font-medium">{flows.homeConsumption > 0 ? (100 - (flows.gridToHome / flows.homeConsumption * 100)).toFixed(0) : 0}%</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Summary Statistics */}
      <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-blue-50 p-3 rounded-lg text-center">
          <div className="text-2xl font-bold text-blue-600">{Math.abs(flows.netGrid).toFixed(1)}</div>
          <div className="text-sm text-gray-600">Net Grid kWh</div>
          <div className="text-xs text-gray-500">
            {flows.netGrid > 0 ? `${flows.netGrid.toFixed(1)} consumed` : `${Math.abs(flows.netGrid).toFixed(1)} exported`}
          </div>
        </div>

        <div className="bg-yellow-50 p-3 rounded-lg text-center">
          <div className="text-2xl font-bold text-yellow-600">{flows.selfConsumption.toFixed(0)}%</div>
          <div className="text-sm text-gray-600">Solar Self-Use</div>
          <div className="text-xs text-gray-500">
            {(flows.solarToHome + flows.solarToBattery).toFixed(1)} of {flows.solarProduction.toFixed(1)} kWh
          </div>
        </div>

        <div className="bg-green-50 p-3 rounded-lg text-center">
          <div className="text-2xl font-bold text-green-600">{flows.totalCharged.toFixed(1)}</div>
          <div className="text-sm text-gray-600">Battery Activity</div>
          <div className="text-xs text-gray-500">
            {flows.totalDischarged.toFixed(1)} kWh discharged
          </div>
        </div>

        <div className="bg-red-50 p-3 rounded-lg text-center">
          <div className="text-2xl font-bold text-red-600">
            {flows.homeConsumption > 0 ? (100 - (flows.gridToHome / flows.homeConsumption * 100)).toFixed(0) : 0}%
          </div>
          <div className="text-sm text-gray-600">Energy Independence</div>
          <div className="text-xs text-gray-500">
            {(flows.solarToHome + flows.batteryToHome).toFixed(1)} of {flows.homeConsumption.toFixed(1)} kWh
          </div>
        </div>
      </div>

      <div className="mt-3 text-sm text-gray-600">
        <p>
          <strong>Interactive diagram:</strong> Node labels show totals, flow thickness represents energy amounts. 
          The detailed breakdown above shows exactly where every kWh came from and went to.
          Self-sufficiency shows how much of your consumption came from renewable sources.
        </p>
      </div>
    </div>
  );
};