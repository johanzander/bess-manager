import { test, expect } from '@playwright/test';

// These tests exercise the InverterStatusDashboard's three-way branching on
// `controlModel` ('tou_register' | 'vpp_power' | 'period_list'). Unlike the
// rest of this suite (e.g. inverter-page.spec.ts), which asserts against
// whatever platform the live mock-HA/backend stack happens to be configured
// for, this spec needs to exercise all three control models in one run —
// something a single live backend instance can't provide simultaneously.
// So each test stubs the /api/inverter/schedule and /api/inverter/status
// responses via page.route() before navigating, then asserts on the
// resulting column set.

const baseSchedule = {
  currentHour: 12,
  inverterPlatform: 'growatt_server_min',
  scheduleData: [],
  tomorrowPeriodGroups: null,
  batteryCapacity: 10,
  lastUpdated: new Date().toISOString(),
};

const baseStatus = {
  batterySoc: 55,
  batterySoe: 5.5,
  batteryChargePower: 0,
  batteryDischargePower: 0,
  pvPower: 0,
  consumption: 0,
  gridPower: 0,
  chargeStopSoc: 100,
  dischargeStopSoc: 10,
  chargePowerRate: 0,
  dischargePowerRate: 0,
  maxChargingPower: 5000,
  maxDischargingPower: 5000,
  gridChargeEnabled: false,
  cycleCost: 0,
  systemStatus: 'ok',
  lastUpdated: new Date().toISOString(),
};

async function mockInverterApis(
  page: import('@playwright/test').Page,
  controlModel: 'tou_register' | 'vpp_power' | 'period_list',
  periodGroup: Record<string, unknown>,
) {
  await page.route('**/api/inverter/schedule', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...baseSchedule,
        controlModel,
        touIntervals: [],
        periodGroups: [
          {
            startTime: '00:00',
            endTime: '01:00',
            dominantIntent: 'IDLE',
            intentCounts: { IDLE: 4 },
            periodCount: 4,
            durationMinutes: 60,
            chargePowerRate: 0,
            dischargePowerRate: 0,
            gridCharge: false,
            ...periodGroup,
          },
        ],
      }),
    });
  });

  await page.route('**/api/inverter/status', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...baseStatus, controlModel }),
    });
  });

  // Not under test here — fulfil with empty-ish payloads so the page
  // doesn't hang or spam console errors while other cards fail to load.
  await page.route('**/api/settings', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      // App.tsx gates all routes behind non-null battery + electricityPrice
      // settings (useSettings hook) -- both must be present for /inverter
      // to render at all.
      body: JSON.stringify({
        battery: { totalCapacity: 10 },
        electricityPrice: { area: 'SE3' },
      }),
    });
  });
  await page.route('**/api/dashboard**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ hourlyData: [] }),
    });
  });
}

test.describe('Inverter schedule display branches on controlModel', () => {
  test('tou_register install shows Mode/Charge%/Discharge%/Grid Charge columns', async ({ page }) => {
    await mockInverterApis(page, 'tou_register', { battMode: 'load_first', chargePowerRate: 40 });

    await page.goto('/inverter');

    await expect(
      page.getByRole('heading', { name: /Schedule Overview/i })
    ).toBeVisible({ timeout: 15_000 });

    await expect(page.getByRole('columnheader', { name: 'Mode' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Charge %', exact: true })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Discharge %' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Grid Charge' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'VPP Power' })).toHaveCount(0);

    // Rendered battery-mode badge for 'load_first'.
    await expect(page.getByText('Load First').first()).toBeVisible();
  });

  test('vpp_power install shows VPP Power column, not Mode/Charge%', async ({ page }) => {
    await mockInverterApis(page, 'vpp_power', { vppPowerPct: 35, vppRemoteControl: true });

    await page.goto('/inverter');

    await expect(
      page.getByRole('heading', { name: /Schedule Overview/i })
    ).toBeVisible({ timeout: 15_000 });

    await expect(page.getByRole('columnheader', { name: 'VPP Power' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Mode' })).toHaveCount(0);
    await expect(page.getByRole('columnheader', { name: 'Charge %' })).toHaveCount(0);
    await expect(page.getByRole('columnheader', { name: 'Discharge %' })).toHaveCount(0);
    await expect(page.getByRole('columnheader', { name: 'Grid Charge' })).toHaveCount(0);

    // Signed percent value renders in the schedule table's VPP column. Scoped
    // to a table cell because the Current Strategy card also shows the current
    // group's percent (e.g. "+35% (Remote)") when the wall clock falls inside
    // that group's time window — a strict getByText() then resolves to 2.
    await expect(page.getByRole('cell', { name: '+35%' })).toBeVisible();
  });

  test('period_list install shows neither Mode nor VPP Power columns', async ({ page }) => {
    await mockInverterApis(page, 'period_list', {});

    await page.goto('/inverter');

    await expect(
      page.getByRole('heading', { name: /Schedule Overview/i })
    ).toBeVisible({ timeout: 15_000 });

    await expect(page.getByRole('columnheader', { name: 'Mode' })).toHaveCount(0);
    await expect(page.getByRole('columnheader', { name: 'VPP Power' })).toHaveCount(0);

    // Only Intent/Solar/Grid/Target SOC columns remain from the base set.
    await expect(page.getByRole('columnheader', { name: 'Intent' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Target SOC' })).toBeVisible();
  });
});
