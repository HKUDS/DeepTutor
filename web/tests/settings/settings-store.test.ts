import test from 'node:test'
import assert from 'node:assert/strict'

let mockLocalStorage: Record<string, string> = {}
let mockSessionStorage: Record<string, string> = {}
let dispatchedEvents: Array<{ type: string; detail: unknown }> = []

function mockWindow() {
  global.window = {
    location: { search: '', origin: 'http://localhost' },
    localStorage: {
      getItem: (key: string) => mockLocalStorage[key] ?? null,
      setItem: (key: string, value: string) => {
        mockLocalStorage[key] = value
      },
      removeItem: (key: string) => {
        delete mockLocalStorage[key]
      },
    },
    sessionStorage: {
      getItem: (key: string) => mockSessionStorage[key] ?? null,
      setItem: (key: string, value: string) => {
        mockSessionStorage[key] = value
      },
      removeItem: (key: string) => {
        delete mockSessionStorage[key]
      },
    },
    dispatchEvent: (event: { type: string; detail?: unknown }) => {
      dispatchedEvents.push({ type: event.type, detail: event.detail })
      return true
    },
    addEventListener: () => {},
    removeEventListener: () => {},
  } as unknown as typeof globalThis.window
}

mockWindow()

import * as settingsContext from '../../features/settings/store/SettingsStore'
import {
  CODE_BLOCK_SHOW_LINE_NUMBERS_STORAGE_KEY,
  CODE_BLOCK_SETTINGS_EVENT,
  CODE_BLOCK_THEME_STORAGE_KEY,
  CODE_BLOCK_WRAP_LONG_LINES_STORAGE_KEY,
  DEFAULT_CODE_BLOCK_THEME,
  isResponseLanguage,
  readStoredCodeBlockShowLineNumbers,
  readStoredCodeBlockTheme,
  readStoredCodeBlockWrapLongLines,
} from '../../context/app-shell-storage'
import type {
  Catalog,
  CatalogProfile,
  DiagnosticsResult,
  ServiceName,
  UiSettings,
} from '../../features/settings/store/SettingsStore'

// ─── Fixtures ──────────────────────────────────────────────────────────────

const VALID_UI: UiSettings = {
  theme: 'dark',
  language: 'en',
  response_language: 'en',
  code_block_theme: 'dracula',
  code_block_show_line_numbers: true,
  code_block_wrap_long_lines: true,
}

function emptyService() {
  return { active_profile_id: null, active_model_id: null, profiles: [] }
}

/** Minimal catalog: llm active with two models, search with one provider. */
function makeCatalog(): Catalog {
  return {
    version: 1,
    connections: [],
    services: {
      llm: {
        active_profile_id: 'p1',
        active_model_id: 'm1',
        profiles: [
          {
            id: 'p1',
            name: 'OpenAI',
            binding: 'openai',
            base_url: 'https://api.openai.com/v1',
            api_key: 'sk-test',
            api_version: '',
            extra_headers: {},
            wire_api: 'auto',
            models: [
              { id: 'm1', name: 'M1', model: 'gpt-test' },
              { id: 'm2', name: 'M2', model: 'gpt-other' },
            ],
          },
        ],
      },
      search: {
        active_profile_id: 's1',
        profiles: [
          {
            id: 's1',
            name: 'Brave',
            provider: 'brave',
            base_url: '',
            api_key: 'bsk-test',
            api_version: '',
            models: [],
          },
        ],
      },
      task: emptyService(),
      embedding: emptyService(),
      tts: emptyService(),
      stt: emptyService(),
      imagegen: emptyService(),
      videogen: emptyService(),
    },
  }
}

function diagnostics(overrides: Partial<DiagnosticsResult>): DiagnosticsResult {
  return {
    state: 'success',
    message: 'ok',
    profileId: 'p1',
    modelId: 'm1',
    ...overrides,
  }
}

/** Fetch recorder for persistUiSettingsPatch. */
function recordingFetcher() {
  const calls: Array<{
    input: RequestInfo | URL
    init?: RequestInit
  }> = []
  const fetcher = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    calls.push({ input, init })
    return { ok: true } as Response
  }
  return { calls, fetcher }
}

