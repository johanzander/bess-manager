import { test, expect, Page } from '@playwright/test';
import nordpoolMin from '../fixtures/wizard-nordpool-min.json';
import nordpoolSph from '../fixtures/wizard-nordpool-sph.json';
import octopusMin from '../fixtures/wizard-octopus-min.json';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface WizardFixture {
  setupStatus: { wizardNeeded: boolean; configuredSensors: number; totalSensors: number };
  discovery: Record<string, unknown>;
}

/**
 * Intercept the backend API calls so the wizard runs entirely against
 * canned fixture data.  This lets us test the full UI flow without
 * needing a specific docker-compose / mock-HA scenario per config.
 */
async function mockWizardAPIs(page: Page, fixture: WizardFixture) {
  const fulfill = (route: import('@playwright/test').Route, body: unknown) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

  // Intercept only /api/setup/* endpoints with a single route handler.
  // Other API calls (e.g. /api/settings, /api/dashboard) pass through to
  // the real backend — the app needs them to render without errors before
  // the SetupGuard redirect fires.
  await page.route(
    url => url.pathname.startsWith('/api/setup/'),
    route => {
      const path = new URL(route.request().url()).pathname;
      switch (path) {
        case '/api/setup/status':
          return fulfill(route, fixture.setupStatus);
        case '/api/setup/discover':
          return fulfill(route, fixture.discovery);
        case '/api/setup/confirm':
          return fulfill(route, { success: true, applied_sensors: 12 });
        case '/api/setup/complete':
          return fulfill(route, {
            success: true,
            saved_sections: ['sensors', 'battery', 'home', 'electricity_price', 'energy_provider', 'growatt'],
          });
        default:
          return route.continue();
      }
    },
  );
}

/** Wait until the wizard step indicator shows the expected active step. */
async function expectActiveStep(page: Page, stepIndex: number) {
  // Step indicators are circles; the active one has bg-blue-500
  const steps = page.locator('.rounded-full');
  await expect(steps.nth(stepIndex)).toHaveClass(/bg-blue-500/, { timeout: 10_000 });
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

test.describe('Setup Wizard — Nordpool + MIN inverter', () => {
  test.beforeEach(async ({ page }) => {
    await mockWizardAPIs(page, nordpoolMin);
  });

  test('redirects to /setup when wizard is needed', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL('/setup', { timeout: 10_000 });
  });

  test('completes full wizard flow with defaults', async ({ page }) => {
    await page.goto('/setup');

    // ── Step 0 → 1: Auto-scan advances to Review Sensors ──────────────
    await expectActiveStep(page, 1);
    await expect(page.getByRole('heading', { name: 'Review Sensors' })).toBeVisible();

    // Verify Growatt integration section is present
    await expect(page.getByText('Growatt Server').first()).toBeVisible();

    // Click "Next: Electricity Pricing"
    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();

    // ── Step 2: Electricity Pricing ───────────────────────────────────
    await expectActiveStep(page, 2);
    await expect(page.getByRole('heading', { name: 'Electricity Pricing' })).toBeVisible();

    // Verify auto-filled values from discovery
    await expect(radioByLabel(page, 'Nord Pool (official HA integration)')).toBeChecked();
    await expect(fieldByLabel(page, 'Price Area')).toHaveValue('SE4');
    await expect(fieldByLabel(page, 'Currency')).toHaveValue('SEK');
    await expect(fieldByLabel(page, /VAT Multiplier/)).toHaveValue('1.25');

    // Click "Next: Battery"
    await page.getByRole('button', { name: /Next: Battery/i }).click();

    // ── Step 3: Battery ───────────────────────────────────────────────
    await expectActiveStep(page, 3);
    await expect(page.getByRole('heading', { name: 'Battery' }).first()).toBeVisible();

    // Verify inverter type auto-detected as MIN
    await expect(radioByLabel(page, 'MIN (AC-coupled)')).toBeChecked();

    // Adjust total capacity from default 30 to 15
    const capacityInput = fieldByLabel(page, /Total Capacity/);
    await capacityInput.fill('15');

    // Click "Next: Home"
    await page.getByRole('button', { name: /Next: Home/i }).click();

    // ── Step 4: Home ──────────────────────────────────────────────────
    await expectActiveStep(page, 4);
    await expect(page.getByRole('heading', { name: 'Home' }).first()).toBeVisible();

    // Click "Finish Setup"
    await page.getByRole('button', { name: /Finish Setup/i }).click();

    // ── Step 5: Done ──────────────────────────────────────────────────
    await expectActiveStep(page, 5);
    await expect(page.getByText('Setup Complete!')).toBeVisible();

    // Verify summary values
    await expect(page.getByText('15 kWh')).toBeVisible();
    await expect(page.getByText('MIN')).toBeVisible();
    await expect(page.getByText('SEK')).toBeVisible();
    await expect(page.getByText('nordpool_official')).toBeVisible();

    // Verify dashboard navigation button is present
    // (Actually clicking it would re-trigger the mocked SetupGuard redirect,
    // since our mock always returns wizardNeeded=true.)
    await expect(page.getByRole('button', { name: /Go to Dashboard/i })).toBeVisible();
  });
});

