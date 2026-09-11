"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from "react";

import { clampPanelRatio } from "../model/editor-state";
import { loadSplitRatio, saveSplitRatio } from "../storage/drafts";

export function useSplitPane(containerRef: RefObject<HTMLElement | null>) {
  const [editorCollapsed, setEditorCollapsed] = useState(false);
  const [previewCollapsed, setPreviewCollapsed] = useState(false);
  const [editorRatio, setEditorRatio] = useState(0.5);
  const [isResizingSplit, setIsResizingSplit] = useState(false);
  const preferencesLoadedRef = useRef(false);
  const showEditor = !editorCollapsed;
  const showPreview = !previewCollapsed;

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      setEditorRatio(loadSplitRatio(window.localStorage));
      preferencesLoadedRef.current = true;
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);
  useEffect(() => {
    if (!preferencesLoadedRef.current) return;
    saveSplitRatio(window.localStorage, editorRatio);
  }, [editorRatio]);

  const handleSplitterPointerDown = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (!showEditor || !showPreview) return;
      event.preventDefault();
      setIsResizingSplit(true);
      try {
        event.currentTarget.setPointerCapture(event.pointerId);
      } catch {
        // Pointer capture is an enhancement; global listeners still complete the drag.
      }
    },
    [showEditor, showPreview],
  );

  useEffect(() => {
    if (!isResizingSplit) return;
    const handleMove = (event: PointerEvent) => {
      const container = containerRef.current;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      if (rect.width <= 0) return;
      setEditorRatio(clampPanelRatio((event.clientX - rect.left) / rect.width));
    };
    const handleEnd = () => setIsResizingSplit(false);
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleEnd);
    window.addEventListener("pointercancel", handleEnd);
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleEnd);
      window.removeEventListener("pointercancel", handleEnd);
    };
  }, [containerRef, isResizingSplit]);

  return {
    editorCollapsed,
    editorRatio,
    handleSplitterPointerDown,
    isResizingSplit,
    previewCollapsed,
    setEditorCollapsed,
    setEditorRatio,
    setPreviewCollapsed,
    showEditor,
    showPreview,
  };
}
