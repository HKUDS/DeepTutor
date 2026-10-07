import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ChatMessageList } from '@/features/chat/messages'
import { WatchingProvider } from '@/context/WatchingContext'
import { initI18n } from '@/i18n/init'

initI18n('en')

// The #1410 shape: editing an early message forks the transcript and the
// visible path follows the newest sibling, so the pre-edit history is
// reachable only through the BranchNavigator on the forked user message.
// That navigator is the way back to history, not a per-message convenience:
// it must share the Copy/Edit action row while staying outside their
// hover-only reveal, or the fork reads as "chat history lost, only the
// latest few messages remain".
type ForkedMessage = {
  id: number
  role: 'user' | 'assistant'
  content: string
  parentMessageId: number | null
}

const forkedMessages: ForkedMessage[] = [
  { id: 1, role: 'user', content: 'Original question', parentMessageId: null },
  {
    id: 2,
    role: 'assistant',
    content: 'Long answer on the original branch',
    parentMessageId: 1,
  },
  { id: 3, role: 'user', content: 'Edited question', parentMessageId: null },
  {
    id: 4,
    role: 'assistant',
    content: 'Fresh answer on the new branch',
    parentMessageId: 3,
  },
]

type ListProps = Parameters<typeof ChatMessageList>[0]

function renderList(
  props: Partial<
    Pick<ListProps, 'selectedBranches' | 'onSwitchBranch' | 'onEditMessage'>
  > = {},
) {
  const onSwitchBranch = props.onSwitchBranch ?? vi.fn()
  const view = render(
    <WatchingProvider>
      <ChatMessageList
        messages={forkedMessages}
        isStreaming={false}
        onCopyAssistantMessage={async () => undefined}
        onRegenerateMessage={() => undefined}
        onEditMessage={() => undefined}
        {...props}
        onSwitchBranch={onSwitchBranch}
      />
    </WatchingProvider>,
  )
  return { view, onSwitchBranch }
}

describe('branch navigator discoverability (#1410)', () => {
  it('keeps the navigator on the Copy/Edit row, outside their hover reveal', () => {
    renderList()

    const prev = screen.getByRole('button', { name: 'Previous branch' })
    // The action row hosting the navigator also hosts Copy/Edit; scope the
    // queries to it because every other message row carries its own Copy.
    const actionRow = prev.closest('div')!.parentElement!
    const copy = within(actionRow).getByRole('button', { name: 'Copy' })
    const edit = within(actionRow).getByRole('button', { name: 'Edit' })

    // The navigator must not live inside the group that stays hidden until
    // the reader hovers the bubble: a reader who never hovers still has to
    // see which version of the turn they are on and how to go back.
    const hoverRevealedGroup = copy.closest('div')
    expect(hoverRevealedGroup).not.toBeNull()
    expect(hoverRevealedGroup!.contains(prev)).toBe(false)
    expect(hoverRevealedGroup!.contains(edit)).toBe(true)

    // Same action row: the navigator renders beside the Copy/Edit group in
    // one row, so promoting it to always-visible adds no extra line under
    // the bubble.
    expect(actionRow).toBe(hoverRevealedGroup!.parentElement)

    // The position indicator tells the reader this transcript is one of
    // several versions of the turn.
    expect(screen.getByText('2 / 2')).toBeVisible()
  })

  it('switches back to the previous branch and restores the hidden history', async () => {
    const { view, onSwitchBranch } = renderList()

    // Only the newest branch renders by default — the #1410 "history lost"
    // experience. Every row is still in the message list.
    expect(screen.getByText('Edited question')).toBeVisible()
    expect(screen.queryByText('Original question')).toBeNull()
    expect(screen.queryByText('Long answer on the original branch')).toBeNull()

    await userEvent
      .setup()
      .click(screen.getByRole('button', { name: 'Previous branch' }))
    expect(onSwitchBranch).toHaveBeenCalledWith(null, 1)

    // Applying that selection (root -> sibling 1) puts the whole pre-edit
    // branch back on screen.
    view.rerender(
      <WatchingProvider>
        <ChatMessageList
          messages={forkedMessages}
          isStreaming={false}
          onCopyAssistantMessage={async () => undefined}
          onRegenerateMessage={() => undefined}
          onEditMessage={() => undefined}
          selectedBranches={{ null: 1 }}
          onSwitchBranch={onSwitchBranch}
        />
      </WatchingProvider>,
    )
    expect(screen.getByText('Original question')).toBeVisible()
    expect(screen.getByText('Long answer on the original branch')).toBeVisible()
    expect(screen.queryByText('Fresh answer on the new branch')).toBeNull()
    expect(screen.getByText('1 / 2')).toBeVisible()
    expect(
      screen.getByRole('button', { name: 'Next branch' }),
    ).toBeInTheDocument()
  })

  it('renders no branch navigation for a linear session', () => {
    render(
      <WatchingProvider>
        <ChatMessageList
          messages={[
            { id: 1, role: 'user', content: 'Only line', parentMessageId: null },
            { id: 2, role: 'assistant', content: 'Reply', parentMessageId: 1 },
          ] as ForkedMessage[]}
          isStreaming={false}
          onCopyAssistantMessage={async () => undefined}
          onRegenerateMessage={() => undefined}
          onEditMessage={() => undefined}
        />
      </WatchingProvider>,
    )
    expect(
      screen.queryByRole('button', { name: 'Previous branch' }),
    ).toBeNull()
    expect(screen.queryByText('1 / 1')).toBeNull()
  })
})
