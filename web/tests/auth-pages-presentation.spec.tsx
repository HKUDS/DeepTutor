import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

/**
 * The auth screens are the product's first impression, and the redesign moved
 * their chrome around. These render the real components — not a copy of the
 * markup — so a broken wrapper or a lost form field fails here.
 *
 * Behaviour is deliberately out of scope: the submit handler, the
 * `mustChangePassword` redirect and the return-URL tab handling are covered by
 * `auth-return-url.test.ts` and `auth-status-singleflight.spec.ts`. This file
 * only guarantees the page still renders as a usable sign-in form.
 */

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'fa' } }),
}))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))
vi.mock('@/lib/auth', () => ({
  login: vi.fn(async () => ({ ok: false })),
  fetchAuthStatus: vi.fn(async () => ({ authenticated: false })),
  checkIsFirstUser: vi.fn(async () => false),
  register: vi.fn(async () => ({ ok: false })),
  checkRegistrationAllowed: vi.fn(async () => ({ allowed: true })),
}))

it('renders the sign-in form inside the two-column shell', async () => {
  const { default: LoginPage } = await import('@/app/(auth)/login/page')
  const { container } = render(<LoginPage />)

  // The username field still exists and is still labelled — the redesign must
  // not have swallowed the form.
  expect(await screen.findByLabelText('Email or username')).toBeTruthy()
  expect(screen.getByLabelText('Password')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Sign in' })).toBeTruthy()

  // Two-column shell: the brand panel is a sibling `aside` of the form column.
  expect(container.querySelector('aside')).toBeTruthy()
})

it('names the product in the brand panel', async () => {
  const { AuthBrandPanel } = await import('@/components/auth/AuthBrandPanel')
  const { container } = render(<AuthBrandPanel />)

  const aside = container.querySelector('aside')
  expect(aside).toBeTruthy()
  // The mark is decorative; the heading carries the name.
  expect(aside!.querySelector('img')?.getAttribute('alt')).toBe('')
  expect(aside!.textContent).toContain('Darsyar')
})

it('keeps the brand panel out of the reading order on small screens', async () => {
  const { AuthBrandPanel } = await import('@/components/auth/AuthBrandPanel')
  const { container } = render(<AuthBrandPanel />)
  const aside = container.querySelector('aside')
  // `hidden lg:flex` — visible only once there is room for two columns.
  expect(aside!.className).toContain('hidden')
  expect(aside!.className).toContain('lg:flex')
  // Mirrors with the page direction rather than a physical border.
  expect(aside!.className).toContain('border-e')
})

it('renders a separate admin sign-in that names its own purpose', async () => {
  const { default: AdminLoginPage } = await import('@/app/(admin)/admin/login/page')
  render(<AdminLoginPage />)

  // It must be distinguishable from /login, or the separate entrance is
  // pointless: same fields, different framing.
  expect(await screen.findByText('Sign in to the admin panel')).toBeTruthy()
  expect(screen.getByLabelText('Email or username')).toBeTruthy()
  expect(screen.getByLabelText('Password')).toBeTruthy()
  // A way back, so an operator who landed here by mistake is not stuck.
  expect(screen.getByRole('link', { name: 'Back to the learning app' })).toBeTruthy()
})
