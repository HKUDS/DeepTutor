"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { fetchMediaJob } from "@/lib/media-api";
import { mergeImageJobRefs } from "@/lib/media-job-card";
import type { MediaJobCard } from "@/lib/media-types";
import type { StreamEvent } from "@/lib/unified-ws";
import ImageJobCard from "./ImageJobCard";

/**
 * Additive chat hook (§13.4): renders an image-job card for every ``image_job``
 * reference carried by the message attachments/events, and restores each card
 * from the durable job state after a refresh.
 */
export function InlineImageJobs({
  attachments,
  events,
  onError,
}: {
  attachments: Array<{ type?: string; id?: string; job_id?: unknown }>;
  events?: StreamEvent[];
  onError?: (message: string) => void;
}) {
  const { t } = useTranslation();
  const refs = useMemo(
    () => mergeImageJobRefs(attachments as Parameters<typeof mergeImageJobRefs>[0], events),
    [attachments, events],
  );
  const [jobs, setJobs] = useState<Record<string, MediaJobCard>>({});
  const [failed, setFailed] = useState<Record<string, boolean>>({});

  // Restore each job card from durable state (page refresh / initial mount).
  useEffect(() => {
    let cancelled = false;
    void Promise.all(
      refs.map(async (ref) => {
        try {
          const job = await fetchMediaJob(ref.job_id);
          if (!cancelled) {
            setJobs((prev) => ({ ...prev, [ref.job_id]: job }));
            setFailed((prev) => ({ ...prev, [ref.job_id]: false }));
          }
        } catch {
          if (!cancelled) {
            setFailed((prev) => ({ ...prev, [ref.job_id]: true }));
          }
        }
      }),
    );
    return () => {
      cancelled = true;
    };
  }, [refs]);

  if (refs.length === 0) return null;

  return (
    <div className="mt-3 flex flex-col gap-2" data-inline-image-jobs="">
      {refs.map((ref) => {
        if (failed[ref.job_id] && !jobs[ref.job_id]) {
          return (
            <div
              key={ref.job_id}
              className="max-w-[min(560px,100%)] rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-[12px] text-[var(--muted-foreground)]"
            >
              {t("media.job_unavailable")}
            </div>
          );
        }
        if (jobs[ref.job_id]) {
          return (
            <ImageJobCard
              key={ref.job_id}
              job={jobs[ref.job_id]}
              onChanged={(fresh) =>
                setJobs((prev) => ({ ...prev, [fresh.id]: fresh }))
              }
              onError={onError}
            />
          );
        }
        // First paint before the durable fetch resolves: stable-dimension card.
        return (
          <div
            key={ref.job_id}
            className="flex h-16 max-w-[min(560px,100%)] items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 text-[12px] text-[var(--muted-foreground)]"
          >
            <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-sky-500/70" />
            {t("media.loading_job")}
          </div>
        );
      })}
    </div>
  );
}

export default InlineImageJobs;
