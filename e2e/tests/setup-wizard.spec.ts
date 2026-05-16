import { test, expect, Page } from '@playwright/test';
import { EXPECTATIONS, WizardExpectation } from './wizard-expectations';

// ---------------------------------------------------------------------------
// Resolve scenario expectations from SCENARIO env var
// ---------------------------------------------------------------------------

const scenarioName = process.env.SCENARIO ?? 'ci-wizard-nordpool-min';
const expected: WizardExpectation = EXPECTATIONS[scenarioName] ?? EXPECTATIONS['ci-wizard-nordpool-min'];

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
// Tests
// ---------------------------------------------------------------------------

test.describe('Setup Wizard', () => {
  test('redirects to /setup when no sensors are configured', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL('/setup', { timeout: 15_000 });
  });

  test('discovers Growatt integration and sensors', async ({ page }) => {
    await page.goto('/setup');
    await expectActiveStep(page, 1);
    await expect(page.getByRole('heading', { name: 'Review Sensors' })).toBeVisible();

    // Growatt should always be found in our scenarios
    await expect(page.getByText('Growatt Server').first()).toBeVisible();
  });

  test('auto-selects correct pricing provider', async ({ page }) => {
    await page.goto('/setup');
    await expectActiveStep(page, 1);

    // Navigate to pricing step
    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();
    await expectActiveStep(page, 2);

    // Verify the correct provider is auto-selected
    if (expected.autoSelectedProvider === 'octopus') {
      await expect(radioByLabel(page, 'Octopus Energy')).toBeChecked();
    } else {
      await expect(radioByLabel(page, 'Nord Pool (official HA integration)')).toBeChecked();
    }
  });

  test('auto-detects correct inverter type', async ({ page }) => {
    await page.goto('/setup');
    await expectActiveStep(page, 1);

    // Navigate to battery step
    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();
    await page.getByRole('button', { name: /Next: Battery/i }).click();
    await expectActiveStep(page, 3);

    // Verify inverter type radio
    if (expected.inverterType === 'SPH') {
      await expect(radioByLabel(page, 'SPH (DC-coupled)')).toBeChecked();
    } else {
      await expect(radioByLabel(page, 'MIN (AC-coupled)')).toBeChecked();
    }
  });

  test('optional integrations show correct discovery status', async ({ page }) => {
    await page.goto('/setup');
    await expectActiveStep(page, 1);

    // Check optional integration visibility based on expectations
    if (expected.solcastFound) {
      // When found, Solcast section should have auto-filled sensors
      await expect(page.getByText('Solar Forecast (Solcast)').first()).toBeVisible();
    }
    if (expected.weatherFound) {
      await expect(page.getByText('Weather Integration').first()).toBeVisible();
    }
    if (expected.dischargeInhibitFound) {
      await expect(page.getByText('Discharge Inhibit').first()).toBeVisible();
    }
    if (expected.consumptionForecastFound) {
      await expect(page.getByText('Consumption Forecast').first()).toBeVisible();
    }
  });

  test('provider-specific fields shown correctly', async ({ page }) => {
    await page.goto('/setup');
    await expectActiveStep(page, 1);

    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();
    await expectActiveStep(page, 2);

    if (expected.autoSelectedProvider === 'octopus') {
      // Octopus fields should be visible
      await expect(fieldByLabel(page, 'Import today')).toBeVisible();
      await expect(fieldByLabel(page, 'Import tomorrow')).toBeVisible();
      await expect(fieldByLabel(page, 'Export today')).toBeVisible();
      await expect(fieldByLabel(page, 'Export tomorrow')).toBeVisible();
      // Nordpool fields should NOT be visible
      await expect(fieldByLabel(page, 'Config Entry ID')).not.toBeVisible();
    } else {
      // Nordpool fields should be visible
      await expect(fieldByLabel(page, 'Config Entry ID')).toBeVisible();
      // Octopus fields should NOT be visible
      await expect(fieldByLabel(page, 'Import today')).not.toBeVisible();
    }
  });

  test('can switch provider when both are available', async ({ page }) => {
    // Only meaningful when both providers are detected
    test.skip(!expected.nordpoolFound || !expected.octopusFound,
      'Scenario has only one provider');

    await page.goto('/setup');
    await expectActiveStep(page, 1);

    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();
    await expectActiveStep(page, 2);

    // Default should be nordpool_official when both are available
    await expect(radioByLabel(page, 'Nord Pool (official HA integration)')).toBeChecked();

    // Switch to Octopus
    await radioByLabel(page, 'Octopus Energy').click();
    await expect(radioByLabel(page, 'Octopus Energy')).toBeChecked();

    // Octopus fields should now appear
    await expect(fieldByLabel(page, 'Import today')).toBeVisible();
    await expect(fieldByLabel(page, 'Config Entry ID')).not.toBeVisible();

    // Switch back to Nordpool
    await radioByLabel(page, 'Nord Pool (official HA integration)').click();
    await expect(radioByLabel(page, 'Nord Pool (official HA integration)')).toBeChecked();
    await expect(fieldByLabel(page, 'Config Entry ID')).toBeVisible();
    await expect(fieldByLabel(page, 'Import today')).not.toBeVisible();
  });

  test('completes full wizard flow end-to-end', async ({ page }) => {
    await page.goto('/setup');

    // Step 0 → 1: Scan
    await expectActiveStep(page, 1);

    // Step 1 → 2: Confirm sensors
    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();
    await expectActiveStep(page, 2);

    // Step 2 → 3: Pricing (accept auto-selected defaults)
    await page.getByRole('button', { name: /Next: Battery/i }).click();
    await expectActiveStep(page, 3);

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

  test('can navigate back and forth without losing state', async ({ page }) => {
    await page.goto('/setup');
    await expectActiveStep(page, 1);

    // Forward to pricing
    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();
    await expectActiveStep(page, 2);

    // Back to sensors
    await page.getByRole('button', { name: /Back/i }).click();
    await expectActiveStep(page, 1);

    // Forward again — provider selection should persist
    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();
    await expectActiveStep(page, 2);

    if (expected.autoSelectedProvider === 'octopus') {
      await expect(radioByLabel(page, 'Octopus Energy')).toBeChecked();
    } else {
      await expect(radioByLabel(page, 'Nord Pool (official HA integration)')).toBeChecked();
    }
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
});
