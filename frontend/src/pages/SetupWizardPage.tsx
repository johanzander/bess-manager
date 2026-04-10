import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle, AlertCircle, ChevronRight, ChevronLeft, ChevronDown, Zap } from 'lucide-react';
import api from '../lib/api';
import { INTEGRATIONS } from '../lib/sensorDefinitions';
import type { IntegrationDef } from '../lib/sensorDefinitions';

/** Parse a numeric input value, returning `fallback` instead of NaN. */
const num = (v: string, fallback: number) => { const n = parseFloat(v); return Number.isNaN(n) ? fallback : n; };
const int = (v: string, fallback: number) => { const n = parseInt(v, 10); return Number.isNaN(n) ? fallback : n; };

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface BatteryForm {
  totalCapacity: number;
  minSoc: number;
  maxSoc: number;
  maxChargeDischargePower: number;
  cycleCost: number;
  minActionProfitThreshold: number;
}

interface HomeForm {
  currency: string;
  consumption: number;
  consumptionStrategy: string;
  maxFuseCurrent: number;
  voltage: number;
  safetyMarginFactor: number;
  phaseCount: number;
  powerMonitoringEnabled: boolean;
}

interface ElectricityForm {
  provider: string;
  markupRate: number;
  vatMultiplier: number;
  additionalCosts: number;
  taxReduction: number;
}

interface DiscoveryResult {
  growattFound: boolean;
  deviceSn: string | null;
  growattDeviceId: string | null;
  nordpoolFound: boolean;
  nordpoolArea: string | null;
  nordpoolConfigEntryId: string | null;
  sensors: Record<string, string>;
  missingSensors: string[];
  // Auto-detected hints
  inverterType: string | null;
  detectedPhaseCount: number | null;
  currency: string | null;
  vatMultiplier: number | null;
}



