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
  Plug,
  RefreshCw,
  Search,
  ShieldAlert,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import BrandIcon, { TrademarkNote } from "@/components/common/BrandIcon";
import { chipClass, inputClass, labelClass } from "@/components/mcp/styles";
import type { McpSurface } from "@/components/mcp/surface";
import {
  getMcpCatalog,
  installMcpCatalogEntry,
  testSpaceMcpServer,
  type McpCatalogEntry,
  type McpServerConfig,
  type McpStoreState,
  type McpTestResult,
} from "@/lib/mcp-api";
import {
  MCP_CATALOG_TIERS,
  appendCatalogPage,
  canInstallEntry,
  catalogCategoryChips,
  describeMcpError,
  filledCredentials,
  localizedCatalogText,
  missingRequiredFields,
  type McpCatalogList,
} from "@/lib/mcp-store";

/** One grid page. Small enough that the first paint is quick, and every further
 *  page is an explicit "Load more" — the store never renders itself whole. */
const PAGE_SIZE = 12;

type InstallState =
  | { kind: "installing" }
  | { kind: "done" }
  | { kind: "error"; message: string };

/**
 * Local names *entry* is installed under, for the caller.
 *
 * Keyed on recorded provenance (`catalog_entry`), not on the name: "Install as"
 * lets someone call Exa `search`, and matching by name would then tell them it
 * is not installed — offering a second install that trips the account cap.
 *
 * A `null` server map means the list has not loaded, and the catalog page's own
 * `installed_as` is the only answer available. Once it *has* loaded it wins, so
 * deleting a server flips the badge back without refetching the catalog.
 */
function installedNames(
  entry: McpCatalogEntry,
  servers: Record<string, McpServerConfig> | null,
): string[] {
  if (!servers) return entry.installed_as;
  return Object.entries(servers)
    .filter(
      ([name, cfg]) =>
        cfg.catalog_entry === entry.id ||
        // Installed before provenance was recorded: the entry id was the only
        // name the store could have written it under.
        (!cfg.catalog_entry && name === entry.id),
    )
    .map(([name]) => name)
    .sort();
}

/**
 * The curated MCP store: search, filter, paginate, and install into the
 * caller's own server list.
 */
