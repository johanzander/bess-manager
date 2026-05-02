import { test, expect } from '@playwright/test';

test.describe('API Smoke Tests', () => {
  test('GET /api/settings returns 200', async ({ request }) => {
    const res = await request.get('/api/settings');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty('battery');
  });

  test('GET /api/dashboard returns 200', async ({ request }) => {
    const res = await request.get('/api/dashboard');
    expect(res.status()).toBe(200);
  });

  test('GET /api/system-health returns 200', async ({ request }) => {
    const res = await request.get('/api/system-health');
    expect(res.status()).toBe(200);
  });

  test('GET /api/setup/status returns 200', async ({ request }) => {
    const res = await request.get('/api/setup/status');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty('wizardNeeded');
  });

  test('GET /api/runtime-failures returns 200', async ({ request }) => {
    const res = await request.get('/api/runtime-failures');
    expect(res.status()).toBe(200);
  });

  test('GET /api/growatt/inverter_status returns 200', async ({ request }) => {
    const res = await request.get('/api/growatt/inverter_status');
    expect(res.status()).toBe(200);
  });

  test('GET /api/decision-intelligence returns 200', async ({ request }) => {
    const res = await request.get('/api/decision-intelligence');
    expect(res.status()).toBe(200);
  });
});
