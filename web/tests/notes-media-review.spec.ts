import { describe, expect, it, vi } from 'vitest'
import { Schema } from '@tiptap/pm/model'
import { reviewPosition } from '@/features/notes/model/review-placement'
import { noteMediaType } from '@/features/notes/model/media'
import { learningConfig, learningMode, visibleNotePrompt } from '@/features/notes/model/ai-request'
import { resultLearningBlock } from '@/features/notes/model/results'
import { noteConceptMap } from '@/features/notes/model/concept-map'

const schema = new Schema({
  nodes: {
    doc: { content: 'blockGroup' },
    blockGroup: { content: 'blockContainer+' },
    blockContainer: { attrs: { id: { default: null } }, content: 'paragraph blockGroup?' },
    paragraph: { content: 'text*' },
    text: {},
  },
})

it('sends note animations through Visualize with explicit Manim settings', () => {
  expect(learningMode('animation')).toBe('visualize')
  expect(learningConfig('animation')).toEqual({ render_mode: 'manim_video' })
  expect(learningConfig('animation', { output_mode: 'image', quality: 'high', style_hint: 'blue' }))
    .toEqual({ render_mode: 'manim_image', quality: 'high', style_hint: 'blue' })
  expect(learningConfig('animation', { render_mode: 'manim_image' }))
    .toEqual({ render_mode: 'manim_image' })
  expect(learningConfig('audio', { target_minutes: 2 })).toEqual({ target_minutes: 2 })
  expect(learningMode('audio')).toBe('audio_overview')
})

it('keeps rendered Visualize Manim artifacts as animation learning blocks', () => {
  const payload = {
    render_type: 'manim_video',
    output_mode: 'video',
    artifacts: [{ type: 'video', url: '/files/animation.mp4' }],
    response: 'A rotating vector traces a sine wave.',
  }
  const block = resultLearningBlock(payload)!
  expect(block.props.kind).toBe('animation')
  expect(JSON.parse(String(block.props.data))).toEqual(payload)
})
const block = (id: string, children?: ReturnType<typeof schema.node>) =>
  schema.node('blockContainer', { id }, [
    schema.node('paragraph', null, schema.text(id)),
    ...(children ? [children] : []),
  ])
const doc = schema.node(
  'doc',
  null,
  schema.node('blockGroup', null, [
    block('first', schema.node('blockGroup', null, [block('child')])),
    block('last'),
  ])
)

describe('inline review placement', () => {
  it('anchors a nested edit inside its group and a parent edit after all children', () => {
    const parent = reviewPosition(doc, 'first')
    const child = reviewPosition(doc, 'child')
    const last = reviewPosition(doc, 'last')
    expect(child.position).toBeLessThan(parent.position)
    expect(parent.position).toBe(last.target?.from)
    expect(parent.position).toBeLessThan(reviewPosition(doc, '').position)
    const parentText = reviewPosition(doc, 'first', [], true)
    expect(parentText.position).toBeLessThan(child.target!.from)
    expect(doc.nodeAt(parentText.target!.from)?.type.name).toBe('paragraph')
  })
  it('finds the target after other blocks are inserted or reordered', () => {
    const reordered = schema.node(
      'doc',
      null,
      schema.node('blockGroup', null, [block('last'), block('new'), doc.firstChild!.firstChild!])
    )
    expect(reviewPosition(reordered, 'first').position).toBe(reordered.content.size - 1)
    expect(reviewPosition(reordered, 'missing').target).toBeUndefined()
  })
  it('keeps a removed target near surviving context, including after reopening', () => {
    const removed = schema.node('doc', null, schema.node('blockGroup', null, [block('first'), block('last')]))
    const anchors = [{ id: 'last', side: 'before' as const }, { id: 'first', side: 'after' as const }]
    const reopened = schema.nodeFromJSON(removed.toJSON())
    expect(reviewPosition(reopened, 'missing', anchors).position).toBe(reviewPosition(reopened, 'last').target!.from)
    expect(reviewPosition(reopened, 'missing').position).toBe(1)
  })
})

