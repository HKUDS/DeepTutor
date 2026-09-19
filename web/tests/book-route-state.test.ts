import test from 'node:test'
import assert from 'node:assert/strict'

import { isBookRouteLoading } from '../lib/book-route-state'

test('deep book routes stay at book level until their detail is loaded', () => {
  assert.equal(isBookRouteLoading('book-1', null), true)
  assert.equal(isBookRouteLoading('book-1', 'book-2'), true)
  assert.equal(isBookRouteLoading('book-1', 'book-1'), false)
})

test('the top-level book route can render the library immediately', () => {
  assert.equal(isBookRouteLoading(null, null), false)
  assert.equal(isBookRouteLoading(null, 'book-1'), false)
})
