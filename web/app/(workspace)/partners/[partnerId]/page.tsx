"use client";

/**
 * Partner detail: a chat-first page with Configure and Channels tabs.
 * Header carries identity + run state; everything else lives in the tabs.
 */

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  Archive,
  BookmarkPlus,
  Download,
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
  destroyPartner,
  getPartner,
  startPartner,
  stopPartner,
  type PartnerInfo,
} from "@/lib/partners-api";
import {
  downloadChatMarkdown,
  type ExportableMessage,
} from "@/lib/chat-export";
import {
  loadPartnerSessionKey,
  persistPartnerSessionKey,
} from "@/lib/partner-session";
import PartnerAvatar from "@/components/partners/PartnerAvatar";
import PartnerChat from "@/components/partners/PartnerChat";
import PartnerChannels from "@/components/partners/PartnerChannels";
import PartnerConfigure from "@/components/partners/PartnerConfigure";
import PartnerArchives from "@/components/partners/PartnerArchives";
import SaveToNotebookModal, {
  type NotebookSaveMessage,
  type NotebookSavePayload,
} from "@/components/notebook/SaveToNotebookModal";

type Tab = "chat" | "configure" | "channels" | "archive";

function PartnerDetail() {
  const params = useParams<{ partnerId: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const { t } = useTranslation();
  const partnerId = params.partnerId;

  const initialTab = (searchParams.get("tab") as Tab) || "chat";
  const [tab, setTab] = useState<Tab>(
    ["chat", "configure", "channels", "archive"].includes(initialTab)
      ? initialTab
      : "chat",
  );
  const [partner, setPartner] = useState<PartnerInfo | null>(null);
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
  // The active web session key lives here so the Archive tab's Resume can
  // point the (always-mounted) Chat tab at a different conversation.
  const [sessionKey, setSessionKey] = useState("");
  useEffect(() => {
    setSessionKey(loadPartnerSessionKey(partnerId));
  }, [partnerId]);
  const changeSessionKey = useCallback(
    (key: string) => {
      persistPartnerSessionKey(partnerId, key);
      setSessionKey(key);
    },
    [partnerId],
  );

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(timer);
  }, [toast]);

  const exportMessages = useMemo<ExportableMessage[]>(() => {
    if (tab === "chat") return chatMessages;
    if (tab === "archive") return archiveMessages;
    return [];
  }, [tab, chatMessages, archiveMessages]);

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

  const load = useCallback(async () => {
    try {
      setPartner(await getPartner(partnerId));
    } catch {
      setPartner(null);
    } finally {
      setLoading(false);
    }
  }, [partnerId]);

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

  if (loading) {
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

  const tabs: { key: Tab; label: string; icon: typeof MessageCircle }[] = [
    { key: "chat", label: t("Chat"), icon: MessageCircle },
    { key: "configure", label: t("Configure"), icon: Settings2 },
    { key: "channels", label: t("Channels"), icon: Radio },
    { key: "archive", label: t("Archive"), icon: Archive },
  ];

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-[var(--border)] px-5 py-3">
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
        <div className="min-w-0 flex-1">
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

        <nav className="flex gap-0.5 rounded-lg bg-[var(--muted)] p-0.5">
          {tabs.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[12px] transition-colors ${
                tab === key
                  ? "bg-[var(--background)] font-medium text-[var(--foreground)] shadow-sm"
                  : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </button>
          ))}
        </nav>

        {(tab === "chat" || tab === "archive") && (
          <>
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
      </div>

      {/* Body. Chat stays mounted (hidden off-tab) so an in-progress turn —
          its WebSocket and live trace — survives switching to another tab. */}
      <div className="min-h-0 flex-1">
        <div className={tab === "chat" ? "h-full" : "hidden"}>
          <div className="mx-auto h-full max-w-3xl px-5">
            <PartnerChat
              partnerId={partnerId}
              partnerName={partner.name}
              emoji={partner.emoji}
              color={partner.color}
              avatar={partner.avatar}
              running={partner.running}
              sessionKey={sessionKey}
              onSessionKeyChange={changeSessionKey}
              onToast={setToast}
              onMessagesChange={setChatMessages}
            />
          </div>
        </div>
        {tab === "archive" ? (
          <div className="mx-auto h-full max-w-5xl overflow-hidden px-5 py-5">
            <PartnerArchives
              partnerId={partnerId}
              onToast={setToast}
              onMessagesChange={setArchiveMessages}
              onResume={(key) => {
                changeSessionKey(key);
                setTab("chat");
              }}
            />
          </div>
        ) : tab === "configure" ? (
          <div className="mx-auto h-full max-w-3xl overflow-y-auto px-5 py-5">
            <PartnerConfigure
              partner={partner}
              onToast={setToast}
              onUpdated={() => void load()}
            />
          </div>
        ) : tab === "channels" ? (
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
