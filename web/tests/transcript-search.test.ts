import assert from 'node:assert/strict'
import test from 'node:test'

import { stepTranscriptMatch, transcriptMatchIndexes } from '../lib/transcript-search'

const cues = [
  { text: 'Fourier transform' },
  { text: 'A geometric interpretation' },
  { text: 'Inverse FOURIER transform' },
]

test('transcript search is trimmed and case-insensitive', () => {
  assert.deepEqual(transcriptMatchIndexes(cues, '  fourier '), [0, 2])
  assert.deepEqual(transcriptMatchIndexes(cues, 'geometric'), [1])
  assert.deepEqual(transcriptMatchIndexes(cues, ''), [])
})

test('transcript match navigation wraps in both directions', () => {
  assert.equal(stepTranscriptMatch(-1, 3, 1), 0)
  assert.equal(stepTranscriptMatch(-1, 3, -1), 2)
  assert.equal(stepTranscriptMatch(2, 3, 1), 0)
  assert.equal(stepTranscriptMatch(0, 3, -1), 2)
  assert.equal(stepTranscriptMatch(0, 0, 1), -1)
})
