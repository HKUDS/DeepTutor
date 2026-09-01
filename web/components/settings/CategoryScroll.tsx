"use client";

import { useEffect, useRef } from "react";

import { useSettings } from "./SettingsContext";

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

    const requested = window.location.hash.replace(/^#/, "");
    const requestedElement = requested
      ? document.getElementById(requested)
      : null;
    const initial =
      requestedElement && rootElement.contains(requestedElement)
        ? requested
        : (sections[0]?.key ?? null);
    setActiveSection(initial);
    if (requestedElement && requested !== sections[0]?.key) {
      requestAnimationFrame(() => {
        requestedElement.scrollIntoView({ behavior: "auto", block: "start" });
      });
    }
    return () => setActiveSection(null);
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
