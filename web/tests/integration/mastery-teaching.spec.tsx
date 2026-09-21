import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ChatMessageList } from '@/features/chat/messages'
import type { StreamEvent } from '@/features/chat/model/protocol'
import { compactTracePreview } from '@/features/chat/trace/memory'
import { WatchingProvider } from '@/context/WatchingContext'
import { initI18n } from '@/i18n/init'

initI18n('en')

const preamble = 'I will check the course material.\n\n'
const teaching = 'Reducers accumulate values instead of overwriting history.'
const question = 'Which reducer keeps history?'

function event(
  type: StreamEvent['type'],
  metadata: Record<string, unknown>,
  content = '',
): StreamEvent {
  return {
    type, content, metadata, source: 'chat', stage: 'responding',
    session_id: 's1', turn_id: 't1', seq: 0, timestamp: 0,
  }
}

function lessonEvents(extraTool: boolean, legacyCard: boolean): StreamEvent[] {
  const payload = {
    question_id: 'q1', prompt: question, question_type: 'choice',
    objective: { id: 'kp1', name: 'Reducers' }, difficulty: 'medium', attempt: 1,
    options: [{ label: 'A', body: 'overwrite' }, { label: 'B', body: 'accumulate' }],
    allow_free_text: true,
  }
  return [
    event('content', { call_id: 'r1', call_kind: 'agent_loop_round' }, preamble),
    event('tool_call', { call_id: 'read', assistant_content_offset: preamble.length }, 'read_source'),
    event('tool_result', { call_id: 'read', assistant_content_offset: preamble.length }, 'Course material'),
    event('content', { call_id: 'r2', call_kind: 'agent_loop_round' }, teaching),
    event('progress', {
      call_id: 'r2', trace_kind: 'call_status', call_state: 'complete',
      call_role: 'narration', answer_visible: true,
    }),
    ...(extraTool ? [
      // A state update can share the teaching round with the quiz. It still
      // belongs in the trace; it must not hide the explanation above it.
      event('tool_call', { call_id: 'grade', label: 'Record mastery grade', assistant_content_offset: preamble.length + teaching.length }, 'mastery_grade'),
      event('tool_result', { call_id: 'grade', assistant_content_offset: preamble.length + teaching.length }, 'Recorded'),
    ] : []),
    event('tool_call', { call_id: 'quiz', tool_name: 'mastery_quiz' }, 'mastery_quiz'),
    event('tool_result', {
      tool_call_id: 'quiz', assistant_content_offset: preamble.length + teaching.length,
      tool_metadata: legacyCard
        ? { ask_user: { kind: 'mastery_question', questions: [{ id: 'q1', prompt: question }], mastery_question: payload } }
        : { mastery_question: payload },
    }),
  ]
}

function conversation(events: StreamEvent[], isStreaming: boolean) {
  return (
    <WatchingProvider>
      <ChatMessageList
        messages={[{ id: 1, role: 'assistant', content: preamble + teaching, parentMessageId: null, events }]}
        isStreaming={isStreaming}
        onCopyAssistantMessage={async () => undefined}
        onRegenerateMessage={() => undefined}
      />
    </WatchingProvider>
  )
}

describe('mastery teaching beside a question', () => {
  it.each([
    { extraTool: false, legacyCard: false },
    { extraTool: true, legacyCard: false },
    { extraTool: false, legacyCard: true },
  ])('keeps teaching visible through completion and reload: %j', ({ extraTool, legacyCard }) => {
    const live = lessonEvents(extraTool, legacyCard)
    const { rerender } = render(conversation(live, true))
    const assertTeaching = () => {
      const prose = screen.getByText(teaching)
      const card = screen.getByText(question)
      // jsdom does not lay out the grid collapse. Check the actual fold
      // wrapper as well as visibility, so 0fr cannot produce a false pass.
      expect(prose.closest('.grid')).toBeNull()
      expect(prose).toBeVisible()
      expect(card.closest('.opacity-0')).toBeNull()
      expect(prose.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
      expect(screen.getAllByText(teaching)).toHaveLength(1)
    }
    assertTeaching()

    const completed = [...live, event('done', { status: 'completed' })]
    rerender(conversation(completed, false))
    assertTeaching()
    expect(screen.getByText(preamble.trim()).closest('.opacity-0')).not.toBeNull()
    if (extraTool) {
      expect(screen.getByText('Record mastery grade').closest('.opacity-0')).not.toBeNull()
    }

    // Reload serves semantic events plus saved prose, without content deltas.
    const preview = compactTracePreview(completed).events
    expect(preview.some((item) => item.type === 'content')).toBe(false)
    rerender(conversation(preview, false))
    assertTeaching()
    expect(screen.getByText(preamble.trim()).closest('.opacity-0')).not.toBeNull()
  })

  it('still folds commentary before an ordinary clarification card', () => {
    const events = lessonEvents(false, false)
    events[events.length - 1] = event('tool_result', {
      tool_call_id: 'quiz',
      tool_metadata: {
        ask_user: { questions: [{ id: 'q1', prompt: 'Which chapter should I check?' }] },
      },
    })
    render(conversation([...events, event('done', { status: 'completed' })], false))
    expect(screen.getByText(teaching).closest('.opacity-0')).not.toBeNull()
    expect(screen.getByText('Which chapter should I check?').closest('.opacity-0')).toBeNull()
  })
})
