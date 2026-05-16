import { defineConfig } from '@playwright/test';

const baseURL = process.env.BASE_URL || `http://localhost:${process.env.BESS_PORT || '8080'}`;

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  retries: 1,
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
