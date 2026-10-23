import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ReviewTrail } from '@/components/space/learning/ReviewTrail'
import type { ReviewStrategy, TopicReview } from '@/lib/learning-api'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts
        ? key.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(opts[name]))
        : key,
    i18n: { language: 'en' },
  }),
}))

const preset: ReviewStrategy = {
  template_id: 'preset-exam-cramming',
  name: 'Exam Cramming',
  description: '',
  builtin: true,
  desired_retention: 0.95,
  intervals: {
    memory: [0, 1, 1, 2],
    concept: [1, 2, 3],
    procedure: [1, 2],
    design: [3],
  },
  created_at: 1,
  updated_at: 1,
}

const reviews: TopicReview[] = [
  {
    id: 'review-1',
    knowledge_point_id: 'kp-1',
    knowledge_point_name: 'KP 1',
    knowledge_type: 'memory',
    due_at: 1,
    priority: 1,
    due: true,
    forgetting_risk: 0.5,
    reason: 'scheduled',
    stability: 1,
    retrievability: 0.9,
    desired_retention: 0.9,
    lapse_count: 0,
    recent_failure: false,
  },
]

function renderTrail(overrides: Partial<Parameters<typeof ReviewTrail>[0]> = {}) {
  return render(
    <ReviewTrail
      reviews={reviews}
      desiredRetention={0.9}
      retentionBusy={false}
      retentionError={null}
      onRetentionChange={vi.fn()}
      strategies={[preset]}
      selectedStrategyId=""
      strategyLoading={false}
      strategyError={null}
      strategyBusy={false}
      onStrategyChange={vi.fn()}
      onRetryStrategies={vi.fn()}
      onStrategySave={vi.fn()}
      onStrategyDuplicate={vi.fn()}
      onStrategyDelete={vi.fn()}
      zh={false}
      onSelect={vi.fn()}
      onStartReview={vi.fn()}
      {...overrides}
    />,
  )
}

describe('ReviewTrail strategies (#1908)', () => {
  it('shows the default empty state before a custom strategy exists', () => {
    renderTrail()

    expect(screen.getByText('No custom strategies yet')).toBeTruthy()
  })

  it('binds a selected strategy', () => {
    const onStrategyChange = vi.fn()
    renderTrail({ onStrategyChange })

    fireEvent.change(screen.getByLabelText('Strategy'), {
      target: { value: 'preset-exam-cramming' },
    })

    expect(onStrategyChange).toHaveBeenCalledWith('preset-exam-cramming')
  })

  it('rejects decreasing custom rounds before submission', async () => {
    const onStrategySave = vi.fn().mockResolvedValue(undefined)
    renderTrail({ onStrategySave })

    fireEvent.click(screen.getByRole('button', { name: 'Edit strategy' }))
    fireEvent.change(screen.getByLabelText('memory rounds (days)'), {
      target: { value: '0,2,1' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save as custom' }))

    expect(
      await screen.findByText(
        'Use 1-16 non-decreasing whole-day rounds from 0-365 in every row.',
      ),
    ).toBeTruthy()
    expect(onStrategySave).not.toHaveBeenCalled()
  })
})
