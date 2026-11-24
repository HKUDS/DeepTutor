import { act, renderHook, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { catalogTranslate, hydrateTopicSource, useTopicSourceLibrary } from '@/hooks/useTopicSourceLibrary'
import { ensureLanguage, initI18n } from '@/i18n/init'
import { apiFetch } from '@/lib/api'

vi.mock('@/lib/api', () => ({ apiUrl: (path: string) => path, apiFetch: vi.fn() }))
vi.mock('@/lib/partners-api', () => ({ listPartners: async () => [], getPartnerSessions: vi.fn() }))
vi.mock('@/lib/partner-groups-api', () => ({
  listPartnerGroups: async () => [],
  listPartnerGroupSessions: vi.fn(),
}))
const translate = (key: string) => key

it('reads the current workspace indexes and pins file expansion and book hydration to their source', async () => {
  window.history.replaceState({}, '', '/learning/books?dt_workspace=destination')
  const origin = { content_workspace_id: 'original', content_workspace_name: 'Original' }
  vi.mocked(apiFetch).mockImplementation(async url => {
    const path = new URL(String(url), 'http://localhost').pathname
    const data = path.endsWith('/files')
      ? { files: [{ name: 'lesson.pdf', type: 'file' }] }
      : path.endsWith('/spine')
        ? {
            spine: {
              chapters: [{ title: 'Vectors', learning_objectives: [], summary: 'Geometry' }],
            },
          }
        : {
            items: path.endsWith('/knowledge')
              ? [{ id: 'workspace:original:kb:notes', name: 'notes', ...origin }]
              : path.endsWith('/books')
                ? [{ id: 'book1', title: 'Vectors', ...origin }]
                : [],
            unavailable_workspaces: [],
          }
    return new Response(JSON.stringify(data), { status: 200 })
  })
  const { result } = renderHook(() => useTopicSourceLibrary(translate))
  await waitFor(() => expect(result.current.loading).toBe(false))
  const kb = result.current.library.knowledgeBases[0]
  await act(() => result.current.loadChildren(kb))
  expect(result.current.childLists[kb.key].error).toBe('')
  expect(result.current.childLists[kb.key].candidates[0]).toMatchObject({
    sourceId: 'lesson.pdf',
    content_workspace_id: 'original',
  })
  const book = await hydrateTopicSource(result.current.library.books[0])
  expect(book.available).toBe(true)
  expect(book.metadata?.content_workspace_id).toBe('original')
  const urls = vi
    .mocked(apiFetch)
    .mock.calls.map(call => new URL(String(call[0]), 'http://localhost'))
  expect(
    urls
      .filter(url => url.pathname.includes('source-library'))
      .every(url => url.searchParams.get('dt_workspace') === 'destination')
  ).toBe(true)
  expect(
    urls
      .filter(url => /\/(files|spine)$/.test(url.pathname))
      .every(url => url.searchParams.get('dt_workspace') === 'original')
  ).toBe(true)
  expect(window.location.search).toBe('?dt_workspace=destination')
})

it('keeps fallback labels Chinese in Chinese and reads the catalog elsewhere', async () => {
  const i18n = initI18n('en')
  await ensureLanguage('tr')
  await ensureLanguage('zh')
  const t = i18n.getFixedT('tr')
  const zh = catalogTranslate(t, true)
  const tr = catalogTranslate(t, false)

  // Callers used to pass i18next's t, which read the Chinese text as the key and fell back to English.
  expect(zh('未命名题目', 'Untitled question')).toBe('未命名题目')
  expect(zh('未命名', 'Untitled')).toBe(i18n.getFixedT('zh')('Untitled'))
  expect(zh('{{count}} 条消息', '{{count}} messages', { count: 3 })).toBe('3 条消息')
  expect(tr('未命名题目', 'Untitled question')).toBe(t('Untitled question'))
  expect(tr('未命名题目', 'Untitled question')).not.toBe('Untitled question')
  expect(tr('{{name}} 中的文件', 'File in {{name}}', { name: 'notes' })).toContain('notes')
})
