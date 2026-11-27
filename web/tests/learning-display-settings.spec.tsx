import React, { useEffect } from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { SettingsProvider, useSettings } from '@/features/settings/store/SettingsStore'
import { UiSettingsProvider } from '@/features/settings/store/UiSettingsProvider'
import Appearance from '@/features/settings/sections/AppearanceSettingsSection'
import { LEARNING_DISPLAY_APPLIED } from '@/lib/learning-display'
import { recoveryPrincipal, updateRecoveryPrincipal } from '@/lib/recovery-principal'
const mocks = vi.hoisted(() => ({ fetch: vi.fn(), t: (key: string) => key }))
vi.mock('@/lib/api', () => ({
  apiUrl: (s: string) => s,
  apiFetch: (...args: unknown[]) => mocks.fetch(...args),
}))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mocks.t }),
}))
vi.mock('next/dynamic', () => ({ default: () => () => null }))
vi.mock('@/context/AppShellContext', () => ({
  useAppShell: () => ({
    codeBlockTheme: 'github',
    codeBlockShowLineNumbers: false,
    codeBlockWrapLongLines: false,
  }),
}))
vi.mock('@/lib/llm-options', () => ({ invalidateLLMOptionsCache: vi.fn() }))
let settings: ReturnType<typeof useSettings>
let live: Record<string, unknown>
let parked: any
let failLoad: boolean
let failApply: boolean
const response = (data: unknown, ok = true) => ({
  ok,
  status: ok ? 200 : 503,
  json: async () => data,
})
function Capture() {
  const value = useSettings()
  useEffect(() => {
    settings = value
  }, [value])
  return null
}
async function mount() {
  render(
    <SettingsProvider>
      <UiSettingsProvider>
        <Capture />
        <Appearance />
      </UiSettingsProvider>
    </SettingsProvider>
  )
  await waitFor(() => expect(settings.settingsLoading).toBe(false))
}
function uiWrites() {
  return mocks.fetch.mock.calls.filter(
    ([url, init]) => url === '/api/settings/ui' && init?.method === 'PUT'
  )
}
beforeEach(() => {
  mocks.t = (key: string) => key
  updateRecoveryPrincipal(null)
  live = {
    theme: 'system',
    language: 'en',
    response_language: 'en',
    content_font_scale: 110,
    content_line_spacing: 'compact',
  }
  parked = null
  failLoad = false
  failApply = false
  mocks.fetch.mockReset()
  mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    if (url === '/api/settings') return response({ ui: live }, !failLoad)
    if (url === '/api/settings/display') return response(live)
    if (url === '/api/settings/draft') {
      if (method === 'PUT') parked = JSON.parse(String(init?.body))
      if (method === 'DELETE') {
        if (failApply) return response({}, false)
        parked = null
      }
      return response({ draft: parked })
    }
    if (url === '/api/settings/ui' && method === 'PUT') {
      if (failApply) return response({}, false)
      live = { ...live, ...JSON.parse(String(init?.body)) }
      return response(live)
    }
    return response({})
  })
})
it('previews locally and preserves Save Draft, Discard, Apply and reset', async () => {
  const applied = vi.fn()
  window.addEventListener(LEARNING_DISPLAY_APPLIED, applied)
  try {
    await mount()
    applied.mockClear()
    fireEvent.change(screen.getByLabelText('Learning text size'), {
      target: { value: '150' },
    })
    fireEvent.change(screen.getByLabelText('Learning line spacing'), {
      target: { value: 'relaxed' },
    })
    expect(
      screen.getByTestId('learning-text-preview').style.getPropertyValue('--learning-font-scale')
    ).toBe('1.5')
    expect(uiWrites()).toHaveLength(0)
    expect(applied).not.toHaveBeenCalled()
    await act(async () => {
      await settings.saveDraft()
    })
    expect(parked.extensions.ui.content_font_scale).toBe(150)
    expect(uiWrites()).toHaveLength(0)
    expect(applied).not.toHaveBeenCalled()
    await act(async () => {
      await settings.discardDraft()
    })
    expect(settings.contentFontScale).toBe(110)
    expect(settings.contentLineSpacing).toBe('compact')
    fireEvent.click(screen.getByRole('button', { name: 'Reset learning text' }))
    expect(settings.contentFontScale).toBe(100)
    expect(settings.contentLineSpacing).toBe('normal')
    expect(settings.theme).toBe('system')
    expect(applied).not.toHaveBeenCalled()
    await act(async () => {
      await settings.applyCatalog()
    })
    expect(live.content_font_scale).toBe(100)
    expect(live.content_line_spacing).toBe('normal')
    expect(applied).toHaveBeenCalledTimes(1)
  } finally {
    window.removeEventListener(LEARNING_DISPLAY_APPLIED, applied)
  }
})
it('keeps draft and global display unchanged when Apply fails', async () => {
  await mount()
  const applied = vi.fn()
  window.addEventListener(LEARNING_DISPLAY_APPLIED, applied)
  try {
    fireEvent.change(screen.getByLabelText('Learning text size'), {
      target: { value: '150' },
    })
    failApply = true
    await act(async () => {
      await settings.applyCatalog()
    })
    expect(settings.contentFontScale).toBe(150)
    expect(live.content_font_scale).toBe(110)
    expect(applied).not.toHaveBeenCalled()
    expect(settings.hasUnsavedChanges).toBe(true)
  } finally {
    window.removeEventListener(LEARNING_DISPLAY_APPLIED, applied)
  }
})
it('omits unknown display values after a failed load', async () => {
  failLoad = true
  await mount()
  await act(async () => {
    await settings.updateLanguage('zh')
    await settings.applyCatalog()
  })
  const payload = JSON.parse(uiWrites()[0][1].body)
  expect(payload).not.toHaveProperty('content_font_scale')
  expect(payload).not.toHaveProperty('content_line_spacing')
  expect(live.content_font_scale).toBe(110)
})
it('applies legacy UI drafts without materializing display defaults', async () => {
  parked = { extensions: { ui: { theme: 'snow', language: 'zh' } } }
  await mount()
  expect(settings.contentFontScale).toBe(110)
  await act(async () => {
    await settings.applyCatalog()
  })
  expect(JSON.parse(uiWrites()[0][1].body)).not.toHaveProperty('content_font_scale')
  expect(live.content_font_scale).toBe(110)
})

