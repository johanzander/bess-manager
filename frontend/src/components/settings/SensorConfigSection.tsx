import React, { useState } from 'react';
import { AlertCircle, CheckCircle, ChevronDown, ChevronUp } from 'lucide-react';
import { INTEGRATIONS } from '../../lib/sensorDefinitions';
import type { IntegrationDef } from '../../lib/sensorDefinitions';
import type { HealthStatus } from '../../types';

// ---------------------------------------------------------------------------
// Discovery result type (used by the setup wizard)
// ---------------------------------------------------------------------------

export interface DiscoveryResult {
  growattFound: boolean;
  deviceSn: string | null;
  growattDeviceId: string | null;
  nordpoolFound: boolean;
  nordpoolArea: string | null;
  nordpoolConfigEntryId: string | null;
  sensors: Record<string, string>;
  missingSensors: string[];
  inverterType: string | null;
  detectedPhaseCount: number | null;
  currency: string | null;
  vatMultiplier: number | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isIntegrationFound(
  id: string,
  discovery: DiscoveryResult,
  sensors: Record<string, string>,
): boolean {
  if (id === 'growatt') return discovery.growattFound;
  if (id === 'nordpool') return discovery.nordpoolFound;
  if (id === 'phase_current') {
    return !!(sensors['current_l1'] || sensors['current_l2'] || sensors['current_l3']);
  }
  if (id === 'solar_forecast') {
    return !!(sensors['solar_forecast_today'] || sensors['solar_forecast_tomorrow']);
  }
  if (id === 'weather') return !!sensors['weather_entity'];
  if (id === 'consumption_forecast') return !!sensors['48h_avg_grid_import'];
  if (id === 'discharge_inhibit') return !!sensors['discharge_inhibit'];
  return false;
}

function integrationSensorCounts(
  integration: IntegrationDef,
  sensors: Record<string, string>,
): { configured: number; total: number; missingRequired: number } {
  let configured = 0;
  let total = 0;
  let missingRequired = 0;
  for (const group of integration.sensorGroups) {
    for (const s of group.sensors) {
      total++;
      if (sensors[s.key]) configured++;
      else if (s.required) missingRequired++;
    }
  }
  return { configured, total, missingRequired };
}

function sensorIcon(status: HealthStatus | null, hasValue: boolean) {
  if (!hasValue) return <AlertCircle className="h-3.5 w-3.5 text-gray-400 flex-shrink-0" />;
  if (status === 'ERROR') return <AlertCircle className="h-3.5 w-3.5 text-amber-500 flex-shrink-0" />;
  return <CheckCircle className="h-3.5 w-3.5 text-green-500 flex-shrink-0" />;
}

// Derive a status dot from discovery data (wizard mode)
function discoveryDot(intg: IntegrationDef, found: boolean, counts: ReturnType<typeof integrationSensorCounts>) {
  if (counts.total === 0) return null;
  if (counts.missingRequired > 0)
    return <span className="h-2 w-2 rounded-full bg-amber-500 flex-shrink-0" />;
  if (!found)
    return <span className="h-2 w-2 rounded-full bg-gray-300 dark:bg-gray-600 flex-shrink-0" />;
  return <span className="h-2 w-2 rounded-full bg-green-500 flex-shrink-0" />;
}

// Derive a status dot from health check data (settings mode)
function healthDot(
  intg: IntegrationDef,
  sensors: Record<string, string>,
  sensorStatus: Record<string, HealthStatus>,
) {
  const allSensors = intg.sensorGroups.flatMap(g => g.sensors);
  if (allSensors.length === 0) return null;
  const configured = allSensors.filter(s => sensors[s.key]);
  if (configured.length === 0)
    return <span className="h-2 w-2 rounded-full bg-gray-300 dark:bg-gray-600 flex-shrink-0" />;
  const statuses = configured.map(s => sensorStatus[s.key] ?? null);
  if (statuses.some(s => s === 'ERROR'))
    return <span className="h-2 w-2 rounded-full bg-red-500 flex-shrink-0" />;
  if (statuses.some(s => s === 'WARNING'))
    return <span className="h-2 w-2 rounded-full bg-amber-500 flex-shrink-0" />;
  return <span className="h-2 w-2 rounded-full bg-green-500 flex-shrink-0" />;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface Props {
  sensors: Record<string, string>;
  onChange: (sensors: Record<string, string>) => void;
  // Wizard mode — pass discovery result
  discovery?: DiscoveryResult | null;
  // Settings mode — pass health status map
  sensorStatus?: Record<string, HealthStatus>;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SensorConfigSection({ sensors, onChange, discovery, sensorStatus = {} }: Props) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const wizardMode = discovery != null;

  const toggleId = (id: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const visibleIntegrations = INTEGRATIONS.filter(intg => intg.sensorGroups.length > 0);

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100 dark:border-gray-700/60">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Sensor Entity IDs</h3>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
          Entity IDs for each integration. Expand a category to view and edit.
        </p>
      </div>
      <div className="divide-y divide-gray-100 dark:divide-gray-700/50">
        {visibleIntegrations.map(intg => {
          const counts = integrationSensorCounts(intg, sensors);
          const expanded = expandedIds.has(intg.id);
          const isFullyConfigured = counts.total > 0 && counts.configured === counts.total;

          const statusDot = wizardMode
            ? discoveryDot(intg, isIntegrationFound(intg.id, discovery, sensors), counts)
            : healthDot(intg, sensors, sensorStatus);

          return (
            <div key={intg.id}>
              <button
                type="button"
                onClick={() => toggleId(intg.id)}
                className="w-full flex items-center justify-between px-5 py-3.5 transition-colors text-left hover:bg-gray-50 dark:hover:bg-gray-700/40"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    {statusDot}
                    <span className="text-sm font-medium text-gray-900 dark:text-white">{intg.name}</span>
                    {intg.required && (
                      <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300">
                        REQUIRED
                      </span>
                    )}
                    {counts.missingRequired > 0 ? (
                      <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-orange-100 dark:bg-orange-900/30 text-orange-600 dark:text-orange-400">
                        {counts.missingRequired} required missing
                      </span>
                    ) : isFullyConfigured ? (
                      <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400">
                        {counts.configured}/{counts.total} configured
                      </span>
                    ) : (
                      <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400">
                        {counts.configured}/{counts.total} configured
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{intg.description}</p>
                </div>
                {expanded
                  ? <ChevronUp className="h-4 w-4 text-gray-400 flex-shrink-0" />
                  : <ChevronDown className="h-4 w-4 text-gray-400 flex-shrink-0" />}
              </button>

              {expanded && (
                <div className="border-t border-gray-100 dark:border-gray-700/50 divide-y divide-gray-100 dark:divide-gray-700/30">
                  {intg.sensorGroups.map(group => (
                    <div key={group.name} className="px-5 py-3 space-y-2">
                      <p className="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">
                        {group.name}
                      </p>
                      {group.sensors.map(s => {
                        const val = sensors[s.key] ?? '';
                        const isMissing = !val;
                        const status = sensorStatus[s.key] ?? null;
                        return (
                          <div
                            key={s.key}
                            className={`flex flex-col sm:flex-row sm:items-center gap-1 p-2 rounded-lg ${
                              isMissing && s.required
                                ? 'bg-orange-50 dark:bg-orange-900/10'
                                : isMissing
                                  ? 'bg-gray-50 dark:bg-gray-700/30'
                                  : 'bg-gray-50 dark:bg-gray-700/50'
                            }`}
                          >
                            <div className="flex items-center gap-1.5 sm:w-52 flex-shrink-0">
                              {sensorIcon(wizardMode ? null : status, !isMissing)}
                              <span className="text-xs font-medium text-gray-600 dark:text-gray-300">
                                {s.label}
                              </span>
                              {s.required && isMissing && (
                                <span className="text-[9px] text-orange-500 dark:text-orange-400 font-medium">*</span>
                              )}
                            </div>
                            <input
                              type="text"
                              value={val}
                              placeholder={isMissing ? 'Not detected — enter entity ID' : ''}
                              onChange={e => onChange({ ...sensors, [s.key]: e.target.value })}
                              className={`flex-1 text-xs px-2 py-1 rounded border font-mono ${
                                isMissing && s.required
                                  ? 'border-orange-300 dark:border-orange-600 bg-white dark:bg-gray-800 text-orange-700 dark:text-orange-300 placeholder-orange-400'
                                  : 'border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-200'
                              } focus:outline-none focus:ring-1 focus:ring-blue-400`}
                            />
                          </div>
                        );
                      })}
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
