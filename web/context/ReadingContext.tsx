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
 * changes the URL from `/home` to `/home/<id>`, which remounts the page
 * component. State held inside the reader pane died with it, so the document
 * vanished the moment the user asked their first question. The layout persists
 * across that navigation — which is exactly why `UnifiedChatProvider` sits there
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
  openMaterial: (candidate: MaterialDetail | MaterialInfo) => Promise<void>;
  closeMaterial: () => void;
  /** Insert or update an annotation, optimistically. */
  saveMark: (
    draft: AnnotationDraft,
    optimistic: AnnotationItem,
  ) => Promise<void>;
  /** Remove an annotation, optimistically. */
  removeMark: (annotation: AnnotationItem) => Promise<void>;
  /** Accept a mark the assistant just made (arrives via a tool result). */
  mergeMark: (annotation: AnnotationItem) => void;
  dismissError: () => void;
  setError: (message: string) => void;
  /** Report scroll position / selection. Does not trigger a render. */
  reportViewport: (next: { locator?: number; selection?: string }) => void;
}

const noop = () => {};

const ReadingContext = createContext<ReadingContextValue>({
  material: null,
  annotations: [],
  loading: false,
  error: null,
  openMaterial: async () => {},
  closeMaterial: noop,
  saveMark: async () => {},
  removeMark: async () => {},
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

  // Mirror the open document into the turn-state cell, which is what the chat
  // reads when it sends. One effect rather than writes scattered through the
  // mutators, so the two can never disagree.
  useEffect(() => {
    setReadingMaterial(material?.material_id ?? null);
  }, [material]);

  const openMaterial = useCallback(
    async (candidate: MaterialDetail | MaterialInfo) => {
      const token = ++openTokenRef.current;
      setLoading(true);
      setErrorState(null);
      try {
        const detail =
          "outline" in candidate
            ? (candidate as MaterialDetail)
            : await getMaterial(candidate.material_id);
        const marks = await listAnnotations(detail.material_id);
        if (token !== openTokenRef.current) return;
        setMaterial(detail);
        setAnnotations(marks);
      } catch (caught) {
        if (token !== openTokenRef.current) return;
        setErrorState(
          caught instanceof Error
            ? caught.message
            : "This document could not be opened.",
        );
      } finally {
        if (token === openTokenRef.current) setLoading(false);
      }
    },
    [],
  );

  const closeMaterial = useCallback(() => {
    // Bump the token so an open still in flight cannot resurrect the document.
    openTokenRef.current += 1;
    setMaterial(null);
    setAnnotations([]);
    setErrorState(null);
    setReadingViewport({ locator: 0, selection: "" });
  }, []);

  const saveMark = useCallback(
    async (draft: AnnotationDraft, optimistic: AnnotationItem) => {
      const materialId = material?.material_id;
      if (!materialId) return;
      // Shown immediately: waiting for a round trip before any ink appears
      // makes highlighting feel broken.
      setAnnotations((current) => [...current, optimistic]);
      try {
        const saved = await saveAnnotation(materialId, draft);
        setAnnotations((current) =>
          current.map((row) =>
            row.annotation_id === optimistic.annotation_id ? saved : row,
          ),
        );
      } catch (caught) {
        setAnnotations((current) =>
          current.filter(
            (row) => row.annotation_id !== optimistic.annotation_id,
          ),
        );
        setErrorState(
          caught instanceof Error
            ? caught.message
            : "That annotation could not be saved.",
        );
      }
    },
    [material],
  );

  const removeMark = useCallback(
    async (annotation: AnnotationItem) => {
      const materialId = material?.material_id;
      if (!materialId) return;
      let previous: AnnotationItem[] = [];
      setAnnotations((current) => {
        previous = current;
        return current.filter(
          (row) => row.annotation_id !== annotation.annotation_id,
        );
      });
      try {
        await deleteAnnotationApi(materialId, annotation.annotation_id);
      } catch {
        // Put it back: pretending a failed delete succeeded would lose the mark
        // on the next reload.
        setAnnotations(previous);
        setErrorState("That annotation could not be removed.");
      }
    },
    [material],
  );

  const mergeMark = useCallback((annotation: AnnotationItem) => {
    if (!annotation?.annotation_id) return;
    setAnnotations((current) => [
      ...current.filter(
        (row) => row.annotation_id !== annotation.annotation_id,
      ),
      annotation,
    ]);
  }, []);

  const reportViewport = useCallback(
    (next: { locator?: number; selection?: string }) =>
      setReadingViewport(next),
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