it('inherits omitted server spacing when explicitly applying size after a failed load', async () => {
  failLoad = true
  await mount()
  await act(async () => {
    await settings.updateContentFontScale(150)
  })
  await act(async () => {
    await settings.applyCatalog()
  })
  expect(settings.contentFontScale).toBe(150)
  expect(settings.contentLineSpacing).toBe('compact')
  expect(live.content_line_spacing).toBe('compact')
})

const switchAccount = (id: string) =>
  updateRecoveryPrincipal({ enabled: true, authenticated: true, user_id: id })

it.each(['bob', 'alice'])(
  "ignores Alice's delayed draft after switching to %s",
  async finalAccount => {
    switchAccount('alice')
    let finishDraft!: (value: unknown) => void
    let requestedDraft = false
    const delayedDraft = new Promise(resolve => {
      finishDraft = resolve
    })
    const fallback = mocks.fetch.getMockImplementation()!
    mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === '/api/settings/draft' && !init?.method) {
        requestedDraft = true
        return { ok: true, json: () => delayedDraft }
      }
      return fallback(url, init)
    })
    await mount()
    await waitFor(() => expect(requestedDraft).toBe(true))
    live = { ...live, content_font_scale: 90, content_line_spacing: 'normal' }
    act(() => switchAccount('bob'))
    await waitFor(() => expect(settings.contentFontScale).toBe(90))
    if (finalAccount === 'alice') {
      live = { ...live, content_font_scale: 125 }
      act(() => switchAccount('alice'))
      await waitFor(() => expect(settings.contentFontScale).toBe(125))
    }
    await act(async () => {
      finishDraft({
        draft: { extensions: { ui: { content_font_scale: 150, content_line_spacing: 'relaxed' } } },
      })
    })
    expect(settings.contentFontScale).toBe(finalAccount === 'alice' ? 125 : 90)
    expect(settings.contentLineSpacing).toBe('normal')
    expect(settings.pendingExtensionPayload('ui')).toBeUndefined()
  }
)

