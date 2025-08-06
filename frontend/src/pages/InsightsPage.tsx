import React, { useState, useEffect } from 'react';
import { Brain, Info, AlertCircle, Loader2 } from 'lucide-react';
import DecisionIntelligenceTable from '../components/DecisionIntelligenceTable';
import DecisionAnalysisPanel from '../components/DecisionAnalysisPanel';
import { DecisionIntelligenceResponse } from '../types/decisionIntelligence';
import api from '../lib/api';


const InsightsPage: React.FC = () => {
  const [decisionData, setDecisionData] = useState<DecisionIntelligenceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Move expandedHour and activeTab state to top level
  const [expandedHour, setExpandedHour] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<'landscape' | 'economic' | 'future'>('landscape');

  useEffect(() => {
    const fetchDecisionIntelligence = async () => {
      try {
        setLoading(true);
        setError(null);
        const response = await api.get('/api/decision-intelligence');
        setDecisionData(response.data);
      } catch (err) {
        console.error('Error fetching decision intelligence:', err);
        setError('Failed to load decision intelligence data. Please try again.');
      } finally {
        setLoading(false);
      }
    };

    fetchDecisionIntelligence();
    
    // Refresh data every 5 minutes
    const interval = setInterval(fetchDecisionIntelligence, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  const renderContent = () => {
    if (loading) {
      return (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700 p-8">
          <div className="flex items-center justify-center gap-3">
            <Loader2 className="h-6 w-6 animate-spin text-blue-600 dark:text-blue-400" />
            <span className="text-gray-600 dark:text-gray-300">Loading decision intelligence data...</span>
          </div>
        </div>
      );
    }

    if (error) {
      return (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700 p-8">
          <div className="flex items-center gap-3 text-red-600 dark:text-red-400">
            <AlertCircle className="h-6 w-6" />
            <div>
              <h3 className="font-medium">Error Loading Data</h3>
              <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">{error}</p>
            </div>
          </div>
        </div>
      );
    }

    if (!decisionData || !decisionData.patterns.length) {
      return (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700 p-8">
          <div className="text-center text-gray-500 dark:text-gray-400">
            <Brain className="h-12 w-12 mx-auto mb-4 opacity-50" />
            <h3 className="font-medium mb-2">No Decision Intelligence Available</h3>
            <p className="text-sm">Run an optimization to see decision analysis.</p>
          </div>
        </div>
      );
    }

    return (
      <div className="space-y-4">
        <DecisionIntelligenceTable
          patterns={decisionData.patterns}
        />
        {expandedHour !== null && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700 p-6">
            <div className="flex space-x-2 mb-4">
              <button
                className={`px-4 py-2 rounded font-medium transition-colors ${activeTab === 'landscape' ? 'bg-blue-100 text-blue-900 dark:bg-blue-900 dark:text-blue-100' : 'text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100'}`}
                onClick={() => setActiveTab('landscape')}
              >
                Decision Landscape
              </button>
              <button
                className={`px-4 py-2 rounded font-medium transition-colors ${activeTab === 'economic' ? 'bg-green-100 text-green-900 dark:bg-green-900 dark:text-green-100' : 'text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100'}`}
                onClick={() => setActiveTab('economic')}
              >
                Economic Breakdown
              </button>
              <button
                className={`px-4 py-2 rounded font-medium transition-colors ${activeTab === 'future' ? 'bg-purple-100 text-purple-900 dark:bg-purple-900 dark:text-purple-100' : 'text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100'}`}
                onClick={() => setActiveTab('future')}
              >
                Future Timeline
              </button>
            </div>
            <DecisionAnalysisPanel
              pattern={decisionData.patterns.find(p => p.hour === expandedHour)!}
              view={activeTab}
            />
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="p-6 space-y-6 bg-gray-50 dark:bg-gray-900 min-h-screen">
      {/* Page Header */}
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white flex items-center">
          <Brain className="h-8 w-8 mr-3 text-purple-600 dark:text-purple-400" />
          Insights & Decision Intelligence
        </h1>
        <p className="text-gray-600 dark:text-gray-300 mt-2">
          Deep insights into your battery system's decision-making process and optimization strategies
        </p>
      </div>

      {/* Summary Cards (if data available) */}
      {decisionData && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
          <div className="bg-white dark:bg-gray-800 p-4 rounded-lg shadow border border-gray-200 dark:border-gray-700">
            <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400">Total Net Value</h3>
            <p className={`text-2xl font-bold ${
              decisionData.summary.totalNetValue >= 0 
                ? 'text-green-600 dark:text-green-400' 
                : 'text-red-600 dark:text-red-400'
            }`}>
              {decisionData.summary.totalNetValue >= 0 ? '+' : ''}
              {decisionData.summary.totalNetValue.toFixed(2)} SEK
            </p>
          </div>
          
          <div className="bg-white dark:bg-gray-800 p-4 rounded-lg shadow border border-gray-200 dark:border-gray-700">
            <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400">Average Confidence</h3>
            <p className="text-2xl font-bold text-gray-900 dark:text-white">
              {(decisionData.summary.averageConfidence * 100).toFixed(0)}%
            </p>
          </div>
          
          <div className="bg-white dark:bg-gray-800 p-4 rounded-lg shadow border border-gray-200 dark:border-gray-700">
            <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400">Opportunity Cost</h3>
            <p className="text-2xl font-bold text-red-600 dark:text-red-400">
              {(decisionData.summary.totalOpportunityCost ?? 0).toFixed(2)} SEK
            </p>
          </div>
          
          <div className="bg-white dark:bg-gray-800 p-4 rounded-lg shadow border border-gray-200 dark:border-gray-700">
            <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400">Hours with Alternatives</h3>
            <p className="text-2xl font-bold text-gray-900 dark:text-white">
              {decisionData.summary.hoursWithAlternatives} / {decisionData.patterns.length}
            </p>
          </div>
        </div>
      )}

      {/* Decision Intelligence Table */}
      {renderContent()}

      {/* Educational Information */}
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow border border-gray-200 dark:border-gray-700">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4 flex items-center">
          <Info className="h-5 w-5 mr-2" />
          About Decision Intelligence
        </h2>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 text-sm text-gray-700 dark:text-gray-300">
          <div>
            <h3 className="font-medium mb-2 text-gray-900 dark:text-white">How It Works</h3>
            <p className="mb-3">
              The Decision Intelligence framework analyzes every battery decision using sophisticated 
              Dynamic Programming optimization. Each action is evaluated based on current conditions, 
              future price forecasts, and multi-hour arbitrage opportunities.
            </p>
            
            <h3 className="font-medium mb-2 text-gray-900 dark:text-white">Decision Landscape</h3>
            <p>
              Shows real alternatives the optimization algorithm evaluated, with confidence scores 
              indicating how close each alternative was to optimal. The chosen action represents 
              the best trade-off between immediate and future value.
            </p>
          </div>
          
          <div>
            <h3 className="font-medium mb-2 text-gray-900 dark:text-white">Economic Breakdown</h3>
            <p className="mb-3">
              Detailed analysis of economic components shows exactly how value is created: grid 
              purchase costs, avoidance benefits, battery cost basis, wear costs, and export revenue. 
              This transparency builds trust in the optimization decisions.
            </p>
            
            <h3 className="font-medium mb-2 text-gray-900 dark:text-white">Future Timeline</h3>
            <p>
              Each decision includes forward-looking analysis showing when and how future value 
              will be realized. For example, charging at cheap night rates enables profitable 
              discharge during expensive peak hours.
            </p>
          </div>
        </div>

        {/* Feature Highlights */}
        <div className="mt-6 pt-6 border-t border-gray-200 dark:border-gray-700">
          <h3 className="font-medium mb-3 text-gray-900 dark:text-white">Key Features</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
            <div className="flex items-start gap-2">
              <div className="w-2 h-2 bg-blue-500 rounded-full mt-2 flex-shrink-0"></div>
              <div>
                <span className="font-medium text-gray-900 dark:text-white">Real DP Alternatives:</span>
                <span className="text-gray-600 dark:text-gray-400 ml-1">
                  Shows actual alternatives the algorithm evaluated with real computed rewards
                </span>
              </div>
            </div>
            <div className="flex items-start gap-2">
              <div className="w-2 h-2 bg-green-500 rounded-full mt-2 flex-shrink-0"></div>
              <div>
                <span className="font-medium text-gray-900 dark:text-white">Economic Transparency:</span>
                <span className="text-gray-600 dark:text-gray-400 ml-1">
                  Detailed cost/benefit breakdown using actual optimization data
                </span>
              </div>
            </div>
            <div className="flex items-start gap-2">
              <div className="w-2 h-2 bg-purple-500 rounded-full mt-2 flex-shrink-0"></div>
              <div>
                <span className="font-medium text-gray-900 dark:text-white">Future Value Timeline:</span>
                <span className="text-gray-600 dark:text-gray-400 ml-1">
                  Shows when and how future value will be realized
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default InsightsPage;