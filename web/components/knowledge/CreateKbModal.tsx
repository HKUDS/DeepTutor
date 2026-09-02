"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  Check,
  ChevronRight,
  Database,
  ExternalLink,
  FolderSearch,
  Link2,
  Loader2,
  Plus,
  Server,
} from "lucide-react";
import Modal from "@/components/common/Modal";
import { useImaConnection } from "@/hooks/useImaConnection";
import {
  getGraphRagConfig,
  getLightRagConfig,
  getLightRagServerConfig,
  getLlamaIndexConfig,
  getPageIndexConfig,
  probeLightRagServer,
  type LightRagServerProbe,
} from "@/features/knowledge/api/engines";
import {
  probeLinkedFolder,
  probeWeKnora,
  type KnowledgeUploadPolicy,
  type LinkedFolderProbe,
  type RagProviderSummary,
  type WeKnoraProbe,
} from "@/features/knowledge/api/catalog";
import {
  createProviders,
  IMA_PROVIDER,
  linkSourceEnabled,
} from "@/lib/ima-connection";
import {
  uploadPolicyForProvider,
  validateFiles,
} from "@/lib/knowledge-helpers";
import FileDropZone from "./FileDropZone";
import ImaConnectionFields from "./ImaConnectionFields";
import KnowledgeEngineIcon from "./KnowledgeEngineIcon";

const OBSIDIAN_SOURCE = "obsidian";
const MARGINNOTE4_SOURCE = "marginnote4";
const LIGHTRAG_SERVER_PROVIDER = "lightrag-server";
const WEKNORA_PROVIDER = "weknora";
const EXAMPLE_INDEX_PATH = "/Users/you/knowledge_bases/my-kb";
const EXAMPLE_VAULT_PATH = "/Users/you/Documents/MyVault";
const EXAMPLE_SERVER_URL = "http://localhost:9621";

type Mode = "new" | "link";

interface CreateKbModalProps {
  isOpen: boolean;
  onClose: () => void;
  providers: RagProviderSummary[];
  uploadPolicy: KnowledgeUploadPolicy;
  onCreate: (params: {
    name: string;
    provider: string;
    files: File[];
    pageindexMode?: "flash" | "standard";
    searchMode?: string;
  }) => Promise<void>;
  /** Link a pre-built engine index folder in place (no copy, no re-index). */
  onConnectLinkedFolder: (params: {
    name: string;
    folderPath: string;
    provider: string;
  }) => Promise<void>;
  /** Connect a live Obsidian vault (no index). */
  onConnectObsidian: (params: {
    name: string;
    vaultPath: string;
  }) => Promise<void>;
  /** Connect an external LightRAG server (retrieval only, no local index). */
  onConnectLightRagServer: (params: {
    name: string;
    serverUrl: string;
    apiKey?: string;
    mode?: string;
  }) => Promise<void>;
  /** Connect a self-hosted WeKnora knowledge base (retrieval only). */
  onConnectWeKnora: (params: {
    name: string;
    serverUrl: string;
    apiKey: string;
    knowledgeBaseId: string;
  }) => Promise<void>;
  /** Connect a MarginNote 4 library (its Add-on pushes objects in; no index). */
  onConnectMarginNote4: (params: { name: string }) => Promise<void>;
  /** Connect a Tencent IMA knowledge base (retrieval only, no local index). */
  onConnectIma: (params: {
    name: string;
    clientId: string;
    apiKey: string;
    knowledgeBaseId: string;
  }) => Promise<void>;
  /** Open the RAG pipeline settings (to add a missing API key). */
  onConfigureProvider?: (providerId: string) => void;
  /** Open straight into a given mode (e.g. "link" from the Obsidian card). */
  initialMode?: Mode;
  /** Pre-select a link source (engine id or "obsidian") when opening in link mode. */
  initialSource?: string;
}

