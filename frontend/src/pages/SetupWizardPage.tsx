import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle, AlertCircle, ChevronRight, ChevronLeft, ChevronDown, Zap } from 'lucide-react';
import api from '../lib/api';

interface DiscoveryResult {
  growattFound: boolean;
  deviceSn: string | null;
  growattDeviceId: string | null;
  nordpoolFound: boolean;
  nordpoolArea: string | null;
  nordpoolConfigEntryId: string | null;
  sensors: Record<string, string>;
  missingSensors: string[];
}

interface SensorDef {
  key: string;
  label: string;
  required: boolean;
}

interface SensorGroup {
  name: string;
  sensors: SensorDef[];
}

interface IntegrationDef {
  id: string;
  name: string;
  required: boolean;
  description: string;
  sensorGroups: SensorGroup[];
}

const INTEGRATIONS: IntegrationDef[] = [
  {
    id: 'growatt',
    name: 'Growatt Server',
    required: true,
    description: 'Battery inverter control and monitoring',
    sensorGroups: [
      {
        name: 'Battery Control',
        sensors: [
          { key: 'battery_soc', label: 'State of Charge (SOC)', required: true },
          { key: 'battery_charge_power', label: 'Charging Power', required: true },
          { key: 'battery_discharge_power', label: 'Discharging Power', required: true },
          { key: 'battery_charge_stop_soc', label: 'Charge Stop SOC', required: false },
          { key: 'battery_discharge_stop_soc', label: 'Discharge Stop SOC', required: false },
          { key: 'battery_charging_power_rate', label: 'Charging Power Rate', required: false },
          { key: 'battery_discharging_power_rate', label: 'Discharging Power Rate', required: false },
          { key: 'grid_charge', label: 'Grid Charge Enable', required: false },
        ],
      },
      {
        name: 'Power Monitoring',
        sensors: [
          { key: 'pv_power', label: 'Solar PV Power', required: true },
          { key: 'local_load_power', label: 'Local Load Power', required: true },
          { key: 'import_power', label: 'Grid Import Power', required: true },
          { key: 'export_power', label: 'Grid Export Power', required: true },
        ],
      },
      {
        name: 'Lifetime Energy Totals',
        sensors: [
          { key: 'lifetime_battery_charged', label: 'Total Battery Charged', required: false },
          { key: 'lifetime_battery_discharged', label: 'Total Battery Discharged', required: false },
          { key: 'lifetime_solar_energy', label: 'Total Solar Energy', required: false },
          { key: 'lifetime_export_to_grid', label: 'Total Export to Grid', required: false },
          { key: 'lifetime_import_from_grid', label: 'Total Import from Grid', required: false },
          { key: 'lifetime_load_consumption', label: 'Total Load Consumption', required: false },
          { key: 'lifetime_system_production', label: 'Total System Production', required: false },
          { key: 'lifetime_self_consumption', label: 'Total Self Consumption', required: false },
        ],
      },
    ],
  },
  {
    id: 'nordpool',
    name: 'Nord Pool Official',
    required: true,
    description: 'Electricity spot price data for optimization',
    sensorGroups: [],
  },
  {
    id: 'solar_forecast',
    name: 'Solar Forecast (Solcast)',
    required: false,
    description: 'PV production forecast for planning charge/discharge strategy',
    sensorGroups: [
      {
        name: 'Daily Forecasts',
        sensors: [
          { key: 'solar_forecast_today', label: 'Forecast Today (kWh)', required: false },
          { key: 'solar_forecast_tomorrow', label: 'Forecast Tomorrow (kWh)', required: false },
        ],
      },
    ],
  },
  {
    id: 'consumption_forecast',
    name: 'Consumption Forecast',
    required: false,
    description: '48-hour average grid import for load prediction',
    sensorGroups: [
      {
        name: 'Consumption',
        sensors: [
          { key: '48h_avg_grid_import', label: '48h Avg Grid Import', required: false },
        ],
      },
    ],
  },
  {
    id: 'phase_current',
    name: 'Phase Current Monitoring',
    required: false,
    description: 'Three-phase current sensors for grid fuse protection',
    sensorGroups: [
      {
        name: 'Phase Currents',
        sensors: [
          { key: 'current_l1', label: 'Phase L1 Current', required: false },
          { key: 'current_l2', label: 'Phase L2 Current', required: false },
          { key: 'current_l3', label: 'Phase L3 Current', required: false },
        ],
      },
    ],
  },
  {
    id: 'ev_metering',
    name: 'EV Energy Metering',
    required: false,
    description: 'EV charger energy sensor for consumption analytics',
    sensorGroups: [
      {
        name: 'EV Charger',
        sensors: [
          { key: 'ev_energy_meter', label: 'Lifetime EV Energy (kWh)', required: false },
        ],
      },
    ],
  },
  {
    id: 'discharge_inhibit',
    name: 'Discharge Inhibit',
    required: false,
    description: 'Binary sensor to prevent battery discharge (e.g. Tibber/Zaptec EV charging)',
    sensorGroups: [
      {
        name: 'Constraint',
        sensors: [
          { key: 'discharge_inhibit', label: 'Discharge Inhibit Sensor', required: false },
        ],
      },
    ],
  },
  {
    id: 'weather',
    name: 'Weather Integration',
    required: false,
    description: 'Temperature forecast for LFP battery cold weather derating',
    sensorGroups: [
      {
        name: 'Weather Entity',
        sensors: [
          { key: 'weather_entity', label: 'HA Weather Entity', required: false },
        ],
      },
    ],
  },
];

