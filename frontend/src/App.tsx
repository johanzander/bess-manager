import React, { useState, useMemo } from 'react';
import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';
import OptimizationDashboard from './pages/OptimizationDashboard';
import SystemHealthPage from './pages/SystemHealthPage';
import DateSelector from './components/DateSelector';
import { CombinedSettings } from './components/Settings';
import { useSettings } from './hooks/useSettings';
import { BatterySettings } from './types';
import { Home, Activity } from 'lucide-react';

// Default settings to use when real settings are not available
const DEFAULT_BATTERY_SETTINGS: BatterySettings = {
  totalCapacity: 30.0,
  reservedCapacity: 3.0, // 10% of 30.0
  estimatedConsumption: 3.5,
  maxChargeDischarge: 6,
  chargeCycleCost: 0.50,
  chargingPowerRate: 40,
  useActualPrice: false
};

const DEFAULT_ELECTRICITY_SETTINGS: ElectricitySettings = {
  markupRate: 0.08,
  vatMultiplier: 1.25,
  additionalCosts: 1.03,
  taxReduction: 0.6518,
  area: 'SE4'
};

// An ErrorBoundary component to catch rendering errors
class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean; error: Error | null }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error("Error caught by boundary:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-red-50">
          <div className="max-w-md p-6 bg-white rounded-lg shadow-lg">
            <h2 className="text-xl font-bold text-red-600 mb-4">Something went wrong</h2>
            <p className="mb-4">{this.state.error?.message || "An unknown error occurred"}</p>
            <button
              className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
              onClick={() => window.location.reload()}
            >
              Reload page
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

function App() {
  console.log('App component rendering');
  
  const [selectedDate, setSelectedDate] = useState(new Date());
  const [isLoading, setIsLoading] = useState(false);
  
  try {
    const { 
      batterySettings, 
      electricitySettings, 
      updateBatterySettings,
      updateElectricitySettings,
      isLoading: settingsLoading,
      error: settingsError 
    } = useSettings();

    console.log('App state:', {
      settingsLoading,
      settingsError,
      hasBatterySettings: !!batterySettings,
      hasElectricitySettings: !!electricitySettings
    });

    const handleDateChange = (date: Date) => {
      setSelectedDate(date);
    };

    // Safely create settings with fallbacks
    const settings = useMemo(() => {
      const defaultSettings = {
        totalCapacity: 10,
        reservedCapacity: 2,
        estimatedConsumption: 1.5,
        maxChargeDischarge: 6,
        chargeCycleCost: 10,
        chargingPowerRate: 90,
        useActualPrice: true,
        markupRate: 0.05,
        vatMultiplier: 1.25,
        additionalCosts: 0.45,
        taxReduction: 0.1,
        area: 'SE3' as const
      };
    
      // If we don't have any settings at all, return defaults
      if (!batterySettings && !electricitySettings) {
        return defaultSettings;
      }
    
      // Merge available settings with defaults for any missing properties
      return {
        ...defaultSettings,
        ...(batterySettings || {}),
        ...(electricitySettings || {})
      };
    }, [batterySettings, electricitySettings]);

    if (settingsLoading) {
      console.log('Rendering loading state');
      return (
        <div className="flex items-center justify-center min-h-screen">
          <div className="p-6 max-w-sm bg-white rounded-lg shadow-lg">
            <div className="flex items-center space-x-4">
              <div className="animate-spin h-6 w-6 border-2 border-blue-500 rounded-full border-t-transparent"></div>
              <div>Loading settings...</div>
            </div>
          </div>
        </div>
      );
    }

    // Main app render
    return (
      <Router>
        <div className="min-h-screen bg-gray-50">
          <header className="bg-white shadow fixed top-0 left-0 w-full z-10">
            <div className="max-w-7xl mx-auto py-2 px-4 sm:px-6 lg:px-14">
              <div className="flex justify-between items-center">
                <div className="flex items-center space-x-4">
                  <ErrorBoundary>
                    <CombinedSettings
                      batterySettings={batterySettings || DEFAULT_BATTERY_SETTINGS}
                      electricitySettings={electricitySettings || DEFAULT_ELECTRICITY_SETTINGS}
                      onBatteryUpdate={updateBatterySettings}
                      onElectricityUpdate={updateElectricitySettings}
                    />
                  </ErrorBoundary>
                  <h1 className="text-2xl font-bold text-gray-900">Smart Charger</h1>
                  <span className="italic text-gray-600 hidden sm:inline">
                    Turn electricity price differences into savings with your home battery
                  </span>
                </div>
                <div className="flex items-center space-x-4">
                  {/* Only show date selector on the main dashboard */}
                  <Routes>
                    <Route path="/" element={
                      <ErrorBoundary>
                        <DateSelector
                          selectedDate={selectedDate}
                          onDateChange={handleDateChange}
                          isLoading={isLoading}
                        />
                      </ErrorBoundary>
                    } />
                  </Routes>
                  
                  {/* Navigation Menu */}
                  <div className="flex space-x-2 ml-4">
                    <Link 
                      to="/" 
                      className="p-2 hover:bg-gray-100 rounded flex items-center space-x-1 text-gray-700 hover:text-gray-900"
                    >
                      <Home className="h-5 w-5" />
                      <span className="hidden sm:inline">Dashboard</span>
                    </Link>
                    <Link 
                      to="/system-health" 
                      className="p-2 hover:bg-gray-100 rounded flex items-center space-x-1 text-gray-700 hover:text-gray-900"
                    >
                      <Activity className="h-5 w-5" />
                      <span className="hidden sm:inline">System Health</span>
                    </Link>
                  </div>
                </div>
              </div>
            </div>
          </header>
          
          <main className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8 mt-24">
            {settingsError && (
              <div className="bg-red-50 p-6 rounded-lg shadow mb-6">
                <h2 className="text-lg font-semibold text-red-700">Error loading settings</h2>
                <p className="mt-2">{settingsError}</p>
                <button 
                  className="mt-4 px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
                  onClick={() => window.location.reload()}
                >
                  Retry
                </button>
              </div>
            )}
            
            <ErrorBoundary>
              <Routes>
                <Route path="/" element={
                  <OptimizationDashboard 
                    selectedDate={selectedDate} 
                    onLoadingChange={setIsLoading}
                    settings={settings}
                  />
                } />
                <Route path="/system-health" element={<SystemHealthPage />} />
              </Routes>
            </ErrorBoundary>
          </main>
        </div>
      </Router>
    );
  } catch (err) {
    console.error("Unhandled error in App:", err);
    return (
      <div className="min-h-screen flex items-center justify-center bg-red-50">
        <div className="max-w-md p-6 bg-white rounded-lg shadow-lg">
          <h2 className="text-xl font-bold text-red-600 mb-4">Something went wrong</h2>
          <p className="mb-4">{err instanceof Error ? err.message : "An unknown error occurred"}</p>
          <button
            className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
            onClick={() => window.location.reload()}
          >
            Reload page
          </button>
        </div>
      </div>
    );
  }
}

// Wrap the App component with an ErrorBoundary
function AppWithErrorBoundary() {
  return (
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  );
}

export default AppWithErrorBoundary;