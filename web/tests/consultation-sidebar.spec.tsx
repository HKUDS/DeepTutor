import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ConsultationTabBody from '@/components/chat/home/ConsultationTabBody'
import type { StreamEvent } from '@/features/chat/model/protocol'

const fixture = vi.hoisted(() => ({
  send: vi.fn(() => true),
  frame: null as null | ((event: { data: string }) => void),
}))
const translate = vi.hoisted(() => (key: string) => key)
const autoScroll = vi.hoisted(() => ({
  containerRef: { current: null },
  shouldAutoScrollRef: { current: true },
  handleScroll: () => {},
  scrollToBottom: () => {},
}))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: translate, i18n: { language: 'en' } }),
}))
vi.mock('@/features/chat/trace', () => ({
  AssistantActivity: () => null,
  getTraceMeta: (event: StreamEvent) => event.metadata || {},
}))
vi.mock('@/components/chat/home/SubagentTabBody', () => ({
  default: () => <div>Local agent input</div>,
}))
vi.mock('next/dynamic', () => ({
  default:
    () =>
    ({ content }: { content: string }) => <div>{content}</div>,
}))
vi.mock('@/lib/api', () => ({ wsUrl: (path: string) => path }))
vi.mock('@/hooks/useChatAutoScroll', () => ({
  useChatAutoScroll: () => autoScroll,
}))
vi.mock('@/components/chat/home/TurnNavigator', () => ({ TurnNavigator: () => null }))
vi.mock('@/lib/reconnecting-websocket', () => ({
  ReconnectingWebSocket: class {
    connected = true
    constructor(
      _url: string,
      private options: { onOpen: () => void; onMessage: typeof fixture.frame }
    ) {
      fixture.frame = options.onMessage
    }
    start() {
      this.options.onOpen()
    }
    stop() {}
    send = fixture.send
  },
}))
vi.mock('@/lib/partners-api', () => ({
  getPartner: async () => ({ partner_id: 'frank', name: 'Frank', emoji: '🦊' }),
  getPartnerHistory: async () => [{ role: 'user', content: 'Earlier question' }, { role: 'assistant', content: 'Earlier answer' }],
  getPartnerHistoryPage: async () => ({
    messages: [{ role: 'user', content: 'Earlier question' }, { role: 'assistant', content: 'Earlier answer' }],
    next_before: null,
    start: 0,
    total: 2,
  }),
  getPartnerCommands: async () => [],
}))
vi.mock('@/lib/attachment-limits', () => ({ useAttachmentLimits: () => ({ maxBytes: 1000000, maxCount: 5 }) }))
const invocation = {
  invocation_id: 'proposal',
  group_id: 'group',
  session_key: 'dt-test',
  parent_turn_id: 'turn',
  requester_partner_id: 'a',
  requester_partner_name: 'Alice',
  target_partner_id: 'b',
  target_partner_name: 'Bob',
  question: 'Can you check my assumption?',
  status: 'pending',
  created_at: '',
  updated_at: '',
  question_event_id: '',
  reply_event_id: '',
  error: '',
}
vi.mock('@/lib/partner-groups-api', () => ({
  getPartnerGroup: async () => ({
    group_id: 'group',
    name: 'Panel',
    member_ids: ['a', 'b'],
    members: [
      { partner_id: 'a', name: 'Alice' },
      { partner_id: 'b', name: 'Bob' },
    ],
    discussion_mode: 'panel_parallel',
  }),
  getPartnerGroupHistory: async () => [
    {
      event_id: 'answer',
      turn_id: 'turn',
      session_key: 'dt-test',
      role: 'partner',
      author_id: 'a',
      author_name: 'Alice',
      content: 'Initial answer',
      kind: 'message',
      events: [],
      mentions: [],
      invocation_id: 'proposal',
      invocation,
    },
  ],
  getPartnerGroupWhiteboard: async () => [],
}))
afterEach(() => {
  cleanup()
  fixture.send.mockClear()
})

