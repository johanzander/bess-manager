import { test, expect } from '@playwright/test';

test.describe('Navigation', () => {
  test('app loads with BESS header', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('h1')).toContainText('BESS');
  });

  test('navigation links are visible', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('link', { name: /Dashboard/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /Savings/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /Inverter/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /Insights/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /Settings/i })).toBeVisible();
  });

  test('can navigate to each page without errors', async ({ page }) => {
    const routes = [
      { name: /Savings/i, url: '/savings' },
      { name: /Inverter/i, url: '/inverter' },
      { name: /Insights/i, url: '/insights' },
      { name: /Settings/i, url: '/settings' },
      { name: /Dashboard/i, url: '/' },
    ];

    await page.goto('/');

    for (const route of routes) {
      await page.getByRole('link', { name: route.name }).click();
      await expect(page).toHaveURL(route.url);
      // Verify no error boundary triggered
      await expect(page.getByText('Something went wrong')).not.toBeVisible();
    }
  });
});
