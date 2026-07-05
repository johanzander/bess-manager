import { test, expect } from '@playwright/test';

// #215/#239: a sensor that goes ERROR/WARNING and self-resolves should leave
// a trace even if nobody was watching the live banner when it recovered.
//
// The shared `ci-normal-day` scenario this CI job runs against has its own
// permanently-pinned pre-existing errors (Electricity Price Data's Nordpool
// date lookup never matches "today" in CI; see docs/agents/memory), so
// hasCriticalErrors is never reliably false here — the "recovered" banner
// (which only shows once ALL active issues clear) can't be observed in the
// DOM in this shared stack. That part is verified at the API level instead,
// which is deterministic regardless of the scenario's other baseline noise.

const MOCK_HA = 'http://localhost:8123';
const SENSOR = 'number.growatt_battery_charging_power_rate';
const SENSOR_ATTRS = { unit_of_measurement: '%', min: 0, max: 100 };

async function breakSensor(request: import('@playwright/test').APIRequestContext) {
  await request.post(`${MOCK_HA}/mock/update_sensor/${SENSOR}`, {
    data: { state: 'unavailable', attributes: SENSOR_ATTRS },
  });
  await request.post('/api/system-health/recheck');
}

async function fixSensor(request: import('@playwright/test').APIRequestContext) {
  await request.post(`${MOCK_HA}/mock/update_sensor/${SENSOR}`, {
    data: { state: '100', attributes: SENSOR_ATTRS },
  });
  await request.post('/api/system-health/recheck');
}

test.describe('Health-check recovery banner (#215)', () => {
  test.afterEach(async ({ request }) => {
    // Always restore the sensor and clear any recorded recovery so this spec
    // doesn't leak state into whichever test runs next against the same stack.
    await fixSensor(request);
    await request.post('/api/health-recoveries/acknowledge');
  });

  test('breaking a required sensor surfaces it in the active-issue API and the dashboard banner', async ({
    request,
    page,
  }) => {
    await breakSensor(request);

    const summary = await (await request.get('/api/dashboard-health-summary')).json();
    expect(summary.hasCriticalErrors).toBe(true);
    const issue = summary.criticalIssues.find((i: { component: string }) => i.component === 'Battery Control');
    expect(issue).toBeTruthy();
    expect(issue.detail).toContain(SENSOR);

    await page.goto('/');
    await expect(page.getByText('Critical System Issues Detected')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('Battery Control')).toBeVisible();
    await expect(page.getByText(SENSOR)).toBeVisible();
    // Active issues are not dismissible.
    await expect(page.getByRole('button', { name: /dismiss/i })).not.toBeVisible();
  });

  test('fixing it records a recovery with the specific sensor and previous status', async ({ request }) => {
    await breakSensor(request);
    await fixSensor(request);

    const recoveries = await (await request.get('/api/health-recoveries')).json();
    const recovery = recoveries.find((r: { component: string }) => r.component === 'Battery Control');
    expect(recovery).toBeTruthy();
    expect(recovery.previousStatus).toBe('ERROR');
    expect(recovery.detail).toContain(SENSOR);
  });

  test('acknowledging clears the recovery', async ({ request }) => {
    await breakSensor(request);
    await fixSensor(request);

    await request.post('/api/health-recoveries/acknowledge');

    const recoveries = await (await request.get('/api/health-recoveries')).json();
    expect(recoveries.find((r: { component: string }) => r.component === 'Battery Control')).toBeUndefined();
  });

  test('a component erroring again clears its own stale pending recovery', async ({ request }) => {
    await breakSensor(request);
    await fixSensor(request);
    let recoveries = await (await request.get('/api/health-recoveries')).json();
    expect(recoveries.find((r: { component: string }) => r.component === 'Battery Control')).toBeTruthy();

    await breakSensor(request);

    recoveries = await (await request.get('/api/health-recoveries')).json();
    expect(recoveries.find((r: { component: string }) => r.component === 'Battery Control')).toBeUndefined();
  });
});
