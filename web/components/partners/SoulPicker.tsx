"use client";

/**
 * Soul source selector for the creation wizard: start from the library, clone
 * one of the chat personas, or write a custom soul. Whatever the source, the
 * chosen text lands in the SoulEditor below — the text IS the partner's
 * SOUL.md, and editing it detaches a private custom copy. A custom soul can
 * be saved back into the shared library for future partners.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  BookHeart,
  Check,
  Loader2,
  Save,
  Sparkles,
  UserRound,
} from "lucide-react";
import {
  createSoulTemplate,
  getSoulSources,
  type SoulSources,
  type SoulSpec,
} from "@/lib/partners-api";
import SoulEditor from "@/components/partners/SoulEditor";

type SourceTab = "library" | "persona" | "custom";

// Soul ids ride in /souls/<id> URLs, so keep them ASCII/URL-safe (a CJK id is
// unreachable) — the server re-slugs authoritatively and the create flow uses
// the returned id, but producing an ASCII slug here keeps the preview honest
// and avoids sending a non-ASCII id over the wire.
function slugifySoulId(name: string): string {
  return (
    name
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || `soul-${Date.now().toString(36)}`
  );
}

export default function SoulPicker({
  value,
  onChange,
}: {
  value: SoulSpec;
  onChange: (next: SoulSpec) => void;
}) {
  const { t } = useTranslation();
  const [sources, setSources] = useState<SoulSources | null>(null);
  const [tab, setTab] = useState<SourceTab>(
    value.source === "persona"
      ? "persona"
      : value.source === "custom"
        ? "custom"
        : "library",
  );
  const [saveName, setSaveName] = useState("");
  const [saving, setSaving] = useState(false);
  const [savedId, setSavedId] = useState("");
  const [saveError, setSaveError] = useState("");

  useEffect(() => {
    void (async () => {
      try {
        setSources(await getSoulSources());
      } catch {
        setSources({ library: [], personas: [] });
      }
    })();
  }, []);

  // Untouched wizard ("default" source) → preselect the first library soul
  // so the editor is visible and the actual content explicit from the start.
  useEffect(() => {
    if (value.source !== "default") return;
    const first = sources?.library[0];
    if (first)
      onChange({ source: "library", id: first.id, content: first.content });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once when sources land
  }, [sources]);

  const tabs: { key: SourceTab; label: string; icon: typeof Sparkles }[] = [
    { key: "library", label: t("Soul library"), icon: BookHeart },
    { key: "persona", label: t("Clone a persona"), icon: UserRound },
    { key: "custom", label: t("Write your own"), icon: Sparkles },
  ];

  const selectLibrary = (id: string) => {
    const entry = sources?.library.find((s) => s.id === id);
    onChange({ source: "library", id, content: entry?.content });
  };

  const selectPersona = (name: string) => {
    const entry = sources?.personas.find((p) => p.name === name);
    onChange({ source: "persona", id: name, content: entry?.content });
  };

  // Typing into the editor detaches a private copy of whatever was selected.
  const editContent = (next: string) =>
    onChange({ source: "custom", content: next });

  // A template/persona was edited into a private copy on this tab.
  const detached = tab !== "custom" && value.source === "custom";

  const saveToLibrary = async () => {
    const content = (value.content ?? "").trim();
    const name = saveName.trim();
    if (!content || !name) return;
    setSaving(true);
    setSaveError("");
    try {
      const entry = await createSoulTemplate(
        slugifySoulId(name),
        name,
        content,
      );
      setSavedId(entry.id);
      setSources(await getSoulSources());
      // Keep the wizard pointed at the (identical) library entry.
      onChange({ source: "library", id: entry.id, content });
      setTab("library");
      setSaveName("");
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : t("Save failed"));
    } finally {
      setSaving(false);
    }
  };

  const showEditor = tab === "custom" || value.content !== undefined;

  return (
    <div className="space-y-4">
      <div className="flex w-fit gap-1 rounded-xl bg-[var(--muted)] p-1">
        {tabs.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => {
              setTab(key);
              if (key === "custom")
                onChange({ source: "custom", content: value.content ?? "" });
            }}
            className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] transition-all duration-150 ${
              tab === key
                ? "bg-[var(--background)] font-medium text-[var(--foreground)] shadow-sm"
                : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            }`}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      {tab === "library" && (
        <div className="flex flex-wrap gap-2">
          {(sources?.library ?? []).map((soul) => (
            <button
              key={soul.id}
              type="button"
              onClick={() => selectLibrary(soul.id)}
              className={`rounded-full border px-3.5 py-1.5 text-[13px] transition-all duration-150 active:scale-[0.97] ${
                value.source === "library" && value.id === soul.id
                  ? "border-[var(--primary)] bg-[var(--secondary)] font-medium text-[var(--primary)]"
                  : "border-[var(--border)] text-[var(--muted-foreground)] hover:border-[var(--ring)] hover:text-[var(--foreground)]"
              }`}
            >
              {soul.name}
              {savedId === soul.id && (
                <Check className="ml-1 inline h-3.5 w-3.5 text-[var(--primary)]" />
              )}
            </button>
          ))}
          {sources && sources.library.length === 0 && (
            <p className="text-[13px] text-[var(--muted-foreground)]">
              {t("No soul templates yet.")}
            </p>
          )}
        </div>
      )}

      {tab === "persona" && (
        <div className="flex flex-wrap gap-2">
          {(sources?.personas ?? []).map((persona) => (
            <button
              key={persona.name}
              type="button"
              onClick={() => selectPersona(persona.name)}
              title={persona.description}
              className={`rounded-full border px-3.5 py-1.5 text-[13px] transition-all duration-150 active:scale-[0.97] ${
                value.source === "persona" && value.id === persona.name
                  ? "border-[var(--primary)] bg-[var(--secondary)] font-medium text-[var(--primary)]"
                  : "border-[var(--border)] text-[var(--muted-foreground)] hover:border-[var(--ring)] hover:text-[var(--foreground)]"
              }`}
            >
              {persona.name}
            </button>
          ))}
          {sources && sources.personas.length === 0 && (
            <p className="text-[13px] text-[var(--muted-foreground)]">
              {t("No personas in your chat workspace yet.")}
            </p>
          )}
        </div>
      )}

      {showEditor && (
        <div className="space-y-2">
          <SoulEditor value={value.content ?? ""} onChange={editContent} />
          {tab === "persona" && value.source === "persona" && value.id && (
            <p className="text-[12px] leading-relaxed text-[var(--muted-foreground)]">
              {t(
                "The persona's markdown is copied into the partner — later edits to the persona won't affect it.",
              )}
            </p>
          )}
          {detached && (
            <p className="text-[12px] leading-relaxed text-[var(--muted-foreground)]">
              {t(
                "Edited — your version becomes this partner's soul. The original template is untouched.",
              )}
            </p>
          )}
        </div>
      )}

      {tab === "custom" && (value.content ?? "").trim() && (
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={saveName}
            onChange={(e) => setSaveName(e.target.value)}
            placeholder={t("Template name")}
            className="w-48 rounded-lg border border-[var(--border)] bg-transparent px-3 py-1.5 text-[13px] outline-none transition-colors focus:border-[var(--ring)]"
          />
          <button
            type="button"
            onClick={() => void saveToLibrary()}
            disabled={saving || !saveName.trim()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[13px] font-medium text-[var(--foreground)] transition-all duration-150 hover:border-[var(--ring)] active:scale-[0.98] disabled:opacity-40"
          >
            {saving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            {t("Save to soul library")}
          </button>
          {saveError && (
            <span className="text-[12px] text-[var(--destructive)]">
              {saveError}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
