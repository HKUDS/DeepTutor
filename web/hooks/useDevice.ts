"use client";

import { useSyncExternalStore } from "react";

/* Device classes for layout branching.
 *
 * The two thresholds deliberately mirror Tailwind's ``md`` (768px) and ``lg``
 * (1024px) so a component can express the *static* half of its responsive
 * behaviour in CSS (``max-md:fixed``, ``lg:flex-row``) and the *stateful* half
 * in JS (``useDevice()``) without the two ever disagreeing about which class is
 * active. Change a number here and you must change the Tailwind screen too.
 *
 *   mobile   < 768   phones, and anything narrow enough that a 220px sidebar
 *                    would eat the content column
 *   tablet   768—1023  iPad portrait: wide enough for one full column plus
 *                    chrome, too narrow for a side-by-side panel
 *   desktop  >= 1024 iPad landscape and up: the layout the app was built for
 */
export const DEVICE_BREAKPOINTS = {
  /** Below this width the sidebar becomes an overlay drawer. */
  tablet: 768,
  /** At/above this width side-by-side panels are affordable. */
  desktop: 1024,
} as const;

export type DeviceClass = "mobile" | "tablet" | "desktop";

export interface DeviceState {
  device: DeviceClass;
  isMobile: boolean;
  isTablet: boolean;
  isDesktop: boolean;
  /**
   * ``mobile || tablet`` — the "no room for a second column" test. Most panel
   * code cares about this rather than the exact class: below 1024px an overlay
   * that reserves 400px of width leaves nothing to overlay onto.
   */
  isCompact: boolean;
}

const MOBILE_QUERY = `(max-width: ${DEVICE_BREAKPOINTS.tablet - 1}px)`;
const DESKTOP_QUERY = `(min-width: ${DEVICE_BREAKPOINTS.desktop}px)`;

/* One MediaQueryList per query for the whole app. Every `useDevice()` caller
   subscribes to the same pair, so N components cost N listeners on 2 objects
   rather than N matchMedia registrations. Created lazily — module scope also
   runs on the server, where `window` is undefined. */
let cachedQueries: [MediaQueryList, MediaQueryList] | null = null;

function queries(): [MediaQueryList, MediaQueryList] | null {
  if (typeof window === "undefined" || !window.matchMedia) return null;
  if (!cachedQueries) {
    cachedQueries = [
      window.matchMedia(MOBILE_QUERY),
      window.matchMedia(DESKTOP_QUERY),
    ];
  }
  return cachedQueries;
}

function subscribe(onStoreChange: () => void): () => void {
  const qs = queries();
  if (!qs) return () => {};
  for (const q of qs) q.addEventListener("change", onStoreChange);
  return () => {
    for (const q of qs) q.removeEventListener("change", onStoreChange);
  };
}

function getSnapshot(): DeviceClass {
  const qs = queries();
  if (!qs) return "desktop";
  const [mobile, desktop] = qs;
  if (mobile.matches) return "mobile";
  return desktop.matches ? "desktop" : "tablet";
}

/* The server has no viewport. Rendering the desktop shell keeps SSR output
   identical to what it is today, so this hook can be adopted incrementally
   without changing a single server-rendered byte.

   That does mean JS briefly believes a phone is a desktop, between hydration
   and the first snapshot. Keep purely visual branching in CSS (`max-md:`) —
   it is correct on the very first paint — and reserve this hook for behaviour
   that has state anyway (is the drawer open, may this panel be drag-resized),
   where the pre-hydration value is unobservable. */
function getServerSnapshot(): DeviceClass {
  return "desktop";
}

/**
 * Current device class, re-rendering the caller when the viewport crosses a
 * breakpoint. See the note on `getServerSnapshot` for the CSS-vs-JS split.
 */
export function useDevice(): DeviceState {
  const device = useSyncExternalStore(
    subscribe,
    getSnapshot,
    getServerSnapshot,
  );
  return {
    device,
    isMobile: device === "mobile",
    isTablet: device === "tablet",
    isDesktop: device === "desktop",
    isCompact: device !== "desktop",
  };
}
