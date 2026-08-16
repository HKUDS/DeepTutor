import { useCallback, useRef, useState } from "react";

import {
  listImaKnowledgeBases,
  probeImaKnowledgeBase,
  type ImaProbe,
} from "@/lib/knowledge-api";
import {
  canConnectIma,
  emptyImaLookupState,
  mergeImaKnowledgeBases,
  nextAutoName,
  type ImaConnectionMode,
  type ImaKnowledgeBaseOption,
  type ImaLookupState,
} from "@/lib/ima-connection";

interface UseImaConnectionOptions {
  name: string;
  onNameChange: (name: string) => void;
  onError: (error: string | null) => void;
}

export interface ImaConnectionController {
  clientId: string;
  setClientId: (value: string) => void;
  apiKey: string;
  setApiKey: (value: string) => void;
  mode: ImaConnectionMode;
  setMode: (value: ImaConnectionMode) => void;
  manualKnowledgeBaseId: string;
  setManualKnowledgeBaseId: (value: string) => void;
  lookup: ImaLookupState;
  manualProbe: ImaProbe | null;
  canSubmit: boolean;
  knowledgeBaseId: string;
  reset: () => void;
  load: (reset: boolean) => Promise<void>;
  select: (item: ImaKnowledgeBaseOption) => void;
  probe: () => Promise<void>;
}

/** Owns the credential-sensitive IMA connection flow outside the modal UI. */
export function useImaConnection({
  name,
  onNameChange,
  onError,
}: UseImaConnectionOptions): ImaConnectionController {
  const [clientId, setClientId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [mode, setMode] = useState<ImaConnectionMode>("automatic");
  const [manualKnowledgeBaseId, setManualKnowledgeBaseId] = useState("");
  const [lookup, setLookup] = useState(emptyImaLookupState);
  const [manualProbe, setManualProbe] = useState<ImaProbe | null>(null);
  const requestVersionRef = useRef(0);

  const reset = useCallback(() => {
    requestVersionRef.current += 1;
    setClientId("");
    setApiKey("");
    setMode("automatic");
    setManualKnowledgeBaseId("");
    setLookup(emptyImaLookupState());
    setManualProbe(null);
    onError(null);
  }, [onError]);

  const invalidateLookup = useCallback(() => {
    requestVersionRef.current += 1;
    setLookup((current) => ({
      ...emptyImaLookupState(),
      lastAutoName: current.lastAutoName,
    }));
    setManualProbe(null);
    onError(null);
  }, [onError]);

  const changeClientId = useCallback(
    (value: string) => {
      setClientId(value);
      invalidateLookup();
    },
    [invalidateLookup],
  );

  const changeApiKey = useCallback(
    (value: string) => {
      setApiKey(value);
      invalidateLookup();
    },
    [invalidateLookup],
  );

  const changeMode = useCallback(
    (value: ImaConnectionMode) => {
      setMode(value);
      invalidateLookup();
    },
    [invalidateLookup],
  );

  const changeManualKnowledgeBaseId = useCallback(
    (value: string) => {
      setManualKnowledgeBaseId(value);
      invalidateLookup();
    },
    [invalidateLookup],
  );

  const load = useCallback(
    async (resetPage: boolean) => {
      const normalizedClientId = clientId.trim();
      const normalizedApiKey = apiKey.trim();
      if (!normalizedClientId || !normalizedApiKey) return;

      const version = ++requestVersionRef.current;
      const cursor = resetPage ? "" : lookup.nextCursor;
      onError(null);
      setLookup((current) =>
        resetPage
          ? {
              ...emptyImaLookupState(),
              status: "loading",
              isEnd: false,
              lastAutoName: current.lastAutoName,
            }
          : { ...current, status: "loading" },
      );
      try {
        const page = await listImaKnowledgeBases({
          clientId: normalizedClientId,
          apiKey: normalizedApiKey,
          cursor,
          limit: 20,
        });
        if (requestVersionRef.current !== version) return;
        setLookup((current) => {
          const knowledgeBases = mergeImaKnowledgeBases(
            resetPage ? [] : current.knowledgeBases,
            page.knowledge_bases,
          );
          return {
            ...current,
            status: knowledgeBases.length > 0 ? "ready" : "empty",
            knowledgeBases,
            selectedId: resetPage ? "" : current.selectedId,
            nextCursor: page.next_cursor,
            isEnd: page.is_end,
            manualVerification: null,
          };
        });
      } catch (error) {
        if (requestVersionRef.current !== version) return;
        setLookup((current) => ({
          ...current,
          status: current.knowledgeBases.length > 0 ? "ready" : "error",
        }));
        onError(error instanceof Error ? error.message : String(error));
      }
    }, [apiKey, clientId, lookup.nextCursor, onError],
  );

  const select = useCallback(
    (item: ImaKnowledgeBaseOption) => {
      const autoFilled = !name.trim() || name === lookup.lastAutoName;
      onNameChange(nextAutoName(name, lookup.lastAutoName, item.name));
      setLookup((current) => ({
        ...current,
        selectedId: item.id,
        lastAutoName: autoFilled ? item.name : current.lastAutoName,
      }));
    },
    [lookup.lastAutoName, name, onNameChange],
  );

  const probe = useCallback(async () => {
    const normalizedClientId = clientId.trim();
    const normalizedApiKey = apiKey.trim();
    const knowledgeBaseId = manualKnowledgeBaseId.trim();
    if (!normalizedClientId || !normalizedApiKey || !knowledgeBaseId) return;

    const version = ++requestVersionRef.current;
    onError(null);
    setLookup((current) => ({ ...current, status: "loading" }));
    try {
      const result = await probeImaKnowledgeBase({
        clientId: normalizedClientId,
        apiKey: normalizedApiKey,
        knowledgeBaseId,
      });
      if (requestVersionRef.current !== version) return;
      setManualProbe(result);
      setLookup((current) => ({
        ...current,
        status: result.ok ? "manual_verified" : "error",
        manualVerification: result.ok
          ? {
              ok: true,
              clientId: normalizedClientId,
              apiKey: normalizedApiKey,
              knowledgeBaseId,
            }
          : null,
      }));
    } catch (error) {
      if (requestVersionRef.current !== version) return;
      setLookup((current) => ({
        ...current,
        status: "error",
        manualVerification: null,
      }));
      setManualProbe(null);
      onError(error instanceof Error ? error.message : String(error));
    }
  }, [apiKey, clientId, manualKnowledgeBaseId, onError]);

  const canSubmit = canConnectIma({
    mode,
    name,
    clientId,
    apiKey,
    selectedId: lookup.selectedId,
    manualKnowledgeBaseId,
    manualVerification: lookup.manualVerification,
  });

  return {
    clientId,
    setClientId: changeClientId,
    apiKey,
    setApiKey: changeApiKey,
    mode,
    setMode: changeMode,
    manualKnowledgeBaseId,
    setManualKnowledgeBaseId: changeManualKnowledgeBaseId,
    lookup,
    manualProbe,
    canSubmit,
    knowledgeBaseId:
      mode === "automatic" ? lookup.selectedId : manualKnowledgeBaseId.trim(),
    reset,
    load,
    select,
    probe,
  };
}
