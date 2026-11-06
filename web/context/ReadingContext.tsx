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

  const saveMark = useCallback(
    async (draft: AnnotationDraft, optimistic: AnnotationItem) => {
      const materialId = material?.material_id;
      if (!materialId) return false;
      const token = openTokenRef.current;
      // From here on this tab's list differs from any GET already in flight.
      localMutationSeqRef.current += 1;
      pendingWritesRef.current.add(optimistic.annotation_id);
      const previous = annotations.find(row => row.annotation_id === optimistic.annotation_id);
      setAnnotations(current => previous
        ? current.map(row => row.annotation_id === optimistic.annotation_id ? optimistic : row)
        : [...current, optimistic]);
      try {
        const saved = await saveAnnotation(materialId, draft);
        if (token === openTokenRef.current) setAnnotations(current => current.map(row => row.annotation_id === optimistic.annotation_id ? saved : row));
        pendingWritesRef.current.delete(optimistic.annotation_id);
        // The acknowledged row is now part of this tab's list; a GET that
        // started before the PUT returned may not contain it.
        localMutationSeqRef.current += 1;
        publishAnnotationsChange(materialId);
        return true;
      } catch (caught) {
        pendingWritesRef.current.delete(optimistic.annotation_id);
        localMutationSeqRef.current += 1;
        if (token !== openTokenRef.current) return false;
        setAnnotations(current => previous
          ? current.map(row => row.annotation_id === optimistic.annotation_id ? previous : row)
          : current.filter(row => row.annotation_id !== optimistic.annotation_id));
        setErrorState(caught instanceof Error ? caught.message : "That annotation could not be saved.");
        return false;
      }
    }, [material, annotations],
  );

  const removeMark = useCallback(
    async (annotation: AnnotationItem): Promise<boolean> => {
      const materialId = material?.material_id;
      if (!materialId) return false;
      const scope = annotationScopeRef.current;
      const id = annotation.annotation_id;
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
        deletedIdsRef.current.delete(id);
        localMutationSeqRef.current += 1;
        if (scope !== annotationScopeRef.current) return false;
        // Put it back: pretending a failed delete succeeded would lose the mark
        // on the next reload.
        setAnnotations((current) => current.some(
          (row) => row.annotation_id === id,
        ) ? current : [...current, annotation]);
        setErrorState("That annotation could not be removed.");
        return false;
      }
    },
    [material],
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
    const materialId = material?.material_id;
    if (materialId) publishAnnotationsChange(materialId);
  }, [material]);

  /**
   * Re-read the marks when another tab reports a change.
   *
   * Two tabs on one document each hold their own copy, so a mark saved in one
   * is invisible in the other — and an edit made from the second tab writes
   * over the first tab's stale view of the rest. Re-reading through the normal
   * API (rather than trusting the broadcast payload) means the result is
   * whatever the server actually holds.
   *
   * Deliberately not optimistic: another tab's change is not something this
   * reader made, so it should arrive as a settled list, not a guess.
   */
  const materialId = material?.material_id ?? null;
  useEffect(() => {
    if (!materialId) return;
    const read = () => {
      const seq = ++refreshSeqRef.current;
      const scope = annotationScopeRef.current;
      const mutation = localMutationSeqRef.current;
      void listAnnotations(materialId)
        .then((rows) => {
          // The document may have been closed or swapped while this was in
          // flight; a stale response must not repopulate the list.
          if (scope !== annotationScopeRef.current) return;
          // A newer refresh is already on its way, and its answer is the newer
          // one. Letting this older list land would overwrite it.
          if (seq !== refreshSeqRef.current) return;
          // Our own list changed after this GET started. The snapshot predates
          // that change — a create it does not know about, a delete it still
          // lists — so discard it and read again from the settled state.
          if (mutation !== localMutationSeqRef.current) {
            read();
            return;
          }
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
        })
        .catch(() => {
          // A failed refresh leaves the local list alone; the next write, or
          // the next open, will resync.
        });
    };
    return subscribeToAnnotationsChange(materialId, read);
  }, [materialId]);

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
