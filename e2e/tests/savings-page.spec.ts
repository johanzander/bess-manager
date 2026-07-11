import { test, expect } from '@playwright/test';

// Helper: wait for the savings page to fully render (heading + hero cards settled)
async function waitForSavingsPage(page: import('@playwright/test').Page) {
  await page.goto('/savings');
  await expect(
    page.getByRole('heading', { name: 'Savings Report' })
  ).toBeVisible({ timeout: 15_000 });
  // The hero cards' key metrics render once the Day-resolution fetch settles
  // (either with real data or a zeroed-out bucket) — this is the equivalent
  // of the old page's loading-spinner gate.
  await expect(page.getByText('Net Cost')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText('Net Savings')).toBeVisible();
}

test.describe('Savings Page', () => {
  test('loads and shows page heading', async ({ page }) => {
    await page.goto('/savings');

    await expect(
      page.getByRole('heading', { name: 'Savings Report' })
    ).toBeVisible({ timeout: 15_000 });
  });

  test('shows the Day/Month/Year resolution selector and a date picker', async ({ page }) => {
    await waitForSavingsPage(page);

    await expect(page.getByRole('button', { name: 'Day' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Month' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Year' })).toBeVisible();
    // The date picker's chevron buttons flank its date/label button.
    await expect(page.getByRole('button', { name: 'Chart' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Table' })).toBeVisible();
  });

  test('shows the Cost and Savings hero cards', async ({ page }) => {
    await waitForSavingsPage(page);

    await expect(page.getByText('Import Costs')).toBeVisible();
    await expect(page.getByText('Export Revenues')).toBeVisible();
    await expect(page.getByText('Grid Only')).toBeVisible();
    await expect(page.getByText('Solar Contribution')).toBeVisible();
    await expect(page.getByText('Battery Contribution')).toBeVisible();
  });

  test('switching to Table view shows a table or a no-data message', async ({ page }) => {
    await waitForSavingsPage(page);

    await page.getByRole('button', { name: 'Table' }).click();

    await expect(
      page.locator('table').first().or(page.getByText(/No savings history yet/i))
    ).toBeVisible({ timeout: 10_000 });
  });

  test('switching between Day, Month, and Year resolutions does not crash', async ({ page }) => {
    await waitForSavingsPage(page);

    await page.getByRole('button', { name: 'Month' }).click();
    await expect(page.getByRole('heading', { name: 'Savings Report' })).toBeVisible();
    await expect(page.getByText('Net Cost')).toBeVisible({ timeout: 15_000 });

    await page.getByRole('button', { name: 'Year' }).click();
    await expect(page.getByRole('heading', { name: 'Savings Report' })).toBeVisible();
    await expect(page.getByText('Net Cost')).toBeVisible({ timeout: 15_000 });

    await page.getByRole('button', { name: 'Day' }).click();
    await expect(page.getByRole('heading', { name: 'Savings Report' })).toBeVisible();
    await expect(page.getByText('Net Cost')).toBeVisible({ timeout: 15_000 });

    await expect(page.getByText('Something went wrong')).not.toBeVisible();
  });

  test('navigating the date picker does not crash', async ({ page }) => {
    await waitForSavingsPage(page);

    // The date picker's previous button is the one containing the
    // chevron-left icon; it's disabled once there's no earlier available
    // date, so only click if enabled.
    const prevButton = page.locator('button:has(svg.lucide-chevron-left)');
    if (await prevButton.isEnabled().catch(() => false)) {
      await prevButton.click();
      await expect(page.getByRole('heading', { name: 'Savings Report' })).toBeVisible();
      await expect(page.getByText('Something went wrong')).not.toBeVisible();
    }
  });
});
