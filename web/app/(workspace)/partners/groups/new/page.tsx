"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Check, Loader2, Plus, Users } from "lucide-react";
import { useTranslation } from "react-i18next";

import PartnerAvatar, {
  PARTNER_COLORS,
} from "@/components/partners/PartnerAvatar";
import DiscussionModePicker from "@/components/partners/group/DiscussionModePicker";
import { createPartnerGroup } from "@/lib/partner-groups-api";
import { listPartners, type PartnerInfo } from "@/lib/partners-api";

export default function NewPartnerGroupPage() {
  const { t } = useTranslation();
  const router = useRouter();
  const [partners, setPartners] = useState<PartnerInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [emoji, setEmoji] = useState("👥");
  // Groups share the Partner palette so a roster of avatars and group icons
  // reads as one family, rather than introducing a second set of hues.
  const [color, setColor] = useState<string>(PARTNER_COLORS[0]);
  const [mode, setMode] = useState("panel_parallel");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void listPartners()
      .then(setPartners)
      .catch(() => setPartners([]))
      .finally(() => setLoading(false));
  }, []);

  const selectedPartners = useMemo(
    () => partners.filter((partner) => selected.has(partner.partner_id)),
    [partners, selected],
  );
  const ready = Boolean(name.trim()) && selected.size >= 2;

  const toggle = (partnerId: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(partnerId)) next.delete(partnerId);
      else next.add(partnerId);
      return next;
    });
  };

  const submit = async () => {
    if (!ready) return;
    setCreating(true);
    setError("");
    try {
      const group = await createPartnerGroup({
        name: name.trim(),
        description: description.trim(),
        member_ids: Array.from(selected),
        discussion_mode: mode,
        shared_memory: "whiteboard",
        emoji,
        color,
      });
      router.push(`/partners/groups/${encodeURIComponent(group.group_id)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Create failed"));
      setCreating(false);
    }
  };

  return (
    <div className="mx-auto h-full max-w-3xl overflow-y-auto px-6 py-7">
      <Link
        href="/partners"
        className="inline-flex items-center gap-1.5 text-[12px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
      >
        <ArrowLeft size={14} /> {t("Partners")}
      </Link>

      <h1 className="mt-6 text-[20px] font-semibold tracking-tight text-[var(--foreground)]">
        {t("Create a Partner Group")}
      </h1>
      <p className="mt-1 text-[12.5px] text-[var(--muted-foreground)]">
        {t("Choose at least two Partners, then how they should discuss.")}
      </p>

      {/* A live card of the thing being made: emoji, colour and name only mean
          something once you can see them together the way the list will. */}
      <div className="mt-6 flex items-start gap-3 rounded-2xl border border-[var(--border)] p-4">
        <div
          className="flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded-2xl text-xl"
          // Tinted enough that picking a colour visibly changes the card.
          style={{ backgroundColor: `${color}2e`, color }}
        >
          {emoji || "👥"}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[14px] font-medium text-[var(--foreground)]">
            {name.trim() || (
              <span className="text-[var(--muted-foreground)]">
                {t("Untitled group")}
              </span>
            )}
          </div>
          {description.trim() ? (
            <p className="mt-0.5 line-clamp-2 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
              {description}
            </p>
          ) : null}
          <div className="mt-2 flex items-center gap-2">
            {selectedPartners.length ? (
              <div className="flex -space-x-1.5">
                {selectedPartners.slice(0, 6).map((partner) => (
                  <PartnerAvatar
                    key={partner.partner_id}
                    name={partner.name}
                    emoji={partner.emoji}
                    color={partner.color}
                    image={partner.avatar}
                    size={20}
                    className="ring-2 ring-[var(--background)]"
                  />
                ))}
              </div>
            ) : null}
            <span className="text-[11px] text-[var(--muted-foreground)]">
              {selected.size < 2
                ? t("Pick {{count}} more Partner(s)", {
                    count: 2 - selected.size,
                  })
                : t("{{count}} members", { count: selected.size })}
            </span>
          </div>
        </div>
      </div>

      <div className="mt-7 space-y-7">
        <section>
          <h2 className="mb-2 text-[12px] font-medium text-[var(--foreground)]">
            {t("Name")}
          </h2>
          <div className="flex gap-2">
            <input
              value={emoji}
              onChange={(event) => setEmoji(event.target.value.slice(0, 4))}
              aria-label={t("Emoji")}
              className="w-[64px] shrink-0 rounded-xl border border-[var(--border)] bg-[var(--card)] px-2 py-2.5 text-center text-xl outline-none focus:border-[var(--ring)]"
            />
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("Group name")}
              className="min-w-0 flex-1 rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2.5 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
            />
          </div>
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder={t("What will this group help you learn or decide?")}
            rows={2}
            className="mt-2 w-full resize-none rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2.5 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
          />
          <div className="mt-3 flex items-center gap-2">
            {PARTNER_COLORS.map((preset) => (
              <button
                key={preset}
                type="button"
                aria-label={preset}
                onClick={() => setColor(preset)}
                className="flex h-6 w-6 items-center justify-center rounded-full transition-transform hover:scale-110"
                style={{ background: preset }}
              >
                {color === preset ? (
                  <span className="h-2 w-2 rounded-full bg-white/90" />
                ) : null}
              </button>
            ))}
          </div>
        </section>

        <section>
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-[12px] font-medium text-[var(--foreground)]">
              {t("Members")}
            </h2>
            <span
              className={`text-[11px] ${
                selected.size >= 2
                  ? "text-[var(--foreground)]"
                  : "text-[var(--muted-foreground)]"
              }`}
            >
              {t("{{count}} selected", { count: selected.size })}
            </span>
          </div>

          {loading ? (
            <div className="flex h-32 items-center justify-center">
              <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
            </div>
          ) : partners.length < 2 ? (
            <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-[var(--border)] p-6 text-center">
              <p className="text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                {t(
                  "A group needs at least two Partners. Create one more first.",
                )}
              </p>
              <Link
                href="/partners/new"
                className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)]"
              >
                <Plus size={13} /> {t("New partner")}
              </Link>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {partners.map((partner) => {
                const active = selected.has(partner.partner_id);
                return (
                  <button
                    key={partner.partner_id}
                    type="button"
                    onClick={() => toggle(partner.partner_id)}
                    className={`flex items-center gap-3 rounded-xl border p-3 text-left transition-colors ${
                      active
                        ? "border-[var(--primary)] bg-[var(--primary)]/[0.05]"
                        : "border-[var(--border)] hover:border-[var(--ring)]"
                    }`}
                  >
                    <PartnerAvatar
                      name={partner.name}
                      emoji={partner.emoji}
                      color={partner.color}
                      image={partner.avatar}
                      size={34}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[12.5px] font-medium text-[var(--foreground)]">
                        {partner.name}
                      </div>
                      {partner.description ? (
                        <div className="truncate text-[10.5px] text-[var(--muted-foreground)]">
                          {partner.description}
                        </div>
                      ) : null}
                    </div>
                    <span
                      className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${
                        active
                          ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                          : "border-[var(--border)]"
                      }`}
                    >
                      {active ? <Check size={12} /> : null}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </section>

        <DiscussionModePicker
          value={mode}
          onChange={setMode}
          title={t("How they discuss")}
          note={t(
            "Whatever the mode, each member's tool traces and intermediate reasoning stay private.",
          )}
        />

        {error ? <p className="text-[12px] text-red-500">{error}</p> : null}

        <div className="flex justify-end pb-8">
          <button
            type="button"
            onClick={submit}
            disabled={creating || !ready}
            className="inline-flex items-center gap-2 rounded-lg bg-[var(--primary)] px-4 py-2.5 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {creating ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Users size={14} />
            )}
            {creating ? t("Creating…") : t("Create group")}
          </button>
        </div>
      </div>
    </div>
  );
}
