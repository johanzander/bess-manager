import { test, expect, Page } from '@playwright/test';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Wait until the wizard step indicator shows the expected active step. */
async function expectActiveStep(page: Page, stepIndex: number) {
  const steps = page.locator('.rounded-full');
  await expect(steps.nth(stepIndex)).toHaveClass(/bg-blue-500/, { timeout: 15_000 });
}

/** Get an input field by its label text. */
function fieldByLabel(page: Page, label: string | RegExp) {
  return page.locator('label').filter({ hasText: label }).locator('input');
}

/** Get a radio button by its visible label text. */
function radioByLabel(page: Page, label: string) {
  return page.locator('label').filter({ hasText: label }).locator('input[type="radio"]');
}

// ---------------------------------------------------------------------------
// The SCENARIO env var determines which mock-HA scenario is running.
// CI starts the docker-compose stack with the right scenario before each
// Playwright project. See ci.yml for the orchestration.
//
// Locally, run:
//   SCENARIO=ci-wizard-nordpool-min docker compose -f docker-compose.ci.yml up -d
//   cd e2e && npx playwright test --project=wizard
// ---------------------------------------------------------------------------

test.describe('Setup Wizard', () => {
  test('redirects to /setup when no sensors are configured', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL('/setup', { timeout: 15_000 });
  });

  test('auto-discovery fills sensors and pricing from mock HA', async ({ page }) => {
    await page.goto('/setup');

    // Step 0 → 1: Auto-scan discovers sensors from mock HA
    await expectActiveStep(page, 1);
    await expect(page.getByRole('heading', { name: 'Review Sensors' })).toBeVisible();

    // Growatt integration should be detected
    await expect(page.getByText('Growatt Server').first()).toBeVisible();

    // Advance to pricing
    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();

    // Step 2: Pricing should be auto-filled from Nordpool discovery
    await expectActiveStep(page, 2);
    await expect(radioByLabel(page, 'Nord Pool (official HA integration)')).toBeChecked();
    // Area and currency come from the WS entity registry unique_id
    // and the _AREA_HINTS lookup (SE4 → SEK, 1.25)
    await expect(fieldByLabel(page, 'Currency')).not.toHaveValue('');
  });

  test('completes full wizard flow end-to-end', async ({ page }) => {
    await page.goto('/setup');

    // Step 0 → 1: Scan
    await expectActiveStep(page, 1);

    // Step 1 → 2: Confirm sensors
    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();
    await expectActiveStep(page, 2);

    // Step 2 → 3: Pricing (accept defaults)
    await page.getByRole('button', { name: /Next: Battery/i }).click();
    await expectActiveStep(page, 3);

    // Verify inverter type was auto-detected from mock HA services
    const minRadio = radioByLabel(page, 'MIN (AC-coupled)');
    const sphRadio = radioByLabel(page, 'SPH (DC-coupled)');
    // One of them should be checked (depending on which scenario is running)
    const minChecked = await minRadio.isChecked().catch(() => false);
    const sphChecked = await sphRadio.isChecked().catch(() => false);
    expect(minChecked || sphChecked).toBe(true);

    // Edit battery capacity
    await fieldByLabel(page, /Total Capacity/).fill('15');

    // Step 3 → 4: Battery
    await page.getByRole('button', { name: /Next: Home/i }).click();
    await expectActiveStep(page, 4);

    // Step 4 → 5: Finish
    await page.getByRole('button', { name: /Finish Setup/i }).click();

    // Step 5: Done — saved to real backend
    await expect(page.getByText('Setup Complete!')).toBeVisible();
    await expect(page.getByText('15 kWh')).toBeVisible();
    await expect(page.getByRole('button', { name: /Go to Dashboard/i })).toBeVisible();
  });

  test('can navigate back and forth between steps', async ({ page }) => {
    await page.goto('/setup');
    await expectActiveStep(page, 1);

    // Forward to pricing
    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();
    await expectActiveStep(page, 2);

    // Back to sensors
    await page.getByRole('button', { name: /Back/i }).click();
    await expectActiveStep(page, 1);

    // Forward again — pricing data should still be there
    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();
    await expect(fieldByLabel(page, 'Currency')).not.toHaveValue('');
  });

  test('edited battery values appear in summary', async ({ page }) => {
    await page.goto('/setup');
    await expectActiveStep(page, 1);

    // Step 1 → 2
    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();
    // Step 2 → 3
    await page.getByRole('button', { name: /Next: Battery/i }).click();

    // Edit battery values
    await fieldByLabel(page, /Total Capacity/).fill('20');
    await fieldByLabel(page, /Min SOC/).fill('10');
    await fieldByLabel(page, /Max SOC/).fill('90');

    // Step 3 → 4
    await page.getByRole('button', { name: /Next: Home/i }).click();
    // Step 4 → 5
    await page.getByRole('button', { name: /Finish Setup/i }).click();

    // Verify edited values in summary
    await expect(page.getByText('Setup Complete!')).toBeVisible();
    await expect(page.getByText('20 kWh')).toBeVisible();
    await expect(page.getByText('10% – 90%')).toBeVisible();
  });

  test('can switch to Octopus Energy provider', async ({ page }) => {
    await page.goto('/setup');
    await expectActiveStep(page, 1);

    // Step 1 → 2
    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();
    await expectActiveStep(page, 2);

    // Switch to Octopus
    await radioByLabel(page, 'Octopus Energy').click();
    await expect(radioByLabel(page, 'Octopus Energy')).toBeChecked();

    // Octopus-specific fields should appear
    await expect(fieldByLabel(page, 'Import today')).toBeVisible();
    await expect(fieldByLabel(page, 'Import tomorrow')).toBeVisible();
    await expect(fieldByLabel(page, 'Export today')).toBeVisible();
    await expect(fieldByLabel(page, 'Export tomorrow')).toBeVisible();

    // Nordpool fields should be hidden
    await expect(fieldByLabel(page, 'Config Entry ID')).not.toBeVisible();

    // Octopus description
    await expect(page.getByText('Octopus prices are already final')).toBeVisible();

    // Fill entities and complete the flow
    await fieldByLabel(page, 'Import today').fill('sensor.octopus_import_today');
    await fieldByLabel(page, 'Import tomorrow').fill('sensor.octopus_import_tomorrow');
    await fieldByLabel(page, 'Export today').fill('sensor.octopus_export_today');
    await fieldByLabel(page, 'Export tomorrow').fill('sensor.octopus_export_tomorrow');

    // Step 2 → 3 → 4 → 5
    await page.getByRole('button', { name: /Next: Battery/i }).click();
    await page.getByRole('button', { name: /Next: Home/i }).click();
    await page.getByRole('button', { name: /Finish Setup/i }).click();

    await expect(page.getByText('Setup Complete!')).toBeVisible();
    await expect(page.getByText('octopus')).toBeVisible();
  });
});
