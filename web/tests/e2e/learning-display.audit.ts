import { expect, test, type Page } from '@playwright/test'
import { sourceModuleInventory } from './fixtures/modules'
import { emptyLearningIndex } from './fixtures/learning-index'
import { emptyTaskBoard } from './fixtures/task-board'

const SESSION = 'learning-display-fixture'
const QUESTION = 'Explain how a question becomes understanding. 学习从问题开始。'
const ANSWER = 'A learning answer stays readable at every size. 将新知识与已有知识联系起来。'
const HEADING_ONE =
  'A deliberately long lesson heading connecting familiar questions to deeper understanding'
const HEADING_TWO =
  'A deliberately long section heading explaining how those connections support learning'

const entry = {
  id: 8,
  question: QUESTION,
  options: { A: 'Connect ideas 联系想法', B: 'Memorize alone' },
  correct_answer: 'A',
  explanation:
    "### Why connections matter\n\nConnections make recall easier.\n\n```python\nprint('learning')\n```",
  question_type: 'single_choice',
  source: 'import',
  categories: [],
  user_answer: '',
  material_title: 'Disposable learning fixture',
  session_id: SESSION,
  session_title: 'Learning fixture',
  turn_id: '',
  question_id: 'q8',
  difficulty: '',
  material_id: '',
  section_id: '',
  section_title: '',
  score_trend: 'new',
  is_correct: false,
  resolved: false,
  bookmarked: false,
  followup_session_id: '',
  created_at: 1,
  updated_at: 1,
}

