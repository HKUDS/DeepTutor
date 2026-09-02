"use client";

import { RefreshCw, ServerCog } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  Button,
  InlineAlert,
  Skeleton,
  StatusChip,
  type StatusTone,
} from "@/shared/ui";
import type { RuntimeHealth, RuntimeStatusSnapshot } from "./model";

export interface RuntimeHealthCardProps {
  snapshot: RuntimeStatusSnapshot;
  onRefresh?: () => void | Promise<void>;
  showDetails?: boolean;
  compact?: boolean;
}

const tone: Record<RuntimeHealth, StatusTone> = {
  healthy: "success",
  degraded: "warning",
  recovering: "warning",
  unavailable: "danger",
};

export function RuntimeHealthCard({
  snapshot,
  onRefresh,
  showDetails = false,
  compact = false,
}: RuntimeHealthCardProps) {
  const { t } = useTranslation();
  const label = {
    healthy: t("Healthy"),
    degraded: t("Degraded"),
    recovering: t("Recovering"),
    unavailable: t("Unavailable"),
  }[snapshot.health];

  if (snapshot.loading && !snapshot.data) {
    return compact ? (
      <Skeleton className="h-6 w-28" />
    ) : (
      <Skeleton className="h-36 w-full" />
    );
  }

  if (compact) {
    return (
      <div className="flex items-center gap-2">
        <span className="text-[13px] font-medium text-foreground">
          {t("Turn runtime")}
        </span>
        <StatusChip tone={tone[snapshot.health]}>{label}</StatusChip>
      </div>
    );
  }

  const status = snapshot.data;
  return (
    <section
      className="rounded-2xl border border-border bg-card p-5 shadow-sm"
      aria-labelledby="runtime-health-title"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-muted text-muted-foreground">
            <ServerCog aria-hidden className="h-5 w-5" />
          </span>
          <div>
            <div className="flex items-center gap-2">
              <h2
                id="runtime-health-title"
                className="text-sm font-semibold text-foreground"
              >
                {t("Turn runtime")}
              </h2>
              <StatusChip tone={tone[snapshot.health]}>{label}</StatusChip>
            </div>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              {healthDescription(snapshot.health, t)}
            </p>
          </div>
        </div>
        {onRefresh ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void onRefresh()}
            loading={snapshot.loading}
            icon={<RefreshCw aria-hidden className="h-4 w-4" />}
          >
            {t("Refresh")}
          </Button>
        ) : null}
      </div>

      {snapshot.error ? (
        <InlineAlert tone={status ? "warning" : "danger"} className="mt-4">
          {status
            ? t("The latest refresh failed. Showing the last safe snapshot.")
            : t("Runtime health could not be loaded.")}
        </InlineAlert>
      ) : null}

      {status && showDetails ? (
        <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-4 border-t border-border pt-4 md:grid-cols-4">
          <Metric label={t("Workers")} value={String(status.workerCount)} />
          <Metric
            label={t("Coordination")}
            value={
              status.coordinationMode === "redis" ? "Redis" : t("In process")
            }
          />
          <Metric
            label={t("Active owner turns")}
            value={String(status.ownerTurnCount)}
          />
          <Metric
            label={t("Recovery backlog")}
            value={String(status.recoveryBacklog)}
          />
          <Metric
            label={t("Redis")}
            value={redisLabel(status.redisStatus, t)}
          />
          <Metric
            label={t("Leader")}
            value={
              status.leaderHealthy === false
                ? t("Unhealthy")
                : status.leaderId || t("Not applicable")
            }
          />
          <Metric label={t("Protocol")} value={status.protocolVersion} />
          <Metric label={t("Worker ID")} value={status.workerId} />
        </dl>
      ) : null}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-medium text-muted-foreground">{label}</dt>
      <dd
        className="mt-1 truncate text-sm font-semibold text-foreground"
        title={value}
      >
        {value}
      </dd>
    </div>
  );
}

function redisLabel(
  status: "ok" | "unavailable" | "not_configured",
  t: (key: string) => string,
) {
  if (status === "ok") return t("Connected");
  if (status === "unavailable") return t("Unavailable");
  return t("Not configured");
}

function healthDescription(health: RuntimeHealth, t: (key: string) => string) {
  if (health === "healthy")
    return t("Turn ownership and recovery services are operating normally.");
  if (health === "recovering")
    return t("The runtime is reconciling interrupted work.");
  if (health === "degraded")
    return t("Turn coordination needs operator attention.");
  return t("The runtime status endpoint is not available.");
}
