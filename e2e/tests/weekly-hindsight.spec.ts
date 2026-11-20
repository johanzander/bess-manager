import { test, expect } from '@playwright/test';

// Requires the complete synthetic week served by scripts/weekly_hindsight_demo.py.
// Other CI scenarios intentionally do not invent a week of observed history.


test('weekly hindsight renders real API results, signed flows and both themes', async ({ page, request }) => {
  test.skip(process.env.WEEKLY_HINDSIGHT_DEMO !== '1', 'Run against the isolated synthetic review server');
  const mockURL = process.env.MOCK_HA_URL || 'http://127.0.0.1:8129';
  const before = await (await request.get(`${mockURL}/mock/service_log`)).json();
  const mutations: string[] = [];
  page.on('request', req => {
    if (req.method() !== 'GET') mutations.push(`${req.method()} ${req.url()}`);
  });
  await page.setViewportSize({ width: 1440, height: 1050 });
  await page.goto('/insights');
  await page.getByRole('button', { name: 'Weekly Performance', exact: true }).click();
  await expect(page.getByText('Achievable savings captured', { exact: true })).toBeVisible();
  await expect(page.getByText('672/672 actual energy quarters; 0 predicted (100.0% actual-energy coverage)', { exact: false })).toBeVisible();
  const response = await request.get('/api/insights/weekly-performance?date=2026-09-07');
  expect(response.ok()).toBeTruthy();
  const data = (await response.json()).weeklyPerformance;
  expect(data.status).toBe('complete');
  expect(data.periods).toHaveLength(672);
  expect(data.terminalDifferenceKwh).toBeCloseTo(0, 6);
  expect(data.daily.reduce((sum: number, d: { actualGridCost: number }) => sum + d.actualGridCost, 0)).toBeCloseTo(data.actual.netGridCost, 8);
  await page.getByLabel('Energy flow scenario').selectOption('optimal');
  const household = page.getByRole('heading', { name: 'Household supply ↑ / grid export ↓' }).locator('..');
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

test('real backup exposes coverage, approved partial model and signed charts', async ({ page, request }) => {
  test.skip(process.env.WEEKLY_HINDSIGHT_REAL !== '1', 'Requires the bess-real read-only backup stack');
  test.setTimeout(90_000);
  const artifacts = '../local-test-data/hindsight-results/2026-11-09';
  const mockURL = process.env.MOCK_HA_URL || 'http://127.0.0.1:8185';
  const before = await (await request.get(`${mockURL}/mock/service_log`)).json();
  const mutations: string[] = [];
  const browserErrors: string[] = [];
  page.on('request', req => { if (req.method() !== 'GET') mutations.push(`${req.method()} ${req.url()}`); });
  page.on('pageerror', error => browserErrors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1050 });
  await page.goto('/insights');
  await page.getByRole('button', {name:'Weekly Performance',exact:true}).click();
  await expect(page.getByText(/665\/672 actual energy quarters; 7 predicted/)).toBeVisible();
  await expect(page.getByText('672/672 valid numeric pairs', {exact:true})).toBeVisible();
  await expect(page.getByText(/Comparison withheld/)).toBeVisible();
  await page.getByLabel('Historical analysis mode').selectOption('estimated');
  await expect(page.getByText(/21 kWh · SOC 20–96%/)).toBeVisible();
  await page.getByRole('checkbox', {name:/Allow an observed-interval calculation/}).check();
  await page.getByRole('checkbox', {name:/Use this backup configuration/}).check();
  await expect(page.getByText('Estimated observed-interval model · 665/672 quarters', {exact:true})).toBeVisible({timeout:30_000});
  await expect(page.getByText(/Observed-cost model difference: 0.85 EUR/)).toBeVisible();
  await expect(page.getByText(/N\/A: complete-week energy coverage is insufficient./)).toBeVisible();
  await page.getByLabel('Energy flow scenario').selectOption('optimal');
  const household = page.getByRole('heading', {name:'Household supply ↑ / grid export ↓'}).locator('..');
  await expect(household.locator('svg.recharts-surface').first()).toBeVisible();
  const exportBelowZero = await household.evaluate(element => {
    const zero = element.querySelector('.recharts-reference-line-line');
    const series = element.querySelectorAll('.recharts-bar');
    const y = Number(zero?.getAttribute('y1'));
    const paths = [...series[4].querySelectorAll<SVGGraphicsElement>('.recharts-bar-rectangle path')];
    return paths.length > 0 && paths.every(path => path.getBBox().y >= y - 1);
  });
  expect(exportBelowZero).toBeTruthy();
  await page.screenshot({path:`${artifacts}/dashboard-light.png`,fullPage:true});
  await page.getByTitle(/Switch to dark mode/).click();
  await expect(page.locator('html')).toHaveClass(/dark/);
  await page.screenshot({path:`${artifacts}/dashboard-dark.png`,fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({path:`${artifacts}/dashboard-mobile.png`,fullPage:true});
  expect(mutations).toEqual([]);
  expect(browserErrors).toEqual([]);
  expect(await (await request.get(`${mockURL}/mock/service_log`)).json()).toEqual(before);
});
