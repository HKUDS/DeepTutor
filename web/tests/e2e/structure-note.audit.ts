import { expect, test } from '@playwright/test'

const BASE_URL =
  process.env.WEB_BASE_URL || process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:3000'

test.describe('Structure Note :: Accessibility & UX', () => {
  test('page exposes heading, labeled controls, and result regions', async ({ page }) => {
    await page.route('**/api/v1/structure-note/jobs', route =>
      route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ jobs: [] }),
      })
    )

    await page.goto(`${BASE_URL}/structure-note`)

    await expect(page.locator('main')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Structure Note' })).toBeVisible()
    await expect(page.getByLabel('Course File')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Generate Structure Note' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Result' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Citations' })).toBeVisible()
  })
})
