import React from 'react'
import { act, render, screen } from '@testing-library/react'
import { createInstance } from 'i18next'
import { I18nextProvider } from 'react-i18next'
import { expect, it, vi } from 'vitest'
import { AddProviderPanel } from '@/components/settings/AddProviderPanel'

it('updates provider originals immediately when the interface language changes', async () => {
  const i18n = createInstance()
  await i18n.init({
    lng: 'en',
    fallbackLng: 'en',
    resources: { en: { translation: {} }, zh: { translation: {} }, fr: { translation: {} } },
  })
  const options = [{ value: 'deepseek', label: 'DeepSeek', services: ['llm' as const] }]
  render(
    <I18nextProvider i18n={i18n}>
      <AddProviderPanel options={options} vendor="" onVendor={vi.fn()} onCreate={vi.fn()} onCancel={vi.fn()} />
    </I18nextProvider>,
  )
  expect(screen.getByRole('radio', { name: 'DeepSeek' })).toBeInTheDocument()
  await act(async () => { await i18n.changeLanguage('zh') })
  expect(screen.getByRole('radio', { name: 'DeepSeek（深度求索）' })).toBeInTheDocument()
  await act(async () => { await i18n.changeLanguage('fr') })
  expect(screen.getByRole('radio', { name: 'DeepSeek' })).toBeInTheDocument()
  expect(screen.queryByText('DeepSeek（深度求索）')).not.toBeInTheDocument()
  await act(async () => { await i18n.changeLanguage('zh') })
  expect(screen.getByRole('radio', { name: 'DeepSeek（深度求索）' })).toBeInTheDocument()
  expect(options[0].label).toBe('DeepSeek')
})
