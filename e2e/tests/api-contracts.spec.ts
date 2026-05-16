import { test, expect } from '@playwright/test';

/**
 * API Contract Tests
 *
 * These tests validate the response shapes that the frontend depends on.
 * If an endpoint changes its structure, these tests break before the UI does.
 */

test.describe('API Contracts: /api/settings', () => {
  test('returns all expected top-level sections', async ({ request }) => {
    const res = await request.get('/api/settings');
    expect(res.status()).toBe(200);
    const body = await res.json();

    // Core sections the frontend reads
    expect(body).toHaveProperty('battery');
    expect(body).toHaveProperty('sensors');
    expect(body).toHaveProperty('home');
    expect(body).toHaveProperty('electricityPrice');
    expect(body).toHaveProperty('growatt');
  });

  test('battery section has expected fields', async ({ request }) => {
    const res = await request.get('/api/settings');
    const { battery } = await res.json();

    expect(typeof battery.totalCapacity).toBe('number');
    expect(typeof battery.minSoc).toBe('number');
    expect(typeof battery.maxSoc).toBe('number');
    // Computed fields enriched by backend
    expect(typeof battery.minSoeKwh).toBe('number');
    expect(typeof battery.maxSoeKwh).toBe('number');
    expect(typeof battery.reservedCapacity).toBe('number');
    // Constraints
    expect(battery.minSoc).toBeGreaterThanOrEqual(0);
    expect(battery.maxSoc).toBeLessThanOrEqual(100);
    expect(battery.minSoc).toBeLessThanOrEqual(battery.maxSoc);
  });

  test('sensors section maps keys to entity IDs', async ({ request }) => {
    const res = await request.get('/api/settings');
    const { sensors } = await res.json();

    expect(typeof sensors).toBe('object');
    // At least battery_soc should be configured in the ci scenario
    expect(sensors).toHaveProperty('battery_soc');
    // All values should be entity ID strings or empty
    for (const [key, value] of Object.entries(sensors)) {
      expect(typeof key).toBe('string');
      expect(typeof value).toBe('string');
    }
  });
});

