import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ReviewTrail } from '@/components/space/learning/ReviewTrail'
import type { TopicReview } from '@/lib/learning-api'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? key.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(opts[name])) : key,
    i18n: { language: 'en' },
  }),
}))

function makeReviews(count: number): TopicReview[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `review-${index + 1}`,
    knowledge_point_id: `kp-${index + 1}`,
    knowledge_point_name: `KP ${index + 1}`,
    knowledge_type: 'concept',
    due_at: 1000 + index,
    priority: 1,
    due: true,
    forgetting_risk: 0.5,
    reason: 'scheduled',
    stability: 1,
    retrievability: 0.9,
    desired_retention: 0.9,
    lapse_count: 0,
    recent_failure: false,
  }))
}

function renderTrail(reviews: TopicReview[]) {
  return render(
    <ReviewTrail
      reviews={reviews}
      desiredRetention={0.9}
      retentionBusy={false}
      retentionError={null}
      onRetentionChange={vi.fn()}
      zh={false}
      onSelect={vi.fn()}
      onStartReview={vi.fn()}
    />
  )
}

function sectionElement() {
  return screen.getByText('Review plan').closest('section')
}

function scrollerElement(section: HTMLElement) {
  const firstRow = screen.getByRole('button', {
    name: 'Start review for KP 1',
  })
  expect(section).toContainElement(firstRow)
  const scroller = firstRow?.parentElement?.parentElement
  expect(scroller).toBeTruthy()
  return scroller as HTMLElement
}

/**
 * A long review trail must stay height-capped and scroll internally so the
 * outline column keeps its space (#1566). The layout contract lives in the
 * Tailwind classes the fix introduced, so a regression that drops them —
 * which re-crushes the outline — fails these assertions.
 */
describe('ReviewTrail with a long review trail (#1566)', () => {
  it('caps the section height instead of stretching the left column', () => {
    renderTrail(makeReviews(7))

    const section = sectionElement()
    expect(section).not.toBeNull()
    expect(section?.className).toContain('lg:max-h-[min(30vh,260px)]')
    expect(section?.className).toContain('lg:shrink-0')
    expect(section?.className).toContain('min-h-0')
    expect(section?.className).toContain('flex-col')
  })

  it('scrolls the trail internally while the header stays fixed', () => {
    renderTrail(makeReviews(7))

    const section = sectionElement() as HTMLElement
    const scroller = scrollerElement(section)
    expect(scroller.className).toContain('overflow-y-auto')
    expect(scroller.className).toContain('min-h-0')

    const heading = screen.getByText('Review plan')
    const hint = document.getElementById('review-retention-hint')
    expect(hint?.className).toContain('shrink-0')
    expect(scroller).not.toContainElement(heading)
    expect(scroller).not.toContainElement(hint)
  })

  it('keeps every review reachable inside the capped scroller', () => {
    renderTrail(makeReviews(7))

    const section = sectionElement() as HTMLElement
    const scroller = scrollerElement(section)
    expect(screen.getByText('7 due')).toBeTruthy()

    // Collapsed trail still lives in the internal scroller.
    for (let index = 1; index <= 5; index += 1) {
      expect(screen.getByRole('button', { name: `Start review for KP ${index}` })).toBeTruthy()
    }

    fireEvent.click(screen.getByRole('button', { name: 'Show all 7 reviews' }))

    for (let index = 1; index <= 7; index += 1) {
      const row = screen.getByRole('button', {
        name: `Start review for KP ${index}`,
      })
      expect(scroller).toContainElement(row)
    }
    // Expanding must not lift the cap that protects the outline column.
    expect(section.className).toContain('lg:max-h-[min(30vh,260px)]')
    expect(scroller.className).toContain('overflow-y-auto')
  })
})
