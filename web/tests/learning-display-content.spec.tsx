import React from 'react'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import postcss from 'postcss'
import tailwindcss from 'tailwindcss'
import QuestionCard from '@/components/space/question-bank/QuestionCard'
import type { NotebookEntry } from '@/lib/notebook-api'
import type { MarkdownRendererProps } from '@/components/common/markdown-renderer-types'
import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { LearningText } from '@/components/common/LearningText'
import SimpleMarkdownRenderer from '@/components/common/SimpleMarkdownRenderer'
import RichMarkdownRenderer from '@/components/common/RichMarkdownRenderer'
import { MasteryQuestionCard } from '@/components/chat/home/MasteryQuestionCard'
import { initI18n } from '@/i18n/init'
vi.mock('next/dynamic', () => ({
  default: () => (props: MarkdownRendererProps) => <SimpleMarkdownRenderer {...props} />,
}))
initI18n('en')
it.each([SimpleMarkdownRenderer, RichMarkdownRenderer])(
  'opts in each markdown renderer without scaling traces or reader defaults',
  Renderer => {
    const content = '## Topic\n\nLearning body.'
    const view = render(<Renderer content={content} learningTextSize={16} />)
    expect(view.container.querySelector('.md-renderer')).toHaveClass('learning-text')
    expect(
      (view.container.querySelector('.md-renderer') as HTMLElement).style.getPropertyValue(
        '--learning-text-base'
      )
    ).toBe('16px')
    view.rerender(<Renderer content={content} variant="trace" learningTextSize={16} />)
    expect(view.container.querySelector('.md-renderer')).not.toHaveClass('learning-text')
    // Immersive Reading's actual RichMarkdownRenderer API call has no opt-in.
    view.rerender(<Renderer content={content} variant="prose" />)
    expect(view.container.querySelector('.md-renderer')).not.toHaveClass('learning-text')
  }
)
it('scopes mastery stems, option bodies and explanations without resizing controls', () => {
  const view = render(
    <MasteryQuestionCard
      question={{
        questionId: 'display',
        questionType: 'choice',
        prompt: 'Choose the learning answer.',
        options: [{ label: 'A', body: 'Connect knowledge.' }],
        allowFreeText: false,
        objectiveName: '',
        difficulty: '',
        attempt: 1,
      }}
      answered
      grade={{
        questionId: 'display',
        isCorrect: true,
        learnerAnswer: 'A',
        correctLabel: 'A',
        correctBody: 'Connect knowledge.',
        explanation: 'Connections support recall.',
      }}
      submittedAnswer="A"
      onSubmit={() => true}
    />
  )
  expect(screen.getByText('Choose the learning answer.').closest('.learning-text')).not.toBeNull()
  expect(screen.getByText('Connect knowledge.').closest('.learning-text')).not.toBeNull()
  expect(screen.getByText('Connections support recall.').closest('.learning-text')).not.toBeNull()
  expect(view.container.querySelector('button.learning-text, textarea.learning-text')).toBeNull()
})

it('preserves the actual 16px Markdown baseline after the Tailwind utility cascade', async () => {
  // Compile only the actual prose base rule and the relevant utilities in
  // memory. This checks the incumbent cascade without a Next build or browser.
  const globals = readFileSync('app/globals.css', 'utf8')
  const proseRule = globals.match(/\.prose \{[^}]+\}/)![0]
  const require = createRequire(`${process.cwd()}/package.json`)
  const config = require('./tailwind.config.js')
  const css = await postcss([
    tailwindcss({
      ...config,
      content: [{ raw: '<div class="prose prose-sm text-[13px] text-[14px]">', extension: 'html' }],
    }),
  ]).process(`@tailwind utilities;\n${proseRule}`, { from: undefined })
  const style = document.createElement('style')
  style.textContent = css.css
  document.head.append(style)
  try {
    for (const Renderer of [SimpleMarkdownRenderer, RichMarkdownRenderer]) {
      for (const utility of ['text-[13px]', 'text-[14px]']) {
        const view = render(
          <Renderer content="Learning baseline." className={utility} variant="prose" />
        )
        const root = view.container.querySelector('.md-renderer') as HTMLElement
        expect(getComputedStyle(root).fontSize).toBe('16px')
        view.rerender(
          <Renderer
            content="Learning baseline."
            className={utility}
            variant="prose"
            learningTextSize={16}
          />
        )
        expect(root.style.getPropertyValue('--learning-text-base')).toBe('16px')
        view.unmount()
      }
    }
  } finally {
    style.remove()
  }
})

it('uses the 16px baseline for question bank stems, options, answers and explanations', () => {
  const entry: NotebookEntry = {
    id: 8,
    session_title: '',
    turn_id: '',
    question_id: 'q8',
    difficulty: '',
    material_id: '',
    material_title: '',
    section_id: '',
    section_title: '',
    resolved: false,
    bookmarked: false,
    followup_session_id: '',
    question: 'A learning question.',
    options: { A: 'A learning option.' },
    correct_answer: 'A learning answer.',
    user_answer: 'An earlier answer.',
    explanation: 'A learning explanation.',
    question_type: 'single_choice',
    source: 'import',
    categories: [],
    created_at: 1,
    updated_at: 1,
    session_id: '',
    score_trend: 'new',
    is_correct: false,
  }
  const view = render(
    <QuestionCard
      entry={entry}
      categories={[]}
      selected={false}
      disabled={false}
      onToggleSelected={() => {}}
      onToggleBookmark={() => {}}
      onToggleResolved={() => {}}
      onDelete={() => {}}
      onFile={async () => true}
      onUnfile={async () => true}
      onCreateAndFile={async () => true}
    />
  )
  const content = Array.from(
    view.container.querySelectorAll<HTMLElement>('.md-renderer.learning-text')
  )
  expect(content.length).toBeGreaterThanOrEqual(3)
  for (const root of content)
    expect(root.style.getPropertyValue('--learning-text-base')).toBe('16px')
  view.rerender(
    <QuestionCard
      entry={{ ...entry, options: {} }}
      categories={[]}
      selected={false}
      disabled={false}
      onToggleSelected={() => {}}
      onToggleBookmark={() => {}}
      onToggleResolved={() => {}}
      onDelete={() => {}}
      onFile={async () => true}
      onUnfile={async () => true}
      onCreateAndFile={async () => true}
    />
  )
  const answers = Array.from(
    view.container.querySelectorAll<HTMLElement>('.md-renderer.learning-text')
  )
  expect(answers.length).toBeGreaterThanOrEqual(4)
  for (const root of answers)
    expect(root.style.getPropertyValue('--learning-text-base')).toBe('16px')
})

it('isolates learning text lines by default while preserving explicit inline labels', () => {
  const view = render(
    <span>
      Correct · <LearningText size={14}>Learning text</LearningText>
    </span>
  )
  const text = screen.getByText('Learning text')
  expect(text.tagName).toBe('SPAN')
  expect(getComputedStyle(text).display).toBe('block')
  view.rerender(
    <span>
      Correct ·{' '}
      <LearningText inline size={14}>
        Learning text
      </LearningText>
    </span>
  )
  expect(getComputedStyle(screen.getByText('Learning text')).display).toBe('inline')
  expect(view.container).toHaveTextContent('Correct · Learning text')
})
