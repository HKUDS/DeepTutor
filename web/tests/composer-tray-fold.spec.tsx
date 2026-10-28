import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { ComposerTray } from '@/components/chat/home/ComposerTray'
import { CHAT_CAPABILITIES } from '@/features/capabilities/presentation'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/lib/personas-api', () => ({ listPersonas: async () => [] }))
vi.mock('next/link', () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

const KEY = 'deeptutor.composer-tray'

function renderTray(answer: { open?: boolean; onOpenChange?: (open: boolean) => void } = {}) {
  const view = render(<ComposerTray placement="down" answer={answer} />)
  const tray = view.container.querySelector('.dt-composer-tray') as HTMLElement
  // jsdom has no stylesheet; give the sheet the travel the stylesheet sets.
  tray.style.setProperty('--dt-tray-travel', '23px')
  return { ...view, tray }
}

function drag(target: HTMLElement, from: number, to: number) {
  fireEvent.pointerDown(target, { button: 0, pointerId: 1, clientY: from })
  fireEvent.pointerMove(target, { pointerId: 1, clientY: from + Math.sign(to - from) * 6 })
  fireEvent.pointerMove(target, { pointerId: 1, clientY: to })
  fireEvent.pointerUp(target, { pointerId: 1, clientY: to })
}

beforeEach(() => {
  localStorage.clear()
})

it('offers Visualize once even when the full catalog includes the legacy animator', () => {
  const onChange = vi.fn()
  render(<ComposerTray placement="down" mode={{ capabilities: CHAT_CAPABILITIES, value: '', onChange }} />)
  fireEvent.click(screen.getByRole('button', { name: 'Mode' }))
  expect(screen.getAllByText('Visualize')).toHaveLength(1)
  expect(screen.queryByText('Math Animator')).not.toBeInTheDocument()
  fireEvent.click(screen.getByText('Visualize'))
  expect(onChange).toHaveBeenCalledWith('visualize')
})

it('folds behind the composer from its grip, and opens again from the lip', () => {
  const { tray } = renderTray()
  const grip = screen.getByRole('button', { name: 'Collapse' })
  expect(grip).toHaveAttribute('aria-expanded', 'true')

  fireEvent.click(grip)
  expect(tray).toHaveAttribute('data-folded')
  expect(localStorage.getItem(KEY)).toBe('folded')
  // Out of reach while folded: the row cannot be tabbed into.
  expect(tray.querySelector('.dt-tray-bar')).toHaveAttribute('inert')
  expect(screen.getByRole('button', { name: 'Expand' })).toHaveAttribute('aria-expanded', 'false')

  // Anywhere on the folded lip opens it.
  fireEvent.click(tray)
  expect(tray).not.toHaveAttribute('data-folded')
  expect(localStorage.getItem(KEY)).toBe('open')
})

it('follows a drag: past halfway it folds, a nudge springs back', () => {
  const { tray } = renderTray()
  const grip = screen.getByRole('button', { name: 'Collapse' })

  drag(grip, 300, 290)
  expect(tray).not.toHaveAttribute('data-folded')

  drag(grip, 300, 270)
  expect(tray).toHaveAttribute('data-folded')
  // The click that ends a drag is not a second toggle.
  fireEvent.click(grip)
  expect(tray).toHaveAttribute('data-folded')

  drag(tray, 270, 300)
  expect(tray).not.toHaveAttribute('data-folded')
})

it('keeps following a pull that leaves the folded lip at once', () => {
  localStorage.setItem(KEY, 'folded')
  const { tray } = renderTray()
  fireEvent.pointerDown(tray, { button: 0, pointerId: 2, clientY: 300 })
  // The lip is 11px tall: the pull is over the page below it from the start.
  fireEvent.pointerMove(document.body, { pointerId: 2, clientY: 306 })
  fireEvent.pointerMove(document.body, { pointerId: 2, clientY: 324 })
  expect(tray).toHaveAttribute('data-dragging')
  fireEvent.pointerUp(document.body, { pointerId: 2, clientY: 324 })
  expect(tray).not.toHaveAttribute('data-folded')
  expect(tray).not.toHaveAttribute('data-dragging')

  // The press is over: moving across the page afterwards drags nothing.
  fireEvent.pointerMove(document.body, { pointerId: 2, clientY: 200 })
  expect(tray).not.toHaveAttribute('data-dragging')
})

it('leaves its own controls alone: pressing a menu opens the menu, not a drag', () => {
  const { tray } = renderTray()
  const trigger = screen.getByRole('button', { name: /Preferences/ })
  drag(trigger, 300, 260)
  expect(tray).not.toHaveAttribute('data-folded')
})

it('answers the arrow keys on its grip', () => {
  const { tray } = renderTray()
  fireEvent.keyDown(screen.getByRole('button', { name: 'Collapse' }), { key: 'ArrowUp' })
  expect(tray).toHaveAttribute('data-folded')
  fireEvent.keyDown(screen.getByRole('button', { name: 'Expand' }), { key: 'ArrowDown' })
  expect(tray).not.toHaveAttribute('data-folded')
})

it('comes out for a list opened from elsewhere, without unfolding for good', () => {
  localStorage.setItem(KEY, 'folded')
  const onOpenChange = vi.fn()
  const view = renderTray({ open: false, onOpenChange })
  expect(view.tray).toHaveAttribute('data-folded')

  act(() => view.rerender(<ComposerTray placement="down" answer={{ open: true, onOpenChange }} />))
  expect(view.tray).not.toHaveAttribute('data-folded')
  expect(localStorage.getItem(KEY)).toBe('folded')

  act(() => view.rerender(<ComposerTray placement="down" answer={{ open: false, onOpenChange }} />))
  expect(view.tray).toHaveAttribute('data-folded')
})
