import { act, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { expect, it, vi } from 'vitest'
import { WorkspaceNavigation } from '@/components/workspaces/WorkspaceNavigation'
import { WorkspaceRuntimeBoundary } from '@/components/workspaces/WorkspaceRuntimeBoundary'
import { activeWorkspaceId, selectWorkspace } from '@/lib/workspace-scope'
import { invalidateClientCache, withClientCache } from '@/lib/client-cache'

const fixture = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), query: new URLSearchParams() }))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: fixture.push, replace: fixture.replace }),
  usePathname: () => window.location.pathname,
  useSearchParams: () => fixture.query,
}))
vi.mock('@/lib/workspaces-api', () => ({
  listWorkspaces: () => Promise.resolve(['first', 'second'].map(workspace_id => ({ workspace_id, kind: 'workspace' }))),
}))

it('waits for draft persistence and uses client navigation for cross-workspace links', async () => {
  window.history.replaceState(null, '', '/chat?dt_workspace=first')
  let saved!: () => void
  const saving = new Promise<void>(resolve => { saved = resolve })
  const save = (event: Event) => (event as CustomEvent<Promise<void>[]>).detail.push(saving)
  window.addEventListener('deeptutor:before-workspace-switch', save)
  render(<><WorkspaceNavigation /><a href="/chat?dt_workspace=second">Second workspace</a></>)
  fireEvent.click(screen.getByText('Second workspace'))
  expect(fixture.push).not.toHaveBeenCalled()
  await act(async () => saved())
  expect(fixture.push).toHaveBeenCalledWith('/chat?dt_workspace=second')
  // A real document navigation would change location; only the router is called.
  expect(window.location.search).toBe('?dt_workspace=first')
  window.removeEventListener('deeptutor:before-workspace-switch', save)
})

it('keeps links that name no workspace in the current one', () => {
  window.history.replaceState(null, '', '/chat?dt_workspace=first')
  fixture.query = new URLSearchParams('dt_workspace=first')
  fixture.push.mockClear()
  render(<><WorkspaceNavigation /><a href="/kanban" onClick={event => event.preventDefault()}>Board</a></>)
  fireEvent.click(screen.getByText('Board'))
  expect(fixture.push).not.toHaveBeenCalled()
})

it('writes the tab workspace into a URL that arrived without one', () => {
  window.history.replaceState(null, '', '/chat?dt_workspace=first')
  activeWorkspaceId()
  window.history.replaceState(null, '', '/learning/books')
  fixture.query = new URLSearchParams()
  fixture.replace.mockClear()
  render(<WorkspaceNavigation />)
  expect(fixture.replace).toHaveBeenCalledWith('/learning/books?dt_workspace=first')
})

it('falls back to General once when the workspace no longer exists', async () => {
  window.history.replaceState(null, '', '/learning/books?dt_workspace=removed')
  fixture.query = new URLSearchParams('dt_workspace=removed')
  fixture.push.mockClear()
  render(<WorkspaceNavigation />)
  await vi.waitFor(() => expect(fixture.push).toHaveBeenCalledWith('/learning?dt_workspace='))
})

it('lets the latest navigation win when several switches await a draft', async () => {
  window.history.replaceState(null, '', '/chat?dt_workspace=first')
  fixture.push.mockClear()
  render(<WorkspaceNavigation />)
  const first = selectWorkspace('first', '/chat')
  const second = selectWorkspace('second', '/learning')
  await Promise.all([first, second])
  expect(fixture.push).toHaveBeenCalledExactlyOnceWith('/learning?dt_workspace=second')
})

it('resets content for query-only switches and back navigation, but retains it within one workspace', () => {
  function Content() {
    const [value, setValue] = useState('')
    return <input aria-label="Local state" value={value} onChange={event => setValue(event.target.value)} />
  }
  fixture.query = new URLSearchParams('dt_workspace=first')
  const view = render(<WorkspaceRuntimeBoundary><Content /></WorkspaceRuntimeBoundary>)
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'First workspace only' } })
  fixture.query = new URLSearchParams('dt_workspace=first&tab=files')
  view.rerender(<WorkspaceRuntimeBoundary><Content /></WorkspaceRuntimeBoundary>)
  expect(screen.getByRole('textbox')).toHaveValue('First workspace only')
  for (const scope of ['second', 'first']) {
    fixture.query = new URLSearchParams(`dt_workspace=${scope}`)
    view.rerender(<WorkspaceRuntimeBoundary><Content /></WorkspaceRuntimeBoundary>)
    expect(screen.getByRole('textbox')).toHaveValue('')
  }
})

it('does not let invalidated in-flight requests overwrite fresh cache entries', async () => {
  let finishOld!: (value: string) => void
  const old = withClientCache('scope-regression', () => new Promise<string>(resolve => { finishOld = resolve }))
  invalidateClientCache('scope-regression')
  await withClientCache('scope-regression', async () => 'fresh')
  finishOld('stale')
  await old
  expect(await withClientCache('scope-regression', async () => 'unexpected')).toBe('fresh')
})

it('keeps navigation snapshots during refresh and clears them on account changes', async () => {
  const { readClientCache } = await import('@/lib/client-cache')
  const { invalidateAuthStatusCache } = await import('@/lib/auth')
  const key = 'navigation:retained-view'
  window.history.replaceState(null, '', '/learning?dt_workspace=first')
  await withClientCache(key, async () => 'first account')
  let finish!: (value: string) => void
  const refresh = withClientCache(key, () => new Promise<string>(resolve => { finish = resolve }), { force: true })
  expect(readClientCache(key)).toBe('first account')
  window.history.replaceState(null, '', '/learning?dt_workspace=second')
  expect(readClientCache(key)).toBeUndefined()
  window.history.replaceState(null, '', '/learning?dt_workspace=first')
  invalidateAuthStatusCache()
  expect(readClientCache(key)).toBeUndefined()
  finish('outdated account response')
  await refresh
  expect(readClientCache(key)).toBeUndefined()
})
