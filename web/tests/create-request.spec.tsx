import { render, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useCreateRequest } from '@/components/learning/create-request'

const mocks = vi.hoisted(() => ({ replace: vi.fn(), query: '' }))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: mocks.replace }),
  usePathname: () => '/learning/books',
  useSearchParams: () => new URLSearchParams(mocks.query),
}))
function Creation({ open }: { open: () => void }) {
  useCreateRequest(open)
  return null
}
beforeEach(() => {
  vi.clearAllMocks()
  mocks.query = ''
})
it('opens creation after client navigation even before window.location reflects the new query', async () => {
  const open = vi.fn()
  const view = render(<Creation open={open} />)
  mocks.query = 'create=1&dt_workspace=other'
  view.rerender(<Creation open={open} />)
  await waitFor(() => expect(open).toHaveBeenCalledOnce())
  expect(mocks.replace).toHaveBeenCalledWith('/learning/books?dt_workspace=other', { scroll: false })
})
