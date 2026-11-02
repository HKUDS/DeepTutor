import { render, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import PartnerDetailPage from '@/app/(workspace)/partners/[partnerId]/page'
import { initI18n } from '@/i18n/init'

const getPartner = vi.hoisted(() => vi.fn())
vi.mock('next/navigation', () => ({
  // Next.js keeps a non-ASCII dynamic segment URL-encoded in useParams().
  useParams: () => ({ partnerId: '%E6%80%9D%E8%A8%80' }),
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
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
  getPartner,
  getPartnerSessions: async () => [],
  getPartnerWebContinuity: async () => ({ enabled: false, session_key: null }),
  setPartnerWebContinuity: async (_id: string, selection: unknown) => selection,
}))
vi.mock('@/components/partners/PartnerChat', () => ({ default: () => null }))
vi.mock('@/components/partners/PartnerConfigure', () => ({ default: () => null }))
vi.mock('@/components/partners/PartnerChannels', () => ({ default: () => null }))
vi.mock('@/components/partners/PartnerArchives', () => ({ default: () => null }))
vi.mock('@/components/notebook/SaveToNotebookModal', () => ({ default: () => null }))
initI18n('en')

it('loads a partner whose non-ASCII id arrives URL-encoded from the route', async () => {
  getPartner.mockResolvedValue({ partner_id: '思言', name: '思言', running: false, can_manage: false })
  render(<PartnerDetailPage />)
  await waitFor(() => expect(getPartner).toHaveBeenCalledWith('思言'))
})
