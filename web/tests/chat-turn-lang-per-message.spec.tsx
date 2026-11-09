import { render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ChatMessageList } from '@/features/chat/messages'
import type { MessageRequestSnapshot } from '@/features/chat/ChatStateAdapter'
import { initI18n } from '@/i18n/init'

type ChatMessageItem = Parameters<typeof ChatMessageList>[0]['messages'][number]

initI18n('en')

const snapshot = (language: string): MessageRequestSnapshot => ({
  content: 'question',
  enabledTools: [],
  knowledgeBases: [],
  language,
})

// A conversation where each turn ran in the language its request snapshot
// recorded, plus a legacy turn from before snapshots carried a language.
const messages: ChatMessageItem[] = [
  { id: 1, role: 'user', content: 'question', parentMessageId: null, requestSnapshot: snapshot('zh') },
  { id: 2, role: 'assistant', content: '你好，世界。', parentMessageId: 1 },
  { id: 3, role: 'user', content: 'question', parentMessageId: 2, requestSnapshot: snapshot('ja') },
  { id: 4, role: 'assistant', content: 'こんにちは、世界。', parentMessageId: 3 },
  { id: 5, role: 'user', content: 'legacy question', parentMessageId: 4 },
  { id: 6, role: 'assistant', content: 'Hello, world.', parentMessageId: 5 },
]

const assistantLangs = (container: HTMLElement) =>
  Array.from(
    container.querySelectorAll<HTMLDivElement>(
      '[data-chat-message-role="assistant"] [role="article"]',
    ),
  ).map((node) => node.getAttribute('lang'))

const renderList = (language: string | undefined) =>
  render(
    <ChatMessageList
      messages={messages}
      isStreaming={false}
      language={language}
      onCopyAssistantMessage={vi.fn()}
      onRegenerateMessage={vi.fn()}
    />,
  )

// Each assistant reply is tagged with the language its own turn ran in, so
// the :lang() CJK font stacks follow the reply, not the session setting.
// A legacy reply with no recorded language falls back to the session's.
describe('per-message lang tags from the turn language', () => {
  it('tags each reply with its recorded language; legacy falls back to the session', () => {
    const { container } = renderList('ko')

    expect(assistantLangs(container)).toEqual(['zh-Hans', 'ja', 'ko'])
  })

  it('keeps recorded tags when the session language changes; only legacy follows', () => {
    const { container, rerender } = renderList('ko')
    expect(assistantLangs(container)).toEqual(['zh-Hans', 'ja', 'ko'])

    // zh -> ja mid-session must not re-tag the old Chinese reply with
    // Japanese fonts (the Air finding), nor the Japanese one with zh.
    rerender(
      <ChatMessageList
        messages={messages}
        isStreaming={false}
        language="zh"
        onCopyAssistantMessage={vi.fn()}
        onRegenerateMessage={vi.fn()}
      />,
    )

    expect(assistantLangs(container)).toEqual(['zh-Hans', 'ja', 'zh-Hans'])
  })
})
