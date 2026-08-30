"use client";

import { FileAudio, FileText, Film, Globe2, Youtube } from "lucide-react";

import { formatMediaTime } from "@/lib/reading-media-time";
import type {
  ReadingLibraryMaterial,
  ReadingSourceKind,
} from "@/lib/reading-workspace-api";

/**
 * i18n key for a material's kind. Explicit keys rather than translating the
 * wire value, which is a protocol constant and has no business being a
 * user-facing string.
 */
export const sourceKindKey: Record<ReadingSourceKind, string> = {
  file: "Document",
  web: "Web page",
  video: "Video",
  youtube: "YouTube",
  bilibili: "Bilibili",
  audio: "Audio",
};

/**
 * The glyph for a material, resolved through static branches: assigning a
 * component to a local and rendering it reads to React (and to the lint rule)
 * as a component created during render.
 */
export function MaterialGlyph({
  material,
  size = 14,
  className,
}: {
  material: { source_kind: ReadingSourceKind; render_mode?: string };
  size?: number;
  className?: string;
}) {
  if (material.source_kind === "youtube")
    return <Youtube size={size} className={className} />;
  if (material.source_kind === "bilibili" || material.source_kind === "video")
    return <Film size={size} className={className} />;
  if (material.source_kind === "web")
    return <Globe2 size={size} className={className} />;
  if (material.source_kind === "audio" || material.render_mode === "audio")
    return <FileAudio size={size} className={className} />;
  if (material.render_mode === "video")
    return <Film size={size} className={className} />;
  return <FileText size={size} className={className} />;
}

/**
 * Short, upper-case format tag shown in the library's type column: what the
 * user recognises the file by. Derived from the extension first because a
 * server-guessed mime is often the generic octet-stream.
 */
export function formatTag(material: ReadingLibraryMaterial): string {
  if (material.source_kind === "youtube") return "YouTube";
  if (material.source_kind === "bilibili") return "Bilibili";
  if (material.source_kind === "web") return "";
  const extension = material.filename.split(".").pop() ?? "";
  if (extension && extension.length <= 5 && extension !== material.filename) {
    return extension.toUpperCase();
  }
  if (material.render_mode === "video") return "VIDEO";
  if (material.render_mode === "audio") return "AUDIO";
  return "";
}

export function formatBytes(bytes: number | undefined): string {
  if (!bytes || bytes <= 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  const mb = bytes / (1024 * 1024);
  return `${mb >= 100 ? Math.round(mb) : mb.toFixed(1)} MB`;
}

export function formatDuration(seconds: number | undefined): string {
  if (!seconds || seconds <= 0) return "";
  return formatMediaTime(seconds);
}

/**
 * The host and path of a web source, with the scheme and any `www.` dropped —
 * a URL is only useful here as a recognisable label, and the scheme costs
 * characters the truncated line cannot spare.
 */
export function displayUrl(url: string): string {
  if (!url) return "";
  return url.replace(/^https?:\/\//, "").replace(/^www\./, "");
}

/** The line under a material's title: what it is, in the user's terms. */
export function materialDetail(material: ReadingLibraryMaterial): string {
  const parts: string[] = [];
  if (material.source_kind === "web" || material.source_url) {
    parts.push(displayUrl(material.source_url));
  }
  if (material.filename && material.filename !== material.title) {
    parts.push(material.filename);
  }
  const size = formatBytes(material.size_bytes);
  if (size) parts.push(size);
  return parts.filter(Boolean).join(" · ");
}

export function relativeDate(timestamp: number, locale: string): string {
  if (!timestamp) return "";
  const seconds = Math.round((timestamp * 1000 - Date.now()) / 1000);
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  const abs = Math.abs(seconds);
  if (abs < 3600) return formatter.format(Math.round(seconds / 60), "minute");
  if (abs < 86_400) return formatter.format(Math.round(seconds / 3600), "hour");
  if (abs < 2_592_000)
    return formatter.format(Math.round(seconds / 86_400), "day");
  return new Intl.DateTimeFormat(locale, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(timestamp * 1000);
}
