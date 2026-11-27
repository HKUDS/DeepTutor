import { test, expect } from '@playwright/test'
import { sourceModuleInventory } from './e2e/fixtures/modules'

test('source picker wheel scrolls its parent wizard', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('deeptutor-language', 'en'))
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/modules') return route.fulfill({ json: sourceModuleInventory })
    if (path === '/api/auth/status') {
      return route.fulfill({ json: { enabled: false, authenticated: true, role: 'admin', is_admin: true } })
    }
    if (path === '/api/settings/ui') return route.fulfill({ json: { language: 'en' } })
    if (path.startsWith('/api/dashboard/source-library/')) {
      return route.fulfill({ json: {
        items: path.endsWith('/knowledge') ? Array.from({ length: 50 }, (_, index) => ({
          id: `kb-${index}`, name: `Library ${index}`, available: true,
        })) : [],
        unavailable_workspaces: [],
      } })
    }
    if (path.startsWith('/api/dashboard/learning-library/')) {
      return route.fulfill({ json: { items: [], unavailable_workspaces: [], can_create: true } })
    }
    if (path === '/api/partners' || path === '/api/partner-groups') {
      return route.fulfill({ json: [] })
    }
    return route.fulfill({ status: 404, json: { detail: 'Unused audit endpoint' } })
  })
  await page.goto('/learning/mastery?create=1')
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('textbox').fill('Learn linear algebra')
  await dialog.getByRole('button', { name: 'Choose sources', exact: true }).click()
  const row = dialog.getByRole('button', { name: /Library 0/ }).first()
  await row.hover()
  const wizardScroller = dialog.locator(':scope > div.overflow-y-auto')
  await expect(wizardScroller).toHaveCount(1)
  await page.mouse.wheel(0, 400)
  await expect.poll(() => wizardScroller.evaluate(element => element.scrollTop)).toBeGreaterThan(0)
})
