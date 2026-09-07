import assert from 'node:assert/strict'
import test from 'node:test'

import {
  hydrateMessageAttachments,
  type MessageAttachment,
} from '../features/chat/ChatStateAdapter'
import {
  extractStreamedArtifacts,
  makeFileLinkRemarkPlugin,
  mergeGeneratedFiles,
} from '../components/common/InlineFileCard'

function workspaceFile(path: string, id: string): MessageAttachment {
  return {
    type: 'document',
    filename: path.split('/').pop(),
    url: `/files/workspace-items/ws_test/${id}`,
    mime_type: 'application/pdf',
    generated: true,
    origin: 'workspace',
    workspace_id: 'ws_test',
    workspace_item_id: id,
    relative_path: path,
  }
}

function runPlugin(files: MessageAttachment[], child: Record<string, unknown>) {
  const plugin = makeFileLinkRemarkPlugin(files)
  assert.ok(plugin)
  const transform = plugin()
  const tree = { type: 'root', children: [child] }
  transform(tree)
  return tree.children[0] as {
    children?: Array<Record<string, unknown>>
    url?: string
  }
}

test('workspace Markdown links resolve only by exact relative path', () => {
  const first = workspaceFile('outputs/chat/turn-a/report.pdf', 'wsi_a')
  const second = workspaceFile('outputs/chat/turn-b/report.pdf', 'wsi_b')

  const exact = runPlugin([first, second], {
    type: 'paragraph',
    children: [
      {
        type: 'link',
        url: 'outputs/chat/turn-b/report.pdf',
        children: [{ type: 'text', value: 'open report' }],
      },
    ],
  })
  assert.equal(exact.children?.[0]?.url, 'attachment:outputs%2Fchat%2Fturn-b%2Freport.pdf')

  const ambiguous = runPlugin([first, second], {
    type: 'paragraph',
    children: [
      {
        type: 'link',
        url: 'report.pdf',
        children: [{ type: 'text', value: 'open report' }],
      },
    ],
  })
  assert.equal(ambiguous.children?.[0]?.url, 'report.pdf')
})

test('workspace Markdown images use the same attachment rewrite', () => {
  const image = workspaceFile('outputs/visualize/turn/chart.png', 'wsi_image')
  image.type = 'image'
  image.mime_type = 'image/png'

  const paragraph = runPlugin([image], {
    type: 'paragraph',
    children: [
      {
        type: 'image',
        url: 'outputs/visualize/turn/chart.png',
        alt: 'Chart',
      },
    ],
  })
  assert.equal(paragraph.children?.[0]?.url, 'attachment:outputs%2Fvisualize%2Fturn%2Fchart.png')
})

test('streamed workspace items win over legacy artifacts and dedupe by URL', () => {
  const event = {
    type: 'tool_result' as const,
    content: 'done',
    metadata: {
      tool_metadata: {
        workspace_items: [
          {
            workspace_id: 'ws_test',
            workspace_item_id: 'wsi_one',
            relative_path: 'outputs/chat/turn/report.pdf',
            filename: 'report.pdf',
            url: '/files/workspace-items/ws_test/wsi_one',
            mime_type: 'application/pdf',
          },
        ],
        artifacts: [
          {
            filename: 'legacy.pdf',
            url: '/files/outputs/legacy.pdf',
            mime_type: 'application/pdf',
          },
        ],
      },
    },
  }
  const extracted = extractStreamedArtifacts([event] as never)
  assert.equal(extracted.length, 1)
  assert.equal(extracted[0]?.origin, 'workspace')

  const merged = mergeGeneratedFiles([extracted[0]!], [event] as never)
  assert.equal(merged.length, 1)
})

test('persisted workspace presentation metadata survives session hydration', () => {
  const hydrated = hydrateMessageAttachments([
    {
      type: 'image',
      filename: 'lesson.png',
      url: '/files/workspace-items/ws_test/wsi_image',
      mime_type: 'image/png',
      generated: true,
      size_bytes: 123,
      origin: 'workspace',
      workspace_id: 'ws_test',
      workspace_item_id: 'wsi_image',
      relative_path: 'outputs/chat/s/t/media/imagegen/lesson.png',
      sha256: 'abc123',
      title: 'Lesson image',
      caption: 'A generated illustration',
    },
  ])

  assert.deepEqual(hydrated[0], {
    type: 'image',
    filename: 'lesson.png',
    base64: undefined,
    url: '/files/workspace-items/ws_test/wsi_image',
    mime_type: 'image/png',
    id: undefined,
    extracted_text: undefined,
    generated: true,
    size_bytes: 123,
    origin: 'workspace',
    workspace_id: 'ws_test',
    workspace_item_id: 'wsi_image',
    relative_path: 'outputs/chat/s/t/media/imagegen/lesson.png',
    sha256: 'abc123',
    title: 'Lesson image',
    caption: 'A generated illustration',
  })
})
