import { sourceModuleInventory } from './fixtures/modules'
import { expect, test, type Page } from '@playwright/test'

const SESSION_ID = 'chat-header-overlap'
const THAI_TITLE = 'ทดสอบการแสดงผลภาษาไทย'
const ENGLISH_TITLE = 'A Long English Chat Title That Must Stay Readable'
const EVIDENCE_PHASE = process.env.CHAT_HEADER_EVIDENCE_PHASE ?? 'run'

function session(title: string) {
  return {
    id: SESSION_ID,
    session_id: SESSION_ID,
    title,
    created_at: 1,
    updated_at: 2,
    status: 'idle',
    preferences: { capability: 'chat', language: 'en' },
    active_turns: [],
    messages: [
      {
        id: 1,
        session_id: SESSION_ID,
        role: 'user',
        content: 'A mocked conversation for the header layout audit.',
        capability: 'chat',
        events: [],
        attachments: [],
        metadata: {},
        created_at: 1,
        parent_message_id: null,
      },
    ],
    leaf_message_id: 1,
    selected_leaf_message_id: 1,
  }
}

async function mockChat(page: Page, title: string) {
  const writes: { path: string; method: string; body: unknown }[] = []
  await page.addInitScript(() => {
    localStorage.setItem('deeptutor-theme', 'light')
    localStorage.setItem('deeptutor-language', 'en')
    localStorage.setItem(
      'deeptutor.ui-layout',
      sessionStorage.getItem('chat-header-audit-layout') ?? 'modern'
    )
  })
  await page.route('**/api/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()
    const body = method === 'GET' ? undefined : request.postDataJSON()
    if (method !== 'GET') writes.push({ path, method, body })
    const json = (payload: unknown) => route.fulfill({ status: 200, json: payload })

    if (path === '/api/modules') return json(sourceModuleInventory)
    if (path === '/api/auth/status')
      return json({ enabled: false, authenticated: true, is_admin: true })
    if (path === '/api/settings/page-customization') {
      return json({
        chat: {
          hidden_modes: [],
          controls: { skills: true, mcp: true, partners: true, preferences: true, voice: true },
          starters: {},
        },
        learning: { hidden_features: [] },
      })
    }
    if (path === '/api/settings/ui' || path === '/api/settings') {
      return json({
        ui: { theme: 'light', language: 'en', response_language: 'en' },
        providers: { llm: [] },
        catalog: { version: 1, connections: [], services: {} },
      })
    }
    if (path === `/api/sessions/${SESSION_ID}`) {
      if (method === 'PATCH')
        return json({
          session: {
            ...session(title),
            title: (body as { title?: string } | undefined)?.title ?? title,
          },
        })
      return json(session(title))
    }
    if (path === '/api/sessions')
      return json({ sessions: [{ ...session(title), messages: undefined, message_count: 1 }] })
    if (path === '/api/settings/llm-options') return json({ options: [], active: null })
    if (path === '/api/system/status') return json({ backend: { status: 'online' } })
    if (path === '/api/task-board')
      return json({
        cards: [],
        session_links: [],
        colors: { todo: '#2563eb', doing: '#a16207', done: '#15803d' },
        revision: 0,
      })
    if (path === '/api/workspaces' || path.includes('workspaces'))
      return json({ workspaces: [], active_workspace_id: '' })
    if (path.includes('organization'))
      return json({ workspace_id: '', folder_id: null, tags: [], pinned: false })
    if (path.includes('capabilities')) return json({ capabilities: [] })
    if (path.includes('tools')) return json({ tools: [] })
    if (path.includes('knowledge')) return json({ knowledge_bases: [] })
    if (path.includes('folders')) return json({ folders: [] })
    if (path.includes('tags')) return json({ tags: [] })
    if (path.includes('partners') || path.includes('partner-groups')) return json([])
    if (path.includes('activities')) return json({ activities: [] })
    if (path.includes('learning-index')) return json({ sources: {}, failed: [] })
    if (path.includes('health')) return json({ status: 'ok' })
    if (path.includes('settings')) return json({})
    return route.fulfill({ status: 404, json: {} })
  })
  return writes
}

