import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle, ChevronRight, ChevronLeft, Zap } from 'lucide-react';
import api from '../lib/api';
import { INTEGRATIONS } from '../lib/sensorDefinitions';
import { HomeFormSection } from '../components/settings/HomeFormSection';
import type { HomeForm } from '../components/settings/HomeFormSection';
import { PricingFormSection } from '../components/settings/PricingFormSection';
import type { PricingForm } from '../components/settings/PricingFormSection';
import { BatteryFormSection } from '../components/settings/BatteryFormSection';
import type { BatteryForm, InverterForm } from '../components/settings/BatteryFormSection';
import { SensorConfigSection } from '../components/settings/SensorConfigSection';
import type { DiscoveryResult } from '../components/settings/SensorConfigSection';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STEPS = ['Scan', 'Review Sensors', 'Electricity Pricing', 'Battery', 'Home', 'Done'];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const SetupWizardPage: React.FC = () => {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [discovery, setDiscovery] = useState<DiscoveryResult | null>(null);
  const [sensors, setSensors] = useState<Record<string, string>>({});
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [completing, setCompleting] = useState(false);
  const [completeError, setCompleteError] = useState<string | null>(null);

  const [batteryForm, setBatteryForm] = useState<BatteryForm>({
    totalCapacity: 30.0,
    minSoc: 15,
    maxSoc: 95,
    maxChargeDischargePowerKw: 15.0,
    cycleCostPerKwh: 0.50,
    efficiencyCharge: 97,
    efficiencyDischarge: 97,
    temperatureDeratingEnabled: false,
    minActionProfit: 8.0,
  });

  const [inverterForm, setInverterForm] = useState<InverterForm>({
    inverterType: 'MIN',
    deviceId: '',
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

  const [pricingForm, setPricingForm] = useState<PricingForm>({
    provider: 'nordpool_official',
    currency: 'SEK',
    area: '',
    nordpoolConfigEntryId: '',
    nordpoolTodayEntity: '',
    nordpoolTomorrowEntity: '',
    octopusImportTodayEntity: '',
    octopusImportTomorrowEntity: '',
    octopusExportTodayEntity: '',
    octopusExportTomorrowEntity: '',
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
      setPricingForm(f => ({
        ...f,
        ...(d.currency ? { currency: d.currency } : {}),
        ...(d.nordpoolArea ? { area: d.nordpoolArea } : {}),
        ...(d.vatMultiplier ? { vatMultiplier: d.vatMultiplier } : {}),
        ...(d.nordpoolConfigEntryId ? { nordpoolConfigEntryId: d.nordpoolConfigEntryId } : {}),
      }));
      if (d.inverterType) {
        setInverterForm(f => ({ ...f, inverterType: d.inverterType! }));
      }
      if (d.growattDeviceId) {
        setInverterForm(f => ({ ...f, deviceId: d.growattDeviceId! }));
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
      setSensors(allSensors);
      setStep(1);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Discovery failed';
      setScanError(message);
    } finally {
      setScanning(false);
    }
  }, []);

  useEffect(() => {
    // Load existing settings so re-running the wizard preserves user config,
    // then run the sensor scan. Sequencing via .finally() ensures the scan
    // never overwrites the loaded values (scan seeds only auto-detected hints).
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
        maxChargeDischargePowerKw: bat.maxChargePowerKw        ?? f.maxChargeDischargePowerKw,
        cycleCostPerKwh:          bat.cycleCostPerKwh          ?? f.cycleCostPerKwh,
        minActionProfit:          bat.minActionProfitThreshold ?? f.minActionProfit,
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
        provider:        ep.provider          ?? f.provider,
        currency:        home.currency        ?? f.currency,
        area:            elec.area            ?? f.area,
        markupRate:      elec.markupRate      ?? f.markupRate,
        vatMultiplier:   elec.vatMultiplier   ?? f.vatMultiplier,
        additionalCosts: elec.additionalCosts ?? f.additionalCosts,
        taxReduction:    elec.taxReduction    ?? f.taxReduction,
      }));
      if (inv.inverterType) setInverterForm(f => ({ ...f, inverterType: inv.inverterType }));
      if (inv.deviceId) setInverterForm(f => ({ ...f, deviceId: inv.deviceId }));
    }).catch((err: unknown) => {
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
        sensors,
        nordpool_area: discovery.nordpoolArea,
        nordpool_config_entry_id: discovery.nordpoolConfigEntryId,
        growatt_device_id: discovery.growattDeviceId,
      });
      setStep(2);
    } catch (err: unknown) {
      setConfirmError(err instanceof Error ? err.message : 'Configuration failed');
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
        sensors,
        nordpoolArea: pricingForm.area || discovery.nordpoolArea,
        nordpoolConfigEntryId: discovery.nordpoolConfigEntryId,
        growattDeviceId: discovery.growattDeviceId,
        // Battery
        totalCapacity: batteryForm.totalCapacity,
        minSoc: batteryForm.minSoc,
        maxSoc: batteryForm.maxSoc,
        maxChargeDischargePower: batteryForm.maxChargeDischargePowerKw,
        cycleCost: batteryForm.cycleCostPerKwh,
        minActionProfitThreshold: batteryForm.minActionProfit,
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
        area: pricingForm.area || discovery.nordpoolArea,
        provider: pricingForm.provider,
        markupRate: pricingForm.markupRate,
        vatMultiplier: pricingForm.vatMultiplier,
        additionalCosts: pricingForm.additionalCosts,
        taxReduction: pricingForm.taxReduction,
        // Inverter
        inverterType: inverterForm.inverterType,
      });
      setStep(5);
    } catch (err: unknown) {
      setCompleteError(err instanceof Error ? err.message : 'Setup failed');
    } finally {
      setCompleting(false);
    }
  };

  const allRequiredFilled = INTEGRATIONS.every(integration =>
    integration.sensorGroups.every(group =>
      group.sensors.every(s => !s.required || !!sensors[s.key]),
    ),
  );

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
              discovery={discovery}
            />

            {!allRequiredFilled && (
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
                disabled={confirming}
                className="flex items-center space-x-2 px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 font-medium disabled:opacity-60"
              >
                {confirming && <div className="h-4 w-4 border-2 border-white rounded-full border-t-transparent animate-spin" />}
                <span>Next: Electricity Pricing</span>
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>

            {confirmError && (
              <p className="text-sm text-red-600 dark:text-red-400 text-center">{confirmError}</p>
            )}
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

        {/* ── Step 3: Battery ── */}
        {step === 3 && (
          <div className="space-y-3">
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Battery</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                Your inverter model and battery hardware specifications. These values are used by the optimizer to plan charge and discharge schedules.
              </p>
            </div>

            <BatteryFormSection
              form={batteryForm}
              onChange={setBatteryForm}
              inverterForm={inverterForm}
              onInverterChange={setInverterForm}
              currency={pricingForm.currency}
              weatherEntity={sensors['weather_entity']}
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

            <HomeFormSection form={homeForm} onChange={setHomeForm} />

            {completeError && (
              <p className="text-sm text-red-600 dark:text-red-400">{completeError}</p>
            )}
            <div className="flex justify-between pt-2">
              <button onClick={() => setStep(3)}
                className="flex items-center space-x-1 px-4 py-2 text-gray-600 dark:text-gray-300 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700">
                <ChevronLeft className="h-4 w-4" /><span>Back</span>
              </button>
              <button
                onClick={handleComplete}
                disabled={completing}
                className="flex items-center space-x-2 px-6 py-2 bg-green-500 text-white rounded-lg hover:bg-green-600 font-medium disabled:opacity-60"
              >
                {completing && <div className="h-4 w-4 border-2 border-white rounded-full border-t-transparent animate-spin" />}
                <span>Finish Setup</span><ChevronRight className="h-4 w-4" />
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
                <span className="font-medium text-gray-900 dark:text-white">{batteryForm.maxChargeDischargePowerKw} kW</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">Inverter type</span>
                <span className="font-medium text-gray-900 dark:text-white">{inverterForm.inverterType}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">Currency</span>
                <span className="font-medium text-gray-900 dark:text-white">{pricingForm.currency}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">Price provider</span>
                <span className="font-medium text-gray-900 dark:text-white">{pricingForm.provider}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">VAT multiplier</span>
                <span className="font-medium text-gray-900 dark:text-white">{pricingForm.vatMultiplier}</span>
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
          Settings can be updated at any time via the Settings page.
        </p>
      </div>
    </div>
  );
};

export default SetupWizardPage;
