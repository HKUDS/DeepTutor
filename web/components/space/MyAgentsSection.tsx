"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Bot,
  Loader2,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import SessionList from "@/components/SessionList";
import { agentGlyph } from "@/components/agents/agent-icons";
import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import ImportWizard from "@/components/space/ImportWizard";
import ScopeEditorModal from "@/components/space/ScopeEditorModal";
import { useAppShell } from "@/context/AppShellContext";
import { formatRelativeTime } from "@/lib/relative-time";
import {
  deleteSession,
  updateSessionTitle,
  type SessionSummary,
} from "@/lib/session-api";
import { importChatHistory, listImportedSessions } from "@/lib/imports-api";
import {
  deleteAgent,
  ensureReadPermission,
  getAgents,
  saveAgent,
  type ImportAgent,
} from "@/lib/chat-import/agent-store";
import {
  assignSessionsToAgents,
  readImportMeta,
} from "@/lib/chat-import/attribution";
import {
  filterRefsByScope,
  parseSessions,
  scanDirectory,
  SOURCE_LABEL,
  type AgentScope,
  type ImportSource,
} from "@/lib/chat-import";

/**
 * "My Agents" — each named, scoped slice of an imported `.claude` / `.codex`
 * folder is an agent. Conversations are normal sessions, grouped here by the
 * agent that owns them (by `agent_id`, falling back to source + scope for
 * pre-agent imports). The persisted folder handle lets the user rename, re-scope,
 * refresh, or delete an agent without re-picking the folder.
 */

const UNGROUPED_PREFIX = "ungrouped:";

type CardView =
  | {
      kind: "agent";
      key: string;
      agent: ImportAgent;
      count: number;
      latest: number;
    }
  | {
      kind: "ungrouped";
      key: string;
      source: ImportSource;
      count: number;
      latest: number;
    };

