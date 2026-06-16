import { test, expect } from '@playwright/test';

test.describe('Settings Page', () => {
  test('loads and displays all setting tabs', async ({ page }) => {
    await page.goto('/settings');

    // Wait for loading to finish
    await expect(page.getByText('Loading settings')).not.toBeVisible({ timeout: 15_000 });

    // Settings page has tabbed navigation (exact match to avoid sensor group buttons)
    await expect(page.getByRole('button', { name: 'Integrations', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Electricity Pricing', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Battery', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Home', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'System', exact: true })).toBeVisible();
  });

  test('sensors tab shows sensor groups', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.getByText('Loading settings')).not.toBeVisible({ timeout: 15_000 });

    // Sensors tab is active by default — should show inverter platform selector
    await expect(page.getByText('Growatt').first()).toBeVisible();
  });

  test('battery tab shows capacity fields', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.getByText('Loading settings')).not.toBeVisible({ timeout: 15_000 });

    await page.getByRole('button', { name: 'Battery', exact: true }).click();

    // Should show capacity field
    await expect(page.getByText(/Total Capacity/i)).toBeVisible();
  });

  test('home tab shows consumption and grid settings', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.getByText('Loading settings')).not.toBeVisible({ timeout: 15_000 });

    await page.getByRole('button', { name: 'Home', exact: true }).click();

    // Home settings fields
    await expect(page.getByText(/Consumption/i).first()).toBeVisible();
  });

  test('pricing tab shows provider configuration', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.getByText('Loading settings')).not.toBeVisible({ timeout: 15_000 });

    await page.getByRole('button', { name: 'Electricity Pricing', exact: true }).click();

    // Should show pricing provider options
    await expect(page.getByText(/Nord Pool/i).first()).toBeVisible();
  });

  test('editing battery capacity enables save and persists', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.getByText('Loading settings')).not.toBeVisible({ timeout: 15_000 });

    await page.getByRole('button', { name: 'Battery', exact: true }).click();

    // Find the total capacity input
    const capacityInput = page.locator('label').filter({ hasText: /Total Capacity/i }).locator('input');
    await expect(capacityInput).toBeVisible();

    // Read current value
    const originalValue = await capacityInput.inputValue();

    // Change value
    await capacityInput.fill('17.5');

    // Save button (the blue button with text "Save" in the toolbar)
    const saveButton = page.getByRole('button', { name: 'Save', exact: true });
    await expect(saveButton).toBeEnabled();
    await saveButton.click();

    // Should show success feedback
    await expect(page.getByText(/saved|success/i).first()).toBeVisible({ timeout: 5_000 });

    // Reload and verify persistence
    await page.reload();
    await expect(page.getByText('Loading settings')).not.toBeVisible({ timeout: 15_000 });
    await page.getByRole('button', { name: 'Battery', exact: true }).click();

    const reloadedInput = page.locator('label').filter({ hasText: /Total Capacity/i }).locator('input');
    await expect(reloadedInput).toHaveValue('17.5');

    // Restore original value
    await reloadedInput.fill(originalValue);
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByText(/saved|success/i).first()).toBeVisible({ timeout: 5_000 });
  });

  test('system tab shows diagnostics', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.getByText('Loading settings')).not.toBeVisible({ timeout: 15_000 });

    await page.getByRole('button', { name: 'System', exact: true }).click();

    // System tab has Demo Mode section and Diagnostics section
    await expect(page.getByText('Demo Mode').first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('Diagnostics').first()).toBeVisible({ timeout: 10_000 });
  });
});
