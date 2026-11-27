import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import AnswerModeMenu, { PartnerLinkMenu } from '@/components/chat/home/AnswerModeMenu'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/lib/personas-api', () => ({ listPersonas: async () => [] }))
vi.mock('next/link', () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

const ada = { partner_id: 'p1', name: 'Ada', emoji: '', color: '', avatar: '' } as never

it('hands the turn to a partner or an agent, and takes it back', () => {
  const onChange = vi.fn()
  const view = render(
    <AnswerModeMenu
      placement="down"
      answerers={{ value: null, onChange, partners: [ada], agents: [{ name: 'Claude Code', kind: 'claude_code' }] }}
    />,
  )
  fireEvent.click(screen.getByRole('button', { name: /Preferences/ }))
  fireEvent.click(screen.getByRole('option', { name: /Ada/ }))
  expect(onChange).toHaveBeenLastCalledWith('partner:p1')

  view.rerender(
    <AnswerModeMenu
      placement="down"
      answerers={{ value: 'partner:p1', onChange, partners: [ada], agents: [{ name: 'Claude Code', kind: 'claude_code' }] }}
    />,
  )
  // The trigger names whoever answers now.
  expect(screen.getByRole('button', { name: /Preferences.*Ada/ })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /Preferences/ }))
  fireEvent.click(screen.getByRole('option', { name: /Claude Code/ }))
  expect(onChange).toHaveBeenLastCalledWith('subagent:Claude Code')
  fireEvent.click(screen.getByRole('button', { name: /Preferences/ }))
  fireEvent.click(screen.getByRole('option', { name: /composer\.tray\.deeptutor/ }))
  expect(onChange).toHaveBeenLastCalledWith(null)
})

it('keeps asking partners apart from handing over, with the way to manage them', () => {
  const onPartner = vi.fn()
  const onGroup = vi.fn()
  render(
    <PartnerLinkMenu
      placement="up"
      partners={{ options: [ada], selected: null, onSelect: onPartner }}
      groups={{
        options: [{ group_id: 'g1', name: 'Study circle', emoji: '', members: [{ name: 'Ada' }] }] as never,
        selected: null,
        onSelect: onGroup,
      }}
    />,
  )
  fireEvent.click(screen.getByRole('button', { name: /Partners/ }))
  expect(screen.getByRole('group', { name: 'Ask partner' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Create a Partner Group/ })).toHaveAttribute('href', '/partners/groups/new')
  fireEvent.click(screen.getByRole('option', { name: /Study circle/ }))
  expect(onGroup).toHaveBeenCalledWith('g1')
  expect(onPartner).not.toHaveBeenCalled()
})
