import { defineConfig } from '@playwright/test';

const baseURL = process.env.BASE_URL || `http://localhost:${process.env.BESS_PORT || '8080'}`;

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  retries: 1,
  // One shared backend: specs that PATCH settings or switch platform re-run
  // system start-up, which transiently flips /api/setup/status to
  // wizardNeeded and bounces any page another worker is loading to /setup.
  workers: 1,
  reporter: [['html', { open: 'never' }], ['list']],
  use: {
    baseURL,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
      testIgnore: /setup-wizard/,
    },
    {
      name: 'wizard',
      use: { browserName: 'chromium' },
      testMatch: /setup-wizard/,
    },
  ],
});
