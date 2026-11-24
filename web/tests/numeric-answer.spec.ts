import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

import { numericEquivalent } from '@/lib/numeric-answer'

interface Vector {
  user: string
  expected: string
  comparable: boolean
  correct: boolean
  ambiguous?: boolean
}

// Shared with deeptutor/learning/tests/test_grading.py so both ports agree.
const { vectors } = JSON.parse(
  readFileSync(path.resolve(process.cwd(), '../tests/fixtures/numeric_answers.json'), 'utf8')
) as { vectors: Vector[] }

describe('numericEquivalent shared vectors', () => {
  it.each(vectors)('$user ~ $expected', vector => {
    const result = numericEquivalent(vector.user, vector.expected)
    expect({
      comparable: result.comparable,
      correct: result.correct,
      ambiguous: result.ambiguous,
    }).toEqual({
      comparable: vector.comparable,
      correct: vector.correct,
      ambiguous: vector.ambiguous ?? false,
    })
  })
})

describe('numericEquivalent', () => {
  it('reports each labelled part', () => {
    const result = numericEquivalent('b) 3,6; a) 12', 'a) 12; b) 3,5')
    expect(result.parts.map(p => [p.label, p.correct])).toEqual([
      ['a', true],
      ['b', false],
    ])
  })

  it('lets explicit tolerances replace the key precision', () => {
    expect(numericEquivalent('101', '100').correct).toBe(false)
    expect(numericEquivalent('101', '100', { relTol: 0.01 }).correct).toBe(true)
    expect(numericEquivalent('3.49', '3.48', { absTol: 0.02 }).correct).toBe(true)
    expect(numericEquivalent('3.51', '3.48', { absTol: 0.02 }).correct).toBe(false)
  })
})

describe('numericEquivalent units', () => {
  it('does not treat object prototype keys as currencies', () => {
    expect(numericEquivalent('5 constructor', '5 units').comparable).toBe(false)
  })
})
