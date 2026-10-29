import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import StarterSuggestions from '@/components/chat/home/StarterSuggestions'

const fetcher = vi.hoisted(() => vi.fn())
vi.mock('@/lib/api', () => ({ apiFetch: fetcher, apiUrl: (path: string) => path }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
const response = (payload: object) => ({ ok: true, json: async () => payload })
beforeEach(() => fetcher.mockReset())
afterEach(() => vi.useRealTimers())

it('distinguishes missing learning material from a provider failure and allows retry', async () => {
  fetcher.mockResolvedValue(response({ suggestions: [], stale: false, status: 'error' }))
  render(<StarterSuggestions onPick={vi.fn()} workspaceId="ws_a" />)
  // A failure the learner did not ask about leaves only the way to try again.
  await screen.findByRole('button', { name: 'Suggest what to explore next' })
  expect(screen.queryByRole('status')).toBeNull()
  fetcher.mockResolvedValue(response({ suggestions: [], stale: false, status: 'no-material' }))
  fireEvent.click(screen.getByRole('button', { name: 'Suggest what to explore next' }))
  expect(await screen.findByText('Not enough history yet — have a conversation first.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Suggest what to explore next' })).toBeNull()
  expect(fetcher.mock.calls[1][0]).toBe('/api/dashboard/suggestions/refresh?dt_workspace=ws_a')
})

it('leaves the spinner after a manual request times out', async () => {
  fetcher.mockResolvedValueOnce(response({ suggestions: [], stale: false, status: 'error' }))
  render(<StarterSuggestions onPick={vi.fn()} />)
  await screen.findByRole('button', { name: 'Suggest what to explore next' })
  const deadline = new AbortController()
  vi.spyOn(AbortSignal, 'timeout').mockReturnValue(deadline.signal)
  fetcher.mockImplementationOnce((_url, init) => new Promise((_resolve, reject) => {
    init.signal.addEventListener('abort', () => reject(new Error('timeout')))
  }))
  fireEvent.click(screen.getByRole('button', { name: 'Suggest what to explore next' }))
  expect(screen.getByText('Finding what to explore next...')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Suggest what to explore next' })).toBeNull()
  await act(async () => deadline.abort())
  expect(screen.getByRole('button', { name: 'Suggest what to explore next' })).toBeEnabled()
  expect(screen.getByRole('status')).toHaveTextContent('Suggestions could not be generated')
})

it('cancels a stale response when the task workspace changes', async () => {
  let finish: (value: unknown) => void = () => {}
  fetcher.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const view = render(<StarterSuggestions onPick={vi.fn()} workspaceId="ws_a" />)
  fetcher.mockResolvedValue(response({ suggestions: [{ label: 'B suggestion', prompt: 'B' }], stale: false, status: 'ready' }))
  view.rerender(<StarterSuggestions onPick={vi.fn()} workspaceId="ws_b" />)
  await screen.findByText('B suggestion')
  await act(async () => finish(response({ suggestions: [{ label: 'A suggestion', prompt: 'A' }], stale: false })))
  expect(screen.queryByText('A suggestion')).toBeNull()
  expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true)
})

it('stops polling as soon as the backend reports a terminal empty result', async () => {
  vi.useFakeTimers()
  fetcher.mockResolvedValueOnce(response({ suggestions: [], stale: true, status: 'working' }))
  fetcher.mockResolvedValueOnce(response({ suggestions: [], stale: false, status: 'no-material' }))
  render(<StarterSuggestions onPick={vi.fn()} />)
  await act(async () => { await vi.advanceTimersByTimeAsync(3500) })
  // Nothing to suggest, and nobody asked: the line stays quiet.
  expect(screen.queryByText('Finding what to explore next...')).toBeNull()
  expect(screen.queryByText('Not enough history yet — have a conversation first.')).toBeNull()
  await act(async () => { await vi.advanceTimersByTimeAsync(20000) })
  expect(fetcher).toHaveBeenCalledTimes(2)
})

it('asks the backend for a new suggestion on every refresh', async () => {
  fetcher.mockResolvedValueOnce(response({ suggestions: [{ label: 'First', prompt: '1' }], stale: false, status: 'ready' }))
  render(<StarterSuggestions onPick={vi.fn()} />)
  await screen.findByRole('button', { name: /First$/ })
  fetcher.mockResolvedValueOnce(response({ suggestions: [{ label: 'Second', prompt: '2' }], stale: false, status: 'ready' }))
  fireEvent.click(screen.getByRole('button', { name: 'Suggest something else' }))
  expect(await screen.findByRole('button', { name: /Second$/ })).toBeInTheDocument()
  expect(screen.queryByText('First')).toBeNull()
  expect(fetcher).toHaveBeenCalledTimes(2)
  expect(fetcher.mock.calls[1][0]).toMatch(/^\/api\/dashboard\/suggestions\/refresh/)
  expect(fetcher.mock.calls[1][1].method).toBe('POST')
})

it('fills the composer with the picked request instead of sending it', async () => {
  fetcher.mockResolvedValue(response({ suggestions: [{ label: 'Why BM25 works', prompt: 'Explain BM25' }], stale: false, status: 'ready' }))
  const onPick = vi.fn()
  render(<StarterSuggestions onPick={onPick} />)
  fireEvent.click(await screen.findByRole('button', { name: /Why BM25 works/ }))
  expect(onPick).toHaveBeenLastCalledWith('Explain BM25')
  // Ways to start stay closed until one is chosen, and close once used.
  expect(screen.queryByRole('button', { name: /starters\.solve\.2/ })).toBeNull()
  const solve = screen.getByRole('button', { name: 'starters.solve' })
  fireEvent.click(solve)
  expect(solve).toHaveAttribute('aria-expanded', 'true')
  fireEvent.click(screen.getByRole('button', { name: /starters\.solve\.2/ }))
  expect(onPick).toHaveBeenLastCalledWith('starters.solve.2.prompt')
  expect(solve).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByRole('button', { name: /starters\.solve\.2/ })).toBeNull()
})
