import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ChatMessageList } from '@/features/chat/messages'
import type { StreamEvent } from '@/features/chat/model/protocol'
import { WatchingProvider } from '@/context/WatchingContext'
import { initI18n } from '@/i18n/init'

initI18n('en')

describe('chat message feature', () => {
  it('renders a user row with keyboard-accessible message actions', async () => {
    const copy = vi.fn(async () => undefined)
    const user = userEvent.setup()
    render(
      <ChatMessageList
        messages={[
          {
            id: 1,
            role: 'user',
            content: 'Explain eigenvectors',
            parentMessageId: null,
          },
        ]}
        isStreaming={false}
        onCopyAssistantMessage={copy}
        onRegenerateMessage={() => undefined}
      />
    )
    expect(screen.getByText('Explain eigenvectors')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Copy' }))
    expect(copy).toHaveBeenCalledWith('Explain eigenvectors')
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeVisible()
  })

  // The button used to infer success from the handler's promise *resolving*,
  // so a swallowed clipboard error rendered 已复制 — and, because the label is
  // the aria-label on an aria-live element, announced it to screen readers.
  it('reports a failed copy instead of claiming success', async () => {
    const copy = vi.fn(async () => {
      throw new Error('clipboard unavailable')
    })
    const user = userEvent.setup()
    render(
      <ChatMessageList
        messages={[
          {
            id: 1,
            role: 'user',
            content: 'Explain eigenvectors',
            parentMessageId: null,
          },
        ]}
        isStreaming={false}
        onCopyAssistantMessage={copy}
        onRegenerateMessage={() => undefined}
      />
    )
    await user.click(screen.getByRole('button', { name: 'Copy' }))
    expect(await screen.findByRole('button', { name: 'Could not copy' })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Copied' })).toBeNull()
  })

  // The closing answer used to stream INSIDE the collapsible working-out and
  // hop out of it once the round completed, because where the prose was placed
  // was gated on the same "this round was terminal" signal that decides
  // whether to fold. A round only reveals whether it called tools after its
  // prose is done, so that gate could never be satisfied in time — it just
  // meant the reader watched the answer arrive dressed as reasoning.
  //
  // Placement is structural now: whatever is being written is the answer.
  it('streams the closing answer outside the fold, not inside it', () => {
    const event = (
      type: StreamEvent['type'],
      metadata: Record<string, unknown>,
      content = ''
    ): StreamEvent => ({
      type,
      source: 'chat',
      stage: 'responding',
      content,
      metadata,
      session_id: 's1',
      turn_id: 't1',
      seq: 0,
      timestamp: 0,
    })

    const { container } = render(
      <WatchingProvider>
        <ChatMessageList
          messages={[
            {
              id: 1,
              role: 'assistant',
              content: 'Let me look that up.\n\nIt was 1957.',
              parentMessageId: null,
              events: [
                event(
                  'content',
                  { call_id: 'round-1', call_kind: 'agent_loop_round' },
                  'Let me look that up.'
                ),
                // Round one turned out to have called a tool, so its prose is
                // commentary and belongs to the working-out.
                event('progress', {
                  call_id: 'round-1',
                  trace_kind: 'call_status',
                  call_state: 'complete',
                  call_role: 'narration',
                  answer_visible: true,
                }),
                event('tool_call', { call_id: 'tool-1' }, 'web_search'),
                event('tool_result', { call_id: 'tool-1' }, 'three results'),
                // Round two is still being written — no completion marker yet.
                event(
                  'content',
                  { call_id: 'round-2', call_kind: 'agent_loop_round' },
                  'It was 1957.'
                ),
              ],
            },
          ]}
          isStreaming
          onCopyAssistantMessage={async () => undefined}
          onRegenerateMessage={() => undefined}
        />
      </WatchingProvider>
    )

    const fold = container.querySelector('div.grid')
    expect(fold).not.toBeNull()
    expect(fold!.contains(screen.getByText('Let me look that up.'))).toBe(true)
    expect(fold!.contains(screen.getByText('It was 1957.'))).toBe(false)
  })

  // A synchronous throw is what reading `navigator.clipboard.writeText` does
  // on an insecure origin, and `Promise.resolve(onCopy(content))` ran the
  // handler outside the chain, so that throw escaped the button entirely.
  it('catches a handler that throws synchronously', async () => {
    const copy = vi.fn(() => {
      throw new Error('navigator.clipboard is undefined')
    }) as unknown as (content: string) => Promise<void>
    const user = userEvent.setup()
    render(
      <ChatMessageList
        messages={[
          {
            id: 1,
            role: 'user',
            content: 'Explain eigenvectors',
            parentMessageId: null,
          },
        ]}
        isStreaming={false}
        onCopyAssistantMessage={copy}
        onRegenerateMessage={() => undefined}
      />
    )
    await user.click(screen.getByRole('button', { name: 'Copy' }))
    expect(await screen.findByRole('button', { name: 'Could not copy' })).toBeVisible()
  })
})

describe('empty reply outcomes', () => {
  it.each([
    ['cancelled', 'Turn cancelled', 'Stopped'],
    ['failed', 'Provider quota exceeded', 'Provider quota exceeded'],
    ['legacy', 'Connection timed out', 'Connection timed out'],
    ['empty', '', 'No response was generated. Please try again.'],
  ])('renders %s replies with an explanation', (status, content, expected) => {
    const events: StreamEvent[] = status === 'empty' ? [] : [{
      type: 'error', source: 'chat', stage: '', content, timestamp: 0,
      metadata: status === 'legacy' ? {} : { turn_terminal: true, status },
    }];
    render(<WatchingProvider><ChatMessageList
      messages={[{ id: 1, role: 'user', content: 'hi' }, { id: 2, role: 'assistant', content: '', events }]}
      isStreaming={false}
      onCopyAssistantMessage={async () => undefined}
      onRegenerateMessage={() => undefined}
      onDeleteTurn={() => undefined}
    /></WatchingProvider>);
    expect(screen.getByText(expected)).toBeVisible();
    if (status === 'cancelled') expect(screen.queryByRole('alert')).toBeNull();
  });
});
