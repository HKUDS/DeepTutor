import React from 'react'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterAll, beforeAll, beforeEach, expect, it, vi } from 'vitest'
import SettingsMain from '@/components/settings/SettingsMain'
const mocks = vi.hoisted(() => ({ save: vi.fn(), push: vi.fn(), setActiveSection: vi.fn() }))
vi.mock('next/navigation', () => ({
  usePathname: () => '/settings/appearance',
  useRouter: () => ({ push: mocks.push }),
}))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/features/settings/store/SettingsStore', () => ({
  useSettings: () => ({
    hasUnsavedChanges: true,
    saveDraft: mocks.save,
    saving: false,
    applying: false,
    toast: 'Current save failed',
    setActiveSection: mocks.setActiveSection,
  }),
}))
vi.mock('@/components/settings/SettingsNav', () => ({ default: () => null }))
vi.mock('@/components/settings/SettingsToolbar', () => ({ SettingsToolbar: () => null }))
vi.mock('@/components/settings/SettingsLoadStatusBanner', () => ({
  SettingsLoadStatusBanner: () => null,
}))
vi.mock('@/components/common/Modal', () => ({
  default: ({ isOpen, children }: { isOpen: boolean; children: React.ReactNode }) =>
    isOpen ? <div role="dialog">{children}</div> : null,
}))
const priorScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollTo')
beforeAll(() =>
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
)
afterAll(() => {
  if (priorScroll) Object.defineProperty(HTMLElement.prototype, 'scrollTo', priorScroll)
  else Reflect.deleteProperty(HTMLElement.prototype, 'scrollTo')
})
beforeEach(() => {
  mocks.save.mockReset()
  mocks.push.mockReset()
})
it.each([null, true, false])(
  'handles save-before-leave result %s without confusing cancellation and failure',
  async result => {
    mocks.save.mockResolvedValue(result)
    render(
      <SettingsMain>
        <p>Appearance settings</p>
      </SettingsMain>
    )
    fireEvent.click(screen.getAllByRole('button', { name: 'Back to app' })[0])
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Save draft and return' }))
    })
    if (result === true) expect(mocks.push).toHaveBeenCalledWith('/')
    else expect(mocks.push).not.toHaveBeenCalled()
    if (result === false) expect(screen.getByRole('alert')).toHaveTextContent('Current save failed')
    else expect(screen.queryByRole('alert')).toBeNull()
  }
)
