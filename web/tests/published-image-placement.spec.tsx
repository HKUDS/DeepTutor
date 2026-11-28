import { render, screen, cleanup } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { AssistantMessage, GeneratedFileCards } from '@/features/chat/messages/ChatMessageList'
import { extractStreamedArtifacts } from '@/components/common/InlineFileCard'
import { extractMessageSegments } from '@/components/chat/home/AskUserOptions'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
afterEach(cleanup)

it('compares a synthetic streamed publication and reloaded attachments as answer text changes', () => {
  const items = [
    ['one', 'image/png', 'one.png'],
    ['two', 'image/png', 'two.png'],
    ['report', 'application/pdf', 'report.pdf'],
  ].map(([id, mime_type, filename]) => ({
    workspace_id: 'ws_test',
    workspace_item_id: id,
    filename,
    mime_type,
    relative_path: `outputs/${filename}`,
    url: `/files/workspace-items/ws_test/${id}`,
  }))
  const events = [
    {
      type: 'tool_result',
      content: 'published',
      metadata: { tool_metadata: { workspace_items: items } },
    },
  ] as never
  const attachments = extractStreamedArtifacts(events)
  expect(attachments).toHaveLength(3)
  const view = render(
    <GeneratedFileCards
      attachments={[]}
      events={events}
      content="Before the call. After the call."
    />
  )
  expect(screen.getAllByRole('img')).toHaveLength(2)
  expect(screen.getByText(/report/i)).toBeTruthy()
  view.rerender(
    <GeneratedFileCards
      attachments={[]}
      events={events}
      content="Before the call. ![one](outputs/one.png) After the call."
    />
  )
  expect(screen.queryByRole('img', { name: 'one.png' })).toBeNull()
  expect(screen.getByRole('img', { name: 'two.png' })).toBeTruthy()
  expect(screen.getByText(/report/i)).toBeTruthy()
  view.rerender(
    <GeneratedFileCards attachments={[]} content="![one](outputs/one.png) Before the call." />
  )
  view.rerender(
    <GeneratedFileCards
      attachments={[]}
      events={events}
      content="![one](outputs/one.png) Before the call."
    />
  )
  expect(screen.queryByRole('img', { name: 'one.png' })).toBeNull()
  expect(screen.getByRole('img', { name: 'two.png' })).toBeTruthy()
  view.rerender(
    <GeneratedFileCards
      attachments={attachments}
      content="![one](outputs/one.png) ![two](outputs/two.png)"
    />
  )
  expect(screen.queryAllByRole('img')).toHaveLength(0)
  expect(screen.getByText(/report/i)).toBeTruthy()
})

it('places a generated image at the event during streaming and reload', () => {
  const event = (type: string, content: string, metadata: object = {}) => ({
    type,
    content,
    metadata,
    source: 'chat',
    stage: 'responding',
    session_id: 's',
    turn_id: 't',
    seq: 1,
    timestamp: 0,
  })
  const tool = event('tool_result', 'published', {
    call_id: 't1',
    assistant_content_offset: 7,
    tool_metadata: {
      workspace_items: [
        {
          workspace_id: 'ws',
          workspace_item_id: 'one',
          relative_path: 'outputs/one.png',
          filename: 'one.png',
          mime_type: 'image/png',
          url: '/files/workspace-items/ws/one',
        },
      ],
    },
  })
  const events = [
    event('content', 'Before ', { call_id: 'r1', call_kind: 'agent_loop_round' }),
    event('tool_call', 'workspace_present', { call_id: 't1' }),
    tool,
    event('content', 'after', { call_id: 'r2', call_kind: 'agent_loop_round' }),
  ] as never
  const live = extractMessageSegments(events, 'Before after', { inlinePublishedImages: true })
  expect(live.map(segment => segment.kind)).toEqual(['text', 'trace', 'published_images', 'text'])
  const reloadEvents = [
    event('tool_call', 'workspace_present', { call_id: 't1', assistant_content_offset: 7 }),
    tool,
  ] as never
  const reload = extractMessageSegments(reloadEvents, 'Before after', {
    inlinePublishedImages: true,
  })
  expect(reload.map(segment => segment.kind)).toEqual(['text', 'trace', 'published_images', 'text'])
  for (const answer of [
    '![one](outputs/one.png) Before after',
    'Before after ![one](outputs/one.png)',
  ]) {
    expect(
      extractMessageSegments(reloadEvents, answer, { inlinePublishedImages: true }).some(
        segment => segment.kind === 'published_images'
      )
    ).toBe(false)
  }
})

