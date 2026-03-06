import React, { useEffect, useState } from 'react';
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { LineChart as LineChartIcon, AlertCircle, Info } from 'lucide-react';
import api from '../lib/api';

interface MLMetrics {
  maeKwh: number;
  rmseKwh: number;
  rSquared: number;
  mapePercent: number;
}

interface MLReportData {
  isActive: boolean;
  activeStrategy?: string;
  modelAvailable: boolean;
  lastTrained?: string;
  trainSize?: number;
  testSize?: number;
  metrics?: MLMetrics;
  baselines?: Record<string, MLMetrics>;
  featureImportance?: Array<{ name: string; importance: number }>;
  forecastDate?: string;
  predictions?: number[];
  yesterdayProfile?: number[];
  weekAvgProfile?: number[];
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatLabel(name: string): string {
  return name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

const BASELINE_LABELS: Record<string, string> = {
  same_as_yesterday: 'Same as Yesterday',
  hourly_mean: 'Hourly Mean',
  flat_estimate: 'Flat Estimate',
};

const MLReportPage: React.FC = () => {
  const [data, setData] = useState<MLReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get('/api/ml-report')
      .then((res) => setData(res.data))
      .catch((err) => setError(err?.message ?? 'Failed to load ML report'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="p-6 bg-gray-50 dark:bg-gray-900 min-h-screen flex items-center justify-center">
        <div className="flex items-center gap-3 text-gray-600 dark:text-gray-400">
          <div className="animate-spin h-5 w-5 border-2 border-blue-500 rounded-full border-t-transparent" />
          Loading ML report...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 bg-gray-50 dark:bg-gray-900 min-h-screen">
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 flex items-start gap-3">
          <AlertCircle className="h-5 w-5 text-red-500 mt-0.5 shrink-0" />
          <p className="text-red-700 dark:text-red-300">{error}</p>
        </div>
      </div>
    );
  }

  const notConfigured = data && !data.isActive;
  const noModel = data && data.isActive && !data.modelAvailable;

  return (
    <div className="p-6 space-y-6 bg-gray-50 dark:bg-gray-900 min-h-screen">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-3">
          <LineChartIcon className="h-7 w-7 text-blue-600 dark:text-blue-400" />
          ML Report
        </h1>
        <p className="text-gray-600 dark:text-gray-300 mt-1">
          Review ML forecast quality, model accuracy, and feature drivers.
        </p>
      </div>

      {notConfigured && (
        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4 flex items-start gap-3">
          <Info className="h-5 w-5 text-blue-500 mt-0.5 shrink-0" />
          <div>
            <p className="font-medium text-blue-800 dark:text-blue-200">ML prediction not active</p>
            <p className="text-sm text-blue-700 dark:text-blue-300 mt-1">
              Set <code className="font-mono bg-blue-100 dark:bg-blue-800 px-1 rounded">consumption_strategy</code> to{' '}
              <code className="font-mono bg-blue-100 dark:bg-blue-800 px-1 rounded">ml_prediction</code> or{' '}
              <code className="font-mono bg-blue-100 dark:bg-blue-800 px-1 rounded">influxdb_profile</code> in your configuration to enable the ML forecast engine.
            </p>
          </div>
        </div>
      )}

      {noModel && (
        <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-4 flex items-start gap-3">
          <AlertCircle className="h-5 w-5 text-amber-500 mt-0.5 shrink-0" />
          <div>
            <p className="font-medium text-amber-800 dark:text-amber-200">No trained model found</p>
            <p className="text-sm text-amber-700 dark:text-amber-300 mt-1">
              Run <code className="font-mono bg-amber-100 dark:bg-amber-800 px-1 rounded">python -m ml train</code> to train the model and generate a report.
            </p>
          </div>
        </div>
      )}

      {data?.modelAvailable && data.metrics && (
        <>
          <SummaryCards data={data} />
          <ForecastChart
            predictions={data.predictions}
            yesterday={data.yesterdayProfile}
            weekAvg={data.weekAvgProfile}
            forecastDate={data.forecastDate}
            activeStrategy={data.activeStrategy}
          />
          <MetricsTable metrics={data.metrics} baselines={data.baselines ?? {}} />
          <FeatureImportanceChart features={data.featureImportance ?? []} />
        </>
      )}
    </div>
  );
};

// ── Summary cards ──────────────────────────────────────────────────────────────

interface SummaryCardsProps {
  data: MLReportData;
}

const SummaryCards: React.FC<SummaryCardsProps> = ({ data }) => {
  const total24h =
    data.predictions ? data.predictions.reduce((s, v) => s + v, 0).toFixed(2) : '—';

  const bestBaselineMae =
    data.baselines
      ? Math.min(...Object.values(data.baselines).map((b) => b.maeKwh))
      : null;

  const improvement =
    bestBaselineMae !== null && data.metrics
      ? (((bestBaselineMae - data.metrics.maeKwh) / bestBaselineMae) * 100).toFixed(1)
      : null;

  const cards = [
    {
      label: 'Last Trained',
      value: data.lastTrained ? formatDateTime(data.lastTrained) : '—',
      sub: `${data.trainSize?.toLocaleString()} train / ${data.testSize?.toLocaleString()} test samples`,
    },
    {
      label: 'Total Forecast 24h',
      value: `${total24h} kWh`,
      sub: data.forecastDate ? `For ${data.forecastDate}` : 'No forecast cached',
    },
    {
      label: 'Model MAE',
      value: data.metrics ? `${data.metrics.maeKwh} kWh` : '—',
      sub: `RMSE ${data.metrics?.rmseKwh} kWh · R² ${data.metrics?.rSquared}`,
    },
    {
      label: 'vs Best Baseline',
      value: improvement !== null ? `${improvement}% better` : '—',
      sub: `Best baseline MAE: ${bestBaselineMae?.toFixed(4)} kWh`,
      highlight: improvement !== null && parseFloat(improvement) > 0,
    },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {cards.map((c) => (
        <div key={c.label} className="bg-white dark:bg-gray-800 rounded-lg shadow p-4">
          <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
            {c.label}
          </p>
          <p
            className={`mt-1 text-xl font-semibold ${
              c.highlight
                ? 'text-green-600 dark:text-green-400'
                : 'text-gray-900 dark:text-white'
            }`}
          >
            {c.value}
          </p>
          {c.sub && <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{c.sub}</p>}
        </div>
      ))}
    </div>
  );
};

// ── Forecast chart ─────────────────────────────────────────────────────────────

interface ForecastChartProps {
  predictions?: number[];
  yesterday?: number[];
  weekAvg?: number[];
  forecastDate?: string;
  activeStrategy?: string;
}

const TOOLTIP_LABELS: Record<string, string> = {
  predicted: 'ML Predicted',
  weekAvg: 'Weekly Average',
  yesterday: 'Yesterday',
};

const ForecastChart: React.FC<ForecastChartProps> = ({ predictions, yesterday, weekAvg, forecastDate, activeStrategy }) => {
  const hasAnyData = predictions?.length || weekAvg?.length;
  if (!hasAnyData) return null;

  const length = Math.max(predictions?.length ?? 0, weekAvg?.length ?? 0, yesterday?.length ?? 0);
  const chartData = Array.from({ length }, (_, i) => {
    const label = i % 4 === 0 ? `${String(Math.floor(i / 4)).padStart(2, '0')}:00` : '';
    return {
      period: i,
      label,
      predicted: predictions?.[i] !== undefined ? Math.round(predictions[i] * 1000) / 1000 : undefined,
      weekAvg: weekAvg?.[i] !== undefined ? Math.round(weekAvg[i] * 1000) / 1000 : undefined,
      yesterday: yesterday?.[i] !== undefined ? Math.round(yesterday[i] * 1000) / 1000 : undefined,
    };
  });

  const strategyLabel = activeStrategy === 'influxdb_profile' ? ' (using Weekly Average)' : '';

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
      <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-1">
        Consumption Forecast{strategyLabel}
      </h2>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
        96-period forecast{forecastDate ? ` for ${forecastDate}` : ''} vs yesterday's actual (kWh per 15 min)
      </p>
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 11 }}
            interval={0}
            tickFormatter={(v) => v}
          />
          <YAxis tick={{ fontSize: 11 }} width={50} tickFormatter={(v) => `${v}`} />
          <Tooltip
            formatter={(value: number, name: string) => [
              `${value} kWh`,
              TOOLTIP_LABELS[name] ?? name,
            ]}
            labelFormatter={(_, payload) => {
              if (!payload?.length) return '';
              const p = payload[0].payload as { period: number };
              const h = Math.floor(p.period / 4);
              const m = (p.period % 4) * 15;
              return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
            }}
          />
          <Legend formatter={(value: string) => TOOLTIP_LABELS[value] ?? value} />
          {predictions?.length ? (
            <Line
              type="monotone"
              dataKey="predicted"
              stroke="#3b82f6"
              dot={false}
              strokeWidth={2}
              name="predicted"
            />
          ) : null}
          {weekAvg?.length ? (
            <Line
              type="monotone"
              dataKey="weekAvg"
              stroke="#10b981"
              dot={false}
              strokeWidth={2}
              strokeDasharray={activeStrategy === 'influxdb_profile' ? undefined : '6 3'}
              name="weekAvg"
            />
          ) : null}
          {yesterday?.length ? (
            <Line
              type="monotone"
              dataKey="yesterday"
              stroke="#9ca3af"
              dot={false}
              strokeWidth={1.5}
              strokeDasharray="4 2"
              name="yesterday"
            />
          ) : null}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

// ── Metrics table ──────────────────────────────────────────────────────────────

interface MetricsTableProps {
  metrics: MLMetrics;
  baselines: Record<string, MLMetrics>;
}

const MetricsTable: React.FC<MetricsTableProps> = ({ metrics, baselines }) => {
  const rows: Array<{ key: string; label: string; metrics: MLMetrics; isModel: boolean }> = [
    { key: 'model', label: 'XGBoost (model)', metrics, isModel: true },
    ...Object.entries(baselines).map(([k, v]) => ({
      key: k,
      label: BASELINE_LABELS[k] ?? formatLabel(k),
      metrics: v,
      isModel: false,
    })),
  ];

  const bestMae = Math.min(...rows.map((r) => r.metrics.maeKwh));
  const bestRmse = Math.min(...rows.map((r) => r.metrics.rmseKwh));
  const bestR2 = Math.max(...rows.map((r) => r.metrics.rSquared));
  const bestMape = Math.min(...rows.map((r) => r.metrics.mapePercent));

  const cellClass = (val: number, best: number, lowerIsBetter: boolean) => {
    const isBest = lowerIsBetter ? val === best : val === best;
    return isBest
      ? 'text-green-700 dark:text-green-400 font-semibold'
      : 'text-gray-700 dark:text-gray-300';
  };

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
      <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-4">
        Model vs Baselines
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 dark:border-gray-700">
              <th className="text-left py-2 pr-4 font-medium text-gray-500 dark:text-gray-400">
                Model
              </th>
              <th className="text-right py-2 px-4 font-medium text-gray-500 dark:text-gray-400">
                MAE (kWh)
              </th>
              <th className="text-right py-2 px-4 font-medium text-gray-500 dark:text-gray-400">
                RMSE (kWh)
              </th>
              <th className="text-right py-2 px-4 font-medium text-gray-500 dark:text-gray-400">
                R²
              </th>
              <th className="text-right py-2 pl-4 font-medium text-gray-500 dark:text-gray-400">
                MAPE (%)
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.key}
                className={`border-b border-gray-100 dark:border-gray-700/50 ${
                  row.isModel ? 'bg-blue-50 dark:bg-blue-900/20' : ''
                }`}
              >
                <td className="py-2 pr-4 font-medium text-gray-900 dark:text-white">
                  {row.label}
                </td>
                <td className={`py-2 px-4 text-right ${cellClass(row.metrics.maeKwh, bestMae, true)}`}>
                  {row.metrics.maeKwh}
                </td>
                <td className={`py-2 px-4 text-right ${cellClass(row.metrics.rmseKwh, bestRmse, true)}`}>
                  {row.metrics.rmseKwh}
                </td>
                <td className={`py-2 px-4 text-right ${cellClass(row.metrics.rSquared, bestR2, false)}`}>
                  {row.metrics.rSquared}
                </td>
                <td className={`py-2 pl-4 text-right ${cellClass(row.metrics.mapePercent, bestMape, true)}`}>
                  {row.metrics.mapePercent}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-gray-400 dark:text-gray-500">
        Green highlights indicate best value per column.
      </p>
    </div>
  );
};

// ── Feature importance chart ───────────────────────────────────────────────────

interface FeatureImportanceChartProps {
  features: Array<{ name: string; importance: number }>;
}

const FeatureImportanceChart: React.FC<FeatureImportanceChartProps> = ({ features }) => {
  if (!features.length) return null;

  const top10 = features.slice(0, 10);
  const maxImp = top10[0].importance;

  const chartData = top10
    .map((f) => ({
      name: formatLabel(f.name),
      importance: Math.round((f.importance / maxImp) * 1000) / 1000,
    }))
    .reverse();

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
      <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-1">
        Feature Importance
      </h2>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
        Top 10 features, relative to the most important feature.
      </p>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart
          data={chartData}
          layout="vertical"
          margin={{ top: 0, right: 24, left: 0, bottom: 0 }}
        >
          <CartesianGrid strokeDasharray="3 3" horizontal={false} className="opacity-30" />
          <XAxis type="number" domain={[0, 1]} tick={{ fontSize: 11 }} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
          <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={160} />
          <Tooltip formatter={(v: number) => [`${(v * 100).toFixed(1)}%`, 'Relative importance']} />
          <Bar dataKey="importance" fill="#3b82f6" radius={[0, 3, 3, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};

export default MLReportPage;