it.each([false, true])(
  "does not continue Alice's Apply under Bob's account (rejection=%s)",
  async rejectDraft => {
    switchAccount('alice')
    await mount()
    await act(async () => {
      await settings.updateContentFontScale(150)
    })
    let finishDraft!: (value: unknown) => void
    let failDraft!: (error: Error) => void
    let requestedDraft = false
    const delayedDraft = new Promise((resolve, reject) => {
      finishDraft = resolve
      failDraft = reject
    })
    const fallback = mocks.fetch.getMockImplementation()!
    mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === '/api/settings/draft' && init?.method === 'PUT') {
        requestedDraft = true
        return delayedDraft
      }
      return fallback(url, init)
    })
    let applying!: Promise<void>
    await act(async () => {
      applying = settings.applyCatalog()
    })
    await waitFor(() => expect(requestedDraft).toBe(true))
    live = { ...live, content_font_scale: 90, content_line_spacing: 'normal' }
    act(() => switchAccount('bob'))
    await waitFor(() => expect(settings.contentFontScale).toBe(90))
    await act(async () => {
      if (rejectDraft) failDraft(new Error("Alice's stale draft failed"))
      else finishDraft(response({}))
      await applying
    })
    expect(uiWrites()).toHaveLength(0)
    expect(
      mocks.fetch.mock.calls.some(
        ([url, init]) => url === '/api/settings/draft' && init?.method === 'DELETE'
      )
    ).toBe(false)
    expect(settings.applying).toBe(false)
    expect(settings.contentFontScale).toBe(90)
    expect(settings.toast).not.toMatch(/Applied|Could not apply/)
  }
)

it.each(['single-user', 'user:alice'])(
  'restarts a cold full settings load when %s resolves',
  async owner => {
    let finishInitial!: (value: unknown) => void
    const initialResponse = new Promise(resolve => {
      finishInitial = resolve
    })
    let fullReads = 0
    const writeOwners: Array<string | null> = []
    const fallback = mocks.fetch.getMockImplementation()!
    parked = { extensions: { ui: { theme: 'glass', content_font_scale: 150 } } }
    live = { ...live, theme: 'snow', content_font_scale: 125, content_line_spacing: 'compact' }
    mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === '/api/settings') {
        fullReads += 1
        if (fullReads === 1) return initialResponse
      }
      if (url === '/api/settings/ui' && init?.method === 'PUT')
        writeOwners.push(recoveryPrincipal())
      return fallback(url, init)
    })
    render(
      <SettingsProvider>
        <UiSettingsProvider>
          <Capture />
          <Appearance />
        </UiSettingsProvider>
      </SettingsProvider>
    )
    await waitFor(() => expect(fullReads).toBe(1))
    expect(settings.settingsLoading).toBe(true)
    act(() => {
      if (owner === 'single-user') updateRecoveryPrincipal({ enabled: false, authenticated: true })
      else switchAccount('alice')
    })
    await waitFor(() => expect(fullReads).toBe(2))
    await act(async () => {
      finishInitial(response({ ui: { ...live, theme: 'dark', content_font_scale: 90 } }))
    })
    await waitFor(() => expect(settings.settingsLoading).toBe(false))
    await waitFor(() => expect(settings.contentFontScale).toBe(150))
    expect(settings.catalogEditable).toBe(false)
    expect(settings.theme).toBe('glass')
    expect(settings.contentLineSpacing).toBe('compact')
    expect(settings.pendingExtensionPayload('ui')).toEqual({
      theme: 'glass',
      content_font_scale: 150,
    })
    expect(settings.settingsError).toBeNull()
    await act(async () => {
      await settings.applyCatalog()
    })
    expect(writeOwners).toEqual([owner])
    expect(live.content_font_scale).toBe(150)
    expect(live.content_line_spacing).toBe('compact')
    expect(settings.hasUnsavedChanges).toBe(false)
  }
)

function settingsTree() {
  return (
    <SettingsProvider>
      <UiSettingsProvider>
        <Capture />
        <Appearance />
      </UiSettingsProvider>
    </SettingsProvider>
  )
}
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(finish => {
    resolve = finish
  })
  return { promise, resolve }
}
function fullReads() {
  return mocks.fetch.mock.calls.filter(([url]) => url === '/api/settings').length
}

it('restarts the unsettled initial read during actual StrictMode effect replay', async () => {
  switchAccount('alice')
  const abandoned = deferred<ReturnType<typeof response>>()
  const replacement = deferred<ReturnType<typeof response>>()
  const fallback = mocks.fetch.getMockImplementation()!
  let reads = 0
  parked = { extensions: { ui: { theme: 'glass', content_font_scale: 150 } } }
  mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === '/api/settings') return ++reads === 1 ? abandoned.promise : replacement.promise
    return fallback(url, init)
  })
  render(<React.StrictMode>{settingsTree()}</React.StrictMode>)
  await waitFor(() => expect(reads).toBe(2))
  expect(settings.settingsLoading).toBe(true)
  await act(async () => {
    replacement.resolve(response({ ui: { ...live, theme: 'snow', content_font_scale: 125 } }))
  })
  await waitFor(() => expect(settings.contentFontScale).toBe(150))
  expect(settings.settingsLoading).toBe(false)
  expect(settings.theme).toBe('glass')
  await act(async () => {
    abandoned.resolve(response({ ui: { ...live, theme: 'dark', content_font_scale: 90 } }))
  })
  expect(settings.contentFontScale).toBe(150)
  expect(settings.pendingExtensionPayload('ui')).toEqual(parked.extensions.ui)
  expect(reads).toBe(2)
})

