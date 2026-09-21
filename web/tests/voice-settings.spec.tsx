import React, { useState } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { VoicePreviewPanel } from '@/components/settings/VoicePreviewPanel'
import { VoiceModelFields } from '@/components/settings/VoiceModelFields'
import { ModelsWorkspace } from '@/components/settings/ModelsWorkspace'
import { voiceModelOptions } from '@/lib/voice-settings'
import type { SettingsContextValue } from '@/features/settings/store/SettingsStore'
import type { Catalog, VoiceOptions } from '@/lib/model-catalog-types'

const mock = vi.hoisted(() => ({ settings: {} as SettingsContextValue, fetch: vi.fn() }))
vi.mock('@/features/settings/store/SettingsStore', () => ({ useSettings: () => mock.settings }))
vi.mock('@/lib/api', () => ({
  apiUrl: (url: string) => url,
  apiFetch: (...args: unknown[]) => mock.fetch(...args),
}))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (s: string) => s, i18n: { language: 'en' } }),
}))
const options: VoiceOptions = {
  models: [
    {
      id: 'seed-tts-2.0',
      label: '2.0',
      voices: [{ id: 'vivi-v2', label: 'Vivi 2.0', languages: ['zh-cn', 'en'] }],
      languages: [
        { id: 'zh-cn', label: 'Chinese' },
        { id: 'en', label: 'English' },
      ],
      formats: ['mp3', 'wav'],
      speed: { min: 0.5, max: 2, step: 0.05 },
      instructions: true,
    },
    {
      id: 'seed-tts-1.0',
      label: '1.0',
      voices: [{ id: 'sisi-v1', label: 'Sisi 1.0' }],
      languages: [],
      formats: ['mp3', 'wav'],
    },
  ],
  fallback: { id: '', label: '', voices: [], languages: [], formats: ['mp3', 'wav'] },
  docs_url: 'https://example.test/docs',
}
function fixture(): Catalog {
  const services = Object.fromEntries(
    ['llm', 'task', 'embedding', 'search', 'tts', 'stt', 'imagegen', 'videogen'].map(key => [
      key,
      { profiles: [], active_profile_id: null, active_model_id: null },
    ])
  ) as unknown as Catalog['services']
  services.tts = {
    active_profile_id: 'p',
    active_model_id: 'old',
    profiles: [
      {
        id: 'p',
        name: 'Speech',
        binding: 'volcengine_speech',
        api_key: '***',
        base_url: '',
        api_version: '',
        models: [
          { id: 'old', name: 'Old', model: 'seed-tts-1.0', voice: 'sisi-v1' },
          {
            id: 'new',
            name: 'Draft voice',
            model: 'seed-tts-2.0',
            voice: 'vivi-v2',
            instructions: 'gently',
          },
        ],
      },
    ],
  }
  return { version: 1, services, connections: [] }
}
function Harness({ workspace = false }: { workspace?: boolean }) {
  const [draft, setDraft] = useState(fixture)
  // eslint-disable-next-line react-hooks/immutability
  mock.settings = {
    draft,
    catalog: fixture(),
    providers: { tts: [{ value: 'volcengine_speech', voice_options: options }] },
    connectionTargets: [],
    catalogEditable: true,
    modelTests: {},
    testRunning: null,
    mutateCatalog: (fn: (c: Catalog) => void) =>
      setDraft(current => {
        const next = structuredClone(current)
        fn(next)
        return next
      }),
  } as unknown as SettingsContextValue
  return workspace ? (
    <ModelsWorkspace page="voice" />
  ) : (
    <>
      <button
        onClick={() =>
          setDraft(c => {
            const next = structuredClone(c)
            next.services.tts.profiles[0].models[1].voice = 'custom-speaker'
            return next
          })
        }
      >
        Change voice
      </button>
      <VoicePreviewPanel profileId="p" modelId="new" />
    </>
  )
}
beforeEach(() => {
  mock.fetch.mockReset()
  vi.stubGlobal('matchMedia', () => ({ matches: false }))
  URL.createObjectURL = vi.fn(() => 'blob:preview')
  URL.revokeObjectURL = vi.fn()
  window.history.replaceState({}, '', '/settings/voice?profile=p')
})

