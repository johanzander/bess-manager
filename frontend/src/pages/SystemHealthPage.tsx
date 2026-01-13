import React, { useState } from 'react';
import { Download } from 'lucide-react';
import SystemHealthComponent from '../components/SystemHealth';
import api from '../lib/api';

const SystemHealthPage: React.FC = () => {
  const [isExporting, setIsExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const handleExportDebugData = async () => {
    setIsExporting(true);
    setExportError(null);

    try {
      const response = await api.get('/api/export-debug-data', {
        responseType: 'blob',
      });

      // Extract filename from Content-Disposition header
      const contentDisposition = response.headers['content-disposition'];
      let filename = 'bess-debug.md';

      if (contentDisposition) {
        const filenameMatch = contentDisposition.match(/filename=(.+)/);
        if (filenameMatch) {
          filename = filenameMatch[1].replace(/"/g, '');
        }
      }

      // Download file
      const blob = new Blob([response.data], { type: 'text/markdown' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Failed to export debug data:', error);
      setExportError('Failed to export debug data. Please check the logs.');
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div className="p-6 space-y-6 bg-gray-50 dark:bg-gray-900 min-h-screen">
      <div className="mb-6 flex justify-between items-start">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">System Health</h1>
          <p className="text-gray-600 dark:text-gray-300">
            Monitor all system components to ensure they have proper access to required sensors and can operate correctly.
          </p>
        </div>

        <button
          onClick={handleExportDebugData}
          disabled={isExporting}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed text-white font-medium transition-colors"
          title="Export all system data, logs, and settings for debugging"
        >
          <Download className="w-4 h-4" />
          {isExporting ? 'Exporting...' : 'Export Debug Data'}
        </button>
      </div>

      {exportError && (
        <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
          <p className="text-red-800 dark:text-red-200">{exportError}</p>
        </div>
      )}
      
      <div className="mb-6">
        <SystemHealthComponent />
      </div>
      
      <div className="mt-8 bg-gray-100 dark:bg-gray-800/50 p-4 rounded-lg border border-gray-200 dark:border-gray-700">
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">Status Indicators</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
          <div>
            <ul className="space-y-1 text-gray-600 dark:text-gray-400">
              <li><span className="text-green-600 dark:text-green-400 font-medium">OK</span>: Component is fully functional with all required sensors.</li>
              <li><span className="text-amber-600 dark:text-amber-400 font-medium">WARNING</span>: Component has minor issues but can operate with limitations.</li>
              <li><span className="text-red-600 dark:text-red-400 font-medium">ERROR</span>: Component has critical issues and may not function correctly.</li>
            </ul>
          </div>
          <div>
            <ul className="space-y-1 text-gray-600 dark:text-gray-400">
              <li><span className="font-medium">Required</span>: Essential for basic system operation.</li>
              <li><span className="font-medium">Optional</span>: Enhances functionality but not essential for basic operation.</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SystemHealthPage;