import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError } from '../../services/apiClient';
import type { PickedFile, UploadPolicy } from '../../services/knowledgeApi';
import {
  uploadKnowledgeFiles,
  validatePickedFiles,
  type UploadHandle,
} from '../../services/knowledgeUpload';
import { discardPickedCopy } from './pickFiles';

export type UploadStatus =
  | 'queued'
  | 'uploading'
  | 'done'
  | 'failed'
  | 'cancelled';

export interface UploadItem {
  id: string;
  name: string;
  size: number;
  status: UploadStatus;
  loaded: number;
  /** True byte total the platform reported, or the picked size before that. */
  total: number;
  error: string | null;
  /** A file refused before any bytes moved cannot be retried by itself. */
  retryable: boolean;
  uri: string;
  mimeType: string;
}

/**
 * Everything that decides where a file may be sent.
 *
 * The account id is part of it because a server can serve several accounts at
 * the same origin, and a base called `physics` for one account is a different
 * base for another.
 */
export interface UploadDestination {
  origin: string;
  ref: string;
  accountId: string;
}

interface QueueTask {
  item: UploadItem;
  /**
   * Captured when the file was picked. A task is only ever sent here: if the
   * screen later points at another server, account or base, this task is
   * retired rather than re-addressed.
   */
  destination: UploadDestination | null;
}

interface UploadOptions {
  destination: UploadDestination | null;
  policy: UploadPolicy | null;
  /** Called after a file lands, so the screen can re-read progress. */
  onUploaded?: () => void;
}

const DESTINATION_CHANGED =
  'The upload destination changed. Pick this file again if you still need it.';

function uploadErrorCopy(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.kind === 'unauthorized') return 'Sign in again to upload files.';
    if (error.kind === 'timeout') {
      return 'The upload stopped making progress. Check your connection and retry.';
    }
    if (error.kind === 'network') {
      return 'Could not reach the server. Check your connection.';
    }
    if (error.kind === 'redirect') {
      return 'The server redirected the upload, so it was stopped. Check the server address.';
    }
    // A refusal the server explained is shown in its own words: it can name the
    // real cause (a size limit, an unconfigured embedding model) where a status
    // code cannot.
    if (error.detail) return error.detail;
    if (error.status === 413) return 'The server rejected this file as too large.';
    if (error.status === 409) {
      return 'The server refused this upload in the base’s current state.';
    }
    if (error.status === 404) return 'This knowledge base no longer exists.';
  }
  return 'The upload failed. Try again.';
}

