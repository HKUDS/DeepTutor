import { describe, expect, it } from 'vitest'
import { extractStreamedArtifacts, mergeGeneratedFiles } from '@/components/common/InlineFileCard'
import type { StreamEvent } from '@/features/chat/model/protocol'

const event = (tool_metadata: unknown): StreamEvent[] => [
  {
    type: 'tool_result',
    content: '',
    source: 'exec',
    stage: '',
    timestamp: 0,
    metadata: { tool_metadata },
  },
]

describe('persisted artifact metadata', () => {
  it.each([{}, null, undefined, 'invalid', 42])(
    'does not crash on legacy non-array fields: %j',
    value => {
      expect(extractStreamedArtifacts(event({ workspace_items: value, artifacts: value }))).toEqual(
        []
      )
    }
  )
  it('retains a valid legacy artifact when workspace_items was serialized as an object', () => {
    const files = extractStreamedArtifacts(
      event({
        workspace_items: {},
        artifacts: [
          { filename: 'result.pdf', url: '/files/result.pdf', mime_type: 'application/pdf' },
        ],
      })
    )
    expect(files).toHaveLength(1)
    expect(files[0]).toMatchObject({
      filename: 'result.pdf',
      url: '/files/result.pdf',
      type: 'document',
    })
  })
  it('preserves workspace attachments and deduplicates persisted files', () => {
    const events = event({
      workspace_items: [
        {
          filename: 'plot.png',
          url: '/files/plot.png',
          mime_type: 'image/png',
          workspace_item_id: 'wsi_plot',
        },
      ],
      artifacts: {},
    })
    const files = extractStreamedArtifacts(events)
    expect(files[0]).toMatchObject({
      origin: 'workspace',
      type: 'image',
      workspace_item_id: 'wsi_plot',
    })
    expect(mergeGeneratedFiles(files, events)).toEqual(files)
  })
})
