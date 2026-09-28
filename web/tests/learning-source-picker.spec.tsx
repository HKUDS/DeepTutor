import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { SourcesStep } from '@/components/space/learning/TopicWizardSteps'
import type { SourceCandidate, SourceLibrary } from '@/hooks/useTopicSourceLibrary'
import { initI18n } from '@/i18n/init'

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({}),
  usePathname: () => '/learning/books',
}))
initI18n('en')
const source = (workspace: string, label: string): SourceCandidate => ({
  key: `${workspace}:book:1`,
  kind: 'book',
  sourceId: '1',
  label,
  detail: '',
  available: true,
  content_workspace_id: workspace,
  content_workspace_name: workspace || 'Default workspace',
})
const library: SourceLibrary = {
  books: [source('', 'Original book'), source('Research', 'Research book')],
  notebooks: [],
  knowledgeBases: [],
  chats: [],
  questionSets: [],
  drafts: [],
  partners: [],
  failures: [],
}
function Picker() {
  const [selected, setSelected] = useState(new Set<string>())
  return (
    <SourcesStep
      library={library}
      loading={false}
      selected={selected}
      onToggle={key => setSelected(previous => new Set([...previous, key]))}
      childLists={{}}
      onExpand={vi.fn()}
    />
  )
}
it('shows all origins and preserves chosen sources while filtering and searching', () => {
  window.history.replaceState({}, '', '/learning/books?dt_workspace=destination')
  render(<Picker />)
  expect(screen.getByLabelText('Filter by workspace')).toHaveValue('*')
  fireEvent.click(screen.getByRole('tab', { name: /Books/ }))
  fireEvent.click(screen.getByRole('button', { name: /Original book/ }))
  fireEvent.change(screen.getByLabelText('Filter by workspace'), { target: { value: 'Research' } })
  expect(screen.queryByRole('button', { name: /Original book/ })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /Research book/ }))
  expect(screen.getByText('2 selected')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Filter by workspace'), { target: { value: '*' } })
  expect(screen.getByRole('button', { name: /Original book/ })).toHaveAttribute(
    'aria-pressed',
    'true'
  )
  fireEvent.change(screen.getByLabelText('Search materials'), { target: { value: 'Original' } })
  expect(screen.queryByRole('button', { name: /Research book/ })).not.toBeInTheDocument()
  expect(window.location.search).toBe('?dt_workspace=destination')
})
