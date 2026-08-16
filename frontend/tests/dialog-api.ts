import { Page } from '@playwright/test'

export const MOCK_SESSION_ID = '11111111-1111-4111-8111-111111111111'
export const MOCK_GREETING_ID = '22222222-2222-4222-8222-222222222222'
export const MOCK_REPLY = 'Hello from backend'

export async function mockDialogApi(page: Page, opts?: {
  createStatus?: number
  reply?: string
  streamError?: string
  noisy?: boolean
  delayMs?: number
  chunks?: string[]
  chunkDelayMs?: number
}) {
  const createStatus = opts?.createStatus ?? 200
  const reply = opts?.reply ?? MOCK_REPLY

  await page.route('**/api/v1/sessions**', async (route) => {
    const url = new URL(route.request().url())
    const method = route.request().method()
    if (method === 'PATCH') {
      const body = route.request().postDataJSON() as { title?: string }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ session: { title: body?.title || '会话' } }),
      })
      return
    }
    if (method === 'DELETE') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ deleted: true }),
      })
      return
    }
    if (method !== 'GET') {
      await route.fallback()
      return
    }
    const parts = url.pathname.split('/').filter(Boolean)
    const last = parts[parts.length - 1]
    if (last && last !== 'sessions') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: last,
          session_id: last,
          title: last === MOCK_GREETING_ID ? 'Greeting' : '会话',
          created_at: Date.now() / 1000,
          updated_at: Date.now() / 1000,
          message_count: 2,
          last_message: 'hi',
          messages: last === MOCK_GREETING_ID ? [
            {
              id: 1,
              session_id: last,
              role: 'user',
              content: 'hi',
              events: [],
              attachments: [],
              created_at: Date.now() / 1000,
            },
            {
              id: 2,
              session_id: last,
              role: 'assistant',
              content: 'Hi! What can I help you with?',
              events: [],
              attachments: [],
              created_at: Date.now() / 1000,
            },
          ] : [],
        }),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        sessions: [{
          id: MOCK_GREETING_ID,
          session_id: MOCK_GREETING_ID,
          title: 'Greeting',
          created_at: Date.now() / 1000,
          updated_at: Date.now() / 1000,
          message_count: 2,
          last_message: 'hi',
        }],
      }),
    })
  })

  await page.route('**/api/v1/tools**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        tools: [
          { name: 'brainstorm', toggleable: true, enabled: true, description_i18n: { zh: '头脑风暴' } },
          { name: 'web_search', toggleable: true, enabled: true, description_i18n: { zh: '网页搜索' } },
        ],
        enabled_optional_tools: ['brainstorm', 'web_search'],
      }),
    })
  })

  await page.addInitScript(({ createStatus: status, reply: mockReply, streamError, noisy, delayMs, chunks, chunkDelayMs }) => {
    const event = (type: string, extra: Record<string, unknown> = {}) => JSON.stringify({
      type,
      source: 'chat',
      stage: '',
      content: '',
      metadata: {},
      timestamp: Date.now(),
      ...extra,
    })
    class MockWebSocket {
      static CONNECTING = 0
      static OPEN = 1
      static CLOSING = 2
      static CLOSED = 3
      readyState = MockWebSocket.CONNECTING
      onopen: ((ev?: unknown) => void) | null = null
      onmessage: ((ev: { data: string }) => void) | null = null
      onclose: ((ev?: unknown) => void) | null = null
      onerror: ((ev?: unknown) => void) | null = null
      constructor(_url: string) {
        queueMicrotask(() => {
          this.readyState = MockWebSocket.OPEN
          this.onopen?.({})
        })
      }
      send(raw: string) {
        let data: { type?: string; session_id?: string | null }
        try { data = JSON.parse(raw) as { type?: string; session_id?: string | null } } catch { return }
        if (data.type === 'ping') {
          this.onmessage?.({ data: JSON.stringify({ type: 'pong' }) })
          return
        }
        if (data.type !== 'start_turn' && data.type !== 'message') return
        const sessionId = data.session_id || '11111111-1111-4111-8111-111111111111'
        if (status !== 200) {
          this.onmessage?.({ data: event('error', { content: '会话创建失败，请重试。', session_id: sessionId }) })
          return
        }
        this.onmessage?.({ data: event('session', { session_id: sessionId }) })
        if (streamError) {
          this.onmessage?.({ data: event('error', { content: streamError, session_id: sessionId }) })
          return
        }
        const emitReply = () => {
          if (noisy) {
            this.onmessage?.({ data: event('stage_start', { content: '探索', stage: 'exploring', session_id: sessionId }) })
            this.onmessage?.({ data: event('thinking', { content: '**Planning Socratic tutoring approach**', session_id: sessionId }) })
            this.onmessage?.({ data: event('progress', { content: 'responding', stage: 'responding', session_id: sessionId }) })
            this.onmessage?.({ data: event('tool_call', { content: '', session_id: sessionId, metadata: { tool_name: 'mastery_status' } }) })
            this.onmessage?.({ data: event('tool_result', { content: '{"status":"active"}', session_id: sessionId, metadata: { tool_name: 'mastery_status' } }) })
          }
          const pieces = chunks.length ? chunks : [mockReply]
          pieces.forEach((piece, index) => {
            window.setTimeout(() => {
              this.onmessage?.({ data: event('content', { content: piece, session_id: sessionId }) })
              if (index === pieces.length - 1) {
                this.onmessage?.({ data: event('done', { session_id: sessionId }) })
              }
            }, index * chunkDelayMs)
          })
        }
        if (delayMs > 0) window.setTimeout(emitReply, delayMs)
        else emitReply()
      }
      close() {
        this.readyState = MockWebSocket.CLOSED
        this.onclose?.({})
      }
      addEventListener() { /* noop */ }
      removeEventListener() { /* noop */ }
    }
    window.WebSocket = MockWebSocket as unknown as typeof WebSocket
  }, {
    createStatus,
    reply,
    streamError: opts?.streamError ?? '',
    noisy: opts?.noisy ?? false,
    delayMs: opts?.delayMs ?? 0,
    chunks: opts?.chunks ?? [],
    chunkDelayMs: opts?.chunkDelayMs ?? 40,
  })
}
