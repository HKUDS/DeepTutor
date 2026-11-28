import { expect, test, type Page } from '@playwright/test'
import { emptyLearningIndex } from './fixtures/learning-index'
import { sourceModuleInventory } from './fixtures/modules'
import { emptyTaskBoard } from './fixtures/task-board'

const workspaceId = 'typography-workspace'
const materialId = 'typography-material'
const markdown = [
  '# Reader heading',
  'A paragraph with an inline formula $x^2$ and `inline code`.',
  '$$\nx^2+y^2=z^2\n$$',
  '| Symbol | Meaning |\n| --- | --- |\n| x | Input |',
  '> A quotation',
  '```text\nexample block\n```',
].join('\n\n')

async function openReader(page: Page, isMarkdown: boolean) {
  const material = {
    material_id: materialId,
    content_id: materialId,
    filename: isMarkdown ? 'sample.md' : 'sample.txt',
    title: 'Reader typography fixture',
    source_kind: 'file',
    source_type: 'upload',
    mime: isMarkdown ? 'text/markdown' : 'text/plain',
    render_mode: 'text',
    unit: 'section',
    unit_count: 1,
    content_format: isMarkdown ? 'web_markdown' : 'plain_text',
    status: 'ready',
    outline: [],
    unit_refs: [],
  }
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    const json = (payload: unknown) => route.fulfill({ json: payload })
    if (path === '/api/modules') return json(sourceModuleInventory)
    if (path === '/api/auth/status') return json({ enabled: false, authenticated: true })
    if (path === '/api/settings/ui') return json({ language: 'en' })
    if (path === '/api/dashboard/learning-index') return json(emptyLearningIndex)
    if (path === '/api/task-board') return json(emptyTaskBoard)
    if (path === '/api/settings/llm-options') {
      return json({
        active: { profile_id: 'test', model_id: 'test' },
        options: [
          {
            profile_id: 'test',
            model_id: 'test',
            model: 'test',
            is_active_default: true,
          },
        ],
      })
    }
    if (path === '/api/reading/materials') return json([material])
    if (path === `/api/reading/materials/${materialId}`) return json(material)
    if (path === `/api/reading/workspaces/${workspaceId}`) {
      return json({
        workspace: {
          workspace_id: workspaceId,
          title: 'Reader typography',
          active_material_id: materialId,
          tabs: [{ material, tab_order: 0, opened: true }],
        },
        sessions: [],
      })
    }
    if (path.endsWith('/units/1')) {
      return json({
        locator: 1,
        unit: 'section',
        text: isMarkdown ? markdown : 'Plain text control.',
      })
    }
    if (path.endsWith('/position')) return json({ locator: 1 })
    if (path.endsWith('/sessions')) return json({ sessions: [] })
    if (path.endsWith('/annotations') || path.endsWith('/media') || path.endsWith('/extensions'))
      return json([])
    return json({})
  })
  await page.setViewportSize({ width: 920, height: 900 })
  await page.goto(`/learning/reading/${workspaceId}`)
  return page.locator('.dt-reader-scroll article')
}

test('Markdown follows reader size, font and ink without tinting table rows with app colors', async ({
  page,
}) => {
  const article = await openReader(page, true)
  const prose = article.locator('.md-renderer')
  await expect(prose.locator('p').first()).toHaveCSS('font-size', '17px')
  const selectors = [
    'p',
    'h1',
    'td',
    '.md-inline-code',
    '.md-code-block__code',
    'p .katex',
    '.katex-display .katex',
  ]
  const sizes = () =>
    prose.evaluate(
      (element, entries) =>
        entries.map(selector => {
          const child = element.querySelector(selector)
          if (!child) throw new Error(`Missing fixture element: ${selector}`)
          return parseFloat(getComputedStyle(child).fontSize)
        }),
      selectors
    )
  const before = await sizes()
  for (let i = 0; i < 4; i++) await page.getByRole('button', { name: /Larger text/ }).click()
  await expect(prose.locator('p').first()).toHaveCSS('font-size', '21px')
  const after = await sizes()
  for (const [index, size] of after.entries())
    expect(size / before[index], selectors[index]).toBeCloseTo(21 / 17, 2)

  const beforeFamily = await prose.evaluate(node => getComputedStyle(node).fontFamily)
  await page.getByRole('button', { name: 'Use sans-serif font' }).click()
  const family = (node: Element) => getComputedStyle(node).fontFamily
  expect(await prose.evaluate(family)).not.toBe(beforeFamily)
  expect(await prose.evaluate(family)).toBe(await article.evaluate(family))

  for (const ink of ['rgb(71, 60, 44)', 'rgb(232, 229, 223)']) {
    await page.getByRole('button', { name: /Change reading theme/ }).click()
    await expect(prose.locator('p').first()).toHaveCSS('color', ink)
    await expect(prose.locator('td').first()).toHaveCSS('color', ink)
    await expect(prose.locator('tbody')).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)')
  }
})

test('plain text reader still resizes', async ({ page }) => {
  const article = await openReader(page, false)
  await expect(article).toContainText('Plain text control.')
  await expect(article).toHaveCSS('font-size', '17px')
  await page.getByRole('button', { name: /Larger text/ }).click()
  await expect(article).toHaveCSS('font-size', '18px')
})
