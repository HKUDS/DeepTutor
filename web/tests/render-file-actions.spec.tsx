import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { RenderFileActions } from '@/components/math-animator/RenderFileActions'

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }))
vi.mock('@/lib/api', () => ({ apiFetch: (...args: unknown[]) => mocks.fetch(...args) }))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (s: string, values?: Record<string, unknown>) =>
      s.replace(/\{\{(\w+)\}\}/g, (_, key: string) => String(values?.[key] ?? '')),
  }),
}))

const url = `/files/workspace-items/ws_${'a'.repeat(32)}/wsi_${'b'.repeat(32)}`
const preview = {
  file_path: '/workspace/outputs/movie.mp4',
  file_bytes: 1234,
  cache_bytes: 4096,
  cache_files: 3,
  fingerprint: 'f'.repeat(64),
  can_reveal: false,
}
const ok = (body: unknown) => ({ ok: true, json: async () => body })

beforeEach(() => {
  mocks.fetch.mockReset()
})

it('shows paths on demand and copies the original path', async () => {
  const copy = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: copy } })
  mocks.fetch.mockResolvedValue(ok(preview))
  render(<RenderFileActions url={url} />)
  expect(mocks.fetch).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Output files' }))
  expect(await screen.findByLabelText('Saved file path')).toHaveValue(preview.file_path)
  expect(screen.queryByRole('button', { name: 'Show in file manager' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Copy file path' }))
  await waitFor(() => expect(copy).toHaveBeenCalledWith(preview.file_path))
})

it('previews cleanup and requires confirmation, preserving the output URL', async () => {
  mocks.fetch.mockImplementation(async (path: string) =>
    path.endsWith('clean-render-cache')
      ? ok({ cache_files: 0, cache_bytes: 0, freed_bytes: 4096, fingerprint: 'new' })
      : ok(preview)
  )
  render(<RenderFileActions url={url} />)
  fireEvent.click(screen.getByRole('button', { name: 'Output files' }))
  await screen.findByLabelText('Saved file path')
  fireEvent.click(screen.getByRole('button', { name: 'Clean render files' }))
  const dialog = await screen.findByRole('alertdialog')
  expect(dialog).toHaveTextContent('Remove 3 render files and free 4.0 KB?')
  expect(mocks.fetch.mock.calls.some(([p]) => p.endsWith('clean-render-cache'))).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('alertdialog')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Clean render files' }))
  await screen.findByRole('alertdialog')
  fireEvent.click(screen.getAllByRole('button', { name: 'Clean render files' })[1])
  await screen.findByText('Freed 4.0 KB. Final output is kept.')
  expect(mocks.fetch).toHaveBeenCalledWith(
    `${url}/clean-render-cache`,
    expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ fingerprint: preview.fingerprint }),
    })
  )
  expect(screen.getByRole('button', { name: 'Clean render files' })).toBeDisabled()
  expect(screen.getByLabelText('Saved file path')).toHaveValue(preview.file_path)
})

it('shows cleanup errors without claiming that storage was freed', async () => {
  mocks.fetch.mockImplementation(async (path: string) =>
    path.endsWith('clean-render-cache')
      ? { ok: false, json: async () => ({ detail: 'Render files changed. Review again.' }) }
      : ok(preview)
  )
  render(<RenderFileActions url={url} />)
  fireEvent.click(screen.getByRole('button', { name: 'Output files' }))
  await screen.findByLabelText('Saved file path')
  fireEvent.click(screen.getByRole('button', { name: 'Clean render files' }))
  await screen.findByRole('alertdialog')
  fireEvent.click(screen.getAllByRole('button', { name: 'Clean render files' })[1])
  expect(await screen.findByRole('alert')).toHaveTextContent('Render files changed.')
  expect(screen.queryByText(/Freed/)).toBeNull()
})

it('offers no local actions for external or legacy URLs', () => {
  const { container } = render(<RenderFileActions url="https://example.test/movie.mp4" />)
  expect(container).toBeEmptyDOMElement()
  expect(mocks.fetch).not.toHaveBeenCalled()
})

it("retains the artifact's workspace scope in storage requests", async () => {
  mocks.fetch.mockResolvedValue(ok(preview))
  render(<RenderFileActions url={`${url}?dt_workspace=course-one`} />)
  fireEvent.click(screen.getByRole('button', { name: 'Output files' }))
  await screen.findByLabelText('Saved file path')
  expect(mocks.fetch).toHaveBeenCalledWith(
    `${url}/render-storage?dt_workspace=course-one`,
    undefined
  )
})
