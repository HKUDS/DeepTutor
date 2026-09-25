"use client";

/**
 * Partner detail: a chat-first page with Configure and Channels tabs.
 * Header carries identity + run state; everything else lives in the tabs.
 */

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  Archive,
  BookmarkPlus,
  Download,
  Link2,
  Loader2,
  MessageCircle,
  Play,
  Radio,
  Settings2,
  Square,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  archivePartnerSession,
  destroyPartner,
  getPartner,
  getPartnerSessions,
  getPartnerWebContinuity,
  setPartnerWebContinuity,
  startPartner,
  stopPartner,
  type PartnerInfo,
} from "@/lib/partners-api";
import {
  downloadChatMarkdown,
  type ExportableMessage,
} from "@/lib/chat-export";
import {
  freshPartnerSessionKey,
  initializePartnerSessionKey,
  persistPartnerSessionKey,
} from "@/lib/partner-session";
import PartnerAvatar from "@/components/partners/PartnerAvatar";
import PartnerChat from "@/components/partners/PartnerChat";
import PartnerChannels from "@/components/partners/PartnerChannels";
import PartnerConfigure from "@/components/partners/PartnerConfigure";
import PartnerArchives from "@/components/partners/PartnerArchives";
import PartnerLinkModal from "@/components/partners/PartnerLinkModal";
import SaveToNotebookModal, {
  type NotebookSaveMessage,
  type NotebookSavePayload,
} from "@/components/notebook/SaveToNotebookModal";
import { useAuthStatus } from "@/hooks/useAuthStatus";

type Tab = "chat" | "configure" | "channels" | "archive";