export default function CreateKbModal({
  isOpen,
  onClose,
  providers,
  uploadPolicy,
  onCreate,
  onConnectLinkedFolder,
  onConnectObsidian,
  onConnectLightRagServer,
  onConnectWeKnora,
  onConnectMarginNote4,
  onConnectIma,
  onConfigureProvider,
  initialMode = "new",
  initialSource,
}: CreateKbModalProps) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<Mode>("new");
  const [name, setName] = useState("");
  const [provider, setProvider] = useState("llamaindex");
  const [files, setFiles] = useState<File[]>([]);
  const [pageIndexMode, setPageIndexMode] = useState<"" | "flash" | "standard">(
    "",
  );
  // Link mode: the source is either an engine id or the Obsidian sentinel.
  const [linkSource, setLinkSource] = useState(OBSIDIAN_SOURCE);
  const [folderPath, setFolderPath] = useState("");
  const [probe, setProbe] = useState<LinkedFolderProbe | null>(null);
  const [probing, setProbing] = useState(false);
  // LightRAG Server engine (new mode): a connection instead of an upload.
  const [serverUrl, setServerUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [retrievalMode, setRetrievalMode] = useState("");
  const [serverDefault, setServerDefault] = useState<{
    server_url: string;
    api_key_set: boolean;
  } | null>(null);
  const [engineDefaultSummary, setEngineDefaultSummary] = useState<string[]>(
    [],
  );
  const [serverProbe, setServerProbe] = useState<LightRagServerProbe | null>(
    null,
  );
  const [serverProbing, setServerProbing] = useState(false);
  const [weKnoraKnowledgeBaseId, setWeKnoraKnowledgeBaseId] = useState("");
  const [weKnoraProbe, setWeKnoraProbe] = useState<WeKnoraProbe | null>(null);
  const [weKnoraProbing, setWeKnoraProbing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const linkIsObsidian = linkSource === OBSIDIAN_SOURCE;
  const linkIsMarginNote = linkSource === MARGINNOTE4_SOURCE;
  const linkIsIma = linkSource === IMA_PROVIDER;
  const imaConnection = useImaConnection({
    name,
    onNameChange: setName,
    onError: setError,
    active: linkIsIma,
  });

  const firstLinkable = providers.find((p) => p.linkable)?.id;

  const handleClose = () => {
    imaConnection.reset();
    onClose();
  };

  const handleModeChange = (nextMode: Mode) => {
    if (nextMode !== "link") imaConnection.reset();
    setMode(nextMode);
  };

  const handleLinkSourceChange = (source: string) => {
    if (source !== IMA_PROVIDER) imaConnection.reset();
    setLinkSource(source);
  };

  // Reset the form only on the closed → open transition. While the modal is
  // open, background indexing polls replace `providers` (and friends) every
  // few seconds, and a data refresh must never wipe user input (#691).
  const wasOpenRef = useRef(false);
  useEffect(() => {
    const justOpened = isOpen && !wasOpenRef.current;
    wasOpenRef.current = isOpen;
    if (!justOpened) return;
    setMode(initialMode);
    setName("");
    setFiles([]);
    setPageIndexMode("");
    setError(null);
    const initialProvider = createProviders(providers).find(
      (item) => item.id === initialSource,
    )?.id;
    setProvider(
      initialProvider || createProviders(providers)[0]?.id || "llamaindex",
    );
    setLinkSource(initialSource || firstLinkable || OBSIDIAN_SOURCE);
    setFolderPath("");
    setProbe(null);
    setProbing(false);
    setServerUrl("");
    setApiKey("");
    setRetrievalMode("");
    setServerDefault(null);
    setServerProbe(null);
    setServerProbing(false);
    setWeKnoraKnowledgeBaseId("");
    setWeKnoraProbe(null);
    setWeKnoraProbing(false);
  }, [isOpen, providers, firstLinkable, initialMode, initialSource]);

  useEffect(() => {
    if (!isOpen || mode !== "new") return;
    let cancelled = false;

    const load = async () => {
      try {
        let summary: string[] = [];
        if (provider === "llamaindex") {
          const config = await getLlamaIndexConfig();
          summary = [
            `${t("Retrieval profile")}: ${config.retrieval_profile}`,
            `${t("Results per query")}: ${config.top_k}`,
            `${t("Chunk size")}: ${config.chunk_size} / ${t("Chunk overlap")}: ${config.chunk_overlap}`,
          ];
        } else if (provider === "graphrag") {
          const config = await getGraphRagConfig();
          summary = [
            `${t("Response style")}: ${config.response_type}`,
            `${t("Community level")}: ${config.community_level}`,
          ];
        } else if (provider === "lightrag") {
          const config = await getLightRagConfig();
          summary = [
            `${t("Results per query")}: ${config.top_k}`,
            `${t("Files in parallel")}: ${config.max_concurrent_files}`,
            `${t("Concurrent LLM calls")}: ${config.llm_model_max_async}`,
          ];
        } else if (provider === "pageindex") {
          const config = await getPageIndexConfig();
          summary = [
            config.configured ? t("API key configured") : t("API key missing"),
          ];
        } else if (provider === LIGHTRAG_SERVER_PROVIDER) {
          const config = await getLightRagServerConfig();
          if (!cancelled) {
            setServerDefault(config);
            setServerUrl(config.server_url);
          }
          summary = [
            config.server_url || t("No default server URL"),
            config.api_key_set ? t("API key configured") : t("No API key"),
          ];
        } else if (provider === "pageindex-oss") {
          summary = [t("Uses the globally active chat model")];
        }
        if (!cancelled) setEngineDefaultSummary(summary);
      } catch {
        if (!cancelled) setEngineDefaultSummary([]);
      }
    };

    setEngineDefaultSummary([]);
    if (provider !== LIGHTRAG_SERVER_PROVIDER) setServerDefault(null);
    void load();
    return () => {
      cancelled = true;
    };
  }, [isOpen, mode, provider, t]);

  // A fresh path / source invalidates a stale probe verdict.
  useEffect(() => {
    setProbe(null);
  }, [folderPath, linkSource]);

  // A fresh URL / key invalidates a stale server connection test.
  useEffect(() => {
    setServerProbe(null);
  }, [serverUrl, apiKey]);

  // A fresh URL, key, or remote KB id invalidates a stale WeKnora verdict.
  useEffect(() => {
    setWeKnoraProbe(null);
  }, [serverUrl, apiKey, weKnoraKnowledgeBaseId]);

  // ---- New mode (build a fresh index) ----------------------------------
  const activeProvider = providers.find((p) => p.id === provider);
  const providerNeedsKey =
    !!activeProvider?.requires_api_key && activeProvider?.configured === false;
  const providerUnavailable = activeProvider?.configured === false;
  const isPageIndexCloud = provider === "pageindex";
  const isPageIndexOSS = provider === "pageindex-oss";
  const isLightRagServer = provider === LIGHTRAG_SERVER_PROVIDER;
  const isWeKnora = provider === WEKNORA_PROVIDER;
  const modeOptions = activeProvider?.modes ?? [];

  const policyForProvider = uploadPolicyForProvider(uploadPolicy, provider);

  const selection = validateFiles(files, policyForProvider, t);

  // ---- Link mode (mount an existing folder) ----------------------------
  const trimmed = name.trim();
  const trimmedPath = folderPath.trim();

  const trimmedServerUrl = serverUrl.trim();

  const canSubmit = (() => {
    if (submitting) return false;
    if (!trimmed) return false;
    if (mode === "new") {
      if (isLightRagServer) {
        // The connection must pass the test before a KB is bound to it.
        return !!trimmedServerUrl && !!serverProbe?.ok;
      }
      if (isWeKnora) {
        return (
          !!trimmedServerUrl &&
          !!apiKey.trim() &&
          !!weKnoraKnowledgeBaseId.trim() &&
          !!weKnoraProbe?.ok
        );
      }
      return !providerUnavailable;
    }
    if (linkIsIma) return imaConnection.canSubmit;
    if (linkIsMarginNote) return true;
    if (!trimmedPath) return false;
    if (linkIsObsidian) return true;
    // An engine index must pass the probe before it can be linked.
    return !!probe?.ok;
  })();

  const handleProbe = async () => {
    if (!trimmedPath || linkIsObsidian || probing) return;
    setProbing(true);
    setError(null);
    try {
      const result = await probeLinkedFolder({
        folderPath: trimmedPath,
        provider: linkSource,
      });
      setProbe(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setProbing(false);
    }
  };

  const handleTestServer = async () => {
    if (!trimmedServerUrl || serverProbing) return;
    setServerProbing(true);
    setError(null);
    try {
      const result = await probeLightRagServer({
        serverUrl: trimmedServerUrl,
        apiKey: apiKey.trim(),
        useSavedApiKey:
          !apiKey.trim() &&
          !!serverDefault?.api_key_set &&
          trimmedServerUrl.replace(/\/+$/, "") === serverDefault.server_url,
      });
      setServerProbe(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setServerProbing(false);
    }
  };

  const handleTestWeKnora = async () => {
    if (
      !trimmedServerUrl ||
      !apiKey.trim() ||
      !weKnoraKnowledgeBaseId.trim() ||
      weKnoraProbing
    ) {
      return;
    }
    setWeKnoraProbing(true);
    setError(null);
    try {
      const result = await probeWeKnora({
        serverUrl: trimmedServerUrl,
        apiKey: apiKey.trim(),
        knowledgeBaseId: weKnoraKnowledgeBaseId.trim(),
      });
      setWeKnoraProbe(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setWeKnoraProbing(false);
    }
  };

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      if (mode === "new") {
        if (isLightRagServer) {
          await onConnectLightRagServer({
            name: trimmed,
            serverUrl: trimmedServerUrl,
            apiKey: apiKey.trim(),
            mode: retrievalMode,
          });
        } else if (isWeKnora) {
          await onConnectWeKnora({
            name: trimmed,
            serverUrl: trimmedServerUrl,
            apiKey: apiKey.trim(),
            knowledgeBaseId: weKnoraKnowledgeBaseId.trim(),
          });
        } else {
          await onCreate({
            name: trimmed,
            provider,
            files: selection.validFiles,
            pageindexMode:
              isPageIndexOSS && pageIndexMode ? pageIndexMode : undefined,
            searchMode: retrievalMode || undefined,
          });
        }
      } else if (linkIsIma) {
        await onConnectIma({
          name: trimmed,
          // Empty when the engine's account credentials are used — the server
          // resolves them and the KB stores no copy.
          clientId: imaConnection.submittedClientId,
          apiKey: imaConnection.submittedApiKey,
          knowledgeBaseId: imaConnection.knowledgeBaseId,
        });
      } else if (linkIsMarginNote) {
        await onConnectMarginNote4({ name: trimmed });
      } else if (linkIsObsidian) {
        await onConnectObsidian({ name: trimmed, vaultPath: trimmedPath });
      } else {
        await onConnectLinkedFolder({
          name: trimmed,
          folderPath: trimmedPath,
          provider: linkSource,
        });
      }
      handleClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const submitLabel =
    mode === "new"
      ? isLightRagServer || isWeKnora
        ? t("Connect")
        : t("Create")
      : linkIsObsidian || linkIsIma || linkIsMarginNote
        ? t("Connect")
        : t("Link");

  return (
    <Modal
      isOpen={isOpen}
      onClose={submitting ? () => {} : handleClose}
      title={t("Create knowledge base")}
      titleIcon={<Plus size={16} />}
      width="lg"
      closeOnBackdrop={!submitting}
      closeOnEscape={!submitting}
      footer={
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={handleClose}
            disabled={submitting}
            className="rounded-md px-3 py-1.5 text-[12.5px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40"
          >
            {t("Cancel")}
          </button>
          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={!canSubmit}
            className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-3.5 py-1.5 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {submitting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : mode === "new" && !isLightRagServer && !isWeKnora ? (
              <Plus size={14} />
            ) : (
              <Link2 size={14} />
            )}
            {submitLabel}
          </button>
        </div>
      }
    >
      <div className="space-y-4 px-5 py-4">
        {/* New vs. link existing */}
        <ModeToggle
          mode={mode}
          onChange={handleModeChange}
          disabled={submitting}
          t={t}
        />

        <div>
          <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("Knowledge base name")}
          </label>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            autoFocus
            disabled={submitting}
            placeholder={t("e.g. project-papers")}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25 disabled:opacity-50"
          />
        </div>

        {mode === "new" ? (
          <NewModeFields
            providers={createProviders(providers)}
            provider={provider}
            setProvider={setProvider}
            submitting={submitting}
            providerUnavailable={providerUnavailable}
            providerNeedsKey={providerNeedsKey}
            onConfigureProvider={onConfigureProvider}
            activeProvider={activeProvider}
            engineDefaultSummary={engineDefaultSummary}
            modeOptions={modeOptions}
            retrievalMode={retrievalMode}
            setRetrievalMode={setRetrievalMode}
            isPageIndexCloud={isPageIndexCloud}
            isPageIndexOSS={isPageIndexOSS}
            pageIndexMode={pageIndexMode}
            setPageIndexMode={setPageIndexMode}
            files={files}
            setFiles={setFiles}
            policyForProvider={policyForProvider}
            connectionForm={
              isLightRagServer ? (
                <LightRagServerFields
                  serverUrl={serverUrl}
                  setServerUrl={setServerUrl}
                  apiKey={apiKey}
                  setApiKey={setApiKey}
                  hasSavedApiKey={!!serverDefault?.api_key_set}
                  usingSavedDefault={
                    !!serverDefault?.server_url &&
                    serverUrl.trim().replace(/\/+$/, "") ===
                      serverDefault.server_url
                  }
                  submitting={submitting}
                  probing={serverProbing}
                  probe={serverProbe}
                  onTest={handleTestServer}
                  t={t}
                />
              ) : isWeKnora ? (
                <WeKnoraFields
                  serverUrl={serverUrl}
                  setServerUrl={setServerUrl}
                  apiKey={apiKey}
                  setApiKey={setApiKey}
                  knowledgeBaseId={weKnoraKnowledgeBaseId}
                  setKnowledgeBaseId={setWeKnoraKnowledgeBaseId}
                  submitting={submitting}
                  probing={weKnoraProbing}
                  probe={weKnoraProbe}
                  onTest={handleTestWeKnora}
                  t={t}
                />
              ) : null
            }
            t={t}
          />
        ) : (
          <LinkModeFields
            providers={providers}
            linkSource={linkSource}
            setLinkSource={handleLinkSourceChange}
            linkIsObsidian={linkIsObsidian}
            linkIsIma={linkIsIma}
            linkIsMarginNote={linkIsMarginNote}
            folderPath={folderPath}
            setFolderPath={setFolderPath}
            submitting={submitting}
            probing={probing}
            probe={probe}
            onProbe={handleProbe}
            connectionForm={
              linkIsIma ? (
                <ImaConnectionFields
                  connection={imaConnection}
                  submitting={submitting}
                />
              ) : null
            }
            t={t}
          />
        )}

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
            <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed">
              {error}
            </pre>
          </div>
        )}
      </div>
    </Modal>
  );
}

type TFn = (key: string, options?: Record<string, unknown>) => string;

function ModeToggle({
  mode,
  onChange,
  disabled,
  t,
}: {
  mode: Mode;
  onChange: (mode: Mode) => void;
  disabled: boolean;
  t: TFn;
}) {
  const options: {
    id: Mode;
    label: string;
    hint: string;
    icon: typeof Plus;
  }[] = [
    {
      id: "new",
      label: t("Create new"),
      hint: t("Upload documents and build a fresh index."),
      icon: Plus,
    },
    {
      id: "link",
      label: t("Link existing"),
      hint: t(
        "Reuse an index you already built — read in place, no upload or re-index.",
      ),
      icon: Link2,
    },
  ];
  return (
    <div className="grid grid-cols-2 gap-2">
      {options.map((opt) => {
        const selected = mode === opt.id;
        const Icon = opt.icon;
        return (
          <button
            key={opt.id}
            type="button"
            disabled={disabled}
            onClick={() => onChange(opt.id)}
            className={`flex flex-col gap-1 rounded-2xl border p-3 text-left transition-colors disabled:opacity-50 ${
              selected
                ? "border-[var(--primary)] bg-[var(--primary)]/5"
                : "border-[var(--border)] hover:border-[var(--ring)]"
            }`}
          >
            <span className="flex items-center gap-1.5 text-[13px] font-medium text-[var(--foreground)]">
              <Icon className="h-3.5 w-3.5" />
              {opt.label}
            </span>
            <span className="text-[11px] leading-snug text-[var(--muted-foreground)]">
              {opt.hint}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function NewModeFields({
  providers,
  provider,
  setProvider,
  activeProvider,
  engineDefaultSummary,
  modeOptions,
  retrievalMode,
  setRetrievalMode,
  submitting,
  providerUnavailable,
  providerNeedsKey,
  onConfigureProvider,
  isPageIndexCloud,
  isPageIndexOSS,
  pageIndexMode,
  setPageIndexMode,
  files,
  setFiles,
  policyForProvider,
  connectionForm,
  t,
}: {
  providers: RagProviderSummary[];
  provider: string;
  setProvider: (id: string) => void;
  activeProvider?: RagProviderSummary;
  engineDefaultSummary: string[];
  modeOptions: string[];
  retrievalMode: string;
  setRetrievalMode: (mode: string) => void;
  submitting: boolean;
  providerUnavailable: boolean;
  providerNeedsKey: boolean;
  onConfigureProvider?: (providerId: string) => void;
  isPageIndexCloud: boolean;
  isPageIndexOSS: boolean;
  pageIndexMode: "" | "flash" | "standard";
  setPageIndexMode: (mode: "" | "flash" | "standard") => void;
  files: File[];
  setFiles: (files: File[]) => void;
  policyForProvider: KnowledgeUploadPolicy;
  /** When set, replaces the upload step (e.g. a server connection form). */
  connectionForm?: ReactNode;
  t: TFn;
}) {
  const readinessReason = providers.find(
    (item) => item.id === provider,
  )?.readiness_reason;
  return (
    <>
      <div>
        <label className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
          {t("Index engine")}
        </label>
        <div className="grid gap-2 sm:grid-cols-2">
          {providers.map((p) => {
            const selected = provider === p.id;
            const needsKey = !!p.requires_api_key && p.configured === false;
            const unavailable = p.configured === false && !p.requires_api_key;
            return (
              <div key={p.id} className="flex flex-col gap-1">
                <button
                  type="button"
                  disabled={submitting}
                  onClick={() => {
                    setProvider(p.id);
                    setRetrievalMode("");
                  }}
                  className={`group flex w-full flex-1 flex-col gap-1 rounded-2xl border p-3 text-left transition-colors disabled:opacity-50 ${
                    selected
                      ? "border-[var(--primary)] bg-[var(--primary)]/5"
                      : "border-[var(--border)] hover:border-[var(--ring)]"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex min-w-0 items-center gap-2 text-[13px] font-medium text-[var(--foreground)]">
                      <KnowledgeEngineIcon engine={p.id} size={24} />
                      <span className="truncate">{p.name}</span>
                    </span>
                    {needsKey ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:bg-amber-950/30 dark:text-amber-300">
                        {t("Needs key")}
                      </span>
                    ) : unavailable ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
                        {t("Not installed")}
                      </span>
                    ) : selected ? (
                      <Check className="h-3.5 w-3.5 text-[var(--primary)]" />
                    ) : null}
                  </div>
                  <span className="text-[11.5px] leading-snug text-[var(--muted-foreground)]">
                    {p.description}
                  </span>
                </button>
                {p.id === "pageindex" && (
                  <a
                    href="https://dash.pageindex.ai/api-keys"
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 px-1 text-[10.5px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                  >
                    {t("PageIndex API plans")}
                    <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </div>
            );
          })}
        </div>
        {providerUnavailable && (
          <div className="mt-2 flex items-center justify-between gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
            <span className="flex items-center gap-1.5">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
              {providerNeedsKey
                ? t(
                    "This engine needs an API key. Configure it before creating.",
                  )
                : t(
                    readinessReason ||
                      "This engine isn't ready on the server. Check its requirements before creating.",
                  )}
            </span>
            {providerNeedsKey && onConfigureProvider && (
              <button
                type="button"
                onClick={() => onConfigureProvider(provider)}
                className="shrink-0 rounded-md px-2 py-1 text-[11.5px] font-medium text-amber-900 underline-offset-2 hover:underline dark:text-amber-100"
              >
                {t("Configure")}
              </button>
            )}
          </div>
        )}
      </div>

      {activeProvider && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--muted)]/25 p-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-[12px] font-medium text-[var(--foreground)]">
                {t("Engine defaults")}
              </div>
              <p className="mt-0.5 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
                {t(
                  "This knowledge base starts with the saved engine configuration.",
                )}
              </p>
            </div>
            {onConfigureProvider && (
              <button
                type="button"
                onClick={() => onConfigureProvider(provider)}
                className="inline-flex shrink-0 items-center gap-1 text-[11.5px] font-medium text-[var(--primary)] hover:underline"
              >
                {t("Edit defaults")}
                <ChevronRight className="h-3 w-3" />
              </button>
            )}
          </div>
          {engineDefaultSummary.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {engineDefaultSummary.map((item) => (
                <span
                  key={item}
                  className="rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-[10.5px] text-[var(--muted-foreground)]"
                >
                  {item}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {modeOptions.length > 0 && (
        <div>
          <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("Retrieval mode")}
          </label>
          <select
            value={retrievalMode}
            onChange={(event) => setRetrievalMode(event.target.value)}
            disabled={submitting}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[12.5px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25 disabled:opacity-50"
          >
            <option value="">
              {t("Use engine default: {{mode}}", {
                mode: activeProvider?.default_mode || modeOptions[0],
              })}
            </option>
            {modeOptions.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
            {t(
              "This override applies only to this knowledge base; the engine default stays unchanged.",
            )}
          </p>
        </div>
      )}

      {isPageIndexOSS && (
        <div>
          <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("Index mode")}
            <span className="ml-2 normal-case tracking-normal text-[var(--muted-foreground)]/80">
              · {t("optional")}
            </span>
          </label>
          <select
            value={pageIndexMode}
            onChange={(event) =>
              setPageIndexMode(event.target.value as "" | "flash" | "standard")
            }
            disabled={submitting}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[12.5px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25 disabled:opacity-50"
          >
            <option value="">
              {t("Default — Flash, summaries and full optimization")}
            </option>
            <option value="flash">{t("Flash")}</option>
            <option value="standard">{t("Standard")}</option>
          </select>
          <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
            {t(
              "Uses the globally active LLM credential. Leaving this unset delegates to the PageIndex SDK default.",
            )}
          </p>
        </div>
      )}

      {connectionForm ?? (
        <div>
          <label className="mb-2 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("Initial documents")}
            <span className="ml-1 normal-case tracking-normal text-[var(--muted-foreground)]/80">
              ({t("optional")})
            </span>
            {(isPageIndexCloud || isPageIndexOSS) && (
              <span className="ml-2 normal-case tracking-normal text-[var(--muted-foreground)]/80">
                ·{" "}
                {isPageIndexOSS
                  ? t(
                      "PDF only — use PageIndex Cloud for Office, Markdown or CSV",
                    )
                  : t("PDF, Office, text and Markdown")}
              </span>
            )}
          </label>
          <FileDropZone
            files={files}
            onChange={setFiles}
            uploadPolicy={policyForProvider}
            disabled={submitting}
          />
          <p className="mt-1.5 text-[11px] text-[var(--muted-foreground)]">
            {t(
              "Skip for now — you can add GitHub sources or upload documents after creation.",
            )}
          </p>
        </div>
      )}
    </>
  );
}

function LightRagServerFields({
  serverUrl,
  setServerUrl,
  apiKey,
  setApiKey,
  hasSavedApiKey,
  usingSavedDefault,
  submitting,
  probing,
  probe,
  onTest,
  t,
}: {
  serverUrl: string;
  setServerUrl: (value: string) => void;
  apiKey: string;
  setApiKey: (value: string) => void;
  hasSavedApiKey: boolean;
  usingSavedDefault: boolean;
  submitting: boolean;
  probing: boolean;
  probe: LightRagServerProbe | null;
  onTest: () => void;
  t: TFn;
}) {
  return (
    <div className="space-y-3">
      <div>
        <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
          {t("Server URL")}
        </label>
        <div className="flex gap-2">
          <input
            value={serverUrl}
            onChange={(event) => setServerUrl(event.target.value)}
            disabled={submitting}
            placeholder={EXAMPLE_SERVER_URL}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 font-mono text-[12.5px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25 disabled:opacity-50"
          />
          <button
            type="button"
            onClick={onTest}
            disabled={submitting || probing || serverUrl.trim().length === 0}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:border-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {probing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Server className="h-3.5 w-3.5" />
            )}
            {t("Test connection")}
          </button>
        </div>
        <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
          {t(
            "The base URL of your running LightRAG server. Documents are indexed there — nothing is uploaded or copied.",
          )}
        </p>
        {usingSavedDefault && (
          <p className="mt-1 inline-flex items-center gap-1 text-[11px] font-medium text-emerald-700 dark:text-emerald-300">
            <Check className="h-3 w-3" />
            {t("Using saved engine default · editable for this KB")}
          </p>
        )}
      </div>

      <div>
        <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
          {t("API key")}
          <span className="ml-2 normal-case tracking-normal text-[var(--muted-foreground)]/80">
            · {t("optional")}
          </span>
        </label>
        <input
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
          disabled={submitting}
          type="password"
          autoComplete="off"
          placeholder={t("Only if your server requires one")}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[12.5px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25 disabled:opacity-50"
        />
      </div>

      {hasSavedApiKey && !apiKey && usingSavedDefault && (
        <p className="-mt-2 text-[11px] text-[var(--muted-foreground)]">
          {t(
            "The saved API key will be used. Enter a value only to override it.",
          )}
        </p>
      )}

      {probe && <ServerProbeVerdict probe={probe} t={t} />}
    </div>
  );
}

function ServerProbeVerdict({
  probe,
  t,
}: {
  probe: LightRagServerProbe;
  t: TFn;
}) {
  if (!probe.ok) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
        <span className="flex items-center gap-1.5 font-medium">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          {t("Could not connect")}
        </span>
        {probe.error && <p className="mt-1 leading-relaxed">{probe.error}</p>}
      </div>
    );
  }
  return (
    <div className="space-y-1 rounded-lg border border-[var(--border)] bg-[var(--muted)]/40 px-3 py-2.5 text-[12px]">
      <div className="flex items-center gap-1.5 font-medium text-emerald-700 dark:text-emerald-300">
        <Check className="h-3.5 w-3.5 shrink-0" />
        {t("Connected to LightRAG server")}
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-[var(--muted-foreground)]">
        {probe.core_version && (
          <span>{t("Core {{version}}", { version: probe.core_version })}</span>
        )}
        <span>
          {probe.auth_required ? t("API key accepted") : t("Open access")}
        </span>
      </div>
    </div>
  );
}

function WeKnoraFields({
  serverUrl,
  setServerUrl,
  apiKey,
  setApiKey,
  knowledgeBaseId,
  setKnowledgeBaseId,
  submitting,
  probing,
  probe,
  onTest,
  t,
}: {
  serverUrl: string;
  setServerUrl: (value: string) => void;
  apiKey: string;
  setApiKey: (value: string) => void;
  knowledgeBaseId: string;
  setKnowledgeBaseId: (value: string) => void;
  submitting: boolean;
  probing: boolean;
  probe: WeKnoraProbe | null;
  onTest: () => void;
  t: TFn;
}) {
  const testDisabled =
    submitting ||
    probing ||
    serverUrl.trim().length === 0 ||
    apiKey.trim().length === 0 ||
    knowledgeBaseId.trim().length === 0;

  return (
    <div className="space-y-3">
      <div>
        <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
          {t("Server URL")}
        </label>
        <div className="flex gap-2">
          <input
            value={serverUrl}
            onChange={(event) => setServerUrl(event.target.value)}
            disabled={submitting}
            placeholder={EXAMPLE_SERVER_URL}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 font-mono text-[12.5px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25 disabled:opacity-50"
          />
          <button
            type="button"
            onClick={onTest}
            disabled={testDisabled}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:border-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {probing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Server className="h-3.5 w-3.5" />
            )}
            {t("Test connection")}
          </button>
        </div>
        <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
          {t(
            "The base URL of your self-hosted WeKnora deployment. Documents remain there; DeepTutor only runs retrieval searches.",
          )}
        </p>
      </div>

      <div>
        <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
          {t("WeKnora API key")}
        </label>
        <input
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
          disabled={submitting}
          type="password"
          autoComplete="off"
          placeholder={t("Required to access your WeKnora knowledge base")}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[12.5px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25 disabled:opacity-50"
        />
      </div>

      <div>
        <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
          {t("WeKnora knowledge base ID")}
        </label>
        <div className="relative">
          <Database className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted-foreground)]" />
          <input
            value={knowledgeBaseId}
            onChange={(event) => setKnowledgeBaseId(event.target.value)}
            disabled={submitting}
            placeholder={t("WeKnora knowledge base ID")}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] py-2 pl-9 pr-3 font-mono text-[12.5px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25 disabled:opacity-50"
          />
        </div>
      </div>

      {probe && <WeKnoraProbeVerdict probe={probe} t={t} />}
    </div>
  );
}

function WeKnoraProbeVerdict({ probe, t }: { probe: WeKnoraProbe; t: TFn }) {
  if (!probe.ok) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
        <span className="flex items-center gap-1.5 font-medium">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          {t("Could not connect")}
        </span>
        {probe.error && <p className="mt-1 leading-relaxed">{probe.error}</p>}
      </div>
    );
  }

  return (
    <div className="space-y-1 rounded-lg border border-[var(--border)] bg-[var(--muted)]/40 px-3 py-2.5 text-[12px]">
      <div className="flex items-center gap-1.5 font-medium text-emerald-700 dark:text-emerald-300">
        <Check className="h-3.5 w-3.5 shrink-0" />
        {t("Connected to WeKnora")}
      </div>
      <div className="text-[11.5px] text-[var(--muted-foreground)]">
        {probe.knowledge_base_name
          ? t("Knowledge base {{name}}", {
              name: probe.knowledge_base_name,
            })
          : probe.knowledge_base_id}
      </div>
    </div>
  );
}

function LinkModeFields({
  providers,
  linkSource,
  setLinkSource,
  linkIsObsidian,
  linkIsIma,
  linkIsMarginNote,
  folderPath,
  setFolderPath,
  submitting,
  probing,
  probe,
  onProbe,
  connectionForm,
  t,
}: {
  providers: RagProviderSummary[];
  linkSource: string;
  setLinkSource: (id: string) => void;
  linkIsObsidian: boolean;
  linkIsIma: boolean;
  linkIsMarginNote: boolean;
  folderPath: string;
  setFolderPath: (value: string) => void;
  submitting: boolean;
  probing: boolean;
  probe: LinkedFolderProbe | null;
  onProbe: () => void;
  connectionForm?: ReactNode;
  t: TFn;
}) {
  return (
    <>
      <div>
        <label className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
          {t("Source")}
        </label>
        <div className="grid gap-2 sm:grid-cols-2">
          {providers.map((p) => {
            const selected =
              !linkIsObsidian && !linkIsMarginNote && linkSource === p.id;
            const enabled = linkSourceEnabled(p);
            const disabled = submitting || !enabled;
            return (
              <button
                key={p.id}
                type="button"
                disabled={disabled}
                onClick={() => setLinkSource(p.id)}
                title={
                  !enabled
                    ? t(
                        "This engine's index lives in the cloud and can't be linked.",
                      )
                    : undefined
                }
                className={`group flex flex-col gap-1 rounded-2xl border p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                  selected
                    ? "border-[var(--primary)] bg-[var(--primary)]/5"
                    : "border-[var(--border)] hover:border-[var(--ring)]"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="flex min-w-0 items-center gap-2 text-[13px] font-medium text-[var(--foreground)]">
                    <KnowledgeEngineIcon engine={p.id} size={24} />
                    <span className="truncate">{p.name}</span>
                  </span>
                  {selected ? (
                    <Check className="h-3.5 w-3.5 text-[var(--primary)]" />
                  ) : !enabled ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
                      {t("Cloud index")}
                    </span>
                  ) : p.id === IMA_PROVIDER ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-sky-100 px-1.5 py-0.5 text-[10px] font-medium text-sky-700 dark:bg-sky-950/30 dark:text-sky-300">
                      {t("Read only")}
                    </span>
                  ) : null}
                </div>
                <span className="text-[11.5px] leading-snug text-[var(--muted-foreground)]">
                  {p.description}
                </span>
              </button>
            );
          })}

          {/* Obsidian — a live vault, no index. */}
          <button
            type="button"
            disabled={submitting}
            onClick={() => setLinkSource(OBSIDIAN_SOURCE)}
            className={`group flex flex-col gap-1 rounded-2xl border p-3 text-left transition-colors disabled:opacity-50 ${
              linkIsObsidian
                ? "border-[var(--primary)] bg-[var(--primary)]/5"
                : "border-[var(--border)] hover:border-[var(--ring)]"
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2 text-[13px] font-medium text-[var(--foreground)]">
                <KnowledgeEngineIcon engine="obsidian" size={24} />
                {t("Obsidian")}
              </span>
              {linkIsObsidian && (
                <Check className="h-3.5 w-3.5 text-[var(--primary)]" />
              )}
            </div>
            <span className="text-[11.5px] leading-snug text-[var(--muted-foreground)]">
              {t(
                "A live Obsidian vault — browsed and edited in place, no index.",
              )}
            </span>
          </button>

          {/* MarginNote 4 — filled by its Add-on, not by a path on this disk. */}
          <button
            type="button"
            disabled={submitting}
            onClick={() => setLinkSource(MARGINNOTE4_SOURCE)}
            className={`group flex flex-col gap-1 rounded-2xl border p-3 text-left transition-colors disabled:opacity-50 ${
              linkIsMarginNote
                ? "border-[var(--primary)] bg-[var(--primary)]/5"
                : "border-[var(--border)] hover:border-[var(--ring)]"
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2 text-[13px] font-medium text-[var(--foreground)]">
                <KnowledgeEngineIcon engine="marginnote4" size={24} />
                {t("MarginNote 4")}
              </span>
              {linkIsMarginNote && (
                <Check className="h-3.5 w-3.5 text-[var(--primary)]" />
              )}
            </div>
            <span className="text-[11.5px] leading-snug text-[var(--muted-foreground)]">
              {t(
                "Notes, excerpts and cards pushed in by the MarginNote 4 add-on.",
              )}
            </span>
          </button>
        </div>
      </div>

      {linkIsIma ? (
        connectionForm
      ) : linkIsMarginNote ? (
        <p className="rounded-lg border border-[var(--border)] bg-[var(--muted)]/40 px-3 py-2 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
          {t(
            "The library starts empty. Pair a device from its Devices tab, then enter the token in the MarginNote 4 add-on to start syncing.",
          )}
        </p>
      ) : (
        <>
          <div>
            <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
              {linkIsObsidian ? t("Vault path") : t("Folder path")}
            </label>
            <div className="flex gap-2">
              <input
                value={folderPath}
                onChange={(event) => setFolderPath(event.target.value)}
                disabled={submitting}
                placeholder={
                  linkIsObsidian ? EXAMPLE_VAULT_PATH : EXAMPLE_INDEX_PATH
                }
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 font-mono text-[12.5px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25 disabled:opacity-50"
              />
              {!linkIsObsidian && (
                <button
                  type="button"
                  onClick={onProbe}
                  disabled={
                    submitting || probing || folderPath.trim().length === 0
                  }
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:border-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {probing ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <FolderSearch className="h-3.5 w-3.5" />
                  )}
                  {t("Check folder")}
                </button>
              )}
            </div>
            <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
              {linkIsObsidian
                ? t("The absolute path to the vault folder on this machine.")
                : t(
                    "The absolute path to a knowledge base folder on this machine — nothing is copied.",
                  )}
            </p>
          </div>

          {!linkIsObsidian && probe && <ProbeVerdict probe={probe} t={t} />}
        </>
      )}
    </>
  );
}

function ProbeVerdict({ probe, t }: { probe: LinkedFolderProbe; t: TFn }) {
  if (!probe.ok) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
        <span className="flex items-center gap-1.5 font-medium">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          {t("This folder can't be linked")}
        </span>
        {probe.error && <p className="mt-1 leading-relaxed">{probe.error}</p>}
      </div>
    );
  }

  const compatible = probe.embedding.compatible;
  return (
    <div className="space-y-2 rounded-lg border border-[var(--border)] bg-[var(--muted)]/40 px-3 py-2.5 text-[12px]">
      <div className="flex items-center gap-1.5 font-medium text-emerald-700 dark:text-emerald-300">
        <Check className="h-3.5 w-3.5 shrink-0" />
        {t("Ready index found")}
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-[var(--muted-foreground)]">
        {probe.version && <span className="font-mono">{probe.version}</span>}
        {probe.doc_count != null && (
          <span>{t("{{count}} documents", { count: probe.doc_count })}</span>
        )}
        {compatible === true && (
          <span className="inline-flex items-center gap-1 text-emerald-700 dark:text-emerald-300">
            <Check className="h-3 w-3" />
            {t("Embedding model matches")}
          </span>
        )}
      </div>
      {probe.warnings.map((warning, index) => (
        <p
          key={index}
          className="flex items-start gap-1.5 leading-relaxed text-amber-700 dark:text-amber-300"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{warning}</span>
        </p>
      ))}
    </div>
  );
}
