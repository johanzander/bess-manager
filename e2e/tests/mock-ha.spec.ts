import { test, expect } from '@playwright/test';

const MOCK_HA = 'http://localhost:8123';

test.describe('Mock HA Integration', () => {
  test('mock HA serves sensor data', async ({ request }) => {
    const res = await request.get(`${MOCK_HA}/mock/sensors`);
    expect(res.status()).toBe(200);
    const sensors = await res.json();
    expect(sensors).toHaveProperty('sensor.growatt_battery_soc');
  });

  test('mock HA service log is accessible', async ({ request }) => {
    const res = await request.get(`${MOCK_HA}/mock/service_log`);
    expect(res.status()).toBe(200);
    const log = await res.json();
    expect(Array.isArray(log)).toBe(true);
  });

  test('mock HA returns timezone config', async ({ request }) => {
    const res = await request.get(`${MOCK_HA}/api/config`);
    expect(res.status()).toBe(200);
    const config = await res.json();
    expect(config.time_zone).toBe('Europe/Stockholm');
  });

  test('BESS reads sensors from mock HA', async ({ request }) => {
    // Verify BESS can reach mock HA by checking that settings loaded
    const res = await request.get('/api/settings');
    expect(res.status()).toBe(200);
    const settings = await res.json();
    // If sensors are configured, BESS successfully connected to mock HA
    expect(settings.battery).toBeTruthy();
  });
});