function scopeSummary(
  scope: AgentScope,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string {
  if (scope.kind === "projects")
    return t("{{count}} projects", { count: scope.cwds.length });
  if (scope.kind === "dates")
    return t("{{count}} days", { count: scope.days.length });
  return t("All conversations");
}

export default function MyAgentsSection() {
  const { t, i18n } = useTranslation();
  const router = useRouter();
  const { activeSessionId, setActiveSessionId } = useAppShell();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [registry, setRegistry] = useState<ImportAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [wizardOpen, setWizardOpen] = useState(false);
  const [refreshingId, setRefreshingId] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [scopeAgent, setScopeAgent] = useState<ImportAgent | null>(null);

  const load = useCallback(async (force = false) => {
    setLoading(true);
    try {
      const [imported, reg] = await Promise.all([
        listImportedSessions(200, 0, { force }),
        getAgents(),
      ]);
      setSessions(imported);
      setRegistry(reg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(true);
  }, [load]);

  const { cards, byCard } = useMemo(() => {
    const ordered = [...registry].sort(
      (a, b) => (b.lastSyncAt || b.createdAt) - (a.lastSyncAt || a.createdAt),
    );
    const owner = assignSessionsToAgents(sessions, ordered);
    const byCard = new Map<string, SessionSummary[]>();
    const stats = new Map<string, { count: number; latest: number }>();
    for (const session of sessions) {
      const meta = readImportMeta(session);
      if (!meta) continue;
      const sid = session.session_id || session.id;
      const key = owner.get(sid) ?? `${UNGROUPED_PREFIX}${meta.source}`;
      const arr = byCard.get(key) ?? [];
      arr.push(session);
      byCard.set(key, arr);
      const st = stats.get(key) ?? { count: 0, latest: 0 };
      st.count += 1;
      st.latest = Math.max(st.latest, session.updated_at);
      stats.set(key, st);
    }
    const agentCards: CardView[] = ordered.map((agent) => ({
      kind: "agent",
      key: agent.id,
      agent,
      count: stats.get(agent.id)?.count ?? 0,
      latest: stats.get(agent.id)?.latest ?? 0,
    }));
    const ungroupedCards: CardView[] = Array.from(stats.entries())
      .filter(([key]) => key.startsWith(UNGROUPED_PREFIX))
      .map(([key, st]) => ({
        kind: "ungrouped",
        key,
        source: key.slice(UNGROUPED_PREFIX.length) as ImportSource,
        count: st.count,
        latest: st.latest,
      }));
    return { cards: [...agentCards, ...ungroupedCards], byCard };
  }, [registry, sessions]);

  // Keep a valid selection as cards load/change.
  useEffect(() => {
    if (selectedKey && cards.some((c) => c.key === selectedKey)) return;
    setSelectedKey(cards[0]?.key ?? null);
  }, [cards, selectedKey]);

  const visibleSessions = useMemo(() => {
    const list = selectedKey ? (byCard.get(selectedKey) ?? []) : [];
    const needle = query.trim().toLowerCase();
    if (!needle) return list;
    return list.filter((session) =>
      [session.title, session.last_message]
        .filter(Boolean)
        .some((value) => value.toLowerCase().includes(needle)),
    );
  }, [byCard, selectedKey, query]);

  const handleSelect = useCallback(
    (sessionId: string) => {
      setActiveSessionId(sessionId);
      router.push(`/home/${sessionId}`);
    },
    [router, setActiveSessionId],
  );

  const handleRenameSession = useCallback(
    async (sessionId: string, title: string) => {
      await updateSessionTitle(sessionId, title);
      await load(true);
    },
    [load],
  );

  const handleDeleteSession = useCallback(
    async (sessionId: string) => {
      if (!window.confirm(t("Delete this conversation?"))) return;
      await deleteSession(sessionId);
      if (activeSessionId === sessionId) setActiveSessionId(null);
      setSessions((prev) =>
        prev.filter((session) => session.session_id !== sessionId),
      );
    },
    [activeSessionId, setActiveSessionId, t],
  );

  const refreshAgent = useCallback(
    async (agent: ImportAgent) => {
      setRefreshingId(agent.id);
      setNote("");
      try {
        if (!agent.handle || !(await ensureReadPermission(agent.handle))) {
          setNote(t("Refresh failed — try re-adding the agent."));
          return;
        }
        const scan = await scanDirectory(agent.handle);
        const refs = filterRefsByScope(
          scan.projects.flatMap((p) => p.sessions),
          agent.scope,
        );
        const normalized = await parseSessions(scan.source, refs);
        const res = await importChatHistory(scan.source, normalized, {
          id: agent.id,
          name: agent.name,
        });
        await saveAgent({ ...agent, lastSyncAt: Date.now() });
        await load(true);
        setNote(
          res.imported > 0
            ? t("Added {{count}} new conversations", { count: res.imported })
            : t("Already up to date"),
        );
      } catch {
        setNote(t("Refresh failed — try re-adding the agent."));
      } finally {
        setRefreshingId(null);
      }
    },
    [load, t],
  );

  const commitRename = useCallback(
    async (agent: ImportAgent, name: string) => {
      setRenamingId(null);
      const trimmed = name.trim();
      if (!trimmed || trimmed === agent.name) return;
      await saveAgent({ ...agent, name: trimmed });
      await load(true);
    },
    [load],
  );

  const removeAgent = useCallback(
    async (agent: ImportAgent) => {
      const owned = byCard.get(agent.id) ?? [];
      const message = owned.length
        ? t(
            "Delete “{{name}}” and its {{count}} conversations? This removes them from your space and can't be undone.",
            { name: agent.name, count: owned.length },
          )
        : t("Delete “{{name}}”?", { name: agent.name });
      if (!window.confirm(message)) return;
      await deleteAgent(agent.id);
      await Promise.allSettled(
        owned.map((s) => deleteSession(s.session_id || s.id)),
      );
      await load(true);
    },
    [byCard, load, t],
  );

  const isEmpty = !loading && cards.length === 0;

  return (
    <div className="space-y-6">
      <SpaceSectionHeader
        icon={Bot}
        title={t("Imported conversations")}
        description={t(
          "Your Claude Code and Codex conversations as named agents — open one to keep chatting, edit what each imports, or refresh to pull in new conversations.",
        )}
        action={
          !isEmpty ? (
            <button
              type="button"
              onClick={() => setWizardOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-[12px] font-medium text-[var(--background)] shadow-sm transition-opacity hover:opacity-90"
            >
              <Plus className="h-3.5 w-3.5" />
              {t("Add agent")}
            </button>
          ) : null
        }
      />

      {isEmpty ? (
        <EmptyState onAdd={() => setWizardOpen(true)} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            {cards.map((card) =>
              card.kind === "agent" ? (
                <AgentCard
                  key={card.key}
                  agent={card.agent}
                  count={card.count}
                  active={card.key === selectedKey}
                  refreshing={refreshingId === card.agent.id}
                  renaming={renamingId === card.agent.id}
                  lang={i18n.language}
                  onSelect={() => setSelectedKey(card.key)}
                  onRefresh={() => void refreshAgent(card.agent)}
                  onStartRename={() => setRenamingId(card.agent.id)}
                  onCommitRename={(name) => void commitRename(card.agent, name)}
                  onCancelRename={() => setRenamingId(null)}
                  onEditScope={() => setScopeAgent(card.agent)}
                  onDelete={() => void removeAgent(card.agent)}
                />
              ) : (
                <UngroupedCard
                  key={card.key}
                  source={card.source}
                  count={card.count}
                  active={card.key === selectedKey}
                  onSelect={() => setSelectedKey(card.key)}
                  onReadd={() => setWizardOpen(true)}
                />
              ),
            )}
          </div>

          {note && (
            <p className="text-[11.5px] text-[var(--muted-foreground)]">
              {note}
            </p>
          )}

          <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
            <div className="border-b border-[var(--border)]/60 px-4 py-3">
              <label className="flex items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--muted-foreground)] focus-within:border-[var(--ring)]">
                <Search size={14} strokeWidth={1.7} />
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={t("Search conversations...")}
                  className="min-w-0 flex-1 bg-transparent text-[13px] text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]/55"
                />
              </label>
            </div>
            <div className="px-3 py-3">
              <SessionList
                sessions={visibleSessions}
                activeSessionId={activeSessionId}
                loading={loading}
                onSelect={handleSelect}
                onRename={handleRenameSession}
                onDelete={handleDeleteSession}
              />
            </div>
          </section>
        </>
      )}

      {wizardOpen && (
        <ImportWizard
          onClose={() => setWizardOpen(false)}
          onImported={() => {
            setWizardOpen(false);
            void load(true);
          }}
        />
      )}

      {scopeAgent && (
        <ScopeEditorModal
          agent={scopeAgent}
          ownedSessions={byCard.get(scopeAgent.id) ?? []}
          onClose={() => setScopeAgent(null)}
          onSaved={() => {
            setScopeAgent(null);
            void load(true);
          }}
        />
      )}
    </div>
  );
}

function AgentCard({
  agent,
  count,
  active,
  refreshing,
  renaming,
  lang,
  onSelect,
  onRefresh,
  onStartRename,
  onCommitRename,
  onCancelRename,
  onEditScope,
  onDelete,
}: {
  agent: ImportAgent;
  count: number;
  active: boolean;
  refreshing: boolean;
  renaming: boolean;
  lang: string;
  onSelect: () => void;
  onRefresh: () => void;
  onStartRename: () => void;
  onCommitRename: (name: string) => void;
  onCancelRename: () => void;
  onEditScope: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  // Member-expression render (``glyph.Icon``) — a bare local capitalized
  // component trips react-hooks/static-components; this doesn't.
  const glyph = { Icon: agentGlyph(agent.source) ?? Bot };

  useEffect(() => {
    if (!menuOpen) return;
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [menuOpen]);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => !renaming && onSelect()}
      onKeyDown={(event) => {
        if (renaming) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
      className={`group relative flex items-center gap-3 rounded-2xl border px-4 py-3 text-left transition-all ${
        active
          ? "border-[var(--foreground)]/25 bg-[var(--card)] shadow-sm"
          : "border-[var(--border)] bg-[var(--card)]/50 hover:border-[var(--border)] hover:bg-[var(--card)]"
      }`}
    >
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-[var(--border)]/60 bg-[var(--background)] text-[var(--foreground)]">
        <glyph.Icon size={20} strokeWidth={1.6} />
      </span>
      <div className="min-w-0 flex-1">
        {renaming ? (
          <RenameInput
            initial={agent.name}
            onCommit={onCommitRename}
            onCancel={onCancelRename}
          />
        ) : (
          <div className="truncate text-[13.5px] font-semibold tracking-tight text-[var(--foreground)]">
            {agent.name}
          </div>
        )}
        <div className="mt-0.5 truncate text-[11.5px] text-[var(--muted-foreground)]">
          {SOURCE_LABEL[agent.source]} · {scopeSummary(agent.scope, t)} ·{" "}
          {t("{{count}} conversations", { count })}
        </div>
        <div className="mt-0.5 truncate text-[10.5px] text-[var(--muted-foreground)]/80">
          {agent.lastSyncAt
            ? t("Synced {{time}}", {
                time: formatRelativeTime(agent.lastSyncAt / 1000, lang),
              })
            : t("Not synced yet")}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-1">
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onRefresh();
          }}
          disabled={refreshing}
          title={t("Refresh history")}
          aria-label={t("Refresh history")}
          className="rounded-lg border border-[var(--border)]/50 p-2 text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:opacity-50"
        >
          {refreshing ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
        </button>
        <div ref={menuRef} className="relative">
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              setMenuOpen((v) => !v);
            }}
            title={t("More")}
            aria-label={t("More")}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            className="rounded-lg border border-[var(--border)]/50 p-2 text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)]"
          >
            <MoreHorizontal className="h-3.5 w-3.5" />
          </button>
          {menuOpen && (
            <div
              role="menu"
              onClick={(e) => e.stopPropagation()}
              className="animate-fade-in absolute right-0 top-full z-20 mt-1.5 w-44 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] p-1 shadow-[0_14px_44px_rgba(0,0,0,0.16)]"
            >
              <MenuItem
                icon={<Pencil size={14} />}
                label={t("Rename")}
                onClick={() => {
                  setMenuOpen(false);
                  onStartRename();
                }}
              />
              <MenuItem
                icon={<SlidersHorizontal size={14} />}
                label={t("Edit scope")}
                onClick={() => {
                  setMenuOpen(false);
                  onEditScope();
                }}
              />
              <MenuItem
                icon={<Trash2 size={14} />}
                label={t("Delete agent")}
                destructive
                onClick={() => {
                  setMenuOpen(false);
                  onDelete();
                }}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function RenameInput({
  initial,
  onCommit,
  onCancel,
}: {
  initial: string;
  onCommit: (name: string) => void;
  onCancel: () => void;
}) {
  // Mounted fresh whenever rename starts, so it seeds from `initial` without an
  // effect that would feed state back into a render.
  const [draft, setDraft] = useState(initial);
  return (
    <input
      autoFocus
      value={draft}
      onClick={(e) => e.stopPropagation()}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => onCommit(draft)}
      onKeyDown={(e) => {
        e.stopPropagation();
        if (e.key === "Enter") onCommit(draft);
        else if (e.key === "Escape") onCancel();
      }}
      className="w-full rounded-md border border-[var(--primary)]/50 bg-[var(--background)] px-1.5 py-0.5 text-[13.5px] font-semibold text-[var(--foreground)] outline-none ring-2 ring-[var(--primary)]/15"
    />
  );
}

function MenuItem({
  icon,
  label,
  onClick,
  destructive,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  destructive?: boolean;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-[12.5px] transition-colors ${
        destructive
          ? "text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/30"
          : "text-[var(--foreground)] hover:bg-[var(--muted)]/60"
      }`}
    >
      <span className="shrink-0 opacity-80">{icon}</span>
      {label}
    </button>
  );
}

function UngroupedCard({
  source,
  count,
  active,
  onSelect,
  onReadd,
}: {
  source: ImportSource;
  count: number;
  active: boolean;
  onSelect: () => void;
  onReadd: () => void;
}) {
  const { t } = useTranslation();
  const glyph = { Icon: agentGlyph(source) ?? Bot };
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
      className={`group flex items-center gap-3 rounded-2xl border border-dashed px-4 py-3 text-left transition-all ${
        active
          ? "border-[var(--foreground)]/25 bg-[var(--card)] shadow-sm"
          : "border-[var(--border)] bg-[var(--card)]/40 hover:bg-[var(--card)]"
      }`}
    >
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-[var(--border)]/60 bg-[var(--background)] text-[var(--muted-foreground)]">
        <glyph.Icon size={20} strokeWidth={1.6} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13.5px] font-semibold tracking-tight text-[var(--foreground)]">
          {SOURCE_LABEL[source]}
        </div>
        <div className="mt-0.5 truncate text-[11.5px] text-[var(--muted-foreground)]">
          {t("Ungrouped")} · {t("{{count}} conversations", { count })}
        </div>
      </div>
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          onReadd();
        }}
        className="shrink-0 rounded-lg border border-[var(--border)]/50 px-2.5 py-1.5 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)]"
      >
        {t("Add agent")}
      </button>
    </div>
  );
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  const { t } = useTranslation();
  return (
    <section className="flex flex-col items-center justify-center gap-4 rounded-2xl border border-dashed border-[var(--border)] bg-[var(--card)]/40 px-6 py-16 text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--border)]/60 bg-[var(--card)] text-[var(--muted-foreground)] shadow-sm">
        <Bot size={20} strokeWidth={1.6} />
      </span>
      <div className="space-y-1.5">
        <h2 className="font-serif text-[16px] font-semibold tracking-tight text-[var(--foreground)]">
          {t("No agents yet")}
        </h2>
        <p className="mx-auto max-w-sm text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
          {t(
            "Add your Claude Code or Codex folder to bring its conversations in — then chat with them or refresh anytime.",
          )}
        </p>
      </div>
      <button
        type="button"
        onClick={onAdd}
        className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-4 py-2 text-[12.5px] font-medium text-[var(--background)] shadow-sm transition-opacity hover:opacity-90"
      >
        <Plus className="h-3.5 w-3.5" />
        {t("Add agent")}
      </button>
    </section>
  );
}
