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
});
