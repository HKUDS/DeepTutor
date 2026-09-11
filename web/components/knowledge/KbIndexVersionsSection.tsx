"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Layers,
  Loader2,
  RefreshCw,
  Star,
} from "lucide-react";
import {
  currentLightRagBuildCandidate,
  formatKnowledgeTimestamp,
  kbCanReindex,
  kbHasLiveProgress,
  kbNeedsReindex,
  lightRagVersionDisplayState,
  providerUsesEmbeddingMetadata,
  resolveKbStatus,
  resolveProgressPercent,
  type IndexVersion,
  type KnowledgeBase,
} from "@/lib/knowledge-helpers";
import type { TaskState } from "@/hooks/useKnowledgeProgress";
import ProcessLogs from "@/components/common/ProcessLogs";
import Modal from "@/components/common/Modal";
import { useLLMOptions } from "@/hooks/useLLMOptions";
import { getLightRagConfig } from "@/features/knowledge/api/engines";
import type { LLMOption } from "@/lib/llm-options";
import type {
  IndexingLLMSelection,
  LightRagConfig,
} from "@/features/knowledge/model/types";
import KbIndexFailureBanner from "./KbIndexFailureBanner";
import IndexingModelSelector, {
  selectionFromLightRagDefault,
  selectionFromLLMOption,
} from "./IndexingModelSelector";
import LightRagIndexingProvenance from "./LightRagIndexingProvenance";

export function selectionForLightRagModelDialog(
  options: LLMOption[],
  config: Pick<LightRagConfig, "llm_profile_id" | "llm_model_id">,
  activeDefault: {
    profile_id?: string | null;
    model_id?: string | null;
  } | null,
  savedPending: IndexingLLMSelection | undefined,
  preserveSavedPending: boolean,
): IndexingLLMSelection | null {
  const savedOption = preserveSavedPending
    ? options.find(
        (option) =>
          option.profile_id === savedPending?.profile_id &&
          option.model_id === savedPending?.model_id,
      )
    : undefined;
  return savedOption
    ? selectionFromLLMOption(
        savedOption,
        savedPending?.reasoning_effort || "",
      )
    : selectionFromLightRagDefault(options, config, activeDefault);
}

interface KbIndexVersionsSectionProps {
  kb: KnowledgeBase;
  task?: TaskState;
  onReindex: (indexingLLM?: IndexingLLMSelection) => Promise<void>;
  onUpdatePendingIndexingPolicy: (
    indexingLLM: IndexingLLMSelection,
  ) => Promise<void>;
}

