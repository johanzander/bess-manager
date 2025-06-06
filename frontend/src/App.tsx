import React, { useMemo } from 'react';
import { BrowserRouter as Router, Routes, Route, Link, useLocation } from 'react-router-dom';
import DashboardPage from './pages/DashboardPage';
import SavingsAnalysisPage from './pages/SavingsPage';
import InverterPage from './pages/InverterPage';
import InsightsPage from './pages/InsightsPage';
import SystemHealthPage from './pages/SystemHealthPage';
import { useSettings } from './hooks/useSettings';
import { Home, Activity, TrendingUp, Brain, Zap } from 'lucide-react';

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

// Navigation component with new 4-tab structure
const Navigation = () => {
  const location = useLocation();
  
  const isActive = (path: string) => {
    return location.pathname === path ? 'bg-gray-100 text-gray-900' : 'text-gray-700 hover:text-gray-900';
  };
  
  return (
    <div className="flex space-x-2">
      <Link 
        to="/" 
        className={`p-2 hover:bg-gray-100 rounded flex items-center space-x-1 ${isActive('/')}`}
        title="Quick overview & live monitoring"
      >
        <Home className="h-5 w-5" />
        <span className="hidden sm:inline">Dashboard</span>
      </Link>
      <Link 
        to="/savings" 
        className={`p-2 hover:bg-gray-100 rounded flex items-center space-x-1 ${isActive('/savings')}`}
        title="Financial analysis & detailed reports"
      >
        <TrendingUp className="h-5 w-5" />
        <span className="hidden sm:inline">Savings</span>
      </Link>
      <Link 
        to="/inverter" 
        className={`p-2 hover:bg-gray-100 rounded flex items-center space-x-1 ${isActive('/inverter')}`}
        title="Inverter status & battery schedule management"
      >
        <Zap className="h-5 w-5" />
        <span className="hidden sm:inline">Inverter</span>
      </Link>
      <Link 
        to="/insights" 
        className={`p-2 hover:bg-gray-100 rounded flex items-center space-x-1 ${isActive('/insights')}`}
        title="Decision analysis & intelligence"
      >
        <Brain className="h-5 w-5" />
        <span className="hidden sm:inline">Insights</span>
      </Link>
      <Link 
        to="/system-health" 
        className={`p-2 hover:bg-gray-100 rounded flex items-center space-x-1 ${isActive('/system-health')}`}
        title="System status & component health"
      >
        <Activity className="h-5 w-5" />
        <span className="hidden sm:inline">System Health</span>
      </Link>
    </div>
  );
};

function App() {
  console.log('App component rendering');
  
  try {
    const { 
      batterySettings, 
      electricitySettings, 
      isLoading: settingsLoading,
      error: settingsError 
    } = useSettings();

    console.log('App state:', {
      settingsLoading,
      settingsError,
      hasBatterySettings: !!batterySettings,
      hasElectricitySettings: !!electricitySettings
    });

    // Safely create settings with fallbacks
    const mergedSettings = useMemo(() => {
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
        <div className="min-h-screen flex flex-col bg-gray-50">
          <header className="bg-white shadow sticky top-0 z-10">
            <div className="max-w-7xl mx-auto py-2 px-4 sm:px-6 lg:px-8">
              <div className="flex justify-between items-center">
                <div className="flex items-center space-x-4">
                  <h1 className="text-2xl font-bold text-gray-900">ChargeIQ</h1>
                </div>
                <div className="flex items-center space-x-4">                  
                  {/* Navigation Menu */}
                  <Navigation />
                </div>
              </div>
            </div>
          </header>
          
          <main className="flex-1 w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
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
                  <DashboardPage 
                    onLoadingChange={(loading: boolean) => console.log('Dashboard loading:', loading)}
                    settings={mergedSettings}
                  />
                } />
                <Route path="/insights" element={<InsightsPage />} />
                <Route path="/savings" element={<SavingsAnalysisPage />} />
                <Route path="/inverter" element={<InverterPage />} />
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