function PartnerDetail() {
  const params = useParams<{ partnerId: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const { t } = useTranslation();
  const partnerId = params.partnerId;
  const auth = useAuthStatus();

  const initialTab = (searchParams.get("tab") as Tab) || "chat";
  const [tab, setTab] = useState<Tab>(
    ["chat", "configure", "channels", "archive"].includes(initialTab)
      ? initialTab
      : "chat",
  );
  const [partner, setPartner] = useState<PartnerInfo | null>(null);
  const [showLinkModal, setShowLinkModal] = useState(false);
  // A partner shared with you is a companion, not a project: you talk to it and
  // read your own history, but its soul, channels and library stay its owner's.
  const canManage = partner?.can_manage !== false;
  // ``?tab=`` is user-supplied, so a management tab on a shared partner (or
  // before the partner has loaded) resolves to Chat rather than an empty pane.
  const activeTab: Tab =
    !canManage && (tab === "configure" || tab === "channels") ? "chat" : tab;
  const [loading, setLoading] = useState(true);
  const [lifecycleBusy, setLifecycleBusy] = useState(false);
  const [toast, setToast] = useState("");
  // Conversation transcripts lifted from the Chat / Archive tabs so the header
  // can export whichever surface is active.
  const [chatMessages, setChatMessages] = useState<ExportableMessage[]>([]);
  const [archiveMessages, setArchiveMessages] = useState<ExportableMessage[]>(
    [],
  );
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [archiveBusy, setArchiveBusy] = useState(false);
  // The active web session key lives here so the Archive tab's Resume can
  // point the (always-mounted) Chat tab at a different conversation.
  const [sessionKey, setSessionKey] = useState("");
  const [localSessionKey, setLocalSessionKey] = useState("");
  const [continuityEnabled, setContinuityEnabled] = useState(false);
  const [continuityReady, setContinuityReady] = useState(false);
  const [continuityBusy, setContinuityBusy] = useState(false);
  const [continuityError, setContinuityError] = useState(false);
  const [runtimeContinuityError, setRuntimeContinuityError] = useState(false);
  const [continuityRetry, setContinuityRetry] = useState(0);
  const [switchingSession, setSwitchingSession] = useState(false);
  const [chatBusy, setChatBusy] = useState(false);
  const selectionEpochRef = useRef(0);
  const refreshInFlightRef = useRef(false);
  const selectionMutationRef = useRef(false);
  const accountId = auth.userId ?? (!auth.enabled && auth.statusAvailable ? "local-admin" : null);

  useEffect(() => {
    if (auth.loading) return;
    if (!accountId) {
      setContinuityError(true);
      return;
    }
    let cancelled = false;
    setContinuityReady(false);
    setContinuityError(false);
    setRuntimeContinuityError(false);
    void (async () => {
      const localKey = await initializePartnerSessionKey(
        partnerId,
        accountId,
        {
          enabled: auth.enabled,
          isAdmin: auth.isAdmin,
          statusAvailable: auth.statusAvailable,
        },
        async () => (await getPartnerSessions(partnerId)).map((item) => item.session_key),
      );
      const state = await getPartnerWebContinuity(partnerId);
      if (cancelled) return;
      setLocalSessionKey(localKey);
      setContinuityEnabled(state.enabled);
      setSessionKey(state.enabled && state.session_key ? state.session_key : localKey);
      setContinuityReady(true);
    })().catch(() => {
      if (!cancelled) setContinuityError(true);
    });
    return () => {
      cancelled = true;
    };
  }, [partnerId, auth.loading, auth.enabled, auth.isAdmin, auth.statusAvailable, accountId, continuityRetry]);

  const refreshAuthoritative = useCallback(async (required = false) => {
    if (!required && (refreshInFlightRef.current || selectionMutationRef.current)) return;
    refreshInFlightRef.current = true;
    const epoch = selectionEpochRef.current;
    try {
      const state = await getPartnerWebContinuity(partnerId);
      if (epoch !== selectionEpochRef.current) return;
      setContinuityEnabled(state.enabled);
      setSessionKey(state.enabled && state.session_key ? state.session_key : localSessionKey);
      setRuntimeContinuityError(false);
    } catch (error) {
      if (required) {
        setRuntimeContinuityError(true);
        setToast(error instanceof Error ? error.message : t("Load failed"));
      }
    } finally {
      refreshInFlightRef.current = false;
    }
  }, [partnerId, localSessionKey, t]);

  // A second browser can change the selected conversation. Pick it up when
  // this page becomes active, without moving a turn that is still streaming.
  useEffect(() => {
    if (!continuityReady) return;
    const refresh = () => {
      if (document.visibilityState !== "visible" || chatBusy || continuityBusy || switchingSession) return;
      void refreshAuthoritative();
    };
    const timer = continuityEnabled ? window.setInterval(refresh, 15_000) : null;
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      if (timer !== null) window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [continuityReady, continuityEnabled, chatBusy, continuityBusy, switchingSession, refreshAuthoritative]);

  const reconcileSelection = useCallback(async () => {
    selectionEpochRef.current += 1;
    selectionMutationRef.current = true;
    setSwitchingSession(true);
    try {
      await refreshAuthoritative(true);
    } finally {
      selectionMutationRef.current = false;
      setSwitchingSession(false);
    }
  }, [refreshAuthoritative]);
  const handleSelectionStale = useCallback(() => reconcileSelection(), [reconcileSelection]);

  const changeSessionKey = useCallback(
    async (key: string, alreadySaved = false) => {
      selectionEpochRef.current += 1;
      setSessionKey(key);
      if (continuityEnabled) {
        if (alreadySaved) return;
        selectionMutationRef.current = true;
        setSwitchingSession(true);
        try {
          const state = await setPartnerWebContinuity(partnerId, {
            enabled: true,
            session_key: key,
          });
          if (state.session_key && state.session_key !== key) setSessionKey(state.session_key);
        } catch (error) {
          setToast(error instanceof Error ? error.message : t("Action failed"));
          await reconcileSelection();
        } finally {
          selectionMutationRef.current = false;
          setSwitchingSession(false);
        }
      } else {
        if (accountId) persistPartnerSessionKey(partnerId, key, accountId);
        setLocalSessionKey(key);
      }
    },
    [partnerId, continuityEnabled, accountId, reconcileSelection, t],
  );

  const toggleContinuity = useCallback(async () => {
    if (!continuityReady || continuityBusy || switchingSession || runtimeContinuityError || chatBusy || !sessionKey) return;
    selectionEpochRef.current += 1;
    selectionMutationRef.current = true;
    setContinuityBusy(true);
    try {
      if (continuityEnabled) {
        await setPartnerWebContinuity(partnerId, {
          enabled: false,
          session_key: null,
        });
        const localKey = freshPartnerSessionKey();
        if (accountId) persistPartnerSessionKey(partnerId, localKey, accountId);
        setLocalSessionKey(localKey);
        setSessionKey(localKey);
        setContinuityEnabled(false);
      } else {
        await setPartnerWebContinuity(partnerId, {
          enabled: true,
          session_key: sessionKey,
        });
        setContinuityEnabled(true);
      }
    } catch (error) {
      setToast(error instanceof Error ? error.message : t("Action failed"));
      await refreshAuthoritative(true);
    } finally {
      selectionMutationRef.current = false;
      setContinuityBusy(false);
    }
  }, [
    accountId,
    chatBusy,
    continuityBusy,
    continuityEnabled,
    continuityReady,
    runtimeContinuityError,
    switchingSession,
    partnerId,
    refreshAuthoritative,
    sessionKey,
    t,
  ]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(timer);
  }, [toast]);

  const exportMessages = useMemo<ExportableMessage[]>(() => {
    if (activeTab === "chat") return chatMessages;
    if (activeTab === "archive") return archiveMessages;
    return [];
  }, [activeTab, chatMessages, archiveMessages]);

  const canExport = exportMessages.length > 0;

  const exportTitle = useMemo(() => {
    const firstUser = exportMessages
      .find((msg) => msg.role === "user")
      ?.content.trim();
    return firstUser?.slice(0, 80) || partner?.name || "Conversation";
  }, [exportMessages, partner?.name]);

  const savePayload = useMemo<NotebookSavePayload | null>(() => {
    if (!partner || !canExport) return null;
    return {
      recordType: "tutorbot",
      title: exportTitle,
      // The transcript / userQuery are rebuilt inside the modal from the
      // user's selected subset; these are just fallbacks.
      userQuery: "",
      output: "",
      metadata: {
        source: "partner",
        partner_id: partnerId,
        partner_name: partner.name,
      },
    };
  }, [partner, canExport, exportTitle, partnerId]);

  const saveMessages = useMemo<NotebookSaveMessage[]>(
    () =>
      exportMessages
        .filter(
          (msg) =>
            msg.role === "user" ||
            msg.role === "assistant" ||
            msg.role === "system",
        )
        .map((msg) => ({
          role: msg.role as NotebookSaveMessage["role"],
          content: msg.content,
        })),
    [exportMessages],
  );

  const handleDownload = useCallback(() => {
    if (!exportMessages.length) return;
    downloadChatMarkdown(exportMessages, { title: exportTitle });
  }, [exportMessages, exportTitle]);

  const handleArchiveConversation = useCallback(async () => {
    if (!sessionKey || chatMessages.length === 0 || archiveBusy) return;
    setArchiveBusy(true);
    try {
      const result = await archivePartnerSession(partnerId, sessionKey);
      setChatMessages([]);
      if (continuityEnabled) {
        if (result.active_session_key) changeSessionKey(result.active_session_key, true);
        else await reconcileSelection();
      } else {
        changeSessionKey(freshPartnerSessionKey());
      }
      setToast(t("Archived conversation"));
    } catch (error) {
      setToast(error instanceof Error ? error.message : t("Action failed"));
    } finally {
      setArchiveBusy(false);
    }
  }, [
    archiveBusy,
    changeSessionKey,
    chatMessages.length,
    continuityEnabled,
    partnerId,
    reconcileSelection,
    sessionKey,
    t,
  ]);

  const load = useCallback(async () => {
    try {
      setPartner(await getPartner(partnerId));
    } catch {
      setPartner(null);
    } finally {
      setLoading(false);
    }
  }, [partnerId]);
  const handleRuntimeReady = useCallback(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggleRunning = async () => {
    if (!partner) return;
    setLifecycleBusy(true);
    try {
      if (partner.running) {
        await stopPartner(partnerId);
        setToast(t("Partner stopped"));
      } else {
        await startPartner(partnerId);
        setToast(t("Partner started"));
      }
      await load();
    } catch (e) {
      setToast(e instanceof Error ? e.message : t("Action failed"));
    } finally {
      setLifecycleBusy(false);
    }
  };

  const handleDestroy = async () => {
    if (
      !window.confirm(
        t(
          "Delete this partner and ALL its data (workspace, sessions, channels)? This cannot be undone.",
        ),
      )
    )
      return;
    try {
      await destroyPartner(partnerId);
      router.push("/partners");
    } catch (e) {
      setToast(e instanceof Error ? e.message : t("Delete failed"));
    }
  };

  if (loading || auth.loading || (!continuityReady && !continuityError)) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  if (!partner) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3">
        <p className="text-[14px] text-[var(--muted-foreground)]">
          {t("Partner not found")}
        </p>
        <Link
          href="/partners"
          className="text-[13px] text-[var(--primary)] hover:underline"
        >
          {t("Back to Partners")}
        </Link>
      </div>
    );
  }

  if (continuityError) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-[13px]">
        <p className="text-[var(--muted-foreground)]">{t("Could not load browser sync state")}</p>
        <button
          type="button"
          onClick={() => {
            if (!accountId) window.location.reload();
            else setContinuityRetry((value) => value + 1);
          }}
          className="rounded-md border border-[var(--border)] px-3 py-1.5 text-[var(--foreground)] hover:bg-[var(--muted)]"
        >
          {t("Retry")}
        </button>
      </div>
    );
  }

  const tabs: { key: Tab; label: string; icon: typeof MessageCircle }[] = [
    { key: "chat", label: t("Chat"), icon: MessageCircle },
    ...(canManage
      ? ([
          { key: "configure", label: t("Configure"), icon: Settings2 },
          { key: "channels", label: t("Channels"), icon: Radio },
        ] as const)
      : []),
    { key: "archive", label: t("Conversations"), icon: Archive },
  ];

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="grid min-h-[64px] grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3 border-b border-[var(--border)] px-5 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <Link
            href="/partners"
            aria-label={t("Back to Partners")}
            className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <PartnerAvatar
            name={partner.name}
            emoji={partner.emoji}
            color={partner.color}
            image={partner.avatar}
            size={32}
          />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="truncate text-[14px] font-medium text-[var(--foreground)]">
                {partner.name}
              </span>
              <span
                title={partner.running ? t("Running") : t("Stopped")}
                className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                  partner.running ? "bg-emerald-500" : "bg-[var(--border)]"
                }`}
              />
            </div>
            {partner.description ? (
              <p className="truncate text-[11.5px] text-[var(--muted-foreground)]">
                {partner.description}
              </p>
            ) : null}
          </div>
        </div>

        <nav className="flex justify-self-center gap-0.5 rounded-lg bg-[var(--muted)] p-0.5">
          {tabs.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[12px] transition-colors ${
                activeTab === key
                  ? "bg-[var(--background)] font-medium text-[var(--foreground)] shadow-sm"
                  : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </button>
          ))}
        </nav>

        <div className="flex min-w-0 items-center justify-end gap-0.5">
          <label
            title={t("Share this conversation across browsers")}
            className="mr-1 inline-flex cursor-pointer items-center gap-1.5 text-[11px] text-[var(--muted-foreground)]"
          >
            <input
              type="checkbox"
              aria-label={t("Sync browsers")}
              checked={continuityEnabled}
              disabled={continuityBusy || switchingSession || runtimeContinuityError || chatBusy}
              onChange={() => void toggleContinuity()}
              className="h-3.5 w-3.5 accent-[var(--primary)]"
            />
            <span className="hidden whitespace-nowrap xl:inline">
              {t("Sync browsers")}
            </span>
          </label>
          {(activeTab === "chat" || activeTab === "archive") && (
            <>
              {activeTab === "chat" ? (
                <button
                  type="button"
                  onClick={() => void handleArchiveConversation()}
                  disabled={!chatMessages.length || archiveBusy || switchingSession || chatBusy}
                  title={t("Archive")}
                  aria-label={t("Archive")}
                  className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {archiveBusy ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Archive className="h-4 w-4" />
                  )}
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => setShowSaveModal(true)}
                disabled={!canExport}
                title={t("Save to Notebook")}
                aria-label={t("Save to Notebook")}
                className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40"
              >
                <BookmarkPlus className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={handleDownload}
                disabled={!canExport}
                title={t("Download chat history as Markdown")}
                aria-label={t("Download Markdown")}
                className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Download className="h-4 w-4" />
              </button>
            </>
          )}
          <button
            type="button"
            onClick={() => setShowLinkModal(true)}
            title={t("Link a chat account")}
            aria-label={t("Link a chat account")}
            className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          >
            <Link2 className="h-4 w-4" />
          </button>
          {canManage ? (
            <>
              <button
                type="button"
                onClick={() => void toggleRunning()}
                disabled={lifecycleBusy}
                title={partner.running ? t("Stop") : t("Start")}
                className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40"
              >
                {lifecycleBusy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : partner.running ? (
                  <Square className="h-4 w-4" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
              </button>
              <button
                type="button"
                onClick={() => void handleDestroy()}
                title={t("Delete partner")}
                className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-red-500"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </>
          ) : null}
        </div>
      </div>

      {showLinkModal ? (
        <PartnerLinkModal
          partnerId={partnerId}
          partnerName={partner.name}
          onClose={() => setShowLinkModal(false)}
        />
      ) : null}

      {runtimeContinuityError ? (
        <div className="flex items-center justify-center gap-2 border-b border-[var(--border)] px-4 py-2 text-[12px] text-[var(--muted-foreground)]">
          {t("Could not load browser sync state")}
          <button
            type="button"
            onClick={() => void reconcileSelection()}
            className="rounded-md border border-[var(--border)] px-2 py-1 text-[var(--foreground)] hover:bg-[var(--muted)]"
          >
            {t("Retry")}
          </button>
        </div>
      ) : null}

      {/* Body. Chat stays mounted (hidden off-tab) so an in-progress turn —
          its WebSocket and live trace — survives switching to another tab. */}
      <div className="min-h-0 flex-1">
        <div className={activeTab === "chat" ? "h-full" : "hidden"}>
          <div className="mx-auto h-full max-w-3xl px-5">
            <PartnerChat
              partnerId={partnerId}
              partnerName={partner.name}
              emoji={partner.emoji}
              color={partner.color}
              avatar={partner.avatar}
              sessionKey={sessionKey}
              onSessionKeyChange={changeSessionKey}
              onToast={setToast}
              onMessagesChange={setChatMessages}
              onRuntimeReady={handleRuntimeReady}
              onBusyChange={setChatBusy}
              switchingSession={switchingSession || continuityBusy || archiveBusy || runtimeContinuityError}
              sharedAcrossBrowsers={continuityEnabled}
              onSelectionStale={handleSelectionStale}
            />
          </div>
        </div>
        {activeTab === "archive" ? (
          <div className="mx-auto h-full max-w-5xl overflow-hidden px-5 py-5">
            <PartnerArchives
              partnerId={partnerId}
              onToast={setToast}
              onMessagesChange={setArchiveMessages}
              onDeleted={(deletedKey, activeKey) => {
                if (continuityEnabled) {
                  if (activeKey) changeSessionKey(activeKey, true);
                  else if (deletedKey === sessionKey) void reconcileSelection();
                } else if (deletedKey === sessionKey) {
                  changeSessionKey(freshPartnerSessionKey());
                }
              }}
              onResume={(key, activeKey, didCallResume) => {
                if (continuityEnabled && didCallResume) {
                  if (activeKey) changeSessionKey(activeKey, true);
                  else void reconcileSelection();
                } else {
                  changeSessionKey(key);
                }
                setTab("chat");
              }}
            />
          </div>
        ) : activeTab === "configure" ? (
          <div className="mx-auto h-full max-w-3xl overflow-y-auto px-5 py-5">
            <PartnerConfigure
              partner={partner}
              onToast={setToast}
              onUpdated={() => void load()}
            />
          </div>
        ) : activeTab === "channels" ? (
          <div className="mx-auto h-full max-w-3xl overflow-y-auto px-5 py-5">
            <PartnerChannels partnerId={partnerId} onToast={setToast} />
          </div>
        ) : null}
      </div>

      <SaveToNotebookModal
        open={showSaveModal}
        payload={savePayload}
        messages={saveMessages}
        onClose={() => setShowSaveModal(false)}
        onSaved={() => {
          setShowSaveModal(false);
          setToast(t("Saved to notebook."));
        }}
      />

      {toast && (
        <div className="pointer-events-none fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-[var(--foreground)] px-3.5 py-2 text-[12.5px] text-[var(--background)] shadow-lg">
          {toast}
        </div>
      )}
    </div>
  );
}

export default function PartnerDetailPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
        </div>
      }
    >
      <PartnerDetail />
    </Suspense>
  );
}
