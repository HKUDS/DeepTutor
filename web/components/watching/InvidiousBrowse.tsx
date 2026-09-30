"use client";

import { useCallback, useEffect, useState } from "react";
import { Flame, Loader2, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  getInvidiousHome,
  type InvidiousHubFeed,
  type InvidiousHubItem,
} from "@/lib/video-learning-api";

const TAB_ICONS: Record<string, typeof Sparkles> = {
  Popular: Sparkles,
  Trending: Flame,
};

function formatDuration(value: number): string {
  const total = Math.max(0, Math.floor(Number(value) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function InvidiousBrowse({
  onSelectVideo,
}: {
  onSelectVideo(url: string): void;
}) {
  const { t } = useTranslation();
  const [feed, setFeed] = useState<InvidiousHubFeed | null>(null);
  const [tab, setTab] = useState("Popular");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (nextTab?: string) => {
      setLoading(true);
      setError(null);
      try {
        const data = await getInvidiousHome(nextTab || tab);
        setFeed(data);
        setTab(data.current_tab);
      } catch (caught) {
        setFeed(null);
        setError(
          caught instanceof Error
            ? caught.message
            : t("Could not load Invidious videos."),
        );
      } finally {
        setLoading(false);
      }
    },
    [t, tab],
  );

  useEffect(() => {
    void load("Popular");
    // Load the public hub once when the browse panel mounts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const items = feed?.items ?? [];

  return (
    <div className="flex w-full max-w-3xl flex-col gap-3 text-left">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="font-medium">{t("Browse Invidious")}</h3>
          <p className="text-xs text-[var(--muted-foreground)]">
            {t("Open a public Popular or Trending video through the configured instance.")}
          </p>
        </div>
        <div
          className="grid grid-cols-2 rounded-lg bg-[var(--muted)] p-1"
          role="tablist"
          aria-label={t("Invidious hub tabs")}
        >
          {(feed?.tabs ?? ["Popular", "Trending"]).map((name) => {
            const Icon = TAB_ICONS[name] || Sparkles;
            const selected = tab === name;
            return (
              <button
                key={name}
                type="button"
                role="tab"
                aria-selected={selected}
                disabled={loading}
                onClick={() => void load(name)}
                className={`inline-flex items-center justify-center gap-1 rounded-md px-2 py-1 text-xs font-medium ${
                  selected
                    ? "bg-[var(--background)] shadow-sm"
                    : "text-[var(--muted-foreground)]"
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {t(name)}
              </button>
            );
          })}
        </div>
      </div>

      {error && (
        <p role="alert" className="text-sm text-[var(--muted-foreground)]">
          {error}
        </p>
      )}
      {!error && feed?.reason === "unavailable" && (
        <p role="status" className="text-sm text-[var(--muted-foreground)]">
          {t("Invidious did not return videos. Paste a YouTube URL instead.")}
        </p>
      )}
      {loading ? (
        <div className="flex items-center justify-center py-8 text-[var(--muted-foreground)]">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      ) : items.length ? (
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {items.map((item) => (
            <li key={item.video_id}>
              <HubItem item={item} onSelectVideo={onSelectVideo} />
            </li>
          ))}
        </ul>
      ) : (
        !error && (
          <p className="py-6 text-center text-sm text-[var(--muted-foreground)]">
            {t("No public videos are available from this Invidious instance.")}
          </p>
        )
      )}
    </div>
  );
}

function HubItem({
  item,
  onSelectVideo,
}: {
  item: InvidiousHubItem;
  onSelectVideo(url: string): void;
}) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={() => onSelectVideo(item.url)}
      className="flex w-full gap-3 rounded-lg border border-[var(--border)] p-2 text-left hover:bg-[var(--muted)]"
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={item.thumbnail_url}
        alt=""
        className="h-16 w-28 shrink-0 rounded-md object-cover bg-[var(--muted)]"
      />
      <span className="min-w-0 flex-1">
        <span className="line-clamp-2 text-sm font-medium">{item.title}</span>
        <span className="mt-1 block truncate text-xs text-[var(--muted-foreground)]">
          {item.author || t("Unknown channel")}
        </span>
        <span className="mt-0.5 block text-xs text-[var(--muted-foreground)]">
          {formatDuration(item.duration_seconds)}
        </span>
      </span>
    </button>
  );
}
