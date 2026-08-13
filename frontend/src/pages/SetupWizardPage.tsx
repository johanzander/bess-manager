import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle, ChevronRight, ChevronLeft, Zap, Eye } from 'lucide-react';
import api from '../lib/api';
import { INTEGRATIONS, INVERTER_INTEGRATION_IDS, SHARED_INTEGRATION_IDS, emptyPerPlatformSensors, getActiveSensorsFlat } from '../lib/sensorDefinitions';
import type { PerPlatformSensors } from '../lib/sensorDefinitions';
import { HomeFormSection } from '../components/settings/HomeFormSection';
import type { HomeForm } from '../components/settings/HomeFormSection';
import { PricingFormSection } from '../components/settings/PricingFormSection';
import type { PricingForm } from '../components/settings/PricingFormSection';
import { BatteryFormSection } from '../components/settings/BatteryFormSection';
import type { BatteryForm } from '../components/settings/BatteryFormSection';
import { SensorConfigSection } from '../components/settings/SensorConfigSection';
import type { DiscoveryResult, InverterForm } from '../components/settings/SensorConfigSection';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STEPS = ['Scan', 'Review Sensors', 'Electricity Pricing', 'Battery', 'Home', 'Control Mode', 'Done'];

// Battery cycle cost approximates wear cost per kWh cycled, so the SEK
// default (0.40) is wrong for other currencies. Mirrors
// core.bess.settings.CYCLE_COST_BY_CURRENCY.
const CYCLE_COST_BY_CURRENCY: Record<string, number> = { SEK: 0.40, EUR: 0.035, GBP: 0.031 };
// Placeholder values (bootstrap SEK default, initial form default) treated as
// "not yet user-configured" so a detected currency can safely replace them.
const UNSET_CYCLE_COST_DEFAULTS = new Set([0.40, 0.50]);

