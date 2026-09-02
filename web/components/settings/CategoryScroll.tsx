"use client";

import { useEffect, useRef } from "react";

import {
  SETTINGS_ANCHOR_EVENT,
  scrollToSettingsSection,
  type SettingsAnchorEvent,
} from "@/features/settings/navigation/settings-scroll";
import { useSettings } from "@/features/settings/store/SettingsStore";

export type CategorySection = {
  key: string;
  Component: React.ComponentType;
};

/**
 * A continuously scrolling settings document. It is used both for the whole
 * Settings page (Overview through About) and for the nested sections inside
 * Models, Chat, and Partners & Agents.
 *
 * Scroll position is the source of truth for "which leaf is active" — not
 * `IntersectionObserver`, which does not reliably fire in every render
 * surface this app runs in (see the immersive-reading capability). A rect
 * check on the ancestor scroll container (`[data-settings-scroll]`, from
 * `SettingsMain`) is cheap enough to run on every scroll tick.
 */
export function CategoryScroll({ sections }: { sections: CategorySection[] }) {
  const { setActiveSection } = useSettings();
  const rootRef = useRef<HTMLDivElement>(null);
  const pendingAnchorRef = useRef<string | null>(null);

  // Only the outermost document owns scroll tracking. Merged category pages
  // are also rendered on their legacy routes, so they keep working on their
  // own; when nested inside /settings, the parent sees their marked sections
  // and tracks the complete document without competing state updates.
  useEffect(() => {
    const rootElement = rootRef.current;
    if (!rootElement) return;
    const nested = Boolean(
      rootElement.parentElement?.closest("[data-settings-section-list]"),
    );
    if (nested) return;

    const alignToAnchor = (requested: string) => {
      const requestedElement = requested
        ? document.getElementById(requested)
        : null;
      const validRequested = Boolean(
        requestedElement && rootElement.contains(requestedElement),
      );
      setActiveSection(validRequested ? requested : (sections[0]?.key ?? null));
      if (requested && !validRequested && sections[0]?.key) {
        window.history.replaceState(
          null,
          "",
          `${window.location.pathname}#${sections[0].key}`,
        );
      }
      if (validRequested) {
        pendingAnchorRef.current = requested;
        requestAnimationFrame(() => {
          scrollToSettingsSection(requested, "auto");
          window.history.replaceState(
            null,
            "",
            `${window.location.pathname}#${requested}`,
          );
        });
      }
    };

    const applyLocationHash = () => {
      alignToAnchor(window.location.hash.replace(/^#/, ""));
    };

    const applyRequestedAnchor = (event: Event) => {
      const key = (event as SettingsAnchorEvent).detail?.key;
      if (key) alignToAnchor(key);
    };

    // Settings sections fetch independently. Late content can move a deep
    // anchor after the first jump, so keep it aligned across layout changes
    // until the user deliberately starts navigating the document.
    const resizeObserver =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => {
            const key = pendingAnchorRef.current;
            if (key) alignToAnchor(key);
          });
    resizeObserver?.observe(rootElement);

    const cancelPendingAnchor = () => {
      pendingAnchorRef.current = null;
    };
    const scroller = rootElement.closest<HTMLElement>("[data-settings-scroll]");
    const cancelEvents = ["wheel", "touchstart", "pointerdown", "keydown"];
    for (const eventName of cancelEvents) {
      scroller?.addEventListener(eventName, cancelPendingAnchor, {
        passive: true,
      });
    }

    applyLocationHash();
    window.addEventListener("hashchange", applyLocationHash);
    window.addEventListener(SETTINGS_ANCHOR_EVENT, applyRequestedAnchor);
    return () => {
      window.removeEventListener("hashchange", applyLocationHash);
      window.removeEventListener(SETTINGS_ANCHOR_EVENT, applyRequestedAnchor);
      resizeObserver?.disconnect();
      for (const eventName of cancelEvents) {
        scroller?.removeEventListener(eventName, cancelPendingAnchor);
      }
      pendingAnchorRef.current = null;
      setActiveSection(null);
    };
    // Anchor handling only matters on mount — re-running it on every
    // `sections` identity change would re-jump the scroll position.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const rootElement = rootRef.current;
    if (!rootElement) return;
    const nested = Boolean(
      rootElement.parentElement?.closest("[data-settings-section-list]"),
    );
    if (nested) return;

    const root = rootElement.closest<HTMLElement>("[data-settings-scroll]");
    if (!root) return;

    let ticking = false;
    const measure = () => {
      ticking = false;
      const pendingAnchor = pendingAnchorRef.current;
      if (pendingAnchor) {
        setActiveSection(pendingAnchor);
        if (window.location.hash !== `#${pendingAnchor}`) {
          window.history.replaceState(
            null,
            "",
            `${window.location.pathname}#${pendingAnchor}`,
          );
        }
        return;
      }
      const threshold = root.getBoundingClientRect().top + 96;
      const allSections = Array.from(
        rootElement.querySelectorAll<HTMLElement>("[data-settings-section]"),
      );
      let current = allSections[0]?.id || sections[0]?.key || null;
      for (const element of allSections) {
        if (element.getBoundingClientRect().top <= threshold) {
          current = element.id;
        }
      }
      setActiveSection(current);
      if (current && window.location.hash !== `#${current}`) {
        window.history.replaceState(
          null,
          "",
          `${window.location.pathname}#${current}`,
        );
      }
    };
    const onScroll = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(measure);
    };
    root.addEventListener("scroll", onScroll, { passive: true });
    const raf = requestAnimationFrame(measure);
    return () => {
      cancelAnimationFrame(raf);
      root.removeEventListener("scroll", onScroll);
    };
  }, [sections, setActiveSection]);

  return (
    <div ref={rootRef} data-settings-section-list>
      {sections.map(({ key, Component }, index) => (
        <section
          key={key}
          id={key}
          data-settings-section
          className={
            index === 0
              ? "scroll-mt-16"
              : "mt-12 scroll-mt-16 border-t border-[var(--border)]/60 pt-12"
          }
        >
          <Component />
        </section>
      ))}
    </div>
  );
}
