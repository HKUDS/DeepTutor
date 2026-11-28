import { expect, test, type Page } from '@playwright/test'
import { sourceModuleInventory } from './fixtures/modules'
import { emptyTaskBoard } from './fixtures/task-board'

async function learningFixtures(page: Page) {
  const now = Math.floor(Date.now() / 1000)
  const topic = (path_id: string, name: string, created: number, updated: number) => ({
    path_id,
    name,
    content_workspace_id: 'physics',
    updated_at: now - updated,
    metadata: { status: 'active', goal: name, created_at: now - created },
    map: { counts: { total: 4, mastered: 1 } },
    reviews: [],
  })
  const watching = {
    session_id: 'video',
    title: 'Legacy video lesson',
    created_at: now - 900,
    updated_at: now - 80,
    message_count: 1,
    preferences: { capability: 'immersive_watching' },
  }
  const sessions = [
    {
      session_id: 'dot-products',
      title: 'Dot products',
      created_at: now - 800,
      updated_at: now - 10,
      message_count: 2,
      content_workspace_id: 'physics',
      preferences: { workspace_mode: 'mastery_path', mastery_path_id: 'vectors' },
    },
    {
      session_id: 'archived-path',
      title: 'Archived path conversation',
      created_at: now - 800,
      updated_at: now - 500,
      message_count: 2,
      content_workspace_id: 'physics',
      preferences: { workspace_mode: 'mastery_path', mastery_path_id: 'archived' },
    },
    watching,
  ]
  const sources = {
    mastery: [topic('vectors', 'Vectors', 1000, 100), topic('calculus', 'Calculus', 100, 200)],
    books: [
      {
        id: 'mechanics',
        title: 'Mechanics book',
        status: 'ready',
        created_at: now - 1000,
        updated_at: now - 60,
        reading: { percent: 20 },
      },
    ],
    reading: [
      {
        workspace_id: 'papers',
        title: 'Physics papers',
        created_at: now - 1000,
        updated_at: now - 70,
        tabs: [],
        active_material_id: null,
      },
    ],
    watching: [watching],
    practice: [1, 2].map(id => ({
      id,
      question: `Vector exercise ${id}`,
      session_id: 'practice-set',
      session_title: 'Vector practice',
      created_at: now - 1000,
      updated_at: now - 30 - id,
    })),
  }
  await page.addInitScript(() => {
    localStorage.setItem('deeptutor-theme', 'light')
    localStorage.setItem('deeptutor-language', 'en')
    localStorage.setItem('deeptutor.ui-layout', 'modern')
  })
  // Every API call terminates here; no personal learning data or live backend is used.
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    const json = (value: unknown) => route.fulfill({ json: value })
    if (path === '/api/modules') return json(sourceModuleInventory)
    if (path === '/api/auth/status')
      return json({ enabled: false, authenticated: true, role: 'admin', is_admin: true })
    if (path === '/api/settings/ui')
      return json({ theme: 'light', language: 'en', response_language: 'en' })
    if (path === '/api/settings')
      return json({ catalog: {}, ui: { theme: 'light', language: 'en', response_language: 'en' } })
    if (path === '/api/settings/page-customization')
      return json({
        chat: { hidden_modes: [], controls: {}, starters: {} },
        learning: { hidden_features: [] },
      })
    if (path === '/api/dashboard/learning-index') return json({ sources, failed: [] })
    if (path === '/api/task-board') return json(emptyTaskBoard)
    if (path === '/api/dashboard/suggestions') return json({ suggestions: [], stale: false })
    if (path === '/api/sessions') return json({ sessions })
    if (path === '/api/settings/llm-options') return json({ options: [], active: null })
    if (path === '/api/workspaces') return json({ workspaces: [], active_workspace_id: '' })
    if (path === '/api/settings/readiness') return json({ services: {} })
    if (path === '/api/system/status') return json({ backend: { status: 'online' } })
    if (path === '/api/partners' || path === '/api/partner-groups') return json([])
    return json({})
  })
  await page.routeWebSocket('**/ws/**', socket => socket.close())
}

for (const viewport of [
  { width: 1280, height: 900 },
  { width: 390, height: 844 },
]) {
  test(`learning record type filter at ${viewport.width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport)
    await learningFixtures(page)
    await page.goto('/learning', { waitUntil: 'domcontentloaded' })
    if (viewport.width < 768)
      await page.getByRole('button', { name: 'Open navigation', exact: true }).click()
    const filter = page.getByRole('combobox', { name: 'Filter by type', exact: true })
    const records = page
      .getByRole('complementary')
      .getByRole('region', { name: 'Your learning', exact: true })
    const recordLinks = records.locator('.dt-record-node-link')
    await expect(filter).toHaveValue('all')
    await expect(recordLinks).toHaveCount(6)
    await expect(records.getByText('Archived path conversation', { exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('all-types.png'), fullPage: true })

    await filter.selectOption('mastery')
    await expect(recordLinks).toHaveCount(2)
    await expect(recordLinks.first()).toContainText('Vectors')
    await expect(recordLinks.first()).toHaveAttribute('href', /dt_workspace=physics/)
    await expect(records.getByText('Archived path conversation', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Sort by', exact: true }).click()
    await page.getByRole('menuitemradio', { name: 'Created time', exact: true }).click()
    await expect(recordLinks.first()).toContainText('Calculus')
    await page.getByRole('button', { name: 'Sort by', exact: true }).click()
    await page.getByRole('menuitemradio', { name: 'Last active', exact: true }).click()
    await expect(recordLinks.first()).toContainText('Vectors')

    await records.getByRole('button', { name: 'Show 1 conversations', exact: true }).click()
    await expect(records.getByText('Dot products', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Search your learning', exact: true }).click()
    const search = page.getByRole('searchbox', { name: 'Search your learning', exact: true })
    await search.fill('Dot products')
    await expect(recordLinks).toHaveCount(1)
    await expect(records.getByText('Dot products', { exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('mastery-search.png'), fullPage: true })

    await filter.selectOption('reading')
    await expect(search).toHaveValue('Dot products')
    await expect(records.getByText('No matching records', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Clear search', exact: true }).click()
    await expect(filter).toHaveValue('reading')
    await expect(recordLinks).toHaveCount(2)
    await expect(records.getByText('Physics papers', { exact: true })).toBeVisible()
    await expect(records.getByText('Legacy video lesson', { exact: true })).toBeVisible()
    await expect(records.getByText('Archived path conversation', { exact: true })).toHaveCount(0)

    await filter.selectOption('practice')
    await expect(recordLinks).toHaveCount(1)
    await expect(recordLinks.first()).toContainText('Vector practice')
    await records.getByRole('button', { name: 'Show 2 questions', exact: true }).click()
    await expect(records.getByText('Vector exercise 1', { exact: true })).toBeVisible()
    await filter.selectOption('books')
    await expect(recordLinks).toHaveCount(1)
    await expect(recordLinks.first()).toContainText('Mechanics book')

    await filter.selectOption('all')
    await expect(recordLinks).toHaveCount(6)
    await expect(records.getByText('Dot products', { exact: true })).toBeVisible()
    await expect(records.getByText('Vector exercise 1', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Sort by', exact: true }).click()
    await expect(
      page.getByRole('menuitemradio', { name: 'Last active', exact: true })
    ).toHaveAttribute('aria-checked', 'true')
    await page.getByRole('button', { name: 'Sort by', exact: true }).click()
    const bounds = await filter.boundingBox()
    expect(bounds).not.toBeNull()
    expect(bounds!.x).toBeGreaterThanOrEqual(0)
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width)
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
    ).toBe(true)
  })
}
