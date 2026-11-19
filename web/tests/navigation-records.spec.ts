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

it('collapses the questions of one practice session into a single expandable row', () => {
  const sources: LearningSources = {
    books: [],
    mastery: [],
    reading: [],
    watching: [],
    practice: [
      { id: 3, question: 'Q3', created_at: 1, updated_at: 30, session_id: 'set-1', session_title: 'Physics set', content_workspace_id: '' },
      { id: 2, question: 'Q2', created_at: 2, updated_at: 20, session_id: 'set-1', session_title: 'Physics set', content_workspace_id: '' },
      { id: 1, question: 'Q1', created_at: 3, updated_at: 10, session_id: 'set-1', session_title: 'Physics set', content_workspace_id: '' },
    ],
  }
  const rows = allLearningActivity(sources)
  expect(rows).toHaveLength(1)
  const group = rows[0]
  expect(group.title).toBe('Physics set')
  expect(group.count).toBe(3)
  expect(group.updatedAt).toBe(30)
  expect(group.createdAt).toBe(1)
  expect(group.href).toBe('/learning/practice?dt_workspace=')
  // The questions stay reachable from the group, newest first, each on its own link.
  expect(group.children?.map(child => child.title)).toEqual(['Q3', 'Q2', 'Q1'])
  expect(group.children?.map(child => child.href)).toEqual([
    '/learning/practice?question=3&dt_workspace=',
    '/learning/practice?question=2&dt_workspace=',
    '/learning/practice?question=1&dt_workspace=',
  ])
})

it('keeps practice entries without a shared session as individual rows', () => {
  const sources: LearningSources = {
    books: [],
    mastery: [],
    reading: [],
    watching: [],
    practice: [
      { id: 1, question: 'Loose question', created_at: 1, updated_at: 10, content_workspace_id: '' },
      { id: 2, question: 'Only one in its session', created_at: 2, updated_at: 20, session_id: 'solo-1', session_title: 'Solo', content_workspace_id: '' },
    ],
  }
  const rows = allLearningActivity(sources)
  expect(rows.map(row => row.title)).toEqual(['Only one in its session', 'Loose question'])
  expect(rows.every(row => row.count === undefined && row.children === undefined)).toBe(true)
  expect(rows.map(row => row.href)).toEqual([
    '/learning/practice?question=2&dt_workspace=',
    '/learning/practice?question=1&dt_workspace=',
  ])
})

it('falls back to the newest question when a session has no title, and never merges workspaces', () => {
  const sources: LearningSources = {
    books: [],
    mastery: [],
    reading: [],
    watching: [],
    practice: [
      { id: 1, question: 'Older', created_at: 1, updated_at: 10, session_id: 'set-1', session_title: '', content_workspace_id: '' },
      { id: 2, question: 'Newer', created_at: 2, updated_at: 20, session_id: 'set-1', session_title: '', content_workspace_id: '' },
      { id: 3, question: 'Elsewhere', created_at: 3, updated_at: 30, session_id: 'set-1', session_title: '', content_workspace_id: 'ws_other' },
    ],
  }
  const rows = allLearningActivity(sources)
  expect(rows).toHaveLength(2)
  const untitled = rows.find(row => row.key === 'practice::session:set-1')
  expect(untitled?.title).toBe('Newer')
  expect(untitled?.count).toBe(2)
  // The same session id in another workspace is not the same practice set.
  const other = rows.find(row => row.key === 'practice:ws_other:3')
  expect(other?.title).toBe('Elsewhere')
  expect(other?.count).toBeUndefined()
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
