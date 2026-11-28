import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterAll, beforeAll, beforeEach, expect, it, vi } from 'vitest'
import SettingsMain from '@/components/settings/SettingsMain'

const mocks = vi.hoisted(() => ({ push: vi.fn(), setActiveSection: vi.fn() }))
vi.mock('next/navigation', () => ({
  usePathname: () => '/settings/general',
  useRouter: () => ({ push: mocks.push }),
}))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/features/settings/store/SettingsStore', () => ({
  useSettings: () => ({
    hasUnsavedChanges: true,
    saveDraft: vi.fn(),
    saving: false,
    applying: false,
    toast: '',
    setActiveSection: mocks.setActiveSection,
  }),
}))
vi.mock('@/components/settings/SettingsNav', () => ({ default: () => null }))
vi.mock('@/components/settings/SettingsToolbar', () => ({ SettingsToolbar: () => null }))
vi.mock('@/components/settings/SettingsLoadStatusBanner', () => ({
  SettingsLoadStatusBanner: () => null,
}))
vi.mock('@/components/common/Modal', () => ({
  default: ({
    isOpen,
    title,
    children,
  }: {
    isOpen: boolean
    title?: string
    children: React.ReactNode
  }) =>
    isOpen ? (
      <div role="dialog">
        {title}
        {children}
      </div>
    ) : null,
}))

const priorScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollTo')
beforeAll(() =>
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
)
afterAll(() => {
  if (priorScroll) Object.defineProperty(HTMLElement.prototype, 'scrollTo', priorScroll)
  else Reflect.deleteProperty(HTMLElement.prototype, 'scrollTo')
})
beforeEach(() => mocks.push.mockReset())

// The floating card behaves like a dialog: Escape and a scrim click are exits,
// and neither may drop an unsaved draft without asking first.
it('Escape asks before leaving with unsaved changes', () => {
  render(
    <SettingsMain>
      <p>General settings</p>
    </SettingsMain>
  )
  fireEvent.keyDown(window, { key: 'Escape' })
  expect(screen.getByRole('dialog')).toHaveTextContent('Keep your changes?')
  expect(mocks.push).not.toHaveBeenCalled()
})

it('clicking the scrim asks before leaving with unsaved changes', () => {
  const { container } = render(
    <SettingsMain>
      <p>General settings</p>
    </SettingsMain>
  )
  fireEvent.mouseDown(container.querySelector('[data-settings-shell]') as HTMLElement)
  expect(screen.getByRole('dialog')).toHaveTextContent('Keep your changes?')
  expect(mocks.push).not.toHaveBeenCalled()
})
