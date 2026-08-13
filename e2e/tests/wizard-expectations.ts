/**
 * Per-scenario expectations for the setup wizard E2E tests.
 *
 * The SCENARIO env var (set by run-e2e.sh / CI) determines which mock-HA
 * scenario is active. Tests use these expectations to validate that the
 * wizard correctly discovers integrations and auto-selects options.
 */

export interface WizardExpectation {
  // Mandatory integrations
  growattFound: boolean;
  solaxFound: boolean;
  /** Solis (solis_modbus) detected. Optional — defaults to false. */
  solisFound?: boolean;
  inverterPlatform: 'growatt_server_min' | 'growatt_server_sph' | 'solax_modbus_native' | 'solax_modbus_growatt_min' | 'solax_modbus_growatt_sph' | 'solis_modbus';
  nordpoolFound: boolean;
  octopusFound: boolean;
  /** ENTSO-e Transparency Platform (e.g. Belpex). Optional — defaults to false. */
  entsoeFound?: boolean;
  /** Which provider radio should be auto-selected after discovery */
  autoSelectedProvider: 'nordpool_official' | 'nordpool_hacs' | 'octopus' | 'entsoe';

  // Optional integrations (true = found/auto-filled)
  phaseCount: number | null; // null = no phase sensors
  solcastFound: boolean;
  consumptionForecastFound: boolean;
  dischargeInhibitFound: boolean;
  weatherFound: boolean;
  /** No current_l1/l2/l3 sensors were discovered (no CT clamps configured) — disables fuse protection regardless of platform capability. Optional, defaults to false. */
  noPhaseSensors?: boolean;

  /**
   * Entity IDs that exist in HA but are disabled, so the sensor step must
   * block and name them (#549). Optional — absent means nothing disabled.
   */
  disabledEntities?: string[];
  /**
   * The selected provider has no usable configuration, so the pricing step
   * must block (#549). Optional, defaults to false.
   */
  pricingBlocked?: boolean;
  /**
   * The sensor step cannot be passed in this scenario (disabled entities),
   * so every later step is unreachable. Tests that navigate past it skip.
   */
  sensorStepBlocked?: boolean;
}