function resetStorage() {
  mockLocalStorage = {}
  mockSessionStorage = {}
  dispatchedEvents = []
  mockWindow()
}

// ─── 验收 1a：patch 后本地存储与 store 同步 ─────────────────────────────────

test('sync writes backend-loaded code-block values into app-shell storage and returns the normalized values', () => {
  resetStorage()

  const normalized = settingsContext.syncLoadedCodeBlockSettingsToAppShell({
    code_block_theme: 'dracula',
    code_block_show_line_numbers: true,
    code_block_wrap_long_lines: true,
  })

  assert.deepEqual(normalized, {
    code_block_theme: 'dracula',
    code_block_show_line_numbers: true,
    code_block_wrap_long_lines: true,
  })
  // The app-shell storage mirrors exactly what the backend sent.
  assert.equal(readStoredCodeBlockTheme(), 'dracula')
  assert.equal(readStoredCodeBlockShowLineNumbers(), true)
  assert.equal(readStoredCodeBlockWrapLongLines(), true)
  assert.equal(
    mockLocalStorage[CODE_BLOCK_THEME_STORAGE_KEY],
    'dracula',
    'raw theme key should hold the theme id'
  )
  assert.equal(
    mockLocalStorage[CODE_BLOCK_SHOW_LINE_NUMBERS_STORAGE_KEY],
    'true',
    'raw switch keys are stored as strings'
  )
  assert.equal(mockLocalStorage[CODE_BLOCK_WRAP_LONG_LINES_STORAGE_KEY], 'true')
})

test('sync announces every code-block value through the app-shell settings event', () => {
  resetStorage()

  settingsContext.syncLoadedCodeBlockSettingsToAppShell({
    code_block_theme: 'github',
    code_block_show_line_numbers: false,
    code_block_wrap_long_lines: true,
  })

  const events = dispatchedEvents.filter(event => event.type === CODE_BLOCK_SETTINGS_EVENT)
  assert.equal(events.length, 3, 'one event per written code-block setting')
  assert.deepEqual(
    events.map(event => event.detail),
    [
      { codeBlockTheme: 'github' },
      { codeBlockShowLineNumbers: false },
      { codeBlockWrapLongLines: true },
    ]
  )
})

test('sync makes backend values win over stale local ones', () => {
  resetStorage()
  mockLocalStorage = {
    [CODE_BLOCK_THEME_STORAGE_KEY]: 'oneDark',
    [CODE_BLOCK_SHOW_LINE_NUMBERS_STORAGE_KEY]: 'false',
    [CODE_BLOCK_WRAP_LONG_LINES_STORAGE_KEY]: 'false',
  }

  const normalized = settingsContext.syncLoadedCodeBlockSettingsToAppShell({
    code_block_theme: 'dracula',
    code_block_show_line_numbers: true,
    code_block_wrap_long_lines: true,
  })

  assert.deepEqual(normalized, {
    code_block_theme: 'dracula',
    code_block_show_line_numbers: true,
    code_block_wrap_long_lines: true,
  })
  assert.equal(readStoredCodeBlockTheme(), 'dracula')
  assert.equal(readStoredCodeBlockShowLineNumbers(), true)
  assert.equal(readStoredCodeBlockWrapLongLines(), true)
})

test('persistUiSettingsPatch PUTs the patch to the workspace-scoped ui endpoint', async () => {
  const { calls, fetcher } = recordingFetcher()

  await settingsContext.persistUiSettingsPatch({ code_block_theme: 'dracula' }, fetcher)

  assert.equal(calls.length, 1)
  const { input, init } = calls[0]
  assert.match(String(input), /\/api\/settings\/ui\?dt_workspace=$/)
  assert.equal(init?.method, 'PUT')
  assert.equal((init?.headers as Record<string, string>)['Content-Type'], 'application/json')
  assert.deepEqual(JSON.parse(String(init?.body)), {
    code_block_theme: 'dracula',
  })
})

