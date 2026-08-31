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

/** Get an input field by its label text (excludes radio buttons). */
function fieldByLabel(page: Page, label: string | RegExp) {
  return page.locator('label').filter({ hasText: label }).locator('input:not([type="radio"])');
}

/** Get a radio button by its visible label text. */
function radioByLabel(page: Page, label: string) {
  return page.locator('label').filter({ hasText: label }).locator('input[type="radio"]');
}

/** Map provider key to its visible radio label. */
const PROVIDER_LABEL: Record<string, string> = {
  nordpool_official: 'Nord Pool (official HA integration)',
  nordpool_hacs: 'Nord Pool (HACS custom sensor)',
  octopus: 'Octopus Energy',
  entsoe: 'ENTSO-e / Belpex (Transparency Platform)',
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

/**
 * Some scenarios exist to prove a wizard gate holds (#549), so the step
 * they block is unreachable by design. Call these as the first line of any
 * test that navigates past that step.
 */
function skipIfSensorStepBlocked() {
  test.skip(
    !!expected.sensorStepBlocked,
    'scenario deliberately blocks the sensor step (disabled entities)',
  );
}
function skipIfPricingStepBlocked() {
  test.skip(
    !!expected.sensorStepBlocked || !!expected.pricingBlocked,
    'scenario deliberately blocks the sensor or pricing step',
  );
}

test.describe('Setup Wizard', () => {

  test('redirects to /setup when no sensors are configured', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL('/setup', { timeout: 15_000 });
  });

  test('discovers inverter integration and sensors', async ({ page }) => {
    await page.goto('/setup');
    await expectActiveStep(page, 1);
    await expect(page.getByRole('heading', { name: 'Review Sensors' })).toBeVisible();

    // Verify the inverter platform tabs are visible
    // All three tabs are always rendered — check the active one matches detection
    await expect(page.getByRole('tab', { name: /Growatt Cloud/i })).toBeVisible();
    await expect(page.getByRole('tab', { name: /SolaX Modbus/i })).toBeVisible();
    await expect(page.getByRole('tab', { name: /Solis Modbus/i })).toBeVisible();
  });

  test('auto-selects correct pricing provider', async ({ page }) => {
    skipIfSensorStepBlocked()
    await page.goto('/setup');
    await expectActiveStep(page, 1);

    // Navigate to pricing step
    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();
    await expectActiveStep(page, 2);

    // Verify the correct provider is auto-selected
    const providerLabel = PROVIDER_LABEL[expected.autoSelectedProvider];
    await expect(radioByLabel(page, providerLabel)).toBeChecked();
  });

  test('auto-detects correct inverter type', async ({ page }) => {
    await page.goto('/setup');
    await expectActiveStep(page, 1);

    // The UI uses Tabs (Growatt Cloud / SolaX Modbus / Solis Modbus) + pill buttons for subtypes
    const isModbus = expected.inverterPlatform.startsWith('solax_modbus');
    const isCloud = expected.inverterPlatform.startsWith('growatt_server');
    const isSolis = expected.inverterPlatform === 'solis_modbus';

    if (isCloud) {
      // Growatt Cloud tab should be active
      await expect(page.getByRole('tab', { name: /Growatt Cloud/i })).toHaveAttribute('data-state', 'active');
    } else if (isModbus) {
      // SolaX Modbus tab should be active
      await expect(page.getByRole('tab', { name: /SolaX Modbus/i })).toHaveAttribute('data-state', 'active');
    } else if (isSolis) {
      // Solis Modbus tab should be active
      await expect(page.getByRole('tab', { name: /Solis Modbus/i })).toHaveAttribute('data-state', 'active');
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
    skipIfSensorStepBlocked()
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
      await expect(fieldByLabel(page, 'Sensor')).not.toBeVisible();
    } else if (expected.autoSelectedProvider === 'nordpool_hacs') {
      // HACS Nordpool shows Sensor field, not Config Entry ID
      await expect(fieldByLabel(page, 'Sensor')).toBeVisible();
      await expect(fieldByLabel(page, 'Config Entry ID')).not.toBeVisible();
      await expect(fieldByLabel(page, 'Import today')).not.toBeVisible();
    } else if (expected.autoSelectedProvider === 'entsoe') {
      // ENTSO-e shows a single Sensor field, not Config Entry ID or Octopus fields
      await expect(fieldByLabel(page, 'Sensor')).toBeVisible();
      await expect(fieldByLabel(page, 'Config Entry ID')).not.toBeVisible();
      await expect(fieldByLabel(page, 'Import today')).not.toBeVisible();
    } else {
      // Official Nordpool shows Config Entry ID
      await expect(fieldByLabel(page, 'Config Entry ID')).toBeVisible();
      await expect(fieldByLabel(page, 'Sensor')).not.toBeVisible();
      await expect(fieldByLabel(page, 'Import today')).not.toBeVisible();
    }
  });

  test('can switch provider when both are available', async ({ page }) => {
    skipIfSensorStepBlocked()
    // Only meaningful when both providers are detected
    test.skip(!expected.nordpoolFound || !expected.octopusFound,
      'Scenario has only one provider');

    await page.goto('/setup');
    await expectActiveStep(page, 1);

    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();
    await expectActiveStep(page, 2);

    // Auto-selected provider should be checked
    const defaultLabel = PROVIDER_LABEL[expected.autoSelectedProvider];
    await expect(radioByLabel(page, defaultLabel)).toBeChecked();

    // Switch to Octopus
    await radioByLabel(page, 'Octopus Energy').click();
    await expect(radioByLabel(page, 'Octopus Energy')).toBeChecked();

    // Octopus fields should now appear
    await expect(fieldByLabel(page, 'Import today')).toBeVisible();
    await expect(fieldByLabel(page, 'Config Entry ID')).not.toBeVisible();

    // Switch back to the original provider
    await radioByLabel(page, defaultLabel).click();
    await expect(radioByLabel(page, defaultLabel)).toBeChecked();
    await expect(fieldByLabel(page, 'Import today')).not.toBeVisible();
  });

  test('completes full wizard flow end-to-end', async ({ page }) => {
    skipIfPricingStepBlocked()
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

    // Step 4 → 5: Control Mode
    await page.getByRole('button', { name: /Next: Control Mode/i }).click();
    await expectActiveStep(page, 5);

    // Config summary should show edited battery capacity
    await expect(page.getByText('15 kWh')).toBeVisible();

    // Select Live Control and complete
    await page.getByText('Live Control').click();
    await page.getByRole('button', { name: /Complete Setup/i }).click();

    // Step 6: Done — saved to real backend
    await expect(page.getByText('Setup Complete!')).toBeVisible();
    await expect(page.getByRole('button', { name: /Go to Dashboard/i })).toBeVisible();
  });

  test('can navigate back and forth without losing state', async ({ page }) => {
    skipIfSensorStepBlocked()
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

    const providerLabel2 = PROVIDER_LABEL[expected.autoSelectedProvider];
    await expect(radioByLabel(page, providerLabel2)).toBeChecked();
  });

  test('edited battery values appear in summary', async ({ page }) => {
    skipIfPricingStepBlocked()
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
    // Step 4 → 5: Control Mode
    await page.getByRole('button', { name: /Next: Control Mode/i }).click();
    await expectActiveStep(page, 5);

    // Verify edited values in summary on Control Mode step
    await expect(page.getByText('20 kWh')).toBeVisible();
    await expect(page.getByText('10% – 90%')).toBeVisible();

    // Select Live Control and complete
    await page.getByText('Live Control').click();
    await page.getByRole('button', { name: /Complete Setup/i }).click();

    await expect(page.getByText('Setup Complete!')).toBeVisible();
  });

  test('home step gates features by platform capabilities', async ({ page }) => {
    skipIfPricingStepBlocked()
    // SPH lacks local_load_power; SolaX native has it (as house_load)
    const platformsWithoutLocalLoad = ['growatt_server_sph'];
    const platformsWithoutChargeRate = ['growatt_server_sph', 'solax_modbus_native', 'solis_modbus'];
    const expectLoadPowerAvgDisabled = platformsWithoutLocalLoad.includes(expected.inverterPlatform);
    // Fuse protection also needs phase-current sensors (current_l1/l2/l3) discovered,
    // independent of the platform's charge-rate-control capability — a platform that
    // supports charge rate control can still lack phase sensors on an install with no
    // CT clamps configured. Most fixtures provide both; noPhaseSensors opts a scenario
    // out explicitly instead of overloading the (separately-purposed) phaseCount field.
    const expectFuseDisabled =
      platformsWithoutChargeRate.includes(expected.inverterPlatform) || expected.noPhaseSensors === true;

    await page.goto('/setup');
    await expectActiveStep(page, 1);

    // Navigate to Home step (step 4)
    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();
    await expectActiveStep(page, 2);
    await page.getByRole('button', { name: /Next: Battery/i }).click();
    await expectActiveStep(page, 3);
    await page.getByRole('button', { name: /Next: Home/i }).click();
    await expectActiveStep(page, 4);

    // Load Power 7-day Avg radio should be disabled on platforms without local_load_power
    const loadPowerAvgRadio = radioByLabel(page, 'Load Power 7-day Avg');
    if (expectLoadPowerAvgDisabled) {
      await expect(loadPowerAvgRadio).toBeDisabled();
    } else {
      await expect(loadPowerAvgRadio).toBeEnabled();
    }

    // Fuse protection toggle should be disabled on platforms without charge rate control
    const fuseToggle = page.getByRole('switch', { name: /Enable fuse protection/i });
    if (expectFuseDisabled) {
      await expect(fuseToggle).toBeDisabled();
    } else {
      await expect(fuseToggle).toBeEnabled();
    }
  });

  test('partial phase-current discovery does not auto-enable fuse protection or seed an invalid phase count', async ({ page }) => {
    skipIfPricingStepBlocked()
    // Regression test: discovery finding only 2 of the 3 current_l1/l2/l3
    // sensors (detectedPhaseCount === 2) must not auto-enable fuse
    // protection (current_l3 is missing, so real-time monitoring would
    // crash on a None read) and must not seed HomeSettings.phase_count with
    // the raw count 2, which core/bess/settings.py rejects (only 1 or 3 are
    // valid). Stubs POST /api/setup/discover directly, following the
    // page.route() mocking pattern used in inverter-schedule-control-model.spec.ts,
    // since no mock-HA fixture scenario currently reproduces a partial
    // phase-sensor discovery.
    //
    // Also stubs GET /api/settings to a clean baseline: this test runs after
    // other tests in this file that complete the wizard for real against the
    // shared backend, which can leave power_monitoring_enabled=true (and
    // current_l1/2/3 sensors) already persisted. Without this stub, the
    // wizard's "load existing settings" step (SetupWizardPage.tsx) would
    // pick up that leftover state and mask the very regression this test
    // exists to catch.
    await page.route('**/api/settings', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          battery: {},
          home: {},
          electricityPrice: {},
          energyProvider: {},
          growatt: {},
          sensors: {},
        }),
      });
    });

    const growattRequiredSensors = {
      battery_soc: 'sensor.battery_soc',
      battery_charge_power: 'sensor.battery_charge_power',
      battery_discharge_power: 'sensor.battery_discharge_power',
      battery_charge_stop_soc: 'number.battery_charge_stop_soc',
      battery_discharge_stop_soc: 'number.battery_discharge_stop_soc',
      battery_charging_power_rate: 'number.battery_charging_power_rate',
      battery_discharging_power_rate: 'number.battery_discharging_power_rate',
      grid_charge: 'switch.grid_charge',
      lifetime_battery_charged: 'sensor.lifetime_battery_charged',
      lifetime_battery_discharged: 'sensor.lifetime_battery_discharged',
      lifetime_solar_energy: 'sensor.lifetime_solar_energy',
      lifetime_export_to_grid: 'sensor.lifetime_export_to_grid',
      lifetime_import_from_grid: 'sensor.lifetime_import_from_grid',
      lifetime_load_consumption: 'sensor.lifetime_load_consumption',
    };

    await page.route('**/api/setup/discover', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          growattFound: true,
          growattDeviceId: 'device1',
          solaxFound: false,
          solaxHasGrowattTou: false,
          solaxHasGrowattGen3: false,
          solisFound: false,
          huaweiFound: false,
          huaweiDeviceId: null,
          nordpoolFound: true,
          nordpoolArea: 'SE3',
          nordpoolCustomArea: null,
          nordpoolCustomEntity: null,
          nordpoolConfigEntryId: 'entry1',
          octopusFound: false,
          entsoeFound: false,
          entsoeEntity: null,
          // Only current_l1 and current_l2 discovered -- current_l3 is
          // missing, so this is a partial (2-of-3) phase discovery.
          sensors: { current_l1: 'sensor.current_l1', current_l2: 'sensor.current_l2' },
          platformSensors: { growatt_server_min: growattRequiredSensors },
          missingSensors: [],
          detectedInverterPlatforms: ['growatt_server_min'],
          detectedPhaseCount: 2,
          currency: 'SEK',
          vatMultiplier: 1.25,
        }),
      });
    });

    await page.goto('/setup');
    await expectActiveStep(page, 1);

    // Navigate to the Home step (step 4)
    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();
    await expectActiveStep(page, 2);
    await page.getByRole('button', { name: /Next: Battery/i }).click();
    await expectActiveStep(page, 3);
    await page.getByRole('button', { name: /Next: Home/i }).click();
    await expectActiveStep(page, 4);

    // Must NOT have been auto-enabled -- current_l3 is missing, so the
    // required-sensor set for the default (3-phase) HomeSettings config
    // isn't fully mapped.
    const fuseToggle = page.getByRole('switch', { name: /Enable fuse protection/i });
    await expect(fuseToggle).not.toBeChecked();
    await expect(fuseToggle).toBeDisabled();

    // The Phase Count radio group is always rendered (it's used by the
    // day-ahead scheduler regardless of fuse protection), so confirm the
    // real invariant directly: phaseCount was never seeded with the invalid
    // raw discovery count of 2 -- it stayed at the default of 3-phase, and
    // the 1-phase option was not selected either.
    await expect(page.getByRole('radio', { name: '3-phase' })).toBeChecked();
    await expect(page.getByRole('radio', { name: '1-phase' })).not.toBeChecked();
  });

  // -------------------------------------------------------------------------
  // Issue #549: the wizard must refuse configuration it cannot make work
  // -------------------------------------------------------------------------

  test('blocks the sensor step when a required entity is disabled in HA', async ({ page }) => {
    test.skip(!expected.disabledEntities, 'scenario has no disabled entities');

    await page.goto('/setup');
    await expectActiveStep(page, 1);

    // The user is told which entities to switch on — not that they are
    // "missing", which is what the old runtime 404 claimed.
    const warning = page.getByTestId('disabled-entities-warning');
    await expect(warning).toBeVisible();
    for (const entityId of expected.disabledEntities!) {
      await expect(warning).toContainText(entityId);
    }

    // And setup cannot proceed with a mapping that would 404 at runtime.
    await expect(
      page.getByRole('button', { name: /Next: Electricity Pricing/i }),
    ).toBeDisabled();
  });

  test('blocks the pricing step when the selected provider is unconfigured', async ({ page }) => {
    test.skip(!expected.pricingBlocked, 'scenario has a usable price provider');

    await page.goto('/setup');
    await expectActiveStep(page, 1);
    await page.getByRole('button', { name: /Next: Electricity Pricing/i }).click();
    await expectActiveStep(page, 2);

    // No Nord Pool integration exists, so the defaulted provider has an
    // empty config entry — completing here would persist a config that can
    // never fetch a price and abort every optimizer cycle.
    await expect(page.getByTestId('pricing-incomplete-warning')).toBeVisible();
    await expect(page.getByRole('button', { name: /Next: Battery/i })).toBeDisabled();

    // Supplying the missing field releases the gate.
    await fieldByLabel(page, /Config Entry ID/).fill('entry-nordpool-manual');
    await expect(page.getByTestId('pricing-incomplete-warning')).toBeHidden();
    await expect(page.getByRole('button', { name: /Next: Battery/i })).toBeEnabled();
  });
});