export default function KbIndexVersionsSection({
  kb,
  task,
  onReindex,
  onUpdatePendingIndexingPolicy,
}: KbIndexVersionsSectionProps) {
  const { t } = useTranslation();
  const [submitting, setSubmitting] = useState(false);
  const [modelDialogOpen, setModelDialogOpen] = useState(false);
  const [indexingLLM, setIndexingLLM] = useState<IndexingLLMSelection | null>(
    null,
  );
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [lightRagConfig, setLightRagConfig] = useState<LightRagConfig | null>(
    null,
  );
  const [lightRagConfigLoaded, setLightRagConfigLoaded] = useState(false);
  const [lightRagConfigError, setLightRagConfigError] = useState(false);
  const llmCatalog = useLLMOptions();
  const provider = kb.statistics?.rag_provider || "llamaindex";
  const isLightRag = provider === "lightrag";
  const pageIndexProvider = !providerUsesEmbeddingMetadata(provider);
  const modelInsensitiveProvider = pageIndexProvider || isLightRag;
  const versions = kb.statistics?.index_versions ?? [];
  const activeSig = modelInsensitiveProvider
    ? null
    : (kb.statistics?.active_signature ?? null);
  const needsReindex = kbNeedsReindex(kb);
  const isError = resolveKbStatus(kb) === "error";
  const mismatch = Boolean(kb.metadata?.embedding_mismatch);
  const isReindexingHere =
    (task?.kind === "reindex" || task?.kind === "retry") && task.executing;
  const percent = resolveProgressPercent(kb.progress);
  const lastIndexed = formatKnowledgeTimestamp(kb.metadata?.last_indexed_at);
  const lastIndexedCount = kb.metadata?.last_indexed_count;

  const publishedLightRagVersion = isLightRag
    ? versions.find(
        (version) => version.provider === "lightrag" && version.ready,
      )
    : undefined;
  const buildingLightRagVersion = isLightRag
    ? currentLightRagBuildCandidate(versions, Boolean(isReindexingHere))
    : undefined;
  const emptyPendingEligible =
    isLightRag &&
    !kb.read_only &&
    kb.statistics?.raw_documents === 0 &&
    !publishedLightRagVersion &&
    !kbHasLiveProgress(kb) &&
    !task?.executing;

  useEffect(() => {
    if (!isLightRag) return;
    let cancelled = false;
    void getLightRagConfig()
      .then((config) => {
        if (!cancelled) {
          setLightRagConfig(config);
          setLightRagConfigError(false);
        }
      })
      .catch(() => {
        if (!cancelled) setLightRagConfigError(true);
      })
      .finally(() => {
        if (!cancelled) setLightRagConfigLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [isLightRag, t]);

  useEffect(() => {
    if (!modelDialogOpen || indexingLLM || llmCatalog.options.length === 0)
      return;
    if (!lightRagConfigLoaded || !lightRagConfig) return;
    setIndexingLLM(
      selectionForLightRagModelDialog(
        llmCatalog.options,
        lightRagConfig,
        llmCatalog.activeDefault,
        kb.metadata?.indexing_policy?.selection,
        emptyPendingEligible,
      ),
    );
  }, [
    emptyPendingEligible,
    indexingLLM,
    kb.metadata?.indexing_policy?.selection,
    llmCatalog.activeDefault,
    llmCatalog.options,
    lightRagConfig,
    lightRagConfigLoaded,
    modelDialogOpen,
  ]);

  const openModelDialog = () => {
    setIndexingLLM(null);
    setDialogError(null);
    setModelDialogOpen(true);
  };

  const handleReindex = async () => {
    if (isLightRag) {
      openModelDialog();
      return;
    }
    setSubmitting(true);
    try {
      await onReindex();
    } finally {
      setSubmitting(false);
    }
  };

  const handleModelSubmit = async () => {
    if (!indexingLLM) return;
    setSubmitting(true);
    setDialogError(null);
    try {
      if (emptyPendingEligible) {
        await onUpdatePendingIndexingPolicy(indexingLLM);
      } else {
        await onReindex(indexingLLM);
      }
      setModelDialogOpen(false);
    } catch (error) {
      setDialogError(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  };

  const showReindexCta = kbCanReindex(kb);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Layers className="h-3.5 w-3.5 text-[var(--muted-foreground)]" />
          <div>
            <div className="text-[12.5px] font-medium text-[var(--foreground)]">
              {t("Index versions")}
              <span className="ml-2 rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-normal text-[var(--muted-foreground)]">
                {versions.length}
              </span>
            </div>
            <p className="text-[11px] text-[var(--muted-foreground)]">
              {t(
                pageIndexProvider
                  ? "PageIndex versions are model-insensitive and preserve rebuild history."
                  : isLightRag
                    ? "Each full rebuild publishes a separate LightRAG index version."
                    : "Each embedding configuration gets its own stored vector index.",
              )}
            </p>
          </div>
        </div>

        {(showReindexCta || emptyPendingEligible) && (
          <button
            type="button"
            onClick={handleReindex}
            disabled={submitting || isReindexingHere}
            title={
              isError
                ? t(
                    "Retry indexing from the documents already stored in this knowledge base.",
                  )
                : t(
                    isLightRag
                      ? "Choose a model and publish a new LightRAG index version. The current published version remains available until the rebuild succeeds."
                      : pageIndexProvider
                        ? "Rebuild this PageIndex knowledge base. Existing index versions are preserved."
                        : "Click Re-index to rebuild this knowledge base with the active embedding model. Existing index versions are preserved.",
                  )
            }
            className={`inline-flex shrink-0 items-center gap-1.5 rounded-md border px-2.5 py-1 text-[12px] font-medium transition-colors disabled:opacity-50 ${
              isError
                ? "border-red-200 bg-red-50 text-red-700 hover:bg-red-100 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300"
                : "border-amber-300 bg-amber-50 text-amber-700 hover:bg-amber-100 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300"
            }`}
          >
            {submitting || isReindexingHere ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <RefreshCw className="h-3 w-3" />
            )}
            {emptyPendingEligible
              ? t("Change model")
              : isReindexingHere
                ? isError
                  ? t("Retrying…")
                  : t("Re-indexing…")
                : isError
                  ? t("Retry indexing")
                  : t("Re-index")}
          </button>
        )}
      </div>

      {isError && <KbIndexFailureBanner kb={kb} />}

      {isLightRag && (
        <LightRagIndexingProvenance
          policy={kb.metadata?.indexing_policy}
          version={publishedLightRagVersion}
        />
      )}

      {!modelInsensitiveProvider && !isError && (needsReindex || mismatch) && (
        <div className="rounded-lg border border-amber-200 bg-amber-50/80 px-3 py-2 text-[12px] text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-300">
          {t(
            "The active embedding configuration doesn't match any ready index version. Re-index to rebuild against the current embedding model.",
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-[var(--border)] bg-[var(--muted)]/30 px-3 py-2 text-[11.5px] text-[var(--muted-foreground)]">
        <Clock className="h-3.5 w-3.5 shrink-0" />
        <span>
          {t("Last indexed")}:{" "}
          <span className="font-medium text-[var(--foreground)]">
            {lastIndexed || t("Not recorded yet")}
          </span>
        </span>
        {typeof lastIndexedCount === "number" && (
          <span>
            ·{" "}
            {t(
              lastIndexedCount === 1
                ? "{{count}} indexed doc"
                : "{{count}} indexed docs",
              {
                count: lastIndexedCount,
              },
            )}
          </span>
        )}
      </div>

      {versions.length > 0 ? (
        <ul className="divide-y divide-[var(--border)] rounded-lg border border-[var(--border)] bg-[var(--background)]">
          {versions.map((version) => (
            <IndexVersionRow
              key={
                version.signature ??
                `${version.model}-${version.dimension}-${version.created_at}`
              }
              version={version}
              activeSignature={activeSig}
              isPublishedLightRag={version === publishedLightRagVersion}
              isLightRagVersion={isLightRag}
              isLegacyLightRag={
                isLightRag &&
                kb.metadata?.indexing_policy?.policy === "legacy_unpinned" &&
                version.ready === true
              }
              isRebuildActive={version === buildingLightRagVersion}
              kbError={isError}
            />
          ))}
        </ul>
      ) : (
        <div className="rounded-lg border border-dashed border-[var(--border)] px-4 py-6 text-center text-[12px] text-[var(--muted-foreground)]">
          {t("No index versions yet.")}
        </div>
      )}

      {(task?.kind === "reindex" || task?.kind === "retry") &&
        (task.taskId || task.logs.length > 0 || task.executing) && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-[11px] text-[var(--muted-foreground)]">
              <span>
                {task.label}
                {task.taskId ? ` · ${task.taskId}` : ""}
              </span>
              {task.executing && percent > 0 && (
                <span className="font-medium text-[var(--foreground)]">
                  {percent}%
                </span>
              )}
            </div>
            <ProcessLogs
              logs={task.logs}
              executing={task.executing}
              title={t("Re-index Process")}
            />
            {task.executing && (
              <div className="h-1.5 overflow-hidden rounded-full bg-[var(--border)]/70">
                <div
                  className="h-full rounded-full bg-[var(--primary)] transition-all duration-300"
                  style={{ width: `${Math.max(percent, 4)}%` }}
                />
              </div>
            )}
            {task.error && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed">
                  {task.error}
                </pre>
              </div>
            )}
          </div>
        )}

      <Modal
        isOpen={modelDialogOpen}
        onClose={() => !submitting && setModelDialogOpen(false)}
        title={
          emptyPendingEligible
            ? t("Change pending indexing model")
            : t("Re-index with a pinned model")
        }
        width="sm"
        footer={
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setModelDialogOpen(false)}
              disabled={submitting}
              className="rounded-md border border-[var(--border)] px-3 py-1.5 text-[12px] text-[var(--foreground)] disabled:opacity-50"
            >
              {t("Cancel")}
            </button>
            <button
              type="button"
              onClick={() => void handleModelSubmit()}
              disabled={submitting || !indexingLLM}
              className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] disabled:opacity-50"
            >
              {submitting && <Loader2 className="h-3 w-3 animate-spin" />}
              {emptyPendingEligible
                ? t("Save model")
                : t("Start full re-index")}
            </button>
          </div>
        }
      >
        <div className="space-y-3 p-4">
          <p className="text-[12px] text-[var(--muted-foreground)]">
            {emptyPendingEligible
              ? t(
                  "This selection will take effect when the empty knowledge base is indexed for the first time.",
                )
              : t(
                  "A full re-index publishes a new version and then makes this model the pinned identity for future incremental uploads.",
                )}
          </p>
          <IndexingModelSelector
            options={llmCatalog.options}
            selection={indexingLLM}
            loading={llmCatalog.loading}
            error={llmCatalog.error}
            defaultUnavailable={
              lightRagConfigLoaded &&
              !!(
                lightRagConfig?.llm_profile_id || lightRagConfig?.llm_model_id
              ) &&
              !indexingLLM
            }
            defaultLoadError={lightRagConfigError}
            disabled={submitting}
            onChange={setIndexingLLM}
          />
          {dialogError && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
              {dialogError}
            </div>
          )}
        </div>
      </Modal>
    </div>
  );
}

function IndexVersionRow({
  version,
  activeSignature,
  isPublishedLightRag,
  isLightRagVersion,
  isLegacyLightRag,
  isRebuildActive,
  kbError,
}: {
  version: IndexVersion;
  activeSignature: string | null;
  isPublishedLightRag: boolean;
  isLightRagVersion: boolean;
  isLegacyLightRag: boolean;
  isRebuildActive: boolean;
  kbError: boolean;
}) {
  const { t } = useTranslation();
  const matchesActive =
    !!version.signature && version.signature === activeSignature;
  const lightRagState = isLightRagVersion
    ? lightRagVersionDisplayState(version, {
        published: isPublishedLightRag,
        rebuildActive: isRebuildActive,
        kbError,
        legacy: isLegacyLightRag,
      })
    : null;
  const isActive =
    lightRagState === "published" ||
    (!isLightRagVersion && matchesActive && version.ready === true);
  const isPhantom = matchesActive && version.ready !== true;
  const isLegacy = lightRagState === "legacy" || !!version.legacy;
  const isFailedLightRagCandidate = lightRagState === "failed";
  const isBuildingLightRagCandidate = lightRagState === "building";

  const title = isFailedLightRagCandidate
    ? t("Failed rebuild candidate")
    : isBuildingLightRagCandidate
      ? t("Rebuild candidate in progress")
    : isLegacy
      ? t("Legacy index")
      : version.model
        ? version.model
        : (version.signature ?? t("Unknown"));

  const created = formatKnowledgeTimestamp(version.created_at);

  return (
    <li className="flex items-center gap-3 px-3 py-2.5">
      <div
        className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md ${
          isActive
            ? "bg-emerald-100 text-emerald-600 dark:bg-emerald-950/30 dark:text-emerald-300"
            : isPhantom
              ? "bg-amber-100 text-amber-600 dark:bg-amber-950/30 dark:text-amber-300"
              : "bg-[var(--muted)] text-[var(--muted-foreground)]"
        }`}
        title={
          isActive
            ? t("Active version")
            : isPhantom
              ? t("Stale (matches active config but storage is empty)")
              : isLegacy
                ? t("Legacy index format")
                : t("Inactive version")
        }
      >
        {isActive ? (
          <Star className="h-3.5 w-3.5" fill="currentColor" />
        ) : isBuildingLightRagCandidate ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : isPhantom ? (
          <AlertTriangle className="h-3.5 w-3.5" />
        ) : isLegacy ? (
          <Clock className="h-3.5 w-3.5" />
        ) : (
          <CheckCircle2 className="h-3.5 w-3.5" />
        )}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span
            className={`truncate text-[12.5px] font-medium ${
              isPhantom
                ? "text-amber-700 line-through decoration-amber-400/70 dark:text-amber-300"
                : "text-[var(--foreground)]"
            }`}
          >
            {title}
          </span>
          {isActive && (
            <span className="rounded-full bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300">
              {t("Active")}
            </span>
          )}
          {isPhantom && (
            <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:bg-amber-950/30 dark:text-amber-300">
              {t("Stale")}
            </span>
          )}
          {isLegacy && !isActive && (
            <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]">
              {t("Legacy")}
            </span>
          )}
          {isFailedLightRagCandidate && (
            <span className="rounded-full bg-red-100 px-1.5 py-0.5 text-[10px] font-medium text-red-700 dark:bg-red-950/30 dark:text-red-300">
              {t("Not published")}
            </span>
          )}
          {isBuildingLightRagCandidate && (
            <span className="rounded-full bg-blue-100 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 dark:bg-blue-950/30 dark:text-blue-300">
              {t("Building")}
            </span>
          )}
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10.5px] text-[var(--muted-foreground)]">
          {typeof version.dimension === "number" && (
            <span>
              {version.dimension}
              {t("d")}
            </span>
          )}
          {version.binding && <span>{version.binding}</span>}
          {created && <span>{created}</span>}
          {version.signature && (
            <span className="font-mono">{version.signature.slice(0, 10)}</span>
          )}
          {version.failure_summary && (
            <span className="text-red-600 dark:text-red-300">
              {version.failure_summary}
            </span>
          )}
        </div>
      </div>
    </li>
  );
}
