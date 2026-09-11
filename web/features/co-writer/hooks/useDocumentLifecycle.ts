"use client";

import { useCallback, useEffect, useRef } from "react";

/**
 * Shared lifecycle primitives for document requests. The workspace keeps its
 * presentation state, while this hook owns cancellation and stale-result gates.
 */
export function useDocumentLifecycle() {
  const isUnmountedRef = useRef(false);
  const revisionRef = useRef(0);

  useEffect(() => {
    isUnmountedRef.current = false;
    return () => {
      isUnmountedRef.current = true;
    };
  }, []);

  const nextRevision = useCallback(() => {
    revisionRef.current += 1;
    return revisionRef.current;
  }, []);

  const isCurrentRevision = useCallback(
    (revision: number) =>
      !isUnmountedRef.current && revisionRef.current === revision,
    [],
  );

  return { isCurrentRevision, isUnmountedRef, nextRevision, revisionRef };
}
