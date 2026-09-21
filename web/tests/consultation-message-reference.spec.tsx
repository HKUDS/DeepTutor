import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { UserMessage } from '@/features/chat/messages/ChatMessageList'
import { initI18n } from '@/i18n/init'

initI18n('en')
vi.mock('@/lib/partners-api', () => ({ getPartner: async () => ({ name: 'Frank' }) }))
vi.mock('@/lib/partner-groups-api', () => ({ getPartnerGroup: async () => ({ name: 'Study group' }) }))
vi.mock('@/hooks/useConnectedAgentKinds', () => ({ useConnectedAgentKinds: () => ({ Codex: 'codex' }) }))
afterEach(cleanup)

it.each([
  ['consult_partner_id', 'partner-1', 'Ask partner', 'Frank'],
  ['partner_discussion_group_id', 'group-1', 'Organize partner discussion', 'Study group'],
])('renders the selected %s underneath a sent message', async (key, id, kind, name) => {
  render(<UserMessage index={0} msg={{
    id: 1, role: 'user', content: 'What is an agent?',
    requestSnapshot: {
      content: 'What is an agent?', enabledTools: [], knowledgeBases: [], language: 'en',
      config: { [key]: id },
    },
  }} />)
  expect(screen.getByText(kind)).toBeVisible()
  expect(await screen.findByText(name)).toBeVisible()
})

it('keeps the subagent selection visible in the same reference tree', () => {
  render(<UserMessage index={0} msg={{
    role: 'user', content: 'Check this', requestSnapshot: {
      content: 'Check this', enabledTools: [], knowledgeBases: ['Codex'], language: 'en',
    },
  }} />)
  expect(screen.getByText('Ask subagent')).toBeVisible()
  expect(screen.getByText('Codex')).toBeVisible()
})

it('does not add consultation references to an ordinary message', () => {
  render(<UserMessage index={0} msg={{ role: 'user', content: 'Hello' }} />)
  expect(screen.queryByText('Ask partner')).toBeNull()
  expect(screen.queryByText('Organize partner discussion')).toBeNull()
})