const STEPS = ['Scan', 'Review Sensors', 'Battery Setup', 'Home & Grid', 'Pricing', 'Done'];

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
  const [completing, setCompleting] = useState(false);
  const [completeError, setCompleteError] = useState<string | null>(null);
  const [expandedIntegrations, setExpandedIntegrations] = useState<Set<string>>(new Set());
  const [inverterType, setInverterType] = useState<string>('MIN');

  const [batteryForm, setBatteryForm] = useState<BatteryForm>({
    totalCapacity: 30.0,
    minSoc: 15,
    maxSoc: 95,
    maxChargeDischargePower: 15.0,
    cycleCost: 0.50,
    minActionProfitThreshold: 8.0,
  });

  const [homeForm, setHomeForm] = useState<HomeForm>({
    currency: 'SEK',
    consumption: 3.5,
    consumptionStrategy: 'sensor',
    maxFuseCurrent: 25,
    voltage: 230,
    safetyMarginFactor: 1.0,
    phaseCount: 3,
    powerMonitoringEnabled: true,
  });

  const [electricityForm, setElectricityForm] = useState<ElectricityForm>({
    provider: 'nordpool_official',
    markupRate: 0.08,
    vatMultiplier: 1.25,
    additionalCosts: 1.03,
    taxReduction: 0.0,
  });

  useEffect(() => {
    handleScan();
  }, []);

  const handleScan = async () => {
    setScanning(true);
    setScanError(null);
    setDiscovery(null);
    try {
      const res = await api.post('/api/setup/discover');
      const d: DiscoveryResult = res.data;
      setDiscovery(d);

      // Seed form defaults from auto-detected hints
      if (d.currency || d.vatMultiplier || d.detectedPhaseCount) {
        setHomeForm(f => ({
          ...f,
          ...(d.currency ? { currency: d.currency } : {}),
          ...(d.detectedPhaseCount ? { phaseCount: d.detectedPhaseCount } : {}),
        }));
        setElectricityForm(f => ({
          ...f,
          ...(d.vatMultiplier ? { vatMultiplier: d.vatMultiplier } : {}),
        }));
      }
      if (d.inverterType) {
        setInverterType(d.inverterType);
      }

      // Merge discovered sensors with empty entries for all known sensor keys
      const allSensors: Record<string, string> = {};
      for (const integration of INTEGRATIONS) {
        for (const group of integration.sensorGroups) {
          for (const s of group.sensors) {
            allSensors[s.key] = d.sensors[s.key] ?? '';
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
      setStep(2); // → Battery Setup
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Configuration failed';
      setConfirmError(message);
    } finally {
      setConfirming(false);
    }
  };

  const handleComplete = async () => {
    if (!discovery) return;
    setCompleting(true);
    setCompleteError(null);
    try {
      await api.post('/api/setup/complete', {
        sensors: editedSensors,
        nordpoolArea: discovery.nordpoolArea,
        nordpoolConfigEntryId: discovery.nordpoolConfigEntryId,
        growattDeviceId: discovery.growattDeviceId,
        // Battery
        totalCapacity: batteryForm.totalCapacity,
        minSoc: batteryForm.minSoc,
        maxSoc: batteryForm.maxSoc,
        maxChargeDischargePower: batteryForm.maxChargeDischargePower,
        cycleCost: batteryForm.cycleCost,
        minActionProfitThreshold: batteryForm.minActionProfitThreshold,
        // Home
        currency: homeForm.currency,
        consumption: homeForm.consumption,
        consumptionStrategy: homeForm.consumptionStrategy,
        maxFuseCurrent: homeForm.maxFuseCurrent,
        voltage: homeForm.voltage,
        safetyMarginFactor: homeForm.safetyMarginFactor,
        phaseCount: homeForm.phaseCount,
        powerMonitoringEnabled: homeForm.powerMonitoringEnabled,
        // Electricity
        provider: electricityForm.provider,
        markupRate: electricityForm.markupRate,
        vatMultiplier: electricityForm.vatMultiplier,
        additionalCosts: electricityForm.additionalCosts,
        taxReduction: electricityForm.taxReduction,
        // Inverter
        inverterType,
      });
      setStep(5); // → Done
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Setup failed';
      setCompleteError(message);
    } finally {
      setCompleting(false);
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

  const detectedBadge = (detected: boolean) =>
    detected ? (
      <span className="ml-1.5 text-xs font-medium text-green-600 dark:text-green-400">(auto-detected)</span>
    ) : null;

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
                <span>Next: Battery Setup</span>
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>

            {confirmError && (
              <p className="text-sm text-red-600 dark:text-red-400 text-center">{confirmError}</p>
            )}
          </div>
        )}

        {/* Step 2: Success */}
        {/* ── Step 2: Battery Setup ── */}
        {step === 2 && (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6 space-y-5">
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Battery Setup</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Configure your battery hardware specifications.</p>
            </div>

            {/* Inverter type */}
            <div className="space-y-1">
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                Inverter type
                {detectedBadge(discovery?.inverterType != null)}
              </span>
              <div className="flex space-x-4 pt-1">
                {(['MIN', 'SPH'] as const).map(t => (
                  <label key={t} className="flex items-center space-x-2 cursor-pointer">
                    <input
                      type="radio"
                      name="inverterType"
                      value={t}
                      checked={inverterType === t}
                      onChange={() => setInverterType(t)}
                      className="text-blue-500"
                    />
                    <span className="text-sm text-gray-700 dark:text-gray-300">{t}</span>
                  </label>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Total Capacity (kWh)</span>
                <input
                  type="number" min="1" step="0.1"
                  value={batteryForm.totalCapacity}
                  onChange={e => setBatteryForm(f => ({ ...f, totalCapacity: num(e.target.value, f.totalCapacity) }))}
                  className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Max Charge / Discharge Power (kW)</span>
                <input
                  type="number" min="0.1" step="0.1"
                  value={batteryForm.maxChargeDischargePower}
                  onChange={e => setBatteryForm(f => ({ ...f, maxChargeDischargePower: num(e.target.value, f.maxChargeDischargePower) }))}
                  className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Min State of Charge (%)</span>
                <input
                  type="number" min="0" max="100" step="1"
                  value={batteryForm.minSoc}
                  onChange={e => setBatteryForm(f => ({ ...f, minSoc: int(e.target.value, f.minSoc) }))}
                  className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Max State of Charge (%)</span>
                <input
                  type="number" min="0" max="100" step="1"
                  value={batteryForm.maxSoc}
                  onChange={e => setBatteryForm(f => ({ ...f, maxSoc: int(e.target.value, f.maxSoc) }))}
                  className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Cycle Cost (per kWh cycled)</span>
                <input
                  type="number" min="0" step="0.01"
                  value={batteryForm.cycleCost}
                  onChange={e => setBatteryForm(f => ({ ...f, cycleCost: num(e.target.value, f.cycleCost) }))}
                  className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Min Action Profit Threshold</span>
                <input
                  type="number" min="0" step="0.1"
                  value={batteryForm.minActionProfitThreshold}
                  onChange={e => setBatteryForm(f => ({ ...f, minActionProfitThreshold: num(e.target.value, f.minActionProfitThreshold) }))}
                  className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </label>
            </div>

            <div className="flex justify-between pt-2">
              <button
                onClick={() => setStep(1)}
                className="flex items-center space-x-1 px-4 py-2 text-gray-600 dark:text-gray-300 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700"
              >
                <ChevronLeft className="h-4 w-4" />
                <span>Back</span>
              </button>
              <button
                onClick={() => setStep(3)}
                className="flex items-center space-x-2 px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 font-medium"
              >
                <span>Next: Home &amp; Grid</span>
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 3: Home & Grid ── */}
        {step === 3 && (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6 space-y-5">
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Home &amp; Grid</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Configure your home electrical setup.</p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  Currency
                  {detectedBadge(discovery?.currency != null)}
                </span>
                <select
                  value={homeForm.currency}
                  onChange={e => setHomeForm(f => ({ ...f, currency: e.target.value }))}
                  className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {['SEK', 'NOK', 'DKK', 'EUR', 'GBP'].map(c => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </label>

              <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Default Hourly Consumption (kWh)</span>
                <input
                  type="number" min="0" step="0.1"
                  value={homeForm.consumption}
                  onChange={e => setHomeForm(f => ({ ...f, consumption: num(e.target.value, f.consumption) }))}
                  className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Fuse Current (A)</span>
                <input
                  type="number" min="1" step="1"
                  value={homeForm.maxFuseCurrent}
                  onChange={e => setHomeForm(f => ({ ...f, maxFuseCurrent: int(e.target.value, f.maxFuseCurrent) }))}
                  className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Voltage (V)</span>
                <input
                  type="number" min="100" step="1"
                  value={homeForm.voltage}
                  onChange={e => setHomeForm(f => ({ ...f, voltage: int(e.target.value, f.voltage) }))}
                  className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Safety Margin Factor (0–1)</span>
                <input
                  type="number" min="0" max="1" step="0.01"
                  value={homeForm.safetyMarginFactor}
                  onChange={e => setHomeForm(f => ({ ...f, safetyMarginFactor: num(e.target.value, f.safetyMarginFactor) }))}
                  className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </label>
            </div>

            <div className="space-y-3">
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                Phases
                {detectedBadge(discovery?.detectedPhaseCount != null)}
              </span>
              <div className="flex space-x-4">
                {[1, 3].map(n => (
                  <label key={n} className="flex items-center space-x-2 cursor-pointer">
                    <input
                      type="radio"
                      name="phaseCount"
                      value={n}
                      checked={homeForm.phaseCount === n}
                      onChange={() => setHomeForm(f => ({ ...f, phaseCount: n }))}
                      className="text-blue-500"
                    />
                    <span className="text-sm text-gray-700 dark:text-gray-300">{n}-phase</span>
                  </label>
                ))}
              </div>
            </div>

            <div className="space-y-3">
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Consumption Strategy</span>
              <div className="flex flex-col space-y-2">
                {(['sensor', 'fixed', 'influxdb_7d_avg'] as const).map(s => (
                  <label key={s} className="flex items-center space-x-2 cursor-pointer">
                    <input
                      type="radio"
                      name="consumptionStrategy"
                      value={s}
                      checked={homeForm.consumptionStrategy === s}
                      onChange={() => setHomeForm(f => ({ ...f, consumptionStrategy: s }))}
                      className="text-blue-500"
                    />
                    <span className="text-sm text-gray-700 dark:text-gray-300">{s}</span>
                  </label>
                ))}
              </div>
            </div>

            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Power Monitoring Enabled</span>
              <button
                type="button"
                onClick={() => setHomeForm(f => ({ ...f, powerMonitoringEnabled: !f.powerMonitoringEnabled }))}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 ${homeForm.powerMonitoringEnabled ? 'bg-blue-500' : 'bg-gray-300 dark:bg-gray-600'}`}
              >
                <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${homeForm.powerMonitoringEnabled ? 'translate-x-6' : 'translate-x-1'}`} />
              </button>
            </div>

            <div className="flex justify-between pt-2">
              <button
                onClick={() => setStep(2)}
                className="flex items-center space-x-1 px-4 py-2 text-gray-600 dark:text-gray-300 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700"
              >
                <ChevronLeft className="h-4 w-4" />
                <span>Back</span>
              </button>
              <button
                onClick={() => setStep(4)}
                className="flex items-center space-x-2 px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 font-medium"
              >
                <span>Next: Pricing</span>
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 4: Electricity Pricing ── */}
        {step === 4 && (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6 space-y-5">
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Electricity Pricing</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Configure your electricity price source and cost parameters.</p>
            </div>

            {discovery?.vatMultiplier != null && (
              <div className="rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-700 px-4 py-2 text-xs text-green-800 dark:text-green-300">
                VAT multiplier pre-filled from detected Nordpool area ({discovery.nordpoolArea}).
              </div>
            )}

            <div className="space-y-3">
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Price Provider</span>
              <div className="flex flex-col space-y-2">
                {([
                  { value: 'nordpool_official', label: 'Nordpool (official integration)' },
                  { value: 'nordpool', label: 'Nordpool (custom integration)' },
                  { value: 'octopus', label: 'Octopus Energy' },
                ] as const).map(opt => (
                  <label key={opt.value} className="flex items-center space-x-2 cursor-pointer">
                    <input
                      type="radio"
                      name="provider"
                      value={opt.value}
                      checked={electricityForm.provider === opt.value}
                      onChange={() => setElectricityForm(f => ({ ...f, provider: opt.value }))}
                      className="text-blue-500"
                    />
                    <span className="text-sm text-gray-700 dark:text-gray-300">{opt.label}</span>
                  </label>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Markup Rate (per kWh)</span>
                <input
                  type="number" min="0" step="0.001"
                  value={electricityForm.markupRate}
                  onChange={e => setElectricityForm(f => ({ ...f, markupRate: num(e.target.value, f.markupRate) }))}
                  className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">VAT Multiplier (e.g. 1.25 = 25%)</span>
                <input
                  type="number" min="1" step="0.01"
                  value={electricityForm.vatMultiplier}
                  onChange={e => setElectricityForm(f => ({ ...f, vatMultiplier: num(e.target.value, f.vatMultiplier) }))}
                  className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Additional Costs (per kWh)</span>
                <input
                  type="number" min="0" step="0.001"
                  value={electricityForm.additionalCosts}
                  onChange={e => setElectricityForm(f => ({ ...f, additionalCosts: num(e.target.value, f.additionalCosts) }))}
                  className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Tax Reduction (per kWh)</span>
                <input
                  type="number" min="0" step="0.001"
                  value={electricityForm.taxReduction}
                  onChange={e => setElectricityForm(f => ({ ...f, taxReduction: num(e.target.value, f.taxReduction) }))}
                  className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </label>
            </div>

            {completeError && (
              <p className="text-sm text-red-600 dark:text-red-400">{completeError}</p>
            )}
            <div className="flex justify-between pt-2">
              <button
                onClick={() => setStep(3)}
                className="flex items-center space-x-1 px-4 py-2 text-gray-600 dark:text-gray-300 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700"
              >
                <ChevronLeft className="h-4 w-4" />
                <span>Back</span>
              </button>
              <button
                onClick={handleComplete}
                disabled={completing}
                className="flex items-center space-x-2 px-6 py-2 bg-green-500 text-white rounded-lg hover:bg-green-600 font-medium disabled:opacity-60"
              >
                {completing ? <div className="h-4 w-4 border-2 border-white rounded-full border-t-transparent animate-spin" /> : null}
                <span>Finish Setup</span>
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 5: Done ── */}
        {step === 5 && (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
            <div className="text-center py-6">
              <CheckCircle className="h-16 w-16 text-green-500 mx-auto mb-4" />
              <h2 className="text-xl font-bold text-gray-900 dark:text-white">Setup Complete!</h2>
              <p className="text-gray-600 dark:text-gray-400 mt-2">
                BESS Manager is configured and ready to optimize your battery.
              </p>
            </div>

            <div className="mt-2 rounded-lg bg-gray-50 dark:bg-gray-700 p-4 space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">Battery capacity</span>
                <span className="font-medium text-gray-900 dark:text-white">{batteryForm.totalCapacity} kWh</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">SOC range</span>
                <span className="font-medium text-gray-900 dark:text-white">{batteryForm.minSoc}% – {batteryForm.maxSoc}%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">Max power</span>
                <span className="font-medium text-gray-900 dark:text-white">{batteryForm.maxChargeDischargePower} kW</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">Inverter type</span>
                <span className="font-medium text-gray-900 dark:text-white">{inverterType}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">Currency</span>
                <span className="font-medium text-gray-900 dark:text-white">{homeForm.currency}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">Price provider</span>
                <span className="font-medium text-gray-900 dark:text-white">{electricityForm.provider}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">VAT multiplier</span>
                <span className="font-medium text-gray-900 dark:text-white">{electricityForm.vatMultiplier}</span>
              </div>
            </div>

            <button
              onClick={() => navigate('/', { replace: true })}
              className="mt-6 w-full px-8 py-3 bg-green-500 text-white rounded-lg hover:bg-green-600 font-semibold text-base"
            >
              Go to Dashboard
            </button>
          </div>
        )}

        <p className="text-center mt-4 text-xs text-gray-400 dark:text-gray-500">
          Settings can be updated at any time via the Settings page or Auto-Configure on the System Health page.
        </p>
      </div>
    </div>
  );
};

export default SetupWizardPage;
