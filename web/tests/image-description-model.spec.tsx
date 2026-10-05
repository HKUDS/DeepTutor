import React, { useState } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { ImageDescriptionModelSetting } from '@/features/settings/sections/ImageDescriptionModelSetting'
import { applyExtensionPayload } from '@/lib/settings-extensions'

const mocks = vi.hoisted(() => ({ options: vi.fn(), fetch: vi.fn() }))
vi.mock('@/lib/llm-options', () => ({ listLLMOptions: () => mocks.options() }))
vi.mock('@/lib/api', () => ({
  apiUrl: (value: string) => value,
  apiFetch: (...args: unknown[]) => mocks.fetch(...args),
}))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

beforeEach(() => {
  mocks.options.mockResolvedValue({
    options: [
      {
        profile_id: 'vision',
        model_id: 'image',
        profile_name: 'Pictures',
        model_name: 'Vision',
        supports_vision: true,
      },
      {
        profile_id: 'chat',
        model_id: 'text',
        profile_name: 'Chat',
        model_name: 'Text',
        supports_vision: false,
      },
    ],
  })
  mocks.fetch.mockResolvedValue({ ok: true })
})

function Harness() {
  const [value, setValue] = useState<{ profile_id: string; model_id: string } | null>(null)
  return (
    <>
      <ImageDescriptionModelSetting value={value} disabled={false} onChange={setValue} />
      <button
        onClick={() =>
          applyExtensionPayload('document-parsing', {
            engine: 'text_only',
            engines: { mineru: { api_token: 'must-not-overwrite' }, text_only: {} },
            image_description_model: value,
          })
        }
      >
        Apply
      </button>
    </>
  )
}

it('lists vision models and sends explicit IDs or null without overwriting the MinerU draft', async () => {
  render(<Harness />)
  await screen.findByRole('option', { name: 'Pictures / Vision' })
  expect(screen.queryByRole('option', { name: 'Chat / Text' })).toBeNull()
  fireEvent.change(screen.getByLabelText('Image description model'), {
    target: { value: '["vision","image"]' },
  })
  fireEvent.click(screen.getByText('Apply'))
  await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(1))
  expect(JSON.parse(mocks.fetch.mock.calls[0][1].body)).toEqual({
    engine: 'text_only',
    engines: { text_only: {} },
    image_description_model: { profile_id: 'vision', model_id: 'image' },
  })
  fireEvent.change(screen.getByLabelText('Image description model'), { target: { value: '' } })
  fireEvent.click(screen.getByText('Apply'))
  await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(2))
  expect(JSON.parse(mocks.fetch.mock.calls[1][1].body).image_description_model).toBeNull()
})

it('keeps an unavailable saved selection visible instead of silently choosing the main model', async () => {
  render(
    <ImageDescriptionModelSetting
      value={{ profile_id: 'deleted', model_id: 'gone' }}
      disabled={false}
      onChange={vi.fn()}
    />
  )
  await screen.findByRole('option', { name: 'Pictures / Vision' })
  expect(screen.getByLabelText('Image description model')).toHaveValue('["deleted","gone"]')
  expect(screen.getByRole('option', { name: 'Selected model unavailable' })).toBeDisabled()
})

it('reports a model-list error while retaining the ability to reset', async () => {
  mocks.options.mockRejectedValue(new Error('unavailable'))
  const onChange = vi.fn()
  render(
    <ImageDescriptionModelSetting
      value={{ profile_id: 'saved', model_id: 'model' }}
      disabled={false}
      onChange={onChange}
    />
  )
  await screen.findByRole('alert')
  fireEvent.change(screen.getByLabelText('Image description model'), { target: { value: '' } })
  expect(onChange).toHaveBeenCalledWith(null)
})
