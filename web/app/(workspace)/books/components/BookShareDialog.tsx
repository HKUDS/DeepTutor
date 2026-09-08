"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Share2, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { notify } from "@/lib/notifications";
import { bookApi } from "@/lib/book-api";
import { bookErrorMessage } from "@/lib/book-errors";
import type { BookShareLevel, BookShareState } from "@/lib/book-api";

/**
 * Owner-side share management for one personal book. The dialog lists who the
 * book is already shared with (revocable) and grants read/edit to another
 * account. Access only ever moves one explicit user at a time — there is no
 * public or role-wide mode to reach for.
 */
export default function BookShareDialog({
  bookId,
  bookTitle,
  onClose,
}: {
  bookId: string;
  bookTitle: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [state, setState] = useState<BookShareState | null>(null);
  const [loading, setLoading] = useState(true);
  const [userId, setUserId] = useState("");
  const [level, setLevel] = useState<BookShareLevel>("read");
  const [pending, setPending] = useState(false);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const next = await bookApi.listShares(bookId);
      setState(next);
    } catch (error) {
      notify(bookErrorMessage(error, t), { tone: 'error' })
      onClose()
    } finally {
      setLoading(false);
    }
  }, [bookId, onClose, t]);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !pending) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [pending, onClose]);

  const grant = async () => {
    if (!userId || pending) return;
    setPending(true);
    try {
      await bookApi.grantShare(bookId, { user_id: userId, level });
      setUserId("");
      setLevel("read");
      await reload();
    } catch (error) {
      notify(bookErrorMessage(error, t), { tone: 'error' })
    } finally {
      setPending(false);
    }
  };

  const revoke = async (targetUserId: string) => {
    if (revokingId) return;
    setRevokingId(targetUserId);
    try {
      await bookApi.revokeShare(bookId, targetUserId);
      await reload();
    } catch (error) {
      notify(bookErrorMessage(error, t), { tone: 'error' })
    } finally {
      setRevokingId(null);
    }
  };

  const grantedIds = new Set((state?.shares ?? []).map((item) => item.user_id));
  const available = (state?.candidates ?? []).filter(
    (candidate) => !grantedIds.has(candidate.user_id),
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] px-4"
      role="dialog"
      aria-modal="true"
      aria-label={t("Share book")}
      onClick={() => {
        if (!pending && !revokingId) onClose();
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-sm rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-xl"
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-base font-semibold text-[var(--foreground)]">
            <Share2 size={15} className="text-[var(--muted-foreground)]" />
            {t("Share book")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--foreground)]"
            aria-label={t("Close")}
          >
            <X size={16} />
          </button>
        </div>
        <p className="mb-4 truncate text-xs text-[var(--muted-foreground)]">
          {bookTitle}
        </p>

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-8 text-sm text-[var(--muted-foreground)]">
            <Loader2 size={15} className="animate-spin" />
            {t("Loading…")}
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <div className="text-xs font-medium text-[var(--foreground)]">
                {t("Shared with")}
              </div>
              {(state?.shares ?? []).length === 0 ? (
                <div className="rounded-lg border border-dashed border-[var(--border)] px-3 py-3 text-xs text-[var(--muted-foreground)]">
                  {t("Not shared with anyone yet.")}
                </div>
              ) : (
                <ul className="flex flex-col gap-1">
                  {(state?.shares ?? []).map((item) => (
                    <li
                      key={item.user_id}
                      className="flex items-center justify-between rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs"
                    >
                      <span className="truncate text-[var(--foreground)]">
                        {item.username}
                      </span>
                      <span className="flex items-center gap-2">
                        <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
                          {item.level === "edit" ? t("Can edit") : t("Can read")}
                        </span>
                        <button
                          type="button"
                          onClick={() => void revoke(item.user_id)}
                          disabled={revokingId !== null}
                          className="text-[var(--muted-foreground)] transition-colors hover:text-rose-600 disabled:opacity-40"
                          aria-label={t("Revoke access")}
                        >
                          {revokingId === item.user_id ? (
                            <Loader2 size={12} className="animate-spin" />
                          ) : (
                            <X size={12} />
                          )}
                        </button>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="flex flex-col gap-2">
              <div className="text-xs font-medium text-[var(--foreground)]">
                {t("Share with")}
              </div>
              <div className="flex items-center gap-2">
                <select
                  value={userId}
                  onChange={(e) => setUserId(e.target.value)}
                  className="h-8 min-w-0 flex-1 rounded-md border border-[var(--border)] bg-[var(--secondary)]/30 px-2 text-xs text-[var(--foreground)] focus:border-[var(--primary)]/40 focus:outline-none"
                >
                  <option value="">{t("Select a user")}</option>
                  {available.map((candidate) => (
                    <option key={candidate.user_id} value={candidate.user_id}>
                      {candidate.username}
                    </option>
                  ))}
                </select>
                <select
                  value={level}
                  onChange={(e) => setLevel(e.target.value as BookShareLevel)}
                  className="h-8 rounded-md border border-[var(--border)] bg-[var(--secondary)]/30 px-2 text-xs text-[var(--foreground)] focus:border-[var(--primary)]/40 focus:outline-none"
                >
                  <option value="read">{t("Can read")}</option>
                  <option value="edit">{t("Can edit")}</option>
                </select>
                <button
                  type="button"
                  onClick={() => void grant()}
                  disabled={!userId || pending}
                  className="inline-flex h-8 items-center gap-1 rounded-md bg-[var(--primary)] px-3 text-xs font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-40"
                >
                  {pending && <Loader2 size={12} className="animate-spin" />}
                  {t("Share")}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
