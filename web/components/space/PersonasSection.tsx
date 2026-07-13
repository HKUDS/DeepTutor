"use client";

import { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { useTranslation } from "react-i18next";
import {
  Eye,
  Loader2,
  Lock,
  Pencil,
  Plus,
  Sparkles,
  Trash2,
  UserRound,
  X,
} from "lucide-react";
import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import { isValidSkillName, slugifySkillName } from "@/lib/skill-slug";
import {
  createPersona,
  deletePersona,
  getPersona,
  listPersonas,
  updatePersona,
  type PersonaInfo,
} from "@/lib/personas-api";

interface PersonaEditorState {
  mode: "create" | "edit";
  originalName: string | null;
  name: string;
  description: string;
  content: string;
  saving: boolean;
  error: string | null;
}

interface PersonaViewerState {
  name: string;
  source?: string;
  readOnly: boolean;
  description: string;
  content: string;
  loading: boolean;
  error: string | null;
}

// Lazy-load the markdown renderer so the heavier markdown deps only ship
// when a user actually opens a persona viewer (matches SkillsSection).
const PersonaMarkdown = dynamic(
  () => import("@/components/common/SimpleMarkdownRenderer"),
  { ssr: false },
);

/** Drop the YAML frontmatter block so the viewer shows just the playbook. */
function stripFrontmatter(md: string): string {
  const match = md.match(/^---\s*\n[\s\S]*?\n---\s*\n?/);
  return match ? md.slice(match[0].length) : md;
}

export default function PersonasSection() {
  const { t } = useTranslation();

  const [personas, setPersonas] = useState<PersonaInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [editor, setEditor] = useState<PersonaEditorState | null>(null);
  const [viewer, setViewer] = useState<PersonaViewerState | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const items = await listPersonas({ force: true });
      setPersonas(items);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // ── editor handlers ───────────────────────────────────────────────

  const openCreate = useCallback(() => {
    setEditor({
      mode: "create",
      originalName: null,
      name: "",
      description: "",
      content:
        "# My Persona\n\nDescribe the tone, attitude, and communication style the assistant should adopt.\n",
      saving: false,
      error: null,
    });
  }, []);

  const openEdit = useCallback(async (name: string) => {
    setEditor({
      mode: "edit",
      originalName: name,
      name,
      description: "",
      content: "",
      saving: true,
      error: null,
    });
    try {
      const detail = await getPersona(name);
      setEditor({
        mode: "edit",
        originalName: name,
        name: detail.name,
        description: detail.description,
        content: detail.content,
        saving: false,
        error: null,
      });
    } catch (err) {
      setEditor((prev) =>
        prev
          ? {
              ...prev,
              saving: false,
              error: err instanceof Error ? err.message : String(err),
            }
          : prev,
      );
    }
  }, []);

  const openView = useCallback(async (persona: PersonaInfo) => {
    setViewer({
      name: persona.name,
      source: persona.source,
      readOnly: Boolean(persona.read_only),
      description: persona.description,
      content: "",
      loading: true,
      error: null,
    });
    try {
      const detail = await getPersona(persona.name);
      setViewer({
        name: detail.name,
        source: detail.source ?? persona.source,
        readOnly: Boolean(detail.read_only),
        description: detail.description,
        content: detail.content,
        loading: false,
        error: null,
      });
    } catch (err) {
      setViewer((prev) =>
        prev
          ? {
              ...prev,
              loading: false,
              error: err instanceof Error ? err.message : String(err),
            }
          : prev,
      );
    }
  }, []);

  const handleSave = useCallback(async () => {
    if (!editor) return;
    const trimmedName = editor.name.trim();
    if (!trimmedName) {
      setEditor({ ...editor, error: t("Name is required") });
      return;
    }
    if (!isValidSkillName(trimmedName)) {
      setEditor({
        ...editor,
        error: t(
          "Name must use only lowercase letters, digits, and hyphens, and must start with a letter or digit.",
        ),
      });
      return;
    }
    setEditor({ ...editor, saving: true, error: null });
    try {
      if (editor.mode === "create") {
        await createPersona({
          name: trimmedName,
          description: editor.description,
          content: editor.content,
        });
      } else if (editor.originalName) {
        await updatePersona(editor.originalName, {
          description: editor.description,
          content: editor.content,
          rename_to:
            trimmedName !== editor.originalName ? trimmedName : undefined,
        });
      }
      setEditor(null);
      await load();
    } catch (err) {
      setEditor((prev) =>
        prev
          ? {
              ...prev,
              saving: false,
              error: err instanceof Error ? err.message : String(err),
            }
          : prev,
      );
    }
  }, [editor, load, t]);

  const handleDelete = useCallback(
    async (name: string) => {
      if (!window.confirm(t('Delete persona "{{name}}"?', { name }))) return;
      setDeleting(name);
      try {
        await deletePersona(name);
        await load();
      } catch (err) {
        setErrorMsg(err instanceof Error ? err.message : String(err));
      } finally {
        setDeleting(null);
      }
    },
    [load, t],
  );

  // ── render ────────────────────────────────────────────────────────

  const editorNameInvalid = Boolean(
    editor?.name && !isValidSkillName(editor.name),
  );

  return (
    <div className="space-y-6">
      <SpaceSectionHeader
        icon={UserRound}
        title={t("Personas")}
        description={t(
          "Behavior presets that shape the assistant's tone and style. Apply one per chat turn from the composer.",
        )}
        meta={
          <span className="rounded-full border border-[var(--border)] bg-[var(--card)] px-2 py-0.5 text-[10.5px] font-medium text-[var(--muted-foreground)]">
            {personas.length} {t("personas.count.suffix")}
          </span>
        }
        action={
          <button
            onClick={openCreate}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-1.5 text-[12.5px] font-medium text-[var(--primary-foreground)] shadow-sm transition-opacity hover:opacity-90"
          >
            <Plus size={13} strokeWidth={2} />
            {t("New persona")}
          </button>
        }
      />

      {errorMsg && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          {errorMsg}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
        </div>
      ) : personas.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--card)]/40 px-6 py-14 text-center">
          <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--muted)]/60 text-[var(--muted-foreground)]">
            <Sparkles size={18} />
          </div>
          <p className="text-[14px] font-medium text-[var(--foreground)]">
            {t("No personas yet")}
          </p>
          <p className="mx-auto mt-1 max-w-sm text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "Create a persona to define a reusable behavior preset (e.g. a patient tutor, a blunt code reviewer).",
            )}
          </p>
          <button
            onClick={openCreate}
            className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-1.5 text-[12.5px] font-medium text-[var(--primary-foreground)] shadow-sm transition-opacity hover:opacity-90"
          >
            <Plus size={13} strokeWidth={2} />
            {t("Create your first persona")}
          </button>
        </div>
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {personas.map((persona) => {
            const readOnly = Boolean(persona.read_only);
            return (
              <li
                key={persona.name}
                role="button"
                tabIndex={0}
                onClick={() => void openView(persona)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    void openView(persona);
                  }
                }}
                title={t("View persona")}
                className="group relative flex cursor-pointer flex-col rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm transition-all hover:border-[var(--foreground)]/30 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]/40"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-start gap-2.5">
                    <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-[var(--border)]/60 bg-[var(--background)] text-[var(--muted-foreground)]">
                      <UserRound size={13} strokeWidth={1.6} />
                    </span>
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-[14px] font-semibold tracking-tight text-[var(--foreground)]">
                          {persona.name}
                        </span>
                        {persona.source === "admin" ? (
                          <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                            {readOnly ? <Lock size={9} /> : null}
                            {t("Preset")}
                          </span>
                        ) : null}
                      </div>
                      {persona.description ? (
                        <p className="mt-0.5 line-clamp-2 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                          {persona.description}
                        </p>
                      ) : (
                        <p className="mt-0.5 text-[12px] italic text-[var(--muted-foreground)]/60">
                          {t("No description.")}
                        </p>
                      )}
                    </div>
                  </div>
                  {readOnly ? (
                    <span className="shrink-0 text-[var(--muted-foreground)] opacity-0 transition-opacity group-hover:opacity-100">
                      <Eye size={13} />
                    </span>
                  ) : (
                    <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          void openEdit(persona.name);
                        }}
                        className="rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                        title={t("Edit")}
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleDelete(persona.name);
                        }}
                        disabled={deleting === persona.name}
                        className="rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-50 dark:hover:bg-red-950/30"
                        title={t("Delete")}
                      >
                        {deleting === persona.name ? (
                          <Loader2 size={13} className="animate-spin" />
                        ) : (
                          <Trash2 size={13} />
                        )}
                      </button>
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {/* Viewer modal — read-only content view, available for every persona */}
      {viewer && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] p-4"
          role="dialog"
          aria-modal="true"
          onClick={() => setViewer(null)}
        >
          <div
            className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--background)] shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-5 py-3">
              <div className="flex min-w-0 items-center gap-2">
                <UserRound
                  size={14}
                  className="shrink-0 text-[var(--muted-foreground)]"
                />
                <h3 className="truncate text-[14px] font-semibold text-[var(--foreground)]">
                  {viewer.name}
                </h3>
                {viewer.readOnly ? (
                  <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                    <Lock size={9} />
                    {t("Preset")}
                  </span>
                ) : null}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {viewer.readOnly ? null : (
                  <button
                    onClick={() => {
                      const name = viewer.name;
                      setViewer(null);
                      void openEdit(name);
                    }}
                    className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[12px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                    title={t("Edit")}
                  >
                    <Pencil size={12} />
                    {t("Edit")}
                  </button>
                )}
                <button
                  onClick={() => setViewer(null)}
                  className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                >
                  <X size={14} />
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-4">
              {viewer.description ? (
                <p className="mb-3 text-[13px] leading-relaxed text-[var(--muted-foreground)]">
                  {viewer.description}
                </p>
              ) : null}
              {viewer.loading ? (
                <div className="flex items-center justify-center py-10 text-[var(--muted-foreground)]">
                  <Loader2 size={18} className="animate-spin" />
                </div>
              ) : viewer.error ? (
                <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12.5px] text-red-700 dark:border-red-900/40 dark:bg-red-950/20 dark:text-red-300">
                  {viewer.error}
                </div>
              ) : (
                <div className="prose-skill text-[13.5px] leading-relaxed text-[var(--foreground)]">
                  <PersonaMarkdown content={stripFrontmatter(viewer.content)} />
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Editor modal */}
      {editor && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] p-4"
          role="dialog"
          aria-modal="true"
        >
          <div className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--background)] shadow-2xl">
            <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-3">
              <div className="flex items-center gap-2">
                <UserRound
                  size={14}
                  className="text-[var(--muted-foreground)]"
                />
                <h3 className="text-[14px] font-semibold text-[var(--foreground)]">
                  {editor.mode === "create"
                    ? t("New persona")
                    : t("Edit persona")}
                </h3>
              </div>
              <button
                onClick={() => setEditor(null)}
                className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
              >
                <X size={14} />
              </button>
            </div>

            <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
              <div>
                <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                  {t("Name")}
                </label>
                <input
                  value={editor.name}
                  onChange={(e) =>
                    setEditor({
                      ...editor,
                      name: slugifySkillName(e.target.value),
                    })
                  }
                  placeholder={t("e.g. patient-tutor")}
                  className={`w-full rounded-lg border bg-[var(--background)] px-3 py-2 text-[13px] outline-none transition-colors focus:border-[var(--foreground)]/25 ${
                    editorNameInvalid
                      ? "border-red-400 dark:border-red-600"
                      : "border-[var(--border)]"
                  }`}
                />
                <p
                  className={`mt-1 text-[11px] transition-colors ${
                    editorNameInvalid
                      ? "text-red-500 dark:text-red-400"
                      : "text-[var(--muted-foreground)]/70"
                  }`}
                >
                  {t("Lowercase letters, digits, and hyphens only.")}
                </p>
              </div>

              <div>
                <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                  {t("Description")}
                </label>
                <input
                  value={editor.description}
                  onChange={(e) =>
                    setEditor({ ...editor, description: e.target.value })
                  }
                  placeholder={t("Short summary shown in the picker")}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] outline-none transition-colors focus:border-[var(--foreground)]/25"
                />
              </div>

              <div>
                <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                  {t("Markdown body")}
                </label>
                <textarea
                  value={editor.content}
                  onChange={(e) =>
                    setEditor({ ...editor, content: e.target.value })
                  }
                  rows={14}
                  spellCheck={false}
                  className="w-full resize-y rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 font-mono text-[12px] leading-relaxed outline-none transition-colors focus:border-[var(--foreground)]/25"
                />
                <p className="mt-1 text-[11px] text-[var(--muted-foreground)]/70">
                  {t(
                    "YAML frontmatter is optional and is auto-managed for name and description.",
                  )}
                </p>
              </div>

              {editor.error && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                  {editor.error}
                </div>
              )}
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-[var(--border)] px-5 py-3">
              <button
                onClick={() => setEditor(null)}
                className="rounded-md px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
              >
                {t("Cancel")}
              </button>
              <button
                onClick={() => void handleSave()}
                disabled={editor.saving}
                className="inline-flex items-center gap-1.5 rounded-md bg-[var(--foreground)] px-3.5 py-1.5 text-[12px] font-medium text-[var(--background)] transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {editor.saving && (
                  <Loader2 size={12} className="animate-spin" />
                )}
                {t("Save")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