test('persistUiSettingsPatch sends a full ui patch verbatim — no field rewriting', async () => {
  const { calls, fetcher } = recordingFetcher()
  const patch: Partial<UiSettings> = {
    theme: 'glass',
    language: 'zh',
    response_language: 'zh',
    code_block_theme: 'oneDark',
    code_block_show_line_numbers: false,
    code_block_wrap_long_lines: true,
  }

  await settingsContext.persistUiSettingsPatch(patch, fetcher)

  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), patch)
})

test('persistUiSettingsPatch surfaces fetch failures instead of swallowing them', async () => {
  await assert.rejects(
    settingsContext.persistUiSettingsPatch({ theme: 'dark' }, async () => {
      throw new Error('network down')
    }),
    /network down/
  )
})

// ─── 验收 1b：非法值归一化不抛错 ────────────────────────────────────────────

test('sync on an empty patch falls back to defaults without throwing', () => {
  resetStorage()

  const normalized = settingsContext.syncLoadedCodeBlockSettingsToAppShell({})

  assert.deepEqual(normalized, {
    code_block_theme: DEFAULT_CODE_BLOCK_THEME,
    code_block_show_line_numbers: false,
    code_block_wrap_long_lines: false,
  })
  assert.equal(readStoredCodeBlockTheme(), DEFAULT_CODE_BLOCK_THEME)
})

test('sync normalizes null, empty and whitespace-only themes to the default', () => {
  for (const theme of [null, undefined, '', '   '] as Array<string | null | undefined>) {
    resetStorage()
    const normalized = settingsContext.syncLoadedCodeBlockSettingsToAppShell({
      code_block_theme: theme as UiSettings['code_block_theme'],
    })
    assert.equal(
      normalized.code_block_theme,
      DEFAULT_CODE_BLOCK_THEME,
      `theme ${JSON.stringify(theme)} should normalize to the default`
    )
    assert.equal(readStoredCodeBlockTheme(), DEFAULT_CODE_BLOCK_THEME)
  }
})

test('sync trims surrounding whitespace from a valid theme id', () => {
  resetStorage()

  const normalized = settingsContext.syncLoadedCodeBlockSettingsToAppShell({
    code_block_theme: '  dracula  ',
  })

  assert.equal(normalized.code_block_theme, 'dracula')
  assert.equal(readStoredCodeBlockTheme(), 'dracula')
})

test("sync accepts case-insensitive string 'true' for both switches", () => {
  resetStorage()

  const normalized = settingsContext.syncLoadedCodeBlockSettingsToAppShell({
    code_block_show_line_numbers: 'True',
    code_block_wrap_long_lines: 'TRUE',
  } as unknown as Partial<UiSettings>)

  assert.equal(normalized.code_block_show_line_numbers, true)
  assert.equal(normalized.code_block_wrap_long_lines, true)
  assert.equal(readStoredCodeBlockShowLineNumbers(), true)
  assert.equal(readStoredCodeBlockWrapLongLines(), true)
})

test('sync keeps an explicit boolean false — it must never be coerced to true', () => {
  resetStorage()

  const normalized = settingsContext.syncLoadedCodeBlockSettingsToAppShell({
    code_block_show_line_numbers: false,
    code_block_wrap_long_lines: false,
  })

  assert.equal(normalized.code_block_show_line_numbers, false)
  assert.equal(normalized.code_block_wrap_long_lines, false)
  assert.equal(readStoredCodeBlockShowLineNumbers(), false)
  assert.equal(readStoredCodeBlockWrapLongLines(), false)
})

test('sync maps missing and non-truthy garbage switch values to false without throwing', () => {
  const garbage: Array<unknown> = [
    undefined,
    null,
    0,
    1,
    'false',
    'False',
    'yes',
    'on',
    '1',
    {},
    [],
  ]
  for (const value of garbage) {
    resetStorage()
    const normalized = settingsContext.syncLoadedCodeBlockSettingsToAppShell({
      code_block_show_line_numbers: value as UiSettings['code_block_show_line_numbers'],
      code_block_wrap_long_lines: value as UiSettings['code_block_wrap_long_lines'],
    })
    assert.equal(
      normalized.code_block_show_line_numbers,
      false,
      `line-numbers value ${JSON.stringify(value)} should normalize to false`
    )
    assert.equal(
      normalized.code_block_wrap_long_lines,
      false,
      `wrap-lines value ${JSON.stringify(value)} should normalize to false`
    )
    assert.equal(readStoredCodeBlockShowLineNumbers(), false)
    assert.equal(readStoredCodeBlockWrapLongLines(), false)
  }
})

