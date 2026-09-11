import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ReadingWorkspacePage } from '@/components/reading/workspace/ReadingWorkspace'

const LEARNING_KEY = 'reading-learning'

vi.mock('next/navigation', () => ({
  useParams: () => ({ workspaceId: 'reading-1' }),
  usePathname: () => '/reading/reading-1',
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (value: string) => value }),
}))
vi.mock('@/features/chat/ChatStateAdapter', () => ({
  useChatStateAdapter: () => ({
    state: { isStreaming: false, sessionId: null },
    sendMessage: vi.fn(),
  }),
}))
vi.mock('@/components/reading/workspace/useReadingWorkspace', () => ({
  useReadingWorkspace: () => ({
    workspace: {
      workspace_id: 'reading-1',
      title: 'Immersive Reading',
      tabs: [],
      active_material_id: null,
    },
    setWorkspace: vi.fn(),
    conversations: [],
    setConversations: vi.fn(),
    loading: false,
    error: null,
    notice: null,
    setNotice: vi.fn(),
    material: null,
    annotations: [],
    activeTab: undefined,
    activeConversation: null,
    linkedSessionIds: [],
    activeLocator: null,
    setActiveLocator: vi.fn(),
    transcript: [],
    organizedNotes: null,
    setOrganizedNotes: vi.fn(),
    refresh: vi.fn(),
    switchMaterial: vi.fn(),
    removeMaterial: vi.fn(),
    newConversation: vi.fn(),
    openConversation: vi.fn(),
    renameConversation: vi.fn(),
    deleteConversation: vi.fn(),
    organizeNotes: vi.fn(),
    buildMasteryPath: vi.fn(),
    renameWorkspace: vi.fn(),
    reportViewport: vi.fn(),
  }),
}))
vi.mock('@/components/reading/ReaderPane', () => ({
  ReaderPane: () => null,
  READER_ASK_EVENT: 'dt:reader-ask',
}))
vi.mock('@/components/reading/workspace/SourceNavigator', () => ({
  SourceNavigator: ({ open }: { open: boolean }) => (
    <div data-testid="reading-navigator" data-open={String(open)}>
      navigator
    </div>
  ),
}))
vi.mock('@/components/reading/workspace/ReadingCompanion', () => ({
  ReadingCompanion: () => <div data-testid="reading-companion" />,
}))
vi.mock('@/components/reading/workspace/MediaReadingStage', () => ({
  MediaReadingStage: () => null,
}))
vi.mock('@/components/reading/library/AddMaterialsDialog', () => ({
  AddMaterialsDialog: () => null,
}))
vi.mock('@/components/reading/workspace/WorkspaceChrome', () => ({
  CompanionWelcome: () => null,
  EmptyWorkspace: () => null,
  MaterialFailure: () => null,
  MaterialProcessing: () => null,
  MenuItem: ({ label }: { label: string }) => <span>{label}</span>,
  iconForMaterial: () => () => null,
}))
vi.mock('@/components/reading/workspace/dialogs', () => ({
  ConversationLinkDialog: () => null,
  ConversationMenu: () => null,
  NotebookCaptureDialog: () => null,
  OrganizedNotesDialog: () => null,
  WorkspaceConfirmDialog: () => null,
  WorkspaceValueDialog: () => null,
}))

function visibleDialog() {
  const dialog = document.createElement('div')
  dialog.setAttribute('role', 'dialog')
  dialog.getBoundingClientRect = () => ({ width: 100 }) as unknown as DOMRect
  document.body.appendChild(dialog)
  return dialog
}

