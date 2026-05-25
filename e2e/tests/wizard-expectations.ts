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
  inverterType: 'growatt_server_min' | 'growatt_server_sph' | 'solax_modbus_native' | 'solax_modbus_growatt_min' | 'solax_modbus_growatt_sph';
  nordpoolFound: boolean;
  octopusFound: boolean;
  /** Which provider radio should be auto-selected after discovery */
  autoSelectedProvider: 'nordpool_official' | 'nordpool_hacs' | 'octopus';

  // Optional integrations (true = found/auto-filled)
  phaseCount: number | null; // null = no phase sensors
  solcastFound: boolean;
  consumptionForecastFound: boolean;
  dischargeInhibitFound: boolean;
  weatherFound: boolean;
}

export const EXPECTATIONS: Record<string, WizardExpectation> = {
  'ci-wizard-nordpool-min': {
    growattFound: true,
    solaxFound: false,
    inverterType: 'growatt_server_min',
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
    inverterType: 'growatt_server_sph',
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
    inverterType: 'growatt_server_min',
    nordpoolFound: false,
    octopusFound: true,
    autoSelectedProvider: 'octopus',
    phaseCount: null,
    solcastFound: false,
    consumptionForecastFound: false,
    dischargeInhibitFound: false,
    weatherFound: false,
  },
  'ci-wizard-full': {
    growattFound: true,
    solaxFound: false,
    inverterType: 'growatt_server_min',
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
    inverterType: 'growatt_server_min',
    nordpoolFound: true,
    octopusFound: false,
    autoSelectedProvider: 'nordpool_hacs',
    phaseCount: 1,
    solcastFound: true,
    consumptionForecastFound: false,
    dischargeInhibitFound: false,
    weatherFound: true,
  },
  'ci-wizard-octopus-sph': {
    growattFound: true,
    solaxFound: false,
    inverterType: 'growatt_server_sph',
    nordpoolFound: false,
    octopusFound: true,
    autoSelectedProvider: 'octopus',
    phaseCount: 3,
    solcastFound: false,
    consumptionForecastFound: true,
    dischargeInhibitFound: true,
    weatherFound: false,
  },
  'ci-wizard-both-providers': {
    growattFound: true,
    solaxFound: false,
    inverterType: 'growatt_server_min',
    nordpoolFound: true,
    octopusFound: true,
    autoSelectedProvider: 'nordpool_official',
    phaseCount: 1,
    solcastFound: false,
    consumptionForecastFound: false,
    dischargeInhibitFound: true,
    weatherFound: true,
  },
  'ci-wizard-growatt-modbus': {
    growattFound: true,
    solaxFound: true,
    inverterType: 'solax_modbus_growatt_min',
    nordpoolFound: true,
    octopusFound: false,
    autoSelectedProvider: 'nordpool_official',
    phaseCount: 3,
    solcastFound: false,
    consumptionForecastFound: false,
    dischargeInhibitFound: false,
    weatherFound: false,
  },
  'ci-wizard-nordpool-solax': {
    growattFound: false,
    solaxFound: true,
    inverterType: 'solax_modbus_native',
    nordpoolFound: true,
    octopusFound: false,
    autoSelectedProvider: 'nordpool_official',
    phaseCount: null,
    solcastFound: false,
    consumptionForecastFound: false,
    dischargeInhibitFound: false,
    weatherFound: false,
  },
};
