import { test, expect } from '@playwright/test';

// #813: the Planned Schedule shows the planned managed load (e.g. an EV
// session from Planned Consumption Changes) per period group. Stubbed like
// inverter-schedule-control-model.spec.ts: a live mock-HA stack has no
// overlay block, so the chip logic needs a controlled payload.

const group = (over: Record<string, unknown>) => ({
  startTime: '00:00',
  endTime: '01:00',
  dominantIntent: 'LOAD_SUPPORT',
  intentCounts: { LOAD_SUPPORT: 4 },
  periodCount: 4,
  durationMinutes: 60,
  chargePowerRate: 0,
  dischargePowerRate: 0,
  gridCharge: false,
  battMode: 'load_first',
  plannedLoadKwh: 0,
  ...over,
});

async function mockApis(page: import('@playwright/test').Page, periodGroups: unknown[]) {
  await page.route('**/api/inverter/schedule', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        currentHour: 12,
        inverterPlatform: 'growatt_server_min',
        controlModel: 'tou_register',
        touIntervals: [],
        scheduleData: [],
        periodGroups,
        tomorrowPeriodGroups: null,
        batteryCapacity: 10,
        lastUpdated: new Date().toISOString(),
      }),
    });
  });
  await page.route('**/api/inverter/status', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        batterySoc: 55, batterySoe: 5.5, batteryChargePower: 0, batteryDischargePower: 0,
        pvPower: 0, consumption: 0, gridPower: 0, chargeStopSoc: 100, dischargeStopSoc: 10,
        chargePowerRate: 0, dischargePowerRate: 0, maxChargingPower: 5000,
        maxDischargingPower: 5000, gridChargeEnabled: false, cycleCost: 0,
        systemStatus: 'ok', lastUpdated: new Date().toISOString(),
        controlModel: 'tou_register',
      }),
    });
  });
  await page.route('**/api/settings', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ battery: { totalCapacity: 10 }, electricityPrice: { area: 'SE3' } }),
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

test.describe('Planned Schedule shows planned managed load', () => {
  test('a group with planned load shows the chip; a group without does not', async ({ page }) => {
    await mockApis(page, [
      group({ startTime: '04:30', endTime: '05:30', plannedLoadKwh: 3 }),
      group({ startTime: '06:00', endTime: '07:00', plannedLoadKwh: 0 }),
    ]);

    await page.goto('/inverter');
    await expect(page.getByRole('heading', { name: /Schedule Overview/i })).toBeVisible({
      timeout: 15_000,
    });

    const chips = page.getByTestId('planned-load-chip');
    await expect(chips).toHaveCount(1);
    await expect(chips.first()).toHaveText('+3.00 kWh planned load');

    // The chip sits in the 04:30 group's row, not the 06:00 one.
    const row = page.getByRole('row').filter({ hasText: '04:30 - 05:30' });
    await expect(row.getByTestId('planned-load-chip')).toBeVisible();
  });

  test('a subtract block renders with a minus sign', async ({ page }) => {
    await mockApis(page, [group({ plannedLoadKwh: -1.5 })]);

    await page.goto('/inverter');
    await expect(page.getByTestId('planned-load-chip')).toHaveText('−1.50 kWh planned load', {
      timeout: 15_000,
    });
  });
});
