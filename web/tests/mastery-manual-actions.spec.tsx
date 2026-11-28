import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ModuleOutline } from '@/components/space/learning/ModuleOutline'
import { initI18n } from '@/i18n/init'
import { fetchObjectiveReport } from '@/lib/learning-api'
import { manualReport as report, manualTopic as topic } from './fixtures/mastery-manual'

vi.mock('@/lib/learning-api', () => ({ fetchObjectiveReport: vi.fn() }))
initI18n('en')

function show(
  options: {
    deferred?: boolean
    onDefer?: (objectiveId: string, note: string) => Promise<void>
    onOverride?: (objectiveId: string, mastered: boolean, note: string) => Promise<void>
  } = {}
) {
  const onDefer = options.onDefer ?? vi.fn().mockResolvedValue(undefined)
  const onOverride = options.onOverride ?? vi.fn().mockResolvedValue(undefined)
  const snapshot = structuredClone(topic)
  snapshot.map.modules[0].knowledge_points[0].deferred = options.deferred ?? false
  const view = render(
    <ModuleOutline
      topic={snapshot}
      revision={1}
      selectedId="kp1"
      zh={false}
      onSelect={vi.fn()}
      onOverride={onOverride}
      onDefer={onDefer}
    />
  )
  return { ...view, onDefer, onOverride }
}

beforeEach(() => {
  vi.mocked(fetchObjectiveReport).mockReset()
  vi.mocked(fetchObjectiveReport).mockResolvedValue(report)
})

describe('manual mastery and deferral', () => {
  it('requires explicit confirmation and explains that deferral gives no mastery credit', async () => {
    const actions = show()
    fireEvent.click(
      await screen.findByRole('button', { name: 'Skip this knowledge point for now' })
    )
    expect(screen.getByText(/Skipping does not count as mastery/)).toBeVisible()
    expect(actions.onDefer).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('Optional note'), {
      target: { value: 'No question appeared' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Skip for now' }))
    await waitFor(() =>
      expect(actions.onDefer).toHaveBeenCalledExactlyOnceWith('kp1', 'No question appeared')
    )
    expect(actions.onOverride).not.toHaveBeenCalled()
  })

  it('lets the learner cancel without changing progress', async () => {
    const actions = show()
    fireEvent.click(
      await screen.findByRole('button', { name: 'Skip this knowledge point for now' })
    )
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('button', { name: 'Skip for now' })).not.toBeInTheDocument()
    expect(actions.onDefer).not.toHaveBeenCalled()
    expect(actions.onOverride).not.toHaveBeenCalled()
  })

  it('keeps mastery confirmation separate from skipping', async () => {
    const actions = show()
    fireEvent.click(await screen.findByRole('button', { name: 'I already know this — advance' }))
    expect(screen.getByText(/Confirming mastery counts toward progress/)).toBeVisible()
    fireEvent.change(screen.getByLabelText('Optional note'), {
      target: { value: 'My wording was equivalent' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm mastery' }))
    await waitFor(() =>
      expect(actions.onOverride).toHaveBeenCalledExactlyOnceWith(
        'kp1',
        true,
        'My wording was equivalent'
      )
    )
    expect(actions.onDefer).not.toHaveBeenCalled()
  })

  it('retains the reason on failure and allows retry without double submission', async () => {
    let reject!: (reason: Error) => void
    const onDefer = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise((_, fail) => {
            reject = fail
          })
      )
      .mockResolvedValue(undefined)
    show({ onDefer })
    fireEvent.click(
      await screen.findByRole('button', { name: 'Skip this knowledge point for now' })
    )
    fireEvent.change(screen.getByLabelText('Optional note'), {
      target: { value: 'Missing question' },
    })
    const confirm = screen.getByRole('button', { name: 'Skip for now' })
    fireEvent.click(confirm)
    expect(confirm).toBeDisabled()
    fireEvent.click(confirm)
    expect(onDefer).toHaveBeenCalledTimes(1)
    reject(new Error('Another update is in progress'))
    expect(await screen.findByRole('alert')).toHaveTextContent('Another update is in progress')
    expect(screen.getByLabelText('Optional note')).toHaveValue('Missing question')
    fireEvent.click(confirm)
    await waitFor(() => expect(onDefer).toHaveBeenCalledTimes(2))
  })

  it('labels a deferred objective without offering it as already mastered', async () => {
    show({ deferred: true })
    expect(await screen.findByText(/Skipping does not count as mastery/)).toBeVisible()
    expect(screen.getByText('Deferred for now')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Skip this knowledge point for now' })).toBeNull()
    expect(screen.getByRole('button', { name: 'I already know this — advance' })).toBeEnabled()
    expect(screen.queryByText('Confirmed by you')).toBeNull()
  })

  it('allows an existing learner confirmation to be withdrawn', async () => {
    vi.mocked(fetchObjectiveReport).mockResolvedValue({
      ...report,
      mastered: true,
      mastery_source: 'learner',
    })
    const actions = show()
    fireEvent.click(await screen.findByRole('button', { name: 'Return to assessment' }))
    await waitFor(() =>
      expect(actions.onOverride).toHaveBeenCalledExactlyOnceWith('kp1', false, '')
    )
    expect(actions.onDefer).not.toHaveBeenCalled()
  })
})
