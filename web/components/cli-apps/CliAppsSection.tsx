"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  Download,
  ExternalLink,
  Loader2,
  Lock,
  RefreshCw,
  Search,
  ShieldCheck,
  Terminal,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import BrandIcon, { TrademarkNote } from "@/components/common/BrandIcon";
import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import { chipClass } from "@/components/mcp/styles";
import { useAuthStatus } from "@/hooks/useAuthStatus";
import {
  CliAppError,
  type CliApp,
  type CliAppState,
  type CliCatalogEntry,
  getCliApps,
  getCliCatalog,
  installCliApp,
  setCliAppEnabled,
  uninstallCliApp,
} from "@/lib/cli-apps-api";

const PAGE_SIZE = 12;

type Tab = "installed" | "store";

/**
 * CLI Apps — command-line tools the chat agent can call.
 *
 * The two tabs correspond to the two decisions the feature splits apart:
 * *installed* is what this account may use and can switch on or off for itself,
 * and *store* is what exists — where an administrator, and only an
 * administrator, installs. That asymmetry is not a UI choice: installing runs a
 * third-party `setup.py` in the application container, so a non-admin sees the
 * store read-only and the page says so rather than offering a button that 403s.
 */
export default function CliAppsSection() {
  const { t, i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const { isAdmin, loading: authLoading } = useAuthStatus();

  const [state, setState] = useState<CliAppState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("installed");

  // Runs once, and deliberately depends on nothing. There is no reload path
  // either — every mutation route answers with the full state, which the children
  // hand back through `setState`.
  //
  // `t` must stay out of the deps: react-i18next hands back a new `t` when its
  // store settles, so an effect keyed on it re-runs, and each re-run's cleanup
  // cancels the fetch the previous one started. The page then sits on its spinner
  // forever while the network tab shows a perfectly good 200. Which is why the
  // error is stored untranslated and rendered through `t` below.
  useEffect(() => {
    let cancelled = false;
    getCliApps()
      .then((next) => {
        if (!cancelled) setState(next);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(messageOf(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const apps = state?.apps ?? [];
  const usable = apps.filter((app) => app.granted && app.enabled).length;

  return (
    <div className="space-y-6">
      <SpaceSectionHeader
        icon={Terminal}
        title={t("CLI Apps")}
        description={t(
          "Command-line tools from the CLI-Anything catalog. Once enabled, the chat agent can call them directly.",
        )}
        meta={
          <span className="rounded-full border border-[var(--border)] bg-[var(--card)] px-2 py-0.5 text-[10.5px] font-medium text-[var(--muted-foreground)]">
            {t("{{count}} available to you", { count: usable })}
          </span>
        }
      />

      <div className="border-b border-[var(--border)]">
        <div className="flex gap-1">
          <TabButton
            label={t("Installed")}
            count={apps.length}
            active={tab === "installed"}
            onClick={() => setTab("installed")}
          />
          <TabButton
            label={t("Store")}
            active={tab === "store"}
            onClick={() => setTab("store")}
          />
        </div>
      </div>

      {loadError !== null && (
        <Banner tone="error">{loadError || t("Something went wrong.")}</Banner>
      )}

      {tab === "store" ? (
        <Store
          isAdmin={isAdmin}
          adminKnown={!authLoading}
          onChanged={setState}
        />
      ) : state === null && !loadError ? (
        <Spinner />
      ) : (
        <Installed
          state={state}
          isAdmin={isAdmin}
          zh={zh}
          onChanged={setState}
          onBrowse={() => setTab("store")}
        />
      )}
    </div>
  );
}

// ── installed ────────────────────────────────────────────────────────────

function Installed({
  state,
  isAdmin,
  zh,
  onChanged,
  onBrowse,
}: {
  state: CliAppState | null;
  isAdmin: boolean;
  zh: boolean;
  onChanged: (next: CliAppState) => void;
  onBrowse: () => void;
}) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const act = useCallback(
    async (appId: string, run: () => Promise<CliAppState>) => {
      setBusy(appId);
      setError(null);
      try {
        onChanged(await run());
      } catch (err) {
        setError(messageOf(err));
      } finally {
        setBusy(null);
      }
    },
    [onChanged],
  );

  const apps = state?.apps ?? [];
  if (apps.length === 0) {
    return (
      <Empty
        title={t("No CLI apps installed")}
        body={
          isAdmin
            ? t(
                "Browse the store to install one. Installing runs the app's own installer on this server, so it stays an administrator action.",
              )
            : t(
                "An administrator installs these, then assigns them to accounts. Browse the store to see what you could ask for by name.",
              )
        }
        action={
          <button type="button" onClick={onBrowse} className={secondaryButton}>
            {t("Browse the store")}
          </button>
        }
      />
    );
  }

  return (
    <div className="space-y-4">
      {error !== null && (
        <Banner tone="error">{error || t("Something went wrong.")}</Banner>
      )}
      {state?.access.exec_denied && (
        <Banner tone="warn">
          {t(
            "Your account cannot run code, so no CLI app is available to the chat agent — even the ones listed below.",
          )}
        </Banner>
      )}

      <ul className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)]">
        {apps.map((app, index) => (
          <li
            key={app.id}
            className={`px-5 py-4 ${index > 0 ? "border-t border-[var(--border)]/60" : ""}`}
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <BrandIcon
                namespace="cli"
                id={app.id}
                name={app.display_name}
                className="mt-0"
              />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[14px] font-semibold tracking-tight text-[var(--foreground)]">
                    {app.display_name}
                  </span>
                  <code className="rounded bg-[var(--muted)]/60 px-1.5 py-0.5 font-mono text-[11px] text-[var(--muted-foreground)]">
                    {app.tool_name}
                  </code>
                  <TrustChip trust={app.trust} pinned={Boolean(app.pin)} />
                  {!app.in_catalog && (
                    <span className={warnChip}>
                      <AlertTriangle size={9} />
                      {t("No longer in the catalog")}
                    </span>
                  )}
                </div>
                {app.description && (
                  <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
                    {app.description}
                  </p>
                )}
                <p className="mt-1.5 text-[11px] text-[var(--muted-foreground)]/80">
                  {app.installed_at
                    ? t("Installed {{when}}", {
                        when: formatDay(app.installed_at, zh),
                      })
                    : ""}
                  {app.pin ? ` · ${app.pin.slice(0, 12)}` : ""}
                </p>
                {!app.granted && (
                  <p className="mt-2 inline-flex items-center gap-1.5 text-[11.5px] text-[var(--muted-foreground)]">
                    <Lock size={11} />
                    {t(
                      "Not assigned to your account. An administrator has to grant it before you can use it.",
                    )}
                  </p>
                )}
              </div>

              <div className="flex shrink-0 items-center gap-2">
                {app.granted && (
                  <Toggle
                    on={app.enabled}
                    busy={busy === app.id}
                    label={app.enabled ? t("On") : t("Off")}
                    onToggle={() =>
                      void act(app.id, () =>
                        setCliAppEnabled(app.id, !app.enabled),
                      )
                    }
                  />
                )}
                {isAdmin && (
                  <button
                    type="button"
                    disabled={busy === app.id}
                    onClick={() => {
                      if (
                        typeof window !== "undefined" &&
                        !window.confirm(
                          t('Remove "{{name}}" from this deployment?', {
                            name: app.display_name,
                          }),
                        )
                      ) {
                        return;
                      }
                      void act(app.id, () => uninstallCliApp(app.id));
                    }}
                    title={t("Uninstall")}
                    className="rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-red-500 disabled:opacity-50"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>

      <p className="text-[11.5px] text-[var(--muted-foreground)]">
        {t("Installed under")}{" "}
        <span className="font-mono text-[var(--foreground)]/65">
          {"data/cli-apps"}
        </span>
        {" — "}
        {t("mounted read-only into the sandbox that runs them.")}
      </p>
      <TrademarkNote />
    </div>
  );
}

// ── store ────────────────────────────────────────────────────────────────

function Store({
  isAdmin,
  adminKnown,
  onChanged,
}: {
  isAdmin: boolean;
  adminKnown: boolean;
  onChanged: (next: CliAppState) => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [showAll, setShowAll] = useState(false);

  const [entries, setEntries] = useState<CliCatalogEntry[]>([]);
  const [categories, setCategories] = useState<Record<string, number>>({});
  const [cursor, setCursor] = useState("");
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<CliCatalogEntry | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => setQuery(draft.trim()), 250);
    return () => clearTimeout(timer);
  }, [draft]);

  // Identifies the query a response belongs to, so a slow "Load more" cannot
  // append onto a list that has since been rebuilt for different filters.
  const queryKey = JSON.stringify([query, category, showAll]);
  const queryKeyRef = useRef(queryKey);

  useEffect(() => {
    let cancelled = false;
    queryKeyRef.current = queryKey;
    setLoading(true);
    setError(null);
    getCliCatalog({
      q: query,
      category,
      installableOnly: !showAll,
      limit: PAGE_SIZE,
    })
      .then((page) => {
        if (cancelled) return;
        setEntries(page.entries);
        setCategories(page.categories);
        setCursor(page.next_cursor);
        setTotal(page.total);
      })
      .catch((err) => {
        // Stored untranslated, rendered through `t`: keying this effect on `t`
        // would let a new `t` identity cancel the search that is in flight.
        if (!cancelled) setError(messageOf(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [queryKey, query, category, showAll]);

  const loadMore = useCallback(async () => {
    if (!cursor || loadingMore) return;
    const requestedFor = queryKeyRef.current;
    setLoadingMore(true);
    try {
      const page = await getCliCatalog({
        q: query,
        category,
        installableOnly: !showAll,
        cursor,
        limit: PAGE_SIZE,
      });
      if (queryKeyRef.current !== requestedFor) return;
      setEntries((prev) => {
        const seen = new Set(prev.map((entry) => entry.id));
        return [...prev, ...page.entries.filter((entry) => !seen.has(entry.id))];
      });
      setCursor(page.next_cursor);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setLoadingMore(false);
    }
  }, [cursor, loadingMore, query, category, showAll]);

  const chips = useMemo(
    () =>
      Object.entries(categories)
        .filter(([, count]) => count > 0)
        .sort((a, b) => b[1] - a[1]),
    [categories],
  );

  if (selected) {
    return (
      <EntryDetail
        entry={selected}
        isAdmin={isAdmin}
        adminKnown={adminKnown}
        onBack={() => setSelected(null)}
        onInstalled={(next) => {
          onChanged(next);
          setEntries((prev) =>
            prev.map((item) =>
              item.id === selected.id ? { ...item, installed: true } : item,
            ),
          );
          setSelected({ ...selected, installed: true });
        }}
      />
    );
  }

  return (
    <div className="space-y-4">
      {!isAdmin && adminKnown && (
        <Banner tone="info">
          {t(
            "Installing runs the app's own installer on this server, so it is an administrator action. You can browse here and ask for an app by name.",
          )}
        </Banner>
      )}

      <div className="relative">
        <Search
          size={14}
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]"
        />
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={t("Search CLI apps…")}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--card)] py-2 pl-9 pr-3 text-[13px] text-[var(--foreground)] outline-none transition-colors placeholder:text-[var(--muted-foreground)]/70 focus:border-[var(--ring)]"
          spellCheck={false}
        />
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <FilterChip
          label={t("All")}
          active={category === ""}
          onClick={() => setCategory("")}
        />
        {chips.map(([name, count]) => (
          <FilterChip
            key={name}
            label={name}
            count={count}
            active={category === name}
            onClick={() => setCategory(category === name ? "" : name)}
          />
        ))}
        <span className="mx-1 h-4 w-px bg-[var(--border)]" aria-hidden />
        <FilterChip
          label={t("Include unavailable")}
          active={showAll}
          muted
          onClick={() => setShowAll((prev) => !prev)}
        />
      </div>

      {error !== null && (
        <Banner tone="warn">{error || t("Something went wrong.")}</Banner>
      )}

      {loading ? (
        <Spinner />
      ) : entries.length === 0 ? (
        <Empty
          title={t("Nothing matches")}
          body={t("Try a different search or clear the filters.")}
        />
      ) : (
        <>
          <ul className="grid gap-3 md:grid-cols-2">
            {entries.map((entry) => (
              <EntryCard
                key={entry.id}
                entry={entry}
                onOpen={() => setSelected(entry)}
              />
            ))}
          </ul>
          <div className="flex items-center justify-center gap-3 pt-1">
            <span className="text-[11.5px] text-[var(--muted-foreground)]">
              {t("{{shown}} of {{total}} apps", {
                shown: entries.length,
                total,
              })}
            </span>
            {cursor && (
              <button
                type="button"
                onClick={() => void loadMore()}
                disabled={loadingMore}
                className={secondaryButton}
              >
                {loadingMore && <Loader2 className="h-3 w-3 animate-spin" />}
                {t("Load more")}
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function EntryCard({
  entry,
  onOpen,
}: {
  entry: CliCatalogEntry;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  return (
    <li
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
      className="group flex cursor-pointer flex-col rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm transition-all hover:border-[var(--foreground)]/30 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]/40"
    >
      <div className="flex items-start gap-2.5">
        <BrandIcon namespace="cli" id={entry.id} name={entry.display_name} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="truncate text-[14px] font-semibold tracking-tight text-[var(--foreground)]">
              {entry.display_name}
            </span>
            {entry.installed && (
              <span className={okChip}>
                <CheckCircle2 size={9} />
                {t("Installed")}
              </span>
            )}
            {!entry.installable && (
              <span className={warnChip}>{t("Unavailable here")}</span>
            )}
          </div>
          <p className="mt-0.5 line-clamp-2 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
            {entry.description}
          </p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-1.5 pt-1">
        <span className={chipClass}>{entry.category}</span>
        <TrustChip trust={entry.trust} pinned={entry.pinned} />
      </div>
    </li>
  );
}

function EntryDetail({
  entry,
  isAdmin,
  adminKnown,
  onBack,
  onInstalled,
}: {
  entry: CliCatalogEntry;
  isAdmin: boolean;
  adminKnown: boolean;
  onBack: () => void;
  onInstalled: (next: CliAppState) => void;
}) {
  const { t } = useTranslation();
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [log, setLog] = useState<string | null>(null);

  const install = useCallback(async () => {
    setInstalling(true);
    setError(null);
    setLog(null);
    try {
      const next = await installCliApp(entry.id);
      setLog(next.log ?? null);
      onInstalled(next);
    } catch (err) {
      setError(messageOf(err));
      // The log is the only actionable thing about a failed install.
      if (err instanceof CliAppError && err.log) setLog(err.log);
    } finally {
      setInstalling(false);
    }
  }, [entry.id, onInstalled]);

  return (
    <div className="space-y-5">
      <button
        type="button"
        onClick={onBack}
        className="group inline-flex items-center gap-1.5 text-[13px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
      >
        <ArrowLeft
          size={15}
          strokeWidth={1.8}
          className="transition-transform group-hover:-translate-x-0.5"
        />
        {t("Back to the store")}
      </button>

      <div className="flex items-start gap-3.5">
        <BrandIcon
          namespace="cli"
          id={entry.id}
          name={entry.display_name}
          size="lg"
          className="rounded-xl"
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-[18px] font-semibold tracking-tight text-[var(--foreground)]">
              {entry.display_name}
            </h2>
            {entry.installed && (
              <span className={okChip}>
                <CheckCircle2 size={9} />
                {t("Installed")}
              </span>
            )}
          </div>
          <p className="mt-1 text-[13px] leading-relaxed text-[var(--muted-foreground)]">
            {entry.description}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <span className={chipClass}>{entry.category}</span>
            <span className={chipClass}>{entry.runtime}</span>
            <TrustChip trust={entry.trust} pinned={entry.pinned} />
          </div>
        </div>
      </div>

      {entry.requires && (
        <Field label={t("Requirements")}>{entry.requires}</Field>
      )}
      {entry.install_notes && (
        <Field label={t("Notes")}>{entry.install_notes}</Field>
      )}
      {entry.installable && (
        <Field label={t("Installs")}>
          <code className="break-all font-mono text-[11.5px] text-[var(--foreground)]/80">
            {entry.install_target}
          </code>
          {!entry.pinned && (
            <span className="mt-1.5 block text-[11.5px] text-amber-700 dark:text-amber-400">
              {t(
                "This resolves to whatever that source publishes today — it is not pinned to a reviewed revision.",
              )}
            </span>
          )}
        </Field>
      )}
      {entry.installable && (
        <Field label={t("Tool name in chat")}>
          <code className="font-mono text-[11.5px] text-[var(--foreground)]/80">
            {`cli_${entry.id}`}
          </code>
        </Field>
      )}

      {(entry.homepage || entry.source_url) && (
        <div className="flex flex-wrap items-center gap-3 text-[12px]">
          {entry.homepage && (
            <a
              href={entry.homepage}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
            >
              <ExternalLink size={13} />
              {t("Website")}
            </a>
          )}
          {entry.source_url && (
            <a
              href={entry.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
            >
              <BookOpen size={13} />
              {t("Source")}
            </a>
          )}
        </div>
      )}

      {!entry.installable ? (
        <Banner tone="warn">
          <span className="font-medium">{t("Not installable here.")}</span>{" "}
          {entry.unsupported_reason}
        </Banner>
      ) : !adminKnown ? null : !isAdmin ? (
        <Banner tone="info">
          {t(
            "Only an administrator can install this. Once installed they can assign it to your account.",
          )}
        </Banner>
      ) : (
        <div className="space-y-3 rounded-xl border border-[var(--border)]/60 bg-[var(--card)]/40 px-5 py-5">
          {error !== null && (
        <Banner tone="error">{error || t("Something went wrong.")}</Banner>
      )}
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => void install()}
              disabled={installing}
              className="inline-flex items-center gap-2 rounded-lg bg-[var(--primary)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {installing ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : entry.installed ? (
                <RefreshCw className="h-3.5 w-3.5" />
              ) : (
                <Download className="h-3.5 w-3.5" />
              )}
              {entry.installed ? t("Reinstall") : t("Install")}
            </button>
            <span className="text-[11.5px] text-[var(--muted-foreground)]">
              {installing
                ? t("This can take a few minutes — it builds a fresh environment.")
                : t("Runs on this server as the application user.")}
            </span>
          </div>
          {log && (
            <details className="rounded-lg border border-[var(--border)]/60 bg-[var(--background)]/60">
              <summary className="cursor-pointer px-3 py-2 text-[12px] font-medium text-[var(--muted-foreground)]">
                {t("Install output")}
              </summary>
              <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all px-3 pb-3 font-mono text-[11px] leading-relaxed text-[var(--muted-foreground)]">
                {log}
              </pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

// ── small parts ──────────────────────────────────────────────────────────

const secondaryButton =
  "inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:opacity-60";

const okChip =
  "inline-flex shrink-0 items-center gap-1 rounded-md bg-emerald-500/12 px-1.5 py-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400";

const warnChip =
  "inline-flex shrink-0 items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10.5px] font-medium text-amber-700 dark:text-amber-400";

/**
 * Where the code came from, and whether the install is fixed to one revision.
 *
 * Shown everywhere an app appears, because it is the only honest input to
 * "should this run on our server?" — and "installs whatever that repository's
 * default branch holds today" is invisible otherwise.
 */
function TrustChip({
  trust,
  pinned,
}: {
  trust: string;
  pinned: boolean;
}) {
  const { t } = useTranslation();
  if (trust === "first-party") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10.5px] font-medium text-emerald-700 dark:text-emerald-400">
        <ShieldCheck size={9} />
        {t("Pinned")}
      </span>
    );
  }
  return (
    <span className={warnChip}>
      {pinned ? t("Third-party") : t("Third-party, unpinned")}
    </span>
  );
}

function Toggle({
  on,
  busy,
  label,
  onToggle,
}: {
  on: boolean;
  busy: boolean;
  label: string;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={busy}
      onClick={onToggle}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${
        on ? "bg-[var(--primary)]" : "bg-[var(--muted)]"
      }`}
    >
      <span
        className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${
          on ? "translate-x-[18px]" : "translate-x-[3px]"
        }`}
      />
    </button>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-[var(--border)]/60 bg-[var(--card)]/40 px-4 py-3">
      <div className="mb-1.5 block text-[10.5px] font-semibold uppercase tracking-[0.14em] text-[var(--muted-foreground)]/80">
        {label}
      </div>
      <div className="text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
        {children}
      </div>
    </div>
  );
}

function Banner({
  tone,
  children,
}: {
  tone: "error" | "warn" | "info";
  children: React.ReactNode;
}) {
  const styles = {
    error: "border-red-500/40 bg-red-500/5 text-red-500",
    warn:
      "border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-400",
    info: "border-[var(--border)] bg-[var(--muted)]/40 text-[var(--muted-foreground)]",
  }[tone];
  return (
    <div
      className={`rounded-lg border px-3 py-2 text-[12.5px] leading-relaxed ${styles}`}
    >
      {children}
    </div>
  );
}

function Spinner() {
  return (
    <div className="flex items-center justify-center py-16">
      <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
    </div>
  );
}

function Empty({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--card)]/40 px-6 py-14 text-center">
      <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--muted)]/60 text-[var(--muted-foreground)]">
        <Terminal size={18} />
      </div>
      <p className="text-[14px] font-medium text-[var(--foreground)]">{title}</p>
      <p className="mx-auto mt-1 max-w-md text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
        {body}
      </p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

function TabButton({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count?: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`relative px-4 py-2 text-[13px] font-medium transition-colors ${
        active
          ? "text-[var(--foreground)]"
          : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
      }`}
    >
      {label}
      {typeof count === "number" && (
        <span className="ml-2 rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-normal text-[var(--muted-foreground)]">
          {count}
        </span>
      )}
      {active && (
        <span
          aria-hidden
          className="absolute -bottom-px left-0 right-0 h-[2px] bg-[var(--foreground)]"
        />
      )}
    </button>
  );
}

function FilterChip({
  label,
  count,
  active,
  muted,
  onClick,
}: {
  label: string;
  count?: number;
  active: boolean;
  muted?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[12px] font-medium transition-colors ${
        active
          ? "border-[var(--foreground)] bg-[var(--foreground)] text-[var(--background)]"
          : muted
            ? "border-dashed border-[var(--border)] text-[var(--muted-foreground)]/80 hover:text-[var(--foreground)]"
            : "border-[var(--border)] text-[var(--muted-foreground)] hover:border-[var(--foreground)]/30 hover:text-[var(--foreground)]"
      }`}
    >
      {label}
      {typeof count === "number" && (
        <span
          className={`tabular-nums ${
            active ? "opacity-80" : "text-[var(--muted-foreground)]/70"
          }`}
        >
          {count}
        </span>
      )}
    </button>
  );
}

/**
 * The failure's own message, or `""` when it has none.
 *
 * A refusal's own message wins over a generic one: the backend writes these for
 * a person to read ("its published install command is a shell script…"), and
 * replacing them with "request failed" throws away the only useful part.
 *
 * Untranslated on purpose. Translating here would mean passing `t` into the
 * places that catch — including effects, where depending on `t` lets a new `t`
 * identity cancel a request that is already in flight. Callers render
 * `message || t("Something went wrong.")` instead, which also means a language
 * switch updates the fallback.
 */
function messageOf(error: unknown): string {
  if (error instanceof CliAppError && error.message) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return "";
}

function formatDay(iso: string, zh: boolean): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(zh ? "zh-CN" : "en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
