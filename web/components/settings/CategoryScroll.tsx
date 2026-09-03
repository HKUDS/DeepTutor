"use client";

import { useEffect, useRef, useState } from "react";

import {
  SETTINGS_ANCHOR_EVENT,
  scrollToSettingsSection,
  type SettingsAnchorEvent,
} from "@/features/settings/navigation/settings-scroll";
import { useSettings } from "@/features/settings/store/SettingsStore";

export type CategorySection = {
  key: string;
  Component: React.ComponentType;
  /** Descendant anchors that require this parent section to be mounted. */
  activationKeys?: readonly string[];
};

function DeferredSectionContent({
  section,
  defer,
}: {
  section: CategorySection;
  defer: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [mounted, setMounted] = useState(!defer);

  useEffect(() => {
    if (mounted || !defer) return;
    const element = containerRef.current;
    if (!element) return;

    const activationKeys = new Set([
      section.key,
      ...(section.activationKeys ?? []),
    ]);
    const mountForAnchor = (requested: string) => {
      if (activationKeys.has(requested)) setMounted(true);
    };
    const applyLocationHash = () => {
      mountForAnchor(window.location.hash.replace(/^#/, ""));
    };
    const applyRequestedAnchor = (event: Event) => {
      mountForAnchor((event as SettingsAnchorEvent).detail?.key ?? "");
    };

    applyLocationHash();
    window.addEventListener("hashchange", applyLocationHash);
    window.addEventListener(SETTINGS_ANCHOR_EVENT, applyRequestedAnchor);

    const observer =
      typeof IntersectionObserver === "undefined"
        ? null
        : new IntersectionObserver(
            (entries) => {
              if (entries.some((entry) => entry.isIntersecting)) {
                setMounted(true);
              }
            },
            {
              root: element.closest<HTMLElement>("[data-settings-scroll]"),
              // Fetch the next section before it enters the viewport so normal
              // scrolling does not reveal a loading gap.
              rootMargin: "800px 0px",
            },
          );
    let fallbackFrame: number | null = null;
    if (observer) observer.observe(element);
    else {
      // Older embedded browsers may not expose IntersectionObserver. Defer
      // the compatibility mount so the effect itself stays state-free.
      fallbackFrame = window.requestAnimationFrame(() => setMounted(true));
    }

    return () => {
      observer?.disconnect();
      if (fallbackFrame !== null) window.cancelAnimationFrame(fallbackFrame);
      window.removeEventListener("hashchange", applyLocationHash);
      window.removeEventListener(SETTINGS_ANCHOR_EVENT, applyRequestedAnchor);
    };
  }, [defer, mounted, section.activationKeys, section.key]);

  const Component = section.Component;
  return (
    <div
      ref={containerRef}
      data-settings-deferred={defer && !mounted ? "true" : undefined}
      aria-busy={defer && !mounted ? "true" : undefined}
      className={defer && !mounted ? "min-h-80" : undefined}
    >
      {mounted ? <Component /> : null}
    </div>
  );
}

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
export function CategoryScroll({
  sections,
  deferSections = false,
}: {
  sections: CategorySection[];
  deferSections?: boolean;
}) {
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
      const requestedIsRendered = Boolean(
        requestedElement && rootElement.contains(requestedElement),
      );
      const requestedIsKnown = sections.some(
        (section) =>
          section.key === requested ||
          section.activationKeys?.includes(requested),
      );
      const validRequested = requestedIsRendered || requestedIsKnown;
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
      {sections.map((section, index) => (
        <section
          key={section.key}
          id={section.key}
          data-settings-section
          className={
            index === 0
              ? "scroll-mt-16"
              : "mt-12 scroll-mt-16 border-t border-[var(--border)]/60 pt-12"
          }
        >
          <DeferredSectionContent
            section={section}
            defer={deferSections && index > 0}
          />
        </section>
      ))}
    </div>
  );
}
