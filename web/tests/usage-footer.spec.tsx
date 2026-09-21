import React from 'react'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { UsageFooter } from '@/features/chat/messages/UsageFooter'
import {
  combineUsage,
  cumulativeMessageUsage,
  messageUsage,
  type UsageSummary,
} from '@/features/chat/messages/usage-summary'
import type { StreamEvent } from '@/features/chat/model/protocol'
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, vars?: Record<string, unknown>) =>
      key.replace(/{{(.*?)}}/g, (_, k) => String(vars?.[k] ?? k)),
    i18n: { language: 'en' },
  }),
}))
const turn: UsageSummary = {
  total_tokens: 140,
  prompt_tokens: 100,
  completion_tokens: 40,
  total_calls: 1,
  cache_read_input_tokens: 80,
  cache_input_tokens: 100,
  cache_reported_calls: 1,
  cache_hit_rate: 0.8,
  ttft_seconds: 2,
  ttft_calls: 1,
  generation_seconds: 2,
  timed_completion_tokens: 40,
  tokens_per_second: 20,
  call_details: [
    {
      model: 'glm-5.3-flash',
      provider: 'zhipu',
      total_tokens: 140,
      prompt_tokens: 100,
      completion_tokens: 40,
      cache_read_input_tokens: 80,
      cache_hit_rate: 0.8,
      ttft_seconds: 2,
      tokens_per_second: 20,
    },
  ],
}
const other = {
  ...turn,
  total_tokens: 1040,
  prompt_tokens: 1000,
  cache_input_tokens: 1000,
  cache_read_input_tokens: 100,
  cache_hit_rate: 0.1,
  ttft_seconds: 4,
  ttft_calls: 2,
  generation_seconds: 8,
  timed_completion_tokens: 160,
}
const event = (type: string, metadata: Record<string, unknown>) =>
  ({ type, metadata }) as StreamEvent
it('weights cache and TPS by tokens/time, TTFT by calls', () => {
  const all = combineUsage([turn, other])
  expect(all.cache_hit_rate).toBeCloseTo(180 / 1100)
  expect(all.ttft_seconds).toBeCloseTo(10 / 3)
  expect(all.tokens_per_second).toBe(20)
})
it('counts snapshots once, preserves merged turns and old usage', () => {
  expect(
    messageUsage([
      event('result', { metadata: { usage_summary: turn } }),
      event('done', { usage_summary: turn }),
      event('result', { metadata: { usage_summary: other } }),
      event('done', { usage_summary: other }),
    ])?.total_tokens
  ).toBe(1180)
  const old = messageUsage([
    event('result', { metadata: { cost_summary: { total_tokens: 200, total_calls: 2 } } }),
  ])
  expect(old?.total_tokens).toBe(200)
  expect(old?.cache_hit_rate).toBeNull()
})
it('opens details, switches scope and requests, dismisses with Escape', () => {
  render(<UsageFooter turn={turn} session={combineUsage([turn, other])} />)
  const trigger = screen.getByRole('button', { name: /140 tokens/ })
  expect(trigger).not.toHaveTextContent('$')
  fireEvent.click(trigger)
  const panel = screen.getByRole('dialog')
  expect(within(panel).getByText('140')).toBeVisible()
  expect(within(panel).getByText('20.0 tok\/s')).toBeVisible()
  fireEvent.click(within(panel).getByRole('button', { name: 'This session' }))
  expect(within(panel).getByText('1,180')).toBeVisible()
  expect(within(panel).queryByRole('combobox')).toBeNull()
  expect(panel).not.toHaveTextContent('Cache hits are weighted')
  expect(within(panel).getAllByRole('term')).toHaveLength(10)
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(trigger).toHaveFocus()
})
it('keeps unknown cache unknown and closes on outside pointer', () => {
  render(<UsageFooter turn={{ total_tokens: 50 }} session={{ total_tokens: 50 }} />)
  fireEvent.click(screen.getByRole('button', { name: /50 tokens/ }))
  expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  fireEvent.pointerDown(document.body)
  expect(screen.queryByRole('dialog')).toBeNull()
})

it('cumulative totals stop at the selected reply, not the last session reply', () => {
  const messages = [turn, other, turn].map(usage => ({
    role: 'assistant',
    events: [event('done', { usage_summary: usage })],
  }))
  const totals = cumulativeMessageUsage(messages)
  expect(totals.map(usage => usage.total_tokens)).toEqual([140, 1180, 1320])
  expect(totals[0].cache_hit_rate).toBe(0.8)
})
