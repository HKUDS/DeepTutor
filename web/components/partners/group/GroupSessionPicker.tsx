"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Check, ChevronDown, MessagesSquare, Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  deletePartnerGroupSession,
  listPartnerGroupSessions,
  type PartnerGroupSession,
} from "@/lib/partner-groups-api";

/**
 * Discussion threads for one group.
 *
 * A group used to have exactly one ever-growing transcript, which also meant
 * an ever-growing public context for every Partner. Threads keep separate
 * topics apart — and make the history discoverable, since the session key
 * itself only ever lived in this browser's local storage.
 */
export default function GroupSessionPicker({
  groupId,
  sessionKey,
  onSelect,
  onCreate,
}: {
  groupId: string;
  sessionKey: string;
  onSelect: (key: string) => void;
  onCreate: () => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [sessions, setSessions] = useState<PartnerGroupSession[]>([]);
  const [busy, setBusy] = useState("");
  const rootRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(() => {
    void listPartnerGroupSessions(groupId)
      .then(setSessions)
      .catch(() => setSessions([]));
  }, [groupId]);

  // Loaded on mount so the closed button can name the open thread, and again
  // on each open because titles change as the discussion goes on.
  useEffect(() => {
    load();
  }, [load, open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const current = sessions.find((item) => item.session_key === sessionKey);
  const label = current?.title || t("New discussion");

  const remove = async (key: string) => {
    setBusy(key);
    try {
      await deletePartnerGroupSession(groupId, key);
      setSessions((rows) => rows.filter((row) => row.session_key !== key));
      // Deleting the open thread leaves nothing to show — start a fresh one.
      if (key === sessionKey) onCreate();
    } catch {
      // Keep the row; the next open reloads the authoritative list.
    } finally {
      setBusy("");
    }
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="inline-flex h-8 max-w-[190px] items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 text-[11px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
      >
        <MessagesSquare size={12} className="shrink-0" />
        <span className="hidden truncate sm:inline">{label}</span>
        <ChevronDown size={11} className="shrink-0 opacity-70" />
      </button>

      {open ? (
        <div className="absolute right-0 z-40 mt-1.5 w-[290px] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] py-1 shadow-xl">
          <button
            type="button"
            onClick={() => {
              onCreate();
              setOpen(false);
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12px] text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]"
          >
            <Plus
              size={13}
              className="shrink-0 text-[var(--muted-foreground)]"
            />
            {t("New discussion")}
          </button>

          {sessions.length ? (
            <>
              <div className="my-1 h-px bg-[var(--border)]" />
              <div className="max-h-[300px] overflow-y-auto">
                {sessions.map((item) => {
                  const active = item.session_key === sessionKey;
                  return (
                    <div
                      key={item.session_key}
                      className="group/row flex items-center gap-1 px-1"
                    >
                      <button
                        type="button"
                        onClick={() => {
                          onSelect(item.session_key);
                          setOpen(false);
                        }}
                        className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-2 text-left transition-colors hover:bg-[var(--muted)]"
                      >
                        <span className="w-3 shrink-0">
                          {active ? (
                            <Check
                              size={12}
                              className="text-[var(--foreground)]"
                            />
                          ) : null}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[12px] text-[var(--foreground)]">
                            {item.title || t("New discussion")}
                          </span>
                          <span className="block text-[10px] text-[var(--muted-foreground)]">
                            {t("{{count}} messages", {
                              count: item.message_count,
                            })}
                          </span>
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={() => remove(item.session_key)}
                        disabled={busy === item.session_key}
                        title={t("Delete")}
                        className="shrink-0 rounded-md p-1.5 text-[var(--muted-foreground)] transition-opacity hover:text-red-500 focus:opacity-100 sm:opacity-0 sm:group-hover/row:opacity-100 disabled:opacity-40"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  );
                })}
              </div>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
