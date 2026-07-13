"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  connectLightRagServer as connectLightRagServerApi,
  connectLinkedFolder as connectLinkedFolderApi,
  connectObsidianVault as connectObsidianApi,
  createKnowledgeBase as createKbApi,
  deleteKnowledgeBase as deleteKbApi,
  getKnowledgeUploadPolicy,
  invalidateKnowledgeCaches,
  listKnowledgeBases,
  listRagProviders,
  reindexKnowledgeBase as reindexKbApi,
  retryKnowledgeBase as retryKbApi,
  setDefaultKnowledgeBase as setDefaultKbApi,
  uploadKnowledgeBaseFiles as uploadKbApi,
  type KnowledgeTaskResponse,
  type KnowledgeUploadPolicy,
  type RagProviderSummary,
} from "@/lib/knowledge-api";
import {
  DEFAULT_UPLOAD_POLICY,
  type KnowledgeBase,
  type ProgressInfo,
  kbHasLiveProgress,
} from "@/lib/knowledge-helpers";
import { useKnowledgeProgress } from "@/hooks/useKnowledgeProgress";
import { useKnowledgeHistory } from "@/hooks/useKnowledgeHistory";

const DEFAULT_PROVIDER_FALLBACK: RagProviderSummary[] = [
  {
    id: "llamaindex",
    name: "LlamaIndex",
    description: "Pure vector retrieval, fastest processing speed.",
  },
];

interface LoadOptions {
  force?: boolean;
  showSpinner?: boolean;
}

