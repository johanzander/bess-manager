import React, { useState, useEffect, useCallback } from 'react';
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
  currency: string;
  area: string;
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



const STEPS = ['Scan', 'Review Sensors', 'Electricity Pricing', 'Battery', 'Home', 'Done'];

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
    currency: 'SEK',
    area: '',
    markupRate: 0.08,
    vatMultiplier: 1.25,
    additionalCosts: 1.03,
    taxReduction: 0.0,
  });

  const handleScan = useCallback(async () => {
    setScanning(true);
    setScanError(null);
    setDiscovery(null);
    try {
      const res = await api.post('/api/setup/discover');
      const d: DiscoveryResult = res.data;
      setDiscovery(d);

      // Seed form defaults from auto-detected hints
      if (d.detectedPhaseCount) {
        setHomeForm(f => ({ ...f, phaseCount: d.detectedPhaseCount! }));
      }
      setElectricityForm(f => ({
        ...f,
        ...(d.currency ? { currency: d.currency } : {}),
        ...(d.nordpoolArea ? { area: d.nordpoolArea } : {}),
        ...(d.vatMultiplier ? { vatMultiplier: d.vatMultiplier } : {}),
      }));
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
  }, []);

  useEffect(() => {
    // Load existing settings first so re-running the wizard preserves user config,
    // then run the sensor scan. Sequencing via .finally() ensures the scan never
    // overwrites the loaded values (scan seeds only auto-detected hints).
    api.get('/api/settings/all').then(res => {
      const s = res.data;
      const bat = s.battery ?? {};
      const home = s.home ?? {};
      const elec = s.electricityPrice ?? {};
      const ep = s.energyProvider ?? {};
      const inv = s.growatt ?? {};

      setBatteryForm(f => ({
        ...f,
        totalCapacity:            bat.totalCapacity            ?? f.totalCapacity,
        minSoc:                   bat.minSoc                   ?? f.minSoc,
        maxSoc:                   bat.maxSoc                   ?? f.maxSoc,
        maxChargeDischargePower:  bat.maxChargePowerKw         ?? f.maxChargeDischargePower,
        cycleCost:                bat.cycleCostPerKwh          ?? f.cycleCost,
        minActionProfitThreshold: bat.minActionProfitThreshold ?? f.minActionProfitThreshold,
      }));
      setHomeForm(f => ({
        ...f,
        consumption:           home.defaultHourly          ?? f.consumption,
        consumptionStrategy:   home.consumptionStrategy    ?? f.consumptionStrategy,
        maxFuseCurrent:        home.maxFuseCurrent         ?? f.maxFuseCurrent,
        voltage:               home.voltage                ?? f.voltage,
        safetyMarginFactor:    home.safetyMargin           ?? f.safetyMarginFactor,
        phaseCount:            home.phaseCount             ?? f.phaseCount,
        powerMonitoringEnabled: home.powerMonitoringEnabled ?? f.powerMonitoringEnabled,
      }));
      setElectricityForm(f => ({
        ...f,
        provider:        ep.provider          ?? f.provider,
        currency:        home.currency        ?? f.currency,
        area:            elec.area            ?? f.area,
        markupRate:      elec.markupRate      ?? f.markupRate,
        vatMultiplier:   elec.vatMultiplier   ?? f.vatMultiplier,
        additionalCosts: elec.additionalCosts ?? f.additionalCosts,
        taxReduction:    elec.taxReduction    ?? f.taxReduction,
      }));
      if (inv.inverterType) setInverterType(inv.inverterType);
    }).catch((err: unknown) => {
      // A 404 means first-time setup with no existing settings — defaults are fine.
      // Any other error is unexpected and should be surfaced for debugging.
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status !== 404) {
        console.error('Failed to load existing settings:', err);
      }
    }).finally(() => {
      handleScan();
    });
  }, [handleScan]);

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
        nordpoolArea: electricityForm.area || discovery.nordpoolArea,
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
        currency: electricityForm.currency,
        consumption: homeForm.consumption,
        consumptionStrategy: homeForm.consumptionStrategy,
        maxFuseCurrent: homeForm.maxFuseCurrent,
        voltage: homeForm.voltage,
        safetyMarginFactor: homeForm.safetyMarginFactor,
        phaseCount: homeForm.phaseCount,
        powerMonitoringEnabled: homeForm.powerMonitoringEnabled,
        // Electricity
        area: electricityForm.area || discovery.nordpoolArea,
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
                <span>Next: Electricity Pricing</span>
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>

            {confirmError && (
              <p className="text-sm text-red-600 dark:text-red-400 text-center">{confirmError}</p>
            )}
          </div>
        )}

        {/* ── Step 3: Battery ── */}
        {step === 3 && (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6 space-y-5">
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Battery</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Your inverter model and battery hardware specifications. These values are used by the optimizer to plan charge and discharge schedules.</p>
            </div>

            {/* Inverter type */}
            <div className="space-y-1">
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                Inverter type {detectedBadge(discovery?.inverterType != null)}
              </span>
              <div className="flex space-x-4 pt-1">
                {([
                  { value: 'MIN', label: 'MIN (AC-coupled)' },
                  { value: 'SPH', label: 'SPH (DC-coupled)' },
                ] as const).map(t => (
                  <label key={t.value} className="flex items-center space-x-2 cursor-pointer">
                    <input type="radio" name="inverterType" value={t.value}
                      checked={inverterType === t.value}
                      onChange={() => setInverterType(t.value)}
                      className="text-blue-500" />
                    <span className="text-sm text-gray-700 dark:text-gray-300">{t.label}</span>
                  </label>
                ))}
              </div>
            </div>

            {/* Capacity */}
            <div className="space-y-1">
              <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Total Capacity (kWh)</span>
                <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">The total usable energy storage of your battery. Set this to the nameplate capacity of your battery system.</p>
                <input type="number" min="1" step="0.1" value={batteryForm.totalCapacity}
                  onChange={e => setBatteryForm(f => ({ ...f, totalCapacity: num(e.target.value, f.totalCapacity) }))}
                  className="block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </label>
            </div>

            {/* Power */}
            <div className="space-y-1">
              <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Max Charge / Discharge Power (kW)</span>
                <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Maximum power the optimizer may use. Calculate from your battery's C-rate — e.g. 30 kWh × 0.5C = 15 kW.</p>
                <input type="number" min="0.1" step="0.1" value={batteryForm.maxChargeDischargePower}
                  onChange={e => setBatteryForm(f => ({ ...f, maxChargeDischargePower: num(e.target.value, f.maxChargeDischargePower) }))}
                  className="block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </label>
            </div>

            {/* SOC limits */}
            <div className="space-y-1">
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">SOC Limits (%)</span>
              <p className="text-xs text-gray-500 dark:text-gray-400">The operating range the optimizer will stay within. These values are synced to the Growatt inverter. Typical values: Min 15%, Max 95%.</p>
              <div className="grid grid-cols-2 gap-4 pt-1">
                <label className="block">
                  <span className="text-xs font-medium text-gray-600 dark:text-gray-400">Min SOC</span>
                  <input type="number" min="0" max="100" step="1" value={batteryForm.minSoc}
                    onChange={e => setBatteryForm(f => ({ ...f, minSoc: int(e.target.value, f.minSoc) }))}
                    className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </label>
                <label className="block">
                  <span className="text-xs font-medium text-gray-600 dark:text-gray-400">Max SOC</span>
                  <input type="number" min="0" max="100" step="1" value={batteryForm.maxSoc}
                    onChange={e => setBatteryForm(f => ({ ...f, maxSoc: int(e.target.value, f.maxSoc) }))}
                    className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </label>
              </div>
            </div>

            <div className="flex justify-between pt-2">
              <button onClick={() => setStep(2)}
                className="flex items-center space-x-1 px-4 py-2 text-gray-600 dark:text-gray-300 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700">
                <ChevronLeft className="h-4 w-4" /><span>Back</span>
              </button>
              <button onClick={() => setStep(4)}
                className="flex items-center space-x-2 px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 font-medium">
                <span>Next: Home</span><ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 4: Home ── */}
        {step === 4 && (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6 space-y-5">
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Home</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Fuse protection prevents the main fuse from blowing when the battery charges at the same time as other high loads. Recommended if your home does not have hardware power limiting.</p>
            </div>

            {/* Fuse protection — top, controls visibility of grid fields */}
            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Enable Fuse Protection</span>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">Monitors real-time load and limits battery charge power to prevent blowing the main fuse.</p>
                </div>
                <button
                  type="button"
                  onClick={() => setHomeForm(f => ({ ...f, powerMonitoringEnabled: !f.powerMonitoringEnabled }))}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 ${homeForm.powerMonitoringEnabled ? 'bg-blue-500' : 'bg-gray-300 dark:bg-gray-600'}`}
                >
                  <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${homeForm.powerMonitoringEnabled ? 'translate-x-6' : 'translate-x-1'}`} />
                </button>
              </div>

              {homeForm.powerMonitoringEnabled && (
                <>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <label className="block">
                      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Fuse Current (A)</span>
                      <input type="number" min="1" step="1" value={homeForm.maxFuseCurrent}
                        onChange={e => setHomeForm(f => ({ ...f, maxFuseCurrent: int(e.target.value, f.maxFuseCurrent) }))}
                        className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                    </label>
                    <label className="block">
                      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Voltage (V)</span>
                      <input type="number" min="100" step="1" value={homeForm.voltage}
                        onChange={e => setHomeForm(f => ({ ...f, voltage: int(e.target.value, f.voltage) }))}
                        className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                    </label>
                    <label className="block">
                      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Safety Margin</span>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Fraction of the fuse rating to use as the limit. E.g. 0.9 leaves 10% headroom. Default 1.0 uses the full fuse rating.</p>
                      <input type="number" min="0" max="1" step="0.01" value={homeForm.safetyMarginFactor}
                        onChange={e => setHomeForm(f => ({ ...f, safetyMarginFactor: num(e.target.value, f.safetyMarginFactor) }))}
                        className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                    </label>
                  </div>
                  <div className="space-y-2">
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                      Phases {detectedBadge(discovery?.detectedPhaseCount != null)}
                    </span>
                    <div className="flex space-x-4">
                      {[1, 3].map(n => (
                        <label key={n} className="flex items-center space-x-2 cursor-pointer">
                          <input type="radio" name="phaseCount" value={n}
                            checked={homeForm.phaseCount === n}
                            onChange={() => setHomeForm(f => ({ ...f, phaseCount: n }))}
                            className="text-blue-500" />
                          <span className="text-sm text-gray-700 dark:text-gray-300">{n}-phase</span>
                        </label>
                      ))}
                    </div>
                  </div>
                </>
              )}
            </div>

            {/* Consumption strategy */}
            <div className="space-y-3">
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Consumption Strategy</span>
              <p className="text-xs text-gray-500 dark:text-gray-400">The data source the optimizer uses for expected home load each hour. A sensor gives the most accurate forecast; use a fixed value if no consumption sensor is available.</p>
              <div className="flex flex-col space-y-2">
                {([
                  { value: 'sensor', label: 'Home Assistant sensor', hint: 'Reads a HA sensor that provides an hourly consumption estimate, e.g. a 48h rolling average of grid import. Configure the entity ID in Settings → Sensors.' },
                  { value: 'fixed', label: 'Fixed value', hint: 'Always uses the value below — no sensor required. Good starting point if you have no consumption sensor.' },
                  { value: 'influxdb_7d_avg', label: 'InfluxDB 7-day average', hint: 'Queries InfluxDB for the past 7 days of local load power. Requires the InfluxDB integration.' },
                ] as const).map(s => (
                  <label key={s.value} className="flex items-start space-x-2 cursor-pointer">
                    <input type="radio" name="consumptionStrategy" value={s.value}
                      checked={homeForm.consumptionStrategy === s.value}
                      onChange={() => setHomeForm(f => ({ ...f, consumptionStrategy: s.value }))}
                      className="text-blue-500 mt-0.5" />
                    <div>
                      <span className="text-sm text-gray-700 dark:text-gray-300">{s.label}</span>
                      {homeForm.consumptionStrategy === s.value && (
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{s.hint}</p>
                      )}
                    </div>
                  </label>
                ))}
              </div>
              {homeForm.consumptionStrategy === 'fixed' && (
                <label className="block">
                  <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Default Hourly Consumption (kWh)</span>
                  <input type="number" min="0" step="0.1" value={homeForm.consumption}
                    onChange={e => setHomeForm(f => ({ ...f, consumption: num(e.target.value, f.consumption) }))}
                    className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </label>
              )}
            </div>

            {completeError && (
              <p className="text-sm text-red-600 dark:text-red-400">{completeError}</p>
            )}
            <div className="flex justify-between pt-2">
              <button
                onClick={() => setStep(3)}
                className="flex items-center space-x-1 px-4 py-2 text-gray-600 dark:text-gray-300 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700"
              >
                <ChevronLeft className="h-4 w-4" /><span>Back</span>
              </button>
              <button
                onClick={handleComplete}
                disabled={completing}
                className="flex items-center space-x-2 px-6 py-2 bg-green-500 text-white rounded-lg hover:bg-green-600 font-medium disabled:opacity-60"
              >
                {completing ? <div className="h-4 w-4 border-2 border-white rounded-full border-t-transparent animate-spin" /> : null}
                <span>Finish Setup</span><ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 2: Electricity Pricing ── */}
        {step === 2 && (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6 space-y-5">
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Electricity Pricing</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">How the optimizer calculates the real cost of buying and selling electricity. Getting this right is essential for accurate savings calculations.</p>
            </div>

            {discovery?.vatMultiplier != null && (
              <div className="rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-700 px-4 py-2 text-xs text-green-800 dark:text-green-300">
                Currency, VAT multiplier and price area pre-filled from detected Nord Pool integration.
              </div>
            )}

            {/* Provider */}
            <div className="space-y-2">
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Price Source</span>
              <p className="text-xs text-gray-500 dark:text-gray-400">Where spot prices come from. Use the official Nord Pool integration if installed via HACS or the HA store. Use the custom sensor option if you have your own Nord Pool sensor entities.</p>
              <div className="flex flex-col space-y-2 pt-1">
                {([
                  { value: 'nordpool_official', label: 'Nord Pool (official HA integration)' },
                  { value: 'nordpool', label: 'Nord Pool (custom sensor)' },
                  { value: 'octopus', label: 'Octopus Energy' },
                ] as const).map(opt => (
                  <label key={opt.value} className="flex items-center space-x-2 cursor-pointer">
                    <input type="radio" name="provider" value={opt.value}
                      checked={electricityForm.provider === opt.value}
                      onChange={() => setElectricityForm(f => ({ ...f, provider: opt.value }))}
                      className="text-blue-500" />
                    <span className="text-sm text-gray-700 dark:text-gray-300">{opt.label}</span>
                  </label>
                ))}
              </div>
            </div>

            {/* Currency + Area */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  Currency {detectedBadge(discovery?.currency != null)}
                </span>
                <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Used for all savings calculations and price display throughout the app.</p>
                <select value={electricityForm.currency ?? ''}
                  onChange={e => setElectricityForm(f => ({ ...f, currency: e.target.value }))}
                  className="block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                  <option value="">Select currency</option>
                  {['SEK', 'NOK', 'DKK', 'EUR', 'GBP'].map(c => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </label>

              {electricityForm.provider !== 'octopus' && (
                <label className="block">
                  <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                    Price Area {detectedBadge(discovery?.nordpoolArea != null)}
                  </span>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Your Nord Pool bidding zone. Examples: SE4, NO1, DK1, FI, GB.</p>
                  <input type="text" value={electricityForm.area ?? ''}
                    onChange={e => setElectricityForm(f => ({ ...f, area: e.target.value }))}
                    placeholder="e.g. SE4, NO1, DK1"
                    className="block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </label>
              )}
            </div>

            {/* Price calculation */}
            {electricityForm.provider !== 'octopus' && (
              <div className="space-y-3">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Price Calculation</span>
                <p className="text-xs text-gray-500 dark:text-gray-400">How the raw spot price is turned into your actual buy price. Formula: buy = (spot + markup) × VAT + additional costs.</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <label className="block">
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Markup Rate</span>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Fixed surcharge added to the spot price before VAT. Covers your supplier's margin.</p>
                    <input type="number" min="0" step="0.001" value={electricityForm.markupRate}
                      onChange={e => setElectricityForm(f => ({ ...f, markupRate: num(e.target.value, f.markupRate) }))}
                      className="block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                  </label>
                  <label className="block">
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-300">VAT Multiplier</span>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Applied to spot + markup. E.g. 1.25 = 25% VAT. {detectedBadge(discovery?.vatMultiplier != null)}</p>
                    <input type="number" min="1" step="0.01" value={electricityForm.vatMultiplier}
                      onChange={e => setElectricityForm(f => ({ ...f, vatMultiplier: num(e.target.value, f.vatMultiplier) }))}
                      className="block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                  </label>
                  <label className="block">
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Additional Costs</span>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Grid fee + energy tax per kWh, VAT-inclusive. Added after VAT.</p>
                    <input type="number" min="0" step="0.001" value={electricityForm.additionalCosts}
                      onChange={e => setElectricityForm(f => ({ ...f, additionalCosts: num(e.target.value, f.additionalCosts) }))}
                      className="block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                  </label>
                  <label className="block">
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Tax Reduction</span>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Credit per kWh on energy sold back to the grid (e.g. ROT/skattereduktion). Enter 0 if not applicable.</p>
                    <input type="number" min="0" step="0.001" value={electricityForm.taxReduction}
                      onChange={e => setElectricityForm(f => ({ ...f, taxReduction: num(e.target.value, f.taxReduction) }))}
                      className="block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                  </label>
                </div>
              </div>
            )}

            <div className="flex justify-between pt-2">
              <button onClick={() => setStep(1)}
                className="flex items-center space-x-1 px-4 py-2 text-gray-600 dark:text-gray-300 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700">
                <ChevronLeft className="h-4 w-4" /><span>Back</span>
              </button>
              <button onClick={() => setStep(3)}
                className="flex items-center space-x-2 px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 font-medium">
                <span>Next: Battery</span><ChevronRight className="h-4 w-4" />
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
                <span className="font-medium text-gray-900 dark:text-white">{electricityForm.currency}</span>
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
