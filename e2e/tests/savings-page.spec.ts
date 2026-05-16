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
});
