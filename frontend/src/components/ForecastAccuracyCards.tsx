import React from 'react';
import { Sun, Home, TrendingUp, Battery, ChevronDown, ChevronUp } from 'lucide-react';
import { SnapshotComparison } from '../types';

interface ForecastAccuracyCardsProps {
  comparison: SnapshotComparison;
}

interface AccuracyStats {
  accuracy: number;
  totalPredicted: number;
  totalActual: number;
  unit: string;
}

interface DeviationStats {
  totalDeviation: number;
  totalPlanned: number;
  totalActual: number;
  unit: string;
}

const computeAccuracy = (
  comparison: SnapshotComparison,
  getPredicted: (d: typeof comparison.periodDeviations[0]) => number,
  getActual: (d: typeof comparison.periodDeviations[0]) => number,
): AccuracyStats => {
  let totalPredicted = 0;
  let totalActual = 0;

  for (const dev of comparison.periodDeviations) {
    totalPredicted += getPredicted(dev);
    totalActual += getActual(dev);
  }

  const denominator = Math.max(totalPredicted, totalActual);
  const relativeError = denominator > 0 ? Math.abs(totalPredicted - totalActual) / denominator : 0;
  const accuracy = Math.max(0, Math.min(100, (1 - relativeError) * 100));

  const unit = comparison.periodDeviations[0]?.predictedSolar?.unit || 'kWh';
  return { accuracy, totalPredicted, totalActual, unit };
};

const computeDeviation = (
  comparison: SnapshotComparison,
  getPlanned: (d: typeof comparison.periodDeviations[0]) => number,
  getActual: (d: typeof comparison.periodDeviations[0]) => number,
): DeviationStats => {
  let totalPlanned = 0;
  let totalActual = 0;
  for (const dev of comparison.periodDeviations) {
    totalPlanned += getPlanned(dev);
    totalActual += getActual(dev);
  }
  return { totalDeviation: totalActual - totalPlanned, totalPlanned, totalActual, unit: 'kWh' };
};

const formatPeriodTime = (period: number): string => {
  const hour = Math.floor(period / 4);
  const minute = (period % 4) * 15;
  return `${hour.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}`;
};

const getAccuracyColor = (accuracy: number): string => {
  if (accuracy >= 90) return 'text-green-600 dark:text-green-400';
  if (accuracy >= 75) return 'text-yellow-600 dark:text-yellow-400';
  return 'text-red-600 dark:text-red-400';
};

const getDeviationText = (value: number, noun: string): string => {
  if (Math.abs(value) < 0.05) return `${noun} on track`;
  const direction = value >= 0 ? 'more' : 'less';
  return `${direction} ${noun} than planned`;
};

const colorClasses: Record<string, string> = {
  yellow: 'text-yellow-600 dark:text-yellow-400 bg-yellow-50 dark:bg-yellow-900/20',
  red: 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20',
  purple: 'text-purple-600 dark:text-purple-400 bg-purple-50 dark:bg-purple-900/20',
  green: 'text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20',
  blue: 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20',
};

