import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import {
  GeneratedOutputFileActions,
  supportsGeneratedOutputActions,
} from '@/components/chat/GeneratedOutputFileActions'

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }))
vi.mock('@/lib/api', () => ({ apiFetch: (...args: unknown[]) => mocks.fetch(...args) }))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (value: string) => value,
  }),
}))

const url = `/files/workspace-items/ws_${'a'.repeat(32)}/wsi_${'b'.repeat(32)}?dt_workspace=course-one`
const attachment = {
  generated: true,
  url,
  relative_path:
    'outputs/chat/session/turn_one/exec/outputs/chat/session/turn_one/gap-lock.html',
}
const directAttachment = {
  generated: true,
  url,
  relative_path: 'outputs/chat/session/turn_run-123/showme-next-key-lock-range.html',
}
const storage = {
  file_path: '/workspace/outputs/chat/session/turn/exec/outputs/gap-lock.html',
  file_bytes: 6800,
  fingerprint: 'f'.repeat(64),
  can_reveal: true,
}
const ok = (body: unknown) => ({ ok: true, json: async () => body })

beforeEach(() => mocks.fetch.mockReset())

it('offers actions only for generated chat exec outputs', () => {
  expect(supportsGeneratedOutputActions(attachment)).toBe(true)
  expect(supportsGeneratedOutputActions(directAttachment)).toBe(true)
  expect(
    supportsGeneratedOutputActions({
      ...directAttachment,
      relative_path: 'outputs/chat/session/turn_run-123/exec/lp-replay-simulator.html',
    })
  ).toBe(true)
  expect(supportsGeneratedOutputActions({ ...attachment, generated: false })).toBe(false)
  expect(
    supportsGeneratedOutputActions({
      ...attachment,
      relative_path: 'outputs/math_animator/session/turn/artifacts/movie.mp4',
    })
  ).toBe(false)
})

it('shows the path, confirms removal, and keeps the chat attachment', async () => {
  mocks.fetch.mockResolvedValueOnce(ok(storage)).mockResolvedValueOnce(ok({ removed: true }))
  render(<GeneratedOutputFileActions url={url} />)
  fireEvent.click(screen.getByRole('button', { name: 'Output files' }))
  expect(await screen.findByLabelText('Saved file path')).toHaveValue(storage.file_path)
  fireEvent.click(screen.getByRole('button', { name: 'Remove workspace file' }))
  expect(await screen.findByRole('alertdialog')).toHaveTextContent(
    'The chat attachment stays available.'
  )
  fireEvent.click(screen.getAllByRole('button', { name: 'Remove workspace file' })[1])
  expect(
    await screen.findByText('Workspace file removed. The chat attachment is still available.')
  ).toBeInTheDocument()
  expect(mocks.fetch.mock.calls[0][0]).toBe(
    `${url.split('?')[0]}/file-storage?dt_workspace=course-one`
  )
  expect(mocks.fetch).toHaveBeenCalledWith(
    `${url.split('?')[0]}/remove-generated-output?dt_workspace=course-one`,
    expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ fingerprint: storage.fingerprint }),
    })
  )
})
