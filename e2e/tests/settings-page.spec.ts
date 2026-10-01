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

  test('peak shaving window enables and persists (#96)', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.getByText('Loading settings')).not.toBeVisible({ timeout: 15_000 });

    await page.getByRole('button', { name: 'Home', exact: true }).click();

    // Fields are hidden until the toggle is enabled
    await expect(page.getByText(/Window start/i)).not.toBeVisible();
    await page.getByRole('switch', { name: 'Enable peak shaving' }).click();
    await expect(page.getByText(/Window start/i)).toBeVisible();

    const startInput = page.locator('label').filter({ hasText: /Window start/i }).locator('input');
    await startInput.fill('06:00');
    const capInput = page.locator('label').filter({ hasText: /Max grid import during window/i }).locator('input');
    await capInput.fill('2.5');

    const saveButton = page.getByRole('button', { name: 'Save', exact: true });
    await expect(saveButton).toBeEnabled();
    await saveButton.click();
    await expect(page.getByText(/saved|success/i).first()).toBeVisible({ timeout: 5_000 });

    await page.reload();
    await expect(page.getByText('Loading settings')).not.toBeVisible({ timeout: 15_000 });
    await page.getByRole('button', { name: 'Home', exact: true }).click();

    await expect(page.getByRole('switch', { name: 'Enable peak shaving' })).toHaveAttribute('aria-checked', 'true');
    const reloadedStart = page.locator('label').filter({ hasText: /Window start/i }).locator('input');
    await expect(reloadedStart).toHaveValue('06:00');
    const reloadedCap = page.locator('label').filter({ hasText: /Max grid import during window/i }).locator('input');
    await expect(reloadedCap).toHaveValue('2.5');

    // Restore disabled so this test leaves the fixture as it found it.
    await page.getByRole('switch', { name: 'Enable peak shaving' }).click();
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

test.describe('Control mode persists when saved from the Integrations tab (#787)', () => {
  // The Control Mode (TOU/VPP) toggle renders on the Integrations tab
  // alongside the platform picker and that platform's sensor list — it needs
  // to stay there, since switching platform changes which sensors apply.
  // Until #787 was fixed, the Integrations tab's own Save button did not
  // persist inverterForm at all (isDirty.sensors never saw it, and
  // saveSensors()'s payload never included an `inverter` key), so this is
  // the reporter's exact repro: no tab switch, just the Integrations tab's
  // Save button.

  test('switching to VPP enables Save on the Integrations tab and actually reaches the backend', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.getByText('Loading settings')).not.toBeVisible({ timeout: 15_000 });

    // Default CI fixture is growatt_server_min (cloud) — switch to the SolaX
    // Modbus / Growatt MIN(GEN4) platform, the only one with a Control Mode
    // toggle. (The CI fixture has no sensors mapped for this platform, so a
    // full page reload afterwards would land on the setup wizard rather than
    // Settings — the assertions below check persistence via the settings API
    // directly instead, which is what actually regressed and is unaffected by
    // that unrelated completeness gate.)
    await page.getByRole('tab', { name: 'SolaX Modbus' }).click();
    await page.getByRole('button', { name: 'Growatt MIN/GEN4' }).click();

    const saveButton = page.getByRole('button', { name: 'Save', exact: true });

    await page.getByRole('button', { name: 'VPP Remote Power' }).click();

    // Symptom 1: Save must not stay disabled just because the only change
    // was to inverterForm.
    await expect(saveButton).toBeEnabled();
    await saveButton.click();
    await expect(page.getByText(/saved|success/i).first()).toBeVisible({ timeout: 5_000 });

    // Symptom 2: the save must have actually reached the backend, not just
    // updated React state and shown a success toast.
    const afterSave = await (await page.request.get('/api/settings')).json();
    expect(afterSave.inverter.platform).toBe('solax_modbus_growatt_min');
    expect(afterSave.inverter.controlMode).toBe('vpp');

    // Restore TOU and the original platform so later tests see an unmodified
    // install — no reload needed, so the wizard-redirect gate above never
    // applies. (Switching platform alone does not reset controlMode — only
    // deviceId/serviceDomain — so it must be flipped back explicitly too.)
    await page.getByRole('tab', { name: 'SolaX Modbus' }).click();
    await page.getByRole('button', { name: 'TOU Schedule (default)' }).click();
    await page.getByRole('tab', { name: 'Growatt Cloud' }).click();
    await expect(saveButton).toBeEnabled();
    await saveButton.click();
    await expect(page.getByText(/saved|success/i).first()).toBeVisible({ timeout: 5_000 });

    const restored = await (await page.request.get('/api/settings')).json();
    expect(restored.inverter.platform).toBe('growatt_server_min');
    expect(restored.inverter.controlMode).toBe('tou');
  });
});

test.describe('Inverter service domain override', () => {
  // The vendor service domain (huawei_solar / growatt_server) used to be
  // hardcoded, which forced a compatible integration under a different domain
  // name to become a whole new BESS platform (PR #412). It is now an override
  // on the inverter section, editable per install.
  //
  // The inverter form renders on the Integrations tab, and (since #787) is
  // saved correctly by either the Integrations tab's own Save button or the
  // Battery tab's — this spec exercises the Battery-tab path, which was
  // always correct, as a second independent route to the same data.

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
