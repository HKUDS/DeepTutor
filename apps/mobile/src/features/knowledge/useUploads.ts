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

interface UploadOptions {
  origin: string | null;
  ref: string | null;
  policy: UploadPolicy | null;
  /** Called after a file lands, so the screen can re-read progress. */
  onUploaded?: () => void;
}

function uploadErrorCopy(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.kind === 'unauthorized') return 'Sign in again to upload files.';
    if (error.kind === 'timeout') {
      return 'The upload stopped making progress. Check your connection and retry.';
    }
    if (error.kind === 'network') {
      return 'Could not reach the server. Check your connection.';
    }
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

/**
 * Upload queue for one knowledge base.
 *
 * Files go one per request: the endpoint accepts a batch, but a batch reports a
 * single progress figure and a single outcome, which would make per-file retry
 * and per-file cancellation impossible to describe honestly.
 *
 * Progress comes from `XMLHttpRequest.upload.onprogress`, i.e. bytes the
 * platform actually wrote. Cancelling aborts the transfer; the server's parsing
 * task, once the response is returned, is not something this client can cancel.
 */
export function useUploads({ origin, ref, policy, onUploaded }: UploadOptions) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const itemsRef = useRef<UploadItem[]>([]);
  const active = useRef<{ id: string; handle: UploadHandle } | null>(null);
  const draining = useRef(false);
  const mounted = useRef(true);
  const originRef = useRef(origin);
  const refRef = useRef(ref);
  const policyRef = useRef(policy);
  const onUploadedRef = useRef(onUploaded);
  /** Last whole percent written per item, so state updates stay bounded. */
  const percents = useRef(new Map<string, number>());

  useEffect(() => {
    originRef.current = origin;
    refRef.current = ref;
    policyRef.current = policy;
    onUploadedRef.current = onUploaded;
  }, [origin, ref, policy, onUploaded]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      active.current?.handle.abort();
      active.current = null;
    };
  }, []);

  const commit = useCallback((next: UploadItem[]) => {
    itemsRef.current = next;
    if (mounted.current) setItems(next);
  }, []);

  const patch = useCallback(
    (id: string, changes: Partial<UploadItem>) => {
      commit(
        itemsRef.current.map(item =>
          item.id === id ? { ...item, ...changes } : item,
        ),
      );
    },
    [commit],
  );

  const drain = useCallback(async () => {
    if (draining.current) return;
    draining.current = true;
    try {
      for (;;) {
        const next = itemsRef.current.find(item => item.status === 'queued');
        const currentOrigin = originRef.current;
        const currentRef = refRef.current;
        if (!next || !currentOrigin || !currentRef) break;
        patch(next.id, { status: 'uploading', loaded: 0, error: null });
        percents.current.set(next.id, 0);
        const handle = uploadKnowledgeFiles({
          origin: currentOrigin,
          ref: currentRef,
          files: [
            {
              uri: next.uri,
              name: next.name,
              size: next.size,
              mimeType: next.mimeType,
            },
          ],
          onProgress: (loaded, total) => {
            const percent = total > 0 ? Math.floor((loaded / total) * 100) : 0;
            if (percents.current.get(next.id) === percent) return;
            percents.current.set(next.id, percent);
            patch(next.id, { loaded, total });
          },
        });
        active.current = { id: next.id, handle };
        try {
          await handle.promise;
          patch(next.id, {
            status: 'done',
            loaded: next.size,
            total: next.size || next.total,
            error: null,
          });
          // The list is re-read rather than guessed from the response: the
          // server names what it stored, and a `.zip` expands into several rows.
          onUploadedRef.current?.();
          // The server has the file now, so the cache copy is no longer needed.
          discardPickedCopy(next.uri).catch(() => {});
        } catch (error) {
          if (error instanceof ApiError && error.kind === 'aborted') {
            patch(next.id, { status: 'cancelled', error: null });
            discardPickedCopy(next.uri).catch(() => {});
          } else {
            patch(next.id, {
              status: 'failed',
              error: uploadErrorCopy(error),
              retryable: true,
            });
          }
        } finally {
          active.current = null;
          percents.current.delete(next.id);
        }
      }
    } finally {
      draining.current = false;
    }
  }, [patch]);

  // A file picked before the screen knew where to send it — or while the base
  // was still loading — starts moving as soon as the destination exists.
  useEffect(() => {
    if (origin && ref) drain().catch(() => {});
  }, [origin, ref, drain]);

  const upload = useCallback(
    (files: readonly PickedFile[]) => {
      if (!files.length) return;
      const { accepted, rejected } = validatePickedFiles(
        files,
        policyRef.current,
      );
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
      const acceptedItems: UploadItem[] = accepted.map(file => ({
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
      }));
      commit([...acceptedItems, ...rejectedItems, ...itemsRef.current]);
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
      patch(id, { status: 'cancelled', loaded: 0 });
    },
    [patch],
  );

  const retry = useCallback(
    (id: string) => {
      const item = itemsRef.current.find(entry => entry.id === id);
      if (!item || !item.retryable || !item.uri) return;
      patch(id, { status: 'queued', loaded: 0, error: null });
      drain().catch(() => {});
    },
    [drain, patch],
  );

  const dismiss = useCallback(
    (id: string) => {
      const target = itemsRef.current.find(item => item.id === id);
      // Dismissing is the learner giving up on this file, so its copy goes too.
      if (target?.uri) discardPickedCopy(target.uri).catch(() => {});
      commit(itemsRef.current.filter(item => item.id !== id));
    },
    [commit],
  );

  const busy = items.some(
    item => item.status === 'queued' || item.status === 'uploading',
  );

  return { items, upload, cancel, retry, dismiss, busy };
}
