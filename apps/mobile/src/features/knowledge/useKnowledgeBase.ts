import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';

import {
  KnowledgeApi,
  isLiveStatus,
  isTerminalProgress,
  messageFor,
  type KnowledgeBaseSummary,
  type KnowledgeFileEntry,
} from '../../services/knowledgeApi';

export interface KnowledgeBaseState {
  kb: KnowledgeBaseSummary | null;
  files: KnowledgeFileEntry[];
  status: 'loading' | 'ready' | 'failed';
  error: string | null;
  refreshing: boolean;
  retrying: boolean;
  saving: boolean;
}

const POLL_START_MS = 2_000;
const POLL_MAX_MS = 8_000;
const POLL_FACTOR = 1.4;

function emptyState(): KnowledgeBaseState {
  return {
    kb: null,
    files: [],
    status: 'loading',
    error: null,
    refreshing: false,
    retrying: false,
    saving: false,
  };
}

/**
 * One knowledge base: its own record, its raw files, and its processing run.
 *
 * Indexing is a background task on the server and the only progress channel the
 * HTTP API offers is a polled snapshot (`/progress`), so this polls while a run
 * is live: 2 s at first, backing off to 8 s, and stopping the moment the run
 * reports `completed` or `error`. Polling is suspended while the app is in the
 * background — JavaScript is not kept alive there, and a timer that fires on
 * return would only race the foreground refresh.
 *
 * `scope` is the identity key — `knowledgeScope(session)`, i.e. server plus
 * account. It is compared as a primitive rather than the client object so a
 * caller that rebuilds the client inline cannot make this hook loop, and so a
 * real sign-out or account switch still drops the previous owner's record.
 */
