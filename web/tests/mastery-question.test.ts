import assert from 'node:assert/strict'
import test from 'node:test'

import type { StreamEvent } from '../features/chat/model/protocol'
import { collectMasteryGrades, extractMasteryQuestion } from '../lib/mastery-question'

function toolResult(metadata: Record<string, unknown>): StreamEvent {
  return {
    type: 'tool_result',
    source: 'chat',
    stage: 'responding',
    content: '',
    metadata: { tool_metadata: metadata },
    session_id: 'session-1',
    turn_id: 'turn-1',
    seq: 1,
    timestamp: 0,
  }
}

const CARD = {
  question_id: 'q1',
  prompt: 'Which SQL returns names and departments?',
  question_type: 'choice',
  objective: { id: 'kp1', name: 'SELECT basics' },
  difficulty: 'medium',
  attempt: 2,
  options: [
    { label: 'A', body: 'SELECT * FROM employees' },
    { label: 'B', body: 'SELECT name, department FROM employees' },
  ],
  allow_free_text: true,
}

const POSED = toolResult({ mastery_question: CARD })

/** A card posed before mastery questions got their own event key. */
const POSED_LEGACY = toolResult({
  ask_user: {
    kind: 'mastery_question',
    questions: [
      {
        id: 'q1',
        prompt: 'Which SQL returns names and departments?',
        options: [
          { label: 'A', description: 'SELECT * FROM employees' },
          { label: 'B', description: 'SELECT name, department FROM employees' },
        ],
        multi_select: false,
        allow_free_text: true,
      },
    ],
    mastery_question: {
      question_id: 'q1',
      prompt: 'Which SQL returns names and departments?',
      question_type: 'choice',
      objective: { id: 'kp1', name: 'SELECT basics' },
      difficulty: 'medium',
      attempt: 2,
      options: [
        { label: 'A', body: 'SELECT * FROM employees' },
        { label: 'B', body: 'SELECT name, department FROM employees' },
      ],
      allow_free_text: true,
    },
  },
})

test('a posed mastery question is read with the context that makes it graded work', () => {
  const question = extractMasteryQuestion([POSED])

  assert.ok(question)
  assert.equal(question.questionId, 'q1')
  assert.equal(question.objectiveName, 'SELECT basics')
  assert.equal(question.difficulty, 'medium')
  assert.equal(question.attempt, 2)
  // The body is the option; the letter is positional and never doubled into it.
  assert.deepEqual(
    question.options.map(option => option.body),
    ['SELECT * FROM employees', 'SELECT name, department FROM employees']
  )
})

test('a card posed on the old ask_user channel is still read', () => {
  const question = extractMasteryQuestion([POSED_LEGACY])

  assert.ok(question)
  assert.equal(question.questionId, 'q1')
  assert.equal(question.objectiveName, 'SELECT basics')
  assert.equal(question.attempt, 2)
})

test('a generic clarifying question is not mistaken for a mastery one', () => {
  const generic = toolResult({
    ask_user: {
      questions: [{ id: 'c1', prompt: 'Which topic first?', options: [] }],
    },
  })

  assert.equal(extractMasteryQuestion([generic]), null)
})

test('a verdict reaches the card even when it is graded a turn later', () => {
  const graded = toolResult({
    mastery_grade: {
      is_correct: false,
      result: {
        question_id: 'q1',
        is_correct: false,
        learner_answer: 'A',
        correct_label: 'B',
        correct_body: 'SELECT name, department FROM employees',
        explanation: 'Listing the columns is what restricts the projection.',
      },
    },
  })

  const grades = collectMasteryGrades([{ events: [POSED] }, { events: [graded] }])

  const verdict = grades.get('q1')
  assert.ok(verdict)
  assert.equal(verdict.isCorrect, false)
  assert.equal(verdict.correctLabel, 'B')
  assert.match(verdict.explanation, /projection/)
})

test('a ruling the runtime published reaches the card the same way', () => {
  // A card answer is graded when its turn starts, not by the tutor calling a
  // tool, so the verdict arrives on an event the runtime publishes. It carries
  // the dispatcher's trace keys alongside the payload; the card must read it
  // exactly as it reads a tool's own result.
  const published: StreamEvent = {
    type: 'tool_result',
    source: 'mastery',
    stage: 'grading',
    content: 'graded',
    metadata: {
      tool: 'mastery_grade',
      trace_kind: 'tool_result',
      call_id: 'mastery-grade-turn-1-q1',
      trace_id: 'mastery-grade-turn-1-q1',
      label: 'Mastery Grade',
      call_kind: 'tool_call',
      phase: 'grading',
      tool_metadata: {
        mastery_grade: {
          is_correct: true,
          result: {
            question_id: 'q1',
            is_correct: true,
            learner_answer: 'B',
            correct_label: 'B',
            correct_body: 'SELECT name, department FROM employees',
            explanation: 'Listing the columns restricts the projection.',
          },
        },
      },
    },
    session_id: 'session-1',
    turn_id: 'turn-1',
    seq: 1,
    timestamp: 0,
  }

  const verdict = collectMasteryGrades([{ events: [POSED] }, { events: [published] }]).get('q1')

  assert.ok(verdict)
  assert.equal(verdict.isCorrect, true)
  assert.equal(verdict.correctLabel, 'B')
  assert.match(verdict.explanation, /projection/)
})

test('an ungraded conversation yields no verdicts', () => {
  assert.equal(collectMasteryGrades([{ events: [POSED] }]).size, 0)
})
