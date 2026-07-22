"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { useKnowledgeBases } from "@/hooks/useKnowledgeBases";
import { updateRagProviderMode } from "@/lib/knowledge-api";
import KnowledgeBaseDetail from "./KnowledgeBaseDetail";
import KnowledgeHome from "./KnowledgeHome";
import EngineDetail from "./EngineDetail";
import CreateKbModal from "./CreateKbModal";
import PageIndexSettingsModal from "./PageIndexSettingsModal";

export default function KnowledgePage() {
  const { t } = useTranslation();
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialKb = searchParams.get("kb");
  const initialEngine = searchParams.get("engine");

  const {
    kbs: allKbs,
    providers,
    uploadPolicy,
    loading,
    error,
    setError,
    tasksByKb,
    historyByKb,
    clearHistory,
    refresh,
    createKb,
    uploadFiles,
    setDefault,
    reindex,
    retry,
    deleteKb,
    connectObsidian,
    connectLinkedFolder,
    connectLightRagServer,
  } = useKnowledgeBases();

  // Connected subagents are stored as ``type: subagent`` KBs so the chat
  // composer can select them, but they are agents, not knowledge bases — keep
  // them out of the Knowledge Center entirely.
  const kbs = useMemo(
    () => allKbs.filter((kb) => kb.metadata?.type !== "subagent"),
    [allKbs],
  );

  const [explicitSelection, setExplicitSelection] = useState<string | null>(
    initialKb,
  );
  const [selectedEngineId, setSelectedEngineId] = useState<string | null>(
    initialEngine,
  );
  const [createOpen, setCreateOpen] = useState(false);
  const [createPreset, setCreatePreset] = useState<{
    mode: "new" | "link";
    source?: string;
  } | null>(null);
  const [pipelineOpen, setPipelineOpen] = useState(false);

  const openCreate = useCallback(() => {
    setCreatePreset(null);
    setCreateOpen(true);
  }, []);
  // Obsidian lives in the engines grid for discoverability but routes through
  // the unified create flow, pre-set to "link existing → Obsidian".
  const openObsidian = useCallback(() => {
    setCreatePreset({ mode: "link", source: "obsidian" });
    setCreateOpen(true);
  }, []);
  // Lands on the Overview console unless deep-linked to a KB or an engine.
  const [view, setView] = useState<"home" | "kb" | "engine">(
    initialEngine ? "engine" : initialKb ? "kb" : "home",
  );

  const openKb = useCallback((name: string) => {
    setExplicitSelection(name);
    setView("kb");
  }, []);

  const openEngine = useCallback((id: string) => {
    setSelectedEngineId(id);
    setView("engine");
  }, []);

  // Derive the effective selection: respect the user's pick if it still
  // exists, otherwise fall back to the default KB (or the first one). No
  // useEffect chains — keeps state out of effects.
  const selectedKbName = useMemo<string | null>(() => {
    if (explicitSelection && kbs.some((kb) => kb.name === explicitSelection)) {
      return explicitSelection;
    }
    if (!kbs.length) return null;
    return kbs.find((kb) => kb.is_default)?.name ?? kbs[0].name;
  }, [explicitSelection, kbs]);

  const selectedKb = useMemo(
    () => kbs.find((kb) => kb.name === selectedKbName) ?? null,
    [kbs, selectedKbName],
  );

  // The effective engine selection: respect the pick if it still exists.
  const selectedProvider = useMemo(
    () => providers.find((p) => p.id === selectedEngineId) ?? null,
    [providers, selectedEngineId],
  );

  // Keep ?kb / ?engine in sync with the effective selection so deep links work.
  // The Overview view carries neither, so reloading the console stays on it.
  const urlKb = view === "kb" ? (selectedKbName ?? null) : null;
  const urlEngine = view === "engine" ? (selectedProvider?.id ?? null) : null;
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (
      searchParams.get("kb") === urlKb &&
      searchParams.get("engine") === urlEngine
    ) {
      return;
    }
    const params = new URLSearchParams(Array.from(searchParams.entries()));
    if (urlKb) params.set("kb", urlKb);
    else params.delete("kb");
    if (urlEngine) params.set("engine", urlEngine);
    else params.delete("engine");
    const search = params.toString();
    router.replace(search ? `?${search}` : "?", { scroll: false });
  }, [router, searchParams, urlKb, urlEngine]);

  const handleCreate = useCallback(
    async (params: { name: string; provider: string; files: File[] }) => {
      try {
        await createKb(params);
        openKb(params.name);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        throw err;
      }
    },
    [createKb, openKb, setError],
  );

  const handleSetDefault = useCallback(
    async (name: string) => {
      try {
        await setDefault(name);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [setDefault, setError],
  );

  const handleDelete = useCallback(
    async (name: string) => {
      if (!window.confirm(t('Delete knowledge base "{{name}}"?', { name }))) {
        return;
      }
      try {
        await deleteKb(name);
        if (explicitSelection === name) {
          setExplicitSelection(null);
          setView("home");
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [deleteKb, explicitSelection, setError, t],
  );

  const handleUpload = useCallback(
    async (kbName: string, files: File[]) => {
      try {
        await uploadFiles(kbName, files);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        throw err;
      }
    },
    [setError, uploadFiles],
  );

  const handleReindex = useCallback(
    async (kbName: string) => {
      try {
        await reindex(kbName);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [reindex, setError],
  );

  const handleRetry = useCallback(
    async (kbName: string) => {
      try {
        await retry(kbName);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [retry, setError],
  );

  const handleSelectMode = useCallback(
    async (id: string, mode: string) => {
      try {
        await updateRagProviderMode(id, mode);
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [refresh, setError],
  );

  return (
    <div className="flex h-full flex-col bg-[var(--background)]">
      {error && (
        <div className="flex items-center justify-between gap-3 border-b border-red-200 bg-red-50 px-4 py-2 text-[12.5px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          <span className="truncate">{error}</span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void refresh({ force: true })}
              className="rounded-md border border-red-300 px-2 py-0.5 text-[11.5px] font-medium hover:bg-red-100 dark:border-red-900 dark:hover:bg-red-950/50"
            >
              {t("Retry")}
            </button>
            <button
              type="button"
              onClick={() => setError(null)}
              className="rounded-md px-2 py-0.5 text-[11.5px] font-medium hover:bg-red-100 dark:hover:bg-red-950/50"
            >
              {t("Dismiss")}
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
        </div>
      ) : (
        <div className="flex min-h-0 flex-1">
          {view === "home" ? (
            <KnowledgeHome
              kbs={kbs}
              providers={providers}
              onOpenKb={openKb}
              onOpenEngine={openEngine}
              onCreate={openCreate}
              onConnectObsidian={openObsidian}
            />
          ) : view === "engine" && selectedProvider ? (
            <EngineDetail
              provider={selectedProvider}
              kbs={kbs}
              onBack={() => setView("home")}
              onOpenKb={openKb}
              onSelectMode={handleSelectMode}
              onChanged={() => void refresh({ force: true })}
              onError={(message) => setError(message)}
            />
          ) : view === "engine" ? (
            // Selected engine vanished (e.g. provider list changed); bounce home.
            <KnowledgeHome
              kbs={kbs}
              providers={providers}
              onOpenKb={openKb}
              onOpenEngine={openEngine}
              onCreate={openCreate}
              onConnectObsidian={openObsidian}
            />
          ) : (
            <KnowledgeBaseDetail
              kb={selectedKb}
              uploadPolicy={uploadPolicy}
              task={selectedKb ? tasksByKb[selectedKb.name] : undefined}
              history={selectedKb ? (historyByKb[selectedKb.name] ?? []) : []}
              onCreate={openCreate}
              onUpload={handleUpload}
              onReindex={handleReindex}
              onRetry={handleRetry}
              onSetDefault={handleSetDefault}
              onDelete={handleDelete}
              onClearHistory={clearHistory}
              onBack={() => setView("home")}
            />
          )}
        </div>
      )}

      <CreateKbModal
        isOpen={createOpen}
        onClose={() => setCreateOpen(false)}
        providers={providers}
        uploadPolicy={uploadPolicy}
        onCreate={handleCreate}
        onConnectLinkedFolder={connectLinkedFolder}
        onConnectObsidian={connectObsidian}
        onConnectLightRagServer={connectLightRagServer}
        initialMode={createPreset?.mode}
        initialSource={createPreset?.source}
        onConfigureProvider={() => {
          setCreateOpen(false);
          setPipelineOpen(true);
        }}
      />

      <PageIndexSettingsModal
        isOpen={pipelineOpen}
        onClose={() => setPipelineOpen(false)}
        onSaved={() => void refresh({ force: true })}
      />
    </div>
  );
}
