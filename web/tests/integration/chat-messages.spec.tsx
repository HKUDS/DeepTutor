import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ChatMessageList } from '@/features/chat/messages'
import type { StreamEvent } from '@/features/chat/model/protocol'
import { WatchingProvider } from '@/context/WatchingContext'
import { initI18n } from '@/i18n/init'

initI18n('en')

describe('chat message feature', () => {
  it('shows a persisted worker loss beside the saved mastery answer with Retry', async () => {
    const retry = vi.fn()
    render(
      <ChatMessageList
        messages={[{
          id: 23,
          role: 'user',
          content: 'B',
          parentMessageId: null,
          requestSnapshot: { content: 'B', enabledTools: [], knowledgeBases: [], language: 'en' },
          orphanedFailedTurn: {
            turn_id: 'failed-turn', error: 'Worker lost during this turn',
            failure_code: 'worker_lost', retryable: true, finished_at: 1,
          },
        }]}
        isStreaming={false}
        canResendLastTurn
        onResendLastTurn={retry}
        onCopyAssistantMessage={vi.fn()}
        onRegenerateMessage={vi.fn()}
      />,
    )

    expect(screen.getByText('B')).toBeVisible()
    expect(screen.getByRole('alert')).toHaveTextContent('Worker lost during this turn')
    await userEvent.setup().click(screen.getByRole('button', { name: 'Retry' }))
    expect(retry).toHaveBeenCalledOnce()
  })

  // The snapshot stores the qualified KB ref, but the reference chip under a
  // sent message used to print that ref verbatim — while the composer chip
  // for the same resource showed its readable name. The label now resolves
  // through the selection catalog, falling back to the ref when unmapped.
  it('labels sent-message KB references with the catalog name, not the raw ref', () => {
    const renderWithKb = (kb: string[], kbDisplayNames?: Record<string, string>) =>
      render(
        <ChatMessageList
          messages={[{
            id: 7,
            role: 'user',
            content: 'Summarize the papers',
            parentMessageId: null,
            requestSnapshot: {
              content: 'Summarize the papers',
              enabledTools: [],
              knowledgeBases: kb,
              language: 'en',
            },
          }]}
          isStreaming={false}
          onCopyAssistantMessage={vi.fn(async () => undefined)}
          onRegenerateMessage={() => undefined}
          kbDisplayNames={kbDisplayNames}
        />,
      )
    // Identity is preserved: an unmapped ref still renders, as itself.
    renderWithKb(['account:kb:legacy_kb'])
    expect(screen.getByText('account:kb:legacy_kb')).toBeVisible()

    const { unmount } = renderWithKb(
      ['workspace:ws-1:kb:example_kb'],
      { 'workspace:ws-1:kb:example_kb': 'example_kb' },
    )
    expect(screen.getByText('example_kb')).toBeVisible()
    expect(screen.queryByText('workspace:ws-1:kb:example_kb')).toBeNull()
    unmount()
  })

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
