"use client";

import { useEffect, useState } from "react";

import { apiFetch, apiUrl } from "@/lib/api";
import {
  DEFAULT_MAX_ATTACHMENT_BYTES,
  DEFAULT_MAX_TOTAL_ATTACHMENT_BYTES,
} from "@/lib/doc-attachments";

/**
 * Runtime chat-attachment limits.
 *
 * The caps live in `data/user/settings/system.json` (editable at
 * /settings/attachments) and are enforced server-side on every message; the
 * composer mirrors them client-side so oversized picks are rejected before a
 * pointless upload. Defaults apply until the fetch resolves — they match the
 * backend defaults, so a pre-hydration pick is never gated more loosely than
 * the server would allow.
 */
export interface AttachmentLimits {
  /** Per-file cap, bytes. */
  maxFileBytes: number;
  /** Per-message total cap, bytes. */
  maxTotalBytes: number;
}

export const DEFAULT_ATTACHMENT_LIMITS: AttachmentLimits = {
  maxFileBytes: DEFAULT_MAX_ATTACHMENT_BYTES,
  maxTotalBytes: DEFAULT_MAX_TOTAL_ATTACHMENT_BYTES,
};

// Several composers (home chat, book panel, quiz follow-up, partners) mount
// at once; share one fetch and keep the resolved value for the session.
// Admin edits land on the next full page load, which is fine for a policy
// that changes rarely.
let cached: AttachmentLimits | null = null;
let inflight: Promise<AttachmentLimits> | null = null;

function loadAttachmentLimits(): Promise<AttachmentLimits> {
  if (cached) return Promise.resolve(cached);
  if (!inflight) {
    inflight = apiFetch(apiUrl("/api/v1/settings/chat-attachments"))
      .then(async (response) => {
        if (!response.ok) return DEFAULT_ATTACHMENT_LIMITS;
        const data = (await response.json().catch(() => null)) as {
          effective?: { max_file_bytes?: number; max_total_bytes?: number };
        } | null;
        const fileBytes = Number(data?.effective?.max_file_bytes);
        const totalBytes = Number(data?.effective?.max_total_bytes);
        if (!Number.isFinite(fileBytes) || fileBytes <= 0) {
          return DEFAULT_ATTACHMENT_LIMITS;
        }
        cached = {
          maxFileBytes: fileBytes,
          maxTotalBytes:
            Number.isFinite(totalBytes) && totalBytes >= fileBytes
              ? totalBytes
              : fileBytes,
        };
        return cached;
      })
      .catch(() => DEFAULT_ATTACHMENT_LIMITS)
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

/**
 * Effective attachment limits for composer gating. Returns the built-in
 * defaults synchronously, then re-renders once the backend policy arrives.
 */
export function useAttachmentLimits(): AttachmentLimits {
  const [limits, setLimits] = useState<AttachmentLimits>(
    () => cached ?? DEFAULT_ATTACHMENT_LIMITS,
  );

  useEffect(() => {
    if (cached) return;
    let alive = true;
    loadAttachmentLimits().then((value) => {
      if (alive) setLimits(value);
    });
    return () => {
      alive = false;
    };
  }, []);

  return limits;
}
