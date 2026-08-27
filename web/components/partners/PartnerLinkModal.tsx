"use client";

/**
 * Connect a chat account (QQ, Telegram, …) to your DeepTutor account.
 *
 * Without a link, a partner reached over a channel sees only a channel-local
 * sender id: the conversation lands in a shared pool you cannot read back here,
 * and the partner answers without your library or memory. Claiming a code from
 * that chat account closes the gap — and the code is deliberately short-lived
 * and single-use, since whoever sends it becomes you for that partner.
 */

import { useCallback, useEffect, useState } from "react";
import { Check, Copy, Link2, Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  createPartnerLinkCode,
  listPartnerLinks,
  removePartnerLink,
  type PartnerLink,
  type PartnerLinkCode,
} from "@/lib/partners-api";
import ChannelIcon from "@/components/partners/ChannelIcon";

export default function PartnerLinkModal({
  partnerId,
  partnerName,
  onClose,
}: {
  partnerId: string;
  partnerName: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [links, setLinks] = useState<PartnerLink[]>([]);
  const [code, setCode] = useState<PartnerLinkCode | null>(null);
  const [loading, setLoading] = useState(true);
  const [issuing, setIssuing] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setLinks(await listPartnerLinks(partnerId));
    } catch {
      setLinks([]);
    } finally {
      setLoading(false);
    }
  }, [partnerId]);

  useEffect(() => {
    void load();
  }, [load]);

  const issue = useCallback(async () => {
    setIssuing(true);
    setError("");
    setCopied(false);
    try {
      setCode(await createPartnerLinkCode(partnerId));
    } catch {
      setError(t("Couldn't create a code. Try again."));
    } finally {
      setIssuing(false);
    }
  }, [partnerId, t]);

  const copy = useCallback(async () => {
    if (!code) return;
    try {
      await navigator.clipboard.writeText(code.command);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError(t("Couldn't copy — select the command and copy it by hand."));
    }
  }, [code, t]);

  const unlink = useCallback(
    async (key: string) => {
      try {
        await removePartnerLink(partnerId, key);
        await load();
      } catch {
        setError(t("Couldn't disconnect that account. Try again."));
      }
    },
    [partnerId, load, t],
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--background)] p-5 shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[15px] font-semibold text-[var(--foreground)]">
              {t("Link a chat account")}
            </h2>
            <p className="mt-1 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
              {t(
                "Connect the account you message {{name}} from, so those conversations are private to you and it can reach your library and notes there.",
                { name: partnerName },
              )}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("Close")}
            className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {code ? (
          <div className="rounded-xl border border-[var(--border)] bg-[var(--muted)] p-3.5">
            <p className="text-[12px] text-[var(--muted-foreground)]">
              {t(
                "Send this to {{name}} as a direct message from the chat account you want to connect:",
                { name: partnerName },
              )}
            </p>
            <div className="mt-2 flex items-center gap-2">
              <code className="flex-1 select-all rounded-lg bg-[var(--background)] px-3 py-2 font-mono text-[13.5px] text-[var(--foreground)]">
                {code.command}
              </code>
              <button
                type="button"
                onClick={() => void copy()}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-2 text-[12px] text-[var(--foreground)] hover:bg-[var(--background)]"
              >
                {copied ? (
                  <Check className="h-3.5 w-3.5 text-emerald-500" />
                ) : (
                  <Copy className="h-3.5 w-3.5" />
                )}
                {copied ? t("Copied") : t("Copy")}
              </button>
            </div>
            <p className="mt-2 text-[11.5px] text-[var(--muted-foreground)]">
              {t("Valid for 15 minutes, and usable once.")}
            </p>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => void issue()}
            disabled={issuing}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-2.5 text-[12.5px] font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:opacity-60"
          >
            {issuing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Link2 className="h-3.5 w-3.5" />
            )}
            {t("Get a link code")}
          </button>
        )}

        {error ? (
          <p className="mt-2 text-[12px] text-red-500">{error}</p>
        ) : null}

        <div className="mt-4">
          <h3 className="text-[12px] font-medium text-[var(--foreground)]">
            {t("Connected accounts")}
          </h3>
          {loading ? (
            <Loader2 className="mt-2 h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
          ) : links.length === 0 ? (
            <p className="mt-1.5 text-[12px] text-[var(--muted-foreground)]">
              {t("No chat accounts connected yet.")}
            </p>
          ) : (
            <ul className="mt-2 space-y-1.5">
              {links.map((link) => (
                <li
                  key={link.key}
                  className="flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2"
                >
                  <ChannelIcon name={link.channel} size={13} />
                  <span className="flex-1 truncate text-[12.5px] text-[var(--foreground)]">
                    {link.channel} · {link.sender_id}
                  </span>
                  <button
                    type="button"
                    onClick={() => void unlink(link.key)}
                    className="text-[11.5px] text-[var(--muted-foreground)] hover:text-red-500"
                  >
                    {t("Disconnect")}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
