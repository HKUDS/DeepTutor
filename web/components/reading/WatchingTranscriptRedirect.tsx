"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { LoaderCircle } from "lucide-react";
import { useTranslation } from "react-i18next";

import { importReadingUrls } from "@/lib/reading-workspace-api";
import { READING_HOME, readingCollectionRoute } from "@/lib/learning-routes";

export default function WatchingTranscriptRedirect({
  sourceUrl,
  title,
}: {
  sourceUrl: string;
  title: string;
}) {
  const router = useRouter();
  const { t } = useTranslation();
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    void importReadingUrls({
      urls: [sourceUrl],
      workspace_title: `${title} transcript`,
    })
      .then(({ workspace }) => {
        if (!cancelled && workspace?.workspace_id) {
          router.replace(readingCollectionRoute(workspace.workspace_id));
        }
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(
            caught instanceof Error
              ? caught.message
              : t("Could not open this video transcript."),
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [router, sourceUrl, t, title]);

  return (
    <main className="flex h-full flex-col items-center justify-center gap-3 bg-[var(--background)] px-6 text-center text-[var(--foreground)]">
      {error ? (
        <>
          <p role="alert" className="text-sm">{error}</p>
          <a
            href={sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-[var(--primary)] underline"
          >
            {t("Open video on YouTube")}
          </a>
          <Link href={READING_HOME} className="text-xs text-[var(--muted-foreground)]">
            {t("Back to Immersive Reading")}
          </Link>
        </>
      ) : (
        <>
          <LoaderCircle size={20} className="animate-spin text-[var(--primary)]" />
          <p className="text-sm">{t("Preparing the transcript workspace…")}</p>
        </>
      )}
    </main>
  );
}