it('validates media before upload and keeps PDF downloadable', () => {
  expect(noteMediaType({ type: 'application/pdf', size: 100 })).toBe('file')
  expect(noteMediaType({ type: 'audio/wav', size: 100 })).toBe('audio')
  expect(noteMediaType({ type: 'video/mp4', size: 100 })).toBe('video')
  expect(() => noteMediaType({ type: 'text/html', size: 100 })).toThrow('Unsupported')
  expect(() => noteMediaType({ type: 'image/png', size: 0 })).toThrow('25 MB')
  expect(() => noteMediaType({ type: 'image/png', size: 26 * 1024 * 1024 })).toThrow('25 MB')
})
it('keeps hidden generation context out of restored conversation bubbles', () => {
  expect(
    visibleNotePrompt(
      '画一个图\n\n<note-generation-context>\nblock-secret\n</note-generation-context>\n\n<notebook-source>\nsource'
    )
  ).toBe('画一个图')
  expect(visibleNotePrompt('ordinary\nmultiline')).toBe('ordinary\nmultiline')
})
it('renders generated concept-map edge aliases and labels', () => {
  const graph = noteConceptMap({
    nodes: [
      { id: 'a', label: '光' },
      { id: 'b', label: '糖' },
    ],
    edges: [{ source: 'a', target: 'b', label: '提供能量' }],
  })
  expect(graph).toContain('光')
  expect(graph).toContain('糖')
  expect(graph).toContain('提供能量')
  expect(graph).toContain('-->')
})

it('shows an actionable provider error without exposing the raw account response', async () => {
  const { noteGenerationError } = await import('@/features/notes/model/generation-error')
  expect(
    noteGenerationError('HTTP 402: {"error":"Insufficient credits","user_id":"private"}')
  ).toBe(
    'The generation provider has insufficient credits. Add credits in its settings, then retry.'
  )
})

it('uses research defaults and preserves explicit outline confirmation', async () => {
  const { noteGenerationConfig, researchOutline } = await import('@/features/notes/model/research')
  expect(noteGenerationConfig('deep_research')).toEqual({ mode: 'notes', depth: 'quick' })
  const outline = [{ title: 'Energy', overview: 'Explain the role of light' }]
  expect(noteGenerationConfig('deep_research', { confirmed_outline: outline })).toMatchObject({
    confirmed_outline: outline,
  })
  const block = resultLearningBlock({
    outline_preview: true,
    topic: 'Light',
    sub_topics: outline,
    research_config: { mode: 'notes', depth: 'quick' },
  })!
  expect(block.props.kind).toBe('research')
  expect(
    researchOutline({ blocks: [block] } as import('@/lib/notes-api').NoteSuggestion)?.sub_topics
  ).toEqual(outline)
})

it('uses the GeoGebra color API for style commands without an algebra result', async () => {
  const { runGeoGebraCommand } = await import('@/lib/geogebra-commands')
  const calls: unknown[][] = []
  const api = {
    evalCommand: () => false,
    setColor: (...args: unknown[]) => calls.push(args),
    exists: () => true,
  }
  expect(runGeoGebraCommand(api, 'SetColor(tri, 0.15, 0.45, 0.75)')).toBe(true)
  expect(calls).toEqual([['tri', 38, 115, 191]])
  expect(runGeoGebraCommand({ ...api, exists: () => false }, 'SetColor(missing, 0, 0, 1)')).toBe(
    false
  )
})
it('applies line styling through the geometry API without treating it as a failed construction', async () => {
  const { runGeoGebraCommand } = await import('@/lib/geogebra-commands')
  const api = { evalCommand: vi.fn(() => false), setLineThickness: vi.fn(), exists: () => true }
  expect(runGeoGebraCommand(api, 'SetLineThickness(tri, 3)')).toBe(true)
  expect(api.setLineThickness).toHaveBeenCalledWith('tri', 3)
  expect(api.evalCommand).not.toHaveBeenCalled()
  expect(runGeoGebraCommand({ ...api, exists: () => false }, 'SetLineThickness(missing, 3)')).toBe(
    false
  )
  expect(runGeoGebraCommand(api, 'SetLineThickness(tri, 14)')).toBe(false)
})
