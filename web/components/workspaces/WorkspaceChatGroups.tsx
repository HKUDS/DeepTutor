"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronDown, Folder, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

import SessionList from "@/components/SessionList";
import OrganizedSessionList from "@/components/courses/OrganizedSessionList";
import { listSessions, type SessionSummary, type SessionOrganizationPatch } from "@/lib/session-api";
import { subscribeSessionChanges } from "@/lib/session-events";
import {
  readCollapsedGroups,
  writeCollapsedGroups,
} from "@/lib/sidebar-layout";
import type { ChatWorkspaceRegistration } from "@/lib/workspaces-api";

interface Props {
  /** User-created workspaces, loaded once by the sidebar shell. */
  workspaces: ChatWorkspaceRegistration[];
  activeSessionId?: string | null;
  liveSessionIds?: ReadonlySet<string>;
  refreshToken: number;
  onNewChat: (workspaceId: string) => void;
  onSelect: (sessionId: string) => void | Promise<void>;
  onRename: (sessionId: string, title: string) => void | Promise<void>;
  onDelete: (sessionId: string) => void | Promise<void>;
  onOrganize?: (sessionId: string, patch: SessionOrganizationPatch) => void | Promise<void>;
}

// Fetch a bounded page at a time; the API caps individual requests at 200.
async function loadWorkspacePreview(workspaceId: string, count: number) {
  const rows: SessionSummary[] = [];
  while (rows.length < count) {
    const size = Math.min(200, count - rows.length);
    const page = await listSessions(size, rows.length, {
      force: true,
      workspaceId,
    });
    rows.push(...page);
    if (page.length < size) break;
  }
  return rows;
}

/**
 * One foldable row per workspace, with the conversations filed under it.
 *
 * Deliberately the same row as the mastery and reading groups the sidebar
 * already draws (see ``OrganizedSessionList``'s group heading): a quiet title in
 * the ink and size of the conversations it sits among, its caret trailing the
 * words, its mark column holding one left edge for the whole column. A
 * workspace is a place conversations live, so it reads as a heading over them
 * rather than as a control panel bolted above the history.
 */
