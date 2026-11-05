import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import PartnerDetailPage from '@/app/(workspace)/partners/[partnerId]/page'
import { loadPartnerSessionKey } from '@/lib/partner-session'
import { initI18n } from '@/i18n/init'

const state = vi.hoisted(() => ({
  query: 'session=web-old',
  router: { replace: vi.fn(), push: vi.fn() },
  continuity: vi.fn(),
  select: vi.fn(),
}))
vi.mock('next/navigation', () => ({
  useParams: () => ({ partnerId: 'ada' }),
  useSearchParams: () => new URLSearchParams(state.query),
  useRouter: () => state.router,
}))
vi.mock('@/hooks/useAuthStatus', () => ({
  useAuthStatus: () => ({
    loading: false,
    enabled: false,
    userId: 'local-admin',
    isAdmin: true,
    statusAvailable: true,
  }),
}))
vi.mock('@/lib/partners-api', () => ({
  getPartner: async () => ({ partner_id: 'ada', name: 'Ada', running: false, can_manage: false }),
  getPartnerSessions: async () => [
    { session_key: 'web-old', title: 'Old', archived: false },
    { session_key: 'web-other', title: 'Other', archived: false },
    { session_key: 'web-archived', title: 'Archived', archived: true },
  ],
  getPartnerWebContinuity: state.continuity,
  setPartnerWebContinuity: state.select,
}))
vi.mock('@/components/partners/PartnerChat', () => ({
  default: ({
    sessionKey,
    onSessionKeyChange,
  }: {
    sessionKey: string
    onSessionKeyChange: (key: string) => void
  }) => (
    <>
      <output aria-label="Current session">{sessionKey}</output>
      <button onClick={() => onSessionKeyChange('web-other')}>Choose another session</button>
    </>
  ),
}))
vi.mock('@/components/partners/PartnerConfigure', () => ({ default: () => null }))
vi.mock('@/components/partners/PartnerChannels', () => ({ default: () => null }))
vi.mock('@/components/partners/PartnerArchives', () => ({ default: () => null }))
vi.mock('@/components/notebook/SaveToNotebookModal', () => ({ default: () => null }))
initI18n('en')

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  state.query = 'session=web-old'
  state.continuity.mockResolvedValue({ enabled: false, session_key: null })
  state.select.mockImplementation(async (_id, selection) => selection)
})

it('opens the exact linked legacy session and keeps manual selection and reload URL consistent', async () => {
  render(<PartnerDetailPage />)
  await waitFor(() => expect(screen.getByLabelText('Current session')).toHaveTextContent('web-old'))
  expect(loadPartnerSessionKey('ada', 'local-admin')).toBe('web-old')
  fireEvent.click(screen.getByRole('button', { name: 'Choose another session' }))
  await waitFor(() =>
    expect(state.router.replace).toHaveBeenCalledWith('/partners/ada?session=web-other', {
      scroll: false,
    })
  )
  expect(loadPartnerSessionKey('ada', 'local-admin')).toBe('web-other')
})

it("rejects unavailable and archived links without replacing the browser's current session", async () => {
  state.query = 'session=web-archived'
  render(<PartnerDetailPage />)
  await screen.findByText('This conversation is unavailable or archived. Open history to find it.')
  expect(screen.getByLabelText('Current session')).not.toHaveTextContent('web-archived')
  expect(state.select).not.toHaveBeenCalled()
})

it('resolves linked sessions through the existing shared-continuity selection API', async () => {
  state.continuity.mockResolvedValue({ enabled: true, session_key: 'web-other' })
  render(<PartnerDetailPage />)
  await waitFor(() =>
    expect(state.select).toHaveBeenCalledWith('ada', { enabled: true, session_key: 'web-old' })
  )
  expect(screen.getByLabelText('Current session')).toHaveTextContent('web-old')
})
