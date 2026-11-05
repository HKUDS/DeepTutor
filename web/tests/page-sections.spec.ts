import { describe, expect, it } from 'vitest'
import { locatePage, pageSections, switchDestination } from '@/components/sidebar/page-sections'

const sections = (allowedSurfaces: string[] | null = null) =>
  pageSections({ t: key => key, zh: false, allowedSurfaces, isAvailable: () => false })

describe('page sections', () => {
  it('places each index page in the shelf the sidebar shows it under', () => {
    expect(locatePage('/space/journal', sections())?.section.id).toBe('resources')
    expect(locatePage('/learning', sections())?.section.id).toBe('learning')
    expect(locatePage('/kanban', sections())?.section.id).toBe('home')
    // Account-level pages are the same in every workspace, so show no workspace.
    expect(locatePage('/partners', sections())?.page.account).toBe(true)
    expect(locatePage('/memory', sections())?.page.account).toBe(true)
    expect(locatePage('/kanban', sections())?.page.account).toBeUndefined()
    expect(locatePage('/space', sections())?.page.account).toBeUndefined()
  })

  it('places workspace detail views under their index page', () => {
    expect(locatePage('/learning/books/b1/pages/p1', sections())?.page.href).toBe('/learning/books')
    expect(locatePage('/learning/mastery/path_1', sections())?.page.href).toBe('/learning/mastery')
    expect(locatePage('/learning/reading/folders/f1', sections())?.page.href).toBe('/learning/reading')
    expect(locatePage('/notebooks/abc', sections())?.page.href).toBe('/notebooks')
  })

  it('locates conversations, study sessions and account detail views too', () => {
    expect(locatePage('/chat', sections())?.page.href).toBe('/chat')
    expect(locatePage('/chat/s1', sections())?.page.href).toBe('/chat')
    expect(locatePage('/learning/mastery/path_1/sessions/s1', sections())?.page.href).toBe('/learning/mastery')
    expect(locatePage('/partners/frank', sections())?.page.href).toBe('/partners')
    expect(locatePage('/memory/l1', sections())?.page.href).toBe('/memory')
  })

  it('leaves views that draw the crumbs in their own toolbar alone', () => {
    expect(locatePage('/co-writer/doc', sections())).toBeNull()
    expect(locatePage('/learning/reading/rw_1', sections())).toBeNull()
  })

  it('switches workspace onto the same page, or the list a record lives in', () => {
    expect(switchDestination('/learning/books')).toBe('/learning/books')
    expect(switchDestination('/learning/books/b1')).toBe('/learning/books')
    expect(switchDestination('/learning/reading/rw_1/sessions/s1')).toBe('/learning/reading')
    expect(switchDestination('/chat/s1')).toBe('/chat')
    // The account's pages look the same from every workspace.
    expect(switchDestination('/partners/frank')).toBe('/partners/frank')
    expect(switchDestination('/space/skills')).toBe('/space/skills')
  })

  it('splits the shelves into workspace content and the account', () => {
    expect(sections().map(section => [section.id, Boolean(section.account)])).toEqual([
      ['home', false],
      ['learning', false],
      ['resources', false],
      ['partners', true],
      ['personalization', true],
    ])
    const personalization = sections().find(section => section.id === 'personalization')!
    expect(personalization.pages.map(page => page.href)).toContain('/agents')
    expect(sections().find(section => section.id === 'home')!.pages.map(page => page.href)).not.toContain('/agents')
    expect(locatePage('/space/personas', sections())?.page.account).toBe(true)
  })

  it('applies the same gates as the sidebar shelves', () => {
    const learning = sections(['books']).find(section => section.id === 'learning')!
    expect(learning.pages.map(page => page.label)).toEqual(['navigation.createLearning', 'navigation.allLearning', 'Books'])
    // Capability-gated resources stay hidden until the backend registers them.
    const resources = sections().find(section => section.id === 'resources')!
    expect(resources.pages.some(page => page.href === '/whisper')).toBe(false)
  })
})