function WorkspaceGroup({
  workspace,
  ...props
}: Props & { workspace: ChatWorkspaceRegistration }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(
    () => !readCollapsedGroups().includes(workspace.workspace_id),
  );
  const [limit, setLimit] = useState(5);
  const [rows, setRows] = useState<SessionSummary[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    const sessions = await loadWorkspacePreview(
      workspace.workspace_id,
      limit + 1,
    );
    setRows(sessions);
    setError("");
    setLoading(false);
  }, [limit, workspace.workspace_id]);
  useEffect(() => {
    if (!open) return;
    let alive = true;
    const reload = () =>
      void loadWorkspacePreview(workspace.workspace_id, limit + 1)
        .then((sessions) => {
          if (alive) {
            setRows(sessions);
            setError("");
            setLoading(false);
          }
        })
        .catch((err) => {
          if (alive) {
            setError(String(err.message));
            setLoading(false);
          }
        });
    reload();
    const unsubscribe = subscribeSessionChanges(reload);
    return () => {
      alive = false;
      unsubscribe();
    };
  }, [open, limit, workspace.workspace_id, props.refreshToken]);

  return (
    <div className="pt-1.5 first:pt-0">
      <div className="group/heading flex items-center gap-1 rounded-lg px-1.5 transition-colors hover:bg-[color-mix(in_srgb,var(--background)_40%,transparent)]">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => {
            const collapsed = new Set(readCollapsedGroups());
            if (open) collapsed.add(workspace.workspace_id);
            else collapsed.delete(workspace.workspace_id);
            writeCollapsedGroups([...collapsed]);
            setOpen(!open);
          }}
          className="flex min-w-0 flex-1 items-center gap-1.5 py-1 text-left text-[12.5px] font-medium text-[var(--muted-foreground)] transition-colors group-hover/heading:text-[var(--foreground)]"
        >
          <span className="flex w-3 shrink-0 items-center justify-center">
            <Folder size={11} strokeWidth={1.8} className="opacity-60" />
          </span>
          <span className="min-w-0 truncate">{workspace.display_name}</span>
          <ChevronDown
            size={11}
            strokeWidth={2}
            className={`shrink-0 opacity-50 transition-[transform,opacity] duration-150 group-hover/heading:opacity-80 ${
              open ? "" : "-rotate-90"
            }`}
          />
          <span className="flex-1" />
          {!open && rows.length ? (
            <span className="shrink-0 text-[10.5px] tabular-nums opacity-50">
              {rows.length}
            </span>
          ) : null}
        </button>
        {/* Starting a conversation here is the workspace's own action, so it
            lives on its row — revealed on hover, like every other row action in
            this column, rather than parked beside the title at all times. */}
        <button
          type="button"
          aria-label={t("New chat in {{name}}", {
            name: workspace.display_name,
          })}
          title={t("New chat in {{name}}", { name: workspace.display_name })}
          onClick={() => props.onNewChat(workspace.workspace_id)}
          disabled={workspace.status !== "ready"}
          className="shrink-0 rounded-md p-1 text-[var(--muted-foreground)] opacity-100 transition-opacity hover:text-[var(--foreground)] sm:opacity-0 focus-visible:opacity-100 group-hover/heading:opacity-100 disabled:opacity-30"
        >
          <Plus size={13} strokeWidth={1.9} />
        </button>
      </div>
      {open && (
        <div className="ml-1.5 border-l border-[color-mix(in_srgb,var(--border)_40%,transparent)] pl-1">
          {error ? (
            <p role="alert" className="px-2 py-1 text-[11px] text-[var(--destructive)]">
              {error}
            </p>
          ) : props.onOrganize && !loading ? (
            <OrganizedSessionList
              sessions={rows.slice(0, limit)}
              courses={[]}
              workspaces={props.workspaces}
              activeSessionId={props.activeSessionId ?? null}
              liveSessionIds={props.liveSessionIds}
              onSelect={props.onSelect}
              onRename={async (id, title) => { await props.onRename(id, title); await refresh(); }}
              onDelete={async (id) => { await props.onDelete(id); await refresh(); }}
              onOrganize={async (id, patch) => { await props.onOrganize!(id, patch); await refresh(); }}
            />
          ) : (
            <SessionList
              sessions={rows
                .slice(0, limit)
                .map((row) =>
                  props.liveSessionIds?.has(row.session_id)
                    ? { ...row, status: "running" as const }
                    : row,
                )}
              activeSessionId={props.activeSessionId ?? null}
              loading={loading}
              compact
              onSelect={props.onSelect}
              onRename={async (id, title) => {
                await props.onRename(id, title);
                await refresh();
              }}
              onDelete={async (id) => {
                await props.onDelete(id);
                await refresh();
              }}
            />
          )}
          {rows.length > limit && (
            <button
              type="button"
              className="px-2 py-1 text-[11px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
              onClick={() => setLimit((value) => value + 20)}
            >
              {t("Show more")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function WorkspaceChatGroups({ workspaces, ...props }: Props) {
  const { t } = useTranslation();
  const open = workspaces.filter((row) => row.kind === "workspace" && !row.archived);
  // Nothing to head a section with: workspaces are made in settings, and an
  // empty section advertising the idea is clutter in the one column a learner
  // reads on every screen.
  if (open.length === 0) return null;
  return (
    <section className="mt-3 px-2 pt-0.5">
      <div className="mb-2 px-2 text-xs text-[var(--muted-foreground)]">
        {t("Workspaces")}
      </div>
      {open.map((workspace) => (
        <WorkspaceGroup
          key={workspace.workspace_id}
          workspace={workspace}
          workspaces={workspaces}
          {...props}
        />
      ))}
    </section>
  );
}
