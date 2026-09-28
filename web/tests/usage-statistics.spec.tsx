import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import UsageSettingsSection from '@/features/settings/sections/UsageSettingsSection'
import UsageActivity from '@/features/settings/components/UsageActivity'
import { activityCalendar, usageYear, type UsageStatistics } from '@/lib/usage-statistics'
const mocks = vi.hoisted(() => ({ fetch: vi.fn(), push: vi.fn(), search: 'year=2024' }))
vi.mock('@/lib/usage-statistics', async original => ({ ...await original<object>(), fetchUsageStatistics: mocks.fetch }))
vi.mock('next/navigation', () => ({ useRouter: () => ({push: mocks.push}), useSearchParams: () => new URLSearchParams(mocks.search) }))
vi.mock('@/components/settings/shared', () => ({ SettingsPageHeader: ({title}: {title: string}) => <h1>{title}</h1> }))
vi.mock('react-i18next', () => ({useTranslation: () => ({t: (key: string, vars?: Record<string, unknown>) => key.replace(/{{(.*?)}}/g, (_, k) => String(vars?.[k] ?? k)), i18n: {language: 'en'}})}))
const day = {date: '2024-02-29', turns: 3, total_calls: 5, total_tokens: 200, tracked_turns: 3}
const totals = {total_tokens: 200, prompt_tokens: 180, completion_tokens: 20, total_calls: 5, cache_read_input_tokens: 90, cache_creation_input_tokens: 0, cache_input_tokens: 180, cache_reported_calls: 5, cache_hit_rate: .5, ttft_seconds: 1.2, tokens_per_second: 40, duration_seconds: 8, estimated_calls: 0}
const data: UsageStatistics = {year: 2024, timezone: 'UTC', totals, days: activityCalendar([day], 2024).dates, models: [{...totals, provider: 'zhipu', model: 'glm-test'}], active_days: 1, sessions: 1, turns: 3, tracked_turns: 3, updated_at: 1709164800}
beforeEach(() => {mocks.search = 'year=2024'; mocks.fetch.mockReset(); mocks.push.mockReset()})
it('builds a Monday-first leap-year calendar without losing days', () => {
  const calendar = activityCalendar([day], 2024)
  expect(calendar.offset).toBe(0)
  expect(calendar.dates).toHaveLength(366)
  expect(calendar.weeks.flat().filter(Boolean)).toHaveLength(366)
  expect(calendar.dates.find(value => value.date === '2024-02-29')?.turns).toBe(3)
  expect(usageYear('nonsense', 2026)).toBe(2026)
  expect(usageYear('2027', 2026)).toBe(2026)
})
it('supports day selection and keyboard movement across weeks', () => {
  render(<UsageActivity days={data.days} year={2024} activeDays={1} turns={3} />)
  const leap = screen.getByRole('button', {name: /2024-02-29 · 3 activities/})
  fireEvent.click(leap)
  expect(leap).toHaveAttribute('aria-pressed', 'true')
  fireEvent.keyDown(leap, {key: 'ArrowRight'})
  expect(screen.getByRole('button', {name: /2024-03-07/})).toHaveFocus()
})
it('loads yearly totals and persists navigation in the URL', async () => {
  mocks.fetch.mockResolvedValue(data)
  render(<UsageSettingsSection />)
  expect(await screen.findByText('glm-test')).toBeVisible()
  expect(screen.getAllByText('50.0%')).toHaveLength(2)
  fireEvent.click(screen.getByRole('button', {name: 'Previous year'}))
  expect(mocks.push).toHaveBeenCalledWith('/settings/usage?year=2023', {scroll: false})
})
it('shows errors and retries instead of presenting failure as zero usage', async () => {
  mocks.fetch.mockRejectedValueOnce(new Error('offline')).mockResolvedValue(data)
  render(<UsageSettingsSection />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load usage statistics.')
  expect(screen.queryByText('No recorded model usage for this year.')).toBeNull()
  fireEvent.click(screen.getByRole('button', {name: 'Retry'}))
  expect(await screen.findByText('glm-test')).toBeVisible()
})
it('discards a late response after the requested year changes', async () => {
  let finish: (data: UsageStatistics) => void = () => {}
  mocks.fetch.mockImplementationOnce(() => new Promise(resolve => {finish = resolve})).mockResolvedValue({...data, year: 2023, models: []})
  const view = render(<UsageSettingsSection />)
  mocks.search = 'year=2023'
  view.rerender(<UsageSettingsSection />)
  expect(await screen.findByText('No recorded model usage for this year.')).toBeVisible()
  finish(data)
  await waitFor(() => expect(screen.queryByText('glm-test')).toBeNull())
})

it('shows recovered model rows and retains unrecoverable history outside the model table', async () => {
  mocks.fetch.mockResolvedValue({
    ...data,
    models: [...data.models, {...totals, model: '', provider: ''}],
  })
  render(<UsageSettingsSection />)
  expect(await screen.findByText('glm-test')).toBeVisible()
  expect(screen.queryByText('Model not recorded')).toBeNull()
  expect(screen.getByText('Historical usage without recoverable model details')).toBeVisible()
  expect(screen.getByText('200 tokens')).toBeVisible()
})
