"use client";

import { useEffect, useMemo, useState } from "react";

import { fetchCapabilityCatalog } from "./api";
import type { CapabilityDescriptor } from "./model";
import {
  mergeCapabilityPresentations,
  visibleCapabilityPresentations,
} from "./presentation";

function fallbackDescriptors(): CapabilityDescriptor[] {
  return [
    {
      id: "chat",
      kind: "capability",
      available: true,
      manifest: null,
      configSchema: null,
    },
  ];
}

export function useCapabilityCatalog() {
  const [descriptors, setDescriptors] =
    useState<CapabilityDescriptor[]>(fallbackDescriptors);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchCapabilityCatalog()
      .then((next) => {
        if (cancelled) return;
        setDescriptors(next.length > 0 ? next : fallbackDescriptors());
        setError(null);
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setError(reason instanceof Error ? reason : new Error(String(reason)));
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const capabilities = useMemo(
    () => mergeCapabilityPresentations(descriptors),
    [descriptors],
  );
  const visibleCapabilities = useMemo(
    () => visibleCapabilityPresentations(capabilities),
    [capabilities],
  );

  return { capabilities, descriptors, error, isLoading, visibleCapabilities };
}

export type CapabilityFilter = (name: string) => boolean;

export function useCapabilityFilter(): CapabilityFilter | null {
  const { descriptors, error, isLoading } = useCapabilityCatalog();
  if (isLoading) return null;
  if (error) return (name: string) => name === "chat";
  const available = new Set(
    descriptors.filter((item) => item.available).map((item) => item.id),
  );
  return (name: string) => available.has(name);
}
