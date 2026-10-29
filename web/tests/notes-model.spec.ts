import { describe, expect, it } from 'vitest'
import { parseNoteMarkdown } from '@/features/notes/model/markdown'
import { resultLearningBlock } from '@/features/notes/model/results'
import type { NoteBlock } from '@/lib/notes-api'
const parse = (text: string): NoteBlock[] => [
  {
    id: crypto.randomUUID(),
    type: 'paragraph',
    props: {},
    content: [{ type: 'text', text, styles: {} }],
  },
]
describe('notebook migration and generated content', () => {
  it('preserves editor.md markers, math and old diagram fences', () => {
    const blocks = parseNoteMarkdown(
      '【重点】《保留》 $x^2$\n\n$$\ny = x^2\n$$\n\n```flow\nst=>start: Start\n```',
      parse
    )
    expect(JSON.stringify(blocks)).toContain('【重点】《保留》')
    expect(JSON.stringify(blocks)).toContain('inlineMath')
    expect(blocks.find(b => b.type === 'math')?.props.formula).toBe('y = x^2')
    expect(blocks.find(b => b.type === 'learning')?.props.markdown).toContain('st=>start: Start')
  })
  it('keeps unfinished math input as ordinary text', () => {
    expect(parseNoteMarkdown('$$\nunclosed', parse)[0].type).toBe('paragraph')
  })
  it('persists question payloads without the chat quiz provider', () => {
    const result = resultLearningBlock({
      summary: { results: [{ qa_pair: { question: 'Frequency?', correct_answer: 'Hz' } }] },
    })
    expect(result?.props.kind).toBe('quiz')
    expect(JSON.parse(String(result?.props.data)).questions[0].question).toBe('Frequency?')
  })
  it('preserves visualization envelopes and media URLs', () => {
    const payload = {
      renderer: { id: 'svg' },
      payload: { data: '<svg/>' },
      response: 'An illustration',
    }
    expect(JSON.parse(String(resultLearningBlock(payload)?.props.data))).toEqual(payload)
    expect(resultLearningBlock({ response: 'Just text' })).toBeUndefined()
    expect(
      resultLearningBlock({
        workspace_items: [{ url: '/api/workspaces/a/files/b', mime_type: 'audio/mpeg' }],
      })?.props.kind
    ).toBe('media')
  })
})

it('previews text blocks with their formatting and table cells intact', async () => {
  const { blockPreview } = await import('@/features/notes/model/blocks')
  expect(
    blockPreview({
      id: 'h',
      type: 'heading',
      props: { level: 2 },
      content: [{ type: 'text', text: 'Idea', styles: { bold: true } }],
    })
  ).toBe('## **Idea**')
  expect(
    blockPreview({ id: 'todo', type: 'checkListItem', props: { checked: true }, content: 'Done' })
  ).toBe('- [x] Done')
  expect(
    blockPreview({
      id: 'table',
      type: 'table',
      props: {},
      content: { rows: [{ cells: [[{ type: 'text', text: 'A|B' }]] }] },
    })
  ).toContain('| A\\|B |\n| --- |')
})