function newId(): string {
  return `u${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
}

function sameDestination(
  left: UploadDestination | null,
  right: UploadDestination | null,
): boolean {
  if (!left || !right) return left === right;
  return (
    left.origin === right.origin &&
    left.ref === right.ref &&
    left.accountId === right.accountId
  );
}

/**
 * Upload queue for one knowledge base.
 *
 * Files go one per request: the endpoint accepts a batch, but a batch reports a
 * single progress figure and a single outcome, which would make per-file retry
 * and per-file cancellation impossible to describe honestly.
 *
 * Progress comes from `XMLHttpRequest.upload.onprogress`, i.e. bytes the
 * platform actually wrote. Cancelling aborts the transfer and nothing else: once
 * the response is returned the run belongs to the server, and cancelling it is a
 * separate request this screen does not make.
 *
 * The queue is bound to a destination and to the screen. A generation counter
 * is bumped whenever the destination changes or the screen goes away; the drain
 * loop checks it before starting each file and again after every await, so a
 * retired queue can never start another request. Queued copies are released at
 * the same time — a file that will not be uploaded has no reason to sit in the
 * cache.
 */
export function useUploads({ destination, policy, onUploaded }: UploadOptions) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const tasks = useRef<QueueTask[]>([]);
  const active = useRef<{ id: string; handle: UploadHandle } | null>(null);
  const draining = useRef(false);
  /** Set when `drain` is called while it is already running. */
  const rerun = useRef(false);
  const mounted = useRef(true);
  const generation = useRef(0);
  const destinationRef = useRef<UploadDestination | null>(destination);
  const policyRef = useRef(policy);
  const onUploadedRef = useRef(onUploaded);
  /** Last whole percent written per item, so state updates stay bounded. */
  const percents = useRef(new Map<string, number>());

  // The destination's identity is three primitives; the effect below must not
  // depend on an object a caller may rebuild on every render.
  const origin = destination?.origin ?? null;
  const ref = destination?.ref ?? null;
  const accountId = destination?.accountId ?? '';

  const publish = useCallback(() => {
    if (mounted.current) setItems(tasks.current.map(task => task.item));
  }, []);

  const commit = useCallback(
    (next: QueueTask[]) => {
      tasks.current = next;
      publish();
    },
    [publish],
  );

  const patch = useCallback(
    (id: string, changes: Partial<UploadItem>) => {
      tasks.current = tasks.current.map(task =>
        task.item.id === id ? { ...task, item: { ...task.item, ...changes } } : task,
      );
      publish();
    },
    [publish],
  );

  /** Withdraw a task that will never reach the network. */
  const retire = useCallback(
    (task: QueueTask, reason: string | null) => {
      patch(task.item.id, { status: 'cancelled', loaded: 0, error: reason });
      if (task.item.uri) discardPickedCopy(task.item.uri).catch(() => {});
    },
    [patch],
  );

  const drain = useCallback(async () => {
    if (draining.current) {
      rerun.current = true;
      return;
    }
    draining.current = true;
    try {
      do {
        rerun.current = false;
        const token = generation.current;
        for (;;) {
          if (!mounted.current || generation.current !== token) break;
          const target = destinationRef.current;
          if (!target) break;
          const next = tasks.current.find(
            task =>
              task.item.status === 'queued' &&
              sameDestination(task.destination, target),
          );
          if (!next) break;

          const id = next.item.id;
          patch(id, {
            status: 'uploading',
            loaded: 0,
            total: next.item.size,
            error: null,
          });
          percents.current.set(id, 0);
          const handle = uploadKnowledgeFiles({
            origin: target.origin,
            ref: target.ref,
            files: [
              {
                uri: next.item.uri,
                name: next.item.name,
                size: next.item.size,
                mimeType: next.item.mimeType,
              },
            ],
            onProgress: (loaded, total) => {
              const percent = total > 0 ? Math.floor((loaded / total) * 100) : 0;
              if (percents.current.get(id) === percent) return;
              percents.current.set(id, percent);
              patch(id, { loaded, total });
            },
          });
          active.current = { id, handle };

          let failure: ApiError | null = null;
          try {
            await handle.promise;
          } catch (error) {
            failure =
              error instanceof ApiError
                ? error
                : new ApiError('network', 'The upload failed.');
          }

          if (active.current?.id === id) active.current = null;
          percents.current.delete(id);

          // The queue was retired while this request was in flight. Whoever
          // retired it already cancelled the row and released its copy.
          if (!mounted.current || generation.current !== token) break;

          if (!failure) {
            patch(id, {
              status: 'done',
              loaded: next.item.size,
              total: next.item.size || next.item.total,
              error: null,
            });
            // The list is re-read rather than guessed from the response: the
            // server names what it stored, and a `.zip` expands into several
            // rows.
            onUploadedRef.current?.();
            // The server has the file now, so the cache copy is no longer needed.
            discardPickedCopy(next.item.uri).catch(() => {});
            continue;
          }
          if (failure.kind === 'aborted') {
            patch(id, { status: 'cancelled', error: null });
            discardPickedCopy(next.item.uri).catch(() => {});
            continue;
          }
          // The copy is kept: retrying must not need the learner to pick again.
          patch(id, {
            status: 'failed',
            error: uploadErrorCopy(failure),
            retryable: true,
          });
        }
      } while (rerun.current && mounted.current);
    } finally {
      draining.current = false;
    }
  }, [patch]);

  // Keep the live values for callbacks that outlive a render.
  useEffect(() => {
    destinationRef.current = destination;
    policyRef.current = policy;
    onUploadedRef.current = onUploaded;
  }, [destination, policy, onUploaded]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current += 1;
      const running = active.current;
      active.current = null;
      running?.handle.abort();
      // Nobody can retry or dismiss these rows now; the copies they still hold
      // would otherwise linger in the cache.
      for (const task of tasks.current) {
        if (
          task.item.uri &&
          (task.item.status === 'queued' ||
            task.item.status === 'uploading' ||
            task.item.status === 'failed')
        ) {
          discardPickedCopy(task.item.uri).catch(() => {});
        }
      }
    };
  }, []);

  // Signing out, switching account, server or base retires the queue before
  // another request can start. The generation check inside `drain` covers the
  // task that is already in flight.
  useEffect(() => {
    generation.current += 1;
    const target =
      origin && ref ? { origin, ref, accountId } : null;
    const stale = tasks.current.filter(task => {
      const moving =
        task.item.status === 'queued' || task.item.status === 'uploading';
      // A failed row holds a copy and offers Retry; once the destination is
      // gone that offer would send it somewhere else, so it is withdrawn too.
      const retryable =
        task.item.status === 'failed' && task.item.retryable;
      return (moving || retryable) && !sameDestination(task.destination, target);
    });
    for (const task of stale) {
      if (active.current?.id === task.item.id) {
        const running = active.current;
        active.current = null;
        running?.handle.abort();
      }
      retire(task, DESTINATION_CHANGED);
    }
    if (stale.length) rerun.current = true;
    drain().catch(() => {});
  }, [origin, ref, accountId, drain, retire]);

  const upload = useCallback(
    (files: readonly PickedFile[]) => {
      if (!files.length) return;
      if (!mounted.current) {
        // The picker resolved after the screen closed. Nothing can upload
        // these, so the copies go with it.
        files.forEach(file => discardPickedCopy(file.uri).catch(() => {}));
        return;
      }
      const target = destinationRef.current;
      const { accepted, rejected } = validatePickedFiles(
        files,
        policyRef.current,
      );
      // A refused file is never sent, so its copy has no further use.
      for (const entry of rejected) {
        if (entry.uri) discardPickedCopy(entry.uri).catch(() => {});
      }
      const rejectedItems: UploadItem[] = rejected.map(entry => ({
        id: newId(),
        name: entry.name,
        size: 0,
        status: 'failed',
        loaded: 0,
        total: 0,
        error: entry.reason,
        retryable: false,
        uri: '',
        mimeType: '',
      }));

      if (!target) {
        // Without a destination there is nothing these files may be bound to.
        // Failing them now is safer than letting a later screen inherit them.
        for (const file of accepted) discardPickedCopy(file.uri).catch(() => {});
        const blocked: UploadItem[] = accepted.map(file => ({
          id: newId(),
          name: file.name,
          size: file.size ?? 0,
          status: 'failed',
          loaded: 0,
          total: file.size ?? 0,
          error: 'This screen is not connected to a server.',
          retryable: false,
          uri: '',
          mimeType: file.mimeType,
        }));
        commit([
          ...blocked.map(item => ({ item, destination: null })),
          ...rejectedItems.map(item => ({ item, destination: null })),
          ...tasks.current,
        ]);
        return;
      }

      const queued: QueueTask[] = accepted.map(file => ({
        item: {
          id: newId(),
          name: file.name,
          size: file.size ?? 0,
          status: 'queued',
          loaded: 0,
          total: file.size ?? 0,
          error: null,
          retryable: true,
          uri: file.uri,
          mimeType: file.mimeType,
        },
        destination: { ...target },
      }));
      commit([
        ...queued,
        ...rejectedItems.map(item => ({ item, destination: { ...target } })),
        ...tasks.current,
      ]);
      drain().catch(() => {});
    },
    [commit, drain],
  );

  const cancel = useCallback(
    (id: string) => {
      if (active.current?.id === id) {
        active.current.handle.abort();
        return;
      }
      const task = tasks.current.find(entry => entry.item.id === id);
      if (!task) return;
      retire(task, null);
    },
    [retire],
  );

  const retry = useCallback(
    (id: string) => {
      const task = tasks.current.find(entry => entry.item.id === id);
      if (!task || !task.item.retryable || !task.item.uri) return;
      if (!sameDestination(task.destination, destinationRef.current)) {
        // A file picked for another server or account is never sent here.
        retire(task, DESTINATION_CHANGED);
        return;
      }
      patch(id, { status: 'queued', loaded: 0, error: null });
      drain().catch(() => {});
    },
    [drain, patch, retire],
  );

  const dismiss = useCallback(
    (id: string) => {
      const target = tasks.current.find(item => item.item.id === id);
      // Dismissing is the learner giving up on this file, so its copy goes too.
      if (target?.item.uri) discardPickedCopy(target.item.uri).catch(() => {});
      commit(tasks.current.filter(item => item.item.id !== id));
    },
    [commit],
  );

  const busy = items.some(
    item => item.status === 'queued' || item.status === 'uploading',
  );

  return { items, upload, cancel, retry, dismiss, busy };
}
