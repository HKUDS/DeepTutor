import React from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { ServicePreviewPanel } from '@/components/settings/ServicePreviewPanel'
import { VoiceDiscoveryField } from '@/components/settings/VoiceDiscoveryField'
import type { Catalog } from '@/lib/model-catalog-types'
const mock = vi.hoisted(() => ({ draft: {} as Catalog, fetch: vi.fn() }))
vi.mock('@/features/settings/store/SettingsStore', () => ({ useSettings: () => ({ draft: mock.draft }) }))
vi.mock('@/lib/api', () => ({ apiUrl: (s: string) => s, apiFetch: (...args: unknown[]) => mock.fetch(...args) }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (s: string) => s }) }))
const profile = { id: 'p', name: 'Provider', binding: 'minimax', api_version: '', api_key: 'secret', base_url: 'https://example.test', models: [{ id: 'm', name: 'Model', model: 'test-model', voice: 'saved' }] }
function stream(events: object[]) {
  return { ok: true, body: new ReadableStream({ start(c) { for (const event of events) c.enqueue(new TextEncoder().encode(JSON.stringify(event) + '\n')); c.close() } }) }
}
beforeEach(() => {
  mock.fetch.mockReset()
  mock.draft = { version: 1, connections: [], services: Object.fromEntries(['llm','task','embedding','search','tts','stt','imagegen','videogen'].map(s => [s, { active_profile_id: 'old', active_model_id: 'old', profiles: [structuredClone(profile)] }])) } as unknown as Catalog
  URL.createObjectURL = vi.fn(() => 'blob:result')
  URL.revokeObjectURL = vi.fn()
})

it('loads live voices, preserves a saved ID and refreshes from the provider', async () => {
  mock.fetch.mockResolvedValue({ ok: true, json: async () => ({ status: 'ready', scope: 'account', voices: [{ id: 'live', label: 'Live voice' }] }) })
  const update = vi.fn()
  render(<VoiceDiscoveryField profileId="p" modelId="m" value="saved" update={update} disabled={false} />)
  await screen.findByRole('option', { name: 'Live voice' })
  expect(update).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText('settings.voiceDiscovery.choose'), { target: { value: 'live' } })
  expect(update).toHaveBeenCalledWith('live')
  fireEvent.click(screen.getByText('Refresh'))
  await waitFor(() => expect(mock.fetch).toHaveBeenCalledTimes(2))
  await screen.findByRole('option', { name: 'Live voice' })
})

it('ignores late voice results after switching models and retains manual entry', async () => {
  let resolve!: (v: unknown) => void
  mock.fetch.mockReturnValueOnce(new Promise(r => { resolve = r }))
  const update = vi.fn()
  const { rerender } = render(<VoiceDiscoveryField profileId="p" modelId="m" value="saved" update={update} disabled={false} />)
  await waitFor(() => expect(mock.fetch).toHaveBeenCalledTimes(1))
  const signal = mock.fetch.mock.calls[0][1].signal
  mock.draft = structuredClone(mock.draft)
  mock.draft.services.tts.profiles[0].models[0].model = 'other'
  mock.fetch.mockResolvedValue({ ok: true, json: async () => ({ status: 'unsupported', voices: [], scope: 'none' }) })
  rerender(<VoiceDiscoveryField profileId="p" modelId="m" value="saved" update={update} disabled={false} />)
  await screen.findByText('settings.voiceDiscovery.unsupported')
  expect(signal.aborted).toBe(true)
  await act(async () => resolve({ ok: true, json: async () => ({ status: 'ready', voices: [{ id: 'stale', label: 'Stale voice' }], scope: 'account' }) }))
  expect(screen.queryByRole('option', { name: 'Stale voice' })).toBeNull()
  fireEvent.click(screen.getByText('settings.voiceDiscovery.manual'))
  fireEvent.change(screen.getByLabelText('Voice ID'), { target: { value: 'manual-voice' } })
  expect(update).toHaveBeenCalledWith('manual-voice')
})

