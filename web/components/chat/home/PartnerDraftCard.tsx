"use client";

import { memo, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronUp,
  Loader2,
  Pencil,
  Users,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";

import type { PartnerDraftData } from "@/lib/partner-draft";
import { confirmPartnerDraft } from "@/lib/partners-api";

export const PartnerDraftCard = memo(function PartnerDraftCard({
  data,
}: {
  data: PartnerDraftData;
}) {
  const { t } = useTranslation();
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [showSoul, setShowSoul] = useState(false);
  const [name, setName] = useState(data.name);
  const [description, setDescription] = useState(data.description);
  const [soul, setSoul] = useState(data.soul);
  const [language, setLanguage] = useState(data.language);
  const [emoji, setEmoji] = useState(data.emoji || "🤝");
  const [color, setColor] = useState(data.color || "#6366f1");
  const [creating, setCreating] = useState(false);
  const [createdId, setCreatedId] = useState(data.created_partner_id || "");
  const [error, setError] = useState("");

  const confirm = async () => {
    setCreating(true);
    setError("");
    try {
      const partner = await confirmPartnerDraft(data.draft_id, {
        name,
        description,
        soul,
        language,
        emoji,
        color,
        start: true,
      });
      setCreatedId(partner.partner_id);
      setEditing(false);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t("Failed to create partner"),
      );
    } finally {
      setCreating(false);
    }
  };

  const fieldClass =
    "w-full rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[12px] text-[var(--foreground)] outline-none transition focus:border-[var(--ring)]";

  return (
    <div className="mt-3 overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-[0_1px_2px_rgba(0,0,0,0.04),0_8px_24px_rgba(0,0,0,0.05)]">
      <div className="flex items-start gap-3 p-4">
        <div
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl text-xl"
          style={{ backgroundColor: `${color}22`, color }}
        >
          {emoji}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--muted-foreground)]">
                {t("Partner draft")}
              </div>
              {!editing ? (
                <div className="mt-0.5 text-[15px] font-semibold text-[var(--foreground)]">
                  {name}
                </div>
              ) : null}
            </div>
            {!createdId ? (
              <button
                type="button"
                onClick={() => setEditing((value) => !value)}
                className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] text-[var(--muted-foreground)] transition hover:bg-[color-mix(in_srgb,var(--foreground)_6%,transparent)]"
              >
                <Pencil size={12} /> {editing ? t("Done") : t("Edit")}
              </button>
            ) : null}
          </div>

          {editing ? (
            <div className="mt-3 space-y-2.5">
              <input
                aria-label={t("Partner name")}
                value={name}
                onChange={(event) => setName(event.target.value)}
                className={fieldClass}
                placeholder={t("Partner name")}
              />
              <textarea
                aria-label={t("Description")}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                className={`${fieldClass} min-h-16 resize-y`}
                placeholder={t("Description")}
              />
              <div className="grid grid-cols-[72px_1fr_80px] gap-2">
                <input
                  aria-label={t("Emoji")}
                  value={emoji}
                  onChange={(event) => setEmoji(event.target.value)}
                  className={fieldClass}
                />
                <input
                  aria-label={t("Language")}
                  value={language}
                  onChange={(event) => setLanguage(event.target.value)}
                  className={fieldClass}
                  placeholder={t("Auto / zh / en")}
                />
                <input
                  aria-label={t("Color")}
                  value={color}
                  onChange={(event) => setColor(event.target.value)}
                  className={fieldClass}
                />
              </div>
              <textarea
                aria-label={t("Soul profile")}
                value={soul}
                onChange={(event) => setSoul(event.target.value)}
                className={`${fieldClass} min-h-48 resize-y font-mono leading-relaxed`}
              />
            </div>
          ) : (
            <>
              <p className="mt-1 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                {description}
              </p>
              <button
                type="button"
                onClick={() => setShowSoul((value) => !value)}
                className="mt-2 inline-flex items-center gap-1 text-[11px] font-medium text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              >
                {showSoul ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                {t("Soul profile")}
              </button>
              {showSoul ? (
                <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-xl bg-[color-mix(in_srgb,var(--foreground)_4%,transparent)] p-3 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
                  {soul}
                </pre>
              ) : null}
            </>
          )}

          {error ? (
            <p className="mt-3 text-[11px] text-red-500">{error}</p>
          ) : null}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {createdId ? (
              <button
                type="button"
                onClick={() =>
                  router.push(`/partners/${encodeURIComponent(createdId)}`)
                }
                className="inline-flex items-center gap-1.5 rounded-full bg-[var(--foreground)] px-3.5 py-2 text-[11.5px] font-medium text-[var(--background)]"
              >
                <Check size={13} /> {t("Open partner")}
              </button>
            ) : (
              <button
                type="button"
                disabled={creating || !name.trim() || !soul.trim()}
                onClick={confirm}
                className="inline-flex items-center gap-1.5 rounded-full bg-[var(--foreground)] px-3.5 py-2 text-[11.5px] font-medium text-[var(--background)] transition disabled:cursor-not-allowed disabled:opacity-50"
              >
                {creating ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : (
                  <Users size={13} />
                )}
                {creating ? t("Creating…") : t("Confirm & create")}
              </button>
            )}
            <span className="text-[10.5px] text-[var(--muted-foreground)]">
              {createdId
                ? t("Partner created")
                : t("Nothing is created until you confirm")}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
});

PartnerDraftCard.displayName = "PartnerDraftCard";
