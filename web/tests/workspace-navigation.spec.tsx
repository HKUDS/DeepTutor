import { act, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { expect, it, vi } from 'vitest'
import { WorkspaceNavigation } from '@/components/workspaces/WorkspaceNavigation'
import { WorkspaceRuntimeBoundary } from '@/components/workspaces/WorkspaceRuntimeBoundary'
import { selectWorkspace } from '@/lib/workspace-scope'
import { invalidateClientCache, withClientCache } from '@/lib/client-cache'

const fixture = vi.hoisted(() => ({ push: vi.fn(), query: new URLSearchParams() }))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: fixture.push }),
  useSearchParams: () => fixture.query,
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

it('lets the latest navigation win when several switches await a draft', async () => {
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
