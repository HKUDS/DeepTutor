import type { NotebookRecordItem } from './notebook-api'

export interface FavoriteSnapshot {
  type: string
  summary: string
  metadata: Record<string, unknown>
}
/**
 * What a note keeps of a favorite besides its text. The collection name and
 * the save time travel with the snapshot, so the card on the page can say
 * where the excerpt came from even after the original moves or is deleted.
 */
export function favoriteSnapshot(
  record: NotebookRecordItem,
  collection?: { name: string }
): FavoriteSnapshot {
  return {
    type: record.type,
    summary: record.summary || '',
    metadata: {
      ...(record.metadata || {}),
      ...(collection?.name ? { favorite_collection: collection.name } : {}),
      ...(record.created_at ? { favorite_saved_at: record.created_at } : {}),
    },
  }
}
export const FAVORITE_LABELS: Record<string, string> = {
  chat: 'Chat',
  tutorbot: 'Partner',
  research: 'Research',
  solve: 'Solution',
  question: 'Question',
  reading: 'Reading',
  video_learning: 'Video Learning',
  co_writer: 'Learning notebook',
  guided_learning: 'Guided Learning',
}
export function favoriteKind(type: string, metadata: Record<string, unknown> = {}): string {
  if (type !== 'chat') return type
  const source = String(metadata.capability || metadata.source || '')
  return (
    (
      {
        immersive_reading: 'reading',
        deep_research: 'research',
        deep_question: 'question',
        deep_solve: 'solve',
        mastery_path: 'guided_learning',
      } as Record<string, string>
    )[source] || type
  )
}
/** Split only explicit role headings outside fenced code; keep every source character. */
export function favoriteTranscript(markdown: string): { role: string; content: string }[] {
  const parts: { role: string; content: string }[] = []
  let fence = ''
  for (const line of markdown.split('\n')) {
    const marker = /^\s*(`{3,}|~{3,})/.exec(line)?.[1]
    if (marker) {
      if (!fence) fence = marker
      else if (marker[0] === fence[0] && marker.length >= fence.length) fence = ''
    }
    const role = !fence && /^##\s+(User|Assistant|System|用户|助手|系统)\s*$/i.exec(line)?.[1]
    if (role) parts.push({ role, content: '' })
    else {
      if (!parts.length) parts.push({ role: '', content: '' })
      parts[parts.length - 1].content += `${line}\n`
    }
  }
  return parts.some(p => p.role) ? parts.filter(p => p.role || p.content.trim()) : []
}
export function favoriteAnswer(markdown: string): { question: string; answer: string } | null {
  let fence = ''
  let offset = 0
  for (const line of markdown.split('\n')) {
    const marker = /^\s*(`{3,}|~{3,})/.exec(line)?.[1]
    if (marker) {
      if (!fence) fence = marker
      else if (marker[0] === fence[0] && marker.length >= fence.length) fence = ''
    }
    if (
      !fence &&
      /^#{1,6}\s+(?:answer|solution|explanation|答案|参考答案|解答|解析)(?:\s+(?:and\s+explanation|与解析))?(?:\s*[：:]\s*.*|\s*)$/i.test(
        line
      )
    ) {
      if (markdown.slice(0, offset).trim())
        return { question: markdown.slice(0, offset), answer: markdown.slice(offset) }
    }
    offset += line.length + 1
  }
  return null
}
export function favoriteMedia(
  metadata: Record<string, unknown>
): { kind: 'video' | 'audio' | 'image'; url: string } | null {
  for (const [key, kind] of [
    ['video_url', 'video'],
    ['audio_url', 'audio'],
    ['image_url', 'image'],
  ] as const) {
    const url = metadata[key]
    if (typeof url !== 'string' || !/^(?:https?:\/\/|\/(?!\/))/.test(url)) continue
    const path = url.split(/[?#]/)[0]
    const supported =
      kind === 'video'
        ? /\.(mp4|webm|ogv)$/i
        : kind === 'audio'
          ? /\.(mp3|wav|ogg|m4a)$/i
          : /\.(png|jpe?g|webp|gif|avif)$/i
    if (supported.test(path)) return { kind, url }
  }
  return null
}

/** Match the rendered article outline, excluding headings inside code fences. */
export function favoriteHeadings(markdown: string): string[] {
  let fence = ''
  const headings: string[] = []
  for (const line of markdown.split('\n')) {
    const marker = /^\s*(`{3,}|~{3,})/.exec(line)?.[1]
    if (marker) {
      if (!fence) fence = marker
      else if (marker[0] === fence[0] && marker.length >= fence.length) fence = ''
    }
    if (!fence && /^#{1,3}\s+/.test(line))
      headings.push(line.replace(/^#+\s+/, '').replace(/\s+#+\s*$/, ''))
  }
  return headings
}
