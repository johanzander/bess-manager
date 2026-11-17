import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { HomeFormSection } from '../HomeFormSection';
import type { HomeForm } from '../HomeFormSection';

const BASE_FORM: HomeForm = {
  consumption: 3.5,
  consumptionStrategy: 'fixed',
  maxFuseCurrent: 20,
  voltage: 230,
  safetyMarginFactor: 1.0,
  phaseCount: 3,
  powerMonitoringEnabled: true,
  managedLoadSensors: [],
  peakShavingEnabled: false,
  peakShavingStartTime: '07:00',
  peakShavingEndTime: '20:00',
  peakShavingAllDay: false,
  peakShavingDays: [0, 1, 2, 3, 4],
  peakShavingMaxImportKw: 0,
  peakShavingFloorKw: 0,
};

// Sensors a Growatt VPP install has: the charge-rate entity exists (it is the
// TOU-mode register), so sensor presence alone would wrongly promise a guard.
const SENSORS = {
  battery_charging_power_rate: 'number.growatt_charge_rate',
  current_l1: 'sensor.l1',
  current_l2: 'sensor.l2',
  current_l3: 'sensor.l3',
};

const NOTE = /Planning-only protection/i;

describe('HomeFormSection fuse protection (#901)', () => {
  it('warns that protection is planning-only when the platform has no real-time guard', () => {
    render(<HomeFormSection form={BASE_FORM} onChange={vi.fn()} sensors={SENSORS} realtimeFuseGuardSupported={false} />);
    expect(screen.getByText(NOTE)).toBeInTheDocument();
  });

  it('does not warn when the real-time guard runs', () => {
    render(<HomeFormSection form={BASE_FORM} onChange={vi.fn()} sensors={SENSORS} realtimeFuseGuardSupported />);
    expect(screen.queryByText(NOTE)).not.toBeInTheDocument();
  });

  it('does not warn when fuse protection is off', () => {
    render(
      <HomeFormSection
        form={{ ...BASE_FORM, powerMonitoringEnabled: false }}
        onChange={vi.fn()}
        sensors={SENSORS}
        realtimeFuseGuardSupported={false}
      />,
    );
    expect(screen.queryByText(NOTE)).not.toBeInTheDocument();
  });

  it('does not warn when the capability is unknown (setup wizard)', () => {
    render(<HomeFormSection form={BASE_FORM} onChange={vi.fn()} sensors={SENSORS} />);
    expect(screen.queryByText(NOTE)).not.toBeInTheDocument();
  });
});
