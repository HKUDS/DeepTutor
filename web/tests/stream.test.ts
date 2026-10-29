import test from 'node:test'
import assert from 'node:assert/strict'
import { recomputeAnswerContent } from '../lib/stream'
import type { StreamEvent } from '../features/chat/model/protocol'

function event(
  type: StreamEvent['type'],
  content: string,
  metadata: Record<string, unknown>
): StreamEvent {
  return {
    type,
    source: 'chat',
    stage: 'responding',
    content,
    metadata,
    session_id: 'session-1',
    turn_id: 'turn-1',
    seq: 1,
    timestamp: 0,
  }
}

test('commentary written before a tool call stays in the answer', () => {
  // The reader watched this sentence arrive above the tool's own row. Taking
  // it back out on the round's completion marker is what used to make a turn
  // look like it had said nothing while it worked.
  const events = [
    event('content', 'Checking the syllabus first.', {
      call_id: 'round-1',
      call_kind: 'agent_loop_round',
    }),
    event('progress', '', {
      call_id: 'round-1',
      trace_kind: 'call_status',
      call_state: 'complete',
      call_role: 'narration',
      answer_visible: true,
    }),
  ]

  assert.equal(recomputeAnswerContent(events), 'Checking the syllabus first.')
})

test('legacy rejection markers cannot remove published explanations', () => {
  const events = [
    event('content', 'Great job! Choose the next topic.', {
      call_id: 'round-rejected',
      call_kind: 'agent_loop_round',
    }),
    event('progress', '', {
      call_id: 'round-rejected',
      trace_kind: 'call_status',
      call_state: 'complete',
      call_role: 'narration',
      answer_visible: false,
    }),
  ]

  assert.equal(recomputeAnswerContent(events), 'Great job! Choose the next topic.')
})

test('a round recorded before the flag existed keeps its text', () => {
  // Sessions written by an older build carry no `answer_visible` at all.
  const events = [
    event('content', 'Searching.', {
      call_id: 'round-legacy',
      call_kind: 'agent_loop_round',
    }),
    event('progress', '', {
      call_id: 'round-legacy',
      trace_kind: 'call_status',
      call_state: 'complete',
      call_role: 'narration',
    }),
  ]

  assert.equal(recomputeAnswerContent(events), 'Searching.')
})

test('token-limit continuation replays the exact visible answer', () => {
  const events = [
    event('content', 'Part one. ', {
      call_id: 'round-part-1',
      call_kind: 'agent_loop_round',
    }),
    event('progress', '', {
      call_id: 'round-part-1',
      trace_kind: 'call_status',
      call_state: 'complete',
      call_role: 'narration',
      answer_visible: true,
    }),
    event('content', 'Part two.', {
      call_id: 'round-part-2',
      call_kind: 'agent_loop_round',
    }),
    event('progress', '', {
      call_id: 'round-part-2',
      trace_kind: 'call_status',
      call_state: 'complete',
      call_role: 'finish',
    }),
  ]

  assert.equal(recomputeAnswerContent(events), 'Part one. Part two.')
})

test('a later finish check cannot withdraw an already streamed answer', () => {
  // Old persisted rejection markers no longer suppress public text.
  const events = [
    event('content', 'Which value is correct?\n\nA. one\nB. two\nC. three', {
      call_id: 'round-1',
      call_kind: 'agent_loop_round',
    }),
    event('progress', '', {
      call_id: 'round-1',
      trace_kind: 'call_status',
      call_state: 'complete',
      call_role: 'finish',
    }),
    event('progress', '', {
      call_id: 'round-1',
      trace_kind: 'call_status',
      call_state: 'complete',
      call_role: 'narration',
      answer_visible: false,
      finish_rejected: true,
    }),
    event('content', 'Let us try that on a card instead.', {
      call_id: 'round-2',
      call_kind: 'agent_loop_round',
    }),
    event('progress', '', {
      call_id: 'round-2',
      trace_kind: 'call_status',
      call_state: 'complete',
      call_role: 'finish',
    }),
  ]

  assert.equal(
    recomputeAnswerContent(events),
    'Which value is correct?\n\nA. one\nB. two\nC. threeLet us try that on a card instead.'
  )
})

test('an accepted finish keeps its text even after later rounds close', () => {
  const events = [
    event('content', 'The derivative is 2x.', {
      call_id: 'round-1',
      call_kind: 'agent_loop_round',
    }),
    event('progress', '', {
      call_id: 'round-1',
      trace_kind: 'call_status',
      call_state: 'complete',
      call_role: 'finish',
    }),
  ]

  assert.equal(recomputeAnswerContent(events), 'The derivative is 2x.')
})