export default function McpCatalogBrowser({
  surface,
  installedServers,
  atCapacity,
  onInstalled,
}: {
  surface: McpSurface;
  /**
   * The caller's own servers by name, or `null` while the list is still loading.
   * Entries already installed read as installed, and their saved config is what
   * a Test probes — the catalog row itself carries no connection details.
   */
  installedServers: Record<string, McpServerConfig> | null;
  /** True at the per-account server cap: installing would be refused. */
  atCapacity: boolean;
  onInstalled: (state: McpStoreState) => void;
}) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language || "en";
  const basePath = surface.basePath;

  const [queryDraft, setQueryDraft] = useState("");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [tier, setTier] = useState("");

  const [list, setList] = useState<McpCatalogList | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selected, setSelected] = useState<McpCatalogEntry | null>(null);
  const [installState, setInstallState] = useState<
    Record<string, InstallState>
  >({});

  // Search hits the API (the catalog is the backend's to filter), so the input
  // is debounced rather than firing a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => setQuery(queryDraft.trim()), 250);
    return () => clearTimeout(timer);
  }, [queryDraft]);

  // Identifies the query a response belongs to, so a slower "Load more" cannot
  // append onto a list that has since been rebuilt for different filters.
  const queryKeyRef = useRef("");
  useEffect(() => {
    let cancelled = false;
    queryKeyRef.current = `${query}\u0000${category}\u0000${tier}`;
    setLoading(true);
    setError(null);
    getMcpCatalog(basePath, { q: query, category, tier, limit: PAGE_SIZE })
      .then((page) => {
        if (cancelled) return;
        setList(appendCatalogPage(null, page));
      })
      .catch((err) => {
        if (!cancelled) setError(describeMcpError(err, t));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [basePath, query, category, tier, t]);

  const loadMore = useCallback(async () => {
    if (!list?.cursor || loadingMore) return;
    setLoadingMore(true);
    // The query the page was requested for. A response that arrives after the
    // search or filters changed belongs to a list that no longer exists, and
    // appending it would mix two queries' rows.
    const requestedFor = `${query}\u0000${category}\u0000${tier}`;
    try {
      const page = await getMcpCatalog(basePath, {
        q: query,
        category,
        tier,
        cursor: list.cursor,
        limit: PAGE_SIZE,
      });
      if (queryKeyRef.current !== requestedFor) return;
      setList((prev) => appendCatalogPage(prev, page));
    } catch (err) {
      setError(describeMcpError(err, t));
    } finally {
      setLoadingMore(false);
    }
  }, [basePath, list, loadingMore, query, category, tier, t]);

  // The parent hands us fresh state after every install and delete, so this is
  // always current — there is no local "installed during this visit" set to keep
  // in sync with it.
  const namesFor = useCallback(
    (entry: McpCatalogEntry) => installedNames(entry, installedServers),
    [installedServers],
  );

  const install = useCallback(
    async (
      entry: McpCatalogEntry,
      name: string,
      secrets: Record<string, string>,
    ) => {
      setInstallState((prev) => ({
        ...prev,
        [entry.id]: { kind: "installing" },
      }));
      try {
        const state = await installMcpCatalogEntry(basePath, entry.id, {
          name,
          secrets,
        });
        setInstallState((prev) => ({ ...prev, [entry.id]: { kind: "done" } }));
        onInstalled(state);
        return state;
      } catch (err) {
        setInstallState((prev) => ({
          ...prev,
          [entry.id]: { kind: "error", message: describeMcpError(err, t) },
        }));
        return null;
      }
    },
    [basePath, onInstalled, t],
  );

  const chips = useMemo(
    () => catalogCategoryChips(list?.categories ?? {}),
    [list?.categories],
  );
  // An empty grid means two different things, and they need different copy:
  // nothing matched the filter, versus a deployment whose catalog is empty.
  const filtering = Boolean(query || category || tier);

  if (selected) {
    return (
      <EntryDetail
        entry={selected}
        lang={lang}
        installedAs={namesFor(selected)}
        installedServers={installedServers}
        state={installState[selected.id]}
        atCapacity={atCapacity}
        surface={surface}
        onBack={() => setSelected(null)}
        onInstall={install}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="relative">
        <Search
          size={14}
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]"
        />
        <input
          value={queryDraft}
          onChange={(e) => setQueryDraft(e.target.value)}
          placeholder={t("Search MCP services…")}
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
        {chips.map((chip) => (
          <FilterChip
            key={chip.category}
            label={t(`mcp.category.${chip.category}`)}
            count={chip.count}
            active={category === chip.category}
            onClick={() => setCategory(chip.category)}
          />
        ))}
        <span className="mx-1 h-4 w-px bg-[var(--border)]" aria-hidden />
        {MCP_CATALOG_TIERS.map((item) => (
          <FilterChip
            key={item}
            label={t(`mcp.tier.${item}`)}
            active={tier === item}
            muted
            onClick={() => setTier(tier === item ? "" : item)}
          />
        ))}
      </div>

      {error && (
        <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-[12.5px] text-amber-700 dark:text-amber-400">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
        </div>
      ) : !list || list.entries.length === 0 ? (
        filtering ? (
          <div className="rounded-2xl border border-dashed border-[var(--border)] px-6 py-10 text-center text-[13px] text-[var(--muted-foreground)]">
            {t("No services match this filter.")}
          </div>
        ) : (
          <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--card)]/40 px-6 py-14 text-center">
            <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--muted)]/60 text-[var(--muted-foreground)]">
              <Plug size={18} />
            </div>
            <p className="text-[14px] font-medium text-[var(--foreground)]">
              {t("The store is empty")}
            </p>
            <p className="mx-auto mt-1 max-w-sm text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
              {t(
                "This deployment ships no installable MCP services yet. You can still add one by URL.",
              )}
            </p>
          </div>
        )
      ) : (
        <>
          <ul className="grid gap-3 md:grid-cols-2">
            {list.entries.map((entry) => (
              <EntryCard
                key={entry.id}
                entry={entry}
                lang={lang}
                installed={namesFor(entry).length > 0}
                onOpen={() => setSelected(entry)}
              />
            ))}
          </ul>
          <div className="flex items-center justify-center gap-3 pt-1">
            <span className="text-[11.5px] text-[var(--muted-foreground)]">
              {t("{{shown}} of {{total}} services", {
                shown: list.entries.length,
                total: list.total,
              })}
            </span>
            {list.cursor && (
              <button
                type="button"
                onClick={() => void loadMore()}
                disabled={loadingMore}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:opacity-60"
              >
                {loadingMore && (
                  <Loader2 className="h-3 w-3 animate-spin" />
                )}
                {t("Load more")}
              </button>
            )}
          </div>
          <TrademarkNote className="pt-1 text-center" />
        </>
      )}
    </div>
  );
}

// ── grid ─────────────────────────────────────────────────────────────────

