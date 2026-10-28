import type { NoteBlock } from '@/lib/notes-api'

/** Keep editor.md math and diagram fences intact while migrating ordinary Markdown. */
export function parseNoteMarkdown(
  markdown: string,
  parse: (text: string) => NoteBlock[]
): NoteBlock[] {
  const result: NoteBlock[] = []
  const lines = markdown.split('\n')
  let prose: string[] = []
  const flush = () => {
    if (prose.join('\n').trim()) result.push(...parse(prose.join('\n')))
    prose = []
  }
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index]
    const formula = /^\s*\$\$(.*?)\$\$\s*$/.exec(line)
    if (formula) {
      flush()
      result.push({
        id: crypto.randomUUID(),
        type: 'math',
        props: { formula: formula[1] },
        children: [],
      })
      continue
    }
    if (/^\s*\$\$\s*$/.test(line)) {
      const end = lines.findIndex((next, n) => n > index && /^\s*\$\$\s*$/.test(next))
      if (end > index) {
        flush()
        result.push({
          id: crypto.randomUUID(),
          type: 'math',
          props: { formula: lines.slice(index + 1, end).join('\n') },
          children: [],
        })
        index = end
        continue
      }
    }
    const fence = /^\s*(`{3,}|~{3,})(\S*)\s*$/.exec(line)
    if (fence) {
      let end = index + 1
      const close = new RegExp(`^\\s*${fence[1][0]}{${fence[1].length},}\\s*$`)
      while (end < lines.length && !close.test(lines[end])) end++
      if (end < lines.length && ['mermaid', 'flow', 'seq'].includes(fence[2])) {
        flush()
        result.push({
          id: crypto.randomUUID(),
          type: 'learning',
          props: {
            kind: fence[2] === 'mermaid' ? 'mermaid' : 'legacy_diagram',
            markdown: lines.slice(index, end + 1).join('\n'),
            prompt: '',
            data: '{}',
            sourceUrl: '',
          },
          children: [],
        })
      } else prose.push(...lines.slice(index, end + 1))
      index = end
      continue
    }
    prose.push(line)
  }
  flush()
  const inlineMath = (blocks: NoteBlock[]) =>
    blocks.forEach(block => {
      if (block.type !== 'codeBlock' && Array.isArray(block.content)) {
        block.content = block.content.flatMap(raw => {
          const item = raw as { type: string; text?: string; styles?: Record<string, unknown> }
          if (item.type !== 'text' || item.styles?.code || !item.text) return [raw]
          const out: unknown[] = []
          let cursor = 0
          for (const match of item.text.matchAll(/(?<![\\$])\$([^$\n]+)\$(?!\$)/g)) {
            if (match.index! > cursor)
              out.push({ ...item, text: item.text.slice(cursor, match.index) })
            out.push({ type: 'inlineMath', props: { formula: match[1] } })
            cursor = match.index! + match[0].length
          }
          if (cursor < item.text.length) out.push({ ...item, text: item.text.slice(cursor) })
          return out
        })
      }
      if (block.children) inlineMath(block.children)
    })
  inlineMath(result)
  return result
}