// ---------------------------------------------------------------------------
// Undetected inverter platform (#621)
// ---------------------------------------------------------------------------

/**
 * A user whose inverter integration is not one BESS recognises — the
 * reporter runs Huawei LUNA2000/EMMA through `huawei_emma_management`, so
 * `_INVERTER_PLATFORMS` (which matches only `huawei_solar`) detects nothing.
 *
 * Discovery failing must narrow the wizard's *defaults*, not its *choices*:
 * a user who knows their platform has to be able to pick it and configure
 * the sensors by hand. These tests stub a discovery in which nothing at all
 * was recognised, which is exactly that user's state.
 */
test.describe('Setup Wizard — undetected inverter platform', () => {
  const NOTHING_DETECTED = {
    growattFound: false,
    growattDeviceId: null,
    huaweiFound: false,
    huaweiDeviceId: null,
    solaxFound: false,
    solaxHasGrowattTou: false,
    solaxHasGrowattGen3: false,
    solisFound: false,
    nordpoolFound: true,
    nordpoolArea: 'SE3',
    nordpoolCustomArea: null,
    nordpoolCustomEntity: null,
    nordpoolConfigEntryId: 'entry1',
    octopusFound: false,
    entsoeFound: false,
    entsoeEntity: null,
    sensors: {},
    platformSensors: {},
    missingSensors: [],
    detectedInverterPlatforms: [],
    detectedPhaseCount: null,
    currency: 'SEK',
    vatMultiplier: 1.25,
  };

  test.beforeEach(async ({ page }) => {
    await page.route('**/api/setup/discover', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(NOTHING_DETECTED),
      });
    });
  });

  /** Fill every sensor input the wizard reports as undetected. */
  async function fillAllUndetectedSensors(page: Page) {
    const missing = page.locator('input[placeholder="Not detected — enter entity ID"]');
    // The placeholder clears as each field is filled, so the set shrinks and
    // the loop terminates. The cap only guards against a non-shrinking set.
    for (let i = 0; i < 200 && (await missing.count()) > 0; i++) {
      await missing.first().fill(`sensor.manual_entity_${i}`);
    }
    await expect(missing).toHaveCount(0);
  }

  test('every platform tab stays selectable when nothing is detected', async ({ page }) => {
    await page.goto('/setup');
    await expectActiveStep(page, 1);

    // Detection failed for all four, so under the old gate every tab was
    // disabled and the wizard had no reachable platform at all.
    for (const name of [/Growatt Cloud/i, /SolaX Modbus/i, /Solis Modbus/i, /Huawei/i]) {
      await expect(page.getByRole('tab', { name })).toBeEnabled();
    }

    // And the choice actually takes: selecting Huawei reveals its panel.
    await page.getByRole('tab', { name: /Huawei/i }).click();
    await expect(page.getByText('LUNA2000')).toBeVisible();
    await expect(page.getByPlaceholder('Huawei battery device ID')).toBeVisible();
  });

  test('a manually selected platform survives a re-scan', async ({ page }) => {
    await page.goto('/setup');
    await expectActiveStep(page, 1);

    await page.getByRole('tab', { name: /Huawei/i }).click();
    await expect(page.getByPlaceholder('Huawei battery device ID')).toBeVisible();

    // Re-scan is the button this user reaches for after a failed detection.
    // It must not silently revert the platform they just chose: the required
    // -sensor list follows the selected tab while the filled-in check reads
    // the sensor dict named by `sensors.platform`, so if those two diverge
    // the step can never be completed no matter what is typed.
    await page.getByRole('button', { name: /Re-scan/i }).click();
    await expect(page.getByPlaceholder('Huawei battery device ID')).toBeVisible();

    await fillAllUndetectedSensors(page);

    // Huawei LUNA2000 gates step completion on a battery Device ID — it
    // targets huawei_solar.set_tou_periods, so setup can't finish without one.
    await page.getByPlaceholder('Huawei battery device ID').fill('1');

    await expect(
      page.getByRole('button', { name: /Next: Electricity Pricing/i }),
    ).toBeEnabled();
  });

  // #730: Huawei (EMMA) and Solis both expose a native lifetime
  // load-consumption entity, but the wizard's platform definitions offered no
  // field to map it — so their users could never enable the HA Statistics
  // consumption strategy, which needs a Recorder-tracked lifetime-consumption
  // sensor. The Lifetime Energy group must now render the field for both.
  test('Huawei Lifetime Energy group includes a load-consumption field', async ({
    page,
  }) => {
    await page.goto('/setup');
    await expectActiveStep(page, 1);

    await page.getByRole('tab', { name: /Huawei/i }).click();
    await expect(page.getByText('Lifetime Energy')).toBeVisible();
    await expect(
      page.getByText('Total Energy Consumption (EMMA)'),
    ).toBeVisible();
  });

  test('Solis Lifetime Energy group includes a load-consumption field', async ({
    page,
  }) => {
    await page.goto('/setup');
    await expectActiveStep(page, 1);

    await page.getByRole('tab', { name: /Solis Modbus/i }).click();
    await expect(page.getByText('Lifetime Energy')).toBeVisible();
    await expect(
      page.getByText('Total Energy Consumption', { exact: true }),
    ).toBeVisible();
  });
});
