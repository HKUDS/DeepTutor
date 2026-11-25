import { useCallback, useEffect, useRef, useState } from 'react';

import {
  KnowledgeApi,
  messageFor,
  type KnowledgeBaseSummary,
} from '../../services/knowledgeApi';

export interface KnowledgeBasesState {
  bases: KnowledgeBaseSummary[];
  status: 'loading' | 'ready' | 'failed';
  refreshing: boolean;
  error: string | null;
}

const initialState: KnowledgeBasesState = {
  bases: [],
  status: 'loading',
  refreshing: false,
  error: null,
};

/**
 * The server's knowledge-base index.
 *
 * `GET /api/knowledge-bases` returns the whole catalogue in one array — no
 * pagination and no server-side search — so paging is not invented here. A
 * failed refresh keeps the rows already on screen: an empty list would read as
 * "you have no knowledge bases".
 *
 * `scope` is the identity key — `knowledgeScope(session)`, i.e. server plus
 * account. A caller that changes it gets the previous owner's rows removed
 * before the fresh list is read.
 */
export function useKnowledgeBases(api: KnowledgeApi | null, scope = '') {
  const [state, setState] = useState<KnowledgeBasesState>(initialState);
  const mounted = useRef(true);
  const generation = useRef(0);
  const inFlight = useRef<AbortController | null>(null);
  const apiRef = useRef<KnowledgeApi | null>(api);

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

  const load = useCallback(async (mode: 'initial' | 'refresh') => {
    const client = apiRef.current;
    if (!client) return;
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    const token = ++generation.current;
    setState(current =>
      mode === 'initial'
        ? { ...current, status: 'loading', error: null }
        : { ...current, refreshing: true, error: null },
    );
    try {
      const bases = await client.list(controller.signal);
      if (!mounted.current || token !== generation.current) return;
      setState({
        bases,
        status: 'ready',
        refreshing: false,
        error: null,
      });
    } catch (error) {
      if (!mounted.current || token !== generation.current) return;
      setState(current => ({
        ...current,
        // A first-load failure is the only one that has no rows to show.
        status: current.bases.length ? 'ready' : 'failed',
        refreshing: false,
        error: messageFor(error),
      }));
    }
  }, []);

  useEffect(() => {
    // A different scope means a different server or account. The rows on screen
    // belong to the previous identity, so they are dropped instead of being
    // shown under the new one while the fresh list loads.
    generation.current += 1;
    inFlight.current?.abort();
    setState(initialState);
    if (!apiRef.current) return;
    load('initial').catch(() => {});
  }, [scope, load]);

  const refresh = useCallback(() => load('refresh'), [load]);

  /** Drop a deleted base locally so the list matches the server immediately. */
  const forget = useCallback((ref: string) => {
    setState(current => ({
      ...current,
      bases: current.bases.filter(base => base.ref !== ref),
    }));
  }, []);

  const remember = useCallback((base: KnowledgeBaseSummary) => {
    setState(current => {
      const exists = current.bases.some(item => item.ref === base.ref);
      return {
        ...current,
        bases: exists
          ? current.bases.map(item => (item.ref === base.ref ? base : item))
          : [base, ...current.bases],
      };
    });
  }, []);

  return { ...state, refresh, forget, remember };
}
