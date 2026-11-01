import { expect, test, type Page } from '@playwright/test'
import { sourceModuleInventory } from './fixtures/modules'

const SESSION = 'tray-overlap'

async function openConversation(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('deeptutor.ui-layout', 'modern')
    localStorage.setItem('deeptutor-language', 'en')
    localStorage.setItem('deeptutor-theme', 'light')
  })
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    const json = (payload: unknown) => route.fulfill({ json: payload })
    if (path === '/api/modules') return json(sourceModuleInventory)
    if (path === '/api/auth/status') return json({ enabled: false, authenticated: true })
    if (path === `/api/sessions/${SESSION}`)
      return json({
        id: SESSION,
        session_id: SESSION,
        title: 'Tray layout',
        status: 'idle',
        created_at: 1,
        updated_at: 2,
        preferences: { capability: 'chat', language: 'en' },
        active_turns: [],
        leaf_message_id: 1,
        selected_leaf_message_id: 1,
        messages: [
          {
            id: 1,
            session_id: SESSION,
            role: 'user',
            content: 'Hello',
            capability: 'chat',
            events: [],
            attachments: [],
            metadata: {},
            created_at: 1,
            parent_message_id: null,
          },
        ],
      })
    if (path === '/api/sessions') return json({ sessions: [] })
    if (path === '/api/settings/workspace/resources')
      return json({
        skills: Array.from({ length: 12 }, (_, i) => ({
          id: `skill-${i}`,
          name: `Study skill ${i}`,
          description: 'Study aid',
        })),
        mcp: [],
        knowledge_bases: [],
      })
    if (path === '/api/settings/workspace/registrations') return json({ workspaces: [] })
    if (path === '/api/settings/page-customization')
      return json({
        chat: {
          hidden_modes: [],
          controls: {
            skills: true,
            mcp: true,
            partners: true,
            preferences: true,
            voice: true,
          },
          starters: {},
        },
        learning: { hidden_features: [] },
      })
    if (path === '/api/settings' || path === '/api/settings/ui')
      return json({
        ui: { theme: 'light', language: 'en', response_language: 'en' },
        providers: { llm: [] },
        catalog: { version: 1, connections: [], services: {} },
      })
    if (path === '/api/settings/llm-options') return json({ options: [], active: null })
    if (path.includes('partners') || path.includes('personas')) return json([])
    if (path.includes('tools')) return json({ tools: [] })
    if (path === '/api/capabilities/registered')
      return json({
        capabilities: [
          'chat',
          'deep_solve',
          'ask_questions',
          'deep_question',
          'deep_research',
          'visualize',
          'video_lesson',
        ],
      })
    if (path.includes('knowledge')) return json({ knowledge_bases: [] })
    if (path.includes('folders')) return json({ folders: [] })
    if (path.includes('tags')) return json({ tags: [] })
    if (path.includes('activities')) return json({ activities: [] })
    if (path.includes('settings')) return json({})
    return route.fulfill({ status: 404, json: {} })
  })
  await page.goto(`/chat/${SESSION}`, { waitUntil: 'domcontentloaded' })
}

test('upward tray menus keep their final option reachable above the composer', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await openConversation(page)
  // Older container-query implementations impose layout containment, which
  // creates a stacking context. Exercise it on current CI browsers too.
  await page.locator('.dt-composer-tray').evaluate(tray => {
    ;(tray as HTMLElement).style.contain = 'layout'
  })
  const trigger = page.locator('.dt-tray-button').filter({ hasText: 'Mode' })
  await trigger.click()
  const panel = page.getByRole('dialog', { name: 'Mode', exact: true })
  await expect(panel.getByRole('option')).toHaveCount(6)
  const last = panel.getByRole('option').last()
  await last.scrollIntoViewIfNeeded()
  // A visible box alone does not prove it is above the composer: hit testing does.
  await expect(last).toBeInViewport()
  await last.click({ trial: true, timeout: 3000 })
  await page.screenshot({ path: test.info().outputPath('tray-mode.png') })
})
