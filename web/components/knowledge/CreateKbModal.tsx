"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  Check,
  FolderOpen,
  FolderSearch,
  Link2,
  Loader2,
  Plus,
  Server,
} from "lucide-react";
import Modal from "@/components/common/Modal";
import {
  probeLightRagServer,
  probeLinkedFolder,
  type KnowledgeUploadPolicy,
  type LightRagServerProbe,
  type LinkedFolderProbe,
  type RagProviderSummary,
} from "@/lib/knowledge-api";
import { validateFiles } from "@/lib/knowledge-helpers";
import FileDropZone from "./FileDropZone";

const PAGEINDEX_FORMATS = [".pdf", ".md", ".markdown"];
const OBSIDIAN_SOURCE = "obsidian";
const LIGHTRAG_SERVER_PROVIDER = "lightrag-server";
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
  /** Open the RAG pipeline settings (to add a missing API key). */
  onConfigureProvider?: () => void;
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
  onConfigureProvider,
  initialMode = "new",
  initialSource,
}: CreateKbModalProps) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<Mode>("new");
  const [name, setName] = useState("");
  const [provider, setProvider] = useState("llamaindex");
  const [files, setFiles] = useState<File[]>([]);
  // Link mode: the source is either an engine id or the Obsidian sentinel.
  const [linkSource, setLinkSource] = useState(OBSIDIAN_SOURCE);
  const [folderPath, setFolderPath] = useState("");
  const [probe, setProbe] = useState<LinkedFolderProbe | null>(null);
  const [probing, setProbing] = useState(false);
  // LightRAG Server engine (new mode): a connection instead of an upload.
  const [serverUrl, setServerUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [serverMode, setServerMode] = useState("");
  const [serverProbe, setServerProbe] = useState<LightRagServerProbe | null>(
    null,
  );
  const [serverProbing, setServerProbing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const firstLinkable = providers.find((p) => p.linkable)?.id;

  useEffect(() => {
    if (!isOpen) return;
    setMode(initialMode);
    setName("");
    setFiles([]);
    setError(null);
    setProvider(initialSource || providers[0]?.id || "llamaindex");
    setLinkSource(initialSource || firstLinkable || OBSIDIAN_SOURCE);
    setFolderPath("");
    setProbe(null);
    setProbing(false);
    setServerUrl("");
    setApiKey("");
    setServerMode("");
    setServerProbe(null);
    setServerProbing(false);
  }, [isOpen, providers, firstLinkable, initialMode, initialSource]);

  // A fresh path / source invalidates a stale probe verdict.
  useEffect(() => {
    setProbe(null);
  }, [folderPath, linkSource]);

  // A fresh URL / key invalidates a stale server connection test.
  useEffect(() => {
    setServerProbe(null);
  }, [serverUrl, apiKey]);

  // ---- New mode (build a fresh index) ----------------------------------
  const activeProvider = providers.find((p) => p.id === provider);
  const providerNeedsKey =
    !!activeProvider?.requires_api_key && activeProvider?.configured === false;
  const providerUnavailable = activeProvider?.configured === false;
  const isPageIndex = provider === "pageindex";
  const isLightRagServer = provider === LIGHTRAG_SERVER_PROVIDER;
  const serverModeOptions = activeProvider?.modes ?? [];
  const effectiveServerMode =
    serverMode || activeProvider?.default_mode || serverModeOptions[0] || "";

  const policyForProvider: KnowledgeUploadPolicy = isPageIndex
    ? {
        ...uploadPolicy,
        extensions: PAGEINDEX_FORMATS,
        accept: PAGEINDEX_FORMATS.join(","),
      }
    : uploadPolicy;

  const selection = validateFiles(files, policyForProvider, t);

  // ---- Link mode (mount an existing folder) ----------------------------
  const linkIsObsidian = linkSource === OBSIDIAN_SOURCE;
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
      return !providerUnavailable && selection.validFiles.length > 0;
    }
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
      });
      setServerProbe(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setServerProbing(false);
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
            mode: effectiveServerMode,
          });
        } else {
          await onCreate({
            name: trimmed,
            provider,
            files: selection.validFiles,
          });
        }
      } else if (linkIsObsidian) {
        await onConnectObsidian({ name: trimmed, vaultPath: trimmedPath });
      } else {
        await onConnectLinkedFolder({
          name: trimmed,
          folderPath: trimmedPath,
          provider: linkSource,
        });
      }
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const submitLabel =
    mode === "new"
      ? isLightRagServer
        ? t("Connect")
        : t("Create")
      : linkIsObsidian
        ? t("Connect")
        : t("Link");

  return (
    <Modal
      isOpen={isOpen}
      onClose={submitting ? () => {} : onClose}
      title={t("Create knowledge base")}
      titleIcon={<Plus size={16} />}
      width="lg"
      closeOnBackdrop={!submitting}
      closeOnEscape={!submitting}
      footer={
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
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
            ) : mode === "new" && !isLightRagServer ? (
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
          onChange={setMode}
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
            providers={providers}
            provider={provider}
            setProvider={setProvider}
            submitting={submitting}
            providerUnavailable={providerUnavailable}
            providerNeedsKey={providerNeedsKey}
            onConfigureProvider={onConfigureProvider}
            isPageIndex={isPageIndex}
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
                  serverMode={effectiveServerMode}
                  setServerMode={setServerMode}
                  modeOptions={serverModeOptions}
                  submitting={submitting}
                  probing={serverProbing}
                  probe={serverProbe}
                  onTest={handleTestServer}
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
            setLinkSource={setLinkSource}
            linkIsObsidian={linkIsObsidian}
            folderPath={folderPath}
            setFolderPath={setFolderPath}
            submitting={submitting}
            probing={probing}
            probe={probe}
            onProbe={handleProbe}
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
  submitting,
  providerUnavailable,
  providerNeedsKey,
  onConfigureProvider,
  isPageIndex,
  files,
  setFiles,
  policyForProvider,
  connectionForm,
  t,
}: {
  providers: RagProviderSummary[];
  provider: string;
  setProvider: (id: string) => void;
  submitting: boolean;
  providerUnavailable: boolean;
  providerNeedsKey: boolean;
  onConfigureProvider?: () => void;
  isPageIndex: boolean;
  files: File[];
  setFiles: (files: File[]) => void;
  policyForProvider: KnowledgeUploadPolicy;
  /** When set, replaces the upload step (e.g. a server connection form). */
  connectionForm?: ReactNode;
  t: TFn;
}) {
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
              <button
                key={p.id}
                type="button"
                disabled={submitting}
                onClick={() => setProvider(p.id)}
                className={`group flex flex-col gap-1 rounded-2xl border p-3 text-left transition-colors disabled:opacity-50 ${
                  selected
                    ? "border-[var(--primary)] bg-[var(--primary)]/5"
                    : "border-[var(--border)] hover:border-[var(--ring)]"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[13px] font-medium text-[var(--foreground)]">
                    {p.name}
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
                    "This engine isn't installed on the server. Install it before creating.",
                  )}
            </span>
            {providerNeedsKey && onConfigureProvider && (
              <button
                type="button"
                onClick={onConfigureProvider}
                className="shrink-0 rounded-md px-2 py-1 text-[11.5px] font-medium text-amber-900 underline-offset-2 hover:underline dark:text-amber-100"
              >
                {t("Configure")}
              </button>
            )}
          </div>
        )}
      </div>

      {connectionForm ?? (
        <div>
          <label className="mb-2 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("Initial documents")}
            {isPageIndex && (
              <span className="ml-2 normal-case tracking-normal text-[var(--muted-foreground)]/80">
                · {t("PDF and Markdown only")}
              </span>
            )}
          </label>
          <FileDropZone
            files={files}
            onChange={setFiles}
            uploadPolicy={policyForProvider}
            disabled={submitting}
          />
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
  serverMode,
  setServerMode,
  modeOptions,
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
  serverMode: string;
  setServerMode: (value: string) => void;
  modeOptions: string[];
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

      {modeOptions.length > 0 && (
        <div>
          <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("Retrieval mode")}
          </label>
          <select
            value={serverMode}
            onChange={(event) => setServerMode(event.target.value)}
            disabled={submitting}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[12.5px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25 disabled:opacity-50"
          >
            {modeOptions.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
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

function LinkModeFields({
  providers,
  linkSource,
  setLinkSource,
  linkIsObsidian,
  folderPath,
  setFolderPath,
  submitting,
  probing,
  probe,
  onProbe,
  t,
}: {
  providers: RagProviderSummary[];
  linkSource: string;
  setLinkSource: (id: string) => void;
  linkIsObsidian: boolean;
  folderPath: string;
  setFolderPath: (value: string) => void;
  submitting: boolean;
  probing: boolean;
  probe: LinkedFolderProbe | null;
  onProbe: () => void;
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
            const selected = !linkIsObsidian && linkSource === p.id;
            const disabled = submitting || !p.linkable;
            return (
              <button
                key={p.id}
                type="button"
                disabled={disabled}
                onClick={() => setLinkSource(p.id)}
                title={
                  !p.linkable
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
                  <span className="text-[13px] font-medium text-[var(--foreground)]">
                    {p.name}
                  </span>
                  {!p.linkable ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
                      {t("Cloud index")}
                    </span>
                  ) : selected ? (
                    <Check className="h-3.5 w-3.5 text-[var(--primary)]" />
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
              <span className="flex items-center gap-1.5 text-[13px] font-medium text-[var(--foreground)]">
                <FolderOpen className="h-3.5 w-3.5" />
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
        </div>
      </div>

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
              disabled={submitting || probing || folderPath.trim().length === 0}
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
