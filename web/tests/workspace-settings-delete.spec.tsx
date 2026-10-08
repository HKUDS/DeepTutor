import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import WorkspaceSettingsSection from '@/features/settings/sections/WorkspaceSettingsSection'
import type { ChatWorkspaceRegistration, WorkspaceCatalog } from '@/lib/workspaces-api'

const fixture = vi.hoisted(() => ({
  catalog: null as WorkspaceCatalog | null,
  getWorkspaceCatalog: vi.fn(),
  saveWorkspace: vi.fn(),
  deleteWorkspace: vi.fn(),
  migrateWorkspace: vi.fn(),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/lib/workspaces-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/workspaces-api')>()),
  getWorkspaceCatalog: (...args: unknown[]) => fixture.getWorkspaceCatalog(...args),
  saveWorkspace: (...args: unknown[]) => fixture.saveWorkspace(...args),
  deleteWorkspace: (...args: unknown[]) => fixture.deleteWorkspace(...args),
  migrateWorkspace: (...args: unknown[]) => fixture.migrateWorkspace(...args),
}))

function makeCatalog(): WorkspaceCatalog {
  return {
    root: '/workspaces',
    workspaces: [
      {
        workspace_id: 'ws-locked',
        display_name: 'Locked Deployment',
        path: '/deployment/root',
        archived: false,
        locked: true,
        kind: 'workspace',
        follows_root: false,
        created_at: '2026-01-01T00:00:00Z',
        status: 'ready',
        error: '',
      },
      {
        workspace_id: 'ws-archived',
        display_name: 'Archived Project',
        path: '/workspaces/archived',
        archived: true,
        locked: false,
        kind: 'workspace',
        follows_root: false,
        created_at: '2026-01-01T00:00:00Z',
        status: 'ready',
        error: '',
      },
    ],
  }
}

describe('WorkspaceSettingsSection delete and locked state', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fixture.catalog = makeCatalog()
    fixture.getWorkspaceCatalog.mockResolvedValue(fixture.catalog)
    fixture.deleteWorkspace.mockResolvedValue(undefined)
  })

  it('renders locked badge for locked workspaces', async () => {
    render(<WorkspaceSettingsSection />)

    await waitFor(() => {
      expect(screen.getByText('Locked Deployment')).toBeInTheDocument()
    })

    expect(screen.getByText('Locked')).toBeInTheDocument()
  })

  it('allows permanently deleting archived custom workspaces', async () => {
    render(<WorkspaceSettingsSection />)

    await waitFor(() => {
      expect(screen.getByText('Archived Project')).toBeInTheDocument()
    })

    const deleteBtn = screen.getByLabelText('Delete permanently')
    expect(deleteBtn).toBeInTheDocument()

    fireEvent.click(deleteBtn)

    expect(
      screen.getByText(
        'Are you sure you want to permanently delete this workspace? All files and database entries will be removed. This cannot be undone.'
      )
    ).toBeInTheDocument()

    const confirmBtn = screen.getByRole('button', { name: 'Permanently delete' })
    fireEvent.click(confirmBtn)

    await waitFor(() => {
      expect(fixture.deleteWorkspace).toHaveBeenCalledWith('ws-archived')
    })
  })
})