describe('reading fullscreen learning', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: query === '(min-width: 1280px)',
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    })
  })

  it('fills the shell, isolates surrounding UI, closes panels, and restores them', async () => {
    const user = userEvent.setup()
    const shell = document.createElement('div')
    const sidebar = document.createElement('aside')
    // jsdom has no inert property, but the effect must preserve the original
    // value rather than just remove an attribute it did not own.
    Object.defineProperty(sidebar, 'inert', {
      configurable: true,
      value: false,
      writable: true,
    })
    const content = document.createElement('div')
    shell.append(sidebar, content)
    document.body.appendChild(shell)
    render(<ReadingWorkspacePage />, { container: content })

    const root = screen.getByRole('main')
    expect(root).toHaveAttribute('data-reading-workspace')
    expect(root).not.toHaveAttribute('data-learning')
    expect(screen.getByTestId('reading-navigator')).toHaveAttribute('data-open', 'true')
    expect(screen.getByTestId('reading-companion')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Fullscreen learning' }))
    expect(root).toHaveAttribute('data-learning', 'true')
    expect(screen.getByTestId('reading-navigator')).toHaveAttribute('data-open', 'true')
    expect(screen.queryByTestId('reading-companion')).not.toBeInTheDocument()
    await waitFor(() => expect(sidebar.inert).toBe(true))

    await user.click(screen.getByRole('button', { name: 'Exit learning mode' }))
    expect(root).not.toHaveAttribute('data-learning')
    expect(screen.getByTestId('reading-navigator')).toHaveAttribute('data-open', 'true')
    expect(screen.getByTestId('reading-companion')).toBeInTheDocument()
    expect(sidebar.inert).not.toBe(true)
    expect(sidebar.hasAttribute('inert')).toBe(false)
    expect(sessionStorage.getItem(LEARNING_KEY)).toBeNull()
  })

  it('does not steal Escape while a dialog is visible', async () => {
    const user = userEvent.setup()
    const dialog = visibleDialog()
    render(<ReadingWorkspacePage />)
    await user.click(screen.getByRole('button', { name: 'Fullscreen learning' }))
    await user.keyboard('{Escape}')
    expect(screen.getByRole('main')).toHaveAttribute('data-learning', 'true')

    dialog.remove()
    await user.keyboard('{Escape}')
    expect(screen.getByRole('main')).not.toHaveAttribute('data-learning')
  })

  it('expands and collapses contents while learning mode is active', async () => {
    const user = userEvent.setup()
    render(<ReadingWorkspacePage />)

    await user.click(screen.getByRole('button', { name: 'Fullscreen learning' }))
    expect(screen.getByTestId('reading-navigator')).toHaveAttribute('data-open', 'true')

    await user.click(screen.getByRole('button', { name: 'Collapse contents' }))
    expect(screen.getByTestId('reading-navigator')).toHaveAttribute('data-open', 'false')
    expect(screen.getByRole('button', { name: 'Reading companion' })).toHaveAttribute(
      'aria-expanded',
      'false'
    )

    await user.click(screen.getByRole('button', { name: 'Expand contents' }))
    expect(screen.getByTestId('reading-navigator')).toHaveAttribute('data-open', 'true')

    await user.click(screen.getByRole('button', { name: 'Exit learning mode' }))
    expect(screen.getByTestId('reading-navigator')).toHaveAttribute('data-open', 'true')
  })

  it("restores the same workspace's saved learning mode and entry panels", async () => {
    const user = userEvent.setup()
    sessionStorage.setItem(
      LEARNING_KEY,
      JSON.stringify({
        workspaceId: 'reading-1',
        panels: {
          companionOpen: true,
          navigatorOpen: false,
          navigatorCollapsed: false,
        },
      })
    )
    render(<ReadingWorkspacePage />)
    await waitFor(() => expect(screen.getByRole('main')).toHaveAttribute('data-learning', 'true'))
    expect(screen.getByTestId('reading-navigator')).toHaveAttribute('data-open', 'true')
    expect(screen.queryByTestId('reading-companion')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Exit learning mode' }))
    expect(screen.getByRole('main')).not.toHaveAttribute('data-learning')
    expect(screen.getByTestId('reading-companion')).toBeInTheDocument()
    expect(sessionStorage.getItem(LEARNING_KEY)).toBeNull()
  })
})
