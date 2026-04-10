import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, Battery, CheckCircle, ChevronDown, ChevronUp, Home, Settings, Sun, Zap } from 'lucide-react';
import api from '../lib/api';
import { INTEGRATIONS } from '../lib/sensorDefinitions';
import type { HealthStatus } from '../types';

// ---------------------------------------------------------------------------
// Local types
// ---------------------------------------------------------------------------

type Tab = 'home' | 'pricing' | 'solar' | 'growatt';

interface BatteryForm {
  totalCapacity: number;
  minSoc: number;
  maxSoc: number;
  maxChargePowerKw: number;
  maxDischargePowerKw: number;
  cycleCostPerKwh: number;
  chargingPowerRate: number;
  efficiencyCharge: number;
  efficiencyDischarge: number;
  temperatureDeratingEnabled: boolean;
  temperatureDeratingWeatherEntity: string;
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

interface PricingForm {
  currency: string;
  // Energy provider
  provider: string;
  nordpoolConfigEntryId: string;
  nordpoolTodayEntity: string;
  nordpoolTomorrowEntity: string;
  octopusImportTodayEntity: string;
  octopusImportTomorrowEntity: string;
  octopusExportTodayEntity: string;
  octopusExportTomorrowEntity: string;
  // Price calculation
  area: string;
  markupRate: number;
  vatMultiplier: number;
  additionalCosts: number;
  taxReduction: number;
  minProfit: number;
}

interface InverterForm {
  inverterType: string;
  deviceId: string;
}

interface Toast {
  type: 'success' | 'error';
  message: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function numField(
  label: string,
  value: number,
  onChange: (v: number) => void,
  opts: { min?: number; max?: number; step?: number; unit?: string; readOnly?: boolean } = {},
) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
        {label}{opts.unit ? ` (${opts.unit})` : ''}
      </span>
      <input
        type="number"
        min={opts.min}
        max={opts.max}
        step={opts.step ?? 'any'}
        value={value}
        readOnly={opts.readOnly}
        onChange={e => { const n = parseFloat(e.target.value); if (!Number.isNaN(n)) onChange(n); }}
        className={`mt-1 block w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500
          ${opts.readOnly
            ? 'bg-gray-50 dark:bg-gray-700/50 border-gray-200 dark:border-gray-600 text-gray-500 dark:text-gray-400 cursor-default'
            : 'bg-white dark:bg-gray-700 border-gray-300 dark:border-gray-600 text-gray-900 dark:text-white'}`}
      />
    </label>
  );
}

function SectionCard({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100 dark:border-gray-700/60">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-white">{title}</h3>
        {description && (
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{description}</p>
        )}
      </div>
      <div className="px-5 py-4 space-y-4">{children}</div>
    </div>
  );
}

function sensorIcon(status: HealthStatus | null, haValue: boolean) {
  if (!haValue) return <AlertCircle className="h-3.5 w-3.5 text-gray-400 flex-shrink-0" />;
  if (status === 'ERROR' || status === 'WARNING') return <AlertCircle className="h-3.5 w-3.5 text-amber-500 flex-shrink-0" />;
  return <CheckCircle className="h-3.5 w-3.5 text-green-500 flex-shrink-0" />;
}

const EMPTY_BATTERY: BatteryForm = {
  totalCapacity: 0, minSoc: 0, maxSoc: 100,
  maxChargePowerKw: 0, maxDischargePowerKw: 0,
  cycleCostPerKwh: 0, chargingPowerRate: 100,
  efficiencyCharge: 97, efficiencyDischarge: 97,
  temperatureDeratingEnabled: false, temperatureDeratingWeatherEntity: '',
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
  taxReduction: 0, minProfit: 0,
};
const EMPTY_INVERTER: InverterForm = { inverterType: 'MIN', deviceId: '' };