test.describe('API Contracts: /api/dashboard', () => {
  test('returns schedule data with expected structure', async ({ request }) => {
    const res = await request.get('/api/dashboard');
    expect(res.status()).toBe(200);
    const body = await res.json();

    // May return "initializing" state — both are valid contracts
    if (body.error === 'initializing') {
      expect(body).toHaveProperty('message');
      return;
    }

    // Full dashboard response
    expect(body).toHaveProperty('hourlyData');
    expect(body).toHaveProperty('summary');
    expect(body).toHaveProperty('costAndSavings');
    expect(body).toHaveProperty('strategicIntentSummary');
    expect(body).toHaveProperty('batterySoc');
    expect(body).toHaveProperty('batteryCapacity');
    expect(body).toHaveProperty('date');
    expect(body).toHaveProperty('currentPeriod');
  });

  test('hourlyData entries have FormattedValue structure', async ({ request }) => {
    const res = await request.get('/api/dashboard');
    const body = await res.json();
    if (body.error === 'initializing') return;

    expect(Array.isArray(body.hourlyData)).toBe(true);
    expect(body.hourlyData.length).toBeGreaterThan(0);

    const entry = body.hourlyData[0];
    // Each period has FormattedValue fields
    expect(entry).toHaveProperty('period');
    expect(entry).toHaveProperty('buyPrice');
    expect(entry).toHaveProperty('solarProduction');
    expect(entry).toHaveProperty('homeConsumption');
    expect(entry).toHaveProperty('batteryCharged');
    expect(entry).toHaveProperty('batteryDischarged');
    expect(entry).toHaveProperty('gridImported');
    expect(entry).toHaveProperty('gridExported');
    expect(entry).toHaveProperty('hourlyCost');
    expect(entry).toHaveProperty('strategicIntent');

    // FormattedValue structure
    const fv = entry.buyPrice;
    expect(typeof fv.value).toBe('number');
    expect(typeof fv.display).toBe('string');
    expect(typeof fv.unit).toBe('string');
    expect(typeof fv.text).toBe('string');
  });

  test('summary section has energy and savings aggregates', async ({ request }) => {
    const res = await request.get('/api/dashboard');
    const body = await res.json();
    if (body.error === 'initializing') return;

    const { summary } = body;
    expect(summary).toHaveProperty('totalSolarProduction');
    expect(summary).toHaveProperty('totalHomeConsumption');
    expect(summary).toHaveProperty('totalBatteryCharged');
    expect(summary).toHaveProperty('totalBatteryDischarged');
    expect(summary).toHaveProperty('totalGridImported');
    expect(summary).toHaveProperty('totalGridExported');
    expect(summary).toHaveProperty('gridOnlyCost');
    expect(summary).toHaveProperty('optimizedCost');
    expect(summary).toHaveProperty('totalSavings');
  });

  test('costAndSavings section has today cost info', async ({ request }) => {
    const res = await request.get('/api/dashboard');
    const body = await res.json();
    if (body.error === 'initializing') return;

    const { costAndSavings } = body;
    expect(costAndSavings).toHaveProperty('todaysCost');
    expect(costAndSavings).toHaveProperty('todaysSavings');
    expect(costAndSavings).toHaveProperty('gridOnlyCost');
    expect(costAndSavings).toHaveProperty('percentageSaved');
  });

  test('quarter-hourly resolution returns 96 periods', async ({ request }) => {
    const res = await request.get('/api/dashboard?resolution=quarter-hourly');
    const body = await res.json();
    if (body.error === 'initializing') return;

    expect(body.hourlyData.length).toBe(96);
  });

  test('hourly resolution returns 24 periods', async ({ request }) => {
    const res = await request.get('/api/dashboard?resolution=hourly');
    const body = await res.json();
    if (body.error === 'initializing') return;

    expect(body.hourlyData.length).toBe(24);
  });

  test('savings totals are consistent between resolutions', async ({ request }) => {
    const [hourlyRes, quarterRes] = await Promise.all([
      request.get('/api/dashboard?resolution=hourly'),
      request.get('/api/dashboard?resolution=quarter-hourly'),
    ]);
    const hourly = await hourlyRes.json();
    const quarter = await quarterRes.json();
    if (hourly.error === 'initializing' || quarter.error === 'initializing') return;

    // Summary totals must be the same regardless of resolution — they cover the
    // same time range, just sliced differently.
    const hSummary = hourly.summary;
    const qSummary = quarter.summary;

    // totalSavings should match (both are FormattedValue with .value)
    expect(hSummary.totalSavings.value).toBeCloseTo(qSummary.totalSavings.value, 1);
    expect(hSummary.gridOnlyCost.value).toBeCloseTo(qSummary.gridOnlyCost.value, 1);
    expect(hSummary.optimizedCost.value).toBeCloseTo(qSummary.optimizedCost.value, 1);

    // costAndSavings should also be consistent
    expect(hourly.costAndSavings.todaysCost.value).toBeCloseTo(
      quarter.costAndSavings.todaysCost.value, 1
    );
    expect(hourly.costAndSavings.todaysSavings.value).toBeCloseTo(
      quarter.costAndSavings.todaysSavings.value, 1
    );
  });

  test('hourly period values sum to match summary totals', async ({ request }) => {
    const res = await request.get('/api/dashboard?resolution=hourly');
    const body = await res.json();
    if (body.error === 'initializing') return;

    // Sum individual period costs and compare to summary
    const sumCost = body.hourlyData.reduce(
      (acc: number, h: any) => acc + (h.hourlyCost?.value ?? 0), 0
    );
    const summaryOptimizedCost = body.summary.optimizedCost.value;

    // Allow small floating point drift (within 0.5 currency units)
    expect(Math.abs(sumCost - summaryOptimizedCost)).toBeLessThan(0.5);
  });

  test('quarter-hourly period values sum to match summary totals', async ({ request }) => {
    const res = await request.get('/api/dashboard?resolution=quarter-hourly');
    const body = await res.json();
    if (body.error === 'initializing') return;

    const sumCost = body.hourlyData.reduce(
      (acc: number, h: any) => acc + (h.hourlyCost?.value ?? 0), 0
    );
    const summaryOptimizedCost = body.summary.optimizedCost.value;

    expect(Math.abs(sumCost - summaryOptimizedCost)).toBeLessThan(0.5);
  });
});

test.describe('API Contracts: /api/growatt/inverter_status', () => {
  test('returns all inverter status fields', async ({ request }) => {
    const res = await request.get('/api/growatt/inverter_status');
    expect(res.status()).toBe(200);
    const body = await res.json();

    expect(typeof body.batterySoc).toBe('number');
    expect(typeof body.batterySoe).toBe('number');
    expect(typeof body.batteryChargePower).toBe('number');
    expect(typeof body.batteryDischargePower).toBe('number');
    expect(typeof body.batteryMode).toBe('string');
    expect(typeof body.gridChargeEnabled).toBe('boolean');
    expect(typeof body.chargeStopSoc).toBe('number');
    expect(typeof body.dischargeStopSoc).toBe('number');
    expect(typeof body.dischargePowerRate).toBe('number');
    expect(typeof body.timestamp).toBe('string');

    // SOC is 0-100
    expect(body.batterySoc).toBeGreaterThanOrEqual(0);
    expect(body.batterySoc).toBeLessThanOrEqual(100);
  });
});

