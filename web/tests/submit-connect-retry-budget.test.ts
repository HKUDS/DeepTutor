import test from 'node:test'
import assert from 'node:assert/strict'
import { SUBMIT_CONNECT_RETRY_INTERVAL_MS, SUBMIT_CONNECT_RETRY_LIMIT } from '@/lib/send-retry'
import { reconnectDelay } from '@/features/chat/transport/reconnect-policy'

test('submit retry budget covers the worst-case reconnect rung (#1648)', () => {
  const budgetMs = SUBMIT_CONNECT_RETRY_LIMIT * SUBMIT_CONNECT_RETRY_INTERVAL_MS
  const maxRungMs = reconnectDelay(64, () => 1)
  assert.ok(
    budgetMs >= maxRungMs,
    `submit budget ${budgetMs}ms must cover the reconnect rung cap ${maxRungMs}ms`
  )
})

test('submit retry budget leaves headroom beyond one reconnect rung', () => {
  const budgetMs = SUBMIT_CONNECT_RETRY_LIMIT * SUBMIT_CONNECT_RETRY_INTERVAL_MS
  assert.ok(budgetMs > 8_000)
})
