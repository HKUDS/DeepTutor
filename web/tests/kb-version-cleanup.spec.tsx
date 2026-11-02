import React from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import KbVersionCleanup from '@/components/knowledge/KbVersionCleanup'

const mocks = vi.hoisted(() => ({ preview: vi.fn(), clean: vi.fn() }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (s: string) => s }) }))
vi.mock('@/features/knowledge/api/client', () => ({
  previewIndexCleanup: mocks.preview,
  cleanIndexVersions: mocks.clean,
}))
vi.mock('@/components/common/Modal', () => ({
  default: ({ isOpen, children }: { isOpen: boolean; children: React.ReactNode }) =>
    isOpen ? <div>{children}</div> : null,
}))
afterEach(cleanup)
beforeEach(() => {
  mocks.preview
    .mockReset()
    .mockResolvedValue({ versions: ['version-1'], bytes: 1048576, fingerprint: 'fresh' })
  mocks.clean.mockReset().mockResolvedValue({ versions: ['version-1'] })
})

it('previews without deleting and requires confirmation with the preview token', async () => {
  const done = vi.fn()
  render(<KbVersionCleanup kbRef="workspace:demo:kb:example" disabled={false} onCleaned={done} />)
  fireEvent.click(screen.getByRole('button', { name: 'Clean up old index versions' }))
  await screen.findByRole('button', { name: 'Delete old indexes' })
  expect(mocks.clean).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Delete old indexes' }))
  await waitFor(() => expect(done).toHaveBeenCalledWith(['version-1']))
  expect(mocks.clean).toHaveBeenCalledWith('workspace:demo:kb:example', 'fresh')
})

it('requires a new preview after a stale plan error', async () => {
  mocks.clean.mockRejectedValue(new Error('Index versions changed'))
  render(<KbVersionCleanup kbRef="example" disabled={false} onCleaned={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Clean up old index versions' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Delete old indexes' }))
  await screen.findByRole('alert')
  expect(screen.queryByRole('button', { name: 'Delete old indexes' })).toBeNull()
  expect(screen.getByRole('button', { name: 'Preview again' })).toBeTruthy()
})

it('does not start cleanup while the knowledge base is busy', () => {
  render(<KbVersionCleanup kbRef="example" disabled onCleaned={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Clean up old index versions' }))
  expect(mocks.preview).not.toHaveBeenCalled()
})
