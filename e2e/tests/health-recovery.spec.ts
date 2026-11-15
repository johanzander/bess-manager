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
//
// #875: a problem raises a banner only if a check still finds it some time
// after it first appeared. Production waits 3 minutes; docker-compose.ci.yml
// sets BESS_HEALTH_BANNER_MIN_FAILURE_AGE_SECONDS=5, so a "lasting" outage
// here is one rechecked after PERSIST_MS.

const MOCK_HA = 'http://localhost:8123';
const SENSOR = 'number.growatt_battery_charging_power_rate';
const SENSOR_ATTRS = { unit_of_measurement: '%', min: 0, max: 100 };
const PERSIST_MS = 6_000;

type Request = import('@playwright/test').APIRequestContext;

async function breakSensor(request: Request) {
  await request.post(`${MOCK_HA}/mock/update_sensor/${SENSOR}`, {
    data: { state: 'unavailable', attributes: SENSOR_ATTRS },
  });
  await request.post('/api/system-health/recheck');
}

// Break the sensor and recheck once it has been failing long enough to count.
async function breakSensorForGood(request: Request) {
  await breakSensor(request);
  await new Promise((resolve) => setTimeout(resolve, PERSIST_MS));
  await request.post('/api/system-health/recheck');
}

async function fixSensor(request: Request) {
  await request.post(`${MOCK_HA}/mock/update_sensor/${SENSOR}`, {
    data: { state: '100', attributes: SENSOR_ATTRS },
  });
  await request.post('/api/system-health/recheck');
}

async function batteryControlIssue(request: Request) {
  const summary = await (await request.get('/api/dashboard-health-summary')).json();
  return summary.criticalIssues.find((i: { component: string }) => i.component === 'Battery Control');
}

async function batteryControlRecovery(request: Request) {
  const recoveries = await (await request.get('/api/health-recoveries')).json();
  return recoveries.find((r: { component: string }) => r.component === 'Battery Control');
}

test.describe('Health-check recovery banner (#215)', () => {
  test.afterEach(async ({ request }) => {
    // Always restore the sensor and clear any recorded recovery so this spec
    // doesn't leak state into whichever test runs next against the same stack.
    await fixSensor(request);
    await request.post('/api/health-recoveries/acknowledge');
  });

  test('a lasting outage of a required sensor surfaces in the active-issue API and the dashboard banner', async ({
    request,
    page,
  }) => {
    await breakSensor(request);
    // #875: one failed check is usually a blip, so it raises nothing yet.
    expect(await batteryControlIssue(request)).toBeUndefined();

    await new Promise((resolve) => setTimeout(resolve, PERSIST_MS));
    await request.post('/api/system-health/recheck');

    const summary = await (await request.get('/api/dashboard-health-summary')).json();
    expect(summary.hasCriticalErrors).toBe(true);
    const issue = await batteryControlIssue(request);
    expect(issue).toBeTruthy();
    // One banner line per device: detail names the component, not the sensor.
    expect(issue.detail).toContain('Battery Control');

    // ci-options.json carries an influxdb block, so the #722 deprecation
    // banner (which has its own dismiss button) is on the dashboard. Suppress
    // it so the "active issues are not dismissible" assertion below is only
    // about the critical banner.
    await page.addInitScript(() =>
      localStorage.setItem('bess.influxdbDeprecationDismissed', '1'),
    );
    await page.goto('/');
    await expect(page.getByText('Critical System Issues Detected')).toBeVisible({ timeout: 15_000 });
    // The outage collapses to one banner line per device: the device label and
    // detail render together on that single line (both "Battery Control" here,
    // since the mock stack has no device registry to resolve a device name).
    // The component span and description span sit on separate JSX lines, so no
    // whitespace node separates "Battery Control:" from "Critical" — match \s*.
    await expect(page.getByText(/Battery Control:\s*Critical sensor configuration issue detected/)).toBeVisible();
    // Per-sensor detail lives on the System Health page, not the banner.
    await expect(page.getByText(SENSOR)).not.toBeVisible();
    // Active issues are not dismissible.
    await expect(page.getByRole('button', { name: /dismiss/i })).not.toBeVisible();
  });

  test('a blip leaves no recovery behind', async ({ request }) => {
    await breakSensor(request);
    await fixSensor(request);

    expect(await batteryControlRecovery(request)).toBeUndefined();
  });

  test('fixing a lasting outage records a recovery with the component and previous status', async ({
    request,
  }) => {
    await breakSensorForGood(request);
    await fixSensor(request);

    const recovery = await batteryControlRecovery(request);
    expect(recovery).toBeTruthy();
    expect(recovery.previousStatus).toBe('ERROR');
    expect(recovery.detail).toContain('Battery Control');
  });

  test('acknowledging clears the recovery', async ({ request }) => {
    await breakSensorForGood(request);
    await fixSensor(request);

    await request.post('/api/health-recoveries/acknowledge');

    expect(await batteryControlRecovery(request)).toBeUndefined();
  });

  test('a component failing again for good clears its own stale pending recovery', async ({ request }) => {
    await breakSensorForGood(request);
    await fixSensor(request);
    expect(await batteryControlRecovery(request)).toBeTruthy();

    await breakSensorForGood(request);

    expect(await batteryControlRecovery(request)).toBeUndefined();
  });
});
