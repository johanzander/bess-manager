import { test, expect } from '@playwright/test';

// Issue #676: when the current period is a curtailed period, the "Strategic
// Intent" status card used to render a single string
// ("Storing Solar — Curtailed (No Export)") at text-3xl on one non-wrapping
// line, which overflowed the card. The fix keeps the intent name as the
// headline and moves curtailment to its own small badge under it.
//
// Like inverter-schedule-control-model.spec.ts, this stubs the API via
// page.route() so it can pin the exact (curtailed, SOLAR_STORAGE) state a
// live backend won't reliably produce, then asserts on the real rendered
// layout in Chromium.

const fv = (value: number, display: string, unit = '') => ({
  value,
  display,
  unit,
  text: unit ? `${display} ${unit}` : display,
});

function curtailedDashboardPayload() {
  const hour = {
    dataSource: 'predicted' as const,
    strategicIntent: 'SOLAR_STORAGE',
    curtailed: true,
    batteryAction: 0,
    batterySocStart: fv(80, '80', '%'),
    batterySocEnd: fv(82, '82', '%'),
  };
  return {
    date: '2026-07-11',
    hourlyData: Array.from({ length: 24 }, (_, i) => ({ hour: i, period: i, ...hour })),
    summary: {
      gridOnlyCost: fv(2.0, '2.00', 'EUR'),
      netGridCost: fv(1.5, '1.50', 'EUR'),
      netSavings: fv(0.65, '0.65', 'EUR'),
      totalSavingsPercentage: fv(25, '25', '%'),
      horizonDays: 1,
    },
    batteryCapacity: 30,
    batterySoc: fv(82, '82', '%'),
    batterySoe: fv(24.6, '24.6', 'kWh'),
    realTimePower: {
      solarPower: fv(3500, '3.50', 'kW'),
      homeLoadPower: fv(1000, '1.00', 'kW'),
      gridImportPower: fv(0, '0.00', 'kW'),
      gridExportPower: fv(0, '0.00', 'kW'),
      batteryChargePower: fv(2500, '2.50', 'kW'),
      batteryDischargePower: fv(0, '0.00', 'kW'),
      netBatteryPower: fv(2500, '2.50', 'kW'),
    },
    tomorrowData: null,
  };
}

test('Strategic Intent card: curtailment is a separate badge and does not overflow the card', async ({
  page,
}) => {
  await page.route('**/api/settings', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        battery: { totalCapacity: 30 },
        electricityPrice: { area: 'SE3' },
      }),
    });
  });
  await page.route('**/api/dashboard**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(curtailedDashboardPayload()),
    });
  });
  await page.route('**/api/growatt/inverter_status', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ controlModel: 'tou_register', batteryMode: 'LOAD_FIRST' }),
    });
  });
  for (const noisy of [
    '**/api/dashboard-health-summary',
    '**/api/historical-data-status',
    '**/api/system-health**',
  ]) {
    await page.route(noisy, async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
    });
  }

  await page.goto('/');

  // The Battery status card, located by its key-metric label.
  const card = page
    .locator('div.rounded-lg.border')
    .filter({ hasText: 'Strategic Intent' })
    .first();
  await expect(card).toBeVisible({ timeout: 15_000 });

  // Headline is only the intent name...
  await expect(card.getByText('Storing Solar', { exact: true })).toBeVisible();
  // ...and the curtailment note is its own element, not fused into the headline.
  await expect(card.getByText('Curtailed (No Export)', { exact: true })).toBeVisible();
  await expect(
    card.getByText('Storing Solar — Curtailed (No Export)')
  ).toHaveCount(0);

  // The card must not overflow horizontally, and the big headline must stay
  // inside it -- this is the regression the fix addresses.
  const overflow = await card.evaluate(
    (el) => el.scrollWidth - el.clientWidth
  );
  expect(overflow).toBeLessThanOrEqual(1);

  const cardBox = await card.boundingBox();
  const headlineBox = await card.getByText('Storing Solar', { exact: true }).boundingBox();
  expect(cardBox).not.toBeNull();
  expect(headlineBox).not.toBeNull();
  // headline right edge within the card's right edge (1px tolerance)
  expect(headlineBox!.x + headlineBox!.width).toBeLessThanOrEqual(
    cardBox!.x + cardBox!.width + 1
  );
});
