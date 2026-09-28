import React from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { SourceNavigator } from '@/components/reading/workspace/SourceNavigator'
import type { OutlineRow, UnitReference } from '@/lib/reading-api'
import type { ReaderHeading } from '@/lib/reading-outline'
import type { ReadingLibraryMaterial, ReadingWorkspaceTab } from '@/lib/reading-workspace-api'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (value: string) => value }),
}))

const baseMaterial = {
  content_id: 'content',
  render_mode: 'text',
  source_kind: 'file',
  source_url: '',
  mime: 'text/plain',
  cover_url: '',
  duration_seconds: 0,
  status: 'ready',
  progress: 1,
  error_code: '',
  error_detail: '',
  created_at: 1,
  updated_at: 1,
  last_opened_at: 1,
} as const

function material(id: string, title: string): ReadingLibraryMaterial {
  return { ...baseMaterial, material_id: id, filename: `${id}.txt`, title }
}

function tab(id: string, title: string): ReadingWorkspaceTab {
  return {
    material: material(id, title),
    tab_order: id === 'material-1' ? 0 : 1,
    pinned: false,
    opened: true,
    added_at: 1,
  }
}

const materials = [tab('material-1', 'Current'), tab('material-2', 'Other')]
const outline: OutlineRow[] = [
  { locator: 1, title: 'Introduction', level: 1, synthesised: false },
  { locator: 2, title: 'Methods', level: 1, synthesised: false },
]
const refs: UnitReference[] = [
  { locator: 1, title: 'Introduction', source_href: '#one' },
  { locator: 2, title: 'Methods', source_href: '#two' },
]
const headings: ReaderHeading[] = [
  { id: 'heading-1', title: 'Local heading', level: 1, locator: 1 },
]

function renderNavigator({
  outlineRows = outline,
  pageHeadings = [],
}: {
  outlineRows?: OutlineRow[]
  pageHeadings?: ReaderHeading[]
} = {}) {
  const onSelectMaterial = vi.fn()
  const onRemoveMaterial = vi.fn()
  render(
    <SourceNavigator
      material={materials[0].material}
      materials={materials}
      activeMaterialId="material-1"
      onSelectMaterial={onSelectMaterial}
      onRemoveMaterial={onRemoveMaterial}
      outline={outlineRows}
      pageHeadings={pageHeadings}
      activeHeadingId={null}
      onNavigateHeading={vi.fn()}
      refs={refs}
      transcript={[]}
      transcriptUnavailable={false}
      chaptersOnly={false}
      search=""
      onSearch={vi.fn()}
      activeLocator={1}
      annotationCount={0}
      unitCount={2}
      open
      onClose={vi.fn()}
      onNavigate={vi.fn()}
      bookmarks={[]}
      onRemoveBookmark={vi.fn()}
    />
  )
  return { onSelectMaterial, onRemoveMaterial }
}

describe('reading source navigator', () => {
  it('shows collection materials as top-level nodes and selects one', async () => {
    const user = userEvent.setup()
    const { onSelectMaterial } = renderNavigator()

    expect(screen.getByRole('button', { name: 'Current' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Other' })).toBeInTheDocument()
    expect(screen.getByText('Introduction')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Other' }))
    expect(onSelectMaterial).toHaveBeenCalledWith(materials[1].material)
  })

  it('removes a collection material', async () => {
    const user = userEvent.setup()
    const { onRemoveMaterial } = renderNavigator()

    await user.click(screen.getAllByRole('button', { name: 'Remove from collection' })[0])
    expect(onRemoveMaterial).toHaveBeenCalledWith(materials[0].material)
  })

  it('uses the server outline instead of repeating local page headings', () => {
    renderNavigator({ pageHeadings: headings })

    expect(screen.getByText('Introduction')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Local heading' })).not.toBeInTheDocument()
    expect(screen.queryByText('On this page')).not.toBeInTheDocument()
  })

  it('falls back to local page headings when no server outline exists', () => {
    renderNavigator({ outlineRows: [], pageHeadings: headings })

    expect(screen.getByRole('button', { name: 'Local heading' })).toBeInTheDocument()
  })

  it('collapses and re-expands the active material', async () => {
    const user = userEvent.setup()
    renderNavigator()

    expect(screen.getByText('Introduction')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Collapse section' }))
    expect(screen.queryByText('Introduction')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Expand section' }))
    expect(screen.getByText('Introduction')).toBeInTheDocument()
  })
})