async function fixtures(page: Page) {
  let ui = {
    theme: 'system',
    language: 'en',
    response_language: 'en',
    content_font_scale: 100,
    content_line_spacing: 'normal',
  }
  let draft: any = null
  let failApply = false
  const writes: string[] = []
  // All API traffic, including every mutation, terminates in this disposable fixture.
  await page.route('**/api/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()
    const json = (value: unknown) => route.fulfill({ json: value })
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) writes.push(path)
    if (path === '/api/modules') return json(sourceModuleInventory)
    if (path === '/api/auth/status')
      return json({
        enabled: false,
        authenticated: true,
        role: 'admin',
        is_admin: true,
      })
    if (path === '/api/settings/ui') {
      if (method === 'PUT') {
        if (failApply) {
          failApply = false
          return route.fulfill({
            status: 503,
            json: { detail: 'Disposable Apply failure. Retry your changes.' },
          })
        }
        ui = { ...ui, ...request.postDataJSON() }
      }
      return json(ui)
    }
    if (path === '/api/settings/display')
      return json({
        content_font_scale: ui.content_font_scale,
        content_line_spacing: ui.content_line_spacing,
      })
    if (path === '/api/settings') return json({ ui })
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
    if (path === '/api/settings/draft') {
      if (method === 'PUT') draft = request.postDataJSON()
      if (method === 'DELETE') draft = null
      return json({ draft })
    }
    if (path === '/api/dashboard/learning-index') return json(emptyLearningIndex)
    if (path === '/api/task-board') return json(emptyTaskBoard)
    if (path === '/api/dashboard/suggestions') return json({ suggestions: [], stale: false })
    if (path === '/api/sessions') return json({ sessions: [] })
    if (path === `/api/sessions/${SESSION}`)
      return json({
        id: SESSION,
        session_id: SESSION,
        title: 'Learning display fixture',
        status: 'idle',
        created_at: 1,
        updated_at: 2,
        preferences: { capability: 'chat' },
        active_turns: [],
        messages: [
          {
            id: 1,
            session_id: SESSION,
            role: 'user',
            content: QUESTION,
            capability: 'chat',
            events: [],
            attachments: [],
            metadata: {},
            created_at: 1,
            parent_message_id: null,
          },
          {
            id: 2,
            session_id: SESSION,
            role: 'assistant',
            content: `# ${HEADING_ONE}\n\n## ${HEADING_TWO}\n\n${ANSWER}`,
            capability: 'chat',
            events: [],
            attachments: [],
            metadata: {},
            created_at: 2,
            parent_message_id: 1,
          },
        ],
      })
    if (path === '/api/reading/supported-formats')
      return json({
        extensions: ['.md'],
        max_bytes: 1024,
        raw_view_extensions: [],
      })
    if (path === '/api/reading/extensions') return json([])
    const material = {
      material_id: 'aaaaaaaaaaaaaaaa',
      filename: 'sample.md',
      unit: 'section',
      unit_count: 1,
      mime: 'text/markdown',
      title: 'Independent reader fixture',
      byte_size: 256,
      char_count: 128,
      created_at: 1,
      has_raw_view: false,
      render_mode: 'text',
      revision: 1,
      annotation_count: 0,
      outline: [],
      outline_text: '',
      unit_refs: [],
    }
    if (path === '/api/reading/materials') return json([material])
    if (path === '/api/reading/materials/aaaaaaaaaaaaaaaa') return json(material)
    if (path === '/api/reading/materials/aaaaaaaaaaaaaaaa/units/1')
      return json({
        locator: 1,
        unit: 'section',
        text: 'Reader sample stays separate.',
      })
    if (path.endsWith('/media') || path.endsWith('/annotations')) return json([])
    if (path === '/api/reading/workspaces/display-reader/sessions') return json({ sessions: [] })
    if (path === '/api/reading/workspaces/display-reader')
      return json({
        workspace: {
          workspace_id: 'display-reader',
          title: 'Reader fixture',
          description: '',
          active_material_id: material.material_id,
          created_at: 1,
          updated_at: 1,
          tabs: [
            {
              material: {
                ...material,
                content_id: material.material_id,
                source_kind: 'file',
                source_url: '',
                cover_url: '',
                duration_seconds: 0,
                status: 'ready',
                progress: 0,
                error_code: '',
                error_detail: '',
                updated_at: 1,
                last_opened_at: 1,
                size_bytes: 256,
                collections: [],
              },
              tab_order: 0,
              pinned: false,
              opened: true,
              added_at: 1,
            },
          ],
        },
        sessions: [],
      })
    if (path === '/api/settings/llm-options')
      return json({
        active: { profile_id: 'audit-profile', model_id: 'audit-model' },
        options: [
          {
            profile_id: 'audit-profile',
            model_id: 'audit-model',
            profile_name: 'Disposable audit profile',
            model_name: 'Disposable audit model',
            model: 'audit-model',
            provider: 'openai',
            is_active_default: true,
          },
        ],
      })
    if (path === '/api/question-notebook/practice/questions/8')
      return json({
        entry,
        state: { version: 1, review_count: 0, is_mistake: false, due_at: null },
      })
    if (path.endsWith('/questions/8/check')) return json({ correct: true })
    if (path.endsWith('/practice/summary'))
      return json({
        total: 1,
        mistakes: 0,
        due: 1,
        overdue: 0,
        reviewed_today: 0,
        next_due_at: null,
        day_end: 0,
        timezone: 'UTC',
      })
    if (path === '/api/question-notebook/entries') return json({ entries: [entry], total: 1 })
    if (path === '/api/question-notebook/stats') return json({ total: 1 })
    if (
      [
        '/api/partners',
        '/api/partner-groups',
        '/api/workspaces',
        '/api/question-notebook/categories',
        '/api/question-notebook/materials',
      ].includes(path)
    )
      return json([])
    if (path === '/api/settings/readiness') return json({ services: {} })
    if (path === '/api/system/status') return json({ backend: { status: 'online' } })
    return json({})
  })
  return {
    writes,
    failNextApply: () => {
      failApply = true
    },
  }
}

async function expectWrappedHeading(
  page: Page,
  level: 1 | 2,
  fontSize: number,
  lineHeight: number
) {
  const heading = page.getByRole('heading', {
    level,
    name: level === 1 ? HEADING_ONE : HEADING_TWO,
    exact: true,
  })
  await expect(heading).toBeVisible({ timeout: 60_000 })
  await expect(heading).toHaveCSS('font-size', `${fontSize}px`)
  const metrics = await heading.evaluate(el => {
    el.style.maxWidth = '220px'
    const range = document.createRange()
    range.selectNodeContents(el)
    const tops = Array.from(
      new Set(
        Array.from(range.getClientRects())
          .filter(rect => rect.width > 0)
          .map(rect => rect.top)
      )
    ).sort((a, b) => a - b)
    return { lineHeight: parseFloat(getComputedStyle(el).lineHeight), tops }
  })
  expect(metrics.lineHeight).toBeCloseTo(lineHeight, 3)
  expect(metrics.tops.length).toBeGreaterThanOrEqual(2)
  for (let i = 1; i < metrics.tops.length; i += 1) {
    expect(Math.abs(metrics.tops[i] - metrics.tops[i - 1] - lineHeight)).toBeLessThan(0.15)
  }
}

