import test from 'node:test'
import assert from 'node:assert/strict'
import {
  answerAttachment,
  readAnswerAttachment,
} from '../features/chat/inline-answers/answer-attachment'
import { hasAnswerMarker, splitAnswerMarkers } from '../features/chat/inline-answers/markers'

test('splits answer markers out of the surrounding prose', () => {
  const parts = splitAnswerMarkers(
    'Question one?\n\n[[answer:q1]]\n\nQuestion two?\n[[answer:q2]]\n'
  )

  assert.deepEqual(parts, [
    { type: 'text', content: 'Question one?\n\n' },
    { type: 'answer', id: 'q1' },
    { type: 'text', content: '\n\nQuestion two?\n' },
    { type: 'answer', id: 'q2' },
    { type: 'text', content: '\n' },
  ])
  assert.equal(hasAnswerMarker('no marker here'), false)
  assert.equal(hasAnswerMarker('[[answer:q3]]'), true)
})

test('round-trips an attached answer through its wire attachment', () => {
  const attachment = answerAttachment({
    question_id: 'q1',
    question: 'What is pH?',
    answer: '12.26',
    source_message_id: 7,
  })

  assert.equal(attachment.type, 'answer')
  assert.deepEqual(readAnswerAttachment(attachment), {
    question_id: 'q1',
    question: 'What is pH?',
    answer: '12.26',
    source_message_id: 7,
  })
})
