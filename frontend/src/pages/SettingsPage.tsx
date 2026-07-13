import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Activity, Battery, Download, Home, Settings, Sun, Zap } from 'lucide-react';
import api from '../lib/api';
import { downloadDebugBundle } from '../lib/reportProblem';
import SystemHealthComponent from '../components/SystemHealth';
import type { HealthStatus } from '../types';
import { HomeFormSection } from '../components/settings/HomeFormSection';
import type { HomeForm } from '../components/settings/HomeFormSection';
import { PricingFormSection } from '../components/settings/PricingFormSection';
import type { PricingForm } from '../components/settings/PricingFormSection';
import { BatteryFormSection } from '../components/settings/BatteryFormSection';
import type { BatteryForm } from '../components/settings/BatteryFormSection';
import { SensorConfigSection } from '../components/settings/SensorConfigSection';
import type { InverterForm } from '../components/settings/SensorConfigSection';
import { AIAnalystSettings } from '../components/settings/AIAnalystSettings';
import type { AIAnalystForm } from '../components/settings/AIAnalystSettings';
import { SavingsHistorySection } from '../components/settings/SavingsHistorySection';
import { emptyPerPlatformSensors, getActiveSensorsFlat } from '../lib/sensorDefinitions';
import type { PerPlatformSensors } from '../lib/sensorDefinitions';

// ---------------------------------------------------------------------------
// Local types
// ---------------------------------------------------------------------------

