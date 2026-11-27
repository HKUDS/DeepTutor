import type { NoteBlock } from '@/lib/notes-api'
import { safeNoteUrl } from './urls'
function inlineText(value: unknown): string {
  if (typeof value === 'string') return value
  if (!Array.isArray(value)) return ''
  return value
    .map(item => {
      if (!item || typeof item !== 'object') return ''
      if (item.type === 'inlineMath') return `$${item.props?.formula || ''}$`
      if (item.type === 'noteDate') return String(item.props?.date || '')
      if (item.type === 'pageLink')
        return `[${item.props?.title || ''}](/co-writer/${item.props?.pageId || ''})`
      let text = typeof item.text === 'string' ? item.text : inlineText(item.content)
      for (const [key, marker] of [
        ['code', '`'],
        ['bold', '**'],
        ['italic', '*'],
        ['strike', '~~'],
      ])
        if (item.styles?.[key]) text = marker + text + marker
      if (item.type === 'link' && safeNoteUrl(item.href)) text = `[${text}](${item.href})`
      return text
    })
    .join('')
}
/** A readable Markdown preview of the actual block, including its structure. */
export function blockPreview(block: NoteBlock): string {
  const props = block.props || {}
  let text = inlineText(block.content)
  switch (block.type) {
    case 'heading':
    case 'toggleHeading':
      text = `${'#'.repeat(Math.max(1, Math.min(6, Number(props.level) || 1)))} ${text}`
      break
    case 'bulletListItem':
    case 'toggleListItem':
      text = `- ${text}`
      break
    case 'numberedListItem':
      text = `1. ${text}`
      break
    case 'checkListItem':
      text = `- [${props.checked ? 'x' : ' '}] ${text}`
      break
    case 'quote':
    case 'callout':
      text = text
        .split('\n')
        .map(line => `> ${line}`)
        .join('\n')
      break
    case 'math':
      text = `$$\n${props.formula || ''}\n$$`
      break
    case 'divider':
      text = '---'
      break
    case 'codeBlock':
    case 'htmlEmbed': {
      const source = block.type === 'htmlEmbed' ? String(props.source || '') : text
      const fence = '`'.repeat(
        Math.max(3, ...[...source.matchAll(/`+/g)].map(m => m[0].length + 1))
      )
      text = `${fence}${block.type === 'htmlEmbed' ? 'html' : props.language || ''}\n${source}\n${fence}`
      break
    }
    case 'table': {
      const content = block.content as { rows?: { cells: unknown[] }[] } | undefined
      const rows = content?.rows || []
      const lines = rows.map(
        row =>
          '| ' +
          row.cells
            .map(cell =>
              inlineText(
                cell && typeof cell === 'object' && 'content' in cell ? cell.content : cell
              )
                .replaceAll('|', '\\|')
                .replaceAll('\n', '<br>')
            )
            .join(' | ') +
          ' |'
      )
      if (rows.length) lines.splice(1, 0, '| ' + rows[0].cells.map(() => '---').join(' | ') + ' |')
      text = lines.join('\n')
      break
    }
    case 'webCard':
      text = `[${props.title || props.url || ''}](${safeNoteUrl(props.url) || ''})\n\n${props.description || ''}`
      break
    case 'image':
    case 'video':
    case 'audio':
    case 'file':
      text = `${block.type === 'image' ? '!' : ''}[${props.caption || props.name || ''}](${safeNoteUrl(props.url) || ''})`
      break
    default:
      text ||= String(props.markdown || props.prompt || props.title || '')
  }
  return [text, ...(block.children || []).map(blockPreview)].filter(Boolean).join('\n\n')
}