test.describe('API Contracts: /api/growatt/detailed_schedule', () => {
  test('returns 24-hour schedule with strategic intents', async ({ request }) => {
    const res = await request.get('/api/growatt/detailed_schedule');
    expect(res.status()).toBe(200);
    const body = await res.json();

    expect(body).toHaveProperty('scheduleData');
    expect(body).toHaveProperty('hourDistribution');
    expect(body).toHaveProperty('periodGroups');
    expect(body).toHaveProperty('currentHour');
    expect(Array.isArray(body.scheduleData)).toBe(true);
    expect(body.scheduleData.length).toBe(24);

    // Each hour entry (camelCase keys)
    const hour = body.scheduleData[0];
    expect(typeof hour.hour).toBe('number');
    expect(typeof hour.batteryMode).toBe('string');
    expect(typeof hour.strategicIntent).toBe('string');
    expect(typeof hour.action).toBe('string');
    expect(hour).toHaveProperty('price');
    expect(hour).toHaveProperty('isCurrent');
  });

  test('hour distribution totals 24', async ({ request }) => {
    const res = await request.get('/api/growatt/detailed_schedule');
    const body = await res.json();

    const dist = body.hourDistribution;
    expect(typeof dist.charge).toBe('number');
    expect(typeof dist.discharge).toBe('number');
    expect(typeof dist.idle).toBe('number');
    expect(dist.charge + dist.discharge + dist.idle).toBe(24);
  });
});

test.describe('API Contracts: /api/system-health', () => {
  test('returns health check structure', async ({ request }) => {
    const res = await request.get('/api/system-health');
    expect(res.status()).toBe(200);
    const body = await res.json();

    expect(body).toHaveProperty('timestamp');
    expect(body).toHaveProperty('systemMode');
    expect(body).toHaveProperty('checks');
    expect(Array.isArray(body.checks)).toBe(true);
    expect(typeof body.timestamp).toBe('string');
    expect(typeof body.systemMode).toBe('string');
  });
});

test.describe('API Contracts: /api/decision-intelligence', () => {
  test('returns patterns or fallback with summary', async ({ request }) => {
    const res = await request.get('/api/decision-intelligence');
    expect(res.status()).toBe(200);
    const body = await res.json();

    expect(body).toHaveProperty('summary');

    // When real data is available: patterns array with hour entries
    if (body.patterns) {
      expect(Array.isArray(body.patterns)).toBe(true);
      if (body.patterns.length > 0) {
        const p = body.patterns[0];
        expect(typeof p.hour).toBe('number');
        expect(p).toHaveProperty('flows');
        expect(p).toHaveProperty('netStrategyValue');
      }
      // Summary has totals
      expect(body.summary).toHaveProperty('totalNetValue');
      expect(body.summary).toHaveProperty('bestDecisionHour');
    } else {
      // Fallback: empty hours array with basic summary
      expect(body).toHaveProperty('hours');
      expect(Array.isArray(body.hours)).toBe(true);
    }
  });
});

test.describe('API Contracts: PATCH /api/settings', () => {
  test('rejects unknown section names', async ({ request }) => {
    const res = await request.patch('/api/settings', {
      data: { unknownSection: { foo: 'bar' } },
    });
    expect(res.status()).toBe(400);
    const body = await res.json();
    expect(body.detail).toContain('Unknown settings section');
  });

  test('rejects invalid entity ID format in sensors', async ({ request }) => {
    const res = await request.patch('/api/settings', {
      data: { sensors: { battery_soc: 'not-a-valid-entity' } },
    });
    expect(res.status()).toBe(422);
    const body = await res.json();
    expect(body.detail).toContain('Invalid entity ID format');
  });

  test('accepts valid sensor entity ID', async ({ request }) => {
    // First get current sensors to restore later
    const before = await request.get('/api/settings');
    const originalSensors = (await before.json()).sensors;

    const res = await request.patch('/api/settings', {
      data: { sensors: { battery_soc: 'sensor.test_battery_soc' } },
    });
    expect(res.status()).toBe(200);

    // Verify it was persisted
    const after = await request.get('/api/settings');
    const updated = (await after.json()).sensors;
    expect(updated.battery_soc).toBe('sensor.test_battery_soc');

    // Restore original
    await request.patch('/api/settings', {
      data: { sensors: { battery_soc: originalSensors.battery_soc } },
    });
  });

  test('accepts battery settings update', async ({ request }) => {
    const before = await request.get('/api/settings');
    const originalBattery = (await before.json()).battery;

    const res = await request.patch('/api/settings', {
      data: { battery: { totalCapacity: 12.5 } },
    });
    expect(res.status()).toBe(200);

    // Verify
    const after = await request.get('/api/settings');
    const updated = (await after.json()).battery;
    expect(updated.totalCapacity).toBe(12.5);

    // Restore
    await request.patch('/api/settings', {
      data: { battery: { totalCapacity: originalBattery.totalCapacity } },
    });
  });
});

test.describe('API Contracts: /api/runtime-failures', () => {
  test('returns array of failures', async ({ request }) => {
    const res = await request.get('/api/runtime-failures');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(Array.isArray(body)).toBe(true);
  });

  test('dismiss-all returns success', async ({ request }) => {
    const res = await request.post('/api/runtime-failures/dismiss-all');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.success).toBe(true);
  });

  test('dismiss non-existent failure returns 404', async ({ request }) => {
    const res = await request.post('/api/runtime-failures/nonexistent-id/dismiss');
    expect(res.status()).toBe(404);
  });
});
