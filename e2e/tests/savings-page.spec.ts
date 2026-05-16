import { test, expect } from '@playwright/test';

test.describe('Savings Page', () => {
  test('loads and shows page heading', async ({ page }) => {
    await page.goto('/savings');

    await expect(
      page.getByRole('heading', { name: /Financial Analysis/i })
    ).toBeVisible({ timeout: 15_000 });
  });

  test('shows view mode switcher (Standard / Detailed)', async ({ page }) => {
    await page.goto('/savings');

    await expect(page.getByRole('button', { name: /Standard View/i })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('button', { name: /Detailed View/i })).toBeVisible();
  });

  test('shows resolution selector (60 min / 15 min)', async ({ page }) => {
    await page.goto('/savings');

    // Resolution buttons use minute labels
    await expect(page.getByRole('button', { name: '60 min' })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('button', { name: '15 min' })).toBeVisible();
  });

  test('shows hourly battery actions chart', async ({ page }) => {
    await page.goto('/savings');

    // The savings overview renders "Hourly Battery Actions & Savings" heading
    await expect(
      page.getByText(/Hourly Battery Actions/i)
    ).toBeVisible({ timeout: 15_000 });
  });

  test('switching to detailed view shows table', async ({ page }) => {
    await page.goto('/savings');
    await expect(page.getByRole('button', { name: /Detailed View/i })).toBeVisible({ timeout: 15_000 });

    await page.getByRole('button', { name: /Detailed View/i }).click();

    // Detailed view should show a data table
    await expect(page.locator('table').first()).toBeVisible({ timeout: 10_000 });
  });

  test('shows currency values from scenario', async ({ page }) => {
    await page.goto('/savings');

    // The CI scenario uses SEK currency
    await expect(page.getByText(/SEK/).first()).toBeVisible({ timeout: 15_000 });
  });

  test('switching to 15 min resolution updates the data', async ({ page }) => {
    await page.goto('/savings');
    await expect(page.getByRole('button', { name: '60 min' })).toBeVisible({ timeout: 15_000 });

    // Click 15 min resolution
    await page.getByRole('button', { name: '15 min' }).click();

    // The 15 min button should now be active (typically has a different visual state)
    // and the page should still display data without errors
    await expect(page.getByText(/Hourly Battery Actions/i)).toBeVisible();
    await expect(page.getByText('Something went wrong')).not.toBeVisible();
  });

  test('60 min detailed view shows table with hour rows', async ({ page }) => {
    await page.goto('/savings');
    await expect(page.getByRole('button', { name: /Detailed View/i })).toBeVisible({ timeout: 15_000 });

    // Ensure 60 min resolution is active
    await page.getByRole('button', { name: '60 min' }).click();
    await page.getByRole('button', { name: /Detailed View/i }).click();

    const table = page.locator('table').first();
    await expect(table).toBeVisible({ timeout: 10_000 });

    // 60 min should produce ~24 data rows (one per hour)
    const rows = table.locator('tbody tr');
    const count = await rows.count();
    expect(count).toBeGreaterThanOrEqual(1);
    expect(count).toBeLessThanOrEqual(48); // at most 48 for safety
  });

  test('15 min detailed view shows table with more rows than 60 min', async ({ page }) => {
    await page.goto('/savings');
    await expect(page.getByRole('button', { name: /Detailed View/i })).toBeVisible({ timeout: 15_000 });

    // Get row count at 60 min
    await page.getByRole('button', { name: '60 min' }).click();
    await page.getByRole('button', { name: /Detailed View/i }).click();
    const table = page.locator('table').first();
    await expect(table).toBeVisible({ timeout: 10_000 });
    const count60 = await table.locator('tbody tr').count();

    // Switch to 15 min
    await page.getByRole('button', { name: '15 min' }).click();
    await expect(table).toBeVisible({ timeout: 10_000 });
    const count15 = await table.locator('tbody tr').count();

    // 15 min resolution should produce more rows than 60 min
    // (typically 4x, but at minimum more than 60 min)
    if (count60 > 0) {
      expect(count15).toBeGreaterThan(count60);
    }
  });

  test('switching resolutions does not break standard view chart', async ({ page }) => {
    await page.goto('/savings');
    await expect(page.getByText(/Hourly Battery Actions/i)).toBeVisible({ timeout: 15_000 });

    // Toggle back and forth between resolutions
    await page.getByRole('button', { name: '15 min' }).click();
    await expect(page.getByText(/Hourly Battery Actions/i)).toBeVisible();
    await expect(page.getByText('Something went wrong')).not.toBeVisible();

    await page.getByRole('button', { name: '60 min' }).click();
    await expect(page.getByText(/Hourly Battery Actions/i)).toBeVisible();
    await expect(page.getByText('Something went wrong')).not.toBeVisible();
  });
});
