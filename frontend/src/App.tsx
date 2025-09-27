import React, { useMemo, useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Link, useLocation, Navigate } from 'react-router-dom';
import DashboardPage from './pages/DashboardPage';
import SavingsAnalysisPage from './pages/SavingsPage';
import InverterPage from './pages/InverterPage';
import InsightsPage from './pages/InsightsPage';
import SystemHealthPage from './pages/SystemHealthPage';
import { useSettings } from './hooks/useSettings';
import { Home, Activity, TrendingUp, Brain, Zap, Sun, Moon } from 'lucide-react';

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
        <div className="min-h-screen flex items-center justify-center bg-red-50 dark:bg-red-900">
          <div className="max-w-md p-6 bg-white dark:bg-gray-800 rounded-lg shadow-lg">
            <h2 className="text-xl font-bold text-red-600 dark:text-red-400 mb-4">Something went wrong</h2>
            <p className="mb-4 dark:text-gray-300">{this.state.error?.message || "An unknown error occurred"}</p>
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
    // FIXED: Dashboard should be active for both "/" and when no specific page is selected
    if (path === '/') {
      // Dashboard is active for root path OR if we're not on any of the other specific pages
      const otherPages = ['/insights', '/savings', '/inverter', '/system-health'];
      const isOnOtherPage = otherPages.some(page => location.pathname.startsWith(page));
      const isDashboardActive = location.pathname === '/' || !isOnOtherPage;
      
      return isDashboardActive ? 'bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-gray-100' : 'text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-gray-100';
    }
    
    // For other pages, check if current path starts with the target path
    return location.pathname.startsWith(path) ? 
      'bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-gray-100' : 'text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-gray-100';
  };
    
  return (
    <div className="flex space-x-2">
      <Link 
        to="/" 
        className={`p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded flex items-center space-x-1 ${isActive('/')}`}
        title="Quick overview & live monitoring"
      >
        <Home className="h-5 w-5" />
        <span className="hidden sm:inline">Dashboard</span>
      </Link>
      <Link 
        to="/savings" 
        className={`p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded flex items-center space-x-1 ${isActive('/savings')}`}
        title="Financial analysis & detailed reports"
      >
        <TrendingUp className="h-5 w-5" />
        <span className="hidden sm:inline">Savings</span>
      </Link>
      <Link 
        to="/inverter" 
        className={`p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded flex items-center space-x-1 ${isActive('/inverter')}`}
        title="Inverter status & battery schedule management"
      >
        <Zap className="h-5 w-5" />
        <span className="hidden sm:inline">Inverter</span>
      </Link>
      <Link 
        to="/insights" 
        className={`p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded flex items-center space-x-1 ${isActive('/insights')}`}
        title="Decision analysis & intelligence"
      >
        <Brain className="h-5 w-5" />
        <span className="hidden sm:inline">Insights</span>
      </Link>
      <Link 
        to="/system-health" 
        className={`p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded flex items-center space-x-1 ${isActive('/system-health')}`}
        title="System status & component health"
      >
        <Activity className="h-5 w-5" />
        <span className="hidden sm:inline">System Health</span>
      </Link>
    </div>
  );
};

