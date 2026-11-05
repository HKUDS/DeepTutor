import type { Node } from '@tiptap/pm/model'

/** Position reviews after the complete target, including its nested children. */
export function reviewPosition(
  doc: Node,
  blockId: string,
  anchors: { id: string; side: 'before' | 'after' }[] = [],
  textOnly = false
) {
  let target: { from: number; to: number } | undefined
  const positions = new Map<string, { from: number; to: number }>()
  doc.descendants((node, pos) => {
    if (node.type.name !== 'blockContainer') return
    const range = { from: pos, to: pos + node.nodeSize }
    positions.set(node.attrs.id, range)
    if (node.attrs.id === blockId) target = textOnly && node.firstChild
      ? { from: pos + 1, to: pos + 1 + node.firstChild.nodeSize }
      : range
  })
  if (target) return { target, position: target.to }
  for (const anchor of anchors) {
    const range = positions.get(anchor.id)
    if (range) return { target, position: anchor.side === 'before' ? range.from : range.to }
  }
  // Only intentionally unanchored additions belong at the end. An orphaned
  // review stays visible at the start, clearly marked as unavailable.
  return { target, position: blockId ? 1 : Math.max(0, doc.content.size - 1) }
}
