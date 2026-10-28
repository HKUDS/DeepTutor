/** Accept both notebook (source/target) and book (src/dst) graph payloads. */
export function noteConceptMap(payload: Record<string, unknown>): string {
  const graph =
    payload.graph && typeof payload.graph === 'object'
      ? (payload.graph as Record<string, unknown>)
      : payload
  const nodes = Array.isArray(graph.nodes) ? (graph.nodes as Record<string, unknown>[]) : []
  const edges = Array.isArray(graph.edges) ? (graph.edges as Record<string, unknown>[]) : []
  const label = (text: unknown) =>
    String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/[\r\n]/g, ' ')
  const ids = new Map(nodes.map((node, i) => [String(node.id), `n${i}`]))
  const lines = [
    'flowchart TD',
    ...nodes.map((node, i) => `  n${i}["${label(node.label || node.title || node.id)}"]`),
  ]
  for (const edge of edges) {
    const from = ids.get(String(edge.source || edge.src || edge.from))
    const to = ids.get(String(edge.target || edge.dst || edge.to))
    if (from && to) lines.push(`  ${from} -->${edge.label ? `|"${label(edge.label)}"|` : ''} ${to}`)
  }
  return nodes.length ? '```mermaid\n' + lines.join('\n') + '\n```' : ''
}
