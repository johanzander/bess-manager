import React from 'react';
import { ScheduleSummary, HourlyData } from '../types';

interface SummaryCardsProps {
  summary: ScheduleSummary;
  hourlyData: HourlyData[];
}

export const SummaryCards: React.FC<SummaryCardsProps> = ({ summary, hourlyData }) => {
    return (
        <div className="p-6 space-y-8 bg-gray-50">
    
          {/* Cost Summary Cards */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
            <div className="bg-white p-6 rounded-lg shadow">
              <h3 className="text-lg font-medium text-gray-900 mb-2">Base Cost</h3>
              <p className="text-3xl font-bold text-gray-600">{summary.baseCost.toFixed(2)} SEK</p>
              <p className="text-sm text-gray-500 mt-2">Without optimization</p>
            </div>
    
            <div className="bg-white p-6 rounded-lg shadow">
              <h3 className="text-lg font-medium text-gray-900 mb-2">Optimized Cost</h3>
              <p className="text-3xl font-bold text-green-600">{summary.optimizedCost.toFixed(2)} SEK</p>
              <p className="text-sm text-gray-500 mt-2">With battery storage</p>
            </div>
    
            <div className="bg-white p-6 rounded-lg shadow">
              <h3 className="text-lg font-medium text-gray-900 mb-2">Total Savings</h3>
              <p className="text-3xl font-bold text-purple-600">{summary.savings.toFixed(2)} SEK</p>
              <p className="text-sm text-gray-500 mt-2">{((summary.savings / summary.baseCost) * 100).toFixed(1)}% reduction</p>
            </div>
    
            <div className="bg-white p-6 rounded-lg shadow">
              <h3 className="text-lg font-medium text-gray-900 mb-2">Energy Discharged</h3>
              <p className="text-3xl font-bold text-blue-600">{hourlyData.reduce((sum, h) => sum + (h.action > 0 ? h.action : 0), 0).toFixed(1)} kWh</p>
              <p className="text-sm text-gray-500 mt-2">Battery usage</p>
            </div>
            </div>
        </div>)    
};