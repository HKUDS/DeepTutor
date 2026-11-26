"use client";

import { useSyncExternalStore, type ReactNode } from "react";
import { apiUrl } from "@/lib/api";
import { clientEdition } from "@/lib/version";

const subscribe = () => () => {};
const isWindowsDesktop = () => clientEdition().short === "Windows";

// The desktop edition comes from the browser's user agent after hydration.
export function useWindowsDesktop(): boolean {
  return useSyncExternalStore(subscribe, isWindowsDesktop, () => false);
}

export function isRelativeFileReference(href: string): boolean {
  return !/^(?:[a-z][a-z\d+.-]*:|\/|#|\?)/i.test(href)
    && /\.[a-z\d]{1,8}(?:[?#].*)?$/i.test(href);
}

/** Only published session files have a URL the desktop shell can resolve on disk. */
export function sessionFileUrl(url?: string | null): string | null {
  if (!url || !(url.startsWith("/files/") || /^https?:\/\//i.test(url))) return null;
  const origin = typeof window === "undefined" ? "http://workspace.local" : window.location.origin;
  if (!URL.canParse(url, origin)) return null;
  const parsed = new URL(url, origin);
  if (
    parsed.origin !== origin || parsed.username || parsed.password ||
    !/^\/files\/(?:attachments\/[^/]+\/[^/]+\/[^/]+|workspace-items\/[^/]+\/[^/]+|outputs\/.+)$/.test(parsed.pathname)
  ) {
    return null;
  }
  return apiUrl(parsed.pathname + parsed.search);
}

export function SessionFileLink({
  url, onClick, children, ...props
}: {
  url?: string;
  onClick?: () => void;
  children: ReactNode;
  className: string;
  "aria-label"?: string;
}) {
  const href = useWindowsDesktop() ? sessionFileUrl(url) : null;
  if (href && onClick) {
    return (
      <a
        {...props}
        href={href}
        onClick={(event) => {
          event.preventDefault();
          onClick();
        }}
      >
        {children}
      </a>
    );
  }
  return (
    <button {...props} type="button" onClick={onClick}>
      {children}
    </button>
  );
}
