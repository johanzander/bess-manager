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

  test('consumption strategy "Home Assistant sensor" is blocked without its sensor', async ({ page }) => {
    // Issue #558: selecting this strategy without a 48h_avg_grid_import entity
    // makes every optimization run abort, so no schedule is ever built and the
    // dashboard sits on "Initializing" forever. The CI settings fixture has no
    // such sensor configured, so the option must be unselectable here.
    await page.goto('/settings');
    await expect(page.getByText('Loading settings')).not.toBeVisible({ timeout: 15_000 });

    await page.getByRole('button', { name: 'Home', exact: true }).click();

    const sensorOption = page.getByRole('radio', { name: 'Home Assistant sensor' });
    await expect(sensorOption).toBeDisabled();
    await expect(sensorOption).not.toBeChecked();
    await expect(
      page.getByText(/requires the 48h Avg Grid Import sensor/i),
    ).toBeVisible();

    // "Fixed value" needs no sensor and stays selectable — the guard must not
    // leave the user with nothing to choose.
    await expect(page.getByRole('radio', { name: 'Fixed value' })).toBeEnabled();
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

test.describe('Inverter service domain override', () => {
  // The vendor service domain (huawei_solar / growatt_server) used to be
  // hardcoded, which forced a compatible integration under a different domain
  // name to become a whole new BESS platform (PR #412). It is now an override
  // on the inverter section, editable per install.
  //
  // The inverter form renders on the Integrations tab but is saved by the
  // Battery tab's Save button (isDirty.battery covers inverterForm) — the
  // spec follows that existing flow deliberately.

  const serviceDomainInput = (page: import('@playwright/test').Page) =>
    page.locator('label').filter({ hasText: /Service domain/i }).locator('input');

  test('shows the platform default as placeholder, not a value', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.getByText('Loading settings')).not.toBeVisible({ timeout: 15_000 });

    const input = serviceDomainInput(page);
    await expect(input).toBeVisible();
    // Empty override — the effective domain is shown as a placeholder so an
    // untouched install stays on the platform default.
    await expect(input).toHaveValue('');
    await expect(input).toHaveAttribute('placeholder', 'growatt_server');
  });

  test('override persists across a reload', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.getByText('Loading settings')).not.toBeVisible({ timeout: 15_000 });

    await serviceDomainInput(page).fill('my_growatt_bridge');

    // The tab button is renamed to "Battery Unsaved changes" once the form is
    // dirty, so this cannot match on the exact label.
    await page.getByRole('button', { name: /^Battery( Unsaved changes)?$/ }).click();
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByText(/saved|success/i).first()).toBeVisible({ timeout: 5_000 });

    await page.reload();
    await expect(page.getByText('Loading settings')).not.toBeVisible({ timeout: 15_000 });
    await expect(serviceDomainInput(page)).toHaveValue('my_growatt_bridge');

    // Restore the default so later tests see an unmodified install.
    await serviceDomainInput(page).fill('');
    await page.getByRole('button', { name: /^Battery( Unsaved changes)?$/ }).click();
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByText(/saved|success/i).first()).toBeVisible({ timeout: 5_000 });
  });
});
