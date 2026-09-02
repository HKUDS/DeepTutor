"use client";

import { useCallback, useEffect, useRef } from "react";

export function useSelectionEdit() {
  const controllerRef = useRef<AbortController | null>(null);

  const cancelSelectionRequest = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
  }, []);

  const startSelectionRequest = useCallback(() => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    return controller;
  }, []);

  const finishSelectionRequest = useCallback((controller: AbortController) => {
    if (controllerRef.current === controller) controllerRef.current = null;
  }, []);

  useEffect(() => cancelSelectionRequest, [cancelSelectionRequest]);

  return {
    cancelSelectionRequest,
    finishSelectionRequest,
    startSelectionRequest,
  };
}