test("sync stringifies any value whose String() form is 'true' to boolean true", () => {
  // Documented contract: the check is `=== true || String(v).toLowerCase() === "true"`,
  // so anything coercing to the string "true" (case-insensitive) counts as on.
  resetStorage()

  const normalized = settingsContext.syncLoadedCodeBlockSettingsToAppShell({
    code_block_show_line_numbers: ['true'],
    code_block_wrap_long_lines: { toString: () => 'TRUE' },
  } as unknown as Partial<UiSettings>)

  assert.equal(normalized.code_block_show_line_numbers, true)
  assert.equal(normalized.code_block_wrap_long_lines, true)
  assert.equal(readStoredCodeBlockShowLineNumbers(), true)
  assert.equal(readStoredCodeBlockWrapLongLines(), true)
})

test('sync with a fully garbage patch still persists an internally consistent state', () => {
  resetStorage()

  const normalized = settingsContext.syncLoadedCodeBlockSettingsToAppShell({
    code_block_theme: null,
    code_block_show_line_numbers: {
      unexpected: 'field',
    } as unknown as UiSettings['code_block_show_line_numbers'],
    code_block_wrap_long_lines: 42 as unknown as UiSettings['code_block_wrap_long_lines'],
  } as unknown as Partial<UiSettings>)

  // Whatever was normalized is exactly what was persisted — storage can
  // never disagree with the store after a sync, even for garbage input.
  assert.equal(normalized.code_block_theme, DEFAULT_CODE_BLOCK_THEME)
  assert.equal(normalized.code_block_show_line_numbers, false)
  assert.equal(normalized.code_block_wrap_long_lines, false)
  assert.equal(
    mockLocalStorage[CODE_BLOCK_SHOW_LINE_NUMBERS_STORAGE_KEY],
    String(normalized.code_block_show_line_numbers)
  )
  assert.equal(
    mockLocalStorage[CODE_BLOCK_WRAP_LONG_LINES_STORAGE_KEY],
    String(normalized.code_block_wrap_long_lines)
  )
  assert.equal(readStoredCodeBlockShowLineNumbers(), normalized.code_block_show_line_numbers)
  assert.equal(readStoredCodeBlockWrapLongLines(), normalized.code_block_wrap_long_lines)
})

test('sync without a window object is a no-op, not a crash (SSR guard)', () => {
  const originalWindow = global.window
  // @ts-expect-error -- simulating server-side rendering
  global.window = undefined
  try {
    assert.doesNotThrow(() =>
      settingsContext.syncLoadedCodeBlockSettingsToAppShell({
        code_block_theme: 'dracula',
        code_block_show_line_numbers: true,
      })
    )
  } finally {
    global.window = originalWindow
  }
})

// ─── 验收 2：常量与纯函数契约（修复卡可直接领取的夹具） ─────────────────────

test('TOUR_STEPS walk the settings navigator in order with complete steps', () => {
  const steps = settingsContext.TOUR_STEPS

  assert.ok(steps.length > 0, 'the tour must have steps')
  for (const step of steps) {
    assert.ok(step.target.length > 0, 'every step names a data-tour target')
    assert.ok(step.route.startsWith('/settings/'), 'tour steps live under /settings')
    assert.ok(step.titleKey.length > 0, 'every step has a title i18n key')
    assert.ok(step.descKey.length > 0, 'every step has a description i18n key')
  }
  const routes = steps.map(step => step.route)
  assert.equal(new Set(routes).size, routes.length, 'no duplicated tour routes')
  // The tour is ordered: status first, then navigator pages.
  assert.deepEqual(routes, [
    '/settings/status',
    '/settings/appearance',
    '/settings/network',
    '/settings/llm',
    '/settings/knowledge',
    '/settings/starters',
    '/settings/memory',
  ])
})

