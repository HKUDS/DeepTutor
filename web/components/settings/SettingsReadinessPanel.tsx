"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Check, Loader2, RefreshCcw } from "lucide-react";
import { useTranslation } from "react-i18next";

import ProviderIcon from "@/components/common/ProviderIcon";
import { settingsAnchorHref } from "@/features/settings/navigation/settings-nav";
import {
  currentDiagnosticsResult,
  getActiveModel,
  getActiveProfile,
  useSettings,
  type Catalog,
  type DiagnosticsResult,
  type ServiceName,
} from "@/features/settings/store/SettingsStore";
import {
  EXPLAINED_DETAIL_CODES,
  fetchSettingsReadiness,
  groupReadinessRows,
  isProminentReadinessRow,
  readinessRowHref,
  readinessRowSeverity,
  type ReadinessSeverity,
  type ReadinessState,
  type SettingsReadinessRow,
  type SettingsReadinessSnapshot,
} from "@/lib/settings-readiness";

/** Colored text, not a filled pill: 26 green badges is a wall, not a report. */
const STATE_TONES: Record<ReadinessState, string> = {
  enabled_verified: "text-emerald-600 dark:text-emerald-400",
  available_disabled: "text-[var(--muted-foreground)]",
  unavailable: "text-[var(--muted-foreground)] opacity-60",
  misconfigured: "text-amber-600 dark:text-amber-400",
  not_selected: "text-[var(--muted-foreground)] opacity-60",
};

const SEVERITY_TONES: Record<ReadinessSeverity, string> = {
  blocker: "text-amber-700 dark:text-amber-300",
  warning: "text-amber-600 dark:text-amber-400",
  suggestion: "text-[var(--muted-foreground)]",
};

const CATALOG_SERVICES = new Set<string>([
  "llm",
  "task",
  "embedding",
  "search",
  "tts",
  "stt",
  "imagegen",
  "videogen",
]);

type PanelRow = SettingsReadinessRow & {
  href: string | null;
  /** The model (or search provider) this row currently resolves to. */
  model: string;
  /** Provider key for the glyph beside the model. */
  provider: string;
};

/**
 * Join a server row with what this browser knows.
 *
 * The server deliberately reports no model names, and it cannot see the
 * connection tests run from this page — so a service it calls verified may
 * have failed its last test right here. Both facts belong on the same row.
 */
function refineRow(
  row: SettingsReadinessRow,
  catalog: Catalog,
  diagnosticsResults: Partial<Record<ServiceName, DiagnosticsResult>>,
): PanelRow {
  const refined: PanelRow = {
    ...row,
    href: readinessRowHref(row.id),
    model: "",
    provider: "",
  };
  if (!row.id.startsWith("catalog.")) return refined;
  const name = row.id.slice("catalog.".length);
  if (!CATALOG_SERVICES.has(name)) return refined;

  const service = name as ServiceName;
  const profile = getActiveProfile(catalog, service);
  refined.provider =
    (service === "search" ? profile?.provider : profile?.binding) ?? "";
  refined.model =
    service === "search"
      ? (profile?.provider ?? "")
      : (getActiveModel(catalog, service)?.model ?? "");
  if (
    currentDiagnosticsResult(catalog, service, diagnosticsResults)?.state ===
    "failed"
  ) {
    refined.state = "misconfigured";
    refined.detail_code = "connection_test_failed";
  }
  return refined;
}

/**
 * What the current settings can actually run.
 *
 * This is the settings hub's one status module: it absorbed the old "needs
 * attention" and "model services" lists, so a service's model, its last test
 * result, and whether anything downstream depends on it are read off one row.
 *
 * The rule it is built on: optional capabilities are optional. DeepTutor ships
 * with speech, image, and video services unset and their tools switched on —
 * flagging that as a fault trains people to ignore the whole panel. Only a
 * capability the install needs, or one that was configured and now fails, is
 * allowed to raise its voice.
 */
