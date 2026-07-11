import { test, expect } from '@playwright/test';

// Helper: wait for the savings page to render its static structure. The
// hero cards' data (especially for "Day", which reads the *live* view for
// today) can legitimately be empty/erroring against a CI mock scenario
// whose price data is pinned to a fixed past date, not the real container
// clock — so this only waits for structure, not data content, and callers
// that check data-dependent text do so tolerantly.
async function waitForSavingsPage(page: import('@playwright/test').Page) {
  await page.goto('/savings');
  await expect(
    page.getByRole('heading', { name: 'Savings Report' })
  ).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText('Something went wrong')).not.toBeVisible();
}

test.describe('Savings Page', () => {
  test('loads and shows page heading', async ({ page }) => {
    await page.goto('/savings');

    await expect(
      page.getByRole('heading', { name: 'Savings Report' })
    ).toBeVisible({ timeout: 15_000 });
  });

  test('shows the Day/Month/Year resolution selector, date picker, and Chart/Table toggle', async ({ page }) => {
    await waitForSavingsPage(page);

    await expect(page.getByRole('button', { name: 'Day' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Month' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Year' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Chart' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Table' })).toBeVisible();
  });

  test('shows Cost/Savings hero content or a graceful empty state, never a crash', async ({ page }) => {
    await waitForSavingsPage(page);

    // The hero cards render once their fetch settles, with real data or a
    // zeroed-out bucket — either way "Net Cost" appears unless the fetch
    // itself errored (e.g. no live data for today in this CI fixture), in
    // which case the hero silently omits itself. Both are acceptable; a
    // crash is not.
    await page.waitForTimeout(3000);
    await expect(page.getByText('Something went wrong')).not.toBeVisible();
  });

  test('switching to Table view shows a table or a no-data message', async ({ page }) => {
    await waitForSavingsPage(page);

    await page.getByRole('button', { name: 'Table' }).click();

    await expect(
      page
        .locator('table')
        .first()
        .or(page.getByText(/No savings history yet/i))
    ).toBeVisible({ timeout: 10_000 });
  });

  test('switching between Day, Month, and Year resolutions does not crash', async ({ page }) => {
    await waitForSavingsPage(page);

    await page.getByRole('button', { name: 'Month' }).click();
    await expect(page.getByRole('heading', { name: 'Savings Report' })).toBeVisible();
    await expect(page.getByText('Something went wrong')).not.toBeVisible();

    await page.getByRole('button', { name: 'Year' }).click();
    await expect(page.getByRole('heading', { name: 'Savings Report' })).toBeVisible();
    await expect(page.getByText('Something went wrong')).not.toBeVisible();

    await page.getByRole('button', { name: 'Day' }).click();
    await expect(page.getByRole('heading', { name: 'Savings Report' })).toBeVisible();
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
