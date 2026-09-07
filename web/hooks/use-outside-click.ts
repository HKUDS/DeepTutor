import { type RefObject, useEffect, useRef } from "react";

/**
 * Run *onOutside* when a mousedown lands outside *ref*, while *enabled*.
 *
 * Four composer dropdowns each carried this effect verbatim, each with the
 * same lint suppression for leaving its close handler out of the deps. The
 * handler is held in a ref here instead, so the listener is attached exactly
 * once per open — which is what those suppressions were preserving.
 */
export function useOutsideClick(
  ref: RefObject<HTMLElement | null>,
  enabled: boolean,
  onOutside: () => void,
): void {
  const handlerRef = useRef(onOutside);
  useEffect(() => {
    handlerRef.current = onOutside;
  });
  useEffect(() => {
    if (!enabled) return;
    const handler = (event: MouseEvent) => {
      const target = event.target as Node;
      if (ref.current && !ref.current.contains(target)) handlerRef.current();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [enabled, ref]);
}
