import React, { useState } from 'react';
import { AlertCircle, CheckCircle, ChevronDown, ChevronUp } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../ui/tabs';
import { INTEGRATIONS, INVERTER_INTEGRATION_IDS, SHARED_INTEGRATION_IDS } from '../../lib/sensorDefinitions';
import type { IntegrationDef, PerPlatformSensors } from '../../lib/sensorDefinitions';
import type { HealthStatus } from '../../types';

// ---------------------------------------------------------------------------
// Inverter form (owned here — used by wizard and settings pages)
// ---------------------------------------------------------------------------

export interface InverterForm {
  inverterPlatform: string;
  deviceId: string;
  /** Growatt-via-solax_modbus control strategy. GEN4 default "tou"; GEN3 is
   * always "vpp" server-side regardless of this value. */
  controlMode?: 'tou' | 'vpp';
  /** Override for the HA integration domain vendor service calls target
   * (set_tou_periods, update_time_segment). Empty = the platform's standard
   * domain; set it for an integration exposing the same services under its
   * own domain name. */
  serviceDomain?: string;
  /** Domain currently in effect, computed server-side — display only. */
  resolvedServiceDomain?: string;
}

/** Service-domain override input, shown for the platforms that make vendor
 * service calls at all (Growatt cloud and Huawei). Every other platform
 * drives entities directly, where the domain comes from the entity_id. */
function ServiceDomainField({
  inverterForm,
  onInverterChange,
}: {
  inverterForm: InverterForm;
  onInverterChange: (f: InverterForm) => void;
}) {
  return (
    <label className="block mt-3">
      <span className="text-xs font-medium text-gray-500 dark:text-gray-400">Service domain</span>
      <input
        type="text"
        value={inverterForm.serviceDomain ?? ''}
        placeholder={inverterForm.resolvedServiceDomain || 'integration default'}
        onChange={e => onInverterChange({ ...inverterForm, serviceDomain: e.target.value })}
        className="mt-0.5 block w-full sm:w-72 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 px-3 py-1.5 text-sm font-mono text-gray-800 dark:text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-400"
      />
      <span className="mt-1 block text-[11px] text-gray-500 dark:text-gray-400">
        Leave empty unless another integration provides the same services under
        its own domain — then enter that domain (e.g. a bridge exposing
        <span className="font-mono"> set_tou_periods</span>).
      </span>
    </label>
  );
}

// ---------------------------------------------------------------------------
// Discovery result type (used by the setup wizard)
// ---------------------------------------------------------------------------

