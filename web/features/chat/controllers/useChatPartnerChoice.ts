import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'

import { RECOVERY_PRINCIPAL_CHANGED, recoveryPrincipal } from '@/lib/recovery-principal'
import { browserStorage } from '@/shared/storage'

type Choice = `partner:${string}` | `group:${string}` | null

function subscribePrincipal(listener: () => void) {
  window.addEventListener(RECOVERY_PRINCIPAL_CHANGED, listener)
  return () => window.removeEventListener(RECOVERY_PRINCIPAL_CHANGED, listener)
}

function readChoice(scope: 'local' | 'session', key: string): Choice {
  const raw = browserStorage.readRaw(scope, key)
  if (raw?.startsWith('partner:') && raw.length > 8) return raw as Choice
  if (raw?.startsWith('group:') && raw.length > 6) return raw as Choice
  return null
}

export function useChatPartnerChoice(
  chat: {
    sessionKey: string
    sessionId: string | null
    workspaceId: string | null
    boundFromKey?: string | null
  },
  repeat: { partner: boolean; partner_group: boolean }
) {
  const principal = useSyncExternalStore(subscribePrincipal, recoveryPrincipal, () => null)
  const prefix = `dt:chat:partner:${encodeURIComponent(principal ?? '')}:${encodeURIComponent(chat.workspaceId ?? '')}:`
  const scope = chat.sessionId ? 'local' : 'session'
  const key = prefix + encodeURIComponent(chat.sessionId ?? chat.sessionKey)
  const draftKey =
    chat.sessionId && chat.boundFromKey ? prefix + encodeURIComponent(chat.boundFromKey) : null

  function restore() {
    if (!principal) return null
    return readChoice(scope, key) ?? (draftKey ? readChoice('session', draftKey) : null)
  }

  const [current, setCurrent] = useState(() => ({ key, choice: restore() }))
  if (key !== current.key) {
    // A bound draft is still the same chat, including a pending one-turn choice.
    setCurrent({ key, choice: draftKey === current.key ? current.choice : restore() })
  }
  const choice = current.choice
  const remember = choice?.startsWith('partner:') ? repeat.partner : repeat.partner_group
  useEffect(() => {
    if (!principal || current.key !== key) return
    const saved =
      choice && remember
        ? browserStorage.writeRaw(scope, key, choice)
        : browserStorage.removeRaw(scope, key)
    if (saved && draftKey) browserStorage.removeRaw('session', draftKey)
  }, [principal, scope, key, current.key, choice, remember, draftKey])

  const setChoice = useCallback((next: Choice) => setCurrent({ key, choice: next }), [key])
  return {
    selectedPartner: choice?.startsWith('partner:') ? choice.slice(8) : null,
    selectedPartnerGroup: choice?.startsWith('group:') ? choice.slice(6) : null,
    setChoice,
  }
}
