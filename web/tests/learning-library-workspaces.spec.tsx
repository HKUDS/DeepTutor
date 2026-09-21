import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useLearningCreation } from '@/components/learning/LibraryWorkspace'
import { ActivityLibrary } from '@/components/learning/ActivityLibrary'

const mocks = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), query: '', library: vi.fn() }))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mocks.push, replace: mocks.replace }),
  usePathname: () => '/learning/books',
  useSearchParams: () => new URLSearchParams(mocks.query),
}))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/hooks/useChatWorkspaces', () => ({ useChatWorkspaces: () => ({
  workspaces: [{ workspace_id: 'other', display_name: 'Other', status: 'ready' }], error: '',
}) }))
vi.mock('@/lib/learning-library', async importOriginal => ({
  ...await importOriginal<typeof import('@/lib/learning-library')>(), learningLibrary: mocks.library,
}))
function Creation({ open }: { open: () => void }) {
  const creation = useLearningCreation(open)
  return <>{creation.dialog}<button onClick={creation.begin}>New</button></>
}
beforeEach(() => {
  vi.clearAllMocks()
  mocks.query = ''
  window.history.replaceState({}, '', '/learning/books')
  mocks.library.mockResolvedValue({ items: [], unavailable_workspaces: [] })
})
it('chooses a new destination without treating the library filter as storage scope', () => {
  const open = vi.fn()
  render(<Creation open={open} />)
  fireEvent.click(screen.getByRole('button', { name: 'New' }))
  fireEvent.change(screen.getByLabelText('Save to workspace'), { target: { value: 'other' } })
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
  expect(mocks.push).toHaveBeenCalledWith('/learning/books?create=1&dt_workspace=other')
  expect(open).not.toHaveBeenCalled()
})
it('opens creation after client navigation even before window.location reflects the new query', async () => {
  const open = vi.fn()
  const view = render(<Creation open={open} />)
  mocks.query = 'create=1&dt_workspace=other'
  view.rerender(<Creation open={open} />)
  await waitFor(() => expect(open).toHaveBeenCalledOnce())
  expect(mocks.replace).toHaveBeenCalledWith('/learning/books?dt_workspace=other', { scroll: false })
})
it('keeps equal practice IDs in separate workspaces and filters without changing write scope', async () => {
  mocks.library.mockResolvedValue({ items: [
    { id: 1, question: 'Original question', content_workspace_id: '', content_workspace_name: 'Default workspace' },
    { id: 1, question: 'Other question', content_workspace_id: 'other', content_workspace_name: 'Other' },
  ], unavailable_workspaces: [] })
  render(<ActivityLibrary kind="practice" onCreate={vi.fn()} />)
  expect(await screen.findByRole('link', { name: /Original question/ })).toHaveAttribute('href', '/learning/practice?store=1&question=1&dt_workspace=')
  expect(screen.getByRole('link', { name: /Other question/ })).toHaveAttribute('href', '/learning/practice?store=1&question=1&dt_workspace=other')
  fireEvent.change(screen.getByLabelText('Filter by workspace'), { target: { value: 'other' } })
  expect(screen.queryByRole('link', { name: /Original question/ })).toBeNull()
  expect(screen.getByRole('link', { name: /Other question/ })).toBeInTheDocument()
  expect(mocks.push).not.toHaveBeenCalled()
  expect(window.location.search).toBe('')
})
