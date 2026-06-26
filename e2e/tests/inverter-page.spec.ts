import { test, expect } from '@playwright/test';

test.describe('Inverter Page', () => {
  test('loads and shows page heading', async ({ page }) => {
    await page.goto('/inverter');

    await expect(
      page.getByRole('heading', { name: /Inverter and Battery Insights/i })
    ).toBeVisible({ timeout: 15_000 });
  });

  test('shows battery SOC percentage', async ({ page }) => {
    await page.goto('/inverter');

    // Wait for page to load
    await expect(
      page.getByRole('heading', { name: /Inverter and Battery Insights/i })
    ).toBeVisible({ timeout: 15_000 });

    // Battery SOC is shown as "XX%" — look for the specific SOC display
    await expect(page.getByText('%').first()).toBeVisible();
  });

  test('shows schedule overview section', async ({ page }) => {
    await page.goto('/inverter');

    await expect(
      page.getByRole('heading', { name: /Schedule Overview/i })
    ).toBeVisible({ timeout: 15_000 });
  });

  test('shows TOU intervals section', async ({ page }) => {
    await page.goto('/inverter');

    await expect(
      page.getByRole('heading', { name: /Time of Use.*Intervals/i })
    ).toBeVisible({ timeout: 15_000 });
  });

  test('schedule shows period data', async ({ page }) => {
    await page.goto('/inverter');

    // Wait for schedule to load
    await expect(
      page.getByRole('heading', { name: /Schedule Overview/i })
    ).toBeVisible({ timeout: 15_000 });

    // The schedule groups should show time ranges (e.g., "00:00" start time)
    await expect(page.getByText('00:00').first()).toBeVisible();
  });

  test('shows strategic intent labels', async ({ page }) => {
    await page.goto('/inverter');

    // Wait for data to load
    await expect(
      page.getByRole('heading', { name: /Schedule Overview/i })
    ).toBeVisible({ timeout: 15_000 });

    // At least one strategic intent should be visible in the schedule
    const intentPattern = /GRID_CHARGING|SOLAR_CHARGING|IDLE|BATTERY_EXPORT|SELF_CONSUMPTION|LOAD_SUPPORT|SOLAR_STORAGE/;
    await expect(page.getByText(intentPattern).first()).toBeVisible();
  });
});
