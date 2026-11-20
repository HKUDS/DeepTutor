import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { useChatPartnerChoice } from '@/features/chat/controllers/useChatPartnerChoice'
import { updateRecoveryPrincipal } from '@/lib/recovery-principal'

const repeat = { partner: true, partner_group: true }
const draft = { sessionKey: 'draft_123', sessionId: null, workspaceId: 'school' }
const saved = {
  ...draft,
  sessionKey: 'session-a',
  sessionId: 'session-a',
  boundFromKey: draft.sessionKey,
}
beforeEach(() => updateRecoveryPrincipal({ enabled: true, authenticated: true, user_id: 'a' }))
afterEach(() => {
  act(() => updateRecoveryPrincipal(null))
  localStorage.clear()
  sessionStorage.clear()
})

it('moves a draft choice to its bound conversation and isolates accounts', () => {
  const first = renderHook(() => useChatPartnerChoice(draft, repeat))
  act(() => first.result.current.setChoice('group:study'))
  first.unmount()

  const bound = renderHook(() => useChatPartnerChoice(saved, repeat))
  expect(bound.result.current.selectedPartnerGroup).toBe('study')
  bound.unmount()
  const reopened = renderHook(() => useChatPartnerChoice({ ...saved, boundFromKey: null }, repeat))
  expect(reopened.result.current.selectedPartnerGroup).toBe('study')
  act(() => updateRecoveryPrincipal({ enabled: true, authenticated: true, user_id: 'b' }))
  expect(reopened.result.current.selectedPartnerGroup).toBeNull()
  reopened.unmount()
})

it('keeps a one-turn partner available for sending without restoring it on reload', () => {
  const view = renderHook(({ partner }) => useChatPartnerChoice(saved, { ...repeat, partner }), {
    initialProps: { partner: true },
  })
  act(() => view.result.current.setChoice('partner:one-time'))
  view.rerender({ partner: false })
  expect(view.result.current.selectedPartner).toBe('one-time')
  view.unmount()
  const reopened = renderHook(() => useChatPartnerChoice(saved, repeat))
  expect(reopened.result.current.selectedPartner).toBeNull()
  reopened.unmount()
})
