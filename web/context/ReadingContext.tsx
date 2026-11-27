"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  publishAnnotationsChange,
  subscribeToAnnotationsChange,
} from "@/lib/reading-annotation-sync";
import {
  deleteAnnotation as deleteAnnotationApi,
  getMaterial,
  listAnnotations,
  saveAnnotation,
  type AnnotationDraft,
  type AnnotationItem,
  type MaterialDetail,
  type MaterialInfo,
} from "@/lib/reading-api";
import {
  setReadingMaterial,
  setReadingViewport,
} from "@/lib/reading-turn-state";

/**
 * The open document and its annotations, owned above the chat page.
 *
 * This provider lives in the workspace layout, NOT inside the chat page, and
 * that placement is the whole point: sending the first message of a session
 * changes the URL from `/chat` to `/chat/<id>`, which remounts the page
 * component. State held inside the reader pane died with it, so the document
 * vanished the moment the user asked their first question. The layout persists
 * across that navigation — which is exactly why the chat runtime sits there
 * too.
 *
 * The viewport (scroll position, selection) is deliberately NOT state: it
 * changes on every scroll tick and nothing renders from it, so it goes straight
 * into the module cell in `reading-turn-state` and is read once when a turn is
 * sent. Keeping it out of here is what stops scrolling the PDF from re-rendering
 * the message list.
 */
export interface ReadingContextValue {
  material: MaterialDetail | null;
  annotations: AnnotationItem[];
  loading: boolean;
  /** Last failure worth showing the user; cleared by `dismissError`. */
  error: string | null;
  openMaterial: (
    candidate: MaterialDetail | MaterialInfo | string,
  ) => Promise<boolean>;
  closeMaterial: () => void;
  /** Insert or update an annotation, optimistically. */
  saveMark: (
    draft: AnnotationDraft,
    optimistic: AnnotationItem,
  ) => Promise<boolean>;
  /**
   * Remove an annotation, optimistically.
   *
   * Resolves `false` when the delete failed, so a bulk caller can count it;
   * the row is already rolled back and the error notice set by then.
   */
  removeMark: (annotation: AnnotationItem) => Promise<boolean>;
  /** Accept a mark the assistant just made (arrives via a tool result). */
  mergeMark: (annotation: AnnotationItem) => void;
  dismissError: () => void;
  setError: (message: string) => void;
  /** Report scroll position / selection. Does not trigger a render. */
  reportViewport: (next: {
    locator?: number;
    selection?: string;
    timeSeconds?: number | null;
  }) => void;
}

const noop = () => {};

const ReadingContext = createContext<ReadingContextValue>({
  material: null,
  annotations: [],
  loading: false,
  error: null,
  openMaterial: async () => false,
  closeMaterial: noop,
  saveMark: async () => false,
  removeMark: async () => false,
  mergeMark: noop,
  dismissError: noop,
  setError: noop,
  reportViewport: noop,
});