test('RESPONSE_LANGUAGE_OPTIONS covers the supported response languages exactly once each', () => {
  const options = settingsContext.RESPONSE_LANGUAGE_OPTIONS

  assert.equal(options.length, 15)
  const values = options.map(option => option.value)
  assert.equal(new Set(values).size, values.length, 'no duplicated codes')
  for (const value of values) {
    assert.ok(isResponseLanguage(value), `${value} must be a valid ResponseLanguage`)
    assert.ok(option_label(options, value).length > 0, 'every option has a label')
  }
  assert.equal(values[0], 'en', 'English is the first option')
  for (const expected of ['zh', 'zh-tw', 'ja', 'ar', 'ms']) {
    assert.ok(values.includes(expected as (typeof values)[number]))
  }
})

function option_label(
  options: ReadonlyArray<{ value: string; label: string }>,
  value: string
): string {
  return options.find(option => option.value === value)!.label
}

test('defaultCatalog has one bucket per service and is fresh on every call', () => {
  const catalog = settingsContext.defaultCatalog()

  assert.deepEqual(Object.keys(catalog.services).sort(), [
    'embedding',
    'imagegen',
    'llm',
    'search',
    'stt',
    'task',
    'tts',
    'videogen',
  ])
  for (const [service, bucket] of Object.entries(catalog.services)) {
    assert.deepEqual(bucket.profiles, [], `${service} starts without profiles`)
    assert.equal(bucket.active_profile_id, null)
    if (service !== 'search') {
      assert.equal(bucket.active_model_id, null)
    }
  }
  // Mutating one instance must not leak into the next.
  catalog.services.llm.profiles.push({ id: 'x' } as CatalogProfile)
  assert.equal(settingsContext.defaultCatalog().services.llm.profiles.length, 0)
})

test('cloneCatalog returns a deep copy — edits to the clone never reach the source', () => {
  const source = makeCatalog()
  const clone = settingsContext.cloneCatalog(source)

  assert.notEqual(clone, source)
  assert.deepEqual(clone, source)
  clone.services.llm.active_model_id = 'm2'
  clone.services.llm.profiles[0].models.pop()
  clone.services.llm.profiles[0].extra_headers = { injected: 'yes' }
  assert.equal(source.services.llm.active_model_id, 'm1')
  assert.equal(source.services.llm.profiles[0].models.length, 2)
  assert.deepEqual(source.services.llm.profiles[0].extra_headers, {})
})

test('voiceService and generationService classify audio and media services', () => {
  assert.equal(settingsContext.voiceService('tts'), true)
  assert.equal(settingsContext.voiceService('stt'), true)
  assert.equal(settingsContext.voiceService('llm'), false)
  assert.equal(settingsContext.generationService('imagegen'), true)
  assert.equal(settingsContext.generationService('videogen'), true)
  assert.equal(settingsContext.generationService('llm'), false)
  assert.equal(settingsContext.generationService('tts'), false)
})

test('getActiveProfile resolves the active profile, falls back to the first, else null', () => {
  const catalog = makeCatalog()

  assert.equal(settingsContext.getActiveProfile(catalog, 'llm')?.id, 'p1')
  // No active id: fall back to the first profile.
  catalog.services.llm.active_profile_id = null
  assert.equal(settingsContext.getActiveProfile(catalog, 'llm')?.id, 'p1')
  // Unknown active id still falls back rather than returning nothing.
  catalog.services.llm.active_profile_id = 'missing'
  assert.equal(settingsContext.getActiveProfile(catalog, 'llm')?.id, 'p1')
  // Empty bucket.
  assert.equal(settingsContext.getActiveProfile(catalog, 'embedding'), null)
})

test('getActiveModel resolves the active model with the same fallback chain; search has no models', () => {
  const catalog = makeCatalog()

  assert.equal(settingsContext.getActiveModel(catalog, 'llm')?.id, 'm1')
  assert.equal(settingsContext.getActiveModel(catalog, 'search'), null)

  // active_model_id not set: first model wins.
  catalog.services.llm.active_model_id = null
  assert.equal(settingsContext.getActiveModel(catalog, 'llm')?.id, 'm1')
  // active_model_id stale: first model wins over an unknown id.
  catalog.services.llm.active_model_id = 'gone'
  assert.equal(settingsContext.getActiveModel(catalog, 'llm')?.id, 'm1')
  // No profiles at all.
  assert.equal(settingsContext.getActiveModel(catalog, 'tts'), null)
})

