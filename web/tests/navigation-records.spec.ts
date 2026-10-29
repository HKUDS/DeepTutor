import { expect, it } from 'vitest'
import { allLearningActivity, type LearningSources } from '@/lib/learning-dashboard'
import { categoryForPath, partnerSessionHref, isNavigationTargetActive } from '@/lib/navigation'

it('keeps old feature URLs in their new categories', () => {
  for (const path of ['/chat/old-session', '/co-writer/old-document', '/kanban'])
    expect(categoryForPath(path)).toBe('home')
  for (const path of ['/learning/books/old-book', '/learning/reading/old-material'])
    expect(categoryForPath(path)).toBe('learning')
  for (const path of ['/space', '/space/chat-history', '/knowledge-bases/old-kb', '/notebooks/old-notebook'])
    expect(categoryForPath(path)).toBe('resources')
  // The account's own places, the same in every workspace.
  for (const path of ['/personalization', '/agents', '/space/mcp', '/space/skills', '/space/personas', '/memory/l1'])
    expect(categoryForPath(path)).toBe('personalization')
  expect(categoryForPath('/partners/groups/old-group')).toBe('partners')
})

it('retains duplicate question IDs from distinct workspaces and preserves exact origin in links', () => {
  const sources: LearningSources = {
    books: [],
    mastery: [],
    reading: [],
    watching: [],
    practice: [
      {
        id: 1,
        question: 'Original question',
        updated_at: 20,
        created_at: 1,
        content_workspace_id: '',
      },
      {
        id: 1,
        question: 'Workspace question',
        updated_at: 30,
        created_at: 2,
        content_workspace_id: 'ws_other',
      },
    ],
  }
  const rows = allLearningActivity(sources)
  expect(new Set(rows.map(row => row.key)).size).toBe(2)
  expect(rows.map(row => row.href)).toEqual([
    '/learning/practice?question=1&dt_workspace=ws_other',
    '/learning/practice?question=1&dt_workspace=',
  ])
  expect(sources.practice?.[0].question).toBe('Original question')
})

it('encodes partner identities and session keys independently without rewriting them', () => {
  const url = new URL(
    partnerSessionHref({ kind: 'partner', owner_id: '研究伙伴', session_key: 'web:old/+?' }),
    'https://example.test'
  )
  expect(decodeURIComponent(url.pathname)).toBe('/partners/研究伙伴')
  expect(url.searchParams.get('session')).toBe('web:old/+?')
})

it('highlights only the open question in its original workspace', () => {
  const path = '/learning/practice'
  const query = new URLSearchParams('question=7&dt_workspace=research')
  expect(
    isNavigationTargetActive('/learning/practice?question=7&dt_workspace=research', path, query)
  ).toBe(true)
  expect(
    isNavigationTargetActive('/learning/practice?question=8&dt_workspace=research', path, query)
  ).toBe(false)
  expect(isNavigationTargetActive('/learning/practice?question=7&dt_workspace=', path, query)).toBe(
    false
  )
  expect(isNavigationTargetActive('/learning', path, query)).toBe(true)
})
