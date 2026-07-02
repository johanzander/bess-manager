import { test, expect } from '@playwright/test';

test.describe('Dashboard', () => {
  test('dashboard page loads and shows content', async ({ page }) => {
    await page.goto('/');

    // Should not show loading spinner indefinitely
    await expect(page.getByText('Loading settings...')).not.toBeVisible({ timeout: 15_000 });

    // Should show the BESS header
    await expect(page.getByRole('heading', { name: 'BESS', level: 1 })).toBeVisible();

    // Should not show error boundary
    await expect(page.getByText('Something went wrong')).not.toBeVisible();
  });

  test('dashboard does not show setup wizard redirect when configured', async ({ page }) => {
    await page.goto('/');
    // With a properly configured scenario, we should stay on dashboard, not redirect to /setup
    await page.waitForTimeout(2000);
    expect(page.url()).not.toContain('/setup');
  });

  test('shows Dashboard heading with last-updated time', async ({ page }) => {
    await page.goto('/');

    await expect(
      page.getByRole('heading', { name: 'Dashboard', exact: true })
    ).toBeVisible({ timeout: 15_000 });

    // Should show last updated timestamp
    await expect(page.getByText(/Last updated/i)).toBeVisible();
  });

  test('shows system overview, initializing, or no-data state', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible({ timeout: 15_000 });

    // Wait for the dashboard to settle into one of its content states.
    // Using .or() + toBeVisible() so Playwright retries until one appears,
    // rather than snapshot isVisible() calls that race with data loading.
    await expect(
      page.getByText('System Overview')
        .or(page.getByText('Initializing system'))
        .or(page.getByText('No Dashboard Data'))
    ).toBeVisible({ timeout: 10_000 });
  });

  test('shows energy flow section when data is available', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible({ timeout: 15_000 });

    // If data is available, energy flows section shows
    const hasData = await page.getByText('System Overview').isVisible().catch(() => false);
    if (hasData) {
      await expect(page.getByText(/Energy Flows/i)).toBeVisible();
    }
  });

  test('shows resolution selector', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible({ timeout: 15_000 });

    // Resolution buttons are always visible
    await expect(page.getByRole('button', { name: '60 min' })).toBeVisible();
    await expect(page.getByRole('button', { name: '15 min' })).toBeVisible();
  });
});