function EntryCard({
  entry,
  lang,
  installed,
  onOpen,
}: {
  entry: McpCatalogEntry;
  lang: string;
  installed: boolean;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  const description = localizedCatalogText(entry.description_i18n, lang);
  return (
    <li
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      title={t("View details")}
      className="group flex cursor-pointer flex-col rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm transition-all hover:border-[var(--foreground)]/30 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]/40"
    >
      <div className="flex items-start gap-2.5">
        <BrandIcon namespace="mcp" id={entry.id} name={entry.display_name} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="truncate text-[14px] font-semibold tracking-tight text-[var(--foreground)]">
              {entry.display_name}
            </span>
            {installed && (
              <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-emerald-500/12 px-1.5 py-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 size={9} />
                {t("Installed")}
              </span>
            )}
          </div>
          <p className="mt-0.5 line-clamp-2 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
            {description}
          </p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-1.5 pt-1">
        <span className={chipClass}>{t(`mcp.category.${entry.category}`)}</span>
        {entry.tier === "registry" && (
          <span className={chipClass}>{t("mcp.tier.registry")}</span>
        )}
        {entry.trust !== "verified" && (
          <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10.5px] font-medium text-amber-700 dark:text-amber-400">
            <ShieldAlert size={9} />
            {t("Unverified")}
          </span>
        )}
        {entry.fields.length > 0 && (
          <span className={chipClass}>{t("Needs a credential")}</span>
        )}
      </div>
    </li>
  );
}

// ── detail pane ──────────────────────────────────────────────────────────

