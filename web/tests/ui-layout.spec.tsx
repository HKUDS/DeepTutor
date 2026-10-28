import { act, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { LayoutSidebarShell } from '@/features/ui-layout/slots'
import { useCapabilityLabel, useUiLayoutLabel } from '@/features/ui-layout/tokens'
import { applyExtensionPayload } from '@/lib/settings-extensions'
import { UI_LAYOUT_STORAGE_KEY, writeStoredUiLayout } from '@/lib/ui-layout'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/features/ui-layout/classic/ClassicSidebarShell', () => ({ ClassicSidebarShell: () => <nav>classic sidebar</nav> }))
vi.mock('@/components/sidebar/SidebarShell', () => ({ SidebarShell: () => <nav>modern sidebar</nav> }))

beforeEach(() => {
  localStorage.clear()
  document.documentElement.removeAttribute('data-ui-layout')
})

function Labels() {
  const space = useUiLayoutLabel('space')
  const capabilityLabel = useCapabilityLabel()
  return (
    <p>
      {[space, capabilityLabel({ value: '', label: 'Chat' }), capabilityLabel({ value: 'deep_solve', label: 'Deep Solve' })].join(' / ')}
    </p>
  )
}

it('renders the modern UI by default and switches slots and tokens together', () => {
  render(<><LayoutSidebarShell /><Labels /></>)
  expect(screen.getByText('modern sidebar')).toBeInTheDocument()
  expect(screen.getByText('navigation.resources / Auto / Deep Solve')).toBeInTheDocument()

  act(() => writeStoredUiLayout('classic'))

  expect(screen.getByText('classic sidebar')).toBeInTheDocument()
  expect(screen.queryByText('modern sidebar')).not.toBeInTheDocument()
  expect(screen.getByText('Learning Space / Chat / Deep Solve')).toBeInTheDocument()
  expect(document.documentElement).toHaveAttribute('data-ui-layout', 'classic')
})

it('applies a drafted layout with no endpoint and rejects unknown values', async () => {
  await applyExtensionPayload('ui-layout', 'classic')
  expect(localStorage.getItem(UI_LAYOUT_STORAGE_KEY)).toBe('classic')

  await expect(applyExtensionPayload('ui-layout', 'retro')).rejects.toThrow('Invalid UI layout')
  expect(localStorage.getItem(UI_LAYOUT_STORAGE_KEY)).toBe('classic')
})