for (const [name, viewport] of [
  ['desktop', { width: 1440, height: 1000 }],
  ['tablet', { width: 820, height: 1180 }],
  ['mobile', { width: 375, height: 812 }],
] as const) {
  test(`${name}: learning text draft, Apply, real chat and practice remain usable`, async ({
    page,
  }, info) => {
    test.setTimeout(120_000)
    await page.setViewportSize(viewport)
    const fixture = await fixtures(page)
    await page.goto('/settings#appearance', { waitUntil: 'domcontentloaded' })
    const size = page.getByRole('combobox', { name: 'Learning text size' })
    await expect(size).toBeVisible({ timeout: 60_000 })
    const preview = page.getByTestId('learning-text-preview')
    await expect(preview).toHaveCSS('font-size', '16px')
    const chrome = await size.evaluate(el => getComputedStyle(el).fontSize)
    // Reset and Discard stay drafts and recover the server's live settings.
    await size.selectOption('125')
    await page.getByRole('button', { name: 'Reset learning text', exact: true }).click()
    await expect(size).toHaveValue('100')
    await size.selectOption('110')
    await page.getByRole('button', { name: 'Discard', exact: true }).click()
    await expect(size).toHaveValue('100')
    await size.selectOption('150')
    await page.getByRole('combobox', { name: 'Learning line spacing' }).selectOption('relaxed')
    await expect(preview).toHaveCSS('font-size', '24px')
    await expect(preview).toHaveCSS('line-height', '48px')
    expect(
      await page.locator('html').evaluate(el => el.style.getPropertyValue('--learning-font-scale'))
    ).toBe('1')
    expect(fixture.writes).not.toContain('/api/settings/ui')
    await page.getByRole('button', { name: 'Save draft', exact: true }).click()
    expect(fixture.writes).not.toContain('/api/settings/ui')
    await expect(size).toHaveCSS('font-size', chrome)
    await preview.scrollIntoViewIfNeeded()
    await page.screenshot({
      path: info.outputPath(`${name}-appearance.png`),
      fullPage: true,
    })
    fixture.failNextApply()
    await page.getByRole('button', { name: 'Apply changes', exact: true }).click()
    await expect(page.getByText(/Could not apply:.*Disposable Apply failure/)).toBeVisible()
    expect(
      await page.locator('html').evaluate(el => el.style.getPropertyValue('--learning-font-scale'))
    ).toBe('1')
    await expect(size).toHaveValue('150')
    await page.getByRole('button', { name: 'Apply changes', exact: true }).click()
    await expect
      .poll(() =>
        page.locator('html').evaluate(el => el.style.getPropertyValue('--learning-font-scale'))
      )
      .toBe('1.5')
    await page.goto(`/chat/${SESSION}`, { waitUntil: 'domcontentloaded' })
    const answer = page.locator('.learning-text').filter({ hasText: ANSWER })
    await expect(answer).toBeVisible({ timeout: 60_000 })
    await expect(answer).toHaveCSS('font-size', '24px')
    await expect(answer.locator('p')).toHaveCSS('line-height', '48px')
    await expectWrappedHeading(page, 1, 36, (32 * 1.5 * 2) / 1.75)
    await expectWrappedHeading(page, 2, 30, (28 * 1.5 * 2) / 1.75)
    const user = page.locator('[data-turn-bubble] .learning-text').filter({ hasText: QUESTION })
    await expect(user).toHaveCSS('font-size', '21px')
    await page.screenshot({
      path: info.outputPath(`${name}-chat.png`),
      fullPage: true,
    })
    await page.goto('/learning/practice?question=8', {
      waitUntil: 'domcontentloaded',
    })
    const question = page.locator('.learning-text').filter({ hasText: QUESTION })
    await expect(question).toBeVisible({ timeout: 60_000 })
    await expect(question).toHaveCSS('font-size', '24px')
    await page.getByRole('radio').first().check()
    await page.getByRole('button', { name: 'Check and reveal answer', exact: true }).click()
    const explanation = page
      .locator('.learning-text')
      .filter({ hasText: 'Connections make recall easier.' })
    await expect(explanation).toBeVisible()
    await expect(explanation).toHaveCSS('font-size', '24px')
    await expect(explanation.locator('h3')).toHaveCSS('font-size', '27px')
    await expect(explanation.locator('.md-code-block__code').first()).toHaveCSS('font-size', '14px')
    await page.screenshot({
      path: info.outputPath(`${name}-practice.png`),
      fullPage: true,
    })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      viewport.width + 1
    )
    await page.goto('/learning/reading/display-reader', {
      waitUntil: 'domcontentloaded',
    })
    const reader = page.getByRole('article').filter({ hasText: 'Reader sample stays separate.' })
    await expect(reader).toBeVisible({ timeout: 60_000 })
    await expect(reader).toHaveCSS('font-size', '17px')
    expect(await reader.locator('.learning-text').count()).toBe(0)
    if (name === 'desktop')
      await page.screenshot({
        path: info.outputPath('reader-exclusion.png'),
        fullPage: true,
      })

    // Standards mode matters: quirks-mode inline layout can hide the parent's
    // taller line strut. Exercise a real wrapped user message at 90% compact.
    await page.goto('/settings#appearance', { waitUntil: 'domcontentloaded' })
    await page.getByRole('combobox', { name: 'Learning text size' }).selectOption('90')
    await page.getByRole('combobox', { name: 'Learning line spacing' }).selectOption('compact')
    await page.getByRole('button', { name: 'Apply changes', exact: true }).click()
    await expect
      .poll(() =>
        page.locator('html').evaluate(el => el.style.getPropertyValue('--learning-font-scale'))
      )
      .toBe('0.9')
    await page.goto(`/chat/${SESSION}`, { waitUntil: 'domcontentloaded' })
    expect(await page.evaluate(() => document.compatMode)).toBe('CSS1Compat')
    const compactUser = page
      .locator('[data-turn-bubble] .learning-text')
      .filter({ hasText: QUESTION })
    await expect(compactUser).toBeVisible({ timeout: 60_000 })
    await expect(compactUser).toHaveCSS('font-size', '12.6px')
    await expect(compactUser).toHaveCSS('line-height', '18.9px')
    const wrapped = await compactUser.evaluate(el => {
      const parent = el.parentElement!
      parent.style.width = '140px'
      const text = el.firstChild!
      const asciiEnd = (text.textContent ?? '').search(/[^\u0020-\u007E]/)
      const range = document.createRange()
      range.setStart(text, 0)
      range.setEnd(text, asciiEnd < 0 ? (text.textContent ?? '').length : asciiEnd)
      const tops = Array.from(
        new Set(
          Array.from(range.getClientRects())
            .filter(rect => rect.width > 0)
            .map(rect => rect.top)
        )
      ).sort((a, b) => a - b)
      return {
        tops,
        parentLineHeight: getComputedStyle(parent).lineHeight,
        display: getComputedStyle(el).display,
      }
    })
    expect(wrapped.display).toBe('block')
    expect(wrapped.parentLineHeight).toBe('22.75px')
    expect(wrapped.tops.length).toBeGreaterThanOrEqual(2)
    for (let i = 1; i < wrapped.tops.length; i += 1) {
      expect(Math.abs(wrapped.tops[i] - wrapped.tops[i - 1] - 18.9)).toBeLessThan(0.15)
    }

    // Normal at 100% keeps the incumbent heading sizes and line pitch exactly.
    await page.goto('/settings#appearance', { waitUntil: 'domcontentloaded' })
    await page.getByRole('combobox', { name: 'Learning text size' }).selectOption('100')
    await page.getByRole('combobox', { name: 'Learning line spacing' }).selectOption('normal')
    await page.getByRole('button', { name: 'Apply changes', exact: true }).click()
    await expect
      .poll(() =>
        page.locator('html').evaluate(el => el.style.getPropertyValue('--learning-font-scale'))
      )
      .toBe('1')
    await page.goto(`/chat/${SESSION}`, { waitUntil: 'domcontentloaded' })
    expect(await page.evaluate(() => document.compatMode)).toBe('CSS1Compat')
    await expectWrappedHeading(page, 1, 24, 32)
    await expectWrappedHeading(page, 2, 20, 28)
  })
}
