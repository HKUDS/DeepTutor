"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useTranslation } from "react-i18next";
import {
  Check,
  ChevronDown,
  Eye,
  Loader2,
  Lock,
  Pencil,
  Plus,
  Sparkles,
  Store,
  Tag as TagIcon,
  Trash2,
  Wand2,
  X,
} from "lucide-react";
import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import EduHubImportModal from "@/components/space/EduHubImportModal";
import { isValidSkillName, slugifySkillName } from "@/lib/skill-slug";
import {
  createSkill,
  createSkillTag,
  deleteSkill,
  deleteSkillTag,
  getSkill,
  listSkillTags,
  listSkills,
  renameSkillTag,
  updateSkill,
  type SkillInfo,
} from "@/lib/skills-api";

interface SkillEditorState {
  mode: "create" | "edit";
  originalName: string | null;
  name: string;
  description: string;
  content: string;
  tags: string[];
  saving: boolean;
  error: string | null;
}

interface SkillViewerState {
  name: string;
  source?: string;
  readOnly: boolean;
  description: string;
  content: string;
  loading: boolean;
  error: string | null;
}

// Lazy-load the markdown renderer so the heavier markdown deps only ship
// when a user actually opens a skill viewer (matches MemorySection).
const SkillMarkdown = dynamic(
  () => import("@/components/common/SimpleMarkdownRenderer"),
  { ssr: false },
);

function normalizeTag(value: string): string {
  return value.trim().toLowerCase();
}

/** Drop the YAML frontmatter block so the viewer shows just the playbook. */
function stripFrontmatter(md: string): string {
  const match = md.match(/^---\s*\n[\s\S]*?\n---\s*\n?/);
  return match ? md.slice(match[0].length) : md;
}

