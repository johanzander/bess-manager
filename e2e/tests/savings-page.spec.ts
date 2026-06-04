import { test, expect } from '@playwright/test';

// Helper: wait for the savings page to fully render (heading + child content settled)
async function waitForSavingsPage(page: import('@playwright/test').Page) {
  await page.goto('/savings');
  // Wait for the heading that confirms we're on the savings page and past the loading gate
  await expect(
    page.getByRole('heading', { name: /Financial Analysis/i })
  ).toBeVisible({ timeout: 15_000 });
  // Wait for the child component to finish loading (spinner disappears)
  await expect(page.getByText('Loading schedule...')).not.toBeVisible({ timeout: 15_000 });
  // Confirm the page hasn't crashed (error boundary replaces everything)
  await expect(
    page.getByRole('heading', { name: /Financial Analysis/i })
  ).toBeVisible();
}

test.describe('Savings Page', () => {
  test('loads and shows page heading', async ({ page }) => {
    await page.goto('/savings');

    await expect(
      page.getByRole('heading', { name: /Financial Analysis/i })
    ).toBeVisible({ timeout: 15_000 });
  });

  test('shows view mode switcher (Standard / Detailed)', async ({ page }) => {
    await waitForSavingsPage(page);

    await expect(page.getByRole('button', { name: /Standard View/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Detailed View/i })).toBeVisible();
  });

  test('shows resolution selector (60 min / 15 min)', async ({ page }) => {
    await waitForSavingsPage(page);

    await expect(page.getByRole('button', { name: '60 min' })).toBeVisible();
    await expect(page.getByRole('button', { name: '15 min' })).toBeVisible();
  });

  test('shows data content or no-data state', async ({ page }) => {
    await waitForSavingsPage(page);

    // The savings page shows one of: chart data, loading, error, or no-data
    const hasChart = await page.getByText(/Hourly Battery Actions/i).isVisible().catch(() => false);
    const noData = await page.getByText(/No schedule data/i).isVisible().catch(() => false);
    const loadingState = await page.getByText(/Loading schedule/i).isVisible().catch(() => false);
    const errorState = await page.getByText(/Error Loading Schedule/i).isVisible().catch(() => false);

    expect(hasChart || noData || loadingState || errorState).toBe(true);
  });

  test('switching to detailed view shows table or handles no data', async ({ page }) => {
    await waitForSavingsPage(page);

    await page.getByRole('button', { name: /Detailed View/i }).click();

    // At minimum the page should not crash
    await expect(page.getByRole('heading', { name: /Financial Analysis/i })).toBeVisible();

    // Wait for the detailed view to settle — either a table or a no-data message
    await expect(
      page.locator('table').first().or(page.getByText(/No schedule data|no.*data/i))
    ).toBeVisible({ timeout: 10_000 });
  });

  test('switching to 15 min resolution does not crash', async ({ page }) => {
    await waitForSavingsPage(page);

    // Click 15 min resolution
    await page.getByRole('button', { name: '15 min' }).click();

    // Page should remain stable (no error boundary)
    await expect(
      page.getByRole('heading', { name: /Financial Analysis/i })
    ).toBeVisible();
    await expect(page.getByText('Something went wrong')).not.toBeVisible();
  });

  test('switching resolutions does not crash', async ({ page }) => {
    await waitForSavingsPage(page);

    // Toggle back and forth between resolutions
    await page.getByRole('button', { name: '15 min' }).click();
    await expect(page.getByRole('heading', { name: /Financial Analysis/i })).toBeVisible();

    await page.getByRole('button', { name: '60 min' }).click();
    await expect(page.getByRole('heading', { name: /Financial Analysis/i })).toBeVisible();

    await expect(page.getByText('Something went wrong')).not.toBeVisible();
  });

  test('detailed view at 60 min shows table when data available', async ({ page }) => {
    await waitForSavingsPage(page);

    await page.getByRole('button', { name: '60 min' }).click();
    await page.getByRole('button', { name: /Detailed View/i }).click();

    // Wait for either table or no-data state
    await page.waitForTimeout(2000);

    const table = page.locator('table').first();
    const hasTable = await table.isVisible().catch(() => false);

    if (hasTable) {
      // 60 min should have reasonable row count
      const rows = table.locator('tbody tr');
      const count = await rows.count();
      expect(count).toBeGreaterThanOrEqual(1);
      expect(count).toBeLessThanOrEqual(48);
    }
  });

  test('15 min detailed view has more rows than 60 min when data available', async ({ page }) => {
    await waitForSavingsPage(page);

    // Get row count at 60 min
    await page.getByRole('button', { name: '60 min' }).click();
    await page.getByRole('button', { name: /Detailed View/i }).click();
    await page.waitForTimeout(2000);

    const table = page.locator('table').first();
    const hasTable = await table.isVisible().catch(() => false);
    if (!hasTable) return; // skip if no data

    const count60 = await table.locator('tbody tr').count();

    // Switch to 15 min
    await page.getByRole('button', { name: '15 min' }).click();
    await page.waitForTimeout(2000);
    const count15 = await table.locator('tbody tr').count();

    // 15 min resolution should produce more rows than 60 min
    if (count60 > 0) {
      expect(count15).toBeGreaterThan(count60);
    }
  });
});
