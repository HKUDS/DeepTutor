import { useCallback, useEffect, useRef, useState } from "react";

import {
  getImaConfig,
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
  /** True while the IMA source is the one being filled in. */
  active: boolean;
}

export interface ImaConnectionController {
  /** Whether the engine page holds an account credential pair. */
  accountConfigured: boolean;
  /** True when this knowledge base supplies its own credentials instead. */
  useOwnCredentials: boolean;
  setUseOwnCredentials: (value: boolean) => void;
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
  /** Credentials are resolvable — from this form or from the account pair. */
  credentialsReady: boolean;
  canSubmit: boolean;
  knowledgeBaseId: string;
  /** What to send: empty means "use the account pair stored server-side". */
  submittedClientId: string;
  submittedApiKey: string;
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
  active,
}: UseImaConnectionOptions): ImaConnectionController {
  const [accountConfigured, setAccountConfigured] = useState(false);
  const [useOwnCredentials, setUseOwnCredentials] = useState(false);
  const [clientId, setClientId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [mode, setMode] = useState<ImaConnectionMode>("automatic");
  const [manualKnowledgeBaseId, setManualKnowledgeBaseId] = useState("");
  const [lookup, setLookup] = useState(emptyImaLookupState);
  const [manualProbe, setManualProbe] = useState<ImaProbe | null>(null);
  const requestVersionRef = useRef(0);

  // Read the account pair only once the user is actually on this source, so
  // opening the modal for any other engine costs nothing.
  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    getImaConfig()
      .then((config) => {
        if (cancelled) return;
        setAccountConfigured(config.configured);
        // Without an account pair there is nothing to inherit, so the form
        // asks for one instead of offering a choice.
        if (!config.configured) setUseOwnCredentials(true);
      })
      .catch(() => {
        if (!cancelled) setUseOwnCredentials(true);
      });
    return () => {
      cancelled = true;
    };
  }, [active]);

  // What actually goes on the wire: empty tells the server to resolve the
  // account pair, so a stored key is never round-tripped through the browser.
  const submittedClientId = useOwnCredentials ? clientId.trim() : "";
  const submittedApiKey = useOwnCredentials ? apiKey.trim() : "";
  const credentialsReady = useOwnCredentials
    ? Boolean(clientId.trim() && apiKey.trim())
    : accountConfigured;

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

  const changeUseOwnCredentials = useCallback(
    (value: boolean) => {
      setUseOwnCredentials(value);
      invalidateLookup();
    },
    [invalidateLookup],
  );

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
      if (!credentialsReady) return;

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
          clientId: submittedClientId,
          apiKey: submittedApiKey,
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
    },
    [
      credentialsReady,
      lookup.nextCursor,
      onError,
      submittedApiKey,
      submittedClientId,
    ],
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
    const knowledgeBaseId = manualKnowledgeBaseId.trim();
    if (!credentialsReady || !knowledgeBaseId) return;

    const version = ++requestVersionRef.current;
    onError(null);
    setLookup((current) => ({ ...current, status: "loading" }));
    try {
      const result = await probeImaKnowledgeBase({
        clientId: submittedClientId,
        apiKey: submittedApiKey,
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
              clientId: submittedClientId,
              apiKey: submittedApiKey,
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
  }, [
    credentialsReady,
    manualKnowledgeBaseId,
    onError,
    submittedApiKey,
    submittedClientId,
  ]);

  const canSubmit = canConnectIma({
    mode,
    name,
    clientId: submittedClientId,
    apiKey: submittedApiKey,
    credentialsReady,
    selectedId: lookup.selectedId,
    manualKnowledgeBaseId,
    manualVerification: lookup.manualVerification,
  });

  return {
    accountConfigured,
    useOwnCredentials,
    setUseOwnCredentials: changeUseOwnCredentials,
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
    credentialsReady,
    canSubmit,
    knowledgeBaseId:
      mode === "automatic" ? lookup.selectedId : manualKnowledgeBaseId.trim(),
    submittedClientId,
    submittedApiKey,
    reset,
    load,
    select,
    probe,
  };
}