const ForecastAccuracyCards: React.FC<ForecastAccuracyCardsProps> = ({ comparison }) => {
  const insufficientData = comparison.periodDeviations.length < 4;

  const solar = computeAccuracy(
    comparison,
    (d) => d.predictedSolar.value,
    (d) => d.actualSolar.value,
  );

  const consumption = computeAccuracy(
    comparison,
    (d) => d.predictedConsumption.value,
    (d) => d.actualConsumption.value,
  );

  const batteryDev = computeDeviation(
    comparison,
    (d) => d.predictedBatteryAction.value,
    (d) => d.actualBatteryAction.value,
  );
  const gridImportDev = computeDeviation(
    comparison,
    (d) => d.predictedGridImport.value,
    (d) => d.actualGridImport.value,
  );
  const gridExportDev = computeDeviation(
    comparison,
    (d) => d.predictedGridExport.value,
    (d) => d.actualGridExport.value,
  );

  const totalDelta = comparison.currentTotalSavings.value - comparison.snapshotTotalSavings.value;
  const snapshotTime = formatPeriodTime(comparison.snapshotPeriod);

  const insufficientContent = (
    <div className="text-sm text-gray-400 dark:text-gray-500 mt-4">Insufficient data</div>
  );

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {/* Solar Accuracy */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700 p-4">
        <div className="flex items-center gap-3 mb-3">
          <div className={`p-2 rounded-lg ${colorClasses.yellow}`}>
            <Sun className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-semibold text-gray-900 dark:text-white">Solar Accuracy</h3>
            <p className="text-sm text-gray-600 dark:text-gray-300">Forecast vs Actual</p>
          </div>
        </div>
        {insufficientData ? insufficientContent : (
          <>
            <div className={`text-2xl font-bold mb-3 ${getAccuracyColor(solar.accuracy)}`}>
              {solar.accuracy.toFixed(0)}%
            </div>
            <div className="space-y-0.5">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600 dark:text-gray-300">Predicted</span>
                <span className="font-medium text-gray-900 dark:text-gray-100">{solar.totalPredicted.toFixed(1)} {solar.unit}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600 dark:text-gray-300">Actual</span>
                <span className="font-medium text-gray-900 dark:text-gray-100">{solar.totalActual.toFixed(1)} {solar.unit}</span>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Consumption Accuracy */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700 p-4">
        <div className="flex items-center gap-3 mb-3">
          <div className={`p-2 rounded-lg ${colorClasses.red}`}>
            <Home className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-semibold text-gray-900 dark:text-white">Consumption Accuracy</h3>
            <p className="text-sm text-gray-600 dark:text-gray-300">Forecast vs Actual</p>
          </div>
        </div>
        {insufficientData ? insufficientContent : (
          <>
            <div className={`text-2xl font-bold mb-3 ${getAccuracyColor(consumption.accuracy)}`}>
              {consumption.accuracy.toFixed(0)}%
            </div>
            <div className="space-y-0.5">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600 dark:text-gray-300">Predicted</span>
                <span className="font-medium text-gray-900 dark:text-gray-100">{consumption.totalPredicted.toFixed(1)} {consumption.unit}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600 dark:text-gray-300">Actual</span>
                <span className="font-medium text-gray-900 dark:text-gray-100">{consumption.totalActual.toFixed(1)} {consumption.unit}</span>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Savings Comparison */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700 p-4">
        <div className="flex items-center gap-3 mb-3">
          <div className={`p-2 rounded-lg ${colorClasses.purple}`}>
            <TrendingUp className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-semibold text-gray-900 dark:text-white">Savings</h3>
            <p className="text-sm text-gray-600 dark:text-gray-300">Full Day Comparison</p>
          </div>
        </div>
        {insufficientData ? insufficientContent : (
          <>
            <div className="text-2xl font-bold text-gray-900 dark:text-white mb-4">
              {comparison.currentTotalSavings.text}
            </div>
            <div className="space-y-0.5">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600 dark:text-gray-300">At {snapshotTime}</span>
                <span className="font-medium text-gray-900 dark:text-gray-100">{comparison.snapshotTotalSavings.text}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600 dark:text-gray-300">Change</span>
                <span className={`font-medium ${
                  totalDelta >= 0
                    ? 'text-green-600 dark:text-green-400'
                    : 'text-red-600 dark:text-red-400'
                }`}>
                  {totalDelta >= 0 ? '+' : ''}{totalDelta.toFixed(2)} {comparison.currentTotalSavings.unit}
                </span>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Battery Deviation */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700 p-4">
        <div className="flex items-center gap-3 mb-3">
          <div className={`p-2 rounded-lg ${colorClasses.green}`}>
            <Battery className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-semibold text-gray-900 dark:text-white">Battery</h3>
            <p className="text-sm text-gray-600 dark:text-gray-300">Schedule Deviation</p>
          </div>
        </div>
        {insufficientData ? insufficientContent : (
          <>
            <div className="text-2xl font-bold text-gray-900 dark:text-white mb-4">
              {batteryDev.totalDeviation >= 0 ? '+' : ''}{batteryDev.totalDeviation.toFixed(1)} {batteryDev.unit}
            </div>
            <div className="space-y-0.5">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600 dark:text-gray-300">Planned</span>
                <span className="font-medium text-gray-900 dark:text-gray-100">{batteryDev.totalPlanned.toFixed(1)} {batteryDev.unit}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600 dark:text-gray-300">Actual</span>
                <span className="font-medium text-gray-900 dark:text-gray-100">{batteryDev.totalActual.toFixed(1)} {batteryDev.unit}</span>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Grid Import Deviation */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700 p-4">
        <div className="flex items-center gap-3 mb-3">
          <div className={`p-2 rounded-lg ${colorClasses.blue}`}>
            <ChevronDown className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-semibold text-gray-900 dark:text-white">Grid Import</h3>
            <p className="text-sm text-gray-600 dark:text-gray-300">Schedule Deviation</p>
          </div>
        </div>
        {insufficientData ? insufficientContent : (
          <>
            <div className="text-2xl font-bold text-gray-900 dark:text-white mb-4">
              {gridImportDev.totalDeviation >= 0 ? '+' : ''}{gridImportDev.totalDeviation.toFixed(1)} {gridImportDev.unit}
            </div>
            <div className="space-y-0.5">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600 dark:text-gray-300">Planned</span>
                <span className="font-medium text-gray-900 dark:text-gray-100">{gridImportDev.totalPlanned.toFixed(1)} {gridImportDev.unit}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600 dark:text-gray-300">Actual</span>
                <span className="font-medium text-gray-900 dark:text-gray-100">{gridImportDev.totalActual.toFixed(1)} {gridImportDev.unit}</span>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Grid Export Deviation */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700 p-4">
        <div className="flex items-center gap-3 mb-3">
          <div className={`p-2 rounded-lg ${colorClasses.blue}`}>
            <ChevronUp className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-semibold text-gray-900 dark:text-white">Grid Export</h3>
            <p className="text-sm text-gray-600 dark:text-gray-300">Schedule Deviation</p>
          </div>
        </div>
        {insufficientData ? insufficientContent : (
          <>
            <div className="text-2xl font-bold text-gray-900 dark:text-white mb-4">
              {gridExportDev.totalDeviation >= 0 ? '+' : ''}{gridExportDev.totalDeviation.toFixed(1)} {gridExportDev.unit}
            </div>
            <div className="space-y-0.5">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600 dark:text-gray-300">Planned</span>
                <span className="font-medium text-gray-900 dark:text-gray-100">{gridExportDev.totalPlanned.toFixed(1)} {gridExportDev.unit}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600 dark:text-gray-300">Actual</span>
                <span className="font-medium text-gray-900 dark:text-gray-100">{gridExportDev.totalActual.toFixed(1)} {gridExportDev.unit}</span>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default ForecastAccuracyCards;
