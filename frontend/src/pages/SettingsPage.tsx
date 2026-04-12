import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, Battery, Download, Home, RefreshCw, Settings, Sun, Zap } from 'lucide-react';
import api from '../lib/api';
import SystemHealthComponent from '../components/SystemHealth';
import type { HealthStatus } from '../types';
import { HomeFormSection } from '../components/settings/HomeFormSection';
import type { HomeForm } from '../components/settings/HomeFormSection';
import { PricingFormSection } from '../components/settings/PricingFormSection';
import type { PricingForm } from '../components/settings/PricingFormSection';
import { BatteryFormSection } from '../components/settings/BatteryFormSection';
import type { BatteryForm, InverterForm } from '../components/settings/BatteryFormSection';
import { SensorConfigSection } from '../components/settings/SensorConfigSection';

// ---------------------------------------------------------------------------
// Local types
// ---------------------------------------------------------------------------

type Tab = 'home' | 'pricing' | 'battery' | 'sensors' | 'health';

interface Toast {
  type: 'success' | 'error';
  message: string;
}

// ---------------------------------------------------------------------------
// Empty form defaults
// ---------------------------------------------------------------------------

const EMPTY_BATTERY: BatteryForm = {
  totalCapacity: 0, minSoc: 0, maxSoc: 100,
  maxChargeDischargePowerKw: 0,
  cycleCostPerKwh: 0,
  efficiencyCharge: 97, efficiencyDischarge: 97,
  temperatureDeratingEnabled: false, minActionProfit: 0,
};
const EMPTY_HOME: HomeForm = {
  consumption: 3.5, consumptionStrategy: 'sensor',
  maxFuseCurrent: 25, voltage: 230, safetyMarginFactor: 1.0,
  phaseCount: 3, powerMonitoringEnabled: true,
};
const EMPTY_PRICING: PricingForm = {
  currency: 'SEK',
  provider: 'nordpool_official', nordpoolConfigEntryId: '',
  nordpoolTodayEntity: '', nordpoolTomorrowEntity: '',
  octopusImportTodayEntity: '', octopusImportTomorrowEntity: '',
  octopusExportTodayEntity: '', octopusExportTomorrowEntity: '',
  area: '', markupRate: 0, vatMultiplier: 1.25, additionalCosts: 0,
  taxReduction: 0,
};
const EMPTY_INVERTER: InverterForm = { inverterType: 'MIN', deviceId: '' };

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const SettingsPage: React.FC = () => {
  const navigate = useNavigate();

  // ── active tab ─────────────────────────────────────────────────────────
  const [tab, setTab] = useState<Tab>('sensors');

  // ── form state ─────────────────────────────────────────────────────────
  const [batteryForm, setBatteryForm] = useState<BatteryForm>(EMPTY_BATTERY);
  const [homeForm, setHomeForm] = useState<HomeForm>(EMPTY_HOME);
  const [pricingForm, setPricingForm] = useState<PricingForm>(EMPTY_PRICING);
  const [inverterForm, setInverterForm] = useState<InverterForm>(EMPTY_INVERTER);
  const [sensors, setSensors] = useState<Record<string, string>>({});

  // ── saved snapshots (for dirty detection) ──────────────────────────────
  const savedBattery = useRef<string>('');
  const savedHome = useRef<string>('');
  const savedPricing = useRef<string>('');
  const savedInverter = useRef<string>('');
  const savedSensors = useRef<string>('');

  const isDirty: Record<Tab, boolean> = {
    home: JSON.stringify(homeForm) !== savedHome.current,
    pricing: JSON.stringify(pricingForm) !== savedPricing.current,
    battery:
      JSON.stringify(batteryForm) !== savedBattery.current ||
      JSON.stringify(inverterForm) !== savedInverter.current,
    sensors: JSON.stringify(sensors) !== savedSensors.current,
    health: false,
  };

  // ── loading / saving / error state ────────────────────────────────────
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);

  // ── health status map (sensor_key → status) ────────────────────────────
  const [sensorStatus, setSensorStatus] = useState<Record<string, HealthStatus>>({});

  // ── health tab state ──────────────────────────────────────────────────
  const [healthKey, setHealthKey] = useState(0);

  // ── export debug data ─────────────────────────────────────────────────
  const [isExporting, setIsExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  // ── sensor group expand state ─────────────────────────────────────────

  // ── auto-configure ────────────────────────────────────────────────────
  const [discovering, setDiscovering] = useState(false);
  const [lastDiscoveredAt, setLastDiscoveredAt] = useState<string | null>(null);

  // ── auto-dismiss toast ────────────────────────────────────────────────
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  // ── load all settings on mount ────────────────────────────────────────
  const loadAll = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [batRes, homeRes, elecRes, provRes, invRes, senRes, healthRes] = await Promise.all([
        api.get('/api/settings/battery'),
        api.get('/api/settings/home'),
        api.get('/api/settings/electricity'),
        api.get('/api/settings/energy-provider'),
        api.get('/api/settings/inverter'),
        api.get('/api/settings/sensors'),
        api.get('/api/system-health').catch(() => ({ data: null })),
      ]);

      const bat: BatteryForm = {
        totalCapacity: batRes.data.totalCapacity ?? 0,
        minSoc: batRes.data.minSoc ?? 0,
        maxSoc: batRes.data.maxSoc ?? 100,
        maxChargeDischargePowerKw: batRes.data.maxChargePowerKw ?? 0,
        cycleCostPerKwh: batRes.data.cycleCostPerKwh ?? 0,
        efficiencyCharge: batRes.data.efficiencyCharge ?? 97,
        efficiencyDischarge: batRes.data.efficiencyDischarge ?? 97,
        temperatureDeratingEnabled: batRes.data.temperatureDeratingEnabled ?? false,
        minActionProfit: batRes.data.minActionProfitThreshold ?? 0,
      };
      setBatteryForm(bat);
      savedBattery.current = JSON.stringify(bat);

      const h: HomeForm = {
        consumption: homeRes.data.consumption ?? 3.5,
        consumptionStrategy: homeRes.data.consumptionStrategy ?? 'sensor',
        maxFuseCurrent: homeRes.data.maxFuseCurrent ?? 25,
        voltage: homeRes.data.voltage ?? 230,
        safetyMarginFactor: homeRes.data.safetyMarginFactor ?? 1.0,
        phaseCount: homeRes.data.phaseCount ?? 3,
        powerMonitoringEnabled: homeRes.data.powerMonitoringEnabled ?? true,
      };
      setHomeForm(h);
      savedHome.current = JSON.stringify(h);

      const nordpool = provRes.data.nordpoolOfficial ?? provRes.data.nordpool_official ?? {};
      const nordpoolCustom = provRes.data.nordpool ?? {};
      const octopus = provRes.data.octopus ?? {};

      const p: PricingForm = {
        currency: homeRes.data.currency ?? '',
        provider: provRes.data.provider ?? 'nordpool_official',
        nordpoolConfigEntryId: nordpool.configEntryId ?? nordpool.config_entry_id ?? '',
        nordpoolTodayEntity: nordpoolCustom.todayEntity ?? nordpoolCustom.today_entity ?? '',
        nordpoolTomorrowEntity: nordpoolCustom.tomorrowEntity ?? nordpoolCustom.tomorrow_entity ?? '',
        octopusImportTodayEntity: octopus.importTodayEntity ?? octopus.import_today_entity ?? '',
        octopusImportTomorrowEntity: octopus.importTomorrowEntity ?? octopus.import_tomorrow_entity ?? '',
        octopusExportTodayEntity: octopus.exportTodayEntity ?? octopus.export_today_entity ?? '',
        octopusExportTomorrowEntity: octopus.exportTomorrowEntity ?? octopus.export_tomorrow_entity ?? '',
        area: elecRes.data.area ?? '',
        markupRate: elecRes.data.markupRate ?? 0,
        vatMultiplier: elecRes.data.vatMultiplier ?? 1.25,
        additionalCosts: elecRes.data.additionalCosts ?? 0,
        taxReduction: elecRes.data.taxReduction ?? 0,
      };
      setPricingForm(p);
      savedPricing.current = JSON.stringify(p);

      const inv: InverterForm = {
        inverterType: invRes.data.inverterType ?? invRes.data.inverter_type ?? 'MIN',
        deviceId: invRes.data.deviceId ?? invRes.data.device_id ?? '',
      };
      setInverterForm(inv);
      savedInverter.current = JSON.stringify(inv);

      const sen: Record<string, string> = senRes.data ?? {};
      setSensors(sen);
      savedSensors.current = JSON.stringify(sen);

      if (healthRes.data?.checks) {
        const map: Record<string, HealthStatus> = {};
        for (const component of healthRes.data.checks) {
          for (const check of component.checks ?? []) {
            if (check.key) map[check.key] = check.status;
          }
        }
        setSensorStatus(map);
      }
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Failed to load settings');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  // ── auto-configure (in-place discovery) ──────────────────────────────
  const runAutoDiscover = async () => {
    setDiscovering(true);
    try {
      const res = await api.post('/api/setup/discover');
      const d = res.data;

      if (d.sensors && typeof d.sensors === 'object') {
        setSensors(prev => {
          const merged = {
            ...d.sensors,
            ...Object.fromEntries(Object.entries(prev).filter(([, v]) => v)),
          };
          // Drop empty-string entries so the result has the same shape as the
          // persisted sensor map. Without this, discovered empty keys trigger a
          // false dirty state even when nothing actually changed.
          return Object.fromEntries(Object.entries(merged).filter(([, v]) => v));
        });
      }

      if (d.inverterType || d.growattDeviceId) {
        setInverterForm(f => ({
          ...f,
          ...(d.inverterType ? { inverterType: d.inverterType } : {}),
          ...(d.growattDeviceId ? { deviceId: d.growattDeviceId } : {}),
        }));
      }

      setPricingForm(f => ({
        ...f,
        ...(d.nordpoolConfigEntryId ? { nordpoolConfigEntryId: d.nordpoolConfigEntryId } : {}),
        ...(d.nordpoolArea ? { area: d.nordpoolArea } : {}),
        ...(d.currency ? { currency: d.currency } : {}),
        ...(d.vatMultiplier ? { vatMultiplier: d.vatMultiplier } : {}),
      }));

      if (d.detectedPhaseCount) {
        setHomeForm(f => ({ ...f, phaseCount: d.detectedPhaseCount }));
      }

      setLastDiscoveredAt(new Date().toLocaleTimeString());
      const sensorCount = d.sensors ? Object.keys(d.sensors).filter(k => d.sensors[k]).length : 0;
      setToast({
        type: 'success',
        message: `Auto-configure found ${sensorCount} sensors${d.inverterType ? `, ${d.inverterType} inverter` : ''}${d.nordpoolArea ? `, area ${d.nordpoolArea}` : ''}. Review and save.`,
      });

      const healthRes = await api.get('/api/system-health').catch(() => ({ data: null }));
      if (healthRes.data?.checks) {
        const map: Record<string, HealthStatus> = {};
        for (const component of healthRes.data.checks) {
          for (const check of component.checks ?? []) {
            if (check.key) map[check.key] = check.status;
          }
        }
        setSensorStatus(map);
      }
    } catch (err) {
      setToast({ type: 'error', message: err instanceof Error ? err.message : 'Auto-configure failed' });
    } finally {
      setDiscovering(false);
    }
  };

  // ── health check refresh ──────────────────────────────────────────────
  const checkAndUpdateSensorHealth = async (currentSensors: Record<string, string>): Promise<string[]> => {
    try {
      const res = await api.get('/api/system-health').catch(() => ({ data: null }));
      if (res.data?.checks) {
        const map: Record<string, HealthStatus> = {};
        for (const component of res.data.checks) {
          for (const check of component.checks ?? []) {
            if (check.key) map[check.key] = check.status;
          }
        }
        setSensorStatus(map);
        return Object.entries(currentSensors)
          .filter(([k, v]) => v && map[k] === 'ERROR')
          .map(([, v]) => v);
      }
    } catch { /* non-fatal */ }
    return [];
  };

  // ── export debug data ─────────────────────────────────────────────────
  const handleExportDebugData = async () => {
    setIsExporting(true);
    setExportError(null);
    try {
      const response = await api.get('/api/export-debug-data', { responseType: 'blob' });
      const contentDisposition = response.headers['content-disposition'];
      let filename = 'bess-debug.md';
      if (contentDisposition) {
        const m = contentDisposition.match(/filename=(.+)/);
        if (m) filename = m[1].replace(/"/g, '');
      }
      const blob = new Blob([response.data], { type: 'text/markdown' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch {
      setExportError('Failed to export debug data. Please check the logs.');
    } finally {
      setIsExporting(false);
    }
  };

  // ── save handlers ─────────────────────────────────────────────────────

  const saveHome = async () => {
    setSaving(true);
    try {
      await api.put('/api/settings/home', { ...homeForm, currency: pricingForm.currency });
      savedHome.current = JSON.stringify(homeForm);
      setToast({ type: 'success', message: 'Home settings saved.' });
    } catch (err) {
      setToast({ type: 'error', message: err instanceof Error ? err.message : 'Save failed.' });
    } finally {
      setSaving(false);
    }
  };

  const savePricing = async () => {
    setSaving(true);
    try {
      await Promise.all([
        api.post('/api/settings/electricity', {
          area: pricingForm.area,
          markupRate: pricingForm.markupRate,
          vatMultiplier: pricingForm.vatMultiplier,
          additionalCosts: pricingForm.additionalCosts,
          taxReduction: pricingForm.taxReduction,
          useActualPrice: false,
        }),
        api.put('/api/settings/energy-provider', {
          provider: pricingForm.provider,
          nordpoolConfigEntryId: pricingForm.nordpoolConfigEntryId || null,
          nordpoolTodayEntity: pricingForm.nordpoolTodayEntity || null,
          nordpoolTomorrowEntity: pricingForm.nordpoolTomorrowEntity || null,
          octopusImportTodayEntity: pricingForm.octopusImportTodayEntity || null,
          octopusImportTomorrowEntity: pricingForm.octopusImportTomorrowEntity || null,
          octopusExportTodayEntity: pricingForm.octopusExportTodayEntity || null,
          octopusExportTomorrowEntity: pricingForm.octopusExportTomorrowEntity || null,
        }),
        api.put('/api/settings/home', { ...homeForm, currency: pricingForm.currency }),
      ]);
      savedPricing.current = JSON.stringify(pricingForm);
      savedHome.current = JSON.stringify(homeForm);
      setToast({ type: 'success', message: 'Electricity pricing settings saved.' });
    } catch (err) {
      setToast({ type: 'error', message: err instanceof Error ? err.message : 'Save failed.' });
    } finally {
      setSaving(false);
    }
  };

  const saveBattery = async () => {
    setSaving(true);
    try {
      await Promise.all([
        api.post('/api/settings/battery', {
          totalCapacity: batteryForm.totalCapacity,
          reservedCapacity: 0,
          minSoc: batteryForm.minSoc,
          maxSoc: batteryForm.maxSoc,
          minSoeKwh: (batteryForm.totalCapacity * batteryForm.minSoc) / 100,
          maxSoeKwh: (batteryForm.totalCapacity * batteryForm.maxSoc) / 100,
          maxChargePowerKw: batteryForm.maxChargeDischargePowerKw,
          maxDischargePowerKw: batteryForm.maxChargeDischargePowerKw,
          cycleCostPerKwh: batteryForm.cycleCostPerKwh,
          minActionProfitThreshold: batteryForm.minActionProfit,
          efficiencyCharge: batteryForm.efficiencyCharge,
          efficiencyDischarge: batteryForm.efficiencyDischarge,
          estimatedConsumption: 0,
          consumptionStrategy: 'sensor',
          temperatureDeratingEnabled: batteryForm.temperatureDeratingEnabled,
          temperatureDeratingWeatherEntity: sensors['weather_entity'] ?? '',
        }),
        api.put('/api/settings/inverter', {
          inverterType: inverterForm.inverterType,
          deviceId: inverterForm.deviceId || null,
        }),
      ]);
      savedBattery.current = JSON.stringify(batteryForm);
      savedInverter.current = JSON.stringify(inverterForm);
      setToast({ type: 'success', message: 'Battery settings saved.' });
    } catch (err) {
      setToast({ type: 'error', message: err instanceof Error ? err.message : 'Save failed.' });
    } finally {
      setSaving(false);
    }
  };

  const saveSensors = async () => {
    setSaving(true);
    try {
      await Promise.all([
        api.put('/api/settings/sensors', { sensors }),
        api.put('/api/settings/energy-provider', {
          provider: pricingForm.provider,
          nordpoolConfigEntryId: pricingForm.nordpoolConfigEntryId || null,
          nordpoolTodayEntity: pricingForm.nordpoolTodayEntity || null,
          nordpoolTomorrowEntity: pricingForm.nordpoolTomorrowEntity || null,
          octopusImportTodayEntity: pricingForm.octopusImportTodayEntity || null,
          octopusImportTomorrowEntity: pricingForm.octopusImportTomorrowEntity || null,
          octopusExportTodayEntity: pricingForm.octopusExportTodayEntity || null,
          octopusExportTomorrowEntity: pricingForm.octopusExportTomorrowEntity || null,
        }),
      ]);
      savedSensors.current = JSON.stringify(sensors);
      savedPricing.current = JSON.stringify(pricingForm);
      const failed = await checkAndUpdateSensorHealth(sensors);
      if (failed.length > 0) {
        setToast({
          type: 'error',
          message: `Saved — but ${failed.length} sensor(s) not found in HA: ${failed.slice(0, 2).join(', ')}${failed.length > 2 ? ` (+${failed.length - 2} more)` : ''}`,
        });
      } else {
        setToast({ type: 'success', message: 'Sensor settings saved.' });
      }
    } catch (err) {
      setToast({ type: 'error', message: err instanceof Error ? err.message : 'Save failed.' });
    } finally {
      setSaving(false);
    }
  };

  const saveHandlers: Record<Tab, (() => Promise<void>) | null> = {
    home: saveHome,
    pricing: savePricing,
    battery: saveBattery,
    sensors: saveSensors,
    health: null,
  };

  // ── tab definitions ───────────────────────────────────────────────────
  const tabs: { id: Tab; label: string; icon: React.ReactNode }[] = [
    { id: 'sensors', label: 'Sensors', icon: <Sun className="h-4 w-4" /> },
    { id: 'pricing', label: 'Electricity Pricing', icon: <Zap className="h-4 w-4" /> },
    { id: 'battery', label: 'Battery', icon: <Battery className="h-4 w-4" /> },
    { id: 'home', label: 'Home', icon: <Home className="h-4 w-4" /> },
    { id: 'health', label: 'Health', icon: <Activity className="h-4 w-4" /> },
  ];

  // ── render ────────────────────────────────────────────────────────────
  return (
    <div className="max-w-3xl mx-auto pb-12 space-y-4">
      {/* Page header */}
      <div>
        <div className="flex items-center space-x-2">
          <Settings className="h-5 w-5 text-gray-500 dark:text-gray-400" />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Settings</h1>
        </div>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Manage your BESS configuration</p>
      </div>

      {/* Toast */}
      {toast && (
        <div className={`rounded-lg px-4 py-3 text-sm font-medium ${
          toast.type === 'success'
            ? 'bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-700 text-green-800 dark:text-green-300'
            : 'bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700 text-red-800 dark:text-red-300'
        }`}>
          {toast.message}
        </div>
      )}

      {/* Load error */}
      {loadError && (
        <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-4 py-3 text-sm text-red-800 dark:text-red-300">
          {loadError}
          <button onClick={loadAll} className="ml-3 underline font-medium">Retry</button>
        </div>
      )}

      {loading ? (
        <div className="flex items-center space-x-3 text-gray-500 dark:text-gray-400 py-8">
          <div className="h-5 w-5 border-2 border-blue-500 rounded-full border-t-transparent animate-spin" />
          <span>Loading settings…</span>
        </div>
      ) : (
        <>
          {/* Tab navigation card */}
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="flex border-b border-gray-200 dark:border-gray-700 overflow-x-auto">
              {tabs.map(t => (
                <button
                  key={t.id}
                  onClick={() => {
                    setTab(t.id);
                    if (t.id === 'sensors' && Object.keys(sensorStatus).length === 0) {
                      checkAndUpdateSensorHealth(sensors);
                    }
                  }}
                  className={`flex items-center space-x-2 px-4 py-3 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${
                    tab === t.id
                      ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                      : 'border-transparent text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100'
                  }`}
                >
                  {t.icon}
                  <span>{t.label}</span>
                  {isDirty[t.id] && (
                    <span className="inline-block h-2 w-2 rounded-full bg-amber-400" title="Unsaved changes" />
                  )}
                </button>
              ))}
            </div>
            <div className="px-4 py-2 bg-gray-50 dark:bg-gray-800/60 flex items-center justify-between gap-3">
              <p className="text-xs text-gray-500 dark:text-gray-400 flex-1 min-w-0 truncate">
                {tab === 'home' && 'Home electrical setup and consumption prediction for the optimizer.'}
                {tab === 'pricing' && 'Electricity price source and cost calculation (markup, VAT, tax reduction).'}
                {tab === 'battery' && 'Growatt inverter type and battery parameters.'}
                {tab === 'sensors' && 'All sensor entity IDs, grouped by integration.'}
                {tab === 'health' && 'System component health and diagnostics.'}
              </p>
              <div className="flex items-center gap-2 flex-shrink-0">
                <button
                  onClick={runAutoDiscover}
                  disabled={discovering}
                  className="px-4 py-1 bg-green-600 text-white rounded-lg hover:bg-green-700 font-medium text-xs disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
                >
                  {discovering
                    ? <div className="h-3 w-3 border-2 border-white rounded-full border-t-transparent animate-spin" />
                    : <Zap className="h-3 w-3" />}
                  <span>{discovering ? 'Scanning…' : 'Auto-Configure'}</span>
                </button>
                <button
                  onClick={() => saveHandlers[tab]?.()}
                  disabled={saving || !isDirty[tab] || !saveHandlers[tab]}
                  className="px-4 py-1 bg-blue-500 text-white rounded-lg hover:bg-blue-600 font-medium text-xs disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
                >
                  {saving && <div className="h-3 w-3 border-2 border-white rounded-full border-t-transparent animate-spin" />}
                  <span>Save</span>
                </button>
              </div>
            </div>
          </div>

          {/* ── Home ─────────────────────────────────────────────────────── */}
          {tab === 'home' && (
            <HomeFormSection form={homeForm} onChange={setHomeForm} />
          )}

          {/* ── Electricity Pricing ──────────────────────────────────────── */}
          {tab === 'pricing' && (
            <PricingFormSection form={pricingForm} onChange={setPricingForm} />
          )}

          {/* ── Battery ──────────────────────────────────────────────────── */}
          {tab === 'battery' && (
            <BatteryFormSection
              form={batteryForm}
              onChange={setBatteryForm}
              inverterForm={inverterForm}
              onInverterChange={setInverterForm}
              currency={pricingForm.currency}
              weatherEntity={sensors['weather_entity']}
            />
          )}

          {/* ── Sensors ──────────────────────────────────────────────────── */}
          {tab === 'sensors' && (
            <div className="space-y-3">
              {lastDiscoveredAt && (
                <p className="text-xs text-gray-400 dark:text-gray-500 px-1">Last scanned: {lastDiscoveredAt}</p>
              )}
              <SensorConfigSection
                sensors={sensors}
                onChange={setSensors}
                sensorStatus={sensorStatus}
              />
            </div>
          )}

          {/* ── Health ───────────────────────────────────────────────────── */}
          {tab === 'health' && (
            <div className="space-y-4">
              <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 px-5 py-4 flex flex-wrap items-center gap-3">
                <button
                  onClick={() => setHealthKey(k => k + 1)}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                >
                  <RefreshCw className="h-4 w-4" />
                  Refresh
                </button>
                <button
                  onClick={handleExportDebugData}
                  disabled={isExporting}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
                >
                  <Download className="h-4 w-4" />
                  {isExporting ? 'Exporting…' : 'Export Debug Data'}
                </button>
              </div>

              {exportError && (
                <div className="px-4 py-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-sm text-red-800 dark:text-red-200">
                  {exportError}
                </div>
              )}

              <SystemHealthComponent key={healthKey} />

              <div className="bg-gray-100 dark:bg-gray-800/50 p-4 rounded-lg border border-gray-200 dark:border-gray-700">
                <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">Status Indicators</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                  <ul className="space-y-1 text-gray-600 dark:text-gray-400">
                    <li><span className="text-green-600 dark:text-green-400 font-medium">OK</span>: Component is fully functional with all required sensors.</li>
                    <li><span className="text-amber-600 dark:text-amber-400 font-medium">WARNING</span>: Component has minor issues but can operate with limitations.</li>
                    <li><span className="text-red-600 dark:text-red-400 font-medium">ERROR</span>: Component has critical issues and may not function correctly.</li>
                  </ul>
                  <ul className="space-y-1 text-gray-600 dark:text-gray-400">
                    <li><span className="font-medium">Required</span>: Essential for basic system operation.</li>
                    <li><span className="font-medium">Optional</span>: Enhances functionality but not essential for basic operation.</li>
                  </ul>
                </div>
              </div>
            </div>
          )}
        </>
      )}

      {/* Setup wizard re-entry */}
      <div className="mt-8 pt-6 border-t border-gray-200 dark:border-gray-700 text-center">
        <button
          onClick={() => navigate('/setup')}
          className="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 underline transition-colors"
        >
          Re-run setup wizard
        </button>
      </div>
    </div>
  );
};

export default SettingsPage;