function EntryDetail({
  entry,
  lang,
  installedAs,
  installedServers,
  state,
  atCapacity,
  surface,
  onBack,
  onInstall,
}: {
  entry: McpCatalogEntry;
  lang: string;
  /** Local names this entry is already installed under; empty if it is not. */
  installedAs: string[];
  installedServers: Record<string, McpServerConfig> | null;
  state?: InstallState;
  atCapacity: boolean;
  surface: McpSurface;
  onBack: () => void;
  onInstall: (
    entry: McpCatalogEntry,
    name: string,
    secrets: Record<string, string>,
  ) => Promise<McpStoreState | null>;
}) {
  const { t } = useTranslation();
  // Prefilled with the name it is installed under, so Test and Reinstall act on
  // the server that exists rather than on a second copy under the default name.
  const [name, setName] = useState(() => installedAs[0] ?? entry.id);
  const [values, setValues] = useState<Record<string, string>>({});
  const [probe, setProbe] = useState<McpTestResult | null>(null);
  const [probing, setProbing] = useState(false);

  const description = localizedCatalogText(entry.description_i18n, lang);
  const requires = localizedCatalogText(entry.requires_i18n, lang);
  const missing = missingRequiredFields(entry.fields, values);
  const ready = canInstallEntry(entry.fields, values);
  const installing = state?.kind === "installing";
  const installed = installedAs.length > 0;
  const target = name.trim() || entry.id;
  const savedConfig = installedServers?.[target];

  /**
   * Probe one of the caller's servers.
   *
   * A catalog row carries no connection template — the backend materialises it
   * on install, on purpose — so there is nothing for the client to hand
   * `/servers/{name}/test` until the server exists. Hence: Test is offered
   * standalone for a service already installed, and runs automatically right
   * after an install, which is the earliest a credential can be verified.
   */
  const probeServer = useCallback(
    async (cfg: McpServerConfig, serverName: string) => {
      setProbing(true);
      try {
        setProbe(await testSpaceMcpServer(surface.basePath, serverName, cfg));
      } catch (err) {
        setProbe({ ok: false, tools: [], error: describeMcpError(err, t) });
      } finally {
        setProbing(false);
      }
    },
    [surface.basePath, t],
  );

  const handleInstall = useCallback(async () => {
    setProbe(null);
    const next = await onInstall(entry, target, filledCredentials(values));
    const cfg = next?.servers[target];
    if (cfg) await probeServer(cfg, target);
  }, [entry, target, values, onInstall, probeServer]);

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
        <BrandIcon namespace="mcp" id={entry.id} name={entry.display_name} size="lg" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-[18px] font-semibold tracking-tight text-[var(--foreground)]">
              {entry.display_name}
            </h2>
            {installed && (
              <span className="inline-flex items-center gap-1 rounded-md bg-emerald-500/12 px-1.5 py-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 size={9} />
                {t("Installed")}
              </span>
            )}
          </div>
          <p className="mt-1 text-[13px] leading-relaxed text-[var(--muted-foreground)]">
            {description}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <span className={chipClass}>
              {t(`mcp.category.${entry.category}`)}
            </span>
            <span className={chipClass}>{t(`mcp.tier.${entry.tier}`)}</span>
            <span className={chipClass}>{entry.transport}</span>
            {entry.trust !== "verified" && (
              <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10.5px] font-medium text-amber-700 dark:text-amber-400">
                <ShieldAlert size={9} />
                {t("Unverified")}
              </span>
            )}
          </div>
        </div>
      </div>

      {requires && (
        <div className="rounded-lg border border-[var(--border)]/60 bg-[var(--card)]/40 px-4 py-3">
          <div className={labelClass}>{t("Requirements")}</div>
          <p className="text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
            {requires}
          </p>
        </div>
      )}

      {(entry.docs_url || entry.homepage) && (
        <div className="flex flex-wrap items-center gap-3 text-[12px]">
          {entry.docs_url && (
            <a
              href={entry.docs_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
            >
              <BookOpen size={13} />
              {t("Documentation")}
            </a>
          )}
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
        </div>
      )}

      <div className="space-y-4 rounded-xl border border-[var(--border)]/60 bg-[var(--card)]/40 px-5 py-5">
        <div>
          <label className={labelClass}>{t("Install as")}</label>
          <input
            className={`${inputClass} font-mono`}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={entry.id}
            spellCheck={false}
            autoComplete="off"
          />
        </div>

        {entry.fields.map((field) => (
          <div key={field.key}>
            <label className={labelClass}>
              {localizedCatalogText(field.label_i18n, lang) || field.key}
              {!field.required && (
                <span className="ml-1.5 font-normal normal-case tracking-normal opacity-70">
                  {t("optional")}
                </span>
              )}
            </label>
            <input
              className={inputClass}
              // A secret is a password field so the browser never offers to
              // autofill or reveal it in a screenshot-friendly plain input.
              type={field.secret ? "password" : "text"}
              value={values[field.key] ?? ""}
              onChange={(e) =>
                setValues((prev) => ({ ...prev, [field.key]: e.target.value }))
              }
              placeholder={field.placeholder}
              spellCheck={false}
              autoComplete="off"
            />
          </div>
        ))}

        {entry.fields.length > 0 && (
          <p className="text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "Credentials are stored apart from the server config and are never sent back to this page.",
            )}
          </p>
        )}

        {atCapacity && (
          <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-[12px] text-amber-700 dark:text-amber-400">
            {t("You have reached your MCP server limit. Remove one first.")}
          </div>
        )}

        {state?.kind === "error" && (
          <div className="rounded-lg border border-red-500/40 bg-red-500/5 px-3 py-2 text-[12px] text-red-500">
            {state.message}
          </div>
        )}

        {probing && (
          <div className="flex items-center gap-2 text-[12px] text-[var(--muted-foreground)]">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {t("Testing the connection…")}
          </div>
        )}

        {probe && !probing && (
          <div
            className={`rounded-lg border px-3 py-2 text-[12px] ${
              probe.ok
                ? "border-emerald-500/40 bg-emerald-500/5 text-emerald-600 dark:text-emerald-400"
                : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400"
            }`}
          >
            {probe.ok ? (
              t("Connected — {{count}} tools detected", {
                count: probe.tools.length,
              })
            ) : (
              <>
                <span className="inline-flex items-center gap-1.5 font-medium">
                  <AlertTriangle size={12} />
                  {t("Connection failed.")}
                </span>
                {probe.error && (
                  <span className="mt-1 block break-words opacity-80">
                    {probe.error}
                  </span>
                )}
              </>
            )}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          {savedConfig && (
            <button
              type="button"
              onClick={() => void probeServer(savedConfig, target)}
              disabled={probing || installing}
              className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {probing && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {t("Test connection")}
            </button>
          )}
          <button
            type="button"
            onClick={() => void handleInstall()}
            // At capacity, only a write that replaces an existing server is
            // still possible — keyed on the target name, because renaming in the
            // box above turns a reinstall into a new server the store refuses.
            disabled={installing || probing || !ready || (atCapacity && !savedConfig)}
            className="inline-flex items-center gap-2 rounded-lg bg-[var(--primary)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {installing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : installed ? (
              <RefreshCw className="h-3.5 w-3.5" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
            {installed ? t("Reinstall") : t("Install")}
          </button>
          {!ready && (
            <span className="text-[11.5px] text-[var(--muted-foreground)]">
              {t("Fill in {{fields}} to continue", {
                fields: missing.join(", "),
              })}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

// ── small parts ──────────────────────────────────────────────────────────


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