type Tab = 'home' | 'pricing' | 'battery' | 'sensors' | 'system';

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
  nordpoolEntity: '',
  octopusImportTodayEntity: '', octopusImportTomorrowEntity: '',
  octopusExportTodayEntity: '', octopusExportTomorrowEntity: '',
  entsoeEntity: '',
  area: '', markupRate: 0, vatMultiplier: 1.25, additionalCosts: 0,
  taxReduction: 0, spotMultiplier: 1.0, exportSpotMultiplier: 1.0,
};
const EMPTY_INVERTER: InverterForm = { inverterPlatform: 'growatt_server_min', deviceId: '', controlMode: 'tou' };

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const SettingsPage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  // ── active tab ─────────────────────────────────────────────────────────
  const validTabs: Tab[] = ['home', 'pricing', 'battery', 'sensors', 'system'];
  const initialTab = searchParams.get('tab') as Tab;
  const [tab, setTab] = useState<Tab>(validTabs.includes(initialTab) ? initialTab : 'sensors');

  // ── form state ─────────────────────────────────────────────────────────
  const [batteryForm, setBatteryForm] = useState<BatteryForm>(EMPTY_BATTERY);
  const [homeForm, setHomeForm] = useState<HomeForm>(EMPTY_HOME);
  const [pricingForm, setPricingForm] = useState<PricingForm>(EMPTY_PRICING);
  const [inverterForm, setInverterForm] = useState<InverterForm>(EMPTY_INVERTER);
  const [sensors, setSensors] = useState<PerPlatformSensors>(emptyPerPlatformSensors());
  const [aiForm, setAiForm] = useState<AIAnalystForm>({ apiKey: '', model: 'claude-sonnet-4-6', enabled: true });
  const [demoEnabled, setDemoEnabled] = useState(false);
  const [savedDemoEnabled, setSavedDemoEnabled] = useState(false);
  const [showEnableDemoConfirm, setShowEnableDemoConfirm] = useState(false);

  // ── saved snapshots (for dirty detection) ──────────────────────────────
  const savedBattery = useRef<string>('');
  const savedHome = useRef<string>('');
  const savedPricing = useRef<string>('');
  const savedInverter = useRef<string>('');
  const savedSensors = useRef<string>('');
  const savedAi = useRef<string>('');

  // Sensor keys arrive in arbitrary order from different sources (backend
  // load vs. auto-configure merge), so sort keys recursively before comparing.
  const stableStringify = (obj: unknown): string => {
    const sortKeys = (val: unknown): unknown => {
      if (val && typeof val === 'object' && !Array.isArray(val)) {
        const sorted: Record<string, unknown> = {};
        for (const k of Object.keys(val as Record<string, unknown>).sort()) {
          sorted[k] = sortKeys((val as Record<string, unknown>)[k]);
        }
        return sorted;
      }
      return val;
    };
    return JSON.stringify(sortKeys(obj));
  };

  const isDirty: Record<Tab, boolean> = {
    home: JSON.stringify(homeForm) !== savedHome.current,
    pricing: JSON.stringify(pricingForm) !== savedPricing.current,
    battery:
      JSON.stringify(batteryForm) !== savedBattery.current ||
      JSON.stringify(inverterForm) !== savedInverter.current,
    sensors: stableStringify(sensors) !== savedSensors.current,
    system: demoEnabled !== savedDemoEnabled || JSON.stringify(aiForm) !== savedAi.current,
  };

  // ── loading / saving / error state ────────────────────────────────────
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);

  // ── health status map (sensor_key → status) ────────────────────────────
  const [sensorStatus, setSensorStatus] = useState<Record<string, HealthStatus>>({});


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
      const [settingsRes, healthRes] = await Promise.all([
        api.get('/api/settings'),
        api.get('/api/system-health').catch(() => ({ data: null })),
      ]);

      const s = settingsRes.data;
      const bat_s = s.battery ?? {};
      const home_s = s.home ?? {};
      const elec_s = s.electricityPrice ?? {};
      const prov_s = s.energyProvider ?? {};
      const growatt_s = s.growatt ?? {};
      const nordpool = prov_s.nordpoolOfficial ?? {};
      const nordpoolCustom = prov_s.nordpoolHacs ?? {};
      const octopus = prov_s.octopus ?? {};
      const entsoe = prov_s.entsoe ?? {};

      const bat: BatteryForm = {
        totalCapacity: bat_s.totalCapacity ?? 0,
        minSoc: bat_s.minSoc ?? 0,
        maxSoc: bat_s.maxSoc ?? 100,
        maxChargeDischargePowerKw: bat_s.maxChargePowerKw ?? 0,
        cycleCostPerKwh: bat_s.cycleCostPerKwh ?? 0,
        efficiencyCharge: bat_s.efficiencyCharge ?? 0.97,
        efficiencyDischarge: bat_s.efficiencyDischarge ?? 0.95,
        temperatureDeratingEnabled: bat_s.temperatureDerating?.enabled ?? false,
        minActionProfit: bat_s.minActionProfitThreshold ?? 0,
      };
      setBatteryForm(bat);
      savedBattery.current = JSON.stringify(bat);

      const h: HomeForm = {
        consumption: home_s.defaultHourly ?? 3.5,
        consumptionStrategy: home_s.consumptionStrategy ?? 'sensor',
        maxFuseCurrent: home_s.maxFuseCurrent ?? 25,
        voltage: home_s.voltage ?? 230,
        safetyMarginFactor: home_s.safetyMargin ?? 1.0,
        phaseCount: home_s.phaseCount ?? 3,
        powerMonitoringEnabled: home_s.powerMonitoringEnabled ?? true,
      };
      setHomeForm(h);
      savedHome.current = JSON.stringify(h);

      const p: PricingForm = {
        currency: home_s.currency ?? '',
        provider: prov_s.provider ?? 'nordpool_official',
        nordpoolConfigEntryId: nordpool.configEntryId ?? '',
        nordpoolEntity: nordpoolCustom.entity ?? '',
        octopusImportTodayEntity: octopus.importTodayEntity ?? '',
        octopusImportTomorrowEntity: octopus.importTomorrowEntity ?? '',
        octopusExportTodayEntity: octopus.exportTodayEntity ?? '',
        octopusExportTomorrowEntity: octopus.exportTomorrowEntity ?? '',
        entsoeEntity: entsoe.entity ?? '',
        area: elec_s.area ?? '',
        markupRate: elec_s.markupRate ?? 0,
        vatMultiplier: elec_s.vatMultiplier ?? 1.25,
        additionalCosts: elec_s.additionalCosts ?? 0,
        taxReduction: elec_s.taxReduction ?? 0,
        spotMultiplier: elec_s.spotMultiplier ?? 1.0,
        exportSpotMultiplier: elec_s.exportSpotMultiplier ?? 1.0,
      };
      setPricingForm(p);
      savedPricing.current = JSON.stringify(p);

      const invNew = s.inverter ?? {};
      const uiType = invNew.platform ?? 'growatt_server_min';
      const inv: InverterForm = {
        inverterPlatform: uiType,
        deviceId: growatt_s.deviceId ?? '',
        controlMode: (invNew.controlMode as 'tou' | 'vpp' | undefined) ?? 'tou',
      };
      setInverterForm(inv);
      savedInverter.current = JSON.stringify(inv);

      const sen: PerPlatformSensors = s.sensors && 'platform' in s.sensors
        ? s.sensors as PerPlatformSensors
        : emptyPerPlatformSensors();
      setSensors(sen);
      savedSensors.current = stableStringify(sen);

      const ai_s = s.aiAnalyst ?? {};
      const ai: AIAnalystForm = {
        apiKey: ai_s.apiKey ?? '',
        model: ai_s.model ?? 'claude-sonnet-4-6',
        enabled: ai_s.enabled ?? true,
      };
      setAiForm(ai);
      savedAi.current = JSON.stringify(ai);

      const dm = s.demoMode || s.demo_mode || {};
      setDemoEnabled(dm.enabled ?? false);
      setSavedDemoEnabled(dm.enabled ?? false);

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

      if (d.platformSensors && typeof d.platformSensors === 'object') {
        setSensors(prev => {
          const next = { ...prev };
          // Merge discovered platform sensors into each platform sub-dict
          for (const [platId, platMap] of Object.entries(d.platformSensors as Record<string, Record<string, string>>)) {
            if (platId in next && platId !== 'platform' && platId !== 'shared') {
              const existing = (next as Record<string, Record<string, string>>)[platId] ?? {};
              const merged: Record<string, string> = { ...existing };
              for (const [k, v] of Object.entries(platMap)) {
                if (v) merged[k] = v;
              }
              (next as Record<string, Record<string, string>>)[platId] = merged;
            }
          }
          // Merge shared sensors from flat discovery result
          if (d.sensors) {
            const shared = { ...(next.shared ?? {}) };
            for (const [k, v] of Object.entries(d.sensors as Record<string, string>)) {
              // Only merge keys that belong to shared integrations
              if (v && !(k in ((next as Record<string, Record<string, string>>)[next.platform] ?? {}))) {
                shared[k] = v;
              }
            }
            next.shared = shared;
          }
          return next;
        });
      }

      const detected = d.detectedInverterPlatforms ?? [];
      const detectedPlatform = detected[0] ?? null;
      if (detectedPlatform) {
        setInverterForm(f => ({ ...f, inverterPlatform: detectedPlatform }));
      }
      if (d.growattDeviceId) {
        setInverterForm(f => ({ ...f, deviceId: d.growattDeviceId }));
      }

      // Only update discovery fields that actually changed.
      // Never overwrite user-configured price calculation fields
      // (vatMultiplier, markupRate, additionalCosts, taxReduction).
      // Use area from matching integration: official if available,
      // otherwise HACS custom — never mix the two.
      const discoveredArea = d.nordpoolConfigEntryId
        ? d.nordpoolArea : d.nordpoolCustomArea;

      setPricingForm(f => {
        const next = { ...f };
        let changed = false;
        if (d.nordpoolConfigEntryId && d.nordpoolConfigEntryId !== f.nordpoolConfigEntryId) {
          next.nordpoolConfigEntryId = d.nordpoolConfigEntryId; changed = true;
        }
        if (discoveredArea && discoveredArea !== f.area) {
          next.area = discoveredArea; changed = true;
        }
        if (d.currency && d.currency !== f.currency) {
          next.currency = d.currency; changed = true;
        }
        return changed ? next : f;
      });

      if (d.detectedPhaseCount) {
        setHomeForm(f => ({ ...f, phaseCount: d.detectedPhaseCount }));
      }

      setLastDiscoveredAt(new Date().toLocaleTimeString());
      const sensorCount = d.sensors ? Object.keys(d.sensors).filter(k => d.sensors[k]).length : 0;
      setToast({
        type: 'success',
        message: `Auto-configure found ${sensorCount} sensors${detectedPlatform ? `, ${detectedPlatform} inverter` : ''}${discoveredArea ? `, area ${discoveredArea}` : ''}. Review and save.`,
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

  // ── save handlers ─────────────────────────────────────────────────────

  const saveHome = async () => {
    setSaving(true);
    try {
      await api.patch('/api/settings', {
        home: {
          defaultHourly: homeForm.consumption,
          consumptionStrategy: homeForm.consumptionStrategy,
          maxFuseCurrent: homeForm.maxFuseCurrent,
          voltage: homeForm.voltage,
          safetyMargin: homeForm.safetyMarginFactor,
          phaseCount: homeForm.phaseCount,
          powerMonitoringEnabled: homeForm.powerMonitoringEnabled,
          currency: pricingForm.currency,
        },
      });
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
      await api.patch('/api/settings', {
        electricityPrice: {
          area: pricingForm.area,
          markupRate: pricingForm.markupRate,
          vatMultiplier: pricingForm.vatMultiplier,
          additionalCosts: pricingForm.additionalCosts,
          taxReduction: pricingForm.taxReduction,
          spotMultiplier: pricingForm.spotMultiplier,
          exportSpotMultiplier: pricingForm.exportSpotMultiplier,
          useActualPrice: false,
        },
        energyProvider: {
          provider: pricingForm.provider,
          nordpoolOfficial: { configEntryId: pricingForm.nordpoolConfigEntryId },
          nordpoolHacs: { entity: pricingForm.nordpoolEntity },
          octopus: {
            importTodayEntity: pricingForm.octopusImportTodayEntity,
            importTomorrowEntity: pricingForm.octopusImportTomorrowEntity,
            exportTodayEntity: pricingForm.octopusExportTodayEntity,
            exportTomorrowEntity: pricingForm.octopusExportTomorrowEntity,
          },
          entsoe: { entity: pricingForm.entsoeEntity },
        },
        home: { currency: pricingForm.currency },
      });
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
      await api.patch('/api/settings', {
        battery: {
          totalCapacity: batteryForm.totalCapacity,
          minSoc: batteryForm.minSoc,
          maxSoc: batteryForm.maxSoc,
          maxChargePowerKw: batteryForm.maxChargeDischargePowerKw,
          maxDischargePowerKw: batteryForm.maxChargeDischargePowerKw,
          cycleCostPerKwh: batteryForm.cycleCostPerKwh,
          minActionProfitThreshold: batteryForm.minActionProfit,
          efficiencyCharge: batteryForm.efficiencyCharge,
          efficiencyDischarge: batteryForm.efficiencyDischarge,
          temperatureDerating: {
            enabled: batteryForm.temperatureDeratingEnabled,
            weatherEntity: sensors.shared?.['weather_entity'] ?? '',
          },
        },
        growatt: {
          deviceId: inverterForm.deviceId,
        },
        inverter: {
          platform: inverterForm.inverterPlatform,
          controlMode: inverterForm.controlMode ?? 'tou',
        },
      });
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
      await api.patch('/api/settings', {
        sensors,
        energyProvider: {
          provider: pricingForm.provider,
          nordpoolOfficial: { configEntryId: pricingForm.nordpoolConfigEntryId },
          nordpoolHacs: { entity: pricingForm.nordpoolEntity },
          octopus: {
            importTodayEntity: pricingForm.octopusImportTodayEntity,
            importTomorrowEntity: pricingForm.octopusImportTomorrowEntity,
            exportTodayEntity: pricingForm.octopusExportTodayEntity,
            exportTomorrowEntity: pricingForm.octopusExportTomorrowEntity,
          },
          entsoe: { entity: pricingForm.entsoeEntity },
        },
      });
      savedSensors.current = stableStringify(sensors);
      savedPricing.current = JSON.stringify(pricingForm);
      const failed = await checkAndUpdateSensorHealth(getActiveSensorsFlat(sensors));
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

  const saveSystem = async () => {
    setSaving(true);
    try {
      await api.patch('/api/settings', {
        demoMode: { enabled: demoEnabled },
        aiAnalyst: aiForm,
      });
      setSavedDemoEnabled(demoEnabled);
      savedAi.current = JSON.stringify(aiForm);
      window.dispatchEvent(new Event('bess:demo-mode-changed'));
      setToast({ type: 'success', message: 'System settings saved.' });
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
    system: saveSystem,
  };

  // ── tab definitions ───────────────────────────────────────────────────
  const tabs: { id: Tab; label: string; icon: React.ReactNode }[] = [
    { id: 'sensors', label: 'Integrations', icon: <Sun className="h-4 w-4" /> },
    { id: 'pricing', label: 'Electricity Pricing', icon: <Zap className="h-4 w-4" /> },
    { id: 'battery', label: 'Battery', icon: <Battery className="h-4 w-4" /> },
    { id: 'home', label: 'Home', icon: <Home className="h-4 w-4" /> },
    { id: 'system', label: 'System', icon: <Activity className="h-4 w-4" /> },
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
                      checkAndUpdateSensorHealth(getActiveSensorsFlat(sensors));
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
                {tab === 'sensors' && 'Inverter platform selection and sensor entity IDs for each integration.'}
                {tab === 'system' && 'Demo mode, AI analyst, diagnostics and debug tools.'}
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
            <HomeFormSection form={homeForm} onChange={setHomeForm} sensors={getActiveSensorsFlat(sensors)} />
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
              currency={pricingForm.currency}
              weatherEntity={sensors.shared?.['weather_entity']}
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
                inverterForm={inverterForm}
                onInverterChange={(newForm) => {
                  setInverterForm(newForm);
                  // SensorConfigSection handles updating sensors.platform via onChange
                }}
                sensorStatus={sensorStatus}
              />
            </div>
          )}

          {/* ── System ───────────────────────────────────────────────────── */}
          {tab === 'system' && (
            <div className="space-y-6">
              {/* Demo Mode */}
              <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4 space-y-3">
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Demo Mode</h3>
                <div className="flex items-center justify-between">
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    Read-only — optimizer runs but does not control the inverter
                  </p>
                  <button
                    onClick={() => {
                      if (!demoEnabled) {
                        setShowEnableDemoConfirm(true);
                      } else {
                        setDemoEnabled(false);
                      }
                    }}
                    className={`relative inline-flex h-6 w-11 flex-shrink-0 items-center rounded-full transition-colors ${
                      demoEnabled ? 'bg-blue-600' : 'bg-gray-400'
                    }`}
                    role="switch"
                    aria-checked={demoEnabled}
                  >
                    <span
                      className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        demoEnabled ? 'translate-x-6' : 'translate-x-1'
                      }`}
                    />
                  </button>
                </div>
                {demoEnabled && (
                  <div className="p-2 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded-md text-xs text-blue-700 dark:text-blue-300">
                    Currently in demo mode. Savings shown are theoretical estimates.
                  </div>
                )}
                {showEnableDemoConfirm && (
                  <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-300 dark:border-yellow-700 rounded-lg p-4">
                    <p className="text-sm text-yellow-800 dark:text-yellow-300 font-medium">Switch to demo mode?</p>
                    <p className="text-xs text-gray-600 dark:text-gray-400 mt-1">The system will stop sending commands to your inverter.</p>
                    <div className="flex gap-2 mt-3">
                      <button
                        onClick={() => setShowEnableDemoConfirm(false)}
                        className="px-3 py-1.5 text-xs text-gray-600 dark:text-gray-400 bg-gray-200 dark:bg-gray-700 rounded hover:bg-gray-300 dark:hover:bg-gray-600"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={() => {
                          setDemoEnabled(true);
                          setShowEnableDemoConfirm(false);
                        }}
                        className="px-3 py-1.5 text-xs text-white bg-blue-600 rounded hover:bg-blue-500"
                      >
                        Enable Demo Mode
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {/* AI Analyst */}
              <AIAnalystSettings form={aiForm} onChange={setAiForm} />

              {/* Diagnostics */}
              <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4 space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Diagnostics</h3>
                  <button
                    onClick={async () => {
                      try {
                        const filename = await downloadDebugBundle();
                        setToast({ type: 'success', message: `Debug export saved as ${filename}` });
                      } catch {
                        setToast({ type: 'error', message: 'Failed to download debug export.' });
                      }
                    }}
                    className="px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 flex items-center gap-1.5"
                  >
                    <Download className="h-3.5 w-3.5" />
                    <span>Export Debug Data</span>
                  </button>
                </div>
                <SavingsHistorySection />
                <SystemHealthComponent />
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
