import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import PageIndexOssSettingsForm from '@/components/knowledge/PageIndexOssSettingsForm'

const api = vi.hoisted(() => ({ get: vi.fn(), update: vi.fn() }))
vi.mock('@/features/knowledge/api/engines', () => ({
  getPageIndexConfig: api.get,
  updatePageIndexConfig: api.update,
}))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

beforeEach(() => {
  api.get.mockResolvedValue({ api_key_set: false, configured: false, oss_summary_concurrency: 2 })
  api.update.mockImplementation(async value => value)
})

it('loads, saves, and resets the Flash limit without a Cloud API key', async () => {
  const changed = vi.fn()
  render(<PageIndexOssSettingsForm onChanged={changed} />)
  const input = screen.getByRole('spinbutton', { name: 'Flash concurrency per stage' })
  await waitFor(() => expect(input).toHaveValue(2))
  fireEvent.change(input, { target: { value: '3' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  await waitFor(() => expect(api.update).toHaveBeenCalledWith({ oss_summary_concurrency: 3 }))
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(1))
  fireEvent.change(input, { target: { value: '' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  await waitFor(() =>
    expect(api.update).toHaveBeenLastCalledWith({ oss_summary_concurrency: null })
  )
})

it('rejects a fractional limit before sending a settings request', async () => {
  render(<PageIndexOssSettingsForm />)
  const input = screen.getByRole('spinbutton')
  await waitFor(() => expect(input).toBeEnabled())
  fireEvent.change(input, { target: { value: '1.5' } })
  fireEvent.submit(input.closest('form')!)
  expect(await screen.findByRole('alert')).toHaveTextContent('Enter a whole number')
  expect(api.update).not.toHaveBeenCalled()
})

it('keeps saving disabled when settings could not be loaded', async () => {
  api.get.mockRejectedValue(new Error('Unable to read settings'))
  render(<PageIndexOssSettingsForm />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to read settings')
  expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()
})

it('retains the entered limit and displays a failed save', async () => {
  api.update.mockRejectedValue(new Error('Save failed'))
  render(<PageIndexOssSettingsForm />)
  const input = screen.getByRole('spinbutton')
  await waitFor(() => expect(input).toBeEnabled())
  fireEvent.change(input, { target: { value: '4' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Save failed')
  expect(input).toHaveValue(4)
  expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled()
})