export function useKnowledgeBase(
  api: KnowledgeApi | null,
  ref: string | null,
  scope = '',
) {
  const [state, setState] = useState<KnowledgeBaseState>(emptyState);
  const mounted = useRef(true);
  const generation = useRef(0);
  const inFlight = useRef<AbortController | null>(null);
  const wasLive = useRef(false);
  /** Whether a file listing has been read for the current base. */
  const hasFiles = useRef(false);
  const apiRef = useRef<KnowledgeApi | null>(api);
  const refRef = useRef<string | null>(ref);
  const loadRef = useRef<((quiet: boolean) => Promise<void>) | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      inFlight.current?.abort();
    };
  }, []);

  const load = useCallback(async (quiet: boolean) => {
    const client = apiRef.current;
    const current = refRef.current;
    if (!client || !current) return;
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    const token = ++generation.current;
    if (!quiet) {
      setState(value => ({ ...value, status: 'loading', error: null }));
    } else {
      setState(value => ({ ...value, refreshing: true }));
    }
    try {
      const kb = await client.get(current, controller.signal);
      if (!mounted.current || token !== generation.current) return;
      const live = isLiveStatus(kb.status) || !isTerminalProgress(kb.progress);
      // Files change on upload and delete, not during a run; re-read them when
      // a run ends so a file that failed to parse gets its final state.
      const needFiles = !quiet || (wasLive.current && !live) || !hasFiles.current;
      const files = needFiles
        ? await client.files(current, controller.signal)
        : null;
      if (!mounted.current || token !== generation.current) return;
      wasLive.current = live;
      if (files) hasFiles.current = true;
      setState(value => ({
        ...value,
        kb,
        files: files ?? value.files,
        status: 'ready',
        refreshing: false,
        error: null,
      }));
    } catch (error) {
      if (!mounted.current || token !== generation.current) return;
      setState(value => ({
        ...value,
        // Keep whatever was already on screen; only a first load has nothing.
        status: value.kb ? 'ready' : 'failed',
        refreshing: false,
        error: messageFor(error),
      }));
    }
  }, []);

  useEffect(() => {
    loadRef.current = load;
  }, [load]);

  useEffect(() => {
    apiRef.current = api;
  }, [api]);

  useEffect(() => {
    refRef.current = ref;
    // A new identity means a different server or account: the record on screen
    // may belong to someone else, so it is dropped before anything reloads.
    generation.current += 1;
    inFlight.current?.abort();
    wasLive.current = false;
    hasFiles.current = false;
    setState(emptyState());
    if (!apiRef.current || !ref) return;
    load(false).catch(() => {});
  }, [scope, ref, load]);

  const live =
    !!state.kb &&
    (isLiveStatus(state.kb.status) || !isTerminalProgress(state.kb.progress));

  // Poll while the server is working. The delay grows so a long indexing run
  // does not keep a phone's radio busy, and the chain stops on its own once the
  // run reports a terminal stage.
  useEffect(() => {
    if (!live || !mounted.current) return;
    let cancelled = false;
    let delay = POLL_START_MS;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = () => {
      if (cancelled) return;
      if (AppState.currentState !== 'active') {
        // Re-armed on the next foreground refresh instead of polling blind.
        timer = setTimeout(tick, POLL_MAX_MS);
        return;
      }
      const run = loadRef.current;
      if (!run) return;
      run(true)
        .catch(() => {})
        .finally(() => {
          if (cancelled) return;
          delay = Math.min(POLL_MAX_MS, Math.round(delay * POLL_FACTOR));
          timer = setTimeout(tick, delay);
        });
    };
    timer = setTimeout(tick, POLL_START_MS);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [live]);

  // Coming back from the background: ask now rather than wait for the timer.
  useEffect(() => {
    const subscription = AppState.addEventListener('change', next => {
      if (next !== 'active' || !mounted.current) return;
      loadRef.current?.(true).catch(() => {});
    });
    return () => subscription.remove();
  }, []);

  const refresh = useCallback(() => load(true), [load]);

  const retry = useCallback(async () => {
    const client = apiRef.current;
    const current = refRef.current;
    if (!client || !current) return;
    setState(value => ({ ...value, retrying: true, error: null }));
    try {
      await client.retry(current);
      await load(true);
    } catch (error) {
      setState(value => ({
        ...value,
        // A 409 means the run is no longer retryable — or that indexing cannot
        // start at all. The server says which; this client does not guess.
        error: messageFor(error),
      }));
    } finally {
      if (mounted.current) {
        setState(value => ({ ...value, retrying: false }));
      }
    }
  }, [load]);

  const saveDescription = useCallback(async (description: string) => {
    const client = apiRef.current;
    const current = refRef.current;
    if (!client || !current) return false;
    setState(value => ({ ...value, saving: true, error: null }));
    try {
      await client.updateDescription(current, description);
      if (mounted.current) {
        setState(value => ({
          ...value,
          kb: value.kb ? { ...value.kb, description } : value.kb,
        }));
      }
      return true;
    } catch (error) {
      if (mounted.current) {
        setState(value => ({ ...value, error: messageFor(error) }));
      }
      return false;
    } finally {
      if (mounted.current) {
        setState(value => ({ ...value, saving: false }));
      }
    }
  }, []);

  const removeFile = useCallback(async (name: string) => {
    const client = apiRef.current;
    const current = refRef.current;
    if (!client || !current) return false;
    try {
      await client.removeFile(current, name);
      if (mounted.current) {
        setState(value => ({
          ...value,
          files: value.files.filter(file => file.name !== name),
          kb: value.kb
            ? {
                ...value.kb,
                documentCount: Math.max(0, value.kb.documentCount - 1),
              }
            : value.kb,
        }));
      }
      // A deleted file may flip a failed run back to a state worth re-reading.
      load(true).catch(() => {});
      return true;
    } catch (error) {
      if (mounted.current) {
        setState(value => ({ ...value, error: messageFor(error) }));
      }
      return false;
    }
  }, [load]);

  return { ...state, refresh, retry, saveDescription, removeFile };
}
