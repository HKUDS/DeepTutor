import type { NoteSummary } from '@/lib/notes-api'

export function activePages(pages: NoteSummary[]): NoteSummary[] {
  const byId = new Map(pages.map(page => [page.id, page]))
  return pages.filter(page => {
    let ancestor: NoteSummary | undefined = page
    while (ancestor) {
      if (ancestor.archived) return false
      ancestor = ancestor.parent_id ? byId.get(ancestor.parent_id) : undefined
    }
    return true
  })
}

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