test('serviceConfigured requires a usable model entry, and a provider for search', () => {
  const catalog = makeCatalog()

  assert.equal(settingsContext.serviceConfigured(catalog, 'llm'), true)
  assert.equal(settingsContext.serviceConfigured(catalog, 'search'), true)
  assert.equal(settingsContext.serviceConfigured(catalog, 'tts'), false)

  // A model entry without a model id is not configured.
  catalog.services.llm.profiles[0].models[0].model = ''
  assert.equal(settingsContext.serviceConfigured(catalog, 'llm'), false)
  // A search profile without a provider is not configured.
  catalog.services.search.profiles[0].provider = undefined
  assert.equal(settingsContext.serviceConfigured(catalog, 'search'), false)
})

test('currentDiagnosticsResult only reports results for the currently selected profile/model', () => {
  const catalog = makeCatalog()

  assert.equal(
    settingsContext.currentDiagnosticsResult(catalog, 'llm', {}),
    null,
    'no diagnostics at all'
  )
  const matching = diagnostics({})
  assert.equal(
    settingsContext.currentDiagnosticsResult(catalog, 'llm', { llm: matching }),
    matching
  )
  // Stale: result was for a profile/model that is no longer selected.
  const stale = diagnostics({ profileId: 'p-other' })
  assert.equal(settingsContext.currentDiagnosticsResult(catalog, 'llm', { llm: stale }), null)
  // Search diagnostics match on a null model id.
  const searchResult = diagnostics({
    profileId: 's1',
    modelId: null,
  })
  assert.equal(
    settingsContext.currentDiagnosticsResult(catalog, 'search', {
      search: searchResult,
    }),
    searchResult
  )
})

test('serviceReadiness derives its four states from configuration and diagnostics', () => {
  const catalog = makeCatalog()
  const none: Partial<Record<ServiceName, DiagnosticsResult>> = {}

  assert.equal(settingsContext.serviceReadiness(catalog, 'tts', none), 'not_configured')
  assert.equal(settingsContext.serviceReadiness(catalog, 'llm', none), 'untested')
  assert.equal(
    settingsContext.serviceReadiness(catalog, 'llm', {
      llm: diagnostics({ state: 'success' }),
    }),
    'passed'
  )
  assert.equal(
    settingsContext.serviceReadiness(catalog, 'llm', {
      llm: diagnostics({ state: 'failed' }),
    }),
    'failed'
  )
  // A stale failure must not fail the service.
  assert.equal(
    settingsContext.serviceReadiness(catalog, 'llm', {
      llm: diagnostics({ state: 'failed', profileId: 'old' }),
    }),
    'untested'
  )
})

test('servicePendingApply compares one service bucket at a time', () => {
  const catalog = makeCatalog()
  const draft = settingsContext.cloneCatalog(catalog)

  assert.equal(settingsContext.servicePendingApply(catalog, draft, 'llm'), false)
  draft.services.llm.active_model_id = 'm2'
  assert.equal(settingsContext.servicePendingApply(catalog, draft, 'llm'), true)
  // Other buckets stay clean.
  assert.equal(settingsContext.servicePendingApply(catalog, draft, 'search'), false)
  assert.equal(settingsContext.servicePendingApply(catalog, draft, 'tts'), false)
})

test('RESPONSE_LANGUAGE_OPTIONS values are usable as UiSettings.response_language fixtures', () => {
  // Fixture completeness: any option value round-trips through a UiSettings
  // object that persistUiSettingsPatch would send verbatim.
  const option = settingsContext.RESPONSE_LANGUAGE_OPTIONS.at(-1)!
  const ui: UiSettings = { ...VALID_UI, response_language: option.value }
  assert.equal(ui.response_language, option.value)
  assert.equal(VALID_UI.language, 'en')
})