it.each(['approve', 'reject'])(
  'reuses native group approval controls inside chat: %s',
  async decision => {
    const events: StreamEvent[] = [
      {
        type: 'progress',
        source: 'chat',
        stage: '',
        content: 'Panel',
        timestamp: 1,
        metadata: {
          trace_kind: 'subagent_event',
          subagent_kind: 'partner_group',
          partner_group_id: 'group',
          partner_group_session_key: 'dt-test',
        },
      },
    ]
    render(<ConsultationTabBody tabEvents={events} sessionId="chat" />)
    await screen.findByText('Can you check my assumption?')
    expect(screen.queryByText('Local agent input')).toBeNull()
    fireEvent.click(
      screen.getByRole('button', { name: decision === 'approve' ? 'Let them discuss' : 'Not now' })
    )
    await waitFor(() =>
      expect(fixture.send).toHaveBeenCalledWith(
        JSON.stringify({
          action: `${decision}_invocation`,
          invocation_id: 'proposal',
          session_key: 'dt-test',
        })
      )
    )
    act(() =>
      fixture.frame?.({
        data: JSON.stringify({
          type: 'invocation_updated',
          invocation: { ...invocation, status: decision === 'approve' ? 'completed' : 'rejected' },
        }),
      })
    )
    if (decision === 'approve') {
      await waitFor(() =>
        expect(screen.queryByRole('button', { name: 'Let them discuss' })).toBeNull()
      )
      act(() =>
        fixture.frame?.({
          data: JSON.stringify({
            type: 'partner_message',
            message: {
              event_id: 'followup',
              turn_id: 'followup-turn',
              role: 'partner',
              author_id: 'b',
              author_name: 'Bob',
              content: 'Follow-up result',
              kind: 'invocation_reply',
              events: [],
              invocation_id: 'second-proposal',
              invocation: { ...invocation, invocation_id: 'second-proposal', parent_turn_id: 'followup-turn', question: 'One more exchange?', status: 'pending' },
            },
          }),
        })
      )
      expect(await screen.findByText('Follow-up result')).toBeTruthy()
      expect(await screen.findByText('One more exchange?')).toBeTruthy()
      fireEvent.click(screen.getByRole('button', { name: 'Let them discuss' }))
      expect(fixture.send).toHaveBeenCalledWith(JSON.stringify({ action: 'approve_invocation', invocation_id: 'second-proposal', session_key: 'dt-test' }))
    } else expect(await screen.findByText('Declined')).toBeTruthy()
  }
)


it('uses the native partner conversation for replay, live response and follow-up', async () => {
  const events: StreamEvent[] = [{ type: 'progress', source: 'chat', stage: '', content: 'Frank', timestamp: 1,
    metadata: { trace_kind: 'subagent_event', subagent_kind: 'partner', partner_id: 'frank', partner_session_key: 'dt-native', consult_index: 1 } }]
  render(<ConsultationTabBody tabEvents={events} sessionId="chat" />)
  expect(await screen.findByText('Earlier answer')).toBeTruthy()
  expect(screen.queryByText('Local agent input')).toBeNull()
  act(() => fixture.frame?.({ data: JSON.stringify({ type: 'ready' }) }))
  await waitFor(() => expect(fixture.send).toHaveBeenCalledWith(JSON.stringify({ action: 'attach', include_activity: false, session_key: 'dt-native' })))
  act(() => {
    fixture.frame?.({ data: JSON.stringify({ type: 'resuming' }) })
    fixture.frame?.({ data: JSON.stringify({ type: 'user_echo', content: 'DeepTutor question' }) })
    fixture.frame?.({ data: JSON.stringify({ type: 'content', content: 'Native partner answer' }) })
    fixture.frame?.({ data: JSON.stringify({ type: 'done' }) })
  })
  expect(await screen.findByText('Native partner answer')).toBeTruthy()
  const input = screen.getByPlaceholderText('Type a message...')
  fireEvent.change(input, { target: { value: 'My follow-up' } })
  fireEvent.keyDown(input, { key: 'Enter' })
  await waitFor(() => expect(fixture.send).toHaveBeenCalledWith(JSON.stringify({ content: 'My follow-up', session_key: 'dt-native', attachments: [] })))
})

it('reports user input separately from passive draft heartbeats', async () => {
  const events: StreamEvent[] = [{ type: 'progress', source: 'chat', stage: '', content: 'Panel', timestamp: 1,
    metadata: { trace_kind: 'subagent_event', subagent_kind: 'partner_group', partner_group_id: 'group', partner_group_session_key: 'dt-test', partner_group_idle_seconds: 10, partner_group_consultation_status: 'waiting' } }]
  render(<ConsultationTabBody tabEvents={events} sessionId="chat" />)
  await screen.findByText('Initial answer')
  const input = screen.getByRole('textbox')
  fireEvent.change(input, { target: { value: 'Still drafting' } })
  await waitFor(() => expect(fixture.send).toHaveBeenCalledWith(JSON.stringify({ action: 'consultation_activity', session_key: 'dt-test', has_draft: true, active: true })))
  fireEvent.change(input, { target: { value: '' } })
  await waitFor(() => expect(fixture.send).toHaveBeenCalledWith(JSON.stringify({ action: 'consultation_activity', session_key: 'dt-test', has_draft: false, active: true })))
})
