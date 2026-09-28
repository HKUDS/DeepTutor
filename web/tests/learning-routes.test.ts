import assert from 'node:assert/strict'
import test from 'node:test'
import {
  bookRoute,
  masteryTopicRoute,
  masterySessionsRoute,
  masterySessionRoute,
  readingCollectionRoute,
  readingSessionRoute,
  readingSessionIdFromPath,
  watchingRoute,
} from '../lib/learning-routes'

test('learning route builders encode resource identities once', () => {
  const id = '中文 /?#%'
  const encoded = encodeURIComponent(id)
  assert.equal(bookRoute(id, id), `/learning/books/${encoded}/pages/${encoded}`)
  assert.equal(masteryTopicRoute(id), `/learning/mastery/${encoded}`)
  assert.equal(masterySessionRoute(id, id), `/learning/mastery/${encoded}/sessions/${encoded}`)
  assert.equal(readingCollectionRoute(id), `/learning/reading/${encoded}`)
  assert.equal(readingSessionIdFromPath(readingSessionRoute(id, id)), id)
  assert.equal(watchingRoute(id), `/learning/watching/${encoded}`)
  assert.equal(
    masterySessionsRoute(id, new URLSearchParams({ course: id })),
    `/learning/mastery/${encoded}/sessions?course=${encodeURIComponent(id).replace(/%20/g, '+')}`
  )
})

test('malformed and unrelated URLs never bind a reading session', () => {
  for (const path of [
    '/learning/reading/a/sessions/%ZZ',
    '/learning/reading/a/sessions/x/extra',
    '/learning/reading//sessions/x',
    '/learning/reading/a',
    '/learning/reading/materials',
    '/learning/watching/x',
  ]) {
    assert.equal(readingSessionIdFromPath(path), null, path)
  }
})