const STEPS = ['Scan', 'Review Configuration', 'Done'];

/** Count configured/total sensors for an integration */
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
      if (sensors[s.key]) {
        configured++;
      } else if (s.required) {
        missingRequired++;
      }
    }
  }
  return { configured, total, missingRequired };
}

/** Check if an integration was detected */
function isIntegrationFound(id: string, discovery: DiscoveryResult, sensors: Record<string, string>): boolean {
  if (id === 'growatt') return discovery.growattFound;
  if (id === 'nordpool') return discovery.nordpoolFound;
  if (id === 'phase_current') {
    return !!(sensors['current_l1'] || sensors['current_l2'] || sensors['current_l3']);
  }
  if (id === 'solar_forecast') {
    return !!(sensors['solar_forecast_today'] || sensors['solar_forecast_tomorrow']);
  }
  if (id === 'weather') {
    return !!sensors['weather_entity'];
  }
  if (id === 'ev_metering') {
    return !!sensors['ev_energy_meter'];
  }
  if (id === 'consumption_forecast') {
    return !!sensors['48h_avg_grid_import'];
  }
  if (id === 'discharge_inhibit') {
    return !!sensors['discharge_inhibit'];
  }
  return false;
}

const SetupWizardPage: React.FC = () => {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [discovery, setDiscovery] = useState<DiscoveryResult | null>(null);
  const [editedSensors, setEditedSensors] = useState<Record<string, string>>({});
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [expandedIntegrations, setExpandedIntegrations] = useState<Set<string>>(new Set());

  useEffect(() => {
    handleScan();
  }, []);

  const handleScan = async () => {
    setScanning(true);
    setScanError(null);
    setDiscovery(null);
    try {
      const res = await api.post('/api/setup/discover');
      setDiscovery(res.data);
      // Merge discovered sensors with empty entries for all known sensor keys
      const allSensors: Record<string, string> = {};
      for (const integration of INTEGRATIONS) {
        for (const group of integration.sensorGroups) {
          for (const s of group.sensors) {
            allSensors[s.key] = res.data.sensors[s.key] ?? '';
          }
        }
      }
      setEditedSensors(allSensors);
      setExpandedIntegrations(new Set());
      setStep(1);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Discovery failed';
      setScanError(message);
    } finally {
      setScanning(false);
    }
  };

  const handleConfirm = async () => {
    if (!discovery) return;
    setConfirming(true);
    setConfirmError(null);
    try {
      await api.post('/api/setup/confirm', {
        sensors: editedSensors,
        nordpool_area: discovery.nordpoolArea,
        nordpool_config_entry_id: discovery.nordpoolConfigEntryId,
        growatt_device_id: discovery.growattDeviceId,
      });
      setStep(2);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Configuration failed';
      setConfirmError(message);
    } finally {
      setConfirming(false);
    }
  };

  const toggleIntegration = (id: string) => {
    setExpandedIntegrations(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const hasAllRequired = () => {
    for (const integration of INTEGRATIONS) {
      for (const group of integration.sensorGroups) {
        for (const s of group.sensors) {
          if (s.required && !editedSensors[s.key]) return false;
        }
      }
    }
    return true;
  };

  /** Render metadata row for an integration */
  const renderMetadata = (integration: IntegrationDef) => {
    if (!discovery) return null;
    if (integration.id === 'growatt') {
      return (
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-gray-500 dark:text-gray-400">
          <span>SN: <span className="font-mono">{discovery.deviceSn ?? 'unknown'}</span></span>
          {discovery.growattDeviceId && (
            <span>Device ID: <span className="font-mono">{discovery.growattDeviceId}</span></span>
          )}
        </div>
      );
    }
    if (integration.id === 'nordpool') {
      return (
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-gray-500 dark:text-gray-400">
          {discovery.nordpoolArea && (
            <span>Price Area: <span className="font-semibold">{discovery.nordpoolArea}</span></span>
          )}
          {discovery.nordpoolConfigEntryId && (
            <span>Config Entry: <span className="font-mono">{discovery.nordpoolConfigEntryId}</span></span>
          )}
        </div>
      );
    }
    return null;
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex flex-col items-center justify-center p-6">
      <div className="w-full max-w-3xl">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="flex justify-center mb-3">
            <Zap className="h-10 w-10 text-blue-500" />
          </div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">BESS Auto-Configuration</h1>
          <p className="mt-2 text-gray-600 dark:text-gray-400">
            Detecting integrations and mapping sensor entity IDs
          </p>
        </div>

        {/* Step indicator */}
        <div className="flex items-center justify-center mb-8 space-x-2">
          {STEPS.map((label, idx) => (
            <React.Fragment key={label}>
              <div className="flex items-center space-x-1">
                <div className={`w-7 h-7 rounded-full flex items-center justify-center text-sm font-semibold
                  ${idx < step ? 'bg-green-500 text-white' :
                    idx === step ? 'bg-blue-500 text-white' :
                    'bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400'}`}>
                  {idx < step ? <CheckCircle className="h-4 w-4" /> : idx + 1}
                </div>
                <span className={`hidden sm:inline text-sm ${idx === step ? 'font-semibold text-gray-900 dark:text-white' : 'text-gray-500 dark:text-gray-400'}`}>
                  {label}
                </span>
              </div>
              {idx < STEPS.length - 1 && (
                <ChevronRight className="h-4 w-4 text-gray-400 flex-shrink-0" />
              )}
            </React.Fragment>
          ))}
        </div>

        {/* Step 0: Scanning */}
        {step === 0 && (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
            <div className="text-center py-8">
              {scanning ? (
                <>
                  <div className="h-12 w-12 border-2 border-blue-500 rounded-full border-t-transparent animate-spin mx-auto mb-4" />
                  <p className="text-lg font-medium text-gray-900 dark:text-white">Scanning Home Assistant…</p>
                  <p className="text-gray-500 dark:text-gray-400 mt-1">Querying REST API and WebSocket for integrations</p>
                </>
              ) : scanError ? (
                <>
                  <AlertCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
                  <p className="text-lg font-medium text-gray-900 dark:text-white">Discovery failed</p>
                  <p className="text-red-500 mt-1 text-sm">{scanError}</p>
                  <button onClick={handleScan} className="mt-4 px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 font-medium">
                    Retry
                  </button>
                </>
              ) : null}
            </div>
          </div>
        )}

        {/* Step 1: Integration Review */}
        {step === 1 && discovery && (
          <div className="space-y-3">
            {INTEGRATIONS.map(integration => {
              const found = isIntegrationFound(integration.id, discovery, editedSensors);
              const counts = integrationSensorCounts(integration, editedSensors);
              const expanded = expandedIntegrations.has(integration.id);
              const hasSensors = integration.sensorGroups.length > 0;

              return (
                <div key={integration.id} className="bg-white dark:bg-gray-800 rounded-xl shadow-lg overflow-hidden">
                  {/* Integration header */}
                  <button
                    type="button"
                    onClick={() => toggleIntegration(integration.id)}
                    className="w-full px-5 py-4 flex items-start gap-3 text-left cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-750"
                  >
                    {/* Status icon */}
                    {found
                      ? <CheckCircle className="h-5 w-5 text-green-500 flex-shrink-0 mt-0.5" />
                      : <AlertCircle className="h-5 w-5 text-orange-400 flex-shrink-0 mt-0.5" />}

                    {/* Name + description + metadata */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-gray-900 dark:text-white">{integration.name}</span>
                        <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
                          integration.required
                            ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300'
                            : 'bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400'
                        }`}>
                          {integration.required ? 'REQUIRED' : 'OPTIONAL'}
                        </span>
                        {!found && (
                          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-orange-100 dark:bg-orange-900/30 text-orange-600 dark:text-orange-400">
                            NOT FOUND
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{integration.description}</p>
                      {found && renderMetadata(integration)}
                    </div>

                    {/* Sensor count + expand chevron */}
                    <div className="flex items-center gap-2 flex-shrink-0 mt-0.5">
                      {hasSensors && (
                        <span className={`text-xs font-medium ${
                          counts.missingRequired > 0
                            ? 'text-orange-500'
                            : counts.configured === counts.total
                              ? 'text-green-600 dark:text-green-400'
                              : 'text-gray-500 dark:text-gray-400'
                        }`}>
                          {counts.configured}/{counts.total}
                        </span>
                      )}
                      <ChevronDown className={`h-4 w-4 text-gray-400 transition-transform ${expanded ? 'rotate-180' : ''}`} />
                    </div>
                  </button>

                  {/* Expanded detail */}
                  {expanded && hasSensors && (
                    <div className="border-t border-gray-100 dark:border-gray-700 px-5 pb-4">
                      {integration.sensorGroups.map(group => {
                        const groupConfigured = group.sensors.filter(s => editedSensors[s.key]).length;
                        return (
                          <div key={group.name} className="mt-3">
                            <div className="flex items-center gap-2 mb-2">
                              <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
                                {group.name}
                              </h4>
                              <span className="text-[10px] text-gray-400 dark:text-gray-500">
                                {groupConfigured}/{group.sensors.length}
                              </span>
                            </div>
                            <div className="space-y-1.5">
                              {group.sensors.map(sensor => {
                                const value = editedSensors[sensor.key] ?? '';
                                const isMissing = !value;
                                return (
                                  <div key={sensor.key} className={`flex flex-col sm:flex-row sm:items-center gap-1 p-2 rounded-lg ${
                                    isMissing && sensor.required
                                      ? 'bg-orange-50 dark:bg-orange-900/10'
                                      : isMissing
                                        ? 'bg-gray-50 dark:bg-gray-700/30'
                                        : 'bg-gray-50 dark:bg-gray-700/50'
                                  }`}>
                                    <div className="flex items-center gap-1.5 sm:w-52 flex-shrink-0">
                                      {isMissing
                                        ? <AlertCircle className="h-3 w-3 text-orange-400 flex-shrink-0" />
                                        : <CheckCircle className="h-3 w-3 text-green-500 flex-shrink-0" />}
                                      <label className="text-xs font-medium text-gray-600 dark:text-gray-300">
                                        {sensor.label}
                                      </label>
                                      {sensor.required && (
                                        <span className="text-[9px] text-orange-500 dark:text-orange-400 font-medium">*</span>
                                      )}
                                    </div>
                                    <input
                                      type="text"
                                      value={value}
                                      onChange={e => setEditedSensors(prev => ({ ...prev, [sensor.key]: e.target.value }))}
                                      placeholder={isMissing ? 'Not detected — enter entity ID' : ''}
                                      className={`flex-1 text-xs px-2 py-1 rounded border font-mono
                                        ${isMissing && sensor.required
                                          ? 'border-orange-300 dark:border-orange-600 bg-white dark:bg-gray-800 text-orange-700 dark:text-orange-300 placeholder-orange-400'
                                          : 'border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-200'}
                                        focus:outline-none focus:ring-1 focus:ring-blue-400`}
                                    />
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}

            {/* Required sensors warning */}
            {!hasAllRequired() && (
              <div className="p-3 bg-orange-50 dark:bg-orange-900/20 border border-orange-200 dark:border-orange-800 rounded-lg text-sm text-orange-700 dark:text-orange-300">
                Some required sensors (marked with <span className="font-semibold">*</span>) are missing. Expand the integration to configure them manually.
              </div>
            )}

            {/* Action buttons */}
            <div className="flex justify-between pt-2">
              <button
                onClick={handleScan}
                className="flex items-center space-x-1 px-4 py-2 text-gray-600 dark:text-gray-300 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700"
              >
                <ChevronLeft className="h-4 w-4" />
                <span>Re-scan</span>
              </button>
              <button
                onClick={handleConfirm}
                disabled={confirming}
                className="flex items-center space-x-2 px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 font-medium disabled:opacity-60"
              >
                {confirming ? <div className="h-4 w-4 border-2 border-white rounded-full border-t-transparent animate-spin" /> : null}
                <span>Apply Configuration</span>
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>

            {confirmError && (
              <p className="text-sm text-red-600 dark:text-red-400 text-center">{confirmError}</p>
            )}
          </div>
        )}

        {/* Step 2: Success */}
        {step === 2 && (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
            <div className="text-center py-8">
              <CheckCircle className="h-16 w-16 text-green-500 mx-auto mb-4" />
              <h2 className="text-xl font-bold text-gray-900 dark:text-white">Configuration Applied!</h2>
              <p className="text-gray-600 dark:text-gray-400 mt-2">
                BESS Manager has been configured with your discovered sensors.
                The system will begin operating immediately.
              </p>
              <button
                onClick={() => navigate('/', { replace: true })}
                className="mt-6 px-8 py-3 bg-green-500 text-white rounded-lg hover:bg-green-600 font-semibold text-lg"
              >
                Go to Dashboard
              </button>
            </div>
          </div>
        )}

        <p className="text-center mt-4 text-xs text-gray-400 dark:text-gray-500">
          Sensors can be reconfigured at any time via Auto-Configure on the System Health page.
        </p>
      </div>
    </div>
  );
};

export default SetupWizardPage;