test.describe('Setup Wizard — Nordpool + SPH inverter', () => {
  test.beforeEach(async ({ page }) => {
    await mockWizardAPIs(page, nordpoolSph);
  });

  test('completes wizard flow with SPH inverter detected', async ({ page }) => {
    await page.goto('/setup');

    // ── Step 0 → 1: Scan ─────────────────────────────────────────────
    await expectActiveStep(page, 1);

    // Advance through sensors
    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();

    // ── Step 2: Pricing — verify SE3 area ────────────────────────────
    await expectActiveStep(page, 2);
    await expect(fieldByLabel(page, 'Price Area')).toHaveValue('SE3');

    await page.getByRole('button', { name: /Next: Battery/i }).click();

    // ── Step 3: Battery — verify SPH auto-detected ───────────────────
    await expectActiveStep(page, 3);
    await expect(radioByLabel(page, 'SPH (DC-coupled)')).toBeChecked();

    await page.getByRole('button', { name: /Next: Home/i }).click();

    // ── Step 4: Home ──────────────────────────────────────────────────
    await expectActiveStep(page, 4);
    await page.getByRole('button', { name: /Finish Setup/i }).click();

    // ── Step 5: Done ──────────────────────────────────────────────────
    await expect(page.getByText('Setup Complete!')).toBeVisible();
    await expect(page.getByText('SPH')).toBeVisible();
  });
});

test.describe('Setup Wizard — Octopus Energy', () => {
  test.beforeEach(async ({ page }) => {
    await mockWizardAPIs(page, octopusMin);
  });

  test('completes wizard flow with Octopus provider', async ({ page }) => {
    await page.goto('/setup');

    // ── Step 0 → 1: Scan ─────────────────────────────────────────────
    await expectActiveStep(page, 1);
    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();

    // ── Step 2: Pricing — switch to Octopus ──────────────────────────
    await expectActiveStep(page, 2);

    // Nordpool not found, so provider defaults to nordpool_official.
    // User must manually switch to Octopus.
    await radioByLabel(page, 'Octopus Energy').click();
    await expect(radioByLabel(page, 'Octopus Energy')).toBeChecked();

    // Octopus-specific entity fields should appear
    await expect(fieldByLabel(page, 'Import today')).toBeVisible();
    await expect(fieldByLabel(page, 'Import tomorrow')).toBeVisible();
    await expect(fieldByLabel(page, 'Export today')).toBeVisible();
    await expect(fieldByLabel(page, 'Export tomorrow')).toBeVisible();

    // Nordpool fields should NOT be visible
    await expect(fieldByLabel(page, 'Config Entry ID')).not.toBeVisible();

    // Fill in Octopus entity IDs
    await fieldByLabel(page, 'Import today').fill('sensor.octopus_import_today');
    await fieldByLabel(page, 'Import tomorrow').fill('sensor.octopus_import_tomorrow');
    await fieldByLabel(page, 'Export today').fill('sensor.octopus_export_today');
    await fieldByLabel(page, 'Export tomorrow').fill('sensor.octopus_export_tomorrow');

    // Octopus pricing section shows simplified form (no markup/VAT)
    await expect(page.getByText('Octopus prices are already final')).toBeVisible();

    await page.getByRole('button', { name: /Next: Battery/i }).click();

    // ── Step 3: Battery ───────────────────────────────────────────────
    await expectActiveStep(page, 3);
    await page.getByRole('button', { name: /Next: Home/i }).click();

    // ── Step 4: Home ──────────────────────────────────────────────────
    await expectActiveStep(page, 4);
    await page.getByRole('button', { name: /Finish Setup/i }).click();

    // ── Step 5: Done ──────────────────────────────────────────────────
    await expect(page.getByText('Setup Complete!')).toBeVisible();
    await expect(page.getByText('octopus')).toBeVisible();
  });
});

test.describe('Setup Wizard — form editing', () => {
  test.beforeEach(async ({ page }) => {
    await mockWizardAPIs(page, nordpoolMin);
  });

  test('can navigate back and forth between steps', async ({ page }) => {
    await page.goto('/setup');
    await expectActiveStep(page, 1);

    // Go forward to pricing
    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();
    await expectActiveStep(page, 2);

    // Go back to sensors
    await page.getByRole('button', { name: /Back/i }).click();
    await expectActiveStep(page, 1);

    // Go forward again — data should still be there
    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();
    await expect(fieldByLabel(page, 'Price Area')).toHaveValue('SE4');
  });

  test('edited battery values appear in summary', async ({ page }) => {
    await page.goto('/setup');
    await expectActiveStep(page, 1);

    // Step 1 → 2
    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();
    // Step 2 → 3
    await page.getByRole('button', { name: /Next: Battery/i }).click();

    // Edit battery capacity and SOC
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
