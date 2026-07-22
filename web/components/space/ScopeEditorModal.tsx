"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Loader2, SlidersHorizontal } from "lucide-react";
import { useTranslation } from "react-i18next";
import Modal from "@/components/common/Modal";
import Button from "@/components/ui/Button";
import ScopePicker from "@/components/space/ScopePicker";
import { deleteSession, type SessionSummary } from "@/lib/session-api";
import { importChatHistory } from "@/lib/imports-api";
import {
  ensureReadPermission,
  saveAgent,
  type ImportAgent,
} from "@/lib/chat-import/agent-store";
import { readImportMeta, sessionUnitKey } from "@/lib/chat-import/attribution";
import {
  buildSelectGroups,
  parseSessions,
  scanDirectory,
  selectionUnit,
  type AgentScope,
  type SelectGroup,
} from "@/lib/chat-import";

interface ScopeEditorModalProps {
  agent: ImportAgent;
  /** Conversations currently attributed to this agent — used to prune ones
   *  that fall out of scope after the edit. */
  ownedSessions: SessionSummary[];
  onClose: () => void;
  onSaved: () => void;
}

type Phase = "loading" | "ready" | "saving" | "error";

function initialKeys(scope: AgentScope, groups: SelectGroup[]): Set<string> {
  if (scope.kind === "all") return new Set(groups.map((g) => g.key));
  const inScope = scope.kind === "projects" ? scope.cwds : scope.days;
  const set = new Set(inScope);
  return new Set(groups.filter((g) => set.has(g.key)).map((g) => g.key));
}

/**
 * Re-pick which projects/days an agent owns. Saving re-scans the folder so new
 * conversations in still-selected units flow in, then offers to remove ones
 * that just fell out of scope so "what the agent contains" matches the picks.
 */
export default function ScopeEditorModal({
  agent,
  ownedSessions,
  onClose,
  onSaved,
}: ScopeEditorModalProps) {
  const { t, i18n } = useTranslation();
  const [phase, setPhase] = useState<Phase>("loading");
  const [groups, setGroups] = useState<SelectGroup[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const unit = selectionUnit(agent.source);

  useEffect(() => {
    let active = true;
    const run = async () => {
      try {
        if (!agent.handle || !(await ensureReadPermission(agent.handle))) {
          if (active) setPhase("error");
          return;
        }
        const scan = await scanDirectory(agent.handle);
        const next = buildSelectGroups(scan);
        if (!active) return;
        setGroups(next);
        setSelected(initialKeys(agent.scope, next));
        setPhase("ready");
      } catch {
        if (active) setPhase("error");
      }
    };
    void run();
    return () => {
      active = false;
    };
  }, [agent]);

  const toggleKey = useCallback((key: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const selectedRefs = useMemo(
    () => groups.filter((g) => selected.has(g.key)).flatMap((g) => g.sessions),
    [groups, selected],
  );

  const handleSave = useCallback(async () => {
    setPhase("saving");
    try {
      const keys = [...selected];
      const scope: AgentScope =
        unit === "dates"
          ? { kind: "dates", days: keys }
          : { kind: "projects", cwds: keys };

      // Pull in conversations for the (possibly newly) in-scope units; this
      // also backfills agent attribution on already-imported ones.
      const normalized = await parseSessions(agent.source, selectedRefs);
      await importChatHistory(agent.source, normalized, {
        id: agent.id,
        name: agent.name,
      });

      // Anything this agent owned whose unit is no longer selected is now out
      // of scope — offer to remove it so the agent only holds what was picked.
      const keySet = new Set(keys);
      const orphaned = ownedSessions.filter((s) => {
        const meta = readImportMeta(s);
        if (!meta) return false;
        return !keySet.has(sessionUnitKey(agent.source, meta, s.created_at));
      });
      if (orphaned.length > 0) {
        const ok = window.confirm(
          t(
            "{{count}} conversations are no longer in scope. Remove them from your space?",
            { count: orphaned.length },
          ),
        );
        if (ok) {
          await Promise.allSettled(
            orphaned.map((s) => deleteSession(s.session_id || s.id)),
          );
        }
      }

      await saveAgent({ ...agent, scope, lastSyncAt: Date.now() });
      onSaved();
    } catch {
      setPhase("error");
    }
  }, [agent, selected, selectedRefs, unit, ownedSessions, t, onSaved]);

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={t("Edit scope")}
      titleIcon={<SlidersHorizontal className="h-[18px] w-[18px]" />}
      width="xl"
      closeOnBackdrop={phase !== "saving"}
      closeOnEscape={phase !== "saving"}
      showCloseButton={phase !== "saving"}
      footer={
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-[12px] text-[var(--muted-foreground)]">
            {agent.name}
          </span>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>
              {t("Cancel")}
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={handleSave}
              disabled={phase !== "ready"}
            >
              {phase === "saving" ? t("Saving…") : t("Save scope")}
            </Button>
          </div>
        </div>
      }
    >
      <div className="px-5 py-5">
        {phase === "loading" && (
          <CenteredStatus
            icon={<Loader2 className="h-5 w-5 animate-spin" />}
            title={t("Reading your folder…")}
          />
        )}
        {phase === "error" && (
          <CenteredStatus
            icon={
              <AlertTriangle className="h-6 w-6 text-amber-600 dark:text-amber-400" />
            }
            title={t("Couldn't read this folder")}
            subtitle={t("Refresh failed — try re-adding the agent.")}
          />
        )}
        {(phase === "ready" || phase === "saving") && (
          <ScopePicker
            groups={groups}
            unit={unit}
            selected={selected}
            onToggle={toggleKey}
            onSelectAll={() => setSelected(new Set(groups.map((g) => g.key)))}
            onClearAll={() => setSelected(new Set())}
            lang={i18n.language}
          />
        )}
      </div>
    </Modal>
  );
}

function CenteredStatus({
  icon,
  title,
  subtitle,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
      <span className="flex h-11 w-11 items-center justify-center rounded-2xl border border-[var(--border)]/60 bg-[var(--card)] text-[var(--muted-foreground)] shadow-sm">
        {icon}
      </span>
      <div className="space-y-1">
        <p className="text-[14px] font-medium text-[var(--foreground)]">
          {title}
        </p>
        {subtitle ? (
          <p className="mx-auto max-w-sm text-[12px] leading-relaxed text-[var(--muted-foreground)]">
            {subtitle}
          </p>
        ) : null}
      </div>
    </div>
  );
}
