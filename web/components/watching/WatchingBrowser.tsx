"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  Search,
  Flame,
  TrendingUp,
  Link2,
  Play,
  ListVideo,
  Rss,
  Loader2,
  ArrowLeft,
} from "lucide-react";
import { browserStorage } from "@/shared/storage";
import { useAuthStatus } from "@/hooks/useAuthStatus";
import {
  browseInvidious,
  captionStatus,
  invidiousAccount,
  type InvidiousAccountStatus,
  type InvidiousVideo,
  type InvidiousPlaylist,
} from "@/lib/video-learning-api";

type BrowserView =
  "feed" | "playlists" | "search" | "playlist" | "popular" | "trending";
export function WatchingBrowser({
  onDismiss,
  canDismiss,
}: {
  onDismiss(): void;
  canDismiss: boolean;
}) {
  const { t } = useTranslation();
  const router = useRouter();
  const auth = useAuthStatus();
  const [account, setAccount] = useState<InvidiousAccountStatus | null>(null);
  const [view, setView] = useState<BrowserView>("popular");
  const accountOnly =
    view === "feed" || view === "playlists" || view === "playlist";
  const publicFeed = view === "popular" || view === "trending";
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [playlist, setPlaylist] = useState("");
  const [page, setPage] = useState(1);
  const [withCaptions, setWithCaptions] = useState(false);
  const [captionStates, setCaptionStates] = useState<
    Record<string, { ready: boolean; language: string }>
  >({});
  const [items, setItems] = useState<(InvidiousVideo | InvidiousPlaylist)[]>(
    [],
  );
  const [busy, setBusy] = useState(false);
  const [accountBusy, setAccountBusy] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const scroll = useRef<HTMLDivElement>(null);
  const restored = useRef(false);
  const key = `watching-browser:${auth.userId ?? "local"}`;

  useEffect(() => {
    if (auth.loading || !auth.statusAvailable) return;
    let alive = true;
    setItems([]);
    setCaptionStates({});
    setAccount(null);
    void invidiousAccount("status")
      .then(status => {
        if (!alive) return;
        setAccount(status);
        let saved: {
          version?: number;
          withCaptions?: boolean;
          view?: BrowserView;
          query?: string;
          page?: number;
          playlist?: string;
          scroll?: number;
        } = {};
        try {
          saved = JSON.parse(browserStorage.readRaw("session", key) || "{}");
        } catch {
          /* Storage is optional. */
        }
        if (!restored.current) {
          restored.current = true;
          setView(
            saved.view &&
              (saved.version === 2 ||
                (saved.view === "search" && saved.query?.trim())) &&
              !(saved.view === "search" && !saved.query?.trim())
              ? saved.view
              : "popular",
          );
          setWithCaptions(saved.withCaptions === true);
          setQuery(saved.query || "");
          setInput(saved.query || "");
          setPage(saved.page || 1);
          setPlaylist(saved.playlist || "");
        }
      })
      .catch(() => {
        if (alive)
          setError(t("Could not load the Invidious account. Please retry."));
      });
    return () => {
      alive = false;
    };
  }, [auth.loading, auth.statusAvailable, key, t]);

  useEffect(() => {
    if (!account) return;
    const controller = new AbortController();
    setItems([]);
    setCaptionStates({});
    setError("");
    setBusy(false);
    if (
      (accountOnly && !account.connected) ||
      (view === "search" && !query.trim())
    )
      return;
    setBusy(true);
    void browseInvidious(
      view,
      withCaptions && view === "search" ? `${query} features:subtitles` : query,
      page,
      playlist,
      controller.signal,
    )
      .then(data => {
        if (controller.signal.aborted) return;
        const loaded = Array.isArray(data) ? data : data.videos || [];
        setItems(loaded);
        const ids = loaded.flatMap(item =>
          "videoId" in item ? [item.videoId] : [],
        );
        if (ids.length)
          void captionStatus(ids, controller.signal)
            .then(states => {
              if (!controller.signal.aborted) setCaptionStates(states);
            })
            .catch(() => {
              /* Cache status is optional; browsing stays available. */
            });
        requestAnimationFrame(() => {
          try {
            if (scroll.current)
              scroll.current.scrollTop =
                JSON.parse(browserStorage.readRaw("session", key) || "{}")
                  .scroll || 0;
          } catch {
            /* Optional. */
          }
        });
      })
      .catch((e: Error) => {
        if (!controller.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, [
    account,
    view,
    query,
    page,
    playlist,
    reload,
    key,
    accountOnly,
    withCaptions,
  ]);

  function remember(position = 0) {
    try {
      browserStorage.writeRaw(
        "session",
        key,
        JSON.stringify({
          version: 2,
          withCaptions,
          view,
          query,
          page,
          playlist,
          scroll: position,
        }),
      );
    } catch {
      /* Optional. */
    }
  }
  async function connect() {
    setAccountBusy(true);
    setError("");
    try {
      const result = await invidiousAccount("authorize");
      if (result.authorize_url) {
        remember();
        window.location.assign(result.authorize_url);
      }
    } catch {
      setError(t("Could not connect to Invidious. Please retry."));
    } finally {
      setAccountBusy(false);
    }
  }
  async function disconnect() {
    setAccountBusy(true);
    setError("");
    try {
      const status = await invidiousAccount("disconnect");
      setAccount(status);
      setItems([]);
      setCaptionStates({});
      setView("popular");
      setPage(1);
      setQuery("");
      setInput("");
      try {
        browserStorage.removeRaw("session", key);
      } catch {
        /* Optional. */
      }
    } catch {
      setError(
        t("Could not disconnect. Please retry when the instance is available."),
      );
    } finally {
      setAccountBusy(false);
    }
  }
  function select(url: string) {
    remember(scroll.current?.scrollTop || 0);
    router.push(`/watching?video=${encodeURIComponent(url)}`);
    onDismiss();
  }
  return (
    <section className="watching-browser" aria-label={t("Browse videos")}>
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] p-5">
        <div>
          <h1 className="text-xl font-semibold">{t("Immersive Watching")}</h1>
          <p className="mt-1 text-sm text-[var(--muted-foreground)]">
            {t("Your videos, with room to learn.")}
          </p>
        </div>
        <div className="flex items-center gap-2 text-sm">
          {canDismiss && (
            <button className="watching-browser-button" onClick={onDismiss}>
              <ArrowLeft size={16} />
              {t("Back to video")}
            </button>
          )}
          <button
            className="watching-browser-button"
            disabled={accountBusy || auth.loading}
            onClick={() => void (account?.connected ? disconnect() : connect())}
          >
            {accountBusy ? (
              <Loader2 className="animate-spin" size={16} />
            ) : (
              <Link2 size={16} />
            )}
            {account?.connected
              ? t("Disconnect Invidious")
              : account?.needs_reauthorization
                ? t("Reconnect Invidious")
                : t("Connect Invidious")}
          </button>
        </div>
      </header>
      <div className="px-5 pt-5">
        {account && !account.connected && (
          <p className="mb-4 text-sm text-[var(--muted-foreground)]">
            {t(
              "Sign in with your Invidious account, then approve read-only access to return here. Your DeepTutor login is separate.",
            )}
          </p>
        )}
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={withCaptions}
            onChange={event => {
              setWithCaptions(event.target.checked);
              setPage(1);
            }}
          />
          {t("With captions only")}
        </label>
        <form
          className="flex gap-2"
          onSubmit={event => {
            event.preventDefault();
            if (/^https?:\/\//i.test(input.trim())) {
              select(input.trim());
              return;
            }
            setView("search");
            setQuery(input.trim());
            setPage(1);
          }}
        >
          <input
            className="min-w-0 flex-1 rounded-xl border border-[var(--border)] bg-[var(--background)] px-4 py-3"
            aria-label={t("Search videos or paste a video link")}
            placeholder={t("Search videos or paste a video link")}
            value={input}
            onChange={e => setInput(e.target.value)}
          />
          <button
            className="watching-browser-button"
            type="submit"
            disabled={!input.trim()}
          >
            <Search size={18} />
            <span className="hidden sm:inline">{t("Search")}</span>
          </button>
        </form>
        <nav
          className="mt-4 flex gap-2 overflow-x-auto pb-2 [&>button]:shrink-0"
          aria-label={t("Video browsing views")}
        >
          {(
            [
              ["popular", Flame, t("Popular")],
              ["trending", TrendingUp, t("Trending")],
              ["feed", Rss, t("Subscription feed")],
              ["playlists", ListVideo, t("Playlists")],
              ["search", Search, t("Search")],
            ] as const
          ).map(([tab, Icon, label]) => (
            <button
              key={tab}
              className="watching-browser-button"
              aria-pressed={
                view === tab || (tab === "playlists" && view === "playlist")
              }
              onClick={() => {
                setView(tab);
                setPage(1);
              }}
            >
              <Icon size={16} />
              {label}
            </button>
          ))}
        </nav>
      </div>
      <div
        ref={scroll}
        className="min-h-0 flex-1 overflow-y-auto p-5"
        onScroll={() => remember(scroll.current?.scrollTop || 0)}
      >
        {error && (
          <div
            role="alert"
            className="mb-4 rounded-xl border border-[var(--border)] p-4"
          >
            {t(error)}{" "}
            <button
              className="underline"
              onClick={() => {
                setReload(n => n + 1);
                if (!account)
                  void invidiousAccount("status")
                    .then(setAccount)
                    .catch(() => undefined);
              }}
            >
              {t("Retry")}
            </button>
          </div>
        )}
        {accountOnly && account && !account.connected ? (
          <div className="watching-browser-empty">
            <Link2 size={32} />
            <p>
              {t(
                "Connect your Invidious account to see subscriptions and playlists.",
              )}
            </p>
            <button
              className="watching-browser-button"
              onClick={() => void connect()}
              disabled={accountBusy}
            >
              {t("Connect Invidious")}
            </button>
          </div>
        ) : busy ? (
          <div role="status" className="watching-browser-empty">
            <Loader2 className="animate-spin" />
            {t("Loading videos…")}
          </div>
        ) : (
          <>
            {view === "playlist" && (
              <button
                className="watching-browser-button mb-4"
                onClick={() => {
                  setView("playlists");
                  setPage(1);
                }}
              >
                <ArrowLeft size={16} />
                {t("Playlists")}
              </button>
            )}
            <div className="watching-video-grid">
              {items.map(item => {
                const isPlaylist = "playlistId" in item;
                const video = isPlaylist ? item.videos?.[0] : item;
                const thumbnail = video?.videoThumbnails?.find(thumb =>
                  /^https?:\/\//.test(thumb.url),
                )?.url;
                return (
                  <button
                    key={isPlaylist ? item.playlistId : item.videoId}
                    className="watching-video-card"
                    onClick={() => {
                      if (isPlaylist) {
                        setPlaylist(item.playlistId);
                        setView("playlist");
                        setPage(1);
                      } else
                        select(
                          `https://www.youtube.com/watch?v=${encodeURIComponent(item.videoId)}`,
                        );
                    }}
                  >
                    <div className="relative flex aspect-video items-center justify-center overflow-hidden rounded-xl bg-[var(--muted)]">
                      {thumbnail ? (
                        <img
                          src={thumbnail}
                          alt=""
                          loading="lazy"
                          referrerPolicy="no-referrer"
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <Play size={28} />
                      )}
                      {!isPlaylist && (
                        <span className="absolute bottom-2 right-2 rounded bg-black/75 px-1.5 py-0.5 text-xs text-white">
                          {Math.floor((item.lengthSeconds || 0) / 60)}:
                          {String((item.lengthSeconds || 0) % 60).padStart(
                            2,
                            "0",
                          )}
                        </span>
                      )}
                    </div>
                    {!isPlaylist &&
                      (captionStates[item.videoId]?.ready ||
                        item.hasCaptions) && (
                        <span className="mt-2 inline-block rounded bg-[var(--muted)] px-2 py-1 text-xs">
                          {captionStates[item.videoId]?.ready
                            ? `${t("Captions ready")} · ${captionStates[item.videoId].language}`
                            : `CC · ${t("Has captions")}`}
                        </span>
                      )}
                    <h2 className="mt-3 line-clamp-2 text-sm font-medium">
                      {item.title}
                    </h2>
                    <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                      {isPlaylist
                        ? `${item.videoCount} ${t("videos")}`
                        : item.author}
                    </p>
                  </button>
                );
              })}
            </div>
            {!items.length && !error && (
              <div className="watching-browser-empty">
                <Play size={32} />
                <p>
                  {view === "search" && !query
                    ? t("Find a video to start learning.")
                    : t("No videos here yet.")}
                </p>
                {!publicFeed && (
                  <button
                    className="watching-browser-button"
                    onClick={() => {
                      setView("popular");
                      setPage(1);
                    }}
                  >
                    {t("Explore popular videos")}
                  </button>
                )}
              </div>
            )}
            {!publicFeed &&
              view !== "playlists" &&
              (items.length > 0 || page > 1) && (
                <div className="mt-6 flex justify-center gap-4">
                  <button
                    className="watching-browser-button"
                    disabled={page <= 1}
                    onClick={() => setPage(page - 1)}
                  >
                    {t("Previous")}
                  </button>
                  <span className="self-center">{page}</span>
                  <button
                    className="watching-browser-button"
                    disabled={!items.length}
                    onClick={() => setPage(page + 1)}
                  >
                    {t("Next")}
                  </button>
                </div>
              )}
          </>
        )}
      </div>
    </section>
  );
}