export function ReadingProvider({ children }: { children: ReactNode }) {
  const [material, setMaterial] = useState<MaterialDetail | null>(null);
  const [annotations, setAnnotations] = useState<AnnotationItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setErrorState] = useState<string | null>(null);
  // Guards against a slow open landing after the user opened something else.
  const openTokenRef = useRef(0);
  const annotationScopeRef = useRef(0);
  // Ids whose write has been sent but not yet acknowledged. A refresh that
  // lands while this is non-empty must merge, not replace.
  const pendingWritesRef = useRef<Set<string>>(new Set());
  // Resolvers for writes in flight, keyed by their optimistic id. A row cannot
  // be deleted before the server knows its real id, so `removeMark` awaits the
  // write and then deletes the row the server actually created.
  const pendingResolversRef = useRef<
    Map<string, Set<(createdId: string | null) => void>>
  >(new Map());
  // The newest list, for callbacks that must read it after an await without
  // closing over a stale render.
  const annotationsRef = useRef<AnnotationItem[]>([]);
  useEffect(() => {
    annotationsRef.current = annotations;
  }, [annotations]);
  // Ids this tab has deleted but the server has not confirmed yet. A refresh
  // that lands while the DELETE is in flight still lists them; without this
  // tombstone the row would come back and stay back.
  const deletedIdsRef = useRef<Set<string>>(new Set());
  // Newest refresh wins. Every GET takes a number; only the response to the
  // highest one issued may apply, or an older list can land last and overwrite
  // a newer one.
  const refreshSeqRef = useRef(0);
  // Bumped whenever this tab changes its own list. A GET that started before a
  // local write carries a snapshot that predates it, so applying it would drop
  // a mark the reader can see was saved.
  const localMutationSeqRef = useRef(0);
  useEffect(() => () => {
    openTokenRef.current += 1;
    annotationScopeRef.current += 1;
  }, []);

  // Mirror the open document into the turn-state cell, which is what the chat
  // reads when it sends. One effect rather than writes scattered through the
  // mutators, so the two can never disagree.
  useEffect(() => {
    setReadingMaterial(
      material?.material_id ?? null,
      material?.revision ?? null,
    );
  }, [material]);

  const openMaterial = useCallback(
    async (candidate: MaterialDetail | MaterialInfo | string) => {
      const token = ++openTokenRef.current;
      setLoading(true);
      setErrorState(null);
      try {
        const detail =
          typeof candidate === "string"
            ? await getMaterial(candidate)
            : "outline" in candidate
              ? (candidate as MaterialDetail)
              : await getMaterial(candidate.material_id);
        if (token !== openTokenRef.current) return false;
        const marks = await listAnnotations(detail.material_id);
        if (token !== openTokenRef.current) return false;
        annotationScopeRef.current += 1;
        // Tombstones and pending ids belong to the document that was open;
        // carrying them into the next one would hide unrelated rows.
        deletedIdsRef.current.clear();
        pendingWritesRef.current.clear();
        setMaterial(detail);
        setAnnotations(marks);
        return true;
      } catch (caught) {
        if (token !== openTokenRef.current) return false;
        setErrorState(
          caught instanceof Error
            ? caught.message
            : "This document could not be opened.",
        );
        return false;
      } finally {
        if (token === openTokenRef.current) setLoading(false);
      }
    },
    [],
  );

  const closeMaterial = useCallback(() => {
    // Bump the token so an open still in flight cannot resurrect the document.
    openTokenRef.current += 1;
    annotationScopeRef.current += 1;
    deletedIdsRef.current.clear();
    pendingWritesRef.current.clear();
    setMaterial(null);
    setAnnotations([]);
    setErrorState(null);
    setReadingViewport({ locator: 0, selection: "" });
  }, []);

  const materialId = material?.material_id ?? null;

  /**
   * Re-read the marks and merge the server's answer into the list.
   *
   * Two tabs on one document each hold their own copy, so a mark saved in one
   * is invisible in the other — and an edit made from the second tab writes
   * over the first tab's stale view of the rest. Re-reading through the normal
   * API (rather than trusting the broadcast payload) means the result is
   * whatever the server actually holds.
   *
   * Deliberately not optimistic: another tab's change is not something this
   * reader made, so it should arrive as a settled list, not a guess.
   *
   * Resolves `true` only when the response was applied. A superseded read, a
   * read that raced a local change, and a failed request all resolve `false`;
   * the save and delete rollbacks need that answer to decide whether they must
   * fall back to their own captured row.
   */
  const refreshMarks = useCallback((): Promise<boolean> => {
    if (!materialId) return Promise.resolve(false);
    const seq = ++refreshSeqRef.current;
    const scope = annotationScopeRef.current;
    const mutation = localMutationSeqRef.current;
    return listAnnotations(materialId)
      .then((rows) => {
        // The document may have been closed or swapped while this was in
        // flight; a stale response must not repopulate the list.
        if (scope !== annotationScopeRef.current) return false;
        // A newer refresh is already on its way, and its answer is the newer
        // one. Letting this older list land would overwrite it.
        if (seq !== refreshSeqRef.current) return false;
        // Our own list changed after this GET started. The snapshot predates
        // that change — a create it does not know about, a delete it still
        // lists — so discard it and read again from the settled state.
        if (mutation !== localMutationSeqRef.current) return refreshMarks();
        // Snapshot the local effects this response must respect, so the
        // decision is made against the state the response actually raced.
        const deleted = new Set(deletedIdsRef.current);
        const pending = new Set(pendingWritesRef.current);
        setAnnotations((current) => {
          // A write of ours is still in flight: keep those rows. Replacing
          // the list would drop a brand-new mark for good, because the PUT
          // that follows maps by an optimistic id the refresh just removed.
          const keep = current.filter((row) => pending.has(row.annotation_id));
          return [
            ...rows.filter((row) => !deleted.has(row.annotation_id) && !keep.some((k) => k.annotation_id === row.annotation_id)),
            ...keep.filter((row) => !deleted.has(row.annotation_id)),
          ];
        });
        return true;
      })
      .catch(() => {
        // A failed refresh leaves the local list alone; the next write, or
        // the next open, will resync.
        return false;
      });
  }, [materialId]);

  const saveMark = useCallback(
    async (draft: AnnotationDraft, optimistic: AnnotationItem) => {
      const materialId = material?.material_id;
      if (!materialId) return false;
      const token = openTokenRef.current;
      // From here on this tab's list differs from any GET already in flight.
      localMutationSeqRef.current += 1;
      pendingWritesRef.current.add(optimistic.annotation_id);
      // Registered as a listener rather than a single slot: a delete may join
      // while the write is still in flight, and both must be told how it ended.
      const listeners = new Set<(createdId: string | null) => void>();
      pendingResolversRef.current.set(optimistic.annotation_id, listeners);
      const previous = annotations.find(row => row.annotation_id === optimistic.annotation_id);
      setAnnotations(current => previous
        ? current.map(row => row.annotation_id === optimistic.annotation_id ? optimistic : row)
        : [...current, optimistic]);
      try {
        const saved = await saveAnnotation(materialId, draft);
        if (token === openTokenRef.current) setAnnotations(current => current.map(row => row.annotation_id === optimistic.annotation_id ? saved : row));
        pendingWritesRef.current.delete(optimistic.annotation_id);
        for (const listener of pendingResolversRef.current.get(optimistic.annotation_id) ?? []) {
          listener(saved.annotation_id);
        }
        pendingResolversRef.current.delete(optimistic.annotation_id);
        // The acknowledged row is now part of this tab's list; a GET that
        // started before the PUT returned may not contain it.
        localMutationSeqRef.current += 1;
        publishAnnotationsChange(materialId);
        return true;
      } catch (caught) {
        // The write is no longer pending, so a refresh from here on is allowed
        // to replace the optimistic row with whatever the server holds.
        pendingWritesRef.current.delete(optimistic.annotation_id);
        for (const listener of pendingResolversRef.current.get(optimistic.annotation_id) ?? []) {
          listener(null);
        }
        pendingResolversRef.current.delete(optimistic.annotation_id);
        localMutationSeqRef.current += 1;
        if (token !== openTokenRef.current) return false;
        setErrorState(caught instanceof Error ? caught.message : "That annotation could not be saved.");
        // The captured row may be stale: another tab can have edited this mark
        // while the PUT was in flight, and a refresh may already have brought
        // the newer copy — hidden here until now by the pending merge. The row
        // may even be gone, deleted remotely while this tab was still editing
        // it. Re-reading asks the server what it holds now, and the normal
        // merge decides: the newer note wins, and a row the server no longer
        // lists stays gone.
        const reconciled = await refreshMarks();
        if (token !== openTokenRef.current) return false;
        if (!reconciled) {
          // The re-read failed (or was superseded): fall back to the state
          // captured before the edit. This is the pre-reconcile behaviour,
          // kept so a flaky GET never costs the reader a row they can still
          // see. A brand-new mark that never reached the server is removed.
          // Deliberately a map, not an append: if the id is already absent,
          // a newer refresh has settled the list without it, and putting the
          // captured row back would resurrect a remotely deleted mark.
          setAnnotations(current => previous
            ? current.map(row => row.annotation_id === optimistic.annotation_id ? previous : row)
            : current.filter(row => row.annotation_id !== optimistic.annotation_id));
        }
        return false;
      }
    }, [material, annotations, refreshMarks],
  );

  /** Wait for a create in flight; resolves to the real id, or null on failure. */
  const waitForPendingWrite = useCallback(
    (optimisticId: string): Promise<string | null> => {
      if (!pendingWritesRef.current.has(optimisticId)) {
        return Promise.resolve(optimisticId);
      }
      // `saveMark` resolves every registered write on both paths, so this
      // settles whether the PUT succeeded or failed.
      return new Promise<string | null>((resolve) => {
        const listeners = pendingResolversRef.current.get(optimisticId);
        if (!listeners) {
          resolve(optimisticId);
          return;
        }
        listeners.add(resolve);
      });
    },
    [],
  );

  const removeMark = useCallback(
    async (annotation: AnnotationItem): Promise<boolean> => {
      if (!materialId) return false;
      const scope = annotationScopeRef.current;
      // A row still being created carries the optimistic `pending-…` id, which
      // the server has never seen: deleting it 404s while the PUT that follows
      // creates the real row, leaving a mark on the server that this tab has
      // hidden and will not show again until something refreshes. Ask the
      // write in flight to finish first, so the delete names the real id.
      let target = annotation;
      if (pendingWritesRef.current.has(annotation.annotation_id)) {
        const createdId = await waitForPendingWrite(annotation.annotation_id);
        if (scope !== annotationScopeRef.current) return false;
        if (!createdId) return false;
        const created = annotationsRef.current.find(
          (row) => row.annotation_id === createdId,
        );
        // The write landed but the row is not in the list (a refresh settled
        // without it): the server may still hold it, so delete by id anyway.
        target = created ?? { ...annotation, annotation_id: createdId };
      }
      const id = target.annotation_id;
      // The row is gone from this tab's list before the request even leaves;
      // any GET that overlaps must be told, or it will bring the row back.
      deletedIdsRef.current.add(id);
      localMutationSeqRef.current += 1;
      setAnnotations((current) => current.filter(
        (row) => row.annotation_id !== id,
      ));
      try {
        await deleteAnnotationApi(materialId, id);
        // The server has it gone now, so the tombstone has done its job.
        deletedIdsRef.current.delete(id);
        localMutationSeqRef.current += 1;
        publishAnnotationsChange(materialId);
        return true;
      } catch {
        // Clear the tombstone first: the re-read below is exactly the request
        // that must be allowed to see this row again.
        deletedIdsRef.current.delete(id);
        localMutationSeqRef.current += 1;
        if (scope !== annotationScopeRef.current) return false;
        setErrorState("That annotation could not be removed.");
        // The captured row may be stale: another tab can have edited this mark
        // while the DELETE was in flight, and a refresh may already have
        // brought the newer copy. Re-reading asks the server what it holds now
        // and lets the normal merge put that back, so the rollback cannot
        // resurrect an old note over a newer one.
        const reconciled = await refreshMarks();
        if (scope !== annotationScopeRef.current) return false;
        if (!reconciled) {
          // The re-read failed (or was superseded): restore the row we took
          // away, because leaving it missing would hide a mark the server
          // still holds. This is the pre-reconcile behaviour, kept as the
          // fallback so a flaky GET never costs the reader their mark.
          setAnnotations((current) => current.some(
            (row) => row.annotation_id === id,
          ) ? current : [...current, target]);
        }
        return false;
      }
    },
    [materialId, refreshMarks, waitForPendingWrite],
  );

  const mergeMark = useCallback((annotation: AnnotationItem) => {
    if (!annotation?.annotation_id) return;
    // The assistant's mark is a local change too: a GET already in flight may
    // not know it yet.
    localMutationSeqRef.current += 1;
    setAnnotations((current) => [
      ...current.filter(
        (row) => row.annotation_id !== annotation.annotation_id,
      ),
      annotation,
    ]);
    // The assistant's mark is already persisted by the tool that made it, so
    // this is a real change to the document's marks and the other tabs need
    // to hear about it — exactly like a mark the reader saved.
    if (materialId) publishAnnotationsChange(materialId);
  }, [materialId]);

  /**
   * Re-read the marks when another tab reports a change.
   *
   * The read itself lives in `refreshMarks`, which the save and delete
   * rollbacks also use: all three need the same "ask the server, then merge"
   * answer.
   */
  useEffect(() => {
    if (!materialId) return;
    return subscribeToAnnotationsChange(materialId, () => {
      void refreshMarks();
    });
  }, [materialId, refreshMarks]);

  const reportViewport = useCallback(
    (next: {
      locator?: number;
      selection?: string;
      timeSeconds?: number | null;
    }) => setReadingViewport(next),
    [],
  );

  const dismissError = useCallback(() => setErrorState(null), []);
  const setError = useCallback((message: string) => setErrorState(message), []);

  const value = useMemo<ReadingContextValue>(
    () => ({
      material,
      annotations,
      loading,
      error,
      openMaterial,
      closeMaterial,
      saveMark,
      removeMark,
      mergeMark,
      dismissError,
      setError,
      reportViewport,
    }),
    [
      material,
      annotations,
      loading,
      error,
      openMaterial,
      closeMaterial,
      saveMark,
      removeMark,
      mergeMark,
      dismissError,
      setError,
      reportViewport,
    ],
  );

  return (
    <ReadingContext.Provider value={value}>{children}</ReadingContext.Provider>
  );
}

export function useReading(): ReadingContextValue {
  return useContext(ReadingContext);
}
