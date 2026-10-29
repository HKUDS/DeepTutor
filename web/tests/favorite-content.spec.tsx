import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { useState } from 'react'
import FavoriteContent from '@/components/notebook/NotebookFavoriteContent'
import NoteFavoriteBlock from '@/features/notes/components/NoteFavoriteBlock'
import {
  favoriteAnswer,
  favoriteHeadings,
  favoriteKind,
  favoriteMedia,
  favoriteTranscript,
} from '@/lib/favorite-content'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('next/dynamic', () => ({
  default:
    () =>
    ({ content }: { content: string }) => <div>{content}</div>,
}))

it('keeps role-like headings inside code in the same conversation turn', () => {
  const turns = favoriteTranscript(
    '## User\nQuestion\n## Assistant\n```md\n## User\ncode\n```\nAnswer'
  )
  expect(turns).toHaveLength(2)
  expect(turns[1].content).toContain('## User\ncode')
  expect(turns[1].content).toContain('Answer')
})
it('uses capability-specific rendering even for favorites collected from chat', () => {
  expect(favoriteKind('chat', { source: 'chat', capability: 'deep_research' })).toBe('research')
  expect(favoriteKind('chat', { capability: 'mastery_path' })).toBe('guided_learning')
  expect(favoriteKind('reading')).toBe('reading')
})
it('does not mistake code or similarly named headings for an answer', () => {
  expect(favoriteAnswer('# Question\n```md\n## Answer\n```')).toBeNull()
  expect(favoriteAnswer('# Question\n## Answering strategies\nThink first')).toBeNull()
  const source = '# Question\n2+2?\n## Answer\n**4**'
  const parts = favoriteAnswer(source)!
  expect(parts.question + parts.answer).toBe(source)
})
it('excludes fenced headings from article navigation', () => {
  expect(
    favoriteHeadings('# Intro\n```md\n## Not a heading\n```\n## Evidence ##\n### End')
  ).toEqual(['Intro', 'Evidence', 'End'])
})
it('only enables players for safe, direct media URLs', () => {
  expect(favoriteMedia({ video_url: 'javascript:alert(1)' })).toBeNull()
  expect(favoriteMedia({ video_url: '//evil.test/v.mp4' })).toBeNull()
  expect(favoriteMedia({ video_url: '/api/v.mp4?dt_workspace=' })).toEqual({
    kind: 'video',
    url: '/api/v.mp4?dt_workspace=',
  })
})
it('keeps answers hidden until the reader reveals them', () => {
  render(<FavoriteContent type="question" markdown={'# Question\n2+2?\n## Answer\n4'} />)
  const details = screen.getByText('Show answer and explanation').closest('details')!
  expect(details.open).toBe(false)
  fireEvent.click(screen.getByText('Show answer and explanation'))
  expect(details.open).toBe(true)
  expect(details).toHaveTextContent('4')
})
it('seeks the embedded video without starting playback', () => {
  const { container } = render(
    <FavoriteContent
      type="video_learning"
      markdown="00:12 Review"
      metadata={{ video_url: '/clip.mp4' }}
    />
  )
  const video = container.querySelector('video')!
  fireEvent.click(screen.getByRole('button', { name: '00:12 · Review' }))
  expect(video.currentTime).toBe(12)
  expect(video.autoplay).toBe(false)
})
it('keeps unknown favorites readable and source navigation available while collapsed', () => {
  function Example() {
    const [expanded, onExpanded] = useState(false)
    return (
      <NoteFavoriteBlock
        title="Saved"
        markdown="Original text"
        sourceUrl="/notebooks/inbox?record=stable"
        type="legacy"
        summary="Summary"
        metadata="invalid"
        expanded={expanded}
        onExpanded={onExpanded}
      />
    )
  }
  render(<Example />)
  expect(screen.queryByText('Original text')).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Return to source' })).toHaveAttribute(
    'href',
    '/notebooks/inbox?record=stable'
  )
  fireEvent.click(screen.getByRole('button', { name: /Saved original/ }))
  expect(screen.getByText('Original text')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: /Saved original/ }))
  expect(screen.queryByText('Original text')).not.toBeInTheDocument()
})
