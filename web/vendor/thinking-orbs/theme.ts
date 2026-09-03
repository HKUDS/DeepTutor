// Theme resolution: explicit prop → ancestor data-theme/.dark|.light
// class (watched live) → prefers-color-scheme (subscribed live).
// SSR-safe: everything runs in effects; the pre-mount fallback is dark.

import type { RefObject } from 'react';
import { useEffect, useState } from 'react';
import type { Tint } from './engine/core';
import type { OrbTheme } from './types';

function ancestorTheme(el: Element | null): boolean | null {
  let node: Element | null = el;
  while (node) {
    const attr = node.getAttribute('data-theme');
    if (attr === 'dark') return true;
    if (attr === 'light') return false;
    if (node.classList.contains('dark')) return true;
    if (node.classList.contains('light')) return false;
    node = node.parentElement;
  }
  return null;
}

function systemDark(): boolean {
  return typeof matchMedia === 'undefined' || matchMedia('(prefers-color-scheme: dark)').matches;
}

/** Resolve the effective dark/light substrate for a mounted element. */
export function useResolvedDark(theme: OrbTheme, hostRef: RefObject<Element | null>): boolean {
  const [dark, setDark] = useState(true);

  useEffect(() => {
    if (theme === 'dark') {
      setDark(true);
      return;
    }
    if (theme === 'light') {
      setDark(false);
      return;
    }

    const resolve = () => {
      const fromTree = ancestorTheme(hostRef.current);
      setDark(fromTree ?? systemDark());
    };
    resolve();

    // live OS/browser theme switches
    const mq = typeof matchMedia !== 'undefined' ? matchMedia('(prefers-color-scheme: dark)') : null;
    const onMq = () => resolve();
    mq?.addEventListener('change', onMq);

    // live app-level toggles: watch class/data-theme flips on ancestors
    let mo: MutationObserver | null = null;
    if (typeof MutationObserver !== 'undefined' && hostRef.current) {
      mo = new MutationObserver(resolve);
      mo.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['class', 'data-theme'],
        subtree: true
      });
    }

    return () => {
      mq?.removeEventListener('change', onMq);
      mo?.disconnect();
    };
  }, [theme, hostRef]);

  return dark;
}

/**
 * DeepTutor local addition: parse a computed CSS colour into a paintable
 * tint. Returns `undefined` for anything that is not plain `rgb()`/`rgba()`
 * — a wide-gamut or `color-mix()` value falls back to upstream's greyscale
 * rather than guessing.
 */
export function parseTint(color: string | undefined): Tint | undefined {
  if (!color) return undefined;
  const m = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/.exec(color);
  if (!m) return undefined;
  return { r: Number(m[1]), g: Number(m[2]), b: Number(m[3]) };
}

/**
 * DeepTutor local addition: the host element's live `currentColor`, as a raw
 * computed-style string.
 *
 * Returned as a string, not a parsed `Tint`, so callers can key an effect on
 * it — a fresh object every read would re-run the render loop every frame.
 *
 * Read from computed style rather than taken as a prop so the orb simply
 * inherits the colour of the row it sits in, and re-read on the same
 * class/`data-theme` mutations `useResolvedDark` watches: two of DeepTutor's
 * four themes are both "dark" substrates but carry different brand hues, so
 * a dark→dark switch changes the ink without changing `dark`.
 */
export function useResolvedInk(hostRef: RefObject<Element | null>): string | undefined {
  const [ink, setInk] = useState<string | undefined>(undefined);

  useEffect(() => {
    const el = hostRef.current;
    if (!el || typeof getComputedStyle === 'undefined') return;

    const read = () => setInk(getComputedStyle(el).color || undefined);
    read();

    let mo: MutationObserver | null = null;
    if (typeof MutationObserver !== 'undefined') {
      mo = new MutationObserver(read);
      mo.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['class', 'data-theme'],
        subtree: true
      });
    }

    return () => mo?.disconnect();
  }, [hostRef]);

  return ink;
}

/** Live `prefers-reduced-motion` — reduced users get a static frame. */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    if (typeof matchMedia === 'undefined') return;
    const mq = matchMedia('(prefers-reduced-motion: reduce)');
    setReduced(mq.matches);
    const on = (e: MediaQueryListEvent) => setReduced(e.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);
  return reduced;
}
