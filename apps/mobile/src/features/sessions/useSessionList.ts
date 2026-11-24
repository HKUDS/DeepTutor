import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { ApiError } from '../../services/apiClient';
import type { SessionApi, SessionSummary } from '../../services/sessionApi';

const PAGE_SIZE = 30;

export interface SessionListState {
  sessions: SessionSummary[];
  /** `loading` only covers the first page; later pages use `loadingMore`. */
  status: 'loading' | 'ready' | 'failed';
  refreshing: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  error: string | null;
}

const emptyState: SessionListState = {
  sessions: [],
  status: 'loading',
  refreshing: false,
  loadingMore: false,
  hasMore: false,
  error: null,
};

function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.kind === 'unauthorized') {
      return 'Sign in again to see your conversations.';
    }
    if (error.kind === 'network' || error.kind === 'timeout') {
      return 'Could not reach the server. Check your connection.';
    }
  }
  return 'Could not load your conversations.';
}

/** A row can move between offset pages while the index loads; keep one copy. */
function dedupe(rows: SessionSummary[]): SessionSummary[] {
  const seen = new Set<string>();
  const unique: SessionSummary[] = [];
  for (const row of rows) {
    if (seen.has(row.id)) continue;
    seen.add(row.id);
    unique.push(row);
  }
  return unique;
}

/**
 * Paginated conversation index. Every request is stamped with a generation so a
 * slow refresh cannot overwrite rows a later request already delivered.
 */
export function useSessionList(
  api: SessionApi | null,
  workspaceId?: string,
) {
  const [state, setState] = useState<SessionListState>(emptyState);
  const generation = useRef(0);
  const mounted = useRef(true);
  const inFlight = useRef<AbortController | null>(null);
  // The client is held in a ref so an inline `new SessionApi(...)` in a render
  // body cannot restart the index on every frame.
  const apiRef = useRef<SessionApi | null>(api);
  const enabled = api !== null;
  const rows = useRef<SessionSummary[]>([]);
  const hasMore = useRef(false);
  const busy = useRef(false);

  useEffect(() => {
    apiRef.current = api;
  }, [api]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      inFlight.current?.abort();
    };
  }, []);

  const load = useCallback(
    async (mode: 'initial' | 'refresh' | 'more') => {
      const sessionApi = apiRef.current;
      if (!sessionApi) return;
      if (busy.current) return;
      if (mode === 'more' && !hasMore.current) return;
      busy.current = true;
      inFlight.current?.abort();
      const controller = new AbortController();
      inFlight.current = controller;
      const token = ++generation.current;

      setState(current =>
        mode === 'more'
          ? { ...current, loadingMore: true, error: null }
          : mode === 'refresh'
            ? { ...current, refreshing: true, error: null }
            : { ...current, status: 'loading', error: null },
      );

      try {
        const page = await sessionApi.list(
          {
            limit: PAGE_SIZE,
            offset: mode === 'more' ? rows.current.length : 0,
            workspaceId,
          },
          controller.signal,
        );
        if (!mounted.current || token !== generation.current) return;
        const merged =
          mode === 'more' ? dedupe([...rows.current, ...page.sessions]) : page.sessions;
        rows.current = merged;
        hasMore.current = page.hasMore;
        setState({
          sessions: merged,
          status: 'ready',
          refreshing: false,
          loadingMore: false,
          hasMore: page.hasMore,
          error: null,
        });
      } catch (error) {
        if (!mounted.current || token !== generation.current) return;
        if (error instanceof ApiError && error.kind === 'aborted') return;
        setState(current => ({
          ...current,
          status: mode === 'initial' ? 'failed' : 'ready',
          refreshing: false,
          loadingMore: false,
          error: messageFor(error),
        }));
      } finally {
        if (token === generation.current) busy.current = false;
      }
    },
    [workspaceId],
  );

  useEffect(() => {
    if (!enabled) return;
    // A workspace change starts a new index instead of extending the old one.
    rows.current = [];
    hasMore.current = false;
    load('initial');
  }, [load, enabled]);

  const refresh = useCallback(() => load('refresh'), [load]);
  const loadMore = useCallback(() => load('more'), [load]);
  const retry = useCallback(() => load('initial'), [load]);

  const rename = useCallback(
    async (sessionId: string, title: string) => {
      const sessionApi = apiRef.current;
      const trimmed = title.trim();
      if (!sessionApi || !trimmed) return;
      const saved = await sessionApi.rename(sessionId, trimmed);
      if (!mounted.current) return;
      rows.current = rows.current.map(session =>
        session.id === sessionId ? { ...session, title: saved } : session,
      );
      setState(current => ({
        ...current,
        sessions: current.sessions.map(session =>
          session.id === sessionId ? { ...session, title: saved } : session,
        ),
      }));
    },
    [],
  );

  const remove = useCallback(
    async (sessionId: string) => {
      const sessionApi = apiRef.current;
      if (!sessionApi) return;
      await sessionApi.remove(sessionId);
      if (!mounted.current) return;
      rows.current = rows.current.filter(session => session.id !== sessionId);
      setState(current => ({
        ...current,
        sessions: current.sessions.filter(session => session.id !== sessionId),
      }));
    },
    [],
  );

  return useMemo(
    () => ({ ...state, refresh, loadMore, retry, rename, remove }),
    [state, refresh, loadMore, retry, rename, remove],
  );
}
