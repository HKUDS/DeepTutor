import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import WorkspaceSettingsSection from '@/features/settings/sections/WorkspaceSettingsSection'

const fixture = vi.hoisted(() => ({ catalog: vi.fn(), save: vi.fn() }))
vi.mock('@/lib/workspaces-api', async original => ({
  ...(await original<object>()),
  getWorkspaceCatalog: fixture.catalog,
  saveWorkspace: fixture.save,
}))
vi.mock('@/components/workspaces/WorkspaceResourcePicker', () => ({
  WorkspaceResourcePicker: () => null,
}))
vi.mock('@/components/workspaces/SystemWorkspaceSnapshot', () => ({
  SystemWorkspaceSnapshot: () => null,
}))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
afterEach(cleanup)
beforeEach(() => {
  vi.clearAllMocks()
  fixture.save.mockResolvedValue({})
  fixture.catalog.mockResolvedValue({
    root: '/workspaces',
    workspaces: [
      {
        workspace_id: 'system',
        display_name: 'System',
        kind: 'system',
        path: '/system',
        status: 'ready',
      },
      {
        workspace_id: 'default',
        display_name: 'Default',
        kind: 'general',
        path: '/default',
        status: 'ready',
        instructions: 'Default style',
      },
      {
        workspace_id: 'algebra',
        display_name: 'Algebra',
        kind: 'workspace',
        path: '/algebra',
        status: 'ready',
        instructions: 'Start with intuition',
      },
      {
        workspace_id: 'archived',
        display_name: 'Archived',
        kind: 'workspace',
        path: '/archived',
        archived: true,
        status: 'ready',
      },
    ],
  })
})

it('edits only the selected workspace and keeps drafts when saving fails', async () => {
  render(<WorkspaceSettingsSection />)
  const row = within(await screen.findByRole('article', { name: 'Algebra' }))
  fireEvent.click(row.getByRole('button', { name: 'Workspace instructions' }))
  const editor = row.getByRole('textbox', { name: 'Workspace instructions' })
  expect(editor).toHaveValue('Start with intuition')
  expect(editor).toHaveAttribute('maxlength', '10000')
  fireEvent.change(editor, { target: { value: 'Give hints first' } })
  fixture.save.mockRejectedValueOnce(new Error('Could not save'))
  fireEvent.click(row.getByRole('button', { name: 'Save' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not save')
  expect(editor).toHaveValue('Give hints first')
  expect(fixture.save).toHaveBeenCalledWith({ instructions: 'Give hints first' }, 'algebra')
  fireEvent.click(row.getByRole('button', { name: 'Save' }))
  await waitFor(() =>
    expect(row.queryByRole('textbox', { name: 'Workspace instructions' })).toBeNull()
  )
})

it('supports clearing the default workspace instructions and excludes system and archived editors', async () => {
  render(<WorkspaceSettingsSection />)
  const row = within(await screen.findByRole('article', { name: 'Default workspace' }))
  fireEvent.click(row.getByRole('button', { name: 'Workspace instructions' }))
  expect(row.getByRole('textbox', { name: 'Workspace instructions' })).toHaveValue('Default style')
  fireEvent.click(row.getByRole('button', { name: 'Clear instructions' }))
  expect(row.getByRole('textbox', { name: 'Workspace instructions' })).toHaveValue('')
  fireEvent.click(row.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(fixture.save).toHaveBeenCalledWith({ instructions: '' }, 'default'))
  expect(
    within(screen.getByRole('article', { name: 'System workspace' })).queryByRole('button', {
      name: 'Workspace instructions',
    })
  ).toBeNull()
  expect(
    within(screen.getByRole('article', { name: 'Archived' })).queryByRole('button', {
      name: 'Workspace instructions',
    })
  ).toBeNull()
})

it('saves workspace instructions at creation and starts the next creation with an empty draft', async () => {
  render(<WorkspaceSettingsSection />)
  await screen.findByRole('article', { name: 'Algebra' })
  fireEvent.click(screen.getByRole('button', { name: 'New workspace' }))
  fireEvent.change(screen.getByRole('textbox', { name: 'Workspace name' }), {
    target: { value: 'Physics' },
  })
  fireEvent.change(screen.getByRole('textbox', { name: 'Workspace instructions' }), {
    target: { value: 'Explain using experiments' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Create workspace' }))
  await waitFor(() =>
    expect(fixture.save).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'Physics', instructions: 'Explain using experiments' })
    )
  )
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Create workspace' })).toBeNull())
  fireEvent.click(screen.getByRole('button', { name: 'New workspace' }))
  expect(screen.getByRole('textbox', { name: 'Workspace instructions' })).toHaveValue('')
})