it('renders publication once with non-image fallback in streamed and reloaded messages', () => {
  const item = (id: string, filename: string, mime_type: string) => ({
    workspace_id: 'ws',
    workspace_item_id: id,
    relative_path: `outputs/${filename}`,
    filename,
    mime_type,
    url: `/files/workspace-items/ws/${id}`,
  })
  const event = (type: string, content: string, metadata: object = {}) => ({
    type,
    content,
    metadata,
    source: 'chat',
    stage: 'responding',
    session_id: 's',
    turn_id: 't',
    seq: 1,
    timestamp: 0,
  })
  const call = event('tool_call', 'workspace_present', {
    call_id: 't1',
    assistant_content_offset: 7,
  })
  const result = event('tool_result', 'published', {
    call_id: 't1',
    tool_metadata: {
      workspace_items: [
        item('one', 'one.png', 'image/png'),
        item('report', 'report.pdf', 'application/pdf'),
      ],
    },
  })
  const events = [
    event('content', 'Before ', { call_id: 'r1', call_kind: 'agent_loop_round' }),
    call,
    result,
    event('content', 'after', { call_id: 'r2', call_kind: 'agent_loop_round' }),
  ] as never
  const attachments = extractStreamedArtifacts([result] as never)
  const view = render(<AssistantMessage msg={{ content: 'Before after', events }} isStreaming />)
  const before = screen.getByText('Before')
  const figure = screen.getByRole('img', { name: 'one.png' })
  expect(before).toBeVisible()
  expect(before.compareDocumentPosition(figure) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(
    figure.compareDocumentPosition(screen.getByText('after')) & Node.DOCUMENT_POSITION_FOLLOWING
  ).toBeTruthy()
  expect(screen.getByText(/report/i)).toBeTruthy()
  view.rerender(
    <AssistantMessage
      msg={{ content: 'Before after', events: [call, result, event('cancelled', '')] as never, attachments }}
    />
  )
  expect(screen.getAllByRole('img', { name: 'one.png' })).toHaveLength(1)
  expect(screen.getByText(/report/i)).toBeTruthy()
})

it('deduplicates repeated publications and leaves non-generated images as fallback cards', () => {
  const image = {
    workspace_id: 'ws',
    workspace_item_id: 'one',
    relative_path: 'outputs/one.png',
    filename: 'one.png',
    mime_type: 'image/png',
    url: '/files/workspace-items/ws/one',
  }
  const external = {
    ...image,
    workspace_item_id: 'two',
    relative_path: 'outputs/two.png',
    filename: 'two.png',
    url: '/files/workspace-items/ws/two',
    generated: false,
  }
  const result = {
    type: 'tool_result',
    content: 'published',
    metadata: {
      assistant_content_offset: 0,
      tool_metadata: { workspace_items: [image, image, external] },
    },
    source: 'chat',
    stage: 'responding',
    session_id: 's',
    turn_id: 't',
    seq: 1,
    timestamp: 0,
  }
  const segments = extractMessageSegments([result, result] as never, '', {
    inlinePublishedImages: true,
  })
  const placed = segments.filter(segment => segment.kind === 'published_images')
  expect(placed).toHaveLength(1)
  expect(placed[0].kind === 'published_images' && placed[0].images).toHaveLength(1)
})

it('uses the fallback card when the persisted call boundary is unavailable', () => {
  const result = {
    type: 'tool_result',
    content: 'published',
    metadata: {
      tool_metadata: {
        workspace_items: [
          {
            workspace_id: 'ws',
            workspace_item_id: 'one',
            relative_path: 'outputs/one.png',
            filename: 'one.png',
            mime_type: 'image/png',
            url: '/files/workspace-items/ws/one',
          },
        ],
      },
    },
    source: 'chat',
    stage: 'responding',
    session_id: 's',
    turn_id: 't',
    seq: 1,
    timestamp: 0,
  }
  const view = render(<AssistantMessage msg={{ content: 'Answer', events: [result] as never }} />)
  expect(screen.getAllByRole('img', { name: 'one.png' })).toHaveLength(1)
  expect(
    extractMessageSegments([result] as never, 'Answer', { inlinePublishedImages: true }).some(
      segment => segment.kind === 'published_images'
    )
  ).toBe(false)
  view.unmount()
})

it('keeps an image when a basename is ambiguous across stored and streamed files', () => {
  const file = (id: string, path: string) => ({
    workspace_id: 'ws', workspace_item_id: id, relative_path: path,
    filename: 'one.png', mime_type: 'image/png', url: `/files/workspace-items/ws/${id}`,
  })
  const result = { type: 'tool_result', content: 'published', metadata: { assistant_content_offset: 0, tool_metadata: { workspace_items: [file('one', 'outputs/a/one.png')] } }, source: 'chat', stage: 'responding', session_id: 's', turn_id: 't', seq: 1, timestamp: 0 }
  const stored = extractStreamedArtifacts([{ ...result, metadata: { tool_metadata: { workspace_items: [file('two', 'outputs/b/one.png')] } } }] as never)
  const segments = extractMessageSegments([result] as never, '![one](one.png)', { inlinePublishedImages: true, attachments: stored })
  expect(segments.some(segment => segment.kind === 'published_images')).toBe(true)
})