// The pricing field each provider cannot fetch a price without. Mirrors
// backend/api.py's _PROVIDER_REQUIRED_FIELD, which rejects the same gap
// server-side (#549). Without this gate the wizard completes with
// provider=nordpool_official and an empty config entry whenever HA has no
// Nord Pool integration, and every optimizer cycle then aborts.
const PROVIDER_REQUIRED_FIELD: Record<string, keyof PricingForm> = {
  nordpool_official: 'nordpoolConfigEntryId',
  nordpool_hacs: 'nordpoolEntity',
  octopus: 'octopusImportTodayEntity',
  entsoe: 'entsoeEntity',
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const SetupWizardPage: React.FC = () => {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [discovery, setDiscovery] = useState<DiscoveryResult | null>(null);
  const [sensors, setSensors] = useState<PerPlatformSensors>(emptyPerPlatformSensors());
  const [completing, setCompleting] = useState(false);
  const [completeError, setCompleteError] = useState<string | null>(null);
  const [controlMode, setControlMode] = useState<'demo' | 'live' | null>(null);
  const existingSensorsRef = useRef<PerPlatformSensors>(emptyPerPlatformSensors());
  // Only true on a genuinely new install (no prior setup) -- gates the
  // fuse-protection auto-enable below so re-running the wizard on an
  // already-configured system never overrides an explicit user choice.
  const wizardNeededRef = useRef<boolean>(false);

  const [batteryForm, setBatteryForm] = useState<BatteryForm>({
    totalCapacity: 30.0,
    minSoc: 15,
    maxSoc: 95,
    maxChargeDischargePowerKw: 15.0,
    cycleCostPerKwh: 0.50,
    efficiencyCharge: 97,
    efficiencyDischarge: 97,
    temperatureDeratingEnabled: false,
    inverterMaxAcPowerKw: 0,
    inverterAcPowerMargin: 0.05,
    exportCurtailmentEnabled: false,
    exportCurtailmentPriceFloor: 0,
  });

  const [inverterForm, setInverterForm] = useState<InverterForm>({
    inverterPlatform: 'growatt_server_min',
    deviceId: '',
    controlMode: 'tou',
  });

  const [homeForm, setHomeForm] = useState<HomeForm>({
    consumption: 3.5,
    consumptionStrategy: 'sensor',
    maxFuseCurrent: 25,
    voltage: 230,
    safetyMarginFactor: 1.0,
    phaseCount: 3,
    // Turned on in handleScan only once its required sensors are actually
    // detected on a new install -- see wizardNeededRef.
    powerMonitoringEnabled: false,
  });

  const [pricingForm, setPricingForm] = useState<PricingForm>({
    provider: 'nordpool_official',
    currency: 'SEK',
    area: '',
    nordpoolConfigEntryId: '',
    nordpoolEntity: '',
    octopusImportTodayEntity: '',
    octopusImportTomorrowEntity: '',
    octopusExportTodayEntity: '',
    octopusExportTomorrowEntity: '',
    entsoeEntity: '',
    markupRate: 0.08,
    vatMultiplier: 1.25,
    additionalCosts: 0.77,
    taxReduction: 0.2,
    spotMultiplier: 1.0,
    exportSpotMultiplier: 1.0,
  });

  const handleScan = useCallback(async () => {
    setScanning(true);
    setScanError(null);
    setDiscovery(null);
    try {
      const res = await api.post('/api/setup/discover');
      const d: DiscoveryResult = res.data;
      setDiscovery(d);

      // Seed form defaults from auto-detected hints. detectedPhaseCount is a
      // raw count (0-3) of which current_l1/l2/l3 sensors were found — only
      // 3 (all phases) or 1 (single phase, current_l1 only) map to a valid
      // HomeSettings.phase_count (must be 1 or 3; see settings.py __post_init__).
      // A partial 2-of-3 discovery is left at the existing/default phaseCount
      // rather than seeding an invalid value.
      if (d.detectedPhaseCount === 3 || d.detectedPhaseCount === 1) {
        setHomeForm(f => ({ ...f, phaseCount: d.detectedPhaseCount! }));
      }
      // Auto-select pricing provider based on discovered integrations.
      // When the official HA Nordpool integration is present (has a
      // config_entry_id), prefer it.  Otherwise fall back to HACS custom.
      const hasOfficialNordpool = !!d.nordpoolConfigEntryId;
      const hasCustomNordpool = !!d.nordpoolCustomArea;
      const autoProvider = d.octopusFound && !d.nordpoolFound
        ? 'octopus' as const
        : d.entsoeFound && !d.nordpoolFound
          ? 'entsoe' as const
          : hasOfficialNordpool
            ? 'nordpool_official' as const
            : hasCustomNordpool
              ? 'nordpool_hacs' as const
              : undefined;
      // Use area from the matching integration — not mixed
      const autoArea = hasOfficialNordpool ? d.nordpoolArea : d.nordpoolCustomArea;
      setPricingForm(f => ({
        ...f,
        // Only seed spot-multiplier defaults when the provider is newly
        // auto-detected (changing) — never on a re-scan of an already
        // configured provider, or this would clobber a saved custom
        // contract-specific value (e.g. a real Luminus vs. non-Luminus
        // ENTSO-e multiplier) every time the wizard mounts or rescans.
        ...(autoProvider && autoProvider !== f.provider ? (d.pricingDefaults ?? {}) : {}),
        ...(autoProvider ? { provider: autoProvider } : {}),
        ...(d.currency ? { currency: d.currency } : {}),
        ...(autoArea ? { area: autoArea } : {}),
        ...(d.vatMultiplier ? { vatMultiplier: d.vatMultiplier } : {}),
        ...(d.nordpoolConfigEntryId ? { nordpoolConfigEntryId: d.nordpoolConfigEntryId } : {}),
        ...(d.nordpoolCustomEntity ? { nordpoolEntity: d.nordpoolCustomEntity } : {}),
        ...(d.octopusEntities?.importToday ? { octopusImportTodayEntity: d.octopusEntities.importToday } : {}),
        ...(d.octopusEntities?.importTomorrow ? { octopusImportTomorrowEntity: d.octopusEntities.importTomorrow } : {}),
        ...(d.octopusEntities?.exportToday ? { octopusExportTodayEntity: d.octopusEntities.exportToday } : {}),
        ...(d.octopusEntities?.exportTomorrow ? { octopusExportTomorrowEntity: d.octopusEntities.exportTomorrow } : {}),
        ...(d.entsoeEntity ? { entsoeEntity: d.entsoeEntity } : {}),
      }));
      if (d.currency && CYCLE_COST_BY_CURRENCY[d.currency] !== undefined) {
        const cycleCost = CYCLE_COST_BY_CURRENCY[d.currency];
        setBatteryForm(f => (
          UNSET_CYCLE_COST_DEFAULTS.has(f.cycleCostPerKwh)
            ? { ...f, cycleCostPerKwh: cycleCost }
            : f
        ));
      }
      // Auto-select the first detected platform; user can switch if multiple
      const detected = d.detectedInverterPlatforms ?? [];
      const detectedPlatform = detected[0] ?? null;
      if (detectedPlatform) {
        setInverterForm(f => ({ ...f, inverterPlatform: detectedPlatform }));
      }
      if (d.growattDeviceId) {
        setInverterForm(f => ({ ...f, deviceId: d.growattDeviceId! }));
      }
      if (d.huaweiDeviceId) {
        setInverterForm(f => ({ ...f, deviceId: d.huaweiDeviceId! }));
      }

      // Build per-platform sensor structure from discovery results.
      // platformSensors has per-platform dicts; shared sensors come from d.sensors.
      const platform = detectedPlatform ?? inverterForm.inverterPlatform ?? '';
      const newSensors: PerPlatformSensors = emptyPerPlatformSensors(platform);
      const existing = existingSensorsRef.current;

      // Populate each platform's sub-dict from discovered platformSensors
      if (d.platformSensors) {
        for (const [platId, platMap] of Object.entries(d.platformSensors)) {
          if (platId in newSensors && platId !== 'platform' && platId !== 'shared') {
            (newSensors as Record<string, Record<string, string>>)[platId] = { ...platMap };
          }
        }
      }

      // Populate shared sensors from discovery, falling back to existing config
      const sharedSensors: Record<string, string> = {};
      for (const intg of INTEGRATIONS) {
        if (!SHARED_INTEGRATION_IDS.has(intg.id)) continue;
        for (const group of intg.sensorGroups) {
          for (const s of group.sensors) {
            sharedSensors[s.key] = d.sensors[s.key] || (existing.shared ?? {})[s.key] || '';
          }
        }
      }
      newSensors.shared = sharedSensors;

      // For each platform, merge with existing config (fill gaps)
      for (const platId of Object.keys(INVERTER_INTEGRATION_IDS)) {
        const disc = (newSensors as Record<string, Record<string, string>>)[platId] ?? {};
        const prev = (existing as Record<string, Record<string, string>>)[platId] ?? {};
        const merged: Record<string, string> = { ...prev };
        for (const [k, v] of Object.entries(disc)) {
          if (v) merged[k] = v;
        }
        (newSensors as Record<string, Record<string, string>>)[platId] = merged;
      }

      setSensors(newSensors);

      // On a genuinely new install, pre-enable fuse protection once its
      // required sensors are actually present -- never on a wizard re-run
      // for an already-configured system, where this could silently
      // override a choice the user already made.
      const chargeRateSensorFound = !!getActiveSensorsFlat(newSensors).battery_charging_power_rate;
      // Only auto-enable when EVERY phase sensor for the resolved phase count
      // was found -- current_l1 alone (detectedPhaseCount >= 1) is not enough
      // for a 3-phase install (see get_current_phase_loads_w, which crashes
      // on a None current_l2/l3 read otherwise).
      const allPhaseSensorsFound = d.detectedPhaseCount === 3 || d.detectedPhaseCount === 1;
      if (wizardNeededRef.current && chargeRateSensorFound && allPhaseSensorsFound) {
        setHomeForm(f => ({ ...f, powerMonitoringEnabled: true }));
      }

      setStep(1);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Discovery failed';
      setScanError(message);
    } finally {
      setScanning(false);
    }
  }, []);

  useEffect(() => {
    // Record whether this is a genuinely new install (no prior setup) before
    // the settings/scan sequence below runs, so handleScan can gate the
    // fuse-protection auto-enable on it. Awaited alongside the settings load
    // (both feed into the same .finally() below) so it's always resolved
    // before handleScan reads it.
    const statusPromise = api.get('/api/setup/status').then(res => {
      wizardNeededRef.current = !!res.data.wizardNeeded;
    }).catch(() => {});

    // Load existing settings so re-running the wizard preserves user config,
    // then run the sensor scan. Sequencing via .finally() ensures the scan
    // never overwrites the loaded values (scan seeds only auto-detected hints).
    const settingsPromise = api.get('/api/settings').then(res => {
      const s = res.data;
      const bat = s.battery ?? {};
      const home = s.home ?? {};
      const elec = s.electricityPrice ?? {};
      const ep = s.energyProvider ?? {};
      const inv = s.growatt ?? {};

      // Cache existing sensors (per-platform structure) so handleScan can
      // use them as fallback when auto-discovery fails.
      if (s.sensors && typeof s.sensors === 'object' && 'platform' in s.sensors) {
        existingSensorsRef.current = s.sensors as PerPlatformSensors;
      }

      setBatteryForm(f => ({
        ...f,
        totalCapacity:            bat.totalCapacity            ?? f.totalCapacity,
        minSoc:                   bat.minSoc                   ?? f.minSoc,
        maxSoc:                   bat.maxSoc                   ?? f.maxSoc,
        maxChargeDischargePowerKw: bat.maxChargePowerKw        ?? f.maxChargeDischargePowerKw,
        cycleCostPerKwh:          bat.cycleCostPerKwh          ?? f.cycleCostPerKwh,
        efficiencyCharge:         bat.efficiencyCharge         ?? f.efficiencyCharge,
        efficiencyDischarge:      bat.efficiencyDischarge      ?? f.efficiencyDischarge,
        temperatureDeratingEnabled: bat.temperatureDeratingEnabled ?? f.temperatureDeratingEnabled,
      }));
      setHomeForm(f => ({
        ...f,
        consumption:            home.defaultHourly          ?? f.consumption,
        consumptionStrategy:    home.consumptionStrategy    ?? f.consumptionStrategy,
        maxFuseCurrent:         home.maxFuseCurrent         ?? f.maxFuseCurrent,
        voltage:                home.voltage                ?? f.voltage,
        safetyMarginFactor:     home.safetyMargin           ?? f.safetyMarginFactor,
        phaseCount:             home.phaseCount             ?? f.phaseCount,
        powerMonitoringEnabled: home.powerMonitoringEnabled ?? f.powerMonitoringEnabled,
      }));
      setPricingForm(f => ({
        ...f,
        provider:              ep.provider                           ?? f.provider,
        currency:              home.currency                        ?? f.currency,
        // area is read-only / auto-detected — never restore from saved settings;
        // discovery (handleScan) is the single source of truth for price area.
        markupRate:            elec.markupRate                      ?? f.markupRate,
        vatMultiplier:         elec.vatMultiplier                   ?? f.vatMultiplier,
        additionalCosts:       elec.additionalCosts                 ?? f.additionalCosts,
        taxReduction:          elec.taxReduction                    ?? f.taxReduction,
        spotMultiplier:        elec.spotMultiplier                  ?? f.spotMultiplier,
        exportSpotMultiplier:  elec.exportSpotMultiplier            ?? f.exportSpotMultiplier,
        // Restore saved config entry IDs so manual entries survive a wizard re-run
        nordpoolConfigEntryId: ep.nordpoolOfficial?.configEntryId ?? f.nordpoolConfigEntryId,
        nordpoolEntity:        ep.nordpoolHacs?.entity           ?? f.nordpoolEntity,
        // Restore Octopus Energy entity IDs
        octopusImportTodayEntity:    ep.octopus?.importTodayEntity    ?? f.octopusImportTodayEntity,
        octopusImportTomorrowEntity: ep.octopus?.importTomorrowEntity ?? f.octopusImportTomorrowEntity,
        octopusExportTodayEntity:    ep.octopus?.exportTodayEntity    ?? f.octopusExportTodayEntity,
        octopusExportTomorrowEntity: ep.octopus?.exportTomorrowEntity ?? f.octopusExportTomorrowEntity,
        // Restore ENTSO-e entity
        entsoeEntity:          ep.entsoe?.entity                 ?? f.entsoeEntity,
      }));
      const invNew = s.inverter ?? {};
      if (invNew.platform) {
        setInverterForm(f => ({ ...f, inverterPlatform: invNew.platform }));
      }
      if (invNew.controlMode) {
        setInverterForm(f => ({ ...f, controlMode: invNew.controlMode }));
      }
      if (inv.deviceId) setInverterForm(f => ({ ...f, deviceId: inv.deviceId }));
    }).catch((err: unknown) => {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status !== 404) {
        console.error('Failed to load existing settings:', err);
      }
    });

    Promise.all([statusPromise, settingsPromise]).finally(() => {
      handleScan();
    });
  }, [handleScan]);

  const handleConfirm = () => {
    if (!discovery) return;
    setStep(2);
  };

  const handleComplete = async () => {
    if (!discovery) return;
    setCompleting(true);
    setCompleteError(null);
    try {
      await api.post('/api/setup/complete', {
        sensors,
        // Area is read-only / auto-detected — prefer discovery over stale saved value
        nordpoolArea: discovery.nordpoolArea || discovery.nordpoolCustomArea || pricingForm.area,
        // Prefer the user-entered form value; fall back to auto-detected value
        nordpoolConfigEntryId: pricingForm.nordpoolConfigEntryId || discovery.nordpoolConfigEntryId,
        // deviceId is a single shared form field reused across platforms; only
        // attribute it to the platform actually selected, or a stale value
        // typed for one platform gets cross-written into the other's device_id
        // (backend persists whichever field is non-null unconditionally).
        growattDeviceId: inverterForm.inverterPlatform === 'huawei_solar_luna2000'
          ? discovery.growattDeviceId
          : inverterForm.deviceId || discovery.growattDeviceId,
        huaweiDeviceId: inverterForm.inverterPlatform === 'huawei_solar_luna2000'
          ? inverterForm.deviceId || discovery.huaweiDeviceId
          : discovery.huaweiDeviceId,
        // Battery
        totalCapacity: batteryForm.totalCapacity,
        minSoc: batteryForm.minSoc,
        maxSoc: batteryForm.maxSoc,
        maxChargeDischargePower: batteryForm.maxChargeDischargePowerKw,
        cycleCost: batteryForm.cycleCostPerKwh,
        // Home
        currency: pricingForm.currency,
        consumption: homeForm.consumption,
        consumptionStrategy: homeForm.consumptionStrategy,
        maxFuseCurrent: homeForm.maxFuseCurrent,
        voltage: homeForm.voltage,
        safetyMarginFactor: homeForm.safetyMarginFactor,
        phaseCount: homeForm.phaseCount,
        powerMonitoringEnabled: homeForm.powerMonitoringEnabled,
        // Electricity
        area: discovery.nordpoolArea || discovery.nordpoolCustomArea || pricingForm.area,
        provider: pricingForm.provider,
        markupRate: pricingForm.markupRate,
        vatMultiplier: pricingForm.vatMultiplier,
        additionalCosts: pricingForm.additionalCosts,
        taxReduction: pricingForm.taxReduction,
        spotMultiplier: pricingForm.spotMultiplier,
        exportSpotMultiplier: pricingForm.exportSpotMultiplier,
        // Nordpool HACS entity
        nordpoolEntity: pricingForm.nordpoolEntity || undefined,
        // Octopus Energy entity IDs
        octopusImportTodayEntity: pricingForm.octopusImportTodayEntity || undefined,
        octopusImportTomorrowEntity: pricingForm.octopusImportTomorrowEntity || undefined,
        octopusExportTodayEntity: pricingForm.octopusExportTodayEntity || undefined,
        octopusExportTomorrowEntity: pricingForm.octopusExportTomorrowEntity || undefined,
        // ENTSO-e entity
        entsoeEntity: pricingForm.entsoeEntity || undefined,
        // Inverter
        inverterPlatform: inverterForm.inverterPlatform,
        inverterControlMode: inverterForm.controlMode ?? 'tou',
        inverterServiceDomain: inverterForm.serviceDomain ?? '',
        // Control mode
        demoMode: controlMode === 'demo',
      });
      window.dispatchEvent(new Event('bess:demo-mode-changed'));
      setStep(6);
    } catch (err: unknown) {
      setCompleteError(err instanceof Error ? err.message : 'Setup failed');
    } finally {
      setCompleting(false);
    }
  };

  // When the user switches inverter platform, just update inverterForm.
  // The SensorConfigSection handles updating sensors.platform via onChange.
  const handleInverterChange = (newForm: InverterForm) => {
    setInverterForm(newForm);
  };

  const activeInverterIntegrationId = INVERTER_INTEGRATION_IDS[inverterForm.inverterPlatform] ?? 'growatt_server_min';
  const inverterIntegrationIds = new Set(Object.values(INVERTER_INTEGRATION_IDS));

  // Check that all required sensors are filled using the flat merged view
  const activeSensorsFlat = getActiveSensorsFlat(sensors);
  const allRequiredFilled = INTEGRATIONS.every(integration => {
    // Skip inverter integrations that don't match the selected inverter type
    if (inverterIntegrationIds.has(integration.id) && integration.id !== activeInverterIntegrationId) return true;
    return integration.sensorGroups.every(group =>
      group.sensors.every(s => !s.required || !!activeSensorsFlat[s.key]),
    );
  });

  // Required sensors whose only HA entity is disabled (#549). The entity
  // exists but has no state, so BESS cannot read it — the wizard must say
  // "enable it", not "it's missing", and must not let setup complete with
  // a mapping that is guaranteed to 404.
  const requiredSensorKeys = new Set(
    INTEGRATIONS.flatMap(integration => {
      if (inverterIntegrationIds.has(integration.id) && integration.id !== activeInverterIntegrationId) return [];
      return integration.sensorGroups.flatMap(group =>
        group.sensors.filter(s => s.required).map(s => s.key),
      );
    }),
  );
  // Follow the selected inverter tab, not the auto-detected platform — a
  // user with both a cloud and a modbus integration can switch between
  // them, and each has its own set of disabled entities.
  // platformDisabledSensors only has entries for platforms that were actually
  // detected, so a miss means "this platform has no disabled entities" — never
  // fall back to another platform's dict, or the tab would list entity IDs
  // that belong to a different integration.
  const activeDisabledSensors =
    (discovery?.platformDisabledSensors
      ? discovery.platformDisabledSensors[activeInverterIntegrationId]
      : discovery?.disabledSensors)
    ?? {};
  // Compare against the entity ID, not mere presence: a user upgrading from an
  // older wizard run already has the disabled entity persisted, and handleScan
  // restores it from the saved settings. Presence alone would suppress the
  // warning and re-persist the same 404-ing mapping (#549).
  const disabledRequiredEntities = Object.entries(activeDisabledSensors)
    .filter(([key, entityId]) =>
      requiredSensorKeys.has(key)
      && (!activeSensorsFlat[key] || activeSensorsFlat[key] === entityId));

  const pricingRequiredField = PROVIDER_REQUIRED_FIELD[pricingForm.provider];
  const pricingReady = !pricingRequiredField || !!pricingForm[pricingRequiredField];

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

        {/* ── Step 0: Scanning ── */}
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

        {/* ── Step 1: Review Sensors ── */}
        {step === 1 && discovery && (
          <div className="space-y-3">
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Review Sensors</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                Confirm the detected sensor entity IDs. Expand each integration to view or correct individual sensors.
                Fields marked <span className="font-semibold text-orange-500">*</span> are required.
              </p>
            </div>

            {discovery.vatMultiplier != null && (
              <div className="rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-700 px-4 py-2 text-xs text-green-800 dark:text-green-300">
                Sensors and settings pre-filled from detected integrations. Review and correct as needed.
              </div>
            )}

            <SensorConfigSection
              sensors={sensors}
              onChange={setSensors}
              inverterForm={inverterForm}
              onInverterChange={handleInverterChange}
              discovery={discovery}
            />

            {disabledRequiredEntities.length > 0 && (
              <div
                data-testid="disabled-entities-warning"
                className="p-3 bg-orange-50 dark:bg-orange-900/20 border border-orange-200 dark:border-orange-800 rounded-lg text-sm text-orange-700 dark:text-orange-300"
              >
                <p className="font-semibold">
                  These entities exist in Home Assistant but are disabled:
                </p>
                <ul className="mt-1 ml-4 list-disc font-mono text-xs">
                  {disabledRequiredEntities.map(([key, entityId]) => (
                    <li key={key}>{entityId}</li>
                  ))}
                </ul>
                <p className="mt-2">
                  Enable them on the device page in Home Assistant, then press
                  Re-scan. BESS cannot read a disabled entity, so leaving them
                  off would report the system as degraded after setup.
                </p>
              </div>
            )}

            {!allRequiredFilled && disabledRequiredEntities.length === 0 && (
              <div className="p-3 bg-orange-50 dark:bg-orange-900/20 border border-orange-200 dark:border-orange-800 rounded-lg text-sm text-orange-700 dark:text-orange-300">
                Some required sensors (marked with <span className="font-semibold">*</span>) are missing. Expand the integration to configure them manually.
              </div>
            )}

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
                disabled={!allRequiredFilled || disabledRequiredEntities.length > 0}
                className="flex items-center space-x-2 px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 font-medium disabled:opacity-60"
              >
                <span>Next: Electricity Pricing</span>
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 2: Electricity Pricing ── */}
        {step === 2 && (
          <div className="space-y-3">
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Electricity Pricing</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                How the optimizer calculates the real cost of buying and selling electricity. Getting this right is essential for accurate savings calculations.
              </p>
            </div>

            {discovery?.vatMultiplier != null && (
              <div className="rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-700 px-4 py-2 text-xs text-green-800 dark:text-green-300">
                Currency, VAT multiplier and price area pre-filled from detected Nord Pool integration.
              </div>
            )}

            <PricingFormSection form={pricingForm} onChange={setPricingForm} />

            {!pricingReady && (
              <div
                data-testid="pricing-incomplete-warning"
                className="p-3 bg-orange-50 dark:bg-orange-900/20 border border-orange-200 dark:border-orange-800 rounded-lg text-sm text-orange-700 dark:text-orange-300"
              >
                This provider is selected but not configured, so BESS cannot
                fetch any prices and the optimizer will not run. Fill in the
                field above, or pick the provider you actually have installed
                in Home Assistant.
              </div>
            )}

            <div className="flex justify-between pt-2">
              <button onClick={() => setStep(1)}
                className="flex items-center space-x-1 px-4 py-2 text-gray-600 dark:text-gray-300 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700">
                <ChevronLeft className="h-4 w-4" /><span>Back</span>
              </button>
              <button onClick={() => setStep(3)}
                disabled={!pricingReady}
                className="flex items-center space-x-2 px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 font-medium disabled:opacity-40 disabled:cursor-not-allowed">
                <span>Next: Battery</span><ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 3: Battery ── */}
        {step === 3 && (
          <div className="space-y-3">
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Battery</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                Battery hardware specifications. These values are used by the optimizer to plan charge and discharge schedules.
              </p>
            </div>

            <BatteryFormSection
              form={batteryForm}
              onChange={setBatteryForm}
              currency={pricingForm.currency}
              weatherEntity={sensors.shared?.['weather_entity']}
              hideAdvanced
            />

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
          <div className="space-y-3">
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Home</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                Fuse protection prevents the main fuse from blowing when the battery charges at the same time as other high loads. Recommended if your home does not have hardware power limiting.
              </p>
            </div>

            <HomeFormSection form={homeForm} onChange={setHomeForm} sensors={getActiveSensorsFlat(sensors)} />

            <div className="flex justify-between pt-2">
              <button onClick={() => setStep(3)}
                className="flex items-center space-x-1 px-4 py-2 text-gray-600 dark:text-gray-300 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700">
                <ChevronLeft className="h-4 w-4" /><span>Back</span>
              </button>
              <button
                onClick={() => setStep(5)}
                className="flex items-center space-x-2 px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 font-medium"
              >
                <span>Next: Control Mode</span><ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 5: Control Mode ── */}
        {step === 5 && (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
            {/* Config summary */}
            <div className="rounded-lg bg-gray-50 dark:bg-gray-700 p-4 space-y-2 text-sm mb-6">
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
                <span className="font-medium text-gray-900 dark:text-white">{batteryForm.maxChargeDischargePowerKw} kW</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">Inverter type</span>
                <span className="font-medium text-gray-900 dark:text-white">{inverterForm.inverterPlatform}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">Price provider</span>
                <span className="font-medium text-gray-900 dark:text-white">{pricingForm.provider}</span>
              </div>
            </div>

            {/* Control mode choice */}
            <h2 className="text-lg font-bold text-gray-900 dark:text-white">How would you like to start?</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1 mb-4">You can change this anytime in Settings.</p>

            <div className="space-y-3">
              <button
                onClick={() => setControlMode('demo')}
                className={`w-full text-left rounded-lg border-2 p-4 flex items-start gap-3 transition-colors ${
                  controlMode === 'demo'
                    ? 'border-blue-500 bg-blue-900/10'
                    : 'border-gray-300 dark:border-gray-600 hover:border-gray-400 dark:hover:border-gray-500'
                }`}
              >
                <div className={`mt-0.5 w-5 h-5 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${
                  controlMode === 'demo' ? 'border-blue-500 bg-blue-500' : 'border-gray-400 dark:border-gray-500'
                }`}>
                  {controlMode === 'demo' && <CheckCircle className="h-3 w-3 text-white" />}
                </div>
                <div>
                  <div className="font-semibold text-gray-900 dark:text-white flex items-center gap-2">
                    <Eye className="h-4 w-4" /> Demo Mode
                  </div>
                  <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                    Watch how the system would optimize your battery. No commands sent to inverter.
                  </p>
                </div>
              </button>

              <button
                onClick={() => setControlMode('live')}
                className={`w-full text-left rounded-lg border-2 p-4 flex items-start gap-3 transition-colors ${
                  controlMode === 'live'
                    ? 'border-green-500 bg-green-900/10'
                    : 'border-gray-300 dark:border-gray-600 hover:border-gray-400 dark:hover:border-gray-500'
                }`}
              >
                <div className={`mt-0.5 w-5 h-5 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${
                  controlMode === 'live' ? 'border-green-500 bg-green-500' : 'border-gray-400 dark:border-gray-500'
                }`}>
                  {controlMode === 'live' && <CheckCircle className="h-3 w-3 text-white" />}
                </div>
                <div>
                  <div className="font-semibold text-gray-900 dark:text-white flex items-center gap-2">
                    <Zap className="h-4 w-4" /> Live Control
                  </div>
                  <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                    Start optimizing immediately. Sends charge/discharge commands to your inverter.
                  </p>
                </div>
              </button>
            </div>

            <button
              onClick={handleComplete}
              disabled={controlMode === null || completing}
              className="mt-6 w-full px-8 py-3 bg-green-500 text-white rounded-lg hover:bg-green-600 font-semibold text-base disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {completing ? 'Completing...' : controlMode === null ? 'Select a mode to continue' : 'Complete Setup'}
            </button>

            {completeError && (
              <p className="mt-2 text-sm text-red-500">{completeError}</p>
            )}
          </div>
        )}

        {/* ── Step 6: Done ── */}
        {step === 6 && (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6 text-center py-8">
            <CheckCircle className="h-16 w-16 text-green-500 mx-auto mb-4" />
            <h2 className="text-xl font-bold text-gray-900 dark:text-white">Setup Complete!</h2>
            <p className="text-gray-600 dark:text-gray-400 mt-2">
              {controlMode === 'demo'
                ? 'BESS Manager is running in demo mode. You can switch to live control anytime in Settings.'
                : 'BESS Manager is configured and ready to optimize your battery.'}
            </p>
            <button
              onClick={() => navigate('/', { replace: true })}
              className="mt-6 w-full px-8 py-3 bg-green-500 text-white rounded-lg hover:bg-green-600 font-semibold text-base"
            >
              Go to Dashboard
            </button>
          </div>
        )}

        <p className="text-center mt-4 text-xs text-gray-400 dark:text-gray-500">
          Settings can be updated at any time via the Settings page.
        </p>
      </div>
    </div>
  );
};

export default SetupWizardPage;
