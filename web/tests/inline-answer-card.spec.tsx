import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { AnswerCard } from '@/features/chat/inline-answers/AnswerCard'
import { InlineAnswersProvider } from '@/features/chat/inline-answers/context'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

test('attaches a written answer and collapses to a link', () => {
  const attach = vi.fn()
  const view = render(
    <InlineAnswersProvider value={{ attached: new Map(), attach }}>
      <AnswerCard messageId={7} questionId="q1" />
    </InlineAnswersProvider>
  )

  fireEvent.change(screen.getByLabelText('Your answer'), {
    target: { value: '12.26' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Attach' }))

  expect(attach).toHaveBeenCalledWith({
    question_id: 'q1',
    question: '',
    answer: '12.26',
    source_message_id: 7,
  })

  view.rerender(
    <InlineAnswersProvider
      value={{
        attached: new Map([
          [
            '7:q1',
            {
              question_id: 'q1',
              question: '',
              answer: '12.26',
              source_message_id: 7,
              messageId: 9,
            },
          ],
        ]),
        attach,
      }}
    >
      <AnswerCard messageId={7} questionId="q1" />
    </InlineAnswersProvider>
  )

  expect(screen.getByRole('button', { name: /12\.26/ })).toBeTruthy()
})
