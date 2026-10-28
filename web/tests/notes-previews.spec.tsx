import { render, cleanup } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import NoteBlockPreview from '@/features/notes/components/NoteBlockPreview'
import NoteMath from '@/features/notes/components/NoteMath'
import { blockPreviewKinds } from '@/features/notes/model/block-previews'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
afterEach(cleanup)

describe('notebook format previews', () => {
  it.each(blockPreviewKinds)('%s renders a non-interactive, distinct format example', kind => {
    const { container } = render(<NoteBlockPreview kind={kind} />)
    expect(container.textContent?.trim()).toBeTruthy()
    expect(container.textContent).not.toContain('Make room for your next idea')
    expect(container.querySelector('button, input, a[href], iframe')).toBeNull()
  })
  it('shows a linked page title and keeps the three task layouts distinct', () => {
    const { container, rerender } = render(<NoteBlockPreview kind="pageLink" title="My research" />)
    expect(container.querySelector('.dt-note-preview-page-link')?.textContent).toBe('My research')
    rerender(<NoteBlockPreview kind="task_table" />)
    expect(container.querySelector('table')).not.toBeNull()
    rerender(<NoteBlockPreview kind="task_board" />)
    expect(container.querySelectorAll('article')).toHaveLength(2)
    expect(container.querySelector('table')).toBeNull()
    rerender(<NoteBlockPreview kind="task_list" />)
    expect(container.querySelectorAll('.dt-note-preview-checkbox')).toHaveLength(2)
  })
  it('keeps inline formulas inline and isolates invalid or untrusted TeX', () => {
    const { container, rerender } = render(
      <p>
        Before <NoteMath formula="x^2" /> after
      </p>
    )
    expect(container.querySelector('.katex')).not.toBeNull()
    expect(container.querySelector('.katex-display')).toBeNull()
    expect(container.querySelector('p p')).toBeNull()
    rerender(<NoteMath formula="x^2" display />)
    expect(container.querySelector('.katex-display')).not.toBeNull()
    rerender(<NoteMath formula={'\\href{javascript:alert(1)}{click}'} />)
    expect(container.querySelector('a')).toBeNull()
    rerender(<NoteMath formula={'\\frac{'} />)
    expect(container.querySelector('.katex-error')).not.toBeNull()
  })
})
