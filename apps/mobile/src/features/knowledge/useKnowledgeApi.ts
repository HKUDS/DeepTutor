import { useMemo } from 'react';

import { ApiClient } from '../../services/apiClient';
import { KnowledgeApi } from '../../services/knowledgeApi';

/** The part of the app session that decides which catalogue is being read. */
export interface KnowledgeSessionIdentity {
  phase: 'loading' | 'connect' | 'login' | 'chat';
  origin: string | null;
  status: { accountId: string } | null;
}

/**
 * A stable name for "this server, as this account".
 *
 * Hooks key their reload on this string rather than on the client object, so a
 * caller that rebuilds the client on every render cannot make them loop, while
 * a real sign-out, account switch or server change still clears the screen.
 */
export function knowledgeScope(session: KnowledgeSessionIdentity): string {
  if (session.phase !== 'chat' || !session.origin) return '';
  return `${session.origin}\u0000${session.status?.accountId ?? ''}`;
}

/**
 * One API client per (server, account) pair.
 *
 * The client itself carries no credentials — the cookie jar does — but a new
 * identity must get a new instance so every hook keyed on it re-reads the
 * catalogue. Reusing the previous account's client would keep its list, its
 * knowledge bases and its pending requests on screen after a switch.
 */
export function useKnowledgeApi(
  session: KnowledgeSessionIdentity,
): KnowledgeApi | null {
  const origin = session.origin;
  const scope = knowledgeScope(session);

  return useMemo(() => {
    if (!scope || !origin) return null;
    return new KnowledgeApi(new ApiClient(origin));
  }, [scope, origin]);
}
