"use client";

import {
  Activity,
  ArrowLeft,
  Captions,
  Expand,
  Maximize,
  MessageSquare,
  Minimize2,
  MoreHorizontal,
  Settings2,
  StickyNote,
} from "lucide-react";
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
  const { material, loading, error, restore, close, openUrl } =
    useWatching();
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

export type WatchingPanel = "chat" | "transcript" | "notes" | "activity";

/** Presentation only; the player and shared conversation stay mounted across layouts. */
export function WatchingSurface({
  activePanel,
  onPanelChange,
}: {
  activePanel: WatchingPanel;
  onPanelChange(panel: WatchingPanel): void;
}) {
  const { t } = useTranslation();
  const { material } = useWatching();
  const surfaceRef = useRef<HTMLDivElement>(null);
  const [preferencesReady, setPreferencesReady] = useState(false);
  const [learning, setLearning] = useState(false);
  const [railWidth, setRailWidth] = useState(400);
  const [captionsBelow, setCaptionsBelow] = useState(false);
  const [fullscreenError, setFullscreenError] = useState(false);
  const params = useSearchParams();
  const route = useParams();
  const [browsing, setBrowsing] = useState(
    !params.get("video") && !route.sessionId,
  );
  const [accountResult, setAccountResult] = useState(params.get("account"));
  const accountMessage = invidiousAccountResultMessage(accountResult);
  const showBrowser = browsing && !params.get("video");

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      setPreferencesReady(true);
      setLearning(
        browserStorage.readRaw("session", "watching-learning") === "true",
      );
      setCaptionsBelow(
        browserStorage.readRaw("session", "watching-captions-below") ===
          "true",
      );
    });
    return () => cancelAnimationFrame(frame);
  }, []);
  useEffect(() => {
    if (params.has("account"))
      window.history.replaceState(null, "", "/watching");
  }, [params]);
  useEffect(() => {
    const root = surfaceRef.current?.closest<HTMLElement>(
      "[data-watching-workspace]",
    );
    if (!root) return;
    root.dataset.learning = String(learning && !showBrowser);
    root.dataset.browsing = String(showBrowser);
    root.dataset.captionsBelow = String(captionsBelow);
    root.style.setProperty("--watching-rail-width", `${railWidth}px`);
    if (preferencesReady) {
    browserStorage.writeRaw(
      "session",
      "watching-learning",
      String(learning),
    );
    browserStorage.writeRaw(
      "session",
      "watching-captions-below",
      String(captionsBelow),
    );
    }
    // Responsive navigation can remount while focus mode is active.
    const siblings = new Map<HTMLElement, boolean>();
    const isolate = () => {
      let node: HTMLElement = root;
      while (node.parentElement && node.parentElement !== document.body) {
        for (const sibling of Array.from(node.parentElement.children)) {
          if (sibling !== node && sibling instanceof HTMLElement) {
            if (!siblings.has(sibling)) siblings.set(sibling, sibling.inert);
            sibling.inert = true;
          }
        }
        node = node.parentElement;
      }
    };
    const observer = new MutationObserver(isolate);
    if (learning && !showBrowser) {
      isolate();
      observer.observe(document.body, { childList: true, subtree: true });
    }
    return () => {
      observer.disconnect();
      for (const [element, inert] of siblings) element.inert = inert;
    };
  }, [learning, showBrowser, captionsBelow, railWidth, preferencesReady]);
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (
        event.key === "Escape" &&
        !document.fullscreenElement &&
        !Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"]')).some(dialog => dialog.getBoundingClientRect().width > 0 && getComputedStyle(dialog).visibility !== "hidden" && dialog.getAttribute("aria-hidden") !== "true")
      )
        setLearning(false);
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, []);
  useEffect(() => {
    window.dispatchEvent(
      new CustomEvent("dt:watching-panel", { detail: activePanel }),
    );
  }, [activePanel]);
  useEffect(() => {
    const showChat = () => onPanelChange("chat");
    window.addEventListener(WATCHING_ASK_EVENT, showChat);
    return () => window.removeEventListener(WATCHING_ASK_EVENT, showChat);
  }, [onPanelChange]);
  const systemFullscreen = async () => {
    const root = surfaceRef.current?.closest<HTMLElement>(
      "[data-watching-workspace]",
    );
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else if (root?.requestFullscreen) await root.requestFullscreen();
      else setFullscreenError(true);
    } catch {
      setFullscreenError(true);
    }
  };
  return (
    <div
      ref={surfaceRef}
      className="watching-surface"
      data-browsing={showBrowser || undefined}
    >
      {!showBrowser && (
        <>
          <header className="watching-workspace-header">
            <button
              className="watching-icon-button"
              title={t("Browse videos")}
              aria-label={t("Browse videos")}
              onClick={() => {
                window.history.replaceState(
                  null,
                  "",
                  window.location.pathname,
                );
                setBrowsing(true);
              }}
            >
              <ArrowLeft size={18} />
            </button>
            <div className="watching-heading">
              <h1>{material?.metadata.title || t("Immersive Watching")}</h1>
              <span>
                {material?.metadata.author || t("Native YouTube learning")}
              </span>
            </div>
            <button
              className="watching-focus-button"
              aria-pressed={learning}
              onClick={() => setLearning(!learning)}
              title={t(
                learning ? "Exit learning mode" : "Fullscreen learning",
              )}
            >
              {learning ? <Minimize2 size={16} /> : <Expand size={16} />}
              <span>
                {t(learning ? "Exit learning mode" : "Fullscreen learning")}
              </span>
            </button>
            <button
              className="watching-icon-button"
              aria-label={t("System fullscreen")}
              title={t("System fullscreen")}
              onClick={() => void systemFullscreen()}
            >
              <Maximize size={18} />
            </button>
            <details className="watching-more-menu">
              <summary
                className="watching-icon-button"
                aria-label={t("More options")}
              >
                <MoreHorizontal size={20} />
              </summary>
              <div className="watching-menu-content">
                <label>
                  <input
                    type="checkbox"
                    checked={captionsBelow}
                    onChange={(event) =>
                      setCaptionsBelow(event.target.checked)
                    }
                  />
                  {t("Captions below video")}
                </label>
                <button
                  onClick={() => {
                    onPanelChange("activity");
                    surfaceRef.current
                      ?.querySelector("details")
                      ?.removeAttribute("open");
                  }}
                >
                  <Activity size={16} />
                  {t("Activity")}
                </button>
                <button
                  onClick={() => {
                    window.dispatchEvent(new CustomEvent("dt:watching-options"));
                    surfaceRef.current?.querySelector("details")?.removeAttribute("open");
                  }}
                >
                  <Settings2 size={16} />
                  {t("Video options")}
                </button>
              </div>
            </details>
          </header>
          {fullscreenError && (
            <div className="watching-fullscreen-status" role="status">
              {t(
                "System fullscreen unavailable; learning mode remains active.",
              )}
            </div>
          )}
          <div
            className="watching-rail-tabs"
            role="tablist"
            aria-label={t("Video learning panels")}
          >
            {(
              [
                ["chat", "Conversation", MessageSquare],
                ["transcript", "Transcript", Captions],
                ["notes", "Video notes", StickyNote],
              ] as const
            ).map(([name, label, Icon]) => (
              <button
                key={name}
                type="button"
                role="tab"
                aria-selected={activePanel === name}
                aria-controls={`watching-panel-${name}`}
                onClick={() => onPanelChange(name)}
              >
                <Icon size={16} />
                {t(label)}
              </button>
            ))}
            {activePanel === "activity" && (
              <button
                role="tab"
                aria-selected="true"
                onClick={() => onPanelChange("activity")}
              >
                {t("Activity")}
              </button>
            )}
          </div>
          <div
            className="watching-split-handle"
            role="separator"
            tabIndex={0}
            aria-label={t("Video panel width")}
            aria-orientation="vertical"
            aria-valuemin={320}
            aria-valuemax={560}
            aria-valuenow={railWidth}
            onKeyDown={(event) => {
              if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
                event.preventDefault();
                setRailWidth((value) =>
                  Math.max(
                    320,
                    Math.min(
                      560,
                      value + (event.key === "ArrowLeft" ? 16 : -16),
                    ),
                  ),
                );
              }
            }}
            onPointerDown={(event) =>
              event.currentTarget.setPointerCapture(event.pointerId)
            }
            onPointerMove={(event) => {
              if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                const rect = surfaceRef.current
                  ?.closest<HTMLElement>("[data-watching-workspace]")
                  ?.getBoundingClientRect();
                if (rect)
                  setRailWidth(
                    Math.max(
                      320,
                      Math.min(560, rect.right - event.clientX),
                    ),
                  );
              }
            }}
            onPointerUp={(event) =>
              event.currentTarget.releasePointerCapture(event.pointerId)
            }
          />
        </>
      )}
      {accountMessage && showBrowser && (
        <div
          role={accountResult === "connected" ? "status" : "alert"}
          className="watching-account-error flex items-center justify-between gap-3"
        >
          <span>{t(accountMessage)}</span>
          <button
            type="button"
            className="watching-browser-button"
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
      <div className="dt-watching-shell" data-watching-open="true">
        <WatchingPane
          learning={!showBrowser}
          transcriptExpanded={true}
          transcriptActive={activePanel === "transcript"}
          onClose={() => setBrowsing(true)}
        />
      </div>
    </div>
  );
}