export default function SettingsReadinessPanel({
  enabled,
}: {
  enabled: boolean;
}) {
  const { t } = useTranslation();
  const { catalog, diagnosticsResults, draftState } = useSettings();
  const [snapshot, setSnapshot] = useState<SettingsReadinessSnapshot | null>(
    null,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    setError(false);
    try {
      setSnapshot(await fetchSettingsReadiness());
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const rows = useMemo(
    () =>
      (snapshot?.rows ?? []).map((row) =>
        refineRow(row, catalog, diagnosticsResults),
      ),
    [snapshot, catalog, diagnosticsResults],
  );
  const groups = useMemo(() => groupReadinessRows(rows), [rows]);

  // Everything worth acting on, most urgent first: what the install needs,
  // what broke, the draft nobody applied, and finally the purely advisory.
  const attention = useMemo(() => {
    const items: {
      key: string;
      severity: ReadinessSeverity;
      label: string;
      detail: string;
      href: string | null;
    }[] = [];
    for (const row of rows) {
      const severity = readinessRowSeverity(row);
      if (!severity) continue;
      items.push({
        key: row.id,
        severity,
        label: t(row.label),
        detail: detailText(t, row.detail_code),
        href: row.href,
      });
    }
    items.sort((left, right) =>
      left.severity === right.severity ? 0 : left.severity === "blocker" ? -1 : 1,
    );
    if (draftState !== "clean") {
      items.push({
        key: "draft",
        severity: "warning",
        label: t("readiness.attention.draft"),
        detail:
          draftState === "saved"
            ? t("readiness.attention.draftSaved")
            : t("readiness.attention.draftUnsaved"),
        href: settingsAnchorHref("llm"),
      });
    }
    for (const notice of snapshot?.notices ?? []) {
      if (notice.severity !== "suggestion") continue;
      const row = rows.find((item) => item.id === notice.row_id);
      items.push({
        key: `${notice.code}:${notice.row_id}`,
        severity: "suggestion",
        label: row ? t(row.label) : t(`readiness.section.${notice.section}`),
        detail: detailText(t, notice.code),
        href: row?.href ?? null,
      });
    }
    return items;
  }, [rows, snapshot, draftState, t]);

  if (!enabled) return null;

  const summary = snapshot
    ? [
        t("readiness.summary.ready", { n: snapshot.summary.enabled_verified }),
        snapshot.summary.available_disabled > 0 &&
          t("readiness.summary.available", {
            n: snapshot.summary.available_disabled,
          }),
        snapshot.summary.unavailable + snapshot.summary.not_selected > 0 &&
          t("readiness.summary.idle", {
            n: snapshot.summary.unavailable + snapshot.summary.not_selected,
          }),
      ]
        .filter(Boolean)
        .join(" · ")
    : t("readiness.blurb");

  return (
    <section className="mt-8" aria-labelledby="capability-readiness-title">
      <header className="mb-2 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2
            id="capability-readiness-title"
            className="text-[15px] font-semibold tracking-tight text-[var(--foreground)]"
          >
            {t("readiness.title")}
          </h2>
          <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
            {summary}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading}
          aria-label={t("readiness.refresh")}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-[11.5px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] disabled:opacity-50"
        >
          {loading ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <RefreshCcw className="h-3 w-3" />
          )}
          {t("readiness.refresh")}
        </button>
      </header>

      <div className="border-t border-[var(--border)]/60">
        {error && (
          <p role="alert" className="py-3 text-[12.5px] text-amber-600">
            {t("readiness.error")}
          </p>
        )}

        {!snapshot && !error && (
          <p className="flex items-center gap-2 py-3 text-[12.5px] text-[var(--muted-foreground)]">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {t("readiness.loading")}
          </p>
        )}

        {snapshot && (
          <>
            {/* Named like every group below it, so the one row that repeats
                here and in its own group reads as a summary rather than as
                the same line printed twice. */}
            <h3 className="pt-3 pb-1 text-[12px] font-medium text-[var(--muted-foreground)]">
              {t("readiness.attention.title")}
            </h3>
            {attention.length === 0 ? (
              <p className="flex items-center gap-2 border-t border-[var(--border)]/50 py-2.5 text-[12.5px] text-[var(--muted-foreground)]">
                <Check className="h-3.5 w-3.5 text-emerald-500" />
                {t("readiness.attention.none")}
              </p>
            ) : (
              <ul className="border-t border-[var(--border)]/50">
                {attention.map((item) => (
                  <li
                    key={item.key}
                    className="flex flex-wrap items-center justify-between gap-x-4 gap-y-0.5 border-b border-[var(--border)]/50 py-2.5"
                  >
                    <span className="min-w-0 text-[12.5px] text-[var(--foreground)]">
                      <span className={SEVERITY_TONES[item.severity]}>
                        {item.label}
                      </span>
                      {/* A code with no sentence must not leave a dangling
                          separator behind — the label stands on its own. */}
                      {item.detail && (
                        <span className="text-[var(--muted-foreground)]">
                          {" · "}
                          {item.detail}
                        </span>
                      )}
                    </span>
                    {item.href && (
                      <Link
                        href={item.href}
                        className="inline-flex items-center gap-1 text-[11.5px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
                      >
                        {t("readiness.attention.open")}
                        <ArrowUpRight className="h-3 w-3" />
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            )}

            <div data-testid="settings-readiness-matrix">
              {groups.map(([section, sectionRows]) => (
                <ReadinessGroup
                  key={section}
                  section={section}
                  rows={sectionRows}
                />
              ))}
            </div>
          </>
        )}
      </div>
    </section>
  );
}

function detailText(t: (key: string) => string, code: string): string {
  return EXPLAINED_DETAIL_CODES.has(code) ? t(`readiness.detail.${code}`) : "";
}

function ReadinessGroup({
  section,
  rows,
}: {
  section: string;
  rows: PanelRow[];
}) {
  const { t } = useTranslation();
  const prominent = rows.filter(isProminentReadinessRow);
  const folded = rows.filter((row) => !isProminentReadinessRow(row));
  const ready = rows.filter((row) => row.state === "enabled_verified").length;

  return (
    <div className="pt-4">
      <div className="flex items-baseline justify-between gap-3 pb-1">
        <h3 className="text-[12px] font-medium text-[var(--muted-foreground)]">
          {t(`readiness.section.${section}`)}
        </h3>
        {ready > 0 && (
          <span className="text-[11px] text-[var(--muted-foreground)] opacity-70">
            {t("readiness.group.ready", { n: ready })}
          </span>
        )}
      </div>
      <ul className="border-t border-[var(--border)]/50">
        {prominent.map((row) => (
          <ReadinessRow key={row.id} row={row} />
        ))}
      </ul>
      {folded.length > 0 && (
        // Optional capabilities nobody turned on: one line away, never in the
        // way. Native disclosure — no state, no animation, keyboard-operable.
        <details className="group">
          <summary className="cursor-pointer list-none py-2 text-[11.5px] text-[var(--muted-foreground)] transition-colors marker:content-none hover:text-[var(--foreground)]">
            {t("readiness.group.folded", { n: folded.length })}
          </summary>
          <ul className="border-t border-[var(--border)]/50 pb-1">
            {folded.map((row) => (
              <ReadinessRow key={row.id} row={row} />
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function ReadinessRow({ row }: { row: PanelRow }) {
  const { t } = useTranslation();
  const severity = readinessRowSeverity(row);
  const detail = row.state === "enabled_verified" ? "" : detailText(t, row.detail_code);
  const label = t(row.label);

  return (
    <li className="flex flex-wrap items-center justify-between gap-x-3 gap-y-0.5 border-b border-[var(--border)]/40 py-2">
      <span className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
        {row.href ? (
          <Link
            href={row.href}
            className="text-[12.5px] text-[var(--foreground)] transition-opacity hover:opacity-70"
          >
            {label}
          </Link>
        ) : (
          <span className="text-[12.5px] text-[var(--foreground)]">
            {label}
          </span>
        )}
        {detail && (
          <span className="text-[11.5px] text-[var(--muted-foreground)]">
            {detail}
          </span>
        )}
      </span>
      <span className="flex min-w-0 items-center gap-2">
        {row.model && (
          <span className="flex min-w-0 items-center gap-1.5">
            {row.provider && <ProviderIcon provider={row.provider} size={12} />}
            <span className="truncate font-mono text-[11px] text-[var(--muted-foreground)]">
              {row.model}
            </span>
          </span>
        )}
        <span
          className={`shrink-0 text-[11px] ${
            severity ? SEVERITY_TONES[severity] : STATE_TONES[row.state]
          }`}
        >
          {t(`readiness.state.${row.state}`)}
        </span>
      </span>
    </li>
  );
}