// Sensor keys shown inline in other tabs — hidden from the Inverter sensor list to avoid duplication
const HOME_SENSOR_KEYS = ['current_l1', 'current_l2', 'current_l3', 'discharge_inhibit', '48h_avg_grid_import'];
const SOLAR_SENSOR_KEYS = ['solar_forecast_today', 'solar_forecast_tomorrow'];
const BATTERY_SENSOR_KEYS = ['weather_entity'];
const ALL_INLINE_SENSOR_KEYS = new Set([...HOME_SENSOR_KEYS, ...SOLAR_SENSOR_KEYS, ...BATTERY_SENSOR_KEYS]);

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const SettingsPage: React.FC = () => {

  // ── active tab ─────────────────────────────────────────────────────────
  const [tab, setTab] = useState<Tab>('home');

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
    home: JSON.stringify(homeForm) !== savedHome.current || JSON.stringify(sensors) !== savedSensors.current,
    pricing: JSON.stringify(pricingForm) !== savedPricing.current,
    solar: JSON.stringify(sensors) !== savedSensors.current,
    growatt: JSON.stringify(batteryForm) !== savedBattery.current || JSON.stringify(inverterForm) !== savedInverter.current || JSON.stringify(sensors) !== savedSensors.current,
  };
  // ── loading / saving / error state ────────────────────────────────────
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);

  // ── health status map (sensor_key → status) ────────────────────────────
  const [sensorStatus, setSensorStatus] = useState<Record<string, HealthStatus>>({});

  // ── battery efficiency collapsible ────────────────────────────────────
  const [effOpen, setEffOpen] = useState(false);

  // ── sensor group expand state ─────────────────────────────────────────
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());

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
        maxChargePowerKw: batRes.data.maxChargePowerKw ?? 0,
        maxDischargePowerKw: batRes.data.maxDischargePowerKw ?? 0,
        cycleCostPerKwh: batRes.data.cycleCostPerKwh ?? 0,
        chargingPowerRate: batRes.data.chargingPowerRate ?? 100,
        efficiencyCharge: batRes.data.efficiencyCharge ?? 97,
        efficiencyDischarge: batRes.data.efficiencyDischarge ?? 97,
        temperatureDeratingEnabled: batRes.data.temperatureDeratingEnabled ?? false,
        temperatureDeratingWeatherEntity: batRes.data.temperatureDeratingWeatherEntity ?? '',
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
        currency: homeRes.data.currency ?? 'SEK',
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
        minProfit: elecRes.data.minProfit ?? 0,
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

      // Build sensor status map from health checks
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

  // ── auto-configure (in-place discovery) ──────────────────────────
  const [discovering, setDiscovering] = useState(false);

  const runAutoDiscover = async () => {
    setDiscovering(true);
    try {
      const res = await api.post('/api/setup/discover');
      const d = res.data;

      // Merge discovered sensors (only fill blanks, don't overwrite user edits)
      if (d.sensors && typeof d.sensors === 'object') {
        setSensors(prev => ({
          ...d.sensors,   // discovered values as base
          ...Object.fromEntries(Object.entries(prev).filter(([, v]) => v)), // keep user-entered non-empty values
        }));
      }

      // Apply inverter hints if detected
      if (d.inverterType || d.growattDeviceId) {
        setInverterForm(f => ({
          ...f,
          ...(d.inverterType ? { inverterType: d.inverterType } : {}),
          ...(d.growattDeviceId ? { deviceId: d.growattDeviceId } : {}),
        }));
      }

      // Apply pricing hints if detected
      setPricingForm(f => ({
        ...f,
        ...(d.nordpoolConfigEntryId ? { nordpoolConfigEntryId: d.nordpoolConfigEntryId } : {}),
        ...(d.nordpoolArea ? { area: d.nordpoolArea } : {}),
        ...(d.currency ? { currency: d.currency } : {}),
        ...(d.vatMultiplier ? { vatMultiplier: d.vatMultiplier } : {}),
      }));

      // Apply phase count if detected
      if (d.detectedPhaseCount) {
        setHomeForm(f => ({ ...f, phaseCount: d.detectedPhaseCount }));
      }

      const sensorCount = d.sensors ? Object.keys(d.sensors).filter(k => d.sensors[k]).length : 0;
      setToast({ type: 'success', message: `Auto-configure found ${sensorCount} sensors${d.inverterType ? `, ${d.inverterType} inverter` : ''}${d.nordpoolArea ? `, area ${d.nordpoolArea}` : ''}. Review and save each tab.` });
    } catch (err) {
      setToast({ type: 'error', message: err instanceof Error ? err.message : 'Auto-configure failed' });
    } finally {
      setDiscovering(false);
    }
  };

  // ── save handlers ─────────────────────────────────────────────────────

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

  const saveHome = async () => {
    setSaving(true);
    try {
      await Promise.all([
        api.put('/api/settings/home', homeForm),
        api.put('/api/settings/sensors', { sensors }),
      ]);
      savedHome.current = JSON.stringify(homeForm);
      savedSensors.current = JSON.stringify(sensors);
      const homeFailed = await checkAndUpdateSensorHealth(sensors);
      if (homeFailed.length > 0) {
        setToast({ type: 'error', message: `Saved — but ${homeFailed.length} sensor(s) not found in HA: ${homeFailed.slice(0, 2).join(', ')}${homeFailed.length > 2 ? ` (+${homeFailed.length - 2} more)` : ''}` });
      } else {
        setToast({ type: 'success', message: 'Home settings saved.' });
      }
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
          minProfit: pricingForm.minProfit,
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

  const saveGrowatt = async () => {
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
          maxChargePowerKw: batteryForm.maxChargePowerKw,
          maxDischargePowerKw: batteryForm.maxDischargePowerKw,
          cycleCostPerKwh: batteryForm.cycleCostPerKwh,
          chargingPowerRate: batteryForm.chargingPowerRate,
          efficiencyCharge: batteryForm.efficiencyCharge,
          efficiencyDischarge: batteryForm.efficiencyDischarge,
          estimatedConsumption: 0,
          consumptionStrategy: 'sensor',
          temperatureDeratingEnabled: batteryForm.temperatureDeratingEnabled,
          temperatureDeratingWeatherEntity: batteryForm.temperatureDeratingWeatherEntity,
        }),
        api.put('/api/settings/inverter', {
          inverterType: inverterForm.inverterType,
          deviceId: inverterForm.deviceId || null,
        }),
        api.put('/api/settings/sensors', { sensors }),
      ]);
      savedBattery.current = JSON.stringify(batteryForm);
      savedInverter.current = JSON.stringify(inverterForm);
      savedSensors.current = JSON.stringify(sensors);
      const failed = await checkAndUpdateSensorHealth(sensors);
      if (failed.length > 0) {
        setToast({ type: 'error', message: `Saved — but ${failed.length} sensor(s) not found in HA: ${failed.slice(0, 2).join(', ')}${failed.length > 2 ? ` (+${failed.length - 2} more)` : ''}` });
      } else {
        setToast({ type: 'success', message: 'Growatt settings saved.' });
      }
    } catch (err) {
      setToast({ type: 'error', message: err instanceof Error ? err.message : 'Save failed.' });
    } finally {
      setSaving(false);
    }
  };

  const saveSolar = async () => {
    setSaving(true);
    try {
      await api.put('/api/settings/sensors', { sensors });
      savedSensors.current = JSON.stringify(sensors);
      const solarFailed = await checkAndUpdateSensorHealth(sensors);
      if (solarFailed.length > 0) {
        setToast({ type: 'error', message: `Saved — but ${solarFailed.length} sensor(s) not found in HA: ${solarFailed.slice(0, 2).join(', ')}${solarFailed.length > 2 ? ` (+${solarFailed.length - 2} more)` : ''}` });
      } else {
        setToast({ type: 'success', message: 'Solar forecast settings saved.' });
      }
    } catch (err) {
      setToast({ type: 'error', message: err instanceof Error ? err.message : 'Save failed.' });
    } finally {
      setSaving(false);
    }
  };

  const saveHandlers: Record<Tab, () => Promise<void>> = {
    home: saveHome,
    pricing: savePricing,
    solar: saveSolar,
    growatt: saveGrowatt,
  };

  // ── price preview (at a sample 1.00 spot price) ───────────────────────
  const previewSpot = 1.0;
  const previewBuy = Number(
    ((previewSpot + pricingForm.markupRate) * pricingForm.vatMultiplier + pricingForm.additionalCosts).toFixed(4),
  );
  const previewSell = Number((previewSpot + pricingForm.taxReduction).toFixed(4));

  // ── SOE derived values ────────────────────────────────────────────────
  const minSoeKwh = (batteryForm.totalCapacity * batteryForm.minSoc) / 100;
  const maxSoeKwh = (batteryForm.totalCapacity * batteryForm.maxSoc) / 100;

  // ── tab definitions ───────────────────────────────────────────────────
  const tabs: { id: Tab; label: string; icon: React.ReactNode }[] = [
    { id: 'home', label: 'Home', icon: <Home className="h-4 w-4" /> },
    { id: 'pricing', label: 'Electricity Pricing', icon: <Zap className="h-4 w-4" /> },
    { id: 'solar', label: 'Solar Forecast', icon: <Sun className="h-4 w-4" /> },
    { id: 'growatt', label: 'Growatt', icon: <Battery className="h-4 w-4" /> },
  ];

  // ── helpers ───────────────────────────────────────────────────────────
  const txtInput = (
    label: string,
    value: string,
    onChange: (v: string) => void,
    placeholder = '',
  ) => (
    <label className="block">
      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">{label}</span>
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={e => onChange(e.target.value)}
        className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
    </label>
  );

  const radioGroup = <T extends string>(
    label: string,
    options: { value: T; label: string }[],
    value: T,
    onChange: (v: T) => void,
  ) => (
    <div className="space-y-1">
      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">{label}</span>
      <div className="flex flex-wrap gap-x-5 gap-y-1 pt-1">
        {options.map(opt => (
          <label key={opt.value} className="flex items-center space-x-2 cursor-pointer">
            <input
              type="radio"
              name={label}
              value={opt.value}
              checked={value === opt.value}
              onChange={() => onChange(opt.value)}
              className="text-blue-500"
            />
            <span className="text-sm text-gray-700 dark:text-gray-300">{opt.label}</span>
          </label>
        ))}
      </div>
    </div>
  );

  const toggle = (label: string, value: boolean, onChange: (v: boolean) => void) => (
    <div className="flex items-center justify-between">
      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">{label}</span>
      <button
        type="button"
        onClick={() => onChange(!value)}
        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 ${value ? 'bg-blue-500' : 'bg-gray-300 dark:bg-gray-600'}`}
      >
        <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${value ? 'translate-x-6' : 'translate-x-1'}`} />
      </button>
    </div>
  );

  const inlineSensor = (sKey: string, label: string) => {
    const val = sensors[sKey] ?? '';
    const isMissing = !val;
    const status = sensorStatus[sKey] ?? null;
    return (
      <div key={sKey} className={`flex flex-col sm:flex-row sm:items-center gap-1 p-2 rounded-lg ${isMissing ? 'bg-gray-50 dark:bg-gray-700/30' : 'bg-gray-50 dark:bg-gray-700/50'}`}>
        <div className="flex items-center gap-1.5 sm:w-52 flex-shrink-0">
          {sensorIcon(status, !isMissing)}
          <span className="text-xs font-medium text-gray-600 dark:text-gray-300">{label}</span>
        </div>
        <input
          type="text"
          value={val}
          placeholder={isMissing ? 'Not detected — enter entity ID' : ''}
          onChange={e => setSensors(prev => ({ ...prev, [sKey]: e.target.value }))}
          className="flex-1 text-xs px-2 py-1 rounded border font-mono border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-400"
        />
      </div>
    );
  };

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
                  onClick={() => setTab(t.id)}
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
                {tab === 'home' && 'Home electrical setup and energy consumption.'}
                {tab === 'pricing' && 'Fetch and convert electricity spot prices to buy/sell prices.'}
                {tab === 'solar' && 'Solcast forecast for charge/discharge planning around expected solar.'}
                {tab === 'growatt' && 'Growatt inverter type, battery parameters and sensor entity IDs.'}
              </p>
              <div className="flex items-center gap-2 flex-shrink-0">
                <button
                  onClick={runAutoDiscover}
                  disabled={discovering}
                  className="px-3 py-1 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-400 text-xs font-medium hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors whitespace-nowrap disabled:opacity-50 flex items-center gap-1.5"
                >
                  {discovering && <div className="h-3 w-3 border-2 border-gray-500 rounded-full border-t-transparent animate-spin" />}
                  Auto-Configure
                </button>
                <button
                  onClick={saveHandlers[tab]}
                  disabled={saving || !isDirty[tab]}
                  className="px-4 py-1 bg-blue-500 text-white rounded-lg hover:bg-blue-600 font-medium text-xs disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
                >
                  {saving && <div className="h-3 w-3 border-2 border-white rounded-full border-t-transparent animate-spin" />}
                  <span>Save</span>
                </button>
              </div>
            </div>
          </div>

          {/* ── Home & Grid ──────────────────────────────────────────────── */}          {tab === 'home' && (
            <div className="space-y-3">
              <SectionCard
                title="Home Consumption"
              >
                {radioGroup(
                  'Consumption strategy',
                  [
                    { value: 'sensor', label: '48h average grid import sensor' },
                    { value: 'fixed', label: 'Fixed value' },
                    { value: 'influxdb_7d_avg', label: 'InfluxDB 7-day rolling average' },
                  ],
                  homeForm.consumptionStrategy,
                  v => setHomeForm(f => ({ ...f, consumptionStrategy: v })),
                )}
                {homeForm.consumptionStrategy === 'sensor' && (
                  <div className="space-y-2 pt-1">
                    <p className="text-xs text-gray-500 dark:text-gray-400">Uses the rolling 48-hour average grid import sensor as the hourly consumption estimate.</p>
                    {inlineSensor('48h_avg_grid_import', '48h Avg Grid Import sensor')}
                  </div>
                )}
                {homeForm.consumptionStrategy === 'fixed' && (
                  <div className="pt-1">
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">Always uses the value below — no sensor required.</p>
                    {numField('Default Hourly Consumption', homeForm.consumption,
                      v => setHomeForm(f => ({ ...f, consumption: v })), { unit: 'kWh', min: 0, step: 0.1 })}
                  </div>
                )}
                {homeForm.consumptionStrategy === 'influxdb_7d_avg' && (
                  <div className="space-y-2 pt-1">
                    <p className="text-xs text-gray-500 dark:text-gray-400">Queries InfluxDB for the past 7 days of the local load power sensor and uses the hourly average profile. If no data is found, optimization will fail explicitly.</p>
                    {inlineSensor('local_load_power', 'Local Load Power sensor')}
                  </div>
                )}
              </SectionCard>

              <SectionCard
                title="Power Monitoring"
                description="Prevents the optimizer from scheduling charges or discharges that would blow your main fuse. Enable to configure."
              >
                {toggle('Enable grid overload protection', homeForm.powerMonitoringEnabled,
                  v => setHomeForm(f => ({ ...f, powerMonitoringEnabled: v })))}
                {homeForm.powerMonitoringEnabled && (
                  <>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-1">
                      {numField('Fuse Current', homeForm.maxFuseCurrent,
                        v => setHomeForm(f => ({ ...f, maxFuseCurrent: Math.round(v) })), { unit: 'A', min: 1, step: 1 })}
                      {numField('Voltage', homeForm.voltage,
                        v => setHomeForm(f => ({ ...f, voltage: Math.round(v) })), { unit: 'V', min: 100, step: 1 })}
                      {numField('Safety Margin Factor', homeForm.safetyMarginFactor,
                        v => setHomeForm(f => ({ ...f, safetyMarginFactor: v })), { unit: '0.0–1.0', min: 0, max: 1, step: 0.01 })}
                    </div>
                    <div className="pt-1">
                      {radioGroup(
                        'Phase count',
                        [{ value: '1', label: '1-phase' }, { value: '3', label: '3-phase' }],
                        String(homeForm.phaseCount),
                        v => setHomeForm(f => ({ ...f, phaseCount: parseInt(v, 10) })),
                      )}
                    </div>
                    <div className="space-y-2 pt-1">
                      <p className="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">Phase current sensors</p>
                      {inlineSensor('current_l1', 'Phase L1 Current')}
                      {homeForm.phaseCount === 3 && inlineSensor('current_l2', 'Phase L2 Current')}
                      {homeForm.phaseCount === 3 && inlineSensor('current_l3', 'Phase L3 Current')}
                    </div>
                  </>
                )}
              </SectionCard>

              <SectionCard
                title="EV Charging"
                description="When configured, BESS will not discharge the battery while your EV is charging. Auto-detected from Zaptec (zap*_is_charging), Tibber, Easee or Wallbox binary sensors."
              >
                {inlineSensor('discharge_inhibit', 'Discharge Inhibit sensor')}
              </SectionCard>

            </div>
          )}

          {/* ── Solar Forecast ───────────────────────────────────────────── */}
          {tab === 'solar' && (
            <div className="space-y-3">
              <SectionCard
                title="Solar Forecast"
                description="Optional — PV production forecast from Solcast for Home Assistant. Used to plan charge/discharge strategy around expected solar generation."
              >
                {inlineSensor('solar_forecast_today', 'Forecast Today (kWh)')}
                {inlineSensor('solar_forecast_tomorrow', 'Forecast Tomorrow (kWh)')}
              </SectionCard>
            </div>
          )}

          {/* ── Electricity Pricing ──────────────────────────────────────── */}
          {tab === 'pricing' && (
            <div className="space-y-3">
              <SectionCard
                title="Price Source"
                description="Where spot prices come from. Nord Pool (official) uses the HA integration's config entry ID. Nord Pool (custom sensor) reads from two sensor entities. Octopus Energy uses event entities from the Octopus Energy HACS integration."
              >
                {radioGroup(
                  'Provider',
                  [
                    { value: 'nordpool_official', label: 'Nord Pool (official HA integration)' },
                    { value: 'nordpool', label: 'Nord Pool (custom sensor)' },
                    { value: 'octopus', label: 'Octopus Energy' },
                  ],
                  pricingForm.provider,
                  v => setPricingForm(f => ({ ...f, provider: v })),
                )}
                {pricingForm.provider === 'nordpool_official' && (
                  <div className="pt-1">
                    {txtInput('Config Entry ID', pricingForm.nordpoolConfigEntryId,
                      v => setPricingForm(f => ({ ...f, nordpoolConfigEntryId: v })), 'e.g. abc123…')}
                  </div>
                )}
                {pricingForm.provider === 'nordpool' && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
                    {txtInput('Today entity', pricingForm.nordpoolTodayEntity,
                      v => setPricingForm(f => ({ ...f, nordpoolTodayEntity: v })), 'sensor.nordpool_…')}
                    {txtInput('Tomorrow entity', pricingForm.nordpoolTomorrowEntity,
                      v => setPricingForm(f => ({ ...f, nordpoolTomorrowEntity: v })), 'sensor.nordpool_…')}
                  </div>
                )}
                {pricingForm.provider === 'octopus' && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
                    {txtInput('Import today entity', pricingForm.octopusImportTodayEntity,
                      v => setPricingForm(f => ({ ...f, octopusImportTodayEntity: v })))}
                    {txtInput('Import tomorrow entity', pricingForm.octopusImportTomorrowEntity,
                      v => setPricingForm(f => ({ ...f, octopusImportTomorrowEntity: v })))}
                    {txtInput('Export today entity', pricingForm.octopusExportTodayEntity,
                      v => setPricingForm(f => ({ ...f, octopusExportTodayEntity: v })))}
                    {txtInput('Export tomorrow entity', pricingForm.octopusExportTomorrowEntity,
                      v => setPricingForm(f => ({ ...f, octopusExportTomorrowEntity: v })))}
                  </div>
                )}
                {pricingForm.provider !== 'octopus' && (
                  <div className="pt-1">
                    {txtInput('Price Area', pricingForm.area,
                      v => setPricingForm(f => ({ ...f, area: v })), 'e.g. SE4, NO1, DK1, GB')}
                  </div>
                )}
                <label className="block">
                  <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Currency</span>
                  <select
                    value={pricingForm.currency}
                    onChange={e => setPricingForm(f => ({ ...f, currency: e.target.value }))}
                    className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {['SEK', 'NOK', 'DKK', 'EUR', 'GBP'].map(c => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                </label>
              </SectionCard>

              <SectionCard
                title="Price Calculation"
                description={pricingForm.provider === 'octopus'
                  ? 'Octopus prices are already final (VAT-inclusive, GBP/kWh). Only tax reduction and min profit apply.'
                  : 'How the raw spot price is turned into your actual buy and sell prices. Formula: buy = (spot + markup) × VAT + additional costs.'}
              >
                {pricingForm.provider !== 'octopus' && (
                  <>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      {numField('Markup Rate', pricingForm.markupRate,
                        v => setPricingForm(f => ({ ...f, markupRate: v })), { unit: `${pricingForm.currency}/kWh (ex-VAT)`, min: 0, step: 0.001 })}
                      {numField('VAT Multiplier', pricingForm.vatMultiplier,
                        v => setPricingForm(f => ({ ...f, vatMultiplier: v })), { unit: '1.25 = 25% VAT', min: 1, step: 0.01 })}
                      {numField('Additional Costs', pricingForm.additionalCosts,
                        v => setPricingForm(f => ({ ...f, additionalCosts: v })), { unit: `${pricingForm.currency}/kWh (grid fee + energy tax, VAT-inclusive)`, min: 0, step: 0.001 })}
                    </div>
                    <div className="rounded-lg bg-gray-50 dark:bg-gray-700/50 px-4 py-3 text-sm space-y-1.5">
                      <p className="text-xs text-gray-500 dark:text-gray-400">Preview at spot = 1.00 — formula: (spot + markup) × VAT + additional</p>
                      <div className="flex justify-between font-medium">
                        <span className="text-gray-700 dark:text-gray-200">Buy price</span>
                        <span className="text-blue-600 dark:text-blue-400">{previewBuy.toFixed(2)} {pricingForm.currency}/kWh</span>
                      </div>
                      <div className="flex justify-between font-medium">
                        <span className="text-gray-700 dark:text-gray-200">Sell price</span>
                        <span className="text-green-600 dark:text-green-400">{previewSell.toFixed(2)} {pricingForm.currency}/kWh</span>
                      </div>
                    </div>
                  </>
                )}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {numField('Tax Reduction', pricingForm.taxReduction,
                    v => setPricingForm(f => ({ ...f, taxReduction: v })), { unit: `${pricingForm.currency}/kWh credit on sold energy`, min: 0, step: 0.001 })}
                  {numField('Min Action Profit', pricingForm.minProfit,
                    v => setPricingForm(f => ({ ...f, minProfit: v })), { unit: `${pricingForm.currency} — skip cycles below this gain`, min: 0, step: 0.1 })}
                </div>
              </SectionCard>
            </div>
          )}

          {/* ── Growatt ─────────────────────────────────────────────────── */}
          {tab === 'growatt' && (
            <div className="space-y-3">
              <SectionCard
                title="Inverter Type"
                description="Select your Growatt inverter series (auto-detected during setup)."
              >
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    {radioGroup(
                      'Inverter type',
                      [{ value: 'MIN', label: 'MIN (AC-coupled)' }, { value: 'SPH', label: 'SPH (DC-coupled)' }],
                      inverterForm.inverterType,
                      v => setInverterForm(f => ({ ...f, inverterType: v })),
                    )}
                  </div>
                  {txtInput('Device ID', inverterForm.deviceId,
                    v => setInverterForm(f => ({ ...f, deviceId: v })), 'Growatt device ID')}
                </div>
              </SectionCard>

              <SectionCard
                title="Capacity & SOC Limits"
                description="Total battery capacity in kWh — set this to match your actual battery exactly. Min/Max SOC are read from your Growatt inverter settings and displayed here for reference; BESS does not write these limits."
              >
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  {numField('Total Capacity', batteryForm.totalCapacity,
                    v => setBatteryForm(f => ({ ...f, totalCapacity: v })), { unit: 'kWh', min: 1, step: 0.1 })}
                  {numField('Min SOC', batteryForm.minSoc,
                    v => setBatteryForm(f => ({ ...f, minSoc: v })), { unit: '%', min: 0, max: 100, step: 1 })}
                  {numField('Max SOC', batteryForm.maxSoc,
                    v => setBatteryForm(f => ({ ...f, maxSoc: v })), { unit: '%', min: 0, max: 100, step: 1 })}
                </div>
              </SectionCard>

              <SectionCard
                title="Power"
                description="Caps the maximum power the optimizer can request from or to the battery. Set these to match your inverter and battery hardware limits."
              >
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {numField('Max Charge Power', batteryForm.maxChargePowerKw,
                    v => setBatteryForm(f => ({ ...f, maxChargePowerKw: v })), { unit: 'kW', min: 0, step: 0.1 })}
                  {numField('Max Discharge Power', batteryForm.maxDischargePowerKw,
                    v => setBatteryForm(f => ({ ...f, maxDischargePowerKw: v })), { unit: 'kW', min: 0, step: 0.1 })}
                </div>
              </SectionCard>

              {/* Sensor entity IDs – flat card with integrated collapsibles */}
              <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
                <div className="px-5 py-4 border-b border-gray-100 dark:border-gray-700/60">
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Sensor Entity IDs</h3>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                    Entity IDs for each data source. Expand a category to view and edit.
                  </p>
                </div>
                <div className="divide-y divide-gray-100 dark:divide-gray-700/50">
                  {INTEGRATIONS.filter(intg => intg.sensorGroups.length > 0 && !intg.sensorGroups.flatMap(g => g.sensors).some(s => ALL_INLINE_SENSOR_KEYS.has(s.key))).map(intg => {
                    const allSensorKeys = intg.sensorGroups.flatMap(g => g.sensors.map(s => s.key));
                    const configuredCount = allSensorKeys.filter(k => sensors[k]).length;
                    const totalCount = allSensorKeys.length;
                    const missingRequired = intg.sensorGroups.flatMap(g => g.sensors).filter(s => s.required && !sensors[s.key]).length;
                    const isFullyConfigured = configuredCount === totalCount;
                    return (
                    <div key={intg.id}>
                      <button
                        type="button"
                        onClick={() => setExpandedGroups(prev => {
                          const next = new Set(prev);
                          if (next.has(intg.id)) next.delete(intg.id); else next.add(intg.id);
                          return next;
                        })}
                        className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-gray-50 dark:hover:bg-gray-700/40 transition-colors text-left"
                      >
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-sm font-medium text-gray-900 dark:text-white">{intg.name}</span>
                            {intg.required && (
                              <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300">REQUIRED</span>
                            )}
                            {missingRequired > 0 ? (
                              <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-orange-100 dark:bg-orange-900/30 text-orange-600 dark:text-orange-400">{missingRequired} missing</span>
                            ) : isFullyConfigured ? (
                              <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400">{configuredCount}/{totalCount} configured</span>
                            ) : (
                              <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400">{configuredCount}/{totalCount} configured</span>
                            )}
                          </div>
                          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{intg.description}</p>
                        </div>
                        {expandedGroups.has(intg.id)
                          ? <ChevronUp className="h-4 w-4 text-gray-400 flex-shrink-0" />
                          : <ChevronDown className="h-4 w-4 text-gray-400 flex-shrink-0" />}
                      </button>
                      {expandedGroups.has(intg.id) && (
                        <div className="border-t border-gray-100 dark:border-gray-700/50 divide-y divide-gray-100 dark:divide-gray-700/30">
                          {intg.sensorGroups.map(group => (
                            <div key={group.name} className="px-5 py-3 space-y-2">
                              <p className="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">{group.name}</p>
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
                                      {sensorIcon(status, !isMissing)}
                                      <span className="text-xs font-medium text-gray-600 dark:text-gray-300">
                                        {s.label}
                                      </span>
                                      {s.required && (
                                        <span className="text-[9px] text-orange-500 dark:text-orange-400 font-medium">*</span>
                                      )}
                                    </div>
                                    <input
                                      type="text"
                                      value={val}
                                      placeholder={isMissing ? 'Not detected — enter entity ID' : ''}
                                      onChange={e => setSensors(prev => ({ ...prev, [s.key]: e.target.value }))}
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

              {/* Advanced settings collapsible */}
              <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
                <button
                  type="button"
                  onClick={() => setEffOpen(o => !o)}
                  className="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-50 dark:hover:bg-gray-700/40 transition-colors text-left"
                >
                  <div>
                    <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Advanced settings</h3>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">Cycle cost, charging rate, efficiency factors and temperature derating</p>
                  </div>
                  {effOpen ? <ChevronUp className="h-4 w-4 text-gray-400 flex-shrink-0" /> : <ChevronDown className="h-4 w-4 text-gray-400 flex-shrink-0" />}
                </button>
                {effOpen && (
                  <div className="border-t border-gray-100 dark:border-gray-700 px-5 py-4 space-y-4">
                    {numField('Cycle Cost', batteryForm.cycleCostPerKwh,
                      v => setBatteryForm(f => ({ ...f, cycleCostPerKwh: v })), { unit: `${pricingForm.currency}/kWh`, min: 0, step: 0.001 })}
                    <p className="text-xs text-gray-500 dark:text-gray-400 -mt-2">Represents battery wear — a small cost added to every kWh cycled. Used by the optimizer to decide whether a charge/discharge cycle is worth doing given the price spread. A higher value makes cycles less attractive and reduces unnecessary wear.</p>
                    {numField('Charging Power Rate', batteryForm.chargingPowerRate,
                      v => setBatteryForm(f => ({ ...f, chargingPowerRate: v })), { unit: '%', min: 0, max: 100, step: 1 })}
                    <p className="text-xs text-gray-500 dark:text-gray-400 -mt-2">AC charge current cap sent directly to the Growatt inverter. 100% means the inverter uses its full rated charge power. The power monitor may reduce this dynamically when current sensors detect the fuse limit is being approached.</p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      {numField('Charge Efficiency', batteryForm.efficiencyCharge,
                        v => setBatteryForm(f => ({ ...f, efficiencyCharge: v })), { unit: '%', min: 0, max: 100, step: 0.1 })}
                      {numField('Discharge Efficiency', batteryForm.efficiencyDischarge,
                        v => setBatteryForm(f => ({ ...f, efficiencyDischarge: v })), { unit: '%', min: 0, max: 100, step: 0.1 })}
                    </div>
                    {toggle('Enable temperature derating', batteryForm.temperatureDeratingEnabled,
                      v => setBatteryForm(f => ({ ...f, temperatureDeratingEnabled: v })))}
                    {batteryForm.temperatureDeratingEnabled && (
                      <>
                        <label className="block">
                          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Weather entity</span>
                          <input
                            type="text"
                            value={batteryForm.temperatureDeratingWeatherEntity}
                            onChange={e => setBatteryForm(f => ({ ...f, temperatureDeratingWeatherEntity: e.target.value }))}
                            placeholder="weather.home"
                            className="mt-1 block w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                          />
                        </label>
                        <div>
                          <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">Derating curve (LFP default, read-only)</p>
                          <div className="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
                            <table className="w-full text-xs">
                              <thead className="bg-gray-50 dark:bg-gray-700/50">
                                <tr>
                                  <th className="px-3 py-1.5 text-left font-medium text-gray-500 dark:text-gray-400">Temperature</th>
                                  <th className="px-3 py-1.5 text-left font-medium text-gray-500 dark:text-gray-400">Max charge rate</th>
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                                {[[-1, 20], [0, 20], [5, 50], [10, 80], [15, 100]].map(([temp, rate]) => (
                                  <tr key={temp} className="bg-white dark:bg-gray-800">
                                    <td className="px-3 py-1.5 text-gray-700 dark:text-gray-300">{temp}°C</td>
                                    <td className="px-3 py-1.5 text-gray-700 dark:text-gray-300">{rate}%</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default SettingsPage;
