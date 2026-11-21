import { test, expect } from '@playwright/test';

// Requires the complete synthetic week served by scripts/performance_demo.py.
// Other CI scenarios intentionally do not invent a week of observed history.


test('weekly hindsight renders real API results, signed flows and both themes', async ({ page, request }) => {
  test.skip(process.env.PERFORMANCE_DEMO !== '1', 'Run against the isolated synthetic review server');
  const mockURL = process.env.MOCK_HA_URL || 'http://127.0.0.1:8129';
  const before = await (await request.get(`${mockURL}/mock/service_log`)).json();
  const mutations: string[] = [];
  page.on('request', req => {
    if (req.method() !== 'GET') mutations.push(`${req.method()} ${req.url()}`);
  });
  await page.setViewportSize({ width: 1440, height: 1050 });
  await page.goto('/insights');
  await page.getByRole('button', { name: 'Performance', exact: true }).click();
  await expect(page.getByText('Achievable savings captured', { exact: true })).toBeVisible();
  await expect(page.getByText('672/672 actual energy quarters; 0 predicted (100.0% actual-energy coverage)', { exact: false })).toBeVisible();
  const response = await request.get('/api/insights/performance?date=2026-09-07');
  expect(response.ok()).toBeTruthy();
  const data = (await response.json()).performance;
  expect(data.status).toBe('complete');
  expect(data.periods).toHaveLength(672);
  expect(data.terminalDifferenceKwh).toBeCloseTo(0, 6);
  expect(data.daily.reduce((sum: number, d: { actualGridCost: number }) => sum + d.actualGridCost, 0)).toBeCloseTo(data.actual.netGridCost, 8);
  const household = page.getByRole('heading', { name: 'Household supply ↑ / grid export ↓ · actual vs hindsight' }).locator('..');
  await expect(household.locator('svg.recharts-surface').first()).toBeVisible();
  const exportBelowZero = await household.evaluate(element => {
    const zero = element.querySelector('.recharts-reference-line-line');
    const solarExport = element.querySelectorAll('.recharts-bar')[3];
    const y = Number(zero?.getAttribute('y1'));
    const rectangles = [...solarExport.querySelectorAll<SVGGraphicsElement>('.recharts-bar-rectangle path')];
    return rectangles.length > 0 && rectangles.every(path => path.getBBox().y >= y - 1);
  });
  expect(exportBelowZero).toBeTruthy();
  await page.screenshot({ path: 'test-results/weekly-performance-light.png', fullPage: true });
  await page.getByTitle(/Switch to dark mode/).click();
  await expect(page.locator('html')).toHaveClass(/dark/);
  await page.screenshot({ path: 'test-results/weekly-performance-dark.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: 'test-results/weekly-performance-mobile.png', fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1050 });
  await page.getByRole('button', { name: /Week of Sep 7, 2026/ }).locator('..').getByRole('button').last().click();
  await expect(page.getByText(/Comparison withheld/)).toBeVisible();
  await expect(page.getByText('Achievable savings captured', { exact: true })).toHaveCount(0);
  await expect(page.getByText(/Missed savings and captured savings: N\/A/)).toBeVisible();
  expect(mutations).toEqual([]);
  const after = await (await request.get(`${mockURL}/mock/service_log`)).json();
  expect(after).toEqual(before);
});

// Runs against a locally mounted, private backup (see local-test-data, never
// committed). Every expectation is derived from the API response so no
// installation's capacity, limits or costs are written into this public test.
test('real backup exposes coverage, approved partial model and signed charts', async ({ page, request }) => {
  test.skip(process.env.PERFORMANCE_REAL_BACKUP !== '1', 'Requires a read-only real-backup stack');
  test.setTimeout(180_000);
  const week = process.env.PERFORMANCE_WEEK;
  test.skip(!week, 'Set PERFORMANCE_WEEK to a completed backed-up week');
  const artifacts = process.env.PERFORMANCE_ARTIFACTS || 'test-results';
  const mockURL = process.env.MOCK_HA_URL || 'http://127.0.0.1:8185';
  const before = await (await request.get(`${mockURL}/mock/service_log`)).json();
  const strict = (await (await request.get(`/api/insights/performance?date=${week}&mode=verified`)).json()).performance;
  const estimatedResponse = await request.get(
    // The page itself asks for the automatic analysis, with no user choices.
    `/api/insights/performance?date=${week}`,
    { timeout: 120_000 },
  );
  expect(estimatedResponse.ok()).toBeTruthy();
  const estimated = (await estimatedResponse.json()).performance;
  const money = (value: number) =>
    `${value.toLocaleString('en-US', { maximumFractionDigits: 2, minimumFractionDigits: 2 })} ${estimated.currency}`;
  const mutations: string[] = [];
  const browserErrors: string[] = [];
  page.on('request', req => { if (req.method() !== 'GET') mutations.push(`${req.method()} ${req.url()}`); });
  page.on('pageerror', error => browserErrors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1050 });
  await page.goto('/insights');
  await page.getByRole('button', { name: 'Performance', exact: true }).click();
  // The page opens on the newest completed week; PERFORMANCE_WEEK must be it.
  await expect(page.getByText(`${strict.startDate} – ${strict.endDate}`, { exact: false })).toBeVisible();
  await expect(page.getByText(
    `${strict.diagnostics.actualPeriods}/${strict.expectedPeriods} actual energy quarters; ${strict.diagnostics.predictedPeriods} predicted`,
    { exact: false },
  )).toBeVisible();
  await expect(page.getByRole('combobox', { name: /analysis mode/i })).toHaveCount(0);
  await expect(page.getByRole('checkbox')).toHaveCount(0);
  if (estimated.mode === 'estimated') {
    await expect(page.getByText('Estimate', { exact: true })).toBeVisible();
  }
  await expect(page.getByText(/BESS saved .* against solar only/)).toBeVisible({ timeout: 120_000 });
  await expect(page.getByRole('img', { name: /^Coverage:/ })).toBeVisible();
  await expect(page.getByRole('list', { name: 'Cost waterfall' })).toBeVisible();
  // The proof section is collapsed by default.
  await page.getByText('Verification and calculation proof', { exact: true }).click();
  const battery = estimated.assumptions?.battery ?? estimated.assumptionProfile.battery;
  await expect(page.getByText(`${battery.totalCapacity} kWh · SOC ${battery.minSoc}–${battery.maxSoc}%`, { exact: false })).toBeVisible();
  await expect(page.getByText(
    `Estimated observed-interval model · ${estimated.periods.length}/${estimated.expectedPeriods} quarters`,
    { exact: true },
  )).toBeVisible({ timeout: 120_000 });
  await expect(page.getByText(`Observed-cost model difference: ${money(estimated.modelCostDifference)}`, { exact: false })).toBeVisible();
  if (estimated.huaweiFeasible) {
    await expect(page.getByText('Hindsight intents replayed with Huawei TOU rules', { exact: true })).toBeVisible();
  }
  if (estimated.priceReferenceSource) {
    await expect(page.getByText(`Prices: ${estimated.priceReferenceSource}.`, { exact: true })).toBeVisible();
  }
  // Unknown quarters stay gaps: the timeline never carries an actual SOC there.
  expect(estimated.socTimeline.filter((row: { energyUnknown: boolean; actualSoc: number | null; timestamp: string }) =>
    row.energyUnknown && row.actualSoc !== null && !estimated.periods.some((p: { timestamp: string }) => p.timestamp === row.timestamp),
  ).every((row: { actualSoc: number | null }) => row.actualSoc !== 0)).toBeTruthy();
  const household = page.getByRole('heading', { name: 'Household supply ↑ / grid export ↓ · actual vs hindsight' }).locator('..');
  await expect(household.locator('svg.recharts-surface').first()).toBeVisible();
  const exportBelowZero = await household.evaluate(element => {
    const zero = element.querySelector('.recharts-reference-line-line');
    const series = element.querySelectorAll('.recharts-bar');
    const y = Number(zero?.getAttribute('y1'));
    const paths = [...series[9].querySelectorAll<SVGGraphicsElement>('.recharts-bar-rectangle path')];
    return paths.every(path => path.getBBox().y >= y - 1);
  });
  expect(exportBelowZero).toBeTruthy();
  await page.screenshot({ path: `${artifacts}/dashboard-light.png`, fullPage: true });
  await page.getByTitle(/Switch to dark mode/).click();
  await expect(page.locator('html')).toHaveClass(/dark/);
  await page.screenshot({ path: `${artifacts}/dashboard-dark.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: `${artifacts}/dashboard-mobile.png`, fullPage: true });
  await page.getByTitle(/Switch to light mode/).click();
  expect(mutations).toEqual([]);
  expect(browserErrors).toEqual([]);
  expect(await (await request.get(`${mockURL}/mock/service_log`)).json()).toEqual(before);
});
