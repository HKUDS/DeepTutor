import { expect, test } from '@playwright/test'

const WORKSPACE_ID = 'entity-graph-workspace'

const material = {
  material_id: 'graph-material',
  filename: 'Relationship Sample.txt',
  unit: 'section',
  unit_count: 2,
  mime: 'text/plain',
  title: 'Relationship Sample',
  byte_size: 256,
  char_count: 128,
  created_at: 1,
  has_raw_view: false,
  render_mode: 'text',
  annotation_count: 0,
  outline: [],
  outline_text: '',
  unit_refs: [],
}

const libraryMaterial = {
  material_id: material.material_id,
  content_id: material.material_id,
  filename: material.filename,
  title: material.title,
  source_kind: 'file',
  source_url: '',
  mime: material.mime,
  render_mode: material.render_mode,
  cover_url: '',
  duration_seconds: 0,
  status: 'ready',
  progress: 0,
  error_code: '',
  error_detail: '',
  created_at: 1,
  updated_at: 2,
  last_opened_at: 2,
  size_bytes: material.byte_size,
  unit_count: material.unit_count,
  collections: [],
}

const workspace = {
  workspace_id: WORKSPACE_ID,
  title: 'Entity graph regression',
  description: '',
  active_material_id: material.material_id,
  created_at: 1,
  updated_at: 2,
  tabs: [
    {
      material: libraryMaterial,
      tab_order: 0,
      pinned: false,
      opened: true,
      added_at: 1,
    },
  ],
}

function graphResponse(scope: 'current' | 'through_current') {
  const priorSection = scope === 'through_current' ? 1 : null
  return {
    graph: {
      nodes: [
        {
          id: 'entity_1',
          name: 'Ada',
          aliases: ['Countess Lovelace'],
          description: 'The analyst in this chapter.',
          confidence: 0.92,
        },
        {
          id: 'entity_2',
          name: 'Analytical Engine',
          aliases: [],
          description: 'The machine discussed by Ada.',
          confidence: 0.88,
        },
      ],
      edges: [
        {
          source: 'entity_1',
          target: 'entity_2',
          relation: 'describes',
          evidence: 'Ada describes the Analytical Engine.',
          evidence_locators: priorSection === null ? [2] : [1, 2],
          confidence: 0.9,
        },
      ],
    },
    mermaid: 'graph LR\n  entity_1["Ada"] -- "describes" --> entity_2',
    generated_at: 1,
    scope,
    locator: 2,
    included_locators: priorSection === null ? [2] : [1, 2],
    truncated: false,
  }
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    const json = (payload: unknown, status = 200) => route.fulfill({ status, json: payload })

    if (path === '/api/auth/status') {
      return json({
        enabled: false,
        authenticated: true,
        user_id: 'reader',
        username: 'reader',
        role: 'user',
        is_admin: false,
      })
    }
    if (path === '/api/settings/ui') return json({ language: 'en' })
    if (path === '/api/dashboard/suggestions') {
      return json({ suggestions: [], stale: false })
    }
    if (path === '/api/settings/llm-options') {
      return json({
        active: { profile_id: 'p', model_id: 'm' },
        options: [
          {
            profile_id: 'p',
            model_id: 'm',
            profile_name: 'Profile',
            model_name: 'Model',
            model: 'model',
            provider: 'provider',
            is_active_default: true,
          },
        ],
      })
    }
    if (path === `/api/reading/workspaces/${WORKSPACE_ID}`) {
      return json({ workspace, sessions: [] })
    }
    if (path === `/api/reading/workspaces/${WORKSPACE_ID}/sessions`) {
      return json({ sessions: [] })
    }
    if (path === '/api/reading/supported-formats') {
      return json({
        extensions: ['.txt'],
        max_bytes: 1024,
        raw_view_extensions: [],
      })
    }
    if (path === '/api/reading/extensions') return json([])
    if (path === '/api/reading/materials') return json([material])
    if (path === '/api/reading/materials/graph-material') {
      return json(material)
    }
    if (path === '/api/reading/materials/graph-material/annotations') {
      return json([])
    }
    if (path === '/api/reading/materials/graph-material/units/1') {
      return json({
        locator: 1,
        unit: 'section',
        text: 'Earlier, Charles Babbage introduces the machine.',
      })
    }
    if (path === '/api/reading/materials/graph-material/units/2') {
      return json({
        locator: 2,
        unit: 'section',
        text: 'Ada describes the Analytical Engine.',
      })
    }
    if (path === '/api/reading/materials/graph-material/character-graph') {
      const payload = route.request().postDataJSON() as {
        scope: 'current' | 'through_current'
      }
      return json(graphResponse(payload.scope))
    }
    return json({})
  })
})

test('the relationship graph overlays the chapter and preserves reading context', async ({
  page,
}) => {
  const pageErrors: string[] = []
  page.on('pageerror', error => pageErrors.push(error.message))

  await page.goto(`/reading/${WORKSPACE_ID}`)
  await expect(page.getByText('Charles Babbage introduces the machine.')).toBeVisible()
  await page.getByRole('button', { name: 'Next Section' }).click()
  await expect(
    page
      .locator('article.r6o-annotatable')
      .filter({ hasText: 'Ada describes the Analytical Engine.' })
  ).toBeVisible()

  await page.getByRole('button', { name: 'Relationship graph' }).click()
  const panel = page.getByRole('complementary').filter({ hasText: 'Relationship graph' })
  await expect(panel).toBeVisible()
  await expect(panel.getByText('Ada', { exact: true })).toBeVisible()
  await expect(panel.getByText('Analytical Engine', { exact: true })).toBeVisible()
  await expect(panel.getByText('Section 2', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Through current unit' })).toBeVisible()

  await page.getByRole('button', { name: 'Through current unit' }).click()
  await expect(panel.getByText('Section 1, Section 2').first()).toBeVisible()
  await expect(
    page
      .locator('article.r6o-annotatable')
      .filter({ hasText: 'Ada describes the Analytical Engine.' })
  ).toBeVisible()
  expect(pageErrors).toEqual([])
})
