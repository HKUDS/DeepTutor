import { expect, test } from '@playwright/test'

test.describe('Settings navigation', () => {
  test('reports what is ready without dressing optional gaps as faults', async ({
    page,
  }) => {
    await page.route('**/api/settings/readiness', route =>
      route.fulfill({
        status: 200,
        json: {
          schema_version: 'deeptutor.settings-readiness/v2',
          ok: false,
          summary: {
            enabled_verified: 1,
            available_disabled: 0,
            unavailable: 1,
            misconfigured: 1,
            not_selected: 0,
          },
          rows: [
            {
              id: 'catalog.llm',
              section: 'catalog',
              label: 'Chat model',
              state: 'enabled_verified',
              detail_code: 'configuration_verified',
              enabled: true,
              available: true,
              configured: true,
              verified: true,
              required: true,
            },
            {
              id: 'parser.tika',
              section: 'document_parsing',
              label: 'Tika',
              state: 'misconfigured',
              detail_code: 'selected_parser_unreachable',
              enabled: true,
              available: true,
              configured: true,
              verified: false,
              required: true,
            },
            {
              // Optional and never set up: folded away, never flagged.
              id: 'tool.videogen',
              section: 'tools',
              label: 'Video generation tool',
              state: 'unavailable',
              detail_code: 'tool_backend_not_configured',
              enabled: true,
              available: false,
              configured: false,
              verified: false,
              required: false,
            },
          ],
          notices: [
            {
              code: 'selected_parser_unreachable',
              row_id: 'parser.tika',
              section: 'document_parsing',
              severity: 'blocker',
            },
          ],
        },
      })
    )

    await page.goto('/settings')

    const panel = page.locator(
      'section[aria-labelledby="capability-readiness-title"]'
    )
    await expect(panel).toBeVisible()
    const matrix = page.getByTestId('settings-readiness-matrix')
    await expect(matrix).toBeVisible()

    // The selected parser that cannot be reached is the one thing called out.
    await expect(
      panel.getByText(/endpoint is unreachable|服务地址连不上/)
    ).toBeVisible()
    // The optional tool is folded behind its disclosure, not in the open list.
    await expect(
      matrix.getByText(/Video generation tool|视频生成工具/, { exact: true })
    ).toBeHidden()
    await expect(matrix.getByText(/not in use|未启用/)).toBeVisible()
  })

  test('keeps scrolling inside the settings pane', async ({ page }) => {
    await page.goto('/settings')

    const settingsScroll = page.locator('[data-settings-scroll]')
    await expect(settingsScroll).toBeVisible()
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0)

    const aboutLink = page.locator('a[data-tour="tour-nav-about"]')
    await aboutLink.click()
    await expect(page).toHaveURL(/\/settings#about$/)
    await expect
      .poll(() => settingsScroll.evaluate(element => element.scrollTop))
      .toBeGreaterThan(0)

    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0)
  })

  test('keeps deep-link scrolling inside the settings pane', async ({ page }) => {
    await page.goto('/settings#about')

    const settingsScroll = page.locator('[data-settings-scroll]')
    await expect(settingsScroll).toBeVisible()
    await expect(page).toHaveURL(/\/settings#about$/)
    await expect
      .poll(() => settingsScroll.evaluate(element => element.scrollTop))
      .toBeGreaterThan(0)

    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0)
  })
})