it('replaces resolved Alice initial loading with Bob full settings and parked draft', async () => {
  switchAccount('alice')
  const abandoned = deferred<ReturnType<typeof response>>()
  const replacement = deferred<ReturnType<typeof response>>()
  const fallback = mocks.fetch.getMockImplementation()!
  let reads = 0
  parked = { extensions: { ui: { theme: 'glass', content_font_scale: 90 } } }
  mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === '/api/settings') return ++reads === 1 ? abandoned.promise : replacement.promise
    return fallback(url, init)
  })
  render(settingsTree())
  await waitFor(() => expect(reads).toBe(1))
  act(() => switchAccount('bob'))
  await waitFor(() => expect(reads).toBe(2))
  await act(async () => {
    replacement.resolve(response({ ui: { ...live, theme: 'snow', content_font_scale: 125 } }))
  })
  await waitFor(() => expect(settings.contentFontScale).toBe(90))
  expect(settings.settingsLoading).toBe(false)
  expect(settings.theme).toBe('glass')
  await act(async () => {
    abandoned.resolve(response({ ui: { ...live, theme: 'dark', content_font_scale: 150 } }))
  })
  expect(settings.contentFontScale).toBe(90)
  expect(settings.pendingExtensionPayload('ui')).toEqual(parked.extensions.ui)
})

it('uses the ownership epoch for Alice → Bob → Alice while the initial gate is pending', async () => {
  switchAccount('alice')
  const requests = Array.from({ length: 3 }, () => deferred<ReturnType<typeof response>>())
  const fallback = mocks.fetch.getMockImplementation()!
  let reads = 0
  parked = { extensions: { ui: { theme: 'glass', content_font_scale: 125 } } }
  mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === '/api/settings') return requests[reads++].promise
    return fallback(url, init)
  })
  render(settingsTree())
  await waitFor(() => expect(reads).toBe(1))
  act(() => switchAccount('bob'))
  await waitFor(() => expect(reads).toBe(2))
  act(() => switchAccount('alice'))
  await waitFor(() => expect(reads).toBe(3))
  await act(async () => {
    requests[2].resolve(response({ ui: { ...live, theme: 'snow', content_font_scale: 110 } }))
  })
  await waitFor(() => expect(settings.contentFontScale).toBe(125))
  await act(async () => {
    requests[1].resolve(response({ ui: { ...live, theme: 'dark', content_font_scale: 90 } }))
    requests[0].resolve(response({ ui: { ...live, theme: 'dark', content_font_scale: 150 } }))
  })
  expect(settings.settingsLoading).toBe(false)
  expect(settings.contentFontScale).toBe(125)
  expect(settings.theme).toBe('glass')
  expect(settings.pendingExtensionPayload('ui')).toEqual(parked.extensions.ui)
})

it('keeps loaded unrelated drafts across a boundary without another full settings read', async () => {
  switchAccount('alice')
  await mount()
  await act(async () => {
    settings.registerExtension('workspace', {
      dirty: true,
      payload: { path: '/alice-draft' },
      save: async () => {},
    })
    await settings.updateLanguage('zh')
    await settings.updateContentFontScale(150)
  })
  expect(fullReads()).toBe(1)
  live = { ...live, content_font_scale: 90, content_line_spacing: 'normal' }
  act(() => switchAccount('bob'))
  await waitFor(() => expect(settings.contentFontScale).toBe(90))
  expect(fullReads()).toBe(1)
  expect(settings.pendingExtensionPayload('workspace')).toEqual({ path: '/alice-draft' })
  expect(settings.language).toBe('zh')
  expect(settings.pendingExtensionPayload('ui')).not.toHaveProperty('content_font_scale')
  expect(settings.pendingExtensionPayload('ui')).not.toHaveProperty('content_line_spacing')
})

