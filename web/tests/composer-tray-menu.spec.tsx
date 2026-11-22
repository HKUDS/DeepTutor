import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { TrayList, TrayMenu, TrayOption } from '@/components/chat/home/ComposerTrayMenu'
import { ComposerTray } from '@/components/chat/home/ComposerTray'
import { CHAT_CAPABILITIES } from '@/features/capabilities/presentation'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

function renderMenu() {
  const select = vi.fn()
  render(
    <TrayMenu icon={null} label="Study choices" placement="up">
      {() => (
        <TrayList label="Study choices">
          {['First', 'Last'].map(title => (
            <TrayOption
              key={title}
              title={title}
              selected={false}
              leading={null}
              onSelect={select}
            />
          ))}
        </TrayList>
      )}
    </TrayMenu>
  )
  const trigger = screen.getByRole('button', { name: 'Study choices' })
  fireEvent.click(trigger)
  return { trigger, select }
}

it('keeps an inside mouse press open and dismisses on an outside press', async () => {
  const { trigger, select } = renderMenu()
  const last = screen.getByRole('option', { name: 'Last' })
  fireEvent.mouseDown(last)
  fireEvent.click(last)
  expect(select).toHaveBeenCalledOnce()
  expect(trigger).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByRole('dialog', { name: 'Study choices' })).toBeInTheDocument()
  fireEvent.mouseDown(document.body)
  expect(trigger).toHaveAttribute('aria-expanded', 'false')
})

it('navigates the options and returns focus to the trigger with Escape', async () => {
  const { trigger } = renderMenu()
  const first = screen.getByRole('option', { name: 'First' })
  const last = screen.getByRole('option', { name: 'Last' })
  last.scrollIntoView = vi.fn()
  await waitFor(() => expect(first).toHaveFocus())
  fireEvent.keyDown(first, { key: 'End' })
  expect(last).toHaveFocus()
  fireEvent.keyDown(last, { key: 'Escape' })
  expect(trigger).toHaveFocus()
  expect(trigger).toHaveAttribute('aria-expanded', 'false')
})

it('does not start folding the tray when dragging inside an open menu', () => {
  const view = render(
    <ComposerTray
      placement="up"
      mode={{ capabilities: CHAT_CAPABILITIES, value: '', onChange: vi.fn() }}
    />
  )
  const tray = view.container.querySelector('.dt-composer-tray')!
  fireEvent.click(screen.getByRole('button', { name: 'Mode' }))
  const option = screen.getAllByRole('option')[0]
  fireEvent.pointerDown(option, { button: 0, pointerId: 1, clientY: 300 })
  fireEvent.pointerMove(document.body, { pointerId: 1, clientY: 294 })
  fireEvent.pointerMove(document.body, { pointerId: 1, clientY: 260 })
  expect(tray).not.toHaveAttribute('data-dragging')
  fireEvent.pointerUp(document.body, { pointerId: 1, clientY: 260 })
  expect(tray).not.toHaveAttribute('data-folded')
})
