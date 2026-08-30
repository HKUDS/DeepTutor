"use client";

import { useEffect, useRef } from "react";

import { useSettings } from "./SettingsContext";

export type CategorySection = {
  key: string;
  Component: React.ComponentType;
};

/**
 * The content side of a merged settings category (Models, Chat, Partners &
 * Agents): every leaf's page component stacked in one scrollable document
 * instead of one route per leaf, so browsing the whole category is a scroll
 * instead of N page loads.
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

  // One-time: jump to the hash anchor (if any) once the section list has
  // painted, and tell the nav which leaf is on screen.
  useEffect(() => {
    const requested = window.location.hash.replace(/^#/, "");
    const initial =
      sections.find((s) => s.key === requested)?.key ??
      sections[0]?.key ??
      null;
    setActiveSection(initial);
    if (requested && requested !== sections[0]?.key) {
      requestAnimationFrame(() => {
        document
          .getElementById(requested)
          ?.scrollIntoView({ behavior: "auto", block: "start" });
      });
    }
    return () => setActiveSection(null);
    // Anchor handling only matters on mount — re-running it on every
    // `sections` identity change would re-jump the scroll position.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const root = rootRef.current?.closest<HTMLElement>(
      "[data-settings-scroll]",
    );
    if (!root) return;

    let ticking = false;
    const measure = () => {
      ticking = false;
      const threshold = root.getBoundingClientRect().top + 96;
      let current = sections[0]?.key ?? null;
      for (const { key } of sections) {
        const el = document.getElementById(key);
        if (el && el.getBoundingClientRect().top <= threshold) current = key;
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
    return () => root.removeEventListener("scroll", onScroll);
  }, [sections, setActiveSection]);

  return (
    <div ref={rootRef}>
      {sections.map(({ key, Component }, index) => (
        <section
          key={key}
          id={key}
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
