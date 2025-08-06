import React, { useState } from 'react';

// Types for props (replace with your actual types)
type FutureValueContribution = {
  hour: number;
  contribution: number;
};
type DecisionAlternative = {
  battery_action: number;
  total_reward: number;
  immediate_reward: number;
  future_value: number;
  confidence_score: number;
};
type HourlyDecision = {
  hour: number;
  battery_action: number;
  immediate_value: number;
  future_value: number;
  total_reward: number;
  alternatives_evaluated: DecisionAlternative[];
  future_value_timeline: FutureValueContribution[];
  // ...other fields as needed
};

type Props = {
  data: HourlyDecision[];
};

const fontFamily = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";

const DecisionInsightsPage: React.FC<Props> = ({ data }) => {
  const [expandedHour, setExpandedHour] = useState<number | null>(null);
  const [viewType, setViewType] = useState<'simple' | 'full'>('simple');
  const [tab, setTab] = useState<{ [hour: number]: string }>({});

  const toggleHour = (hour: number) => {
    setExpandedHour(expandedHour === hour ? null : hour);
  };

  const showTab = (hour: number, tabName: string) => {
    setTab({ ...tab, [hour]: tabName });
  };

  return (
    <div className="max-w-[1200px] mx-auto" style={{ fontFamily }}>
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900 mb-2">Decision Intelligence</h1>
        <p className="text-gray-500 text-sm">Battery management optimization • Today, March 15, 2024</p>
      </div>
      <div className="bg-white p-6 rounded-lg shadow overflow-x-auto">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h2 className="text-xl font-semibold text-gray-900 mb-2">Hourly Decision Analysis</h2>
            <p className="text-gray-500 text-sm">Click any hour to explore the decision reasoning</p>
          </div>
          <div className="flex gap-2">
            <button className={`toggle-btn${viewType === 'simple' ? ' active' : ''} flex items-center px-4 py-2 rounded-md text-sm font-medium border-none transition`} onClick={() => setViewType('simple')}>Simple View</button>
            <button className={`toggle-btn${viewType === 'full' ? ' active' : ''} flex items-center px-4 py-2 rounded-md text-sm font-medium border-none transition`} onClick={() => setViewType('full')}>Full View</button>
          </div>
        </div>
        {/* Table */}
        <table className="min-w-full border-collapse bg-white" style={{ display: viewType === 'simple' ? '' : 'none' }}>
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2 text-center text-xs font-medium text-gray-700 uppercase border">Hour</th>
              <th className="px-3 py-2 text-center text-xs font-medium text-gray-700 uppercase border">Battery Action</th>
              <th className="px-3 py-2 text-center text-xs font-medium text-gray-700 uppercase border">Immediate Value</th>
              <th className="px-3 py-2 text-center text-xs font-medium text-gray-700 uppercase border">Future Value</th>
              <th className="px-3 py-2 text-center text-xs font-medium text-gray-700 uppercase border">Total Reward</th>
              <th className="border"></th>
            </tr>
          </thead>
          <tbody>
            {data.map((hour) => (
              <React.Fragment key={hour.hour}>
                <tr className={`hour-row actual cursor-pointer transition hover:bg-gray-50 border-l-4 border-green-500 bg-white`} onClick={() => toggleHour(hour.hour)} data-hour={hour.hour}>
                  {/* Hour column with badge inside */}
                  <td className="text-left align-middle font-medium text-gray-900">
                    <div className="flex items-center">
                      <span>{hour.hour.toString().padStart(2, '0')}:00</span>
                      <span className="ml-2 px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">Actual</span>
                    </div>
                  </td>
                  {/* Battery Action */}
                  <td className="text-center align-middle">
                    <div className={hour.battery_action > 0 ? 'text-green-600 font-medium' : hour.battery_action < 0 ? 'text-red-600 font-medium' : 'text-gray-500 font-medium'}>
                      {hour.battery_action > 0 ? '+' : ''}{hour.battery_action} kWh
                    </div>
                    <span className="text-xs text-gray-500 font-normal block">{hour.battery_action > 0 ? 'Charge' : hour.battery_action < 0 ? 'Discharge' : 'Hold'}</span>
                  </td>
                  {/* Immediate Value */}
                  <td className="text-center align-middle">
                    <div className={hour.immediate_value > 0 ? 'text-green-600 font-medium' : hour.immediate_value < 0 ? 'text-red-600 font-medium' : 'text-gray-500 font-medium'}>
                      {hour.immediate_value > 0 ? '+' : ''}{hour.immediate_value.toFixed(2)}
                    </div>
                    <span className="text-xs text-gray-500 font-normal block">SEK</span>
                  </td>
                  {/* Future Value */}
                  <td className="text-center align-middle">
                    <div className={hour.future_value > 0 ? 'text-green-600 font-medium' : hour.future_value < 0 ? 'text-red-600 font-medium' : 'text-gray-500 font-medium'}>
                      {hour.future_value > 0 ? '+' : ''}{hour.future_value.toFixed(2)}
                    </div>
                    <span className="text-xs text-gray-500 font-normal block">SEK</span>
                  </td>
                  {/* Total Reward */}
                  <td className="text-center align-middle">
                    <div className={hour.total_reward > 0 ? 'text-green-600 font-medium' : hour.total_reward < 0 ? 'text-red-600 font-medium' : 'text-gray-500 font-medium'}>
                      {hour.total_reward > 0 ? '+' : ''}{hour.total_reward.toFixed(2)}
                    </div>
                    <span className="text-xs text-gray-500 font-normal block">SEK</span>
                  </td>
                  {/* Expand icon */}
                  <td className="text-center align-middle">
                    <svg className="expand-icon w-4 h-4 text-gray-400 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7" /></svg>
                  </td>
                </tr>
                {expandedHour === hour.hour && (
                  <tr className="hour-details" data-hour={hour.hour}>
                    <td colSpan={6} className="p-0 border-none">
                      <div className="p-6 bg-gray-50 border-l-4 border-green-500">
                        <div className="flex border-b border-gray-200 mb-5">
                          <div className={`px-4 py-2 cursor-pointer border-b-2 text-sm font-medium ${((tab[hour.hour] || 'landscape') === 'landscape') ? 'text-blue-600 border-blue-600' : 'text-gray-500 border-transparent'}`} onClick={() => showTab(hour.hour, 'landscape')}>Battery Action</div>
                          <div className={`px-4 py-2 cursor-pointer border-b-2 text-sm font-medium ${((tab[hour.hour] || '') === 'economic') ? 'text-blue-600 border-blue-600' : 'text-gray-500 border-transparent'}`} onClick={() => showTab(hour.hour, 'economic')}>Immediate Value</div>
                          <div className={`px-4 py-2 cursor-pointer border-b-2 text-sm font-medium ${((tab[hour.hour] || '') === 'future') ? 'text-blue-600 border-blue-600' : 'text-gray-500 border-transparent'}`} onClick={() => showTab(hour.hour, 'future')}>Future Value</div>
                        </div>
                        {/* Tab content - implement as needed, placeholder for now */}
                        <div className={`${((tab[hour.hour] || 'landscape') === 'landscape') ? '' : 'hidden'}`}>Battery Action Analysis (implement chart/table here)</div>
                        <div className={`${((tab[hour.hour] || '') === 'economic') ? '' : 'hidden'}`}>Immediate Value Analysis (implement chart/table here)</div>
                        <div className={`${((tab[hour.hour] || '') === 'future') ? '' : 'hidden'}`}>Future Value (implement chart/table here)</div>
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
        {/* Full View Table - similar structure, add more columns as in your HTML */}
        <table className="min-w-full border-collapse bg-white" style={{ display: viewType === 'full' ? '' : 'none' }}>
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2 text-center text-xs font-medium text-gray-700 uppercase border">Hour</th>
              <th className="px-3 py-2 text-center text-xs font-medium text-gray-700 uppercase border">Home Load</th>
              <th className="px-3 py-2 text-center text-xs font-medium text-gray-700 uppercase border">Solar</th>
              <th className="px-3 py-2 text-center text-xs font-medium text-gray-700 uppercase border">Grid Price</th>
              <th className="px-3 py-2 text-center text-xs font-medium text-gray-700 uppercase border">Battery Action</th>
              <th className="px-3 py-2 text-center text-xs font-medium text-gray-700 uppercase border">Immediate Value</th>
              <th className="px-3 py-2 text-center text-xs font-medium text-gray-700 uppercase border">Future Value</th>
              <th className="px-3 py-2 text-center text-xs font-medium text-gray-700 uppercase border">Total Reward</th>
              <th className="border"></th>
            </tr>
          </thead>
          <tbody>
            {/* Map your data here for full view */}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default DecisionInsightsPage;
