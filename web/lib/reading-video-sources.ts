export interface BilibiliSource {
  bvid: string;
  page: number;
  startSeconds: number;
}

const YOUTUBE_ID = /^[A-Za-z0-9_-]{11}$/;
const BILIBILI_ID = /^BV[0-9A-Za-z]{10}$/i;
const BILIBILI_HOSTS = new Set([
  "bilibili.com",
  "www.bilibili.com",
  "m.bilibili.com",
  "player.bilibili.com",
  "b23.tv",
]);

export function youtubeVideoId(url: string): string {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.toLowerCase();
    let candidate = "";
    if (host === "youtu.be") candidate = parsed.pathname.slice(1).split("/")[0];
    else if (
      [
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
      ].includes(host)
    ) {
      if (
        parsed.pathname.startsWith("/shorts/") ||
        parsed.pathname.startsWith("/live/") ||
        parsed.pathname.startsWith("/embed/")
      ) {
        candidate = parsed.pathname.split("/")[2] || "";
      } else if (parsed.pathname === "/watch") {
        candidate = parsed.searchParams.get("v") ?? "";
      }
    }
    return YOUTUBE_ID.test(candidate) ? candidate : "";
  } catch {
    return "";
  }
}

export function youtubeEntryTime(url: string): number {
  try {
    const parsed = new URL(url);
    return parseMediaTimestamp(
      parsed.searchParams.get("t") || parsed.searchParams.get("start") || "0",
    );
  } catch {
    return 0;
  }
}

export function parseBilibiliSource(url: string): BilibiliSource | null {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.toLowerCase();
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:")
      return null;
    if (!BILIBILI_HOSTS.has(host)) return null;
    let candidate = "";
    if (
      host === "player.bilibili.com" &&
      parsed.pathname.replace(/\/$/, "") === "/player.html"
    ) {
      candidate = parsed.searchParams.get("bvid") || "";
    } else if (host === "b23.tv") {
      candidate = parsed.pathname.slice(1).split("/")[0];
    } else {
      candidate =
        /^\/video\/(BV[0-9A-Za-z]{10})\/?$/i.exec(parsed.pathname)?.[1] || "";
    }
    if (!BILIBILI_ID.test(candidate)) return null;
    const page = Math.max(
      1,
      Number.parseInt(parsed.searchParams.get("p") || "1", 10) || 1,
    );
    const startSeconds = parseMediaTimestamp(
      parsed.searchParams.get("t") || parsed.searchParams.get("start") || "0",
    );
    return { bvid: `BV${candidate.slice(2)}`, page, startSeconds };
  } catch {
    return null;
  }
}

export function bilibiliEmbedUrl(
  source: BilibiliSource,
  startSeconds: number,
): string {
  const params = new URLSearchParams({
    bvid: source.bvid,
    p: String(source.page),
    t: String(Math.max(0, Math.floor(startSeconds))),
    autoplay: "0",
    muted: "0",
    danmaku: "0",
  });
  return `https://player.bilibili.com/player.html?${params}`;
}

export function bilibiliOfficialUrl(
  source: BilibiliSource,
  startSeconds: number,
): string {
  const params = new URLSearchParams();
  if (source.page > 1) params.set("p", String(source.page));
  if (startSeconds > 0) params.set("t", String(Math.floor(startSeconds)));
  return `https://www.bilibili.com/video/${source.bvid}/${params.size ? `?${params}` : ""}`;
}

export function parseMediaTimestamp(value: string): number {
  if (/^\d+$/.test(value)) return Math.max(0, Number(value));
  const match = /^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/i.exec(value);
  if (!match || !match.slice(1).some(Boolean)) return 0;
  return (
    Number(match[1] || 0) * 3600 +
    Number(match[2] || 0) * 60 +
    Number(match[3] || 0)
  );
}