async function titleAndActions(page: Page) {
  const title = page.locator('.dt-chat-title, .dt-page-bar-instance .dt-crumb.is-instance')
  const customize = page.getByRole('button', { name: 'Customize page', exact: true })
  await expect(title).toBeVisible()
  await expect(customize).toBeVisible()
  return { title, customize }
}

async function expectTitleBeforeActions(page: Page) {
  const { title, customize } = await titleAndActions(page)
  const titleBox = await title.boundingBox()
  const actionsBox = await customize.boundingBox()
  expect(titleBox, 'title button must have a rendered box').not.toBeNull()
  expect(actionsBox, 'customize action must have a rendered box').not.toBeNull()
  expect(
    titleBox!.x + titleBox!.width,
    'chat title overlaps the customize action'
  ).toBeLessThanOrEqual(actionsBox!.x + 1)
}

test.describe('chat title header overlap', () => {
  for (const title of [THAI_TITLE, ENGLISH_TITLE]) {
    test(`keeps ${title === THAI_TITLE ? 'Thai' : 'English'} title clear of actions at 320px`, async ({
      page,
    }) => {
      await mockChat(page, title)
      await page.setViewportSize({ width: 320, height: 800 })
      await page.goto(`/chat/${SESSION_ID}`, { waitUntil: 'domcontentloaded' })
      await titleAndActions(page)
      await page.screenshot({
        path: test
          .info()
          .outputPath(`${EVIDENCE_PHASE}-${title === THAI_TITLE ? 'thai' : 'english'}-320.png`),
        fullPage: true,
      })
      await expectTitleBeforeActions(page)
    })
  }

  test('keeps the title bounded at mobile widths and in the Classic layout', async ({ page }) => {
    const writes = await mockChat(page, THAI_TITLE)
    await page.setViewportSize({ width: 320, height: 800 })
    await page.goto(`/chat/${SESSION_ID}`, { waitUntil: 'domcontentloaded' })
    for (const width of [320, 360, 390, 1440]) {
      await page.setViewportSize({ width, height: 800 })
      await expectTitleBeforeActions(page)
      await page.screenshot({
        path: test.info().outputPath(`${EVIDENCE_PHASE}-modern-${width}.png`),
        fullPage: true,
      })
    }
    await page.evaluate(() => {
      sessionStorage.setItem('chat-header-audit-layout', 'classic')
      localStorage.setItem('deeptutor.ui-layout', 'classic')
      document.documentElement.setAttribute('data-ui-layout', 'classic')
    })
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.setViewportSize({ width: 320, height: 800 })
    await expectTitleBeforeActions(page)
    await page.screenshot({
      path: test.info().outputPath(`${EVIDENCE_PHASE}-classic-320.png`),
      fullPage: true,
    })

    const titleButton = page.locator('.dt-chat-title')
    await titleButton.focus()
    await page.keyboard.press('Enter')
    const input = page.getByRole('textbox', { name: 'Session title' })
    await expect(input).toBeFocused()
    await input.fill('Renamed by keyboard')
    await input.press('Escape')
    await expect(page.locator('.dt-chat-title')).toContainText(THAI_TITLE)
    await page.locator('.dt-chat-title').focus()
    await page.keyboard.press('Enter')
    await page.getByRole('textbox', { name: 'Session title' }).fill('Keyboard title')
    await page.getByRole('textbox', { name: 'Session title' }).press('Enter')
    await expect
      .poll(() => page.evaluate(() => document.querySelector('.dt-chat-title')?.textContent))
      .toContain('Keyboard title')
    await expect
      .poll(() =>
        writes.some(
          write =>
            write.path === `/api/sessions/${SESSION_ID}` &&
            write.method === 'PATCH' &&
            (write.body as { title?: string }).title === 'Keyboard title'
        )
      )
      .toBe(true)

    await page.getByRole('button', { name: 'Customize page', exact: true }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('button', { name: 'Note', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Activity', exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Activity', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Activity', exact: true })).toHaveAttribute(
      'aria-pressed',
      'true'
    )
    await page
      .getByRole('main')
      .getByRole('button', { name: 'Conversation actions', exact: true })
      .click()
    await expect(page.getByRole('menu')).toBeVisible()
    await page.getByRole('menuitem', { name: 'Rename chat', exact: true }).click()
    await expect(page.getByRole('textbox', { name: 'Session title' })).toBeFocused()
    await page.keyboard.press('Escape')
  })
})
