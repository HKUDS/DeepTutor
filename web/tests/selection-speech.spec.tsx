import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createRef } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PlayAudioButton } from '@/components/voice/SpeechButton'
import SelectionActions from '@/features/chat/components/SelectionActions'
import { SelectionSpeechToolbar } from '@/components/voice/SelectionSpeechToolbar'

const mock = vi.hoisted(() => ({ fetch: vi.fn(), notify: vi.fn(), audio: [] as MockAudio[] }))
vi.mock('@/lib/api', () => ({
  apiUrl: (url: string) => url,
  apiFetch: (...args: unknown[]) => mock.fetch(...args),
}))
vi.mock('@/lib/notifications', () => ({ notify: mock.notify }))
vi.mock('@/hooks/useVoiceAutoplay', () => ({
  useVoiceAutoplay: () => ({ autoplayEnabled: false }),
}))
vi.mock('@/components/chat/home/ResponderList', () => ({ default: () => null }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (s: string) => s }) }))

class MockAudio {
  src = ''
  onended: (() => void) | null = null
  onerror: (() => void) | null = null
  play = vi.fn(async () => undefined)
  pause = vi.fn()
  load = vi.fn()
  constructor(src: string) {
    this.src = src
    mock.audio.push(this)
  }
}

beforeEach(() => {
  mock.fetch.mockReset()
  mock.notify.mockReset()
  mock.audio.length = 0
  vi.stubGlobal('Audio', MockAudio)
  vi.stubGlobal(
    'URL',
    Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:speech'), revokeObjectURL: vi.fn() })
  )
  mock.fetch.mockResolvedValue({
    ok: true,
    blob: async () => new Blob(['test audio'], { type: 'audio/mpeg' }),
  })
})

describe('selected-text speech', () => {
  it('exposes a nearby speech-only action in a learning transcript, even for one character', async () => {
    const rootRef = createRef<HTMLDivElement>()
    render(
      <>
        <div ref={rootRef}>
          <p data-testid="lesson">I am learning.</p>
        </div>
        <SelectionSpeechToolbar rootRef={rootRef} />
      </>
    )
    const range = document.createRange()
    range.setStart(screen.getByTestId('lesson').firstChild!, 0)
    range.setEnd(screen.getByTestId('lesson').firstChild!, 1)
    Object.defineProperty(range, 'getClientRects', {
      value: () => [{ left: 100, right: 110, top: 130, bottom: 150, width: 10, height: 20 }],
    })
    window.getSelection()!.removeAllRanges()
    window.getSelection()!.addRange(range)
    fireEvent.mouseUp(screen.getByTestId('lesson'))
    const toolbar = await screen.findByRole('toolbar', { name: 'Selected text' })
    expect(toolbar.style.left).toBe('70px')
    expect(mock.fetch).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Read aloud' }))
    await waitFor(() => expect(mock.fetch).toHaveBeenCalledTimes(1))
    expect(JSON.parse(mock.fetch.mock.calls[0][1].body)).toEqual({ text: 'I' })
    await waitFor(() => expect(mock.audio[0].src).toBe('blob:speech'))
    await act(async () => {
      window.getSelection()!.removeAllRanges()
      document.dispatchEvent(new Event('selectionchange'))
    })
    expect(screen.queryByRole('toolbar')).not.toBeInTheDocument()
    expect(mock.audio[0].pause).toHaveBeenCalled()
  })

  it('only submits the selected text, never starts a chat turn, and preserves selection', async () => {
    const ask = vi.fn()
    const quote = vi.fn()
    render(
      <SelectionActions
        text="Only this sentence."
        anchor={{ left: 40, right: 140, top: 180, bottom: 200 }}
        agents={[]}
        onAsk={ask}
        onAddToChat={quote}
        onDismiss={vi.fn()}
      />
    )
    const button = screen.getByRole('button', { name: 'Read aloud' })
    expect(fireEvent.pointerDown(button)).toBe(false)
    fireEvent.click(button)
    await waitFor(() => expect(mock.fetch).toHaveBeenCalledTimes(1))
    const [url, init] = mock.fetch.mock.calls[0]
    expect(url).toBe('/api/voice/tts')
    expect(JSON.parse(init.body)).toEqual({ text: 'Only this sentence.' })
    expect(ask).not.toHaveBeenCalled()
    expect(quote).not.toHaveBeenCalled()
    await screen.findByRole('button', { name: 'Stop' })
  })

  it('uses the current provider settings when replaying a completed selection', async () => {
    render(
      <PlayAudioButton
        content="Replay this particular selection."
        autoPlayFresh={false}
        selection
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Read aloud' }))
    await waitFor(() => expect(mock.audio[0].src).toBe('blob:speech'))
    await act(async () => mock.audio[0].onended?.())
    fireEvent.click(screen.getByRole('button', { name: 'Read aloud' }))
    await waitFor(() => expect(mock.audio).toHaveLength(2))
    await waitFor(() => expect(mock.audio[1].src).toBe('blob:speech'))
    expect(mock.fetch).toHaveBeenCalledTimes(2)
    expect(JSON.parse(mock.fetch.mock.calls[1][1].body)).toEqual({
      text: 'Replay this particular selection.',
    })
  })

  it('stops pending synthesis and ignores a late response', async () => {
    let resolve!: (response: unknown) => void
    mock.fetch.mockImplementation(
      () =>
        new Promise(r => {
          resolve = r
        })
    )
    render(
      <PlayAudioButton content="Cancel this pending request." autoPlayFresh={false} selection />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Read aloud' }))
    await waitFor(() => expect(mock.fetch).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    expect(mock.fetch.mock.calls[0][1].signal.aborted).toBe(true)
    await act(async () => resolve({ ok: true, blob: async () => new Blob(['late']) }))
    expect(mock.audio[0].src).not.toBe('blob:speech')
    expect(mock.notify).not.toHaveBeenCalled()
  })

  it('stops the old selection when another selection or full-message audio starts', async () => {
    render(
      <>
        <PlayAudioButton content="First selection." autoPlayFresh={false} selection />
        <PlayAudioButton content="Whole message." autoPlayFresh={false} />
      </>
    )
    fireEvent.click(screen.getByRole('button', { name: 'Read aloud' }))
    await waitFor(() => expect(mock.audio[0].src).toBe('blob:speech'))
    fireEvent.click(screen.getByRole('button', { name: 'Play aloud' }))
    await waitFor(() => expect(mock.audio).toHaveLength(2))
    expect(mock.audio[0].pause).toHaveBeenCalled()
    await waitFor(() => expect(mock.audio[1].src).toBe('blob:speech'))
  })

  it('reports provider errors instead of silently pretending to play', async () => {
    mock.fetch.mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => ({ detail: 'Speech service unavailable' }),
    })
    render(<PlayAudioButton content="Provider error selection." autoPlayFresh={false} selection />)
    fireEvent.click(screen.getByRole('button', { name: 'Read aloud' }))
    await waitFor(() =>
      expect(mock.notify).toHaveBeenCalledWith('Speech service unavailable', { tone: 'error' })
    )
    expect(screen.getByRole('button', { name: 'Read aloud' })).toBeVisible()
  })
})