export function useKnowledgeBases() {
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [providers, setProviders] = useState<RagProviderSummary[]>([]);
  const [uploadPolicy, setUploadPolicy] = useState<KnowledgeUploadPolicy>(
    DEFAULT_UPLOAD_POLICY,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshRef = useRef<(opts?: LoadOptions) => Promise<void>>(
    async () => {},
  );
  const history = useKnowledgeHistory();

  const progress = useKnowledgeProgress({
    onComplete: (kbName) => {
      void refreshRef.current({ force: true, showSpinner: false });
      // Auto-refresh once completion arrives. The complete tick may fire while
      // the kb still has live progress on the server side, so a force refresh
      // syncs the actual state.
      void kbName;
    },
    onTaskSettled: (kbName, final) => {
      history.append(kbName, {
        taskId: final.taskId,
        kind: final.kind,
        label: final.label,
        status: final.error ? "error" : "completed",
        startedAt: final.startedAt,
        completedAt: final.completedAt,
        error: final.error,
        logTail: final.logs,
      });
    },
  });

  const load = useCallback(
    async (opts?: LoadOptions) => {
      const showSpinner = opts?.showSpinner ?? true;
      if (showSpinner) setLoading(true);
      setError(null);
      try {
        const [kbList, providerList, policy] = await Promise.all([
          listKnowledgeBases({ force: opts?.force }),
          listRagProviders({ force: opts?.force }),
          getKnowledgeUploadPolicy({ force: opts?.force }).catch(
            () => DEFAULT_UPLOAD_POLICY,
          ),
        ]);
        const typedKbs = kbList as KnowledgeBase[];
        setKbs(typedKbs);
        setUploadPolicy(policy);
        setProviders(
          providerList.length ? providerList : DEFAULT_PROVIDER_FALLBACK,
        );

        // Auto-resubscribe to progress for KBs that are still live
        // (e.g. user navigated away and came back mid-indexing).
        for (const kb of typedKbs) {
          const status = kb.status ?? kb.statistics?.status;
          const kbProgress = kb.progress ?? kb.statistics?.progress;
          if (status === "error" && kbProgress) {
            progress.setProgress(kb.name, kbProgress as ProgressInfo);
            continue;
          }
          if (
            kbHasLiveProgress({ ...kb, progress: kbProgress as ProgressInfo })
          ) {
            progress.setProgress(kb.name, (kbProgress as ProgressInfo) ?? {});
            const taskId = (kbProgress as ProgressInfo | undefined)?.task_id;
            progress.subscribeWs(kb.name, taskId || undefined);
          }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (showSpinner) setLoading(false);
      }
    },
    [progress],
  );

  useEffect(() => {
    refreshRef.current = load;
  }, [load]);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Combined view: merge live progress into each KB so consumers see a
  // single source of truth (status + progress).
  const combinedKbs = useMemo<KnowledgeBase[]>(
    () =>
      kbs.map((kb) => ({
        ...kb,
        status: kb.status ?? kb.statistics?.status,
        progress:
          progress.progressByKb[kb.name] ||
          kb.progress ||
          kb.statistics?.progress,
      })),
    [kbs, progress.progressByKb],
  );

  const hasActiveWork = useMemo(
    () =>
      combinedKbs.some((kb) => kbHasLiveProgress(kb)) ||
      Object.values(progress.tasksByKb).some((task) => task.executing),
    [combinedKbs, progress.tasksByKb],
  );

  // While work is happening, poll list every 4s to pick up server-side state
  // that the WS / SSE channels may not surface (e.g. rag_initialized flip).
  useEffect(() => {
    if (!hasActiveWork) return;
    const interval = window.setInterval(() => {
      void load({ force: true, showSpinner: false });
    }, 4000);
    return () => window.clearInterval(interval);
  }, [hasActiveWork, load]);

  // ── Mutations ──
  const createKb = useCallback(
    async (params: {
      name: string;
      provider: string;
      files: File[];
    }): Promise<KnowledgeTaskResponse> => {
      const result = await createKbApi(params);
      invalidateKnowledgeCaches();
      const fileCount = params.files.length;
      if (result.task_id) {
        progress.startTask({
          kbName: params.name,
          taskId: result.task_id,
          kind: "create",
          label: `Create ${params.name}`,
          initialLogs: [
            `Queued create task for ${params.name}.`,
            "Waiting for backend indexing logs...",
          ],
          seed: {
            stage: "initializing",
            message: "Initializing knowledge base...",
            current: 0,
            total: fileCount,
            progress_percent: 0,
          },
        });
      } else {
        progress.subscribeWs(params.name);
      }
      await load({ force: true, showSpinner: false });
      return result;
    },
    [load, progress],
  );

  const uploadFiles = useCallback(
    async (
      kbName: string,
      files: File[],
      provider?: string,
    ): Promise<KnowledgeTaskResponse> => {
      const result = await uploadKbApi(kbName, files, { provider });
      invalidateKnowledgeCaches();
      const fileCount = files.length;
      if (result.task_id) {
        progress.startTask({
          kbName,
          taskId: result.task_id,
          kind: "upload",
          label: `Upload to ${kbName}`,
          initialLogs: [
            `Queued upload task for ${kbName}.`,
            "Waiting for backend indexing logs...",
          ],
          seed: {
            stage: "processing_documents",
            message: `Processing ${fileCount} files...`,
            current: 0,
            total: fileCount,
            progress_percent: 0,
          },
        });
      } else {
        progress.subscribeWs(kbName);
      }
      await load({ force: true, showSpinner: false });
      return result;
    },
    [load, progress],
  );

  const setDefault = useCallback(
    async (kbName: string) => {
      await setDefaultKbApi(kbName);
      await load({ force: true, showSpinner: false });
    },
    [load],
  );

  const reindex = useCallback(
    async (kbName: string): Promise<KnowledgeTaskResponse> => {
      const result = await reindexKbApi(kbName);
      if (result.noop) {
        await load({ force: true, showSpinner: false });
        return result;
      }
      if (result.task_id) {
        progress.startTask({
          kbName,
          taskId: result.task_id,
          kind: "reindex",
          label: `Re-index ${kbName}`,
          initialLogs: [
            `Queued re-index task for ${kbName}.`,
            "Waiting for backend indexing logs...",
          ],
        });
      }
      await load({ force: true, showSpinner: false });
      return result;
    },
    [load, progress],
  );

  const retry = useCallback(
    async (kbName: string): Promise<KnowledgeTaskResponse> => {
      const result = await retryKbApi(kbName);
      if (result.task_id) {
        progress.startTask({
          kbName,
          taskId: result.task_id,
          kind: "retry",
          label: `Retry ${kbName}`,
          initialLogs: [
            `Queued retry task for ${kbName}.`,
            "Waiting for backend indexing logs...",
          ],
        });
      } else {
        progress.subscribeWs(kbName);
      }
      await load({ force: true, showSpinner: false });
      return result;
    },
    [load, progress],
  );

  const deleteKb = useCallback(
    async (kbName: string) => {
      await deleteKbApi(kbName);
      progress.cleanupKb(kbName);
      history.removeKb(kbName);
      await load({ force: true, showSpinner: false });
    },
    [history, load, progress],
  );

  const connectObsidian = useCallback(
    async (params: { name: string; vaultPath: string }) => {
      await connectObsidianApi(params);
      invalidateKnowledgeCaches();
      await load({ force: true, showSpinner: false });
    },
    [load],
  );

  const connectLinkedFolder = useCallback(
    async (params: { name: string; folderPath: string; provider: string }) => {
      await connectLinkedFolderApi(params);
      invalidateKnowledgeCaches();
      await load({ force: true, showSpinner: false });
    },
    [load],
  );

  const connectLightRagServer = useCallback(
    async (params: {
      name: string;
      serverUrl: string;
      apiKey?: string;
      mode?: string;
    }) => {
      await connectLightRagServerApi(params);
      invalidateKnowledgeCaches();
      await load({ force: true, showSpinner: false });
    },
    [load],
  );

  return {
    kbs: combinedKbs,
    rawKbs: kbs,
    providers,
    uploadPolicy,
    loading,
    error,
    setError,
    progressByKb: progress.progressByKb,
    tasksByKb: progress.tasksByKb,
    dismissTask: progress.dismissTask,
    historyByKb: history.historyByKb,
    clearHistory: history.clearKb,
    refresh: load,
    createKb,
    uploadFiles,
    setDefault,
    reindex,
    retry,
    deleteKb,
    connectObsidian,
    connectLinkedFolder,
    connectLightRagServer,
  };
}

export type UseKnowledgeBasesReturn = ReturnType<typeof useKnowledgeBases>;
