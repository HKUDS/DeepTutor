"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  Clock,
  ExternalLink,
  Flame,
  Globe,
  History,
  ListVideo,
  Loader2,
  LogIn,
  LogOut,
  Play,
  Search,
  Sparkles,
  Tv,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  InvidiousFeedItem,
  InvidiousHomeFeed,
  disconnectInvidious,
  getInvidiousAuthorizeUrl,
  getInvidiousHome,
} from "@/lib/video-learning-api";

interface InvidiousHomeProps {
  onSelectVideo: (url: string) => void;
  onOpenInvidious?: () => void;
  onClose?: () => void;
  initialUrl?: string;
}

export function InvidiousHome({ onSelectVideo, onOpenInvidious, onClose, initialUrl = "" }: InvidiousHomeProps) {
  const { t } = useTranslation();
  const [url, setUrl] = useState(initialUrl);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feed, setFeed] = useState<InvidiousHomeFeed | null>(null);
  const [activeTab, setActiveTab] = useState<string>("");
  const [authorizing, setAuthorizing] = useState(false);

  const fetchFeed = useCallback(async (tab?: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await getInvidiousHome(tab);
      setFeed(data);
      if (!activeTab || tab) {
        setActiveTab(data.current_tab);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("Failed to load Invidious feed."));
    } finally {
      setLoading(false);
    }
  }, [activeTab, t]);

  useEffect(() => {
    void fetchFeed();
    const handleAuthMessage = (event: MessageEvent) => {
      if (event.data?.type === "INVIDIOUS_AUTH_SUCCESS") {
        void fetchFeed();
      }
    };
    window.addEventListener("message", handleAuthMessage);
    return () => window.removeEventListener("message", handleAuthMessage);
  }, [fetchFeed]);

  const handleTabChange = (tab: string) => {
    setActiveTab(tab);
    void fetchFeed(tab);
  };

  const handleConnect = async () => {
    setAuthorizing(true);
    try {
      const authUrl = await getInvidiousAuthorizeUrl();
      const popup = window.open(authUrl, "_blank", "width=600,height=750");
      if (!popup) {
        window.location.href = authUrl;
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("Failed to start authorization."));
    } finally {
      setAuthorizing(false);
    }
  };

  const handleDisconnect = async () => {
    try {
      await disconnectInvidious();
      await fetchFeed();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("Failed to disconnect."));
    }
  };

  const handleSubmitUrl = (e: React.FormEvent) => {
    e.preventDefault();
    if (url.trim()) {
      onSelectVideo(url.trim());
    }
  };

  const tabIcons: Record<string, any> = {
    Popular: Sparkles,
    Trending: Flame,
    Subscriptions: Tv,
    Playlists: ListVideo,
    History: History,
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-[var(--background)]">
      {/* Top Header */}
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] px-4 py-3">
        <div className="flex items-center gap-2">
          <Globe className="text-[var(--primary)]" size={20} />
          <div>
            <h2 className="text-sm font-semibold tracking-tight">
              {t("Invidious Video Hub")}
            </h2>
            <p className="text-xs text-[var(--muted-foreground)]">
              {feed?.connected
                ? t("Logged in • Watch history synced to Invidious")
                : t("Public Mode • Connect your account for subscriptions & history")}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {feed?.connected ? (
            <button
              type="button"
              onClick={handleDisconnect}
              className="inline-flex items-center gap-1.5 rounded border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              <LogOut size={13} />
              {t("Disconnect Account")}
            </button>
          ) : (
            <button
              type="button"
              onClick={handleConnect}
              disabled={authorizing}
              className="inline-flex items-center gap-1.5 rounded bg-[var(--foreground)] px-2.5 py-1 text-xs font-medium text-[var(--background)] hover:opacity-90 disabled:opacity-50"
            >
              {authorizing ? <Loader2 size={13} className="animate-spin" /> : <LogIn size={13} />}
              {t("Connect Invidious")}
            </button>
          )}

          {onOpenInvidious && (
            <button
              type="button"
              onClick={onOpenInvidious}
              className="inline-flex items-center gap-1 rounded border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              <ExternalLink size={13} />
              {t("Open Invidious")}
            </button>
          )}

          {onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label={t("Close")}
              className="rounded p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              <X size={16} />
            </button>
          )}
        </div>
      </header>

      {/* URL Input Bar */}
      <div className="border-b border-[var(--border)] bg-[var(--muted)]/20 p-3">
        <form onSubmit={handleSubmitUrl} className="flex gap-2">
          <div className="relative flex-1">
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={t("Paste a YouTube or Invidious video URL...")}
              className="w-full rounded border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--foreground)] placeholder-[var(--muted-foreground)] focus:outline-none focus:ring-1 focus:ring-[var(--foreground)]"
            />
          </div>
          <button
            type="submit"
            disabled={!url.trim()}
            className="inline-flex items-center gap-1.5 rounded bg-[var(--foreground)] px-4 py-2 text-sm font-medium text-[var(--background)] disabled:opacity-50"
          >
            <Play size={14} />
            {t("Start Learning")}
          </button>
        </form>
      </div>

      {/* Tab Navigation */}
      {feed?.tabs && feed.tabs.length > 0 && (
        <div className="flex overflow-x-auto border-b border-[var(--border)] px-4 py-2 gap-1 text-xs">
          {feed.tabs.map((tab) => {
            const Icon = tabIcons[tab] || Sparkles;
            const isActive = activeTab === tab;
            return (
              <button
                key={tab}
                type="button"
                onClick={() => handleTabChange(tab)}
                className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 transition-colors ${
                  isActive
                    ? "bg-[var(--muted)] font-semibold text-[var(--foreground)]"
                    : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
                }`}
              >
                <Icon size={13} />
                {t(tab)}
              </button>
            );
          })}
        </div>
      )}

      {/* Content Area */}
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {loading ? (
          <div className="flex h-48 flex-col items-center justify-center gap-2 text-sm text-[var(--muted-foreground)]">
            <Loader2 className="animate-spin" size={20} />
            <p>{t("Loading videos from Invidious...")}</p>
          </div>
        ) : error ? (
          <div className="rounded border border-red-300/40 p-4 text-center text-sm text-red-500">
            <p>{error}</p>
            <button
              type="button"
              onClick={() => fetchFeed(activeTab)}
              className="mt-2 text-xs underline"
            >
              {t("Retry")}
            </button>
          </div>
        ) : !feed?.items || feed.items.length === 0 ? (
          <div className="flex h-48 flex-col items-center justify-center gap-2 text-center text-sm text-[var(--muted-foreground)]">
            <Search size={24} className="opacity-40" />
            <p>{t("No videos found in this feed.")}</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {feed.items.map((item) => (
              <VideoCard
                key={item.video_id}
                item={item}
                publicBaseUrl={feed.invidious_public_base_url}
                onSelect={() => onSelectVideo(`https://youtu.be/${item.video_id}`)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function VideoCard({
  item,
  publicBaseUrl,
  onSelect,
}: {
  item: InvidiousFeedItem;
  publicBaseUrl: string;
  onSelect: () => void;
}) {
  const { t } = useTranslation();

  return (
    <div className="group relative flex flex-col overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)] transition hover:border-[var(--foreground)]/30 hover:shadow-sm">
      {/* Thumbnail Container */}
      <div
        className="relative aspect-video w-full cursor-pointer bg-black/10 overflow-hidden"
        onClick={onSelect}
      >
        <img
          src={item.thumbnail_url}
          alt={item.title}
          className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
          loading="lazy"
          onError={(e) => {
            // Fallback to youtube img
            (e.currentTarget as HTMLImageElement).src = `https://i.ytimg.com/vi/${item.video_id}/hqdefault.jpg`;
          }}
        />

        {/* Duration badge */}
        {item.duration_seconds > 0 && (
          <span className="absolute bottom-1.5 right-1.5 rounded bg-black/75 px-1.5 py-0.5 font-mono text-[10px] font-medium text-white">
            {formatDuration(item.duration_seconds)}
          </span>
        )}

        {/* Watched badge */}
        {item.watched && (
          <span className="absolute top-1.5 left-1.5 inline-flex items-center gap-1 rounded bg-emerald-600/90 px-1.5 py-0.5 text-[10px] font-medium text-white shadow">
            <CheckCircle2 size={10} />
            {t("Watched")}
          </span>
        )}

        {/* Hover play overlay */}
        <div className="absolute inset-0 flex items-center justify-center bg-black/30 opacity-0 transition-opacity group-hover:opacity-100">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-white/90 text-black shadow">
            <Play size={18} className="translate-x-0.5" />
          </div>
        </div>
      </div>

      {/* Video Details */}
      <div className="flex flex-1 flex-col p-3">
        <h3
          onClick={onSelect}
          className="line-clamp-2 cursor-pointer text-xs font-semibold leading-snug text-[var(--foreground)] group-hover:text-[var(--primary)]"
          title={item.title}
        >
          {item.title}
        </h3>

        <div className="mt-2 flex items-center justify-between gap-2 text-[11px] text-[var(--muted-foreground)]">
          <span className="truncate" title={item.author}>
            {item.author}
          </span>
        </div>

        <div className="mt-1 flex items-center justify-between text-[10px] text-[var(--muted-foreground)]">
          <span>{item.published_text || (item.view_count ? `${item.view_count.toLocaleString()} views` : "")}</span>
          <div className="flex items-center gap-1.5">
            {publicBaseUrl && (
              <a
                href={`${publicBaseUrl}/watch?v=${item.video_id}`}
                target="_blank"
                rel="noreferrer"
                title={t("Open in Invidious")}
                className="hover:text-[var(--foreground)]"
                onClick={(e) => e.stopPropagation()}
              >
                <ExternalLink size={11} />
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
    : `${minutes}:${String(secs).padStart(2, "0")}`;
}
