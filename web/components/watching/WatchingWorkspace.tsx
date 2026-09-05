"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useWatching } from "@/context/WatchingContext";
import type { SessionConfiguration } from "@/features/chat/ChatStateAdapter";
import { WatchingPane, WATCHING_ASK_EVENT } from "./WatchingPane";

/** Bind the existing player to the selected conversation, never browser-global history. */
export function WatchingSessionBridge({
  sessionKey,
  materialId,
  onMaterial,
}: {
  sessionKey: string;
  materialId: string | null;
  onMaterial(configuration: SessionConfiguration): void;
}) {
  const { material, loading, error, restore, close } = useWatching();
  const [restoredKey, setRestoredKey] = useState<string | null>(null);
  const binding = useRef(materialId);
  useEffect(() => {
    binding.current = materialId;
  }, [materialId]);
  useEffect(() => {
    let cancelled = false;
    void restore(binding.current).then(() => {
      if (!cancelled) setRestoredKey(sessionKey);
    });
    return () => {
      cancelled = true;
      close();
    };
  }, [sessionKey, restore, close]);
  useEffect(() => {
    if (
      restoredKey !== sessionKey ||
      loading ||
      error ||
      (material?.material_id ?? null) === materialId
    )
      return;
    onMaterial({ timedMediaId: material?.material_id ?? null });
  }, [restoredKey, sessionKey, material, materialId, loading, error, onMaterial]);
  return null;
}

/** Responsive presentation only; ChatWorkspace continues to own the single chat runtime. */
export function WatchingSurface() {
  const { t } = useTranslation();
  const [view, setView] = useState<"video" | "chat">("video");
  useEffect(() => {
    const showChat = () => setView("chat");
    window.addEventListener(WATCHING_ASK_EVENT, showChat);
    return () => window.removeEventListener(WATCHING_ASK_EVENT, showChat);
  }, []);
  return (
    <div className="watching-surface" data-mobile-view={view}>
      <div
        className="watching-mobile-tabs"
        role="group"
        aria-label={t("Immersive Watching")}
      >
        <button
          type="button"
          aria-pressed={view === "video"}
          onClick={() => setView("video")}
        >
          {t("Video")}
        </button>
        <button
          type="button"
          aria-pressed={view === "chat"}
          onClick={() => setView("chat")}
        >
          {t("Conversation")}
        </button>
      </div>
      <div className="dt-watching-shell" data-watching-open="true">
        <WatchingPane onClose={() => setView("chat")} />
      </div>
    </div>
  );
}