function App() {
  
  // Function to toggle dark mode
  const toggleDarkMode = () => {
    setDarkMode(!darkMode);
  };

  // Function to reset to system preference (double-click)
  const resetToSystemPreference = () => {
    localStorage.removeItem('darkMode');
    const systemPreference = window.matchMedia('(prefers-color-scheme: dark)').matches;
    setDarkMode(systemPreference);
  };

  // Enhanced dark mode state with localStorage persistence and system preference detection
  const [darkMode, setDarkMode] = useState(() => {
    // Check localStorage first, then system preference
    const saved = localStorage.getItem('darkMode');
    if (saved !== null) {
      return JSON.parse(saved);
    }
    // Fall back to system preference
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  });

  // Dark mode effect with localStorage persistence
  useEffect(() => {
    // Save preference to localStorage
    localStorage.setItem('darkMode', JSON.stringify(darkMode));
    
    // Apply to document
    if (darkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [darkMode]);

  // Listen for system theme changes (only if user hasn't set a manual preference)
  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handleSystemThemeChange = (e: MediaQueryListEvent) => {
      // Only auto-update if no manual preference is saved
      if (localStorage.getItem('darkMode') === null) {
        setDarkMode(e.matches);
      }
    };

    mediaQuery.addEventListener('change', handleSystemThemeChange);
    return () => mediaQuery.removeEventListener('change', handleSystemThemeChange);
  }, []);

  // Hook calls must be at the top level - never inside try-catch blocks
  const {
    batterySettings,
    electricitySettings,
    isLoading: settingsLoading,
    error: settingsError
  } = useSettings();

  // Validate that we have required settings - no fallbacks allowed
  // This must be at top level to maintain hook call order
  const mergedSettings = useMemo(() => {
    // Only validate when not loading to avoid premature errors
    if (settingsLoading) {
      return null;
    }

    // Fail fast if settings are not available after loading
    if (!batterySettings || !electricitySettings) {
      throw new Error(`Critical settings missing: ${!batterySettings ? 'battery settings' : ''} ${!electricitySettings ? 'electricity settings' : ''}`.trim());
    }

    // Merge settings without fallbacks
    return {
      ...batterySettings,
      ...electricitySettings
    };
  }, [batterySettings, electricitySettings, settingsLoading]);

  try {


    // Early return for loading state
    if (settingsLoading) {
      return (
        <div className="flex items-center justify-center min-h-screen dark:bg-gray-900">
          <div className="p-6 max-w-sm bg-white dark:bg-gray-800 rounded-lg shadow-lg">
            <div className="flex items-center space-x-4">
              <div className="animate-spin h-6 w-6 border-2 border-blue-500 rounded-full border-t-transparent"></div>
              <div className="dark:text-white">Loading settings...</div>
            </div>
          </div>
        </div>
      );
    }

    // Main app render
    return (
      <Router>
        <div className="min-h-screen flex flex-col bg-gray-50 dark:bg-gray-900">
          <header className="bg-white dark:bg-gray-800 shadow sticky top-0 z-10">
            <div className="max-w-7xl mx-auto py-2 px-4 sm:px-6 lg:px-8">
              <div className="flex justify-between items-center">
                <div className="flex items-center space-x-4">
                  <h1 className="text-2xl font-bold text-gray-900 dark:text-white">ChargeIQ</h1>
                </div>
                <div className="flex items-center space-x-4">                  
                  {/* Navigation Menu */}
                  <Navigation />
                  
                  {/* Dark Mode Toggle Button */}
                  <button
                    onClick={toggleDarkMode}
                    onDoubleClick={resetToSystemPreference}
                    className="p-2 rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
                    title={`${darkMode ? "Switch to light mode" : "Switch to dark mode"} • Click to toggle • Double-click to follow system preference`}
                  >
                    {darkMode ? (
                      <Sun className="h-5 w-5 text-yellow-500" />
                    ) : (
                      <Moon className="h-5 w-5 text-gray-600 dark:text-gray-300" />
                    )}
                  </button>
                </div>
              </div>
            </div>
          </header>
          
          <main className="flex-1 w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
            {settingsError && (
              <div className="bg-red-50 dark:bg-red-900/10 p-6 rounded-lg shadow mb-6">
                <h2 className="text-lg font-semibold text-red-700 dark:text-red-400">Error loading settings</h2>
                <p className="mt-2 dark:text-red-300">{settingsError}</p>
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
                    onLoadingChange={(loading: boolean) => {}}
                    settings={mergedSettings}
                  />
                } />
                <Route path="/dashboard" element={<Navigate to="/" replace />} />
                <Route path="/insights" element={<InsightsPage />} />
                <Route path="/savings" element={<SavingsAnalysisPage />} />
                <Route path="/inverter" element={<InverterPage />} />
                <Route path="/system-health" element={<SystemHealthPage />} />
                {/* Catch-all route: redirect any unmatched paths to dashboard */}
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </ErrorBoundary>
          </main>
        </div>
      </Router>
    );
  } catch (err) {
    console.error("Unhandled error in App:", err);
    return (
      <div className="min-h-screen flex items-center justify-center bg-red-50 dark:bg-red-900">
        <div className="max-w-md p-6 bg-white dark:bg-gray-800 rounded-lg shadow-lg">
          <h2 className="text-xl font-bold text-red-600 dark:text-red-400 mb-4">Something went wrong</h2>
          <p className="mb-4 dark:text-gray-300">{err instanceof Error ? err.message : "An unknown error occurred"}</p>
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