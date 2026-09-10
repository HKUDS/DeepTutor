"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

/** Native preview for generated and workspace video files. */
export default function VideoPreview({
  url,
  filename,
}: {
  url: string;
  filename: string;
}) {
  const { t } = useTranslation();
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  return (
    <div className="relative flex h-full w-full items-center justify-center bg-black/95 p-3">
      {state === "loading" && (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-white/70" />
        </div>
      )}
      {state === "error" ? (
        <div className="text-[12px] text-white/70">
          {t("Failed to load video.")}
        </div>
      ) : (
        <video
          src={url}
          aria-label={filename}
          controls
          playsInline
          preload="metadata"
          className="max-h-full max-w-full rounded-md"
          onLoadedData={() => setState("ready")}
          onError={() => setState("error")}
        />
      )}
    </div>
  );
}
