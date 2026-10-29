import type { NoteSummary } from '@/lib/notes-api'

export function pageDescendants(pages: NoteSummary[], id: string): Set<string> {
  const result = new Set([id])
  const queue = [id]
  for (let i = 0; i < queue.length; i++) {
    for (const page of pages) {
      if (page.parent_id === queue[i] && !result.has(page.id)) {
        result.add(page.id)
        queue.push(page.id)
      }
    }
  }
  return result
}
