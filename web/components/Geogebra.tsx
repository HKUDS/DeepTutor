"use client";

import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

interface GeogebraProps {
  script: string;
  title?: string;
  className?: string;
  width?: number;
  height?: number;
}

declare global {
  interface Window {
    GGBApplet?: new (
      params: Record<string, unknown>,
      html5: boolean,
    ) => {
      inject: (containerId: string) => void;
    };
  }
}

const GGB_SCRIPT_SRC = "https://www.geogebra.org/apps/deployggb.js";

// Single in-flight loader shared by every Geogebra instance on the page.
// deployggb.js is ~MB and lives on geogebra.org's CDN; fetching it once and
// reusing window.GGBApplet keeps subsequent applets snappy.
let ggbLoader: Promise<void> | null = null;

function loadGgbScript(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("window unavailable"));
  }
  if (window.GGBApplet) return Promise.resolve();
  if (ggbLoader) return ggbLoader;

  ggbLoader = new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src="${GGB_SCRIPT_SRC}"]`,
    );
    if (existing) {
      if (window.GGBApplet) {
        resolve();
        return;
      }
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => {
        ggbLoader = null;
        reject(new Error("GeoGebra script failed to load"));
      });
      return;
    }
    const script = document.createElement("script");
    script.src = GGB_SCRIPT_SRC;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      ggbLoader = null;
      reject(new Error("GeoGebra script failed to load"));
    };
    document.head.appendChild(script);
  });

  return ggbLoader;
}

// The agent emits one command per line and prefixes human-readable
// descriptions with `#`. evalCommand only takes one command at a time, so we
// strip comments + empty lines and feed the rest sequentially.
function parseGgbCommands(raw: string): string[] {
  return raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0 && !line.startsWith("#"));
}

let containerCounter = 0;

const Geogebra: React.FC<GeogebraProps> = ({
  script,
  title,
  className = "",
  width = 760,
  height = 480,
}) => {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const containerIdRef = useRef<string>(
    `ggb-${++containerCounter}-${Date.now().toString(36)}`,
  );
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    // Snapshot the ref now so the cleanup closure sees the same node React
    // mounted with, not whatever the ref points at after a later re-render.
    const containerAtMount = containerRef.current;
    setLoading(true);
    setError(null);

    async function mount() {
      try {
        await loadGgbScript();
        if (cancelled) return;
        if (!window.GGBApplet) {
          throw new Error("GGBApplet global missing after script load");
        }

        const commands = parseGgbCommands(script);
        const container = containerRef.current;
        if (!container) return;
        container.id = containerIdRef.current;
        container.innerHTML = "";

        const applet = new window.GGBApplet(
          {
            appName: "geometry",
            width,
            height,
            showToolBar: false,
            showAlgebraInput: false,
            showMenuBar: false,
            showResetIcon: true,
            enableLabelDrags: false,
            enableShiftDragZoom: true,
            useBrowserForJS: false,
            // The api passed in here lets us drive the applet
            // imperatively without going through a global. We feed each
            // command separately so one bad line doesn't abort the rest.
            appletOnLoad: (api: { evalCommand: (cmd: string) => boolean }) => {
              if (cancelled) return;
              for (const cmd of commands) {
                try {
                  api.evalCommand(cmd);
                } catch (err) {
                  console.warn("[ggb] evalCommand failed", { cmd, err });
                }
              }
              setLoading(false);
            },
          },
          true,
        );

        applet.inject(containerIdRef.current);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      }
    }

    void mount();

    return () => {
      cancelled = true;
      if (containerAtMount) {
        containerAtMount.innerHTML = "";
      }
    };
  }, [script, width, height]);

  return (
    <div
      className={`my-4 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] ${className}`}
    >
      {title ? (
        <div className="border-b border-[var(--border)] px-3 py-2 text-sm font-medium text-[var(--foreground)]">
          {title}
        </div>
      ) : null}
      {error ? (
        <div className="p-4 text-sm text-[var(--destructive,#dc2626)]">
          {t("Failed to load GeoGebra")}: {error}
        </div>
      ) : (
        <div className="relative" style={{ minHeight: height }}>
          {loading ? (
            <div className="absolute inset-0 flex items-center justify-center text-sm text-[var(--muted-foreground)]">
              {t("Loading GeoGebra...")}
            </div>
          ) : null}
          <div ref={containerRef} className="ggb-applet-container" />
        </div>
      )}
    </div>
  );
};

export default Geogebra;