export default function SkillsSection() {
  const { t } = useTranslation();

  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [tagVocab, setTagVocab] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [editor, setEditor] = useState<SkillEditorState | null>(null);
  const [viewer, setViewer] = useState<SkillViewerState | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);

  const [filterTag, setFilterTag] = useState<string | "all" | "untagged">(
    "all",
  );
  const [tagManagerOpen, setTagManagerOpen] = useState(false);
  const [newTagDraft, setNewTagDraft] = useState("");
  const [renamingTag, setRenamingTag] = useState<{
    original: string;
    value: string;
  } | null>(null);
  const [editorTagDraft, setEditorTagDraft] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const [items, tags] = await Promise.all([
        listSkills({ force: true }),
        listSkillTags({ force: true }),
      ]);
      setSkills(items);
      setTagVocab(tags);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const filteredSkills = useMemo(() => {
    if (filterTag === "all") return skills;
    if (filterTag === "untagged") {
      return skills.filter((s) => !s.tags || s.tags.length === 0);
    }
    return skills.filter((s) => s.tags?.includes(filterTag));
  }, [filterTag, skills]);

  const tagCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const s of skills) {
      for (const tag of s.tags ?? []) {
        counts.set(tag, (counts.get(tag) ?? 0) + 1);
      }
    }
    return counts;
  }, [skills]);

  const untaggedCount = useMemo(
    () => skills.filter((s) => !s.tags || s.tags.length === 0).length,
    [skills],
  );

  // ── editor handlers ───────────────────────────────────────────────

  const openCreate = useCallback(() => {
    setEditor({
      mode: "create",
      originalName: null,
      name: "",
      description: "",
      content:
        "# My Skill\n\nDescribe how the assistant should behave when this skill is active.\n",
      tags: [],
      saving: false,
      error: null,
    });
    setEditorTagDraft("");
  }, []);

  const openEdit = useCallback(async (name: string) => {
    setEditor({
      mode: "edit",
      originalName: name,
      name,
      description: "",
      content: "",
      tags: [],
      saving: true,
      error: null,
    });
    setEditorTagDraft("");
    try {
      const detail = await getSkill(name);
      setEditor({
        mode: "edit",
        originalName: name,
        name: detail.name,
        description: detail.description,
        content: detail.content,
        tags: [...(detail.tags ?? [])],
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

  const openView = useCallback(async (skill: SkillInfo) => {
    setViewer({
      name: skill.name,
      source: skill.source,
      readOnly: Boolean(skill.read_only),
      description: skill.description,
      content: "",
      loading: true,
      error: null,
    });
    try {
      const detail = await getSkill(skill.name);
      setViewer({
        name: detail.name,
        source: detail.source ?? skill.source,
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
        await createSkill({
          name: trimmedName,
          description: editor.description,
          content: editor.content,
          tags: editor.tags,
        });
      } else if (editor.originalName) {
        await updateSkill(editor.originalName, {
          description: editor.description,
          content: editor.content,
          tags: editor.tags,
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
      if (!window.confirm(t('Delete skill "{{name}}"?', { name }))) return;
      setDeleting(name);
      try {
        await deleteSkill(name);
        await load();
      } catch (err) {
        setErrorMsg(err instanceof Error ? err.message : String(err));
      } finally {
        setDeleting(null);
      }
    },
    [load, t],
  );

  const toggleEditorTag = useCallback((tag: string) => {
    const clean = normalizeTag(tag);
    if (!clean) return;
    setEditor((prev) => {
      if (!prev) return prev;
      const has = prev.tags.includes(clean);
      return {
        ...prev,
        tags: has
          ? prev.tags.filter((t) => t !== clean)
          : [...prev.tags, clean],
      };
    });
  }, []);

  const handleCreateEditorTag = useCallback(async () => {
    const clean = normalizeTag(editorTagDraft);
    if (!clean) return;
    setEditorTagDraft("");
    // add immediately to editor selection regardless of vocab outcome
    setEditor((prev) =>
      prev
        ? {
            ...prev,
            tags: prev.tags.includes(clean) ? prev.tags : [...prev.tags, clean],
          }
        : prev,
    );
    if (tagVocab.includes(clean)) return;
    try {
      await createSkillTag(clean);
      const next = await listSkillTags({ force: true });
      setTagVocab(next);
    } catch {
      /* swallow — adding already-existing tag or invalid — editor still keeps it */
    }
  }, [editorTagDraft, tagVocab]);

  // ── tag vocabulary handlers ───────────────────────────────────────

  const handleCreateTag = useCallback(async () => {
    const clean = normalizeTag(newTagDraft);
    if (!clean) return;
    try {
      await createSkillTag(clean);
      const next = await listSkillTags({ force: true });
      setTagVocab(next);
      setNewTagDraft("");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
    }
  }, [newTagDraft]);

  const handleRenameTag = useCallback(async () => {
    if (!renamingTag) return;
    const next = normalizeTag(renamingTag.value);
    if (!next || next === renamingTag.original) {
      setRenamingTag(null);
      return;
    }
    try {
      await renameSkillTag(renamingTag.original, next);
      if (filterTag === renamingTag.original) {
        setFilterTag(next);
      }
      await load();
      setRenamingTag(null);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
    }
  }, [filterTag, load, renamingTag]);

  const handleDeleteTag = useCallback(
    async (tag: string) => {
      if (!window.confirm(t('Delete tag "{{name}}"?', { name: tag }))) return;
      try {
        await deleteSkillTag(tag);
        if (filterTag === tag) setFilterTag("all");
        await load();
      } catch (err) {
        setErrorMsg(err instanceof Error ? err.message : String(err));
      }
    },
    [filterTag, load, t],
  );

  // ── render ────────────────────────────────────────────────────────

  const availableTagsForEditor = useMemo(
    () =>
      tagVocab.concat(
        (editor?.tags ?? []).filter((t) => !tagVocab.includes(t)),
      ),
    [editor?.tags, tagVocab],
  );
  const editorNameInvalid = Boolean(
    editor?.name && !isValidSkillName(editor.name),
  );

  return (
    <div className="space-y-6">
      <SpaceSectionHeader
        icon={Wand2}
        title={t("Skills")}
        description={t(
          "Capability playbooks the model reads on demand. Built-in and preset skills are read-only.",
        )}
        meta={
          <span className="rounded-full border border-[var(--border)] bg-[var(--card)] px-2 py-0.5 text-[10.5px] font-medium text-[var(--muted-foreground)]">
            {skills.length} {t("skills.count.suffix")}
          </span>
        }
        action={
          <div className="flex items-center gap-2">
            <button
              onClick={() => setImportOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3.5 py-1.5 text-[12.5px] font-medium text-[var(--foreground)] shadow-sm transition-colors hover:bg-[var(--muted)]/50"
            >
              <Store size={13} strokeWidth={1.9} />
              {t("Import from EduHub")}
            </button>
            <button
              onClick={openCreate}
              className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-1.5 text-[12.5px] font-medium text-[var(--primary-foreground)] shadow-sm transition-opacity hover:opacity-90"
            >
              <Plus size={13} strokeWidth={2} />
              {t("New skill")}
            </button>
          </div>
        }
      />

      {/* Tag manager (collapsible) */}
      <section
        className={`overflow-hidden rounded-xl border transition-colors ${
          tagManagerOpen
            ? "border-[var(--border)] bg-[var(--card)] shadow-sm"
            : "border-[var(--border)]/60 bg-[var(--card)]/40"
        }`}
      >
        <button
          onClick={() => setTagManagerOpen((v) => !v)}
          className="flex w-full items-center justify-between px-4 py-3 text-left transition-colors hover:bg-[var(--muted)]/30"
        >
          <span className="flex items-center gap-2 text-[13px] font-medium text-[var(--foreground)]">
            <TagIcon
              size={14}
              strokeWidth={1.7}
              className="text-[var(--muted-foreground)]"
            />
            {t("Manage Tags")}
            <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] tabular-nums text-[var(--muted-foreground)]">
              {tagVocab.length}
            </span>
          </span>
          <ChevronDown
            size={14}
            className={`text-[var(--muted-foreground)] transition-transform duration-200 ${
              tagManagerOpen ? "rotate-180" : ""
            }`}
          />
        </button>

        {tagManagerOpen && (
          <div className="border-t border-[var(--border)]/70 px-4 pb-4 pt-3">
            <p className="mb-3 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
              {t(
                "Tags help you group skills by purpose. Renaming a tag updates every skill using it.",
              )}
            </p>
            <div className="space-y-1.5">
              {tagVocab.map((tag) => (
                <div
                  key={tag}
                  className="flex items-center justify-between gap-2 rounded-lg bg-[var(--muted)]/40 px-3 py-1.5"
                >
                  {renamingTag?.original === tag ? (
                    <input
                      autoFocus
                      value={renamingTag.value}
                      onChange={(e) =>
                        setRenamingTag({
                          original: tag,
                          value: e.target.value,
                        })
                      }
                      onKeyDown={(e) => {
                        if (e.key === "Enter") void handleRenameTag();
                        if (e.key === "Escape") setRenamingTag(null);
                      }}
                      onBlur={() => void handleRenameTag()}
                      className="flex-1 rounded border border-[var(--border)] bg-[var(--background)] px-2 py-0.5 text-[12px] text-[var(--foreground)] outline-none"
                    />
                  ) : (
                    <span className="inline-flex items-center gap-1.5 text-[12px] text-[var(--foreground)]">
                      <span className="inline-flex h-1.5 w-1.5 rounded-full bg-[var(--foreground)]/40" />
                      {tag}
                      <span className="text-[var(--muted-foreground)]">
                        ({tagCounts.get(tag) ?? 0})
                      </span>
                    </span>
                  )}
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() =>
                        setRenamingTag({ original: tag, value: tag })
                      }
                      className="rounded p-1 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                      title={t("Rename")}
                    >
                      <Pencil size={12} />
                    </button>
                    <button
                      onClick={() => void handleDeleteTag(tag)}
                      className="rounded p-1 text-[var(--muted-foreground)] transition-colors hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30"
                      title={t("Delete")}
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
              ))}
              {!tagVocab.length && (
                <p className="py-2 text-center text-[12px] text-[var(--muted-foreground)]">
                  {t("No tags yet.")}
                </p>
              )}
            </div>
            <div className="mt-3 flex items-center gap-1.5">
              <input
                value={newTagDraft}
                onChange={(e) => setNewTagDraft(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && void handleCreateTag()}
                placeholder={t("New tag name...")}
                className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-[12px] text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]"
              />
              <button
                onClick={() => void handleCreateTag()}
                disabled={!newTagDraft.trim()}
                className="inline-flex items-center gap-1 rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-[12px] font-medium text-[var(--background)] transition-opacity hover:opacity-90 disabled:opacity-30"
              >
                <Plus size={12} strokeWidth={2.2} />
                {t("Add")}
              </button>
            </div>
          </div>
        )}
      </section>

      {/* Tag filter bar */}
      <div className="-mt-2 flex flex-wrap items-center gap-1.5">
        <TagFilterChip
          label={t("All")}
          count={skills.length}
          active={filterTag === "all"}
          onClick={() => setFilterTag("all")}
        />
        {tagVocab.map((tag) => (
          <TagFilterChip
            key={tag}
            label={tag}
            count={tagCounts.get(tag) ?? 0}
            active={filterTag === tag}
            onClick={() => setFilterTag(tag)}
          />
        ))}
        {untaggedCount > 0 && (
          <TagFilterChip
            label={t("Untagged")}
            count={untaggedCount}
            active={filterTag === "untagged"}
            onClick={() => setFilterTag("untagged")}
            muted
          />
        )}
      </div>

      {errorMsg && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          {errorMsg}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
        </div>
      ) : skills.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--card)]/40 px-6 py-14 text-center">
          <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--muted)]/60 text-[var(--muted-foreground)]">
            <Sparkles size={18} />
          </div>
          <p className="text-[14px] font-medium text-[var(--foreground)]">
            {t("No skills yet")}
          </p>
          <p className="mx-auto mt-1 max-w-sm text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "Create a skill to define reusable guidance (e.g. a patient tutor, a rigorous research assistant).",
            )}
          </p>
          <button
            onClick={openCreate}
            className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-1.5 text-[12.5px] font-medium text-[var(--primary-foreground)] shadow-sm transition-opacity hover:opacity-90"
          >
            <Plus size={13} strokeWidth={2} />
            {t("Create your first skill")}
          </button>
        </div>
      ) : filteredSkills.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-[var(--border)] px-6 py-10 text-center text-[13px] text-[var(--muted-foreground)]">
          {t("No skills match this filter.")}
        </div>
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {filteredSkills.map((skill) => {
            const readOnly = Boolean(skill.read_only);
            const sourceBadge =
              skill.source === "builtin"
                ? t("Built-in")
                : skill.source === "admin"
                  ? t("Preset")
                  : null;
            return (
              <li
                key={skill.name}
                role="button"
                tabIndex={0}
                onClick={() => void openView(skill)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    void openView(skill);
                  }
                }}
                title={t("View skill")}
                className="group relative flex cursor-pointer flex-col rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm transition-all hover:border-[var(--foreground)]/30 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]/40"
              >
                <div className="mb-2 flex items-start justify-between gap-2">
                  <div className="flex items-start gap-2.5">
                    <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-[var(--border)]/60 bg-[var(--background)] text-[var(--muted-foreground)]">
                      <Wand2 size={13} strokeWidth={1.6} />
                    </span>
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-[14px] font-semibold tracking-tight text-[var(--foreground)]">
                          {skill.name}
                        </span>
                        {sourceBadge ? (
                          <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                            {readOnly ? <Lock size={9} /> : null}
                            {sourceBadge}
                          </span>
                        ) : null}
                      </div>
                      {skill.description ? (
                        <p className="mt-0.5 line-clamp-2 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                          {skill.description}
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
                          void openEdit(skill.name);
                        }}
                        className="rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                        title={t("Edit")}
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleDelete(skill.name);
                        }}
                        disabled={deleting === skill.name}
                        className="rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-50 dark:hover:bg-red-950/30"
                        title={t("Delete")}
                      >
                        {deleting === skill.name ? (
                          <Loader2 size={13} className="animate-spin" />
                        ) : (
                          <Trash2 size={13} />
                        )}
                      </button>
                    </div>
                  )}
                </div>

                {skill.tags && skill.tags.length > 0 ? (
                  <div className="mt-auto flex flex-wrap gap-1 pt-2">
                    {skill.tags.map((tag) => (
                      <button
                        key={tag}
                        onClick={(e) => {
                          e.stopPropagation();
                          setFilterTag(tag);
                        }}
                        className="inline-flex items-center gap-1 rounded-full border border-[var(--border)]/60 bg-[var(--muted)]/40 px-2 py-0.5 text-[10.5px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--foreground)]/30 hover:text-[var(--foreground)]"
                      >
                        <span className="inline-flex h-1.5 w-1.5 rounded-full bg-[var(--foreground)]/40" />
                        {tag}
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="mt-auto pt-2">
                    <span className="inline-flex items-center gap-1 rounded-full border border-dashed border-[var(--border)] px-2 py-0.5 text-[10.5px] text-[var(--muted-foreground)]/70">
                      <TagIcon size={10} />
                      {t("Untagged")}
                    </span>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {/* Viewer modal — read-only content view, available for every skill */}
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
                <Wand2
                  size={14}
                  className="shrink-0 text-[var(--muted-foreground)]"
                />
                <h3 className="truncate text-[14px] font-semibold text-[var(--foreground)]">
                  {viewer.name}
                </h3>
                {viewer.readOnly ? (
                  <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                    <Lock size={9} />
                    {viewer.source === "admin" ? t("Preset") : t("Built-in")}
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
                  <SkillMarkdown content={stripFrontmatter(viewer.content)} />
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
                <Wand2 size={14} className="text-[var(--muted-foreground)]" />
                <h3 className="text-[14px] font-semibold text-[var(--foreground)]">
                  {editor.mode === "create" ? t("New skill") : t("Edit skill")}
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
                  placeholder={t("e.g. socratic-math-mentor")}
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
                  placeholder={t("Short summary used by Auto mode")}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] outline-none transition-colors focus:border-[var(--foreground)]/25"
                />
              </div>

              <div>
                <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                  {t("Tags")}
                </label>
                <div className="flex flex-wrap gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--background)] p-2">
                  {availableTagsForEditor.length === 0 && (
                    <span className="px-1 text-[11px] italic text-[var(--muted-foreground)]/70">
                      {t("No tags yet — add one below.")}
                    </span>
                  )}
                  {availableTagsForEditor.map((tag) => {
                    const active = editor.tags.includes(tag);
                    return (
                      <button
                        key={tag}
                        type="button"
                        onClick={() => toggleEditorTag(tag)}
                        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11.5px] transition-colors ${
                          active
                            ? "bg-[var(--foreground)] text-[var(--background)]"
                            : "border border-[var(--border)] bg-[var(--card)] text-[var(--muted-foreground)] hover:border-[var(--foreground)]/30 hover:text-[var(--foreground)]"
                        }`}
                      >
                        {active ? (
                          <Check size={10} strokeWidth={2.4} />
                        ) : (
                          <span className="inline-flex h-1.5 w-1.5 rounded-full bg-current opacity-50" />
                        )}
                        {tag}
                      </button>
                    );
                  })}
                </div>
                <div className="mt-2 flex items-center gap-1.5">
                  <input
                    value={editorTagDraft}
                    onChange={(e) => setEditorTagDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        void handleCreateEditorTag();
                      }
                    }}
                    placeholder={t("Add a tag...")}
                    className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-[12px] text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]"
                  />
                  <button
                    type="button"
                    onClick={() => void handleCreateEditorTag()}
                    disabled={!editorTagDraft.trim()}
                    className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--muted)]/40 px-2.5 py-1.5 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:opacity-40"
                  >
                    <Plus size={12} strokeWidth={2.2} />
                    {t("Add")}
                  </button>
                </div>
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
                    "YAML frontmatter is optional and is auto-managed for name, description, and tags.",
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

      {importOpen && (
        <EduHubImportModal
          onClose={() => setImportOpen(false)}
          onInstalled={() => void load()}
          installedNames={new Set(skills.map((s) => s.name))}
        />
      )}
    </div>
  );
}

interface TagFilterChipProps {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
  muted?: boolean;
}

function TagFilterChip({
  label,
  count,
  active,
  onClick,
  muted,
}: TagFilterChipProps) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[12px] font-medium transition-colors ${
        active
          ? "border-[var(--foreground)] bg-[var(--foreground)] text-[var(--background)]"
          : muted
            ? "border-dashed border-[var(--border)] text-[var(--muted-foreground)]/80 hover:text-[var(--foreground)]"
            : "border-[var(--border)] text-[var(--muted-foreground)] hover:border-[var(--foreground)]/30 hover:text-[var(--foreground)]"
      }`}
    >
      {label}
      <span
        className={`tabular-nums ${
          active ? "opacity-80" : "text-[var(--muted-foreground)]/70"
        }`}
      >
        {count}
      </span>
    </button>
  );
}
