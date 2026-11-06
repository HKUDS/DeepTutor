import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import BookChatPanel from '@/app/(workspace)/learning/books/components/BookChatPanel'
import type { StreamEvent } from '@/features/chat/model/protocol'
import type { Book, Page } from '@/lib/book-types'

const fixture = vi.hoisted(() => ({
  emit: undefined as ((event: StreamEvent) => void) | undefined,
  getSession: vi.fn(),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))
vi.mock('@/context/AppShellContext', () => ({
  useAppShell: () => ({ language: 'en' }),
}))
vi.mock('@/lib/attachment-limits', () => ({
  useAttachmentLimits: () => ({}),
}))
vi.mock('@/components/common/AssistantResponse', () => ({
  default: ({ content }: { content: string }) => <div>{content}</div>,
}))
vi.mock('@/shared/ui/Tooltip', () => ({
  default: ({ children }: { children: React.ReactNode }) => children,
}))
vi.mock('@/lib/session-api', () => ({ getSession: fixture.getSession }))
vi.mock('@/features/chat/transport/UnifiedTurnClient', () => ({
  UnifiedTurnClient: class {
    connected = true
    constructor(emit: (event: StreamEvent) => void) {
      fixture.emit = emit
    }
    connect() {}
    disconnect() {}
    send() {}
  },
}))

const book = { id: 'book', language: 'en', knowledge_bases: [] } as unknown as Book
const page = { id: 'page', title: 'Chapter' } as Page
let height: number
let top: number

beforeEach(() => {
  height = 1000
  top = 0
  fixture.emit = undefined
  fixture.getSession.mockResolvedValue({
    messages: [
      { role: 'user', content: 'Earlier question' },
      { role: 'assistant', content: 'Earlier answer' },
    ],
  })
  vi.spyOn(Element.prototype, 'clientHeight', 'get').mockReturnValue(200)
  vi.spyOn(Element.prototype, 'scrollHeight', 'get').mockImplementation(() => height)
  vi.spyOn(Element.prototype, 'scrollTop', 'get').mockImplementation(() => top)
  vi.spyOn(Element.prototype, 'scrollTop', 'set').mockImplementation(value => {
    top = Math.max(0, Math.min(value, height - 200))
  })
})

function emit(type: StreamEvent['type'], content = 'Next streamed chunk') {
  act(() =>
    fixture.emit?.({
      type,
      content,
      source: 'chat',
      stage: 'responding',
      metadata: {},
      timestamp: 0,
    })
  )
}

function sendQuestion() {
  const input = screen.getByRole('textbox')
  fireEvent.change(input, { target: { value: 'New question' } })
  fireEvent.submit(input.closest('form')!)
}

async function startStream() {
  const view = render(
    <BookChatPanel book={book} page={page} open onClose={() => {}} initialSessionId="session" />
  )
  await screen.findByText('Earlier answer')
  expect(top).toBe(800)
  sendQuestion()
  await waitFor(() => expect(fixture.emit).toBeTypeOf('function'))
  return { ...view, scroller: view.container.querySelector('[data-chat-scroll-root]')! }
}

it.each(['thinking', 'content'] as const)(
  "preserves a reader's position during streamed %s events",
  async type => {
    const { scroller } = await startStream()
    fireEvent.wheel(scroller, { deltaY: -120 })
    top = 200
    fireEvent.scroll(scroller)
    height = 1300
    emit(type)
    expect(top).toBe(200)
  }
)

it('follows streamed output while the reader stays at the bottom', async () => {
  await startStream()
  height = 1300
  emit('content')
  expect(top).toBe(1100)
})

it('resumes following when the reader scrolls back to the bottom', async () => {
  const { scroller } = await startStream()
  fireEvent.wheel(scroller, { deltaY: -120 })
  top = 200
  fireEvent.scroll(scroller)
  emit('thinking')
  top = 800
  fireEvent.scroll(scroller)
  height = 1300
  emit('content')
  expect(top).toBe(1100)
})

it('follows a newly sent question after the reader left the live end', async () => {
  const { scroller } = await startStream()
  fireEvent.wheel(scroller, { deltaY: -120 })
  top = 200
  fireEvent.scroll(scroller)
  emit('done', '')
  sendQuestion()
  expect(top).toBe(800)
  height = 1300
  emit('content')
  expect(top).toBe(1100)
})

it("starts following again when switching to another page's conversation", async () => {
  const { scroller, rerender } = await startStream()
  fireEvent.wheel(scroller, { deltaY: -120 })
  top = 200
  fireEvent.scroll(scroller)
  rerender(
    <BookChatPanel
      book={book}
      page={{ ...page, id: 'another-page' }}
      open
      onClose={() => {}}
      initialSessionId="another-session"
    />
  )
  await waitFor(() => expect(fixture.getSession).toHaveBeenCalledWith('another-session'))
  await screen.findByText('Earlier answer')
  expect(top).toBe(800)
})

it('listens for upward gestures after closing and reopening the panel', async () => {
  const { rerender } = await startStream()
  emit('done', '')
  rerender(
    <BookChatPanel
      book={book}
      page={page}
      open={false}
      onClose={() => {}}
      initialSessionId="session"
    />
  )
  rerender(
    <BookChatPanel book={book} page={page} open onClose={() => {}} initialSessionId="session" />
  )
  sendQuestion()
  const scroller = document.querySelector('[data-chat-scroll-root]')!
  fireEvent.wheel(scroller, { deltaY: -120 })
  height = 1300
  emit('content')
  expect(top).toBe(800)
})