it('selects model families without inventing voices for unknown models', () => {
  expect(voiceModelOptions(options, 'seed-tts-2.0')?.voices[0].id).toBe('vivi-v2')
  expect(voiceModelOptions(options, 'private-model')?.voices).toEqual([])
})

it('shows provider-specific voices, speed and language choices and accepts private IDs', () => {
  const update = vi.fn()
  render(
    <VoiceModelFields
      service="tts"
      provider="volcengine_speech"
      model={fixture().services.tts.profiles[0].models[1]}
      options={options}
      preset={options.models[0]}
      update={update}
      disabled={false}
    />
  )
  expect(screen.getByRole('option', { name: 'Vivi 2.0' })).toBeTruthy()
  expect(screen.queryByRole('option', { name: 'Sisi 1.0' })).toBeNull()
  expect(screen.getByRole('spinbutton', { name: 'Speech speed' }).getAttribute('max')).toBe('2')
  fireEvent.change(screen.getByRole('combobox', { name: 'Voice ID' }), {
    target: { value: 'private-speaker' },
  })
  expect(update).toHaveBeenCalledWith('voice', 'private-speaker')
})

it('switching model updates an incompatible preset voice and clears unsupported instructions', async () => {
  render(<Harness workspace />)
  fireEvent.click(screen.getByRole('button', { name: /Draft voice/ }))
  fireEvent.change(screen.getByRole('combobox', { name: 'Model \/ resource ID' }), {
    target: { value: 'seed-tts-1.0' },
  })
  expect((screen.getByRole('combobox', { name: 'Voice ID' }) as HTMLInputElement).value).toBe(
    'sisi-v1'
  )
  expect(screen.queryByRole('textbox', { name: 'Voice instructions' })).toBeNull()
  expect(mock.settings.draft.services.tts.active_model_id).toBe('old')
})

it('previews the unsaved model, exposes playback and discards the clip after edits', async () => {
  mock.fetch.mockResolvedValue({
    ok: true,
    blob: async () => new Blob(['audio'], { type: 'audio/wav' }),
  })
  render(<Harness />)
  fireEvent.change(screen.getByRole('textbox', { name: 'Preview text' }), {
    target: { value: 'Hello there' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Preview voice' }))
  await waitFor(() => expect(screen.getByLabelText('Generated voice preview')).toBeTruthy())
  const body = JSON.parse(mock.fetch.mock.calls[0][1].body)
  expect(body.model_id).toBe('new')
  expect(body.text).toBe('Hello there')
  expect(body.catalog.services.tts.active_model_id).toBe('old')
  fireEvent.click(screen.getByText('Change voice'))
  expect(screen.queryByLabelText('Generated voice preview')).toBeNull()
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:preview')
})

it('aborts stale previews and does not display late audio after voice changes', async () => {
  let finish!: (value: unknown) => void
  mock.fetch.mockReturnValue(
    new Promise(resolve => {
      finish = resolve
    })
  )
  render(<Harness />)
  fireEvent.click(screen.getByRole('button', { name: 'Preview voice' }))
  const signal = mock.fetch.mock.calls[0][1].signal
  fireEvent.click(screen.getByText('Change voice'))
  expect(signal.aborted).toBe(true)
  finish({ ok: true, blob: async () => new Blob(['late'], { type: 'audio/wav' }) })
  await waitFor(() => expect(screen.queryByLabelText('Generated voice preview')).toBeNull())
  expect(URL.createObjectURL).not.toHaveBeenCalled()
})

it('reports failures and allows retry without applying settings', async () => {
  mock.fetch.mockResolvedValue({
    ok: false,
    json: async () => ({ detail: 'Check the Speech key' }),
  })
  render(<Harness />)
  fireEvent.click(screen.getByRole('button', { name: 'Preview voice' }))
  await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('Check the Speech key'))
  expect(screen.getByRole('button', { name: 'Preview voice' }).hasAttribute('disabled')).toBe(false)
})
