"use client";

import { browserStorage } from "@/shared/storage";
import { useEffect, useRef, useState } from "react";
import { useSearchParams, useParams } from "next/navigation";
import { invidiousAccountResultMessage } from "@/lib/invidious-account-result";
import { WatchingBrowser } from "./WatchingBrowser";
import { useTranslation } from "react-i18next";
import { useWatching } from "@/context/WatchingContext";
import type { SessionConfiguration } from "@/features/chat/ChatStateAdapter";
import { WatchingPane, WATCHING_ASK_EVENT } from "./WatchingPane";

/** Bind the existing player to the selected conversation, never browser-global history. */
export function WatchingSessionBridge({
  sessionKey,
  materialId,
  onMaterial,
  sourceUrl,
}: {
  sourceUrl?: string | null;
  sessionKey: string;
  materialId: string | null;
  onMaterial(configuration: SessionConfiguration): void;
}) {
  const { material, loading, error, restore, close, openUrl } = useWatching();
  const [restoredKey, setRestoredKey] = useState<string | null>(null);
  const binding = useRef(materialId);
  useEffect(() => {
    binding.current = materialId;
  }, [materialId]);
  useEffect(() => {
    let cancelled = false;
    void restore(sourceUrl ? null : binding.current).then(async () => {
      if (cancelled) return;
      if (sourceUrl) await openUrl(sourceUrl);
      if (!cancelled) setRestoredKey(sessionKey);
    });
    return () => {
      cancelled = true;
      close();
    };
  }, [sessionKey, sourceUrl, restore, close, openUrl]);
  useEffect(() => {
    if (
      restoredKey !== sessionKey ||
      loading ||
      error ||
      (material?.material_id ?? null) === materialId
    )
      return;
    onMaterial({ timedMediaId: material?.material_id ?? null });
  }, [
    restoredKey,
    sessionKey,
    material,
    materialId,
    loading,
    error,
    onMaterial,
  ]);
  return null;
}

