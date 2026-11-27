import React, { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { ModelTestPanel } from '@/components/settings/ModelTestPanel'
import {
  MODEL_SERVICES,
  modelTestFingerprint,
  modelTestKey,
  type ModelTestState,
} from '@/lib/model-settings'
import type { Catalog } from '@/lib/model-catalog-types'

const mocks = vi.hoisted(() => ({ settings: {} as Record<string, unknown> }))
vi.mock('@/features/settings/store/SettingsStore', () => ({ useSettings: () => mocks.settings }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (value: string) => value }) }))

function Harness({
  levels,
  locked = false,
  selectableLevels,
  testState = 'success',
}: {
  levels: string[] | null
  locked?: boolean
  selectableLevels?: string[] | null
  testState?: 'success' | 'failed'
}) {
  const [draft, setDraft] = useState(
    () =>
      ({
        services: {
          ...Object.fromEntries(
            [...MODEL_SERVICES, 'search'].map(service => [service, { profiles: [] }])
          ),
          llm: {
            active_profile_id: 'p',
            active_model_id: 'm',
            profiles: [
              {
                id: 'p',
                name: 'Provider',
                binding: 'custom',
                base_url: 'https://provider.test/v1',
                api_key: '',
                api_version: '',
                read_only: locked,
                models: [
                  {
                    id: 'm',
                    name: 'Model',
                    model: 'provider/model',
                    reasoning_effort: 'medium',
                    enabled_reasoning_efforts: ['low'],
                  },
                ],
              },
            ],
          },
        },
      }) as unknown as Catalog
  )
  const [fingerprint] = useState(() => modelTestFingerprint(draft, 'llm', 'p', 'm'))
  const profile = draft.services.llm.profiles[0]
  const model = profile.models[0]
  const result: ModelTestState = {
    fingerprint,
    state: testState,
    message: testState === 'failed' ? 'Generation failed' : 'OK',
    logs: '',
    reasoning: {
      levels,
      selectableLevels,
      source: levels === null ? 'unknown' : 'provider_metadata',
    },
  }
  // Match the existing settings harness: the mocked hook must see this render's draft.
  // eslint-disable-next-line react-hooks/immutability
  mocks.settings = {
    draft,
    modelTests: { [modelTestKey('llm', 'p', 'm')]: result },
    testRunning: null,
    runDetailedTest: vi.fn(),
    mutateCatalog: (change: (value: Catalog) => void) =>
      setDraft(old => {
        const next = structuredClone(old)
        change(next)
        return next
      }),
  }
  return (
    <>
      <ModelTestPanel service="llm" profile={profile} model={model} />
      <output aria-label="Enabled levels">{model.enabled_reasoning_efforts?.join(',')}</output>
      <output aria-label="Default effort">{model.reasoning_effort}</output>
      <button
        onClick={() =>
          setDraft(old => {
            const next = structuredClone(old)
            next.services.llm.profiles[0].models[0].model = 'different'
            return next
          })
        }
      >
        Change model ID
      </button>
    </>
  )
}

it('offers metadata for explicit adoption without changing the model default', () => {
  render(<Harness levels={['high', 'xhigh']} />)
  expect(screen.getByText('Provider model metadata')).toBeTruthy()
  expect(screen.getByLabelText('Enabled levels')).toHaveTextContent('low')
  fireEvent.click(screen.getByRole('button', { name: 'Use detected levels' }))
  expect(screen.getByLabelText('Enabled levels')).toHaveTextContent('high,xhigh')
  expect(screen.getByLabelText('Default effort')).toHaveTextContent('medium')
  expect(screen.getByRole('button', { name: 'Already applied' })).toBeDisabled()
})

it('keeps unknown distinct from an explicitly empty supported list', () => {
  const view = render(<Harness levels={null} />)
  expect(
    screen.getByText('Reasoning levels could not be determined. Keep your manual selection.')
  ).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Use detected levels' })).toBeNull()
  expect(screen.getByLabelText('Enabled levels')).toHaveTextContent('low')
  view.unmount()
  render(<Harness levels={[]} />)
  expect(screen.getByText('No configurable reasoning levels reported.')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Use detected levels' }))
  expect(screen.getByLabelText('Enabled levels').textContent).toBe('')
})

it('invalidates results when the model changes', () => {
  render(<Harness levels={['high']} />)
  fireEvent.click(screen.getByRole('button', { name: 'Change model ID' }))
  expect(screen.queryByRole('button', { name: 'Use detected levels' })).toBeNull()
  expect(screen.getByLabelText('Enabled levels')).toHaveTextContent('low')
})

it('does not adopt metadata into a read-only profile', () => {
  render(<Harness levels={['high']} locked />)
  expect(screen.getByRole('button', { name: 'Use detected levels' })).toBeDisabled()
})

it('shows declared levels but only adopts levels representable by the transport', () => {
  render(<Harness levels={['low', 'medium', 'high']} selectableLevels={['high']} />)
  expect(screen.getByText('Low', { exact: true })).toBeTruthy()
  expect(screen.getByText('Medium', { exact: true })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Use detected levels' }))
  expect(screen.getByLabelText('Enabled levels')).toHaveTextContent('high')
})

it('cannot clear manual levels when declared levels have no transport mapping', () => {
  render(<Harness levels={['low', 'medium']} selectableLevels={[]} />)
  expect(screen.getByRole('button', { name: 'Use detected levels' })).toBeDisabled()
  expect(screen.getByLabelText('Enabled levels')).toHaveTextContent('low')
})

it('shows provider-specific levels without adopting unsupported application values', () => {
  render(
    <Harness levels={['low', 'future', 'constructor', '__proto__']} selectableLevels={['low']} />
  )
  expect(screen.getByText('future', { exact: true })).toBeTruthy()
  expect(screen.getByText('constructor', { exact: true })).toBeTruthy()
  expect(screen.getByText('__proto__', { exact: true })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Already applied' })).toBeDisabled()
  expect(screen.getByLabelText('Enabled levels')).toHaveTextContent('low')
})

it('can adopt independent metadata without hiding a generation failure', () => {
  render(<Harness levels={['high']} selectableLevels={['high']} testState="failed" />)
  expect(screen.getByText('Generation failed')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Use detected levels' }))
  expect(screen.getByLabelText('Enabled levels')).toHaveTextContent('high')
  expect(screen.getByText('Generation failed')).toBeTruthy()
  expect(screen.queryByText('Model responded successfully')).toBeNull()
})