it.each(['pending', 'loaded'])(
  'does not reload or invalidate %s settings when the translation callback changes',
  async state => {
    switchAccount('alice')
    const initial = deferred<ReturnType<typeof response>>()
    const fallback = mocks.fetch.getMockImplementation()!
    if (state === 'pending') {
      mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) =>
        url === '/api/settings' ? initial.promise : fallback(url, init)
      )
      parked = { extensions: { ui: { theme: 'glass', content_font_scale: 125 } } }
    }
    const view = render(settingsTree())
    await waitFor(() => expect(fullReads()).toBe(1))
    if (state === 'loaded') {
      await waitFor(() => expect(settings.settingsLoading).toBe(false))
      await act(async () => {
        await settings.updateContentFontScale(150)
      })
    }
    mocks.t = (key: string) => key
    view.rerender(settingsTree())
    expect(fullReads()).toBe(1)
    if (state === 'pending') {
      await act(async () => {
        initial.resolve(response({ ui: { ...live, theme: 'snow' } }))
      })
      await waitFor(() => expect(settings.contentFontScale).toBe(125))
      expect(settings.theme).toBe('glass')
    } else expect(settings.contentFontScale).toBe(150)
    expect(settings.settingsLoading).toBe(false)
    expect(fullReads()).toBe(1)
  }
)

async function currentAccountDraft(finalOwner: 'bob' | 'alice') {
  live = { ...live, content_font_scale: 125, content_line_spacing: 'relaxed' }
  act(() => switchAccount('bob'))
  await waitFor(() => expect(settings.contentFontScale).toBe(125))
  if (finalOwner === 'alice') {
    act(() => switchAccount('alice'))
    await waitFor(() => expect(settings.contentFontScale).toBe(125))
  }
  await act(async () => {
    await settings.updateContentLineSpacing('compact')
    settings.registerExtension('workspace', {
      dirty: true,
      payload: { path: '/current-draft' },
      save: async () => {},
    })
  })
  await act(async () => {
    expect(await settings.saveDraft()).toBe(true)
  })
  await act(async () => {
    await settings.updateContentLineSpacing('normal')
    settings.setToast('Current account notice')
  })
}
function draftSnapshot() {
  return {
    ui: settings.pendingExtensionPayload('ui'),
    workspace: settings.pendingExtensionPayload('workspace'),
    storedDraft: settings.storedDraft,
    revision: settings.draftRevision,
    draftState: settings.draftState,
    toast: settings.toast,
  }
}
function deferredRequest() {
  let resolve!: (value: unknown) => void
  let reject!: (error: Error) => void
  const promise = new Promise((finish, fail) => {
    resolve = finish
    reject = fail
  })
  return { promise, resolve, reject }
}

for (const operation of ['save', 'discard'] as const) {
  for (const finalOwner of ['bob', 'alice'] as const) {
    it.each([false, true])(
      `ignores stale ${operation} completion after Alice → Bob → ${finalOwner} (reject=%s)`,
      async reject => {
        switchAccount('alice')
        await mount()
        await act(async () => {
          await settings.updateContentFontScale(150)
        })
        const old = deferredRequest()
        const fallback = mocks.fetch.getMockImplementation()!
        let intercepted = false
        mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
          if (
            !intercepted &&
            url === '/api/settings/draft' &&
            init?.method === (operation === 'save' ? 'PUT' : 'DELETE')
          ) {
            intercepted = true
            return old.promise
          }
          return fallback(url, init)
        })
        let stale!: Promise<boolean | null | void>
        await act(async () => {
          stale = operation === 'save' ? settings.saveDraft() : settings.discardDraft()
        })
        await waitFor(() => expect(intercepted).toBe(true))
        await currentAccountDraft(finalOwner)
        const before = draftSnapshot()
        const applied = vi.fn()
        window.addEventListener(LEARNING_DISPLAY_APPLIED, applied)
        try {
          let result: boolean | null | void
          await act(async () => {
            if (reject) old.reject(new Error('Old account request failed'))
            else
              old.resolve(
                response({
                  draft: {
                    extensions: {
                      ui: { content_font_scale: 150, content_line_spacing: 'relaxed' },
                    },
                  },
                })
              )
            result = await stale
          })
          if (operation === 'save') expect(result!).toBeNull()
          expect(draftSnapshot()).toEqual(before)
          expect(settings.contentFontScale).toBe(125)
          expect(settings.contentLineSpacing).toBe('normal')
          expect(applied).not.toHaveBeenCalled()
        } finally {
          window.removeEventListener(LEARNING_DISPLAY_APPLIED, applied)
        }
      }
    )
  }
}

