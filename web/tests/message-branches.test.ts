import test from 'node:test'
import assert from 'node:assert/strict'
import { buildVisiblePath } from '../lib/message-branches'

type TreeMessage = {
  id: number
  role: 'user' | 'assistant'
  content: string
  parentMessageId: number | null
}

function conversationWithShortBranch() {
  const messages: TreeMessage[] = [
    { id: 1, role: 'user', content: 'question 1', parentMessageId: null },
  ]
  for (let round = 1; round <= 310; round++) {
    const previousId = messages[messages.length - 1].id!
    messages.push({
      id: round * 2,
      role: 'assistant' as const,
      content: `answer ${round}`,
      parentMessageId: previousId,
    })
    if (round === 310) break
    messages.push({
      id: round * 2 + 1,
      role: 'user' as const,
      content: `question ${round + 1}`,
      parentMessageId: round * 2,
    })
  }
  messages.push({
    id: 9000,
    role: 'user' as const,
    content: 'accidental branch',
    parentMessageId: 249,
  })
  return messages
}

test('an unselected short branch does not hide the longest continuation', () => {
  const messages = conversationWithShortBranch()
  const visible = buildVisiblePath(messages, {})

  assert.equal(visible.messages.length, 620)
  assert.equal(visible.messages.at(-1)?.id, 620)
  assert.equal(
    visible.messages.some(message => message.id === 9000),
    false
  )
  assert.deepEqual(visible.siblingsByMessageId.get(250)?.siblingIds, [250, 9000])
})

test('an explicit branch selection still overrides the deepest path', () => {
  const messages = conversationWithShortBranch()
  const visible = buildVisiblePath(messages, { '249': 9000 })

  assert.equal(visible.messages.length, 250)
  assert.equal(visible.messages.at(-1)?.content, 'accidental branch')
  assert.deepEqual(visible.siblingsByMessageId.get(9000)?.siblingIds, [250, 9000])
})