/** Responsive presentation only; ChatWorkspace continues to own the single chat runtime. */
export function WatchingSurface() {
  const { t } = useTranslation();
  const { material } = useWatching();
  const surfaceRef = useRef<HTMLDivElement>(null);
  const [learning, setLearning] = useState(false);
  const [rightPanel, setRightPanel] = useState("chat");
  const [split, setSplit] = useState(60);
  const [fullscreenError, setFullscreenError] = useState(false);
  useEffect(() => {
    const stored =
      browserStorage.readRaw("session", "watching-learning") === "true";
    const frame = requestAnimationFrame(() => setLearning(stored));
    return () => cancelAnimationFrame(frame);
  }, []);
  useEffect(() => {
    const root = surfaceRef.current?.closest<HTMLElement>(
      "[data-watching-workspace]",
    );
    if (!root) return;
    root.dataset.learning = String(learning);
    root.dataset.learningPanel = rightPanel;
    root.style.setProperty("--watching-split", `${split}%`);
    browserStorage.writeRaw("session", "watching-learning", String(learning));
    return () => {
      delete root.dataset.learning;
      delete root.dataset.learningPanel;
    };
  }, [learning, rightPanel, split]);
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (
        event.key === "Escape" &&
        !document.fullscreenElement &&
        !document.querySelector('[role="dialog"]')
      )
        setLearning(false);
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, []);
  const panel = (name: string) => {
    setRightPanel(name);
    setView(name as "chat" | "transcript" | "notes");
    window.dispatchEvent(
      new CustomEvent("dt:watching-panel", { detail: name }),
    );
  };

  const params = useSearchParams();
  const route = useParams();
  const [browsing, setBrowsing] = useState(
    !params.get("video") && !route.sessionId,
  );
  const [accountResult, setAccountResult] = useState(params.get("account"));
  const accountMessage = invidiousAccountResultMessage(accountResult);
  useEffect(() => {
    if (params.has("account"))
      window.history.replaceState(null, "", "/watching");
  }, [params]);
  const showBrowser = browsing && !params.get("video");
  const [view, setView] = useState<"video" | "chat" | "transcript" | "notes">("video");
  useEffect(() => {
    const showChat = () => { setView("chat"); setRightPanel("chat"); window.dispatchEvent(new CustomEvent("dt:watching-panel", {detail: "chat"})); };
    window.addEventListener(WATCHING_ASK_EVENT, showChat);
    return () => window.removeEventListener(WATCHING_ASK_EVENT, showChat);
  }, []);
  return (
    <div
      ref={surfaceRef}
      className="watching-surface"
      data-mobile-view={view}
      data-browsing={showBrowser || undefined}
    >
      {!showBrowser && (
        <div className="watching-learning-toolbar">
          <button
            className="watching-browser-button"
            onClick={() => setLearning(!learning)}
          >
            {t(learning ? "Exit learning mode" : "Fullscreen learning")}
          </button>
          {learning && (
            <>
              <button
                className="watching-browser-button"
                onClick={async () => {
                  const root = surfaceRef.current?.closest<HTMLElement>(
                    "[data-watching-workspace]",
                  );
                  try {
                    if (document.fullscreenElement)
                      await document.exitFullscreen();
                    else if (root?.requestFullscreen)
                      await root.requestFullscreen();
                    else setFullscreenError(true);
                  } catch {
                    setFullscreenError(true);
                  }
                }}
              >
                {t("System fullscreen")}
              </button>
              <button
                className="watching-browser-button"
                aria-pressed={rightPanel === "chat"}
                onClick={() => panel("chat")}
              >
                {t("Conversation")}
              </button>
              <button
                className="watching-browser-button"
                aria-pressed={rightPanel === "notes"}
                onClick={() => panel("notes")}
              >
                {t("Video notes")}
              </button>

            </>
          )}
          {fullscreenError && (
            <span role="status">
              {t(
                "System fullscreen unavailable; learning mode remains active.",
              )}
            </span>
          )}
        </div>
      )}
      {learning && !showBrowser && <div className="watching-split-handle" role="separator" tabIndex={0}
        aria-label={t("Video panel width")} aria-orientation="vertical" aria-valuemin={40} aria-valuemax={75} aria-valuenow={split}
        onKeyDown={event => { if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); setSplit(value => Math.max(40, Math.min(75, value + (event.key === "ArrowRight" ? 1 : -1)))); } }}
        onPointerDown={event => event.currentTarget.setPointerCapture(event.pointerId)}
        onPointerMove={event => { if (event.currentTarget.hasPointerCapture(event.pointerId)) { const rect = surfaceRef.current?.closest<HTMLElement>("[data-watching-workspace]")?.getBoundingClientRect(); if (rect) setSplit(Math.max(40, Math.min(75, (event.clientX - rect.left) / rect.width * 100))); } }}
        onPointerUp={event => event.currentTarget.releasePointerCapture(event.pointerId)} />}
      {accountMessage && showBrowser && (
        <div
          role={accountResult === "connected" ? "status" : "alert"}
          className="watching-account-error flex items-center justify-between gap-3"
        >
          <span>{t(accountMessage)}</span>
          <button
            type="button"
            className="watching-browser-button shrink-0"
            onClick={() => setAccountResult(null)}
          >
            {t("Dismiss")}
          </button>
        </div>
      )}
      {showBrowser && (
        <WatchingBrowser
          canDismiss={!!material}
          onDismiss={() => setBrowsing(false)}
        />
      )}
      {!showBrowser && (
        <button
          className="watching-browse-toggle watching-browser-button"
          onClick={() => {
            window.history.replaceState(null, "", window.location.pathname);
            setBrowsing(true);
          }}
        >
          {t("Browse videos")}
        </button>
      )}
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
          onClick={() => panel("chat")}
        >
          {t("Conversation")}
        </button>
        {learning && (
          <>
            <button type="button" onClick={() => panel("transcript")}>
              {t("Transcript")}
            </button>
            <button type="button" onClick={() => panel("notes")}>
              {t("Video notes")}
            </button>
          </>
        )}
      </div>
      <div className="dt-watching-shell" data-watching-open="true">
        <WatchingPane
          learning={learning && !showBrowser}
          transcriptExpanded={view === "transcript"}
          onClose={() => setView("chat")}
        />
      </div>
    </div>
  );
}
