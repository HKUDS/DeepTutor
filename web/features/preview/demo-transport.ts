/** Browser-only fixtures for /preview. No request on this route reaches a backend.
 * Existing reader/editor/composer APIs remain unchanged. Local writes use their
 * own preview namespace; navigating away restores normal fetch behavior.
 */
import { browserStorage } from '@/shared/storage'
import { initialDocument, material, readingUnits } from './fixtures'
import { DEFAULT_TASK_COLORS, type TaskBoard } from '@/lib/task-board-api'
import type { AnnotationItem } from '@/lib/reading-api'

const PREFIX = 'deeptutor.dito-preview.v1.'
export function readDemo<T>(key: string, fallback: T): T {
  try {
    return JSON.parse(browserStorage.readRaw('local', PREFIX + key) || 'null') ?? fallback
  } catch {
    return fallback
  }
}
export function writeDemo(key: string, value: unknown) {
  try {
    browserStorage.writeRaw('local', PREFIX + key, JSON.stringify(value))
    window.dispatchEvent(new CustomEvent('dito-preview-data', { detail: key }))
  } catch {
    /* Memory-only preview if storage is unavailable. */
  }
}
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
let installed = false

export function installDemoTransport() {
  if (typeof window === 'undefined' || installed) return
  installed = true
  const realFetch = window.fetch.bind(window)
  window.fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : String(input), location.href)
    if (location.pathname !== '/preview' || !url.pathname.startsWith('/api/'))
      return realFetch(input, init)
    const path = url.pathname
    const method = init?.method || (input instanceof Request ? input.method : 'GET')
    const rawBody =
      init?.body ??
      (input instanceof Request && method !== 'GET' ? await input.clone().text() : undefined)
    const body = typeof rawBody === 'string' ? JSON.parse(rawBody || '{}') : {}
    if (path.startsWith('/api/task-board')) {
      const board = readDemo<TaskBoard>('task-board', {
        cards: [
          {
            id: 'task-1',
            title: '整理注意力机制的阅读笔记',
            note: '从 Query、Key、Value 三个角色开始。',
            status: 'doing',
            archived: false,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            workspace_id: null,
            due_date: null,
          },
          {
            id: 'task-2',
            title: '完成线性代数巩固练习',
            note: '',
            status: 'todo',
            archived: false,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            workspace_id: null,
            due_date: null,
          },
        ],
        colors: DEFAULT_TASK_COLORS,
        session_links: [],
        revision: 0,
      })
      if (method === 'POST' && path.endsWith('/cards'))
        board.cards.push({
          id: crypto.randomUUID(),
          title: String(body.title),
          note: '',
          status: 'todo',
          archived: false,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          workspace_id: null,
          due_date: typeof body.due_date === 'string' ? body.due_date : null,
        })
      if (method === 'PATCH')
        board.cards = board.cards.map(card =>
          card.id === path.split('/').pop()
            ? { ...card, ...body, updated_at: new Date().toISOString() }
            : card
        )
      if (method === 'PUT' && path.endsWith('/colors')) board.colors = body.colors
      if (method !== 'GET') {
        board.revision++
        writeDemo('task-board', board)
      }
      return json(board)
    }
    if (path === '/api/subagents/detect') return json({ backends: [] })
    if (path === '/api/imports/chat-history') return json({ sessions: [] })
    if (path === '/api/capabilities/registered') return json({ capabilities: [] })
    if (path === '/api/skills/list') return json({ skills: [] })
    if (path === '/api/space/cli-apps/apps')
      return json({ apps: [], access: { unrestricted: false, exec_denied: true } })
    if (path.startsWith('/api/space/mcp')) return json({ servers: {}, user: null })
    if (path === '/api/settings/ui') return json({ language: 'zh', response_language: 'zh' })
    if (path === '/api/auth/status')
      return json({ enabled: false, authenticated: true, user_id: 'dito-preview' })
    if (path === '/api/settings/workspace/registrations') return json({ workspaces: [] })
    if (path === '/api/settings/llm-options')
      return json({
        active: { profile_id: 'preview', model_id: 'demo' },
        options: [
          {
            profile_id: 'preview',
            model_id: 'demo',
            model: '示例模型',
            model_name: '演示模型',
            profile_name: '本地预览',
            provider: 'demo',
            is_active_default: true,
          },
        ],
      })
    if (path === '/api/knowledge-bases/list') return json([])
    if (path === '/api/subagents/settings') return json({ backends: {}, default_consult_budget: 3 })
    if (path === '/api/subagents/connections') return json({ connections: [] })
    if (path === '/api/settings/chat-attachments')
      return json({ max_files: 10, max_file_size_mb: 20, max_total_size_mb: 50 })
    if (path === '/api/notebooks') return json({ notebooks: [] })
    if (path === '/api/reading/extensions') return json([])
    if (path.startsWith('/api/reading/materials/preview-attention')) {
      const suffix = path.replace('/api/reading/materials/preview-attention', '')
      if (!suffix) return json(material)
      if (suffix.startsWith('/units/')) {
        const locator = Number(suffix.split('/').pop())
        return json({ locator, unit: 'section', text: readingUnits[locator - 1] || '' })
      }
      if (suffix === '/media') return json([])
      if (suffix === '/position') {
        const previous = readDemo('position', {
          locator: 1,
          source_anchor: '',
          percentage: 0,
          updated_at: 0,
        })
        const position =
          method === 'PUT' ? { ...previous, ...body, updated_at: Date.now() / 1000 } : previous
        if (method === 'PUT') writeDemo('position', position)
        return json(position)
      }
      if (suffix.startsWith('/annotations')) {
        let marks = readDemo<AnnotationItem[]>('annotations', [])
        if (method === 'PUT') {
          const mark = {
            ...body,
            annotation_id: body.annotation_id || crypto.randomUUID(),
            author: 'user',
            created_at: Date.now() / 1000,
            updated_at: Date.now() / 1000,
            rects: body.rects || [],
            source_anchor: body.source_anchor || '',
            note: body.note || '',
          } as AnnotationItem
          marks = [...marks.filter(m => m.annotation_id !== mark.annotation_id), mark]
          writeDemo('annotations', marks)
          return json(mark)
        }
        if (method === 'DELETE') {
          writeDemo(
            'annotations',
            marks.filter(m => m.annotation_id !== suffix.split('/').pop())
          )
          return json({ deleted: true })
        }
        return json(marks)
      }
      if (suffix === '/export')
        return new Response(readingUnits.join('\n\n---\n\n'), {
          headers: {
            'Content-Type': 'text/markdown',
            'Content-Disposition': 'attachment; filename="attention-notes.md"',
          },
        })
      if (suffix === '/quiz/rewards') return json({ rewards: [], total_stars: 0 })
      if (suffix === '/bookmarks') return json({ bookmarks: [] })
    }
    if (path === '/api/documents/preview-research') {
      const doc = readDemo('document', initialDocument)
      const updated =
        method === 'PUT'
          ? {
              ...doc,
              ...Object.fromEntries(Object.entries(body).filter(([, v]) => v !== null)),
              updated_at: Date.now() / 1000,
            }
          : doc
      if (method === 'PUT') writeDemo('document', updated)
      return json(updated)
    }
    if (path.startsWith('/api/documents/actions/')) {
      // Do not fake LLM edits: existing UI surfaces this actionable response.
      return json(
        { detail: '此预览未连接模型。可以直接编辑文稿，或在 Dito 侧栏体验示例对话。' },
        501
      )
    }
    if (path === '/api/documents/export/docx')
      return json({ detail: 'Word 导出需要后端；此预览可以编辑和自动保存文稿。' }, 501)
    if (method === 'GET' && /personas|memory|sessions|question-notebook|books/.test(path))
      return json({
        items: [],
        sessions: [],
        personas: [],
        entries: [],
        total: 0,
        books: [],
        files: [],
      })
    return json({ detail: '此功能需要后端服务，当前是前端交互预览。' }, 501)
  }
}