it.each([false, true])('guards the separate Save Draft JSON await (reject=%s)', async reject => {
  switchAccount('alice')
  await mount()
  const old = deferredRequest()
  const fallback = mocks.fetch.getMockImplementation()!
  let decoded = false
  let intercepted = false
  mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
    if (!intercepted && url === '/api/settings/draft' && init?.method === 'PUT') {
      intercepted = true
      return {
        ok: true,
        json: () => {
          decoded = true
          return old.promise
        },
      }
    }
    return fallback(url, init)
  })
  let stale!: Promise<boolean | null>
  await act(async () => {
    stale = settings.saveDraft()
  })
  await waitFor(() => expect(decoded).toBe(true))
  await currentAccountDraft('bob')
  const before = draftSnapshot()
  await act(async () => {
    if (reject) old.reject(new Error('Old JSON failed'))
    else old.resolve({ draft: { extensions: { ui: { content_font_scale: 150 } } } })
    expect(await stale).toBeNull()
  })
  expect(draftSnapshot()).toEqual(before)
})

it.each(['save', 'discard'] as const)(
  'keeps the current account busy when old %s finalizes',
  async operation => {
    switchAccount('alice')
    await mount()
    const old = deferredRequest()
    const current = deferredRequest()
    const fallback = mocks.fetch.getMockImplementation()!
    let requests = 0
    const method = operation === 'save' ? 'PUT' : 'DELETE'
    mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === '/api/settings/draft' && init?.method === method)
        return ++requests === 1 ? old.promise : current.promise
      return fallback(url, init)
    })
    let stale!: Promise<boolean | null | void>
    await act(async () => {
      stale = operation === 'save' ? settings.saveDraft() : settings.discardDraft()
    })
    live = { ...live, content_font_scale: 125 }
    act(() => switchAccount('bob'))
    await waitFor(() => expect(settings.contentFontScale).toBe(125))
    await act(async () => {
      await settings.updateContentLineSpacing('relaxed')
    })
    let active!: Promise<boolean | null | void>
    await act(async () => {
      active = operation === 'save' ? settings.saveDraft() : settings.applyCatalog()
    })
    await waitFor(() => expect(requests).toBe(2))
    await act(async () => {
      old.resolve(response({ draft: null }))
      await stale
    })
    expect(operation === 'save' ? settings.saving : settings.applying).toBe(true)
    await act(async () => {
      current.resolve(response({ draft: null }))
      await active
    })
    expect(operation === 'save' ? settings.saving : settings.applying).toBe(false)
  }
)

for (const finalOwner of ['bob', 'alice'] as const) {
  it.each(['post', 'json', 'rejection'] as const)(
    `ignores stale preset %s after Alice → Bob → ${finalOwner}`,
    async phase => {
      switchAccount('alice')
      await mount()
      const old = deferredRequest()
      const fallback = mocks.fetch.getMockImplementation()!
      let requested = false
      mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
        if (url === '/api/settings/presets/old-preset/draft') {
          if (phase === 'json')
            return {
              ok: true,
              json: () => {
                requested = true
                return old.promise
              },
            }
          requested = true
          return old.promise
        }
        return fallback(url, init)
      })
      let stale!: Promise<boolean>
      await act(async () => {
        stale = settings.stagePreset('old-preset')
      })
      await waitFor(() => expect(requested).toBe(true))
      await currentAccountDraft(finalOwner)
      const before = draftSnapshot()
      const applied = vi.fn()
      window.addEventListener(LEARNING_DISPLAY_APPLIED, applied)
      try {
        await act(async () => {
          const alice = {
            draft: {
              extensions: {
                ui: { theme: 'dark', content_font_scale: 150, content_line_spacing: 'relaxed' },
              },
            },
          }
          if (phase === 'rejection') old.reject(new Error('Old preset failed'))
          else old.resolve(phase === 'json' ? alice : response(alice))
          expect(await stale).toBe(false)
        })
        expect(draftSnapshot()).toEqual(before)
        expect(settings.contentFontScale).toBe(125)
        expect(settings.contentLineSpacing).toBe('normal')
        expect(applied).not.toHaveBeenCalled()
      } finally {
        window.removeEventListener(LEARNING_DISPLAY_APPLIED, applied)
      }
    }
  )
}
