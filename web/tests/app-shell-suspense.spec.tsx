import { act, render, screen } from '@testing-library/react'
import { lazy, Suspense, type ComponentType } from 'react'
import { expect, it, vi } from 'vitest'
import AppShell from '@/components/layout/AppShell'

vi.mock('next/navigation', () => ({ usePathname: () => '/learning' }))
vi.mock('next/image', () => ({ default: () => null }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/hooks/useDevice', () => ({ useDevice: () => ({ isMobile: false }) }))

it('keeps the application navigation visible while a feature module loads', async () => {
  let finish!: (module: { default: ComponentType }) => void
  const Feature = lazy(() => new Promise<{ default: ComponentType }>(resolve => { finish = resolve }))
  render(<Suspense fallback={<p>Whole page replaced</p>}><AppShell sidebar={<nav>Persistent navigation</nav>}><Feature /></AppShell></Suspense>)
  expect(screen.getByText('Persistent navigation')).toBeVisible()
  expect(screen.queryByText('Whole page replaced')).not.toBeInTheDocument()
  await act(async () => finish({ default: () => <p>Loaded feature</p> }))
  expect(screen.getByText('Loaded feature')).toBeVisible()
  expect(screen.getByText('Persistent navigation')).toBeVisible()
})