export const EXPECTATIONS: Record<string, WizardExpectation> = {
  'ci-wizard-nordpool-min': {
    growattFound: true,
    solaxFound: false,
    inverterPlatform: 'growatt_server_min',
    nordpoolFound: true,
    octopusFound: false,
    autoSelectedProvider: 'nordpool_official',
    phaseCount: 3,
    solcastFound: false,
    consumptionForecastFound: false,
    dischargeInhibitFound: false,
    weatherFound: false,
  },
  'ci-wizard-nordpool-sph': {
    growattFound: true,
    solaxFound: false,
    inverterPlatform: 'growatt_server_sph',
    nordpoolFound: true,
    octopusFound: false,
    autoSelectedProvider: 'nordpool_official',
    phaseCount: 3,
    solcastFound: false,
    consumptionForecastFound: false,
    dischargeInhibitFound: false,
    weatherFound: false,
  },
  'ci-wizard-octopus': {
    growattFound: true,
    solaxFound: false,
    inverterPlatform: 'growatt_server_min',
    nordpoolFound: false,
    octopusFound: true,
    autoSelectedProvider: 'octopus',
    phaseCount: null,
    solcastFound: false,
    consumptionForecastFound: false,
    dischargeInhibitFound: false,
    weatherFound: false,
  },
  'ci-wizard-entsoe': {
    growattFound: true,
    solaxFound: false,
    inverterPlatform: 'growatt_server_min',
    nordpoolFound: false,
    octopusFound: false,
    entsoeFound: true,
    autoSelectedProvider: 'entsoe',
    phaseCount: null,
    solcastFound: false,
    consumptionForecastFound: false,
    dischargeInhibitFound: false,
    weatherFound: false,
  },
  'ci-wizard-entsoe-frank-126': {
    growattFound: false,
    solaxFound: true,
    inverterPlatform: 'solax_modbus_growatt_min',
    nordpoolFound: false,
    octopusFound: false,
    entsoeFound: true,
    autoSelectedProvider: 'entsoe',
    phaseCount: 3,
    solcastFound: true,
    consumptionForecastFound: false,
    dischargeInhibitFound: false,
    weatherFound: false,
  },
  'ci-wizard-full': {
    growattFound: true,
    solaxFound: false,
    inverterPlatform: 'growatt_server_min',
    nordpoolFound: true,
    octopusFound: false,
    autoSelectedProvider: 'nordpool_official',
    phaseCount: 3,
    solcastFound: true,
    consumptionForecastFound: true,
    dischargeInhibitFound: true,
    weatherFound: true,
  },
  'ci-wizard-nordpool-hacs': {
    growattFound: true,
    solaxFound: false,
    inverterPlatform: 'growatt_server_min',
    nordpoolFound: true,
    octopusFound: false,
    autoSelectedProvider: 'nordpool_hacs',
    phaseCount: 1,
    solcastFound: true,
    consumptionForecastFound: false,
    dischargeInhibitFound: false,
    weatherFound: true,
  },
  'ci-wizard-growatt-sph-cloud-octopus': {
    growattFound: true,
    solaxFound: false,
    inverterPlatform: 'growatt_server_sph',
    nordpoolFound: false,
    octopusFound: true,
    autoSelectedProvider: 'octopus',
    phaseCount: null,
    solcastFound: false,
    consumptionForecastFound: false,
    dischargeInhibitFound: false,
    weatherFound: false,
  },
  'ci-wizard-both-providers': {
    growattFound: true,
    solaxFound: false,
    inverterPlatform: 'growatt_server_min',
    nordpoolFound: true,
    octopusFound: true,
    autoSelectedProvider: 'nordpool_official',
    phaseCount: 1,
    solcastFound: false,
    consumptionForecastFound: false,
    dischargeInhibitFound: true,
    weatherFound: true,
  },
  // inverterPlatform and phaseCount confirmed against a live POST
  // /api/setup/discover run, not the value this entry originally shipped
  // with -- this scenario was never wired into CI, so the wizard's actual
  // detected[0] auto-select (Growatt Cloud, since detected_inverter_platforms
  // lists WS-detected cloud platforms before appending SolaX ones -- see
  // ha_api_controller.py's detected_inverter_platforms assembly) had never
  // been checked against this expectation.
  'ci-wizard-growatt-modbus': {
    growattFound: true,
    solaxFound: true,
    inverterPlatform: 'growatt_server_min',
    nordpoolFound: true,
    octopusFound: false,
    autoSelectedProvider: 'nordpool_official',
    phaseCount: null,
    solcastFound: false,
    consumptionForecastFound: false,
    dischargeInhibitFound: false,
    weatherFound: false,
  },
  // ci-wizard-growatt-modbus-gen3 has no entry here on purpose: its fixture
  // is missing the 5 VPP entities GEN3 (solax_modbus_growatt_sph) always
  // requires -- battery_system_manager.py:291-292 documents GEN3 as
  // VPP-only, no TOU path exists -- so "Next" never enables and the full
  // wizard flow can't complete. It stays covered by test_scenario_discovery.py
  // (backend-only, doesn't need wizard completion) instead of this Playwright
  // suite. See docs/agents/testing.md's Wizard Scenario Matrix note.
  'ci-wizard-nordpool-solax': {
    growattFound: false,
    solaxFound: true,
    inverterPlatform: 'solax_modbus_native',
    nordpoolFound: true,
    octopusFound: false,
    autoSelectedProvider: 'nordpool_official',
    phaseCount: null,
    solcastFound: false,
    consumptionForecastFound: false,
    dischargeInhibitFound: false,
    weatherFound: false,
  },
  'ci-wizard-solis': {
    growattFound: false,
    solaxFound: false,
    solisFound: true,
    inverterPlatform: 'solis_modbus',
    nordpoolFound: true,
    octopusFound: false,
    autoSelectedProvider: 'nordpool_official',
    phaseCount: null,
    solcastFound: false,
    consumptionForecastFound: false,
    dischargeInhibitFound: false,
    weatherFound: false,
  },
  'ci-wizard-growatt-vpp': {
    growattFound: false,
    solaxFound: true,
    inverterPlatform: 'solax_modbus_growatt_sph',
    nordpoolFound: true,
    octopusFound: false,
    autoSelectedProvider: 'nordpool_official',
    phaseCount: 3,
    solcastFound: false,
    consumptionForecastFound: false,
    dischargeInhibitFound: false,
    weatherFound: false,
  },
  /** Real-world regression from issue #118: ridax67's live Growatt GEN4 VPP installation. */
  'ci-wizard-growatt-vpp-ridax-118': {
    growattFound: false,
    solaxFound: true,
    inverterPlatform: 'solax_modbus_growatt_min',
    nordpoolFound: true,
    octopusFound: false,
    autoSelectedProvider: 'nordpool_official',
    phaseCount: null,
    solcastFound: true,
    consumptionForecastFound: false,
    dischargeInhibitFound: false,
    weatherFound: false,
    noPhaseSensors: true,
  },
  /**
   * Real-world regression from issue #549: solax_modbus ships its Total *
   * lifetime counters disabled_by=integration, and this HA has no Nord Pool
   * integration at all. Both wizard gates must hold.
   */
  'ci-wizard-solax-disabled-lifetime': {
    growattFound: false,
    solaxFound: true,
    inverterPlatform: 'solax_modbus_growatt_min',
    nordpoolFound: false,
    octopusFound: false,
    autoSelectedProvider: 'nordpool_official',
    phaseCount: 3,
    solcastFound: false,
    consumptionForecastFound: false,
    dischargeInhibitFound: false,
    weatherFound: false,
    disabledEntities: [
      'sensor.growatt_inverter_solax_total_grid_import',
      'sensor.growatt_inverter_solax_total_grid_export',
      'sensor.growatt_inverter_solax_total_solar_energy',
      'sensor.growatt_inverter_solax_total_battery_input_energy',
      'sensor.growatt_inverter_solax_total_battery_output_energy',
    ],
    sensorStepBlocked: true,
  },
  /**
   * Issue #549, second half: all inverter sensors enabled, but HA has no
   * price integration at all — the pricing step must block rather than
   * persist the defaulted nordpool_official with an empty config entry.
   */
  'ci-wizard-no-price-provider': {
    growattFound: false,
    solaxFound: true,
    inverterPlatform: 'solax_modbus_growatt_min',
    nordpoolFound: false,
    octopusFound: false,
    autoSelectedProvider: 'nordpool_official',
    phaseCount: 3,
    solcastFound: false,
    consumptionForecastFound: false,
    dischargeInhibitFound: false,
    weatherFound: false,
    pricingBlocked: true,
  },
};
