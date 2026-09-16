"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Trash2, RotateCcw, ChevronDown, ChevronRight } from "lucide-react";
import {
  listRecycleBin,
  restoreSession,
  purgeSession,
  type SessionSummary,
} from "@/lib/session-api";

export function RecycleBinSection() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await listRecycleBin();
      setSessions(result);
    } catch {
      setSessions([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const handleRestore = useCallback(
    async (sessionId: string) => {
      await restoreSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
    },
    [],
  );

  const handlePurge = useCallback(
    async (sessionId: string) => {
      if (!window.confirm(t("Permanently delete this session?"))) return;
      await purgeSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
    },
    [t],
  );

  return (
    <div className="border-t border-[var(--border)] px-2 py-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] hover:bg-[var(--muted)]/50"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0" />
        )}
        <Trash2 className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate">{t("Recycle Bin")}</span>
        {sessions.length > 0 && (
          <span className="ml-auto shrink-0 rounded-full bg-[var(--muted)] px-1.5 text-[10px] leading-[18px] text-[var(--muted-foreground)]">
            {sessions.length}
          </span>
        )}
      </button>
      {open && (
        <div className="mt-1 max-h-[240px] overflow-y-auto">
          {loading ? (
            <p className="px-3 py-2 text-[11px] text-[var(--muted-foreground)]">{t("Loading...")}</p>
          ) : sessions.length === 0 ? (
            <p className="px-3 py-2 text-[11px] text-[var(--muted-foreground)]">{t("No deleted chats")}</p>
          ) : (
            sessions.map((session) => (
              <div
                key={session.session_id}
                className="group flex items-center gap-1 rounded-md px-2 py-1.5 text-[12px] hover:bg-[var(--muted)]/40"
              >
                <span className="min-w-0 flex-1 truncate text-[var(--foreground)]">
                  {session.title || session.session_id}
                </span>
                <button
                  type="button"
                  onClick={() => void handleRestore(session.session_id)}
                  title={t("Restore")}
                  className="shrink-0 rounded p-1 text-[var(--muted-foreground)] opacity-0 hover:bg-[var(--muted)] hover:text-[var(--foreground)] group-hover:opacity-100"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => void handlePurge(session.session_id)}
                  title={t("Delete permanently")}
                  className="shrink-0 rounded p-1 text-[var(--destructive)] opacity-0 hover:bg-[var(--destructive)]/10 group-hover:opacity-100"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