it('distinguishes voice failure from an empty live list and allows retry', async () => {
  mock.fetch.mockResolvedValueOnce({ ok: false }).mockResolvedValueOnce({ ok: true, json: async () => ({ status: 'ready', voices: [], scope: 'account' }) })
  render(<VoiceDiscoveryField profileId="p" modelId="m" value="" update={vi.fn()} disabled={false} />)
  await screen.findByText('settings.voiceDiscovery.failed')
  fireEvent.click(screen.getByText('Refresh'))
  await screen.findByText('settings.voiceDiscovery.empty')
})

it('searches the addressed draft and renders safe result links without applying', async () => {
  mock.fetch.mockResolvedValue(stream([{ type: 'result', kind: 'search', text: '', results: [{ title: 'Result', url: 'https://example.org', snippet: 'Found' }, { title: 'Unsafe', url: 'javascript:alert(1)', snippet: '' }] }]))
  render(<ServicePreviewPanel service="search" profile={profile} />)
  fireEvent.change(screen.getByLabelText('settings.servicePreview.query'), { target: { value: 'a real question' } })
  fireEvent.click(screen.getByRole('button', { name: 'settings.servicePreview.action.search' }))
  await screen.findByRole('link', { name: 'Result' })
  expect(screen.queryByRole('link', { name: 'Unsafe' })).toBeNull()
  const sent = JSON.parse(mock.fetch.mock.calls[0][1].body)
  expect(sent.profile_id).toBe('p')
  expect(sent.text).toBe('a real question')
  expect(sent.catalog.services.search.active_profile_id).toBe('old')
})

it('shows completed image output and releases it on parameter change', async () => {
  mock.fetch.mockResolvedValue(stream([{ type: 'result', kind: 'image', data: btoa('image'), content_type: 'image/png' }]))
  const { rerender } = render(<ServicePreviewPanel service="imagegen" profile={profile} model={profile.models[0]} />)
  fireEvent.change(screen.getByLabelText('settings.servicePreview.prompt'), { target: { value: 'test image' } })
  fireEvent.click(screen.getByRole('button', { name: 'settings.servicePreview.action.imagegen' }))
  await screen.findByRole('img', { name: 'test image' })
  mock.draft = structuredClone(mock.draft)
  mock.draft.services.imagegen.profiles[0].models[0].model = 'other'
  rerender(<ServicePreviewPanel service="imagegen" profile={profile} model={profile.models[0]} />)
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:result')
  expect(screen.queryByRole('img')).toBeNull()
})

it('video submission remains running until media is returned and can be cancelled', async () => {
  let source!: ReadableStreamDefaultController<Uint8Array>
  mock.fetch.mockResolvedValue({ ok: true, body: new ReadableStream({ start(c) { source = c } }) })
  const { unmount } = render(<ServicePreviewPanel service="videogen" profile={profile} model={profile.models[0]} />)
  fireEvent.change(screen.getByLabelText('settings.servicePreview.prompt'), { target: { value: 'a wave' } })
  fireEvent.click(screen.getByRole('button', { name: 'settings.servicePreview.action.videogen' }))
  await act(async () => { source.enqueue(new TextEncoder().encode('{"type":"progress","phase":"rendering"}\n')) })
  expect(screen.getByText('settings.servicePreview.status.rendering')).toBeTruthy()
  expect(screen.queryByText('settings.servicePreview.status.success')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(mock.fetch.mock.calls[0][1].signal.aborted).toBe(true)
  expect(screen.getByText('settings.servicePreview.status.cancelled')).toBeTruthy()
  await act(async () => source.close())
  unmount()
})

it('uploads real audio and displays its transcript', async () => {
  mock.fetch.mockResolvedValue(stream([{ type: 'result', kind: 'transcript', text: 'Hello from the recording' }]))
  render(<ServicePreviewPanel service="stt" profile={profile} model={profile.models[0]} />)
  fireEvent.change(screen.getByLabelText('settings.servicePreview.audio'), { target: { files: [new File(['spoken audio'], 'speech.wav', { type: 'audio/wav' })] } })
  fireEvent.click(screen.getByRole('button', { name: 'settings.servicePreview.action.stt' }))
  await screen.findByText('Hello from the recording')
  expect(JSON.parse(mock.fetch.mock.calls[0][1].body).audio).toBe(btoa('spoken audio'))
})