export interface DiscoveryResult {
  growattFound: boolean;
  growattDeviceId: string | null;
  solaxFound: boolean;
  solaxHasGrowattTou: boolean;
  solaxHasGrowattGen3: boolean;
  solisFound: boolean;
  huaweiFound: boolean;
  huaweiDeviceId: string | null;
  nordpoolFound: boolean;
  nordpoolArea: string | null;
  nordpoolCustomArea: string | null;
  nordpoolCustomEntity: string | null;
  nordpoolConfigEntryId: string | null;
  octopusFound: boolean;
  octopusEntities?: {
    importToday?: string;
    importTomorrow?: string;
    exportToday?: string;
    exportTomorrow?: string;
  };
  entsoeFound: boolean;
  entsoeEntity: string | null;
  sensors: Record<string, string>;
  platformSensors?: Record<string, Record<string, string>>;
  missingSensors: string[];
  /**
   * Sensor keys left unmapped because their only matching HA entity is
   * disabled (#549).  Distinct from missingSensors: the entity exists, it
   * just has no state until the user switches it on, so the fix is
   * "enable it in HA", not "install something".
   */
  disabledSensors?: Record<string, string>;
  /**
   * Same, but keyed by platform — the user can switch the inverter tab away
   * from the auto-detected platform, and the gate must follow that choice.
   */
  platformDisabledSensors?: Record<string, Record<string, string>>;
  detectedInverterPlatforms?: string[];
  detectedPhaseCount: number | null;
  currency: string | null;
  vatMultiplier: number | null;
  pricingDefaults?: Record<string, number>;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Get the flat sensor map for a specific integration from per-platform sensors. */
function getSensorsForIntegration(
  intg: IntegrationDef,
  sensors: PerPlatformSensors,
): Record<string, string> {
  if (SHARED_INTEGRATION_IDS.has(intg.id)) {
    return sensors.shared ?? {};
  }
  // Inverter integration — use the integration's own platform sub-dict
  return (sensors as Record<string, Record<string, string>>)[intg.id] ?? {};
}

function isIntegrationFound(
  id: string,
  discovery: DiscoveryResult,
  sensors: PerPlatformSensors,
): boolean {
  const shared = sensors.shared ?? {};
  if (id === 'growatt_server_min') return discovery.growattFound;
  if (id === 'growatt_server_sph') return discovery.growattFound;
  if (id === 'solax_modbus_growatt_min') return discovery.solaxHasGrowattTou;
  if (id === 'solax_modbus_growatt_sph') return discovery.solaxHasGrowattGen3;
  if (id === 'solax_modbus_native') return discovery.solaxFound;
  if (id === 'solis_modbus') return discovery.solisFound;
  if (id === 'huawei_solar_luna2000') return discovery.huaweiFound;
  if (id === 'nordpool') return discovery.nordpoolFound;
  if (id === 'phase_current') {
    return !!(shared['current_l1'] || shared['current_l2'] || shared['current_l3']);
  }
  if (id === 'solar_forecast') {
    return !!(shared['solar_forecast_today'] || shared['solar_forecast_tomorrow']);
  }
  if (id === 'weather') return !!shared['weather_entity'];
  if (id === 'consumption_forecast') return !!shared['48h_avg_grid_import'];
  if (id === 'consumption_overlay') return !!shared['consumption_overlay'];
  if (id === 'discharge_inhibit') return !!shared['discharge_inhibit'];
  return false;
}

function integrationSensorCounts(
  integration: IntegrationDef,
  sensorMap: Record<string, string>,
): { configured: number; total: number; missingRequired: number } {
  let configured = 0;
  let total = 0;
  let missingRequired = 0;
  for (const group of integration.sensorGroups) {
    for (const s of group.sensors) {
      total++;
      if (sensorMap[s.key]) configured++;
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
  sensorMap: Record<string, string>,
  sensorStatus: Record<string, HealthStatus>,
) {
  const allSensors = intg.sensorGroups.flatMap(g => g.sensors);
  if (allSensors.length === 0) return null;
  const configured = allSensors.filter(s => sensorMap[s.key]);
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

// IDs of inverter integrations — only one should be visible at a time.
const INVERTER_IDS = new Set(['growatt_server_min', 'growatt_server_sph', 'solax_modbus_growatt_min', 'solax_modbus_growatt_sph', 'solax_modbus_native', 'solis_modbus', 'huawei_solar_luna2000']);

interface Props {
  sensors: PerPlatformSensors;
  onChange: (sensors: PerPlatformSensors) => void;
  // Inverter selection
  inverterForm: InverterForm;
  onInverterChange: (f: InverterForm) => void;
  // Wizard mode — pass discovery result
  discovery?: DiscoveryResult | null;
  // Settings mode — pass health status map
  sensorStatus?: Record<string, HealthStatus>;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SensorConfigSection({ sensors, onChange, inverterForm, onInverterChange, discovery, sensorStatus = {} }: Props) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const wizardMode = discovery != null;

  const toggleId = (id: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  // Derive active inverter integration from the selected type
  const activeInverterIntegrationId = INVERTER_INTEGRATION_IDS[inverterForm.inverterPlatform] ?? 'growatt_server_min';
  const isGrowatt = activeInverterIntegrationId === 'growatt_server_min'
    || activeInverterIntegrationId === 'growatt_server_sph'
    || activeInverterIntegrationId === 'solax_modbus_growatt_min'
    || activeInverterIntegrationId === 'solax_modbus_growatt_sph';

  // Detection flags for the wizard's per-platform status dot.
  //
  // These deliberately do NOT gate selection (#621). Discovery matches on a
  // fixed list of HA integration names (_INVERTER_PLATFORMS), so a supported
  // inverter reached through a custom integration — Huawei LUNA2000/EMMA via
  // huawei_emma_management, say — is simply not recognised. Disabling the
  // undetected platforms left such a user with no selectable platform at all
  // and no way to finish setup. Detection narrows the *defaults*, never the
  // *choices*; the dot tells the user what was found, and they can override it.
  const growattDetected = wizardMode
    ? discovery.growattFound
    : Boolean((sensors.growatt_server_min ?? {})['battery_charging_power_rate'] || (sensors.growatt_server_min ?? {})['grid_charge']);
  const growattModbusDetected = wizardMode
    ? Boolean(discovery.solaxFound && discovery.solaxHasGrowattTou)
    : Boolean((sensors.solax_modbus_growatt_min ?? {})['tou_time_1_enabled']);
  const growattModbusGen3Detected = wizardMode
    ? Boolean(discovery.solaxFound && discovery.solaxHasGrowattGen3)
    : Boolean((sensors.solax_modbus_growatt_sph ?? {})['battery_charging_power_rate']);
  const solaxDetected = wizardMode
    ? Boolean(discovery.solaxFound && !discovery.solaxHasGrowattTou && !discovery.solaxHasGrowattGen3)
    : Boolean((sensors.solax_modbus_native ?? {})['solax_power_control_mode'] || (sensors.solax_modbus_native ?? {})['solax_active_power']);
  const solisDetected = wizardMode
    ? discovery.solisFound
    : Boolean((sensors.solis_modbus ?? {})['solis_charge_start_1']);

  /** Update a sensor value in the correct sub-dict (platform or shared). */
  const handleSensorChange = (integrationId: string, sensorKey: string, value: string) => {
    if (SHARED_INTEGRATION_IDS.has(integrationId)) {
      onChange({
        ...sensors,
        shared: { ...sensors.shared, [sensorKey]: value },
      });
    } else {
      // Inverter integration — write to the integration's platform sub-dict
      const current = (sensors as Record<string, Record<string, string>>)[integrationId] ?? {};
      onChange({
        ...sensors,
        [integrationId]: { ...current, [sensorKey]: value },
      });
    }
  };

  // Derive which Level 1 integration is active
  const isCloudActive = inverterForm.inverterPlatform === 'growatt_server_min' || inverterForm.inverterPlatform === 'growatt_server_sph';
  const isModbusActive = inverterForm.inverterPlatform === 'solax_modbus_growatt_min'
    || inverterForm.inverterPlatform === 'solax_modbus_growatt_sph'
    || inverterForm.inverterPlatform === 'solax_modbus_native';
  const isSolisActive = inverterForm.inverterPlatform === 'solis_modbus';
  const isHuaweiActive = inverterForm.inverterPlatform === 'huawei_solar_luna2000';

  const huaweiDetected = wizardMode
    ? discovery.huaweiFound
    : Boolean((sensors.huawei_solar_luna2000 ?? {})['huawei_working_mode']);

  /** Select a platform, dropping any settings that belong to the previous one.
   *
   * deviceId is a single shared form field but names a different thing per
   * platform (a Growatt cloud serial vs the Huawei battery's HA device_id),
   * and each is persisted to its own settings section. Carrying a value
   * across a switch writes one platform's ID into the other's section, where
   * it is applied to the live controller and addresses a device that does not
   * exist. serviceDomain is platform-specific for the same reason. */
  const selectPlatform = (newType: string) => {
    const changed = newType !== inverterForm.inverterPlatform;
    onInverterChange({
      ...inverterForm,
      inverterPlatform: newType,
      ...(changed ? { deviceId: '', serviceDomain: '' } : {}),
    });
    onChange({ ...sensors, platform: newType });
  };

  const handleIntegrationChange = (integration: 'cloud' | 'modbus' | 'solis' | 'huawei') => {
    if (integration === 'cloud') {
      const newType = 'growatt_server_min';
      selectPlatform(newType);
    } else if (integration === 'solis') {
      const newType = 'solis_modbus';
      selectPlatform(newType);
    } else if (integration === 'huawei') {
      const newType = 'huawei_solar_luna2000';
      selectPlatform(newType);
    } else {
      // Default to solax_modbus_growatt_min if Growatt TOU detected, otherwise native
      const newType = growattModbusDetected ? 'solax_modbus_growatt_min'
        : growattModbusGen3Detected ? 'solax_modbus_growatt_sph'
        : 'solax_modbus_native';
      selectPlatform(newType);
    }
  };

  // Active inverter integration (rendered inside tab content)
  const activeInverterIntegration = INTEGRATIONS.find(intg => intg.id === activeInverterIntegrationId) ?? null;

  // Shared integrations (Nordpool, Solcast, etc. — rendered below platform tabs)
  const sharedIntegrations = INTEGRATIONS.filter(intg => {
    if (intg.sensorGroups.length === 0) return false;
    if (INVERTER_IDS.has(intg.id)) return false;
    return true;
  });

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100 dark:border-gray-700/60">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Integrations & Sensors</h3>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
          Select your inverter platform and review sensor entity IDs for each integration.
        </p>
      </div>

      {/* ── Inverter Platform Selection ──────────────────────────────── */}
      <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-700">
        <p className="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-3">
          Inverter Platform
        </p>

        {/* Level 1: Integration tabs — Growatt Cloud vs SolaX Modbus vs Solis Modbus */}
        {(() => {
          const cloudDetected = growattDetected;
          const modbusDetected = growattModbusDetected || growattModbusGen3Detected || solaxDetected;
          const activeTab = isCloudActive ? 'cloud' : isSolisActive ? 'solis' : isHuaweiActive ? 'huawei' : 'modbus';

          return (
            <Tabs value={activeTab} onValueChange={(v) => handleIntegrationChange(v as 'cloud' | 'modbus' | 'solis' | 'huawei')}>
              <TabsList className="bg-gray-100 dark:bg-gray-700/60">
                <TabsTrigger
                  value="cloud"
                  className="data-[state=active]:bg-white dark:data-[state=active]:bg-gray-600 dark:text-gray-300 dark:data-[state=active]:text-white"
                >
                  <span className="flex items-center gap-1.5">
                    {wizardMode && (
                      <span className={`h-2 w-2 rounded-full flex-shrink-0 ${cloudDetected ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-500'}`} />
                    )}
                    Growatt Cloud
                  </span>
                </TabsTrigger>
                <TabsTrigger
                  value="modbus"
                  className="data-[state=active]:bg-white dark:data-[state=active]:bg-gray-600 dark:text-gray-300 dark:data-[state=active]:text-white"
                >
                  <span className="flex items-center gap-1.5">
                    {wizardMode && (
                      <span className={`h-2 w-2 rounded-full flex-shrink-0 ${modbusDetected ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-500'}`} />
                    )}
                    SolaX Modbus
                  </span>
                </TabsTrigger>
                <TabsTrigger
                  value="solis"
                  className="data-[state=active]:bg-white dark:data-[state=active]:bg-gray-600 dark:text-gray-300 dark:data-[state=active]:text-white"
                >
                  <span className="flex items-center gap-1.5">
                    {wizardMode && (
                      <span className={`h-2 w-2 rounded-full flex-shrink-0 ${solisDetected ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-500'}`} />
                    )}
                    Solis Modbus
                  </span>
                </TabsTrigger>
                <TabsTrigger
                  value="huawei"
                  className="data-[state=active]:bg-white dark:data-[state=active]:bg-gray-600 dark:text-gray-300 dark:data-[state=active]:text-white"
                >
                  <span className="flex items-center gap-1.5">
                    {wizardMode && (
                      <span className={`h-2 w-2 rounded-full flex-shrink-0 ${huaweiDetected ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-500'}`} />
                    )}
                    Huawei
                  </span>
                </TabsTrigger>
              </TabsList>

              {/* Level 2: Model variant pills under each tab */}
              <TabsContent value="cloud">
                <div className="flex flex-wrap items-center gap-2">
                  {([
                    { value: 'growatt_server_min' as const, label: 'MIN/MIC/MOD (AC-coupled)' },
                    { value: 'growatt_server_sph' as const, label: 'MIX/SPA/SPH (DC-coupled)' },
                  ]).map(opt => {
                    const selected = inverterForm.inverterPlatform === opt.value;
                    return (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => {
                          selectPlatform(opt.value);
                        }}
                        className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                          selected
                            ? 'bg-blue-50 dark:bg-blue-900/30 border-blue-300 dark:border-blue-600 text-blue-700 dark:text-blue-300'
                            : 'bg-white dark:bg-gray-700 border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:border-gray-300 dark:hover:border-gray-500'
                        }`}
                      >
                        {opt.label}
                      </button>
                    );
                  })}
                </div>

                {/* Device ID for cloud connection */}
                <label className="block mt-3">
                  <span className="text-xs font-medium text-gray-500 dark:text-gray-400">Device ID</span>
                  <input
                    type="text"
                    value={inverterForm.deviceId}
                    placeholder="Growatt device serial number"
                    onChange={e => onInverterChange({ ...inverterForm, deviceId: e.target.value })}
                    className="mt-0.5 block w-full sm:w-72 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 px-3 py-1.5 text-sm font-mono text-gray-800 dark:text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-400"
                  />
                </label>

                <ServiceDomainField inverterForm={inverterForm} onInverterChange={onInverterChange} />
              </TabsContent>

              <TabsContent value="modbus">
                <div className="flex flex-wrap items-center gap-2">
                  {([
                    { value: 'solax_modbus_native' as const, label: 'SolaX Native', detected: solaxDetected },
                    { value: 'solax_modbus_growatt_min' as const, label: 'Growatt MIN/GEN4', detected: growattModbusDetected },
                    { value: 'solax_modbus_growatt_sph' as const, label: 'Growatt SPH/GEN3', detected: growattModbusGen3Detected },
                  ]).map(opt => {
                    const selected = inverterForm.inverterPlatform === opt.value;
                    return (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => {
                          selectPlatform(opt.value);
                        }}
                        className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                          selected
                            ? 'bg-blue-50 dark:bg-blue-900/30 border-blue-300 dark:border-blue-600 text-blue-700 dark:text-blue-300'
                            : 'bg-white dark:bg-gray-700 border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:border-gray-300 dark:hover:border-gray-500'
                        }`}
                      >
                        <span className="flex items-center gap-1.5">
                          {wizardMode && (
                            <span className={`h-1.5 w-1.5 rounded-full flex-shrink-0 ${opt.detected ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-500'}`} />
                          )}
                          {opt.label}
                        </span>
                      </button>
                    );
                  })}
                </div>

                {/* Growatt-via-solax_modbus control mode (TOU vs VPP) */}
                {inverterForm.inverterPlatform === 'solax_modbus_growatt_min' && (
                  <div className="mt-3">
                    <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
                      Control Mode <span className="text-[9px] text-orange-500 dark:text-orange-400 font-medium">(VPP experimental)</span>
                    </span>
                    <div className="flex flex-wrap items-center gap-2 mt-1">
                      {([
                        { value: 'tou' as const, label: 'TOU Schedule (default)' },
                        { value: 'vpp' as const, label: 'VPP Remote Power' },
                      ]).map(opt => {
                        const selected = (inverterForm.controlMode ?? 'tou') === opt.value;
                        return (
                          <button
                            key={opt.value}
                            type="button"
                            onClick={() => onInverterChange({ ...inverterForm, controlMode: opt.value })}
                            className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                              selected
                                ? 'bg-blue-50 dark:bg-blue-900/30 border-blue-300 dark:border-blue-600 text-blue-700 dark:text-blue-300'
                                : 'bg-white dark:bg-gray-700 border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:border-gray-300 dark:hover:border-gray-500'
                            }`}
                          >
                            {opt.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}
                {inverterForm.inverterPlatform === 'solax_modbus_growatt_sph' && (
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-3">
                    Control mode: <span className="font-medium">VPP Remote Power</span> — GEN3 has no working TOU path, so VPP is the only control mode.
                  </p>
                )}
              </TabsContent>

              <TabsContent value="solis">
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  Solis hybrid inverter via the Pho3niX90/solis_modbus integration
                  (Grid Time of Use v2, local Modbus).
                </p>
              </TabsContent>

              <TabsContent value="huawei">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="px-3 py-1 rounded-full text-xs font-medium border bg-blue-50 dark:bg-blue-900/30 border-blue-300 dark:border-blue-600 text-blue-700 dark:text-blue-300">
                    LUNA2000
                  </span>
                  <span className="text-[9px] text-orange-500 dark:text-orange-400 font-medium">experimental</span>
                </div>

                <label className="block mt-3">
                  <span className="text-xs font-medium text-gray-500 dark:text-gray-400">Device ID</span>
                  <input
                    type="text"
                    value={inverterForm.deviceId}
                    placeholder="Huawei battery device ID"
                    onChange={e => onInverterChange({ ...inverterForm, deviceId: e.target.value })}
                    className="mt-0.5 block w-full sm:w-72 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 px-3 py-1.5 text-sm font-mono text-gray-800 dark:text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-400"
                  />
                </label>

                <ServiceDomainField inverterForm={inverterForm} onInverterChange={onInverterChange} />
              </TabsContent>
            </Tabs>
          );
        })()}

        {/* ── Active inverter sensor groups (inside platform section) ── */}
        {activeInverterIntegration && (() => {
          const intg = activeInverterIntegration;
          const sensorMap = getSensorsForIntegration(intg, sensors);
          const counts = integrationSensorCounts(intg, sensorMap);
          return (
            <div className="mt-4">
              <div className="flex items-center gap-2 mb-3">
                {wizardMode
                  ? discoveryDot(intg, isIntegrationFound(intg.id, discovery, sensors), counts)
                  : healthDot(intg, sensorMap, sensorStatus)}
                <span className="text-xs font-medium text-gray-600 dark:text-gray-300">
                  {counts.configured}/{counts.total} sensors configured
                </span>
              </div>
              <div className="divide-y divide-gray-100 dark:divide-gray-700/30 border border-gray-100 dark:border-gray-700/50 rounded-lg overflow-hidden">
                {intg.sensorGroups.map(group => (
                  <div key={group.name} className="px-4 py-3 space-y-2">
                    <p className="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">
                      {group.name}
                    </p>
                    {group.sensors.map(s => {
                      const val = sensorMap[s.key] ?? '';
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
                            onChange={e => handleSensorChange(intg.id, s.key, e.target.value)}
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
            </div>
          );
        })()}
      </div>

      {/* ── Shared Integration Sensor Lists ─────────────────────────── */}
      <div className="divide-y divide-gray-100 dark:divide-gray-700/50">
        {sharedIntegrations.map(intg => {
          const sensorMap = getSensorsForIntegration(intg, sensors);
          const counts = integrationSensorCounts(intg, sensorMap);
          const expanded = expandedIds.has(intg.id);
          const isFullyConfigured = counts.total > 0 && counts.configured === counts.total;

          const statusDot = wizardMode
            ? discoveryDot(intg, isIntegrationFound(intg.id, discovery, sensors), counts)
            : healthDot(intg, sensorMap, sensorStatus);

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
                        const val = sensorMap[s.key] ?? '';
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
                              onChange={e => handleSensorChange(intg.id, s.key, e.target.value)}
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
