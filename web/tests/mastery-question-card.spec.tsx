import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import MasteryQuestionCard from '@/components/chat/home/MasteryQuestionCard'
import { initI18n } from '@/i18n/init'
import type { MasteryQuestion } from '@/lib/mastery-question'

initI18n('en')

const question: MasteryQuestion = {
  questionId: 'limit-question',
  prompt: String.raw`当 $x\to0$ 时，哪个等价式正确？`,
  questionType: 'choice',
  objectiveName: 'Equivalent infinitesimals',
  difficulty: 'medium',
  attempt: 1,
  options: [
    { label: 'A', body: String.raw`$x-\sin x\sim\dfrac{x^3}{3}$` },
    { label: 'B', body: String.raw`\(x-\sin x\sim\dfrac{x^3}{6}\)` },
  ],
  allowFreeText: true,
}

describe('mastery question math', () => {
  it('renders the prompt and option bodies, but submits the stable option label', async () => {
    const onSubmit = vi.fn()
    const user = userEvent.setup()
    const { container } = render(
      <MasteryQuestionCard
        question={question}
        grade={null}
        answered={false}
        submittedAnswer=""
        onSubmit={onSubmit}
      />
    )

    await waitFor(() => {
      expect(container.querySelectorAll('.katex')).toHaveLength(3)
    })
    // Read the visible label: jsdom cannot compute names through KaTeX MathML.
    const option = screen.getByText('B').closest('button')!
    expect(option.querySelector('.mfrac')).not.toBeNull()
    expect(container.querySelector('.katex-error')).toBeNull()
    expect(container).not.toHaveTextContent('$x\\to0$')

    await user.click(option)
    await user.click(screen.getByText('Submit'))
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith({
      text: 'B',
      answers: [{ questionId: question.questionId, text: 'B' }],
    })
  })

  it('renders display math in a stored verdict and keeps answered options locked', async () => {
    const onSubmit = vi.fn()
    const { container } = render(
      <MasteryQuestionCard
        question={question}
        grade={{
          questionId: question.questionId,
          isCorrect: false,
          learnerAnswer: 'A',
          correctLabel: 'B',
          correctBody: question.options[1].body,
          explanation: String.raw`由泰勒展开：\[x-\sin x\sim\dfrac{x^3}{6}\]`,
        }}
        answered
        submittedAnswer="A"
        onSubmit={onSubmit}
      />
    )

    await waitFor(() => {
      expect(container.querySelectorAll('.katex')).toHaveLength(4)
      expect(container.querySelector('.katex-display .mfrac')).not.toBeNull()
    })
    expect(screen.getByText('Not quite')).toBeVisible()
    expect(screen.getByText(/Answer: B/)).toBeVisible()
    expect(screen.getByText('A').closest('button')).toBeDisabled()
    expect(screen.getByText('B').closest('button')).toBeDisabled()
    expect(screen.queryByText('Submit')).toBeNull()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('preserves escaped Unicode and submits a free-text formula verbatim', async () => {
    const onSubmit = vi.fn()
    const user = userEvent.setup()
    render(
      <MasteryQuestionCard
        question={{
          ...question,
          prompt: String.raw`\u8bf7\u9009\u62e9`,
          options: [{ label: 'A', body: String.raw`\u666e\u901a\u6587\u672c` }],
        }}
        grade={null}
        answered={false}
        submittedAnswer=""
        onSubmit={onSubmit}
      />
    )

    expect(await screen.findByText('请选择')).toBeVisible()
    expect(await screen.findByText('普通文本')).toBeVisible()
    await user.click(screen.getByRole('button', { name: /Answer in my own words/ }))
    const answer = String.raw`$\dfrac{x^3}{6}$`
    await user.paste(answer)
    await user.click(screen.getByRole('button', { name: 'Submit' }))
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith({
      text: answer,
      answers: [{ questionId: question.questionId, text: answer }],
    })
  })
})
