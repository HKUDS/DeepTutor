import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import NoteLearningContent from '@/features/notes/components/NoteLearningContent'
import { upsertNotebookEntry } from '@/lib/notebook-api'
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/lib/notebook-api', () => ({ upsertNotebookEntry: vi.fn().mockResolvedValue({}) }))
vi.mock('@/app/(workspace)/learning/books/components/blocks/QuizBlock', () => ({
  default: ({ onAttempt }: { onAttempt: (id: string, args: unknown) => void }) => (
    <button onClick={() => onAttempt('q', { questionId: 'q:1', userAnswer: 'A', isCorrect: true })}>
      Answer quiz
    </button>
  ),
}))
let intersection: IntersectionObserverCallback
beforeEach(() => {
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      constructor(callback: IntersectionObserverCallback) {
        intersection = callback
      }
      observe() {}
      disconnect() {}
      unobserve() {}
    }
  )
})
const base = {
  id: 'q',
  kind: 'quiz',
  prompt: 'Teach this',
  markdown: '',
  sourceUrl: '',
  data: JSON.stringify({
    questions: [{ question: 'Light?', question_id: 'q:1', correct_answer: 'A' }],
  }),
}
const visible = (isIntersecting: boolean) =>
  act(() =>
    intersection([{ isIntersecting } as IntersectionObserverEntry], {} as IntersectionObserver)
  )
it('keeps rendered learning content mounted after scrolling away', async () => {
  render(<NoteLearningContent {...base} onChange={vi.fn()} />)
  visible(true)
  await screen.findByRole('button', { name: 'Answer quiz' })
  visible(false)
  expect(screen.getByRole('button', { name: 'Answer quiz' })).toBeInTheDocument()
})
it('allows quiz preview without writing attempts or the question notebook', async () => {
  const onChange = vi.fn()
  render(<NoteLearningContent {...base} readOnly onChange={onChange} />)
  visible(true)
  fireEvent.click(await screen.findByRole('button', { name: 'Answer quiz' }))
  expect(onChange).not.toHaveBeenCalled()
  expect(upsertNotebookEntry).not.toHaveBeenCalled()
})
it('persists real quiz answers in the learning block', async () => {
  const onChange = vi.fn()
  render(<NoteLearningContent {...base} onChange={onChange} />)
  visible(true)
  fireEvent.click(await screen.findByRole('button', { name: 'Answer quiz' }))
  expect(JSON.parse(onChange.mock.calls[0][0].data).attempts[0]).toMatchObject({
    question_id: 'q:1',
    user_answer: 'A',
    is_correct: true,
  })
  expect(upsertNotebookEntry).toHaveBeenCalledOnce()
})
