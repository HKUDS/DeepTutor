"use client";

import Tooltip from "@/shared/ui/Tooltip";
import { useState } from "react";
import Link from "next/link";
import {
  Check,
  ListTree,
  Pencil,
  ChevronDown,
  ChevronRight,
  PlayCircle,
  FileText,
  Calendar,
  Sparkles,
  BookOpen,
  ArrowRight,
  GraduationCap,
  ChevronsUpDown,
  Clock,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useRouter } from "next/navigation";
import { setPendingPrompt } from "@/lib/pending-prompt";

import type { CourseState, SyllabusUnit } from "@/lib/courses-api";

/**
 * What this course is supposed to cover, and how much of it is done.
 *
 * Supports 4-tier breakdown: Course -> Lecture -> Unit -> Concepts/Sub-topics.
 * Each Lecture can be expanded to reveal its sub-units and 1-click concept learning actions,
 * along with direct quick-action links to Video and Slide materials.
 */

const TOPIC_SEPARATOR = "|";

export interface ParsedUnitTopic {
  raw: string;
  unitTitle: string;
  concepts: string[];
}

function splitConcepts(raw: string): string[] {
  return raw
    .split(/[·•,;|]/)
    .map((c) => c.trim())
    .filter((c) => c.length > 0);
}

/**
 * Parse sub-concepts within each unit topic string.
 * Supports:
 * - Parentheses: "Unit 1: Background & NLP Tasks (NLP Overview · Language Modeling · Sequence Tasks)"
 * - Colons: "Unit 1: Background & NLP Tasks: NLP Tasks, Language Modeling, Seq2seq"
 */
export function parseUnitTopic(rawTopic: string): ParsedUnitTopic {
  const trimmed = rawTopic.trim();
  if (!trimmed) {
    return { raw: rawTopic, unitTitle: "", concepts: [] };
  }

  // 1. Parenthesized concepts: e.g. "Unit 1: Background & NLP Tasks (NLP Tasks · Language Modeling · Seq2seq)"
  const parenMatch = trimmed.match(/^(.*?)\s*\(([^)]+)\)\s*$/);
  if (parenMatch) {
    const unitTitle = parenMatch[1].trim();
    const rawConcepts = parenMatch[2].trim();
    const concepts = splitConcepts(rawConcepts);
    if (concepts.length > 0) {
      return {
        raw: rawTopic,
        unitTitle: unitTitle || trimmed,
        concepts,
      };
    }
  }

  // 2. Colon-separated concepts: e.g. "Unit 1: Background & NLP Tasks: NLP Tasks, Language Modeling, Seq2seq"
  const unitPrefixMatch = trimmed.match(
    /^(Unit\s+\d+|Lesson\s+\d+|Chapter\s+\d+|Bài\s+\d+|Chương\s+\d+|Part\s+\d+):\s*(.*)$/i,
  );
  if (unitPrefixMatch) {
    const prefix = unitPrefixMatch[1];
    const remainder = unitPrefixMatch[2];
    const colonIndex = remainder.indexOf(":");
    if (colonIndex !== -1) {
      const titlePart = remainder.slice(0, colonIndex).trim();
      const rawConcepts = remainder.slice(colonIndex + 1).trim();
      const concepts = splitConcepts(rawConcepts);
      if (concepts.length > 0) {
        return {
          raw: rawTopic,
          unitTitle: `${prefix}: ${titlePart}`,
          concepts,
        };
      }
    }
  } else {
    // Colon without Unit prefix: "Background & NLP Tasks: NLP Tasks, Language Modeling, Seq2seq"
    const colonIndex = trimmed.indexOf(":");
    if (colonIndex !== -1) {
      const titlePart = trimmed.slice(0, colonIndex).trim();
      const rawConcepts = trimmed.slice(colonIndex + 1).trim();
      const concepts = splitConcepts(rawConcepts);
      if (
        concepts.length > 1 ||
        (concepts.length === 1 &&
          (rawConcepts.includes(",") || rawConcepts.includes("·")))
      ) {
        return {
          raw: rawTopic,
          unitTitle: titlePart,
          concepts,
        };
      }
    }
  }

  return {
    raw: rawTopic,
    unitTitle: trimmed,
    concepts: [],
  };
}

export interface LectureMediaInfo {
  videoUrl?: string;
  slideUrl?: string;
  mirrorSlideUrl?: string;
  readingWorkspaceUrl?: string;
  isVideoUpcoming?: boolean;
  isSlideUpcoming?: boolean;
}

const KNOWN_LECTURE_MEDIA: Record<string, LectureMediaInfo> = {
  lecture_1_transformers: {
    videoUrl: "https://www.youtube.com/watch?v=114i2Kz-LZA",
    slideUrl: "https://cme295.stanford.edu/slides/fall26-cme295-lecture1.pdf",
    mirrorSlideUrl:
      "https://raw.githubusercontent.com/afshinea/stanford-cme-295-transformers-large-language-models/main/en/cheatsheet-transformers-large-language-models.pdf",
    readingWorkspaceUrl:
      "/learning/reading/rw_3f8b01ffbee24ecf9ad3f21e1d2f11ae",
    isVideoUpcoming: false,
    isSlideUpcoming: false,
  },
  lecture_2_llms: {
    slideUrl: "https://cme295.stanford.edu/slides/fall26-cme295-lecture2.pdf",
    mirrorSlideUrl:
      "https://raw.githubusercontent.com/afshinea/stanford-cme-295-transformers-large-language-models/main/en/cheatsheet-transformers-large-language-models.pdf",
    isVideoUpcoming: true,
    isSlideUpcoming: false,
  },
  lecture_3_training: {
    isVideoUpcoming: true,
    isSlideUpcoming: true,
  },
  lecture_4_rl: {
    isVideoUpcoming: true,
    isSlideUpcoming: true,
  },
  lecture_5_systems: {
    isVideoUpcoming: true,
    isSlideUpcoming: true,
  },
  lecture_6_agents: {
    isVideoUpcoming: true,
    isSlideUpcoming: true,
  },
  lecture_7_eval: {
    isVideoUpcoming: true,
    isSlideUpcoming: true,
  },
  lecture_8_diffusion: {
    isVideoUpcoming: true,
    isSlideUpcoming: true,
  },
  lecture_9_trending: {
    isVideoUpcoming: true,
    isSlideUpcoming: true,
  },
};

export function getLectureMedia(unit: SyllabusUnit): LectureMediaInfo {
  const explicit = unit as unknown as {
    video_url?: string;
    slide_url?: string;
    mirror_slide_url?: string;
    reading_workspace_url?: string;
    video_status?: "available" | "upcoming";
    slide_status?: "available" | "upcoming";
    media?: {
      video_url?: string;
      slide_url?: string;
      mirror_slide_url?: string;
      reading_workspace_url?: string;
      video_status?: string;
      slide_status?: string;
    };
  };

  let known = KNOWN_LECTURE_MEDIA[unit.id];

  if (!known) {
    const lectureNumMatch = unit.title.match(/Lecture\s+(\d+)/i);
    if (lectureNumMatch) {
      const num = parseInt(lectureNumMatch[1], 10);
      if (num === 1) {
        known = KNOWN_LECTURE_MEDIA["lecture_1_transformers"];
      } else if (num === 2) {
        known = KNOWN_LECTURE_MEDIA["lecture_2_llms"];
      } else if (num >= 3 && num <= 9) {
        known = {
          isVideoUpcoming: true,
          isSlideUpcoming: true,
        };
      }
    }
  }

  const videoUrl =
    explicit.video_url || explicit.media?.video_url || known?.videoUrl;
  const slideUrl =
    explicit.slide_url || explicit.media?.slide_url || known?.slideUrl;
  const mirrorSlideUrl =
    explicit.mirror_slide_url ||
    explicit.media?.mirror_slide_url ||
    known?.mirrorSlideUrl;
  const readingWorkspaceUrl =
    explicit.reading_workspace_url ||
    explicit.media?.reading_workspace_url ||
    known?.readingWorkspaceUrl;

  const isExam = /exam|thi|midterm|final/i.test(unit.title);

  let isVideoUpcoming = false;
  if (!videoUrl && !isExam) {
    if (
      explicit.video_status === "upcoming" ||
      explicit.media?.video_status === "upcoming"
    ) {
      isVideoUpcoming = true;
    } else if (known?.isVideoUpcoming !== undefined) {
      isVideoUpcoming = known.isVideoUpcoming;
    } else if (
      /slide\s*(?:có\s*sẵn|available)|lịch\s*học|sắp\s*tới|upcoming/i.test(unit.title)
    ) {
      isVideoUpcoming = true;
    }
  }

  let isSlideUpcoming = false;
  if (!slideUrl && !isExam) {
    if (
      explicit.slide_status === "upcoming" ||
      explicit.media?.slide_status === "upcoming"
    ) {
      isSlideUpcoming = true;
    } else if (known?.isSlideUpcoming !== undefined) {
      isSlideUpcoming = known.isSlideUpcoming;
    } else if (/lịch\s*học|sắp\s*tới|upcoming/i.test(unit.title)) {
      isSlideUpcoming = true;
    }
  }

  return {
    videoUrl,
    slideUrl,
    mirrorSlideUrl,
    readingWorkspaceUrl,
    isVideoUpcoming,
    isSlideUpcoming,
  };
}

export function unitsToText(units: SyllabusUnit[]): string {
  return units
    .map((unit) =>
      unit.topics.length > 0
        ? `${unit.title} ${TOPIC_SEPARATOR} ${unit.topics.join(", ")}`
        : unit.title,
    )
    .join("\n");
}

/** Parse the editor back into units, keeping ids so `covered` survives a rewrite. */
export function textToUnits(
  text: string,
  existing: SyllabusUnit[],
): { id?: string; title: string; topics: string[] }[] {
  const byTitle = new Map(
    existing.map((unit) => [unit.title.trim().toLowerCase(), unit]),
  );
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [rawTitle, rawTopics = ""] = line.split(TOPIC_SEPARATOR);
      const title = rawTitle.trim();
      const previous = byTitle.get(title.toLowerCase());
      // Split on commas that are not nested inside parentheses
      const topics = rawTopics
        .split(/,(?![^(]*\))/)
        .map((topic) => topic.trim())
        .filter(Boolean);
      return {
        ...(previous ? { id: previous.id } : {}),
        title,
        topics,
      };
    });
}

export function parseLectureTitle(rawTitle: string): {
  cleanTitle: string;
  badge?: {
    label: string;
    variant: "video" | "slide" | "upcoming" | "exam" | "default";
  };
} {
  const match = rawTitle.match(/\[(.*?)\]$/);
  if (!match) return { cleanTitle: rawTitle };

  const tag = match[1].trim();
  const cleanTitle = rawTitle.slice(0, match.index).trim();
  const lower = tag.toLowerCase();

  if (lower.includes("video")) {
    return { cleanTitle, badge: { label: tag, variant: "video" } };
  }
  if (lower.includes("slide")) {
    return { cleanTitle, badge: { label: tag, variant: "slide" } };
  }
  if (
    lower.includes("lịch") ||
    lower.includes("sắp") ||
    lower.includes("upcoming")
  ) {
    return { cleanTitle, badge: { label: tag, variant: "upcoming" } };
  }
  if (
    lower.includes("thi") ||
    lower.includes("exam") ||
    lower.includes("midterm") ||
    lower.includes("final")
  ) {
    return { cleanTitle, badge: { label: tag, variant: "exam" } };
  }
  return { cleanTitle, badge: { label: tag, variant: "default" } };
}

function getBadgeIcon(variant: string) {
  switch (variant) {
    case "video":
      return <PlayCircle size={11} className="shrink-0" />;
    case "slide":
      return <FileText size={11} className="shrink-0" />;
    case "upcoming":
      return <Calendar size={11} className="shrink-0" />;
    case "exam":
      return <GraduationCap size={11} className="shrink-0" />;
    default:
      return null;
  }
}

function getBadgeClasses(variant: string) {
  switch (variant) {
    case "video":
      return "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20";
    case "slide":
      return "bg-sky-500/10 text-sky-600 dark:text-sky-400 border-sky-500/20";
    case "upcoming":
      return "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20";
    case "exam":
      return "bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/20";
    default:
      return "bg-[var(--muted)] text-[var(--muted-foreground)] border-[var(--border)]";
  }
}

export default function CourseSyllabus({
  state,
  courseId,
  onSave,
  onToggle,
}: {
  state: CourseState | null;
  courseId?: string;
  onSave: (
    units: { id?: string; title: string; topics: string[] }[],
  ) => Promise<void>;
  onToggle: (unitId: string, covered: boolean) => Promise<void>;
}) {
  const { t } = useTranslation();
  const router = useRouter();

  const syllabus = state?.syllabus ?? {
    total: 0,
    covered: 0,
    next: null,
    units: [],
  };
  const units = syllabus.units ?? [];

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  // Expanded accordion items
  const [expandedUnits, setExpandedUnits] = useState<Set<string>>(() => {
    const initial = new Set<string>();
    if (syllabus.next?.id) {
      initial.add(syllabus.next.id);
    } else if (units.length > 0 && units[0]?.id) {
      initial.add(units[0].id);
    }
    return initial;
  });

  const handleStartEdit = () => {
    setDraft(unitsToText(units as SyllabusUnit[]));
    setEditing(true);
  };

  const handleCancelEdit = () => {
    setEditing(false);
  };

  const toggleExpand = (unitId: string) => {
    setExpandedUnits((prev) => {
      const next = new Set(prev);
      if (next.has(unitId)) {
        next.delete(unitId);
      } else {
        next.add(unitId);
      }
      return next;
    });
  };

  const toggleAllExpanded = () => {
    if (expandedUnits.size === units.length) {
      setExpandedUnits(new Set());
    } else {
      setExpandedUnits(new Set(units.map((u) => u.id)));
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      await onSave(textToUnits(draft, units as SyllabusUnit[]));
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const handleStudyLecture = (lectureTitle: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    if (!courseId) return;
    const prompt = t(
      "Guide me through the entire lecture '{{lectureTitle}}'. Summarize the lecture roadmap and guide me through each unit step by step.",
      { lectureTitle },
    );
    setPendingPrompt(prompt, "chat");
    router.push(
      `/chat?course=${encodeURIComponent(courseId)}&capability=course_study`,
    );
  };

  const handleStudyTopic = (lectureTitle: string, topic: string) => {
    if (!courseId) return;
    const prompt = t(
      "I would like to study '{{topic}}' in detail from lecture '{{lectureTitle}}' of this course. Explain the core concepts, real-world examples, and ask questions to test my understanding.",
      { topic, lectureTitle },
    );
    setPendingPrompt(prompt, "chat");
    router.push(
      `/chat?course=${encodeURIComponent(courseId)}&capability=course_study`,
    );
  };

  const handleStudyConcept = (
    lectureTitle: string,
    unitTitle: string,
    concept: string,
    e?: React.MouseEvent,
  ) => {
    if (e) e.stopPropagation();
    if (!courseId) return;
    const prompt = t(
      "I would like to study the concept '{{concept}}' in depth (part of {{unitTitle}}, lecture '{{lectureTitle}}') from this course. Explain the underlying theory, intuition, formulas or code if applicable, real-world examples, and comprehension check questions.",
      { concept, unitTitle, lectureTitle },
    );
    setPendingPrompt(prompt, "chat");
    router.push(
      `/chat?course=${encodeURIComponent(courseId)}&capability=course_study`,
    );
  };

  const percent =
    syllabus.total > 0
      ? Math.round((syllabus.covered / syllabus.total) * 100)
      : 0;

  return (
    <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4">
      <div className="flex items-baseline justify-between gap-4">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 font-serif text-[16px] font-semibold text-[var(--foreground)]">
            <ListTree size={15} strokeWidth={1.7} />
            {t("Course Syllabus & Roadmap")}
          </h2>
          <p className="mt-0.5 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
            {syllabus.total > 0
              ? t(
                  "{{covered}} / {{total}} lectures completed (Course -> Lecture -> Unit -> Concepts)",
                  {
                    covered: syllabus.covered,
                    total: syllabus.total,
                  },
                )
              : t(
                  "What this course should cover. Without it, progress has no denominator.",
                )}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          {units.length > 0 && !editing ? (
            <button
              type="button"
              onClick={toggleAllExpanded}
              className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-[11.5px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/50 hover:text-[var(--foreground)]"
              aria-label={
                expandedUnits.size === units.length
                  ? t("Collapse all")
                  : t("Expand all")
              }
            >
              <ChevronsUpDown size={12} />
              {expandedUnits.size === units.length
                ? t("Collapse")
                : t("Expand")}
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => (editing ? handleCancelEdit() : handleStartEdit())}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-[11.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]/50"
          >
            <Pencil size={12} />
            {editing ? t("Cancel") : syllabus.total > 0 ? t("Edit") : t("Add")}
          </button>
        </div>
      </div>

      {syllabus.total > 0 && !editing ? (
        <div
          className="mt-3 h-1 overflow-hidden rounded-full bg-[var(--muted)]"
          role="progressbar"
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className="h-full rounded-full bg-[var(--foreground)]/45 transition-[width] duration-300"
            style={{ width: `${percent}%` }}
          />
        </div>
      ) : null}

      {editing ? (
        <div className="mt-3">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            rows={8}
            placeholder={t(
              "One unit per line. Add keywords after a | so DeepTutor can tell which questions belong to it:\n\nProcesses and threads | context switch, scheduling\nVirtual memory | address translation, page replacement",
            )}
            className="w-full resize-y rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2.5 font-mono text-[12px] leading-relaxed text-[var(--foreground)] outline-none transition-colors focus:border-[var(--ring)]"
          />
          <div className="mt-2 flex justify-end">
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className="rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-[11.5px] font-medium text-[var(--background)] transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {saving ? t("Saving") : t("Save")}
            </button>
          </div>
        </div>
      ) : units.length === 0 ? (
        <p className="mt-3 rounded-xl border border-dashed border-[var(--border)] px-3 py-4 text-center text-[11.5px] text-[var(--muted-foreground)]">
          {t(
            "Paste the course outline and every number on this page gains a denominator.",
          )}
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {units.map((unit) => {
            const isNext = syllabus.next?.id === unit.id;
            const isExpanded = expandedUnits.has(unit.id);
            const { cleanTitle, badge } = parseLectureTitle(unit.title);
            const {
              videoUrl,
              slideUrl,
              mirrorSlideUrl,
              readingWorkspaceUrl,
              isVideoUpcoming,
              isSlideUpcoming,
            } = getLectureMedia(unit);

            return (
              <li
                key={unit.id}
                className={`overflow-hidden rounded-xl border transition-colors ${
                  isNext
                    ? "border-[var(--ring)]/60 bg-[var(--muted)]/20"
                    : "border-[var(--border)] bg-[var(--card)]"
                }`}
              >
                {/* Lecture Header Row */}
                <div
                  onClick={() => toggleExpand(unit.id)}
                  className="flex cursor-pointer select-none items-center gap-2.5 p-3 transition-colors hover:bg-[var(--muted)]/40"
                >
                  {/* Accordion Chevron */}
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleExpand(unit.id);
                    }}
                    className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                    aria-label={isExpanded ? "Collapse" : "Expand"}
                  >
                    {isExpanded ? (
                      <ChevronDown size={15} />
                    ) : (
                      <ChevronRight size={15} />
                    )}
                  </button>

                  {/* Covered Checkbox */}
                  <button
                    type="button"
                    role="checkbox"
                    aria-checked={unit.covered}
                    onClick={(e) => {
                      e.stopPropagation();
                      void onToggle(unit.id, !unit.covered);
                    }}
                    className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors ${
                      unit.covered
                        ? "border-[var(--foreground)] bg-[var(--foreground)] text-[var(--background)]"
                        : "border-[var(--border)] hover:border-[var(--foreground)]/60"
                    }`}
                  >
                    {unit.covered ? <Check size={11} strokeWidth={3} /> : null}
                  </button>

                  {/* Title & Badges */}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span
                        className={`text-[13px] font-medium leading-snug ${
                          unit.covered
                            ? "text-[var(--muted-foreground)] line-through"
                            : "text-[var(--foreground)]"
                        }`}
                      >
                        {unit.position + 1}. {cleanTitle}
                      </span>

                      {/* Exam / Custom Tag Badge */}
                      {badge && badge.variant === "exam" ? (
                        <span
                          className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10.5px] font-medium ${getBadgeClasses(
                            badge.variant,
                          )}`}
                        >
                          {getBadgeIcon(badge.variant)}
                          {t(badge.label)}
                        </span>
                      ) : null}

                      {/* Header Media Quick-Action Pills */}
                      {videoUrl ? (
                        <a
                          href={videoUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10.5px] font-medium text-emerald-600 dark:text-emerald-400 transition-colors hover:bg-emerald-500/20"
                          aria-label={t("Watch lecture video")}
                        >
                          <PlayCircle
                            size={11}
                            className="shrink-0 text-emerald-500"
                          />
                          <span>{t("Watch Video")}</span>
                        </a>
                      ) : null}

                      {slideUrl ? (
                        <div className="flex items-center gap-1">
                          <a
                            href={slideUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="inline-flex items-center gap-1 rounded-full border border-sky-500/30 bg-sky-500/10 px-2 py-0.5 text-[10.5px] font-medium text-sky-600 dark:text-sky-400 transition-colors hover:bg-sky-500/20"
                            aria-label={t("View lecture slides")}
                          >
                            <FileText
                              size={11}
                              className="shrink-0 text-sky-500"
                            />
                            <span>{t("View Slide PDF")}</span>
                          </a>
                          {mirrorSlideUrl ? (
                            <a
                              href={mirrorSlideUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--card)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--secondary)] transition-colors"
                              aria-label={t("Mirror PDF (GitHub)")}
                            >
                              <span>{t("Mirror PDF")}</span>
                            </a>
                          ) : null}
                        </div>
                      ) : null}

                      {isVideoUpcoming ? (
                        <span
                          className="inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10.5px] font-medium text-amber-600 dark:text-amber-400"
                          aria-label={t("Lecture video is being updated")}
                        >
                          <Clock
                            size={11}
                            className="shrink-0 text-amber-500"
                          />
                          <span>{t("Video coming soon")}</span>
                        </span>
                      ) : null}

                      {isSlideUpcoming ? (
                        <span
                          className="inline-flex items-center gap-1 rounded-full border border-sky-500/30 bg-sky-500/10 px-2 py-0.5 text-[10.5px] font-medium text-sky-600 dark:text-sky-400"
                          aria-label={t("Lecture slides are being updated")}
                        >
                          <Clock
                            size={11}
                            className="shrink-0 text-sky-500"
                          />
                          <span>{t("Slide PDF coming soon")}</span>
                        </span>
                      ) : null}

                      {/* Fallback badge for non-media, non-exam tags */}
                      {badge &&
                      badge.variant !== "exam" &&
                      !videoUrl &&
                      !slideUrl &&
                      !isVideoUpcoming &&
                      !isSlideUpcoming ? (
                        <span
                          className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10.5px] font-medium ${getBadgeClasses(
                            badge.variant,
                          )}`}
                        >
                          {getBadgeIcon(badge.variant)}
                          {badge.label}
                        </span>
                      ) : null}
                    </div>

                    {/* Preview / collapsed line */}
                    {!isExpanded && unit.topics.length > 0 ? (
                      <p className="mt-0.5 truncate text-[11px] text-[var(--muted-foreground)]/80">
                        {t("{{count}} units: {{topics}}", {
                          count: unit.topics.length,
                          topics:
                            unit.topics
                              .slice(0, 3)
                              .map((top) => parseUnitTopic(top).unitTitle)
                              .join(" · ") +
                            (unit.topics.length > 3 ? "..." : ""),
                        })}
                      </p>
                    ) : null}
                  </div>

                  {/* Right Actions */}
                  <div className="flex shrink-0 items-center gap-2">
                    {unit.wrong_questions > 0 ? (
                      <Tooltip
                        label={t(
                          "Evidence, not a verdict — you decide whether this unit is done.",
                        )}
                        side="top"
                      >
                        <span className="text-[11px] text-[var(--muted-foreground)]">
                          {t("{{count}} wrong", {
                            count: unit.wrong_questions,
                          })}
                        </span>
                      </Tooltip>
                    ) : null}

                    {unit.topics.length > 0 ? (
                      <span className="rounded-md bg-[var(--muted)] px-1.5 py-0.5 text-[10.5px] font-medium text-[var(--muted-foreground)]">
                        {t("{{count}} units", { count: unit.topics.length })}
                      </span>
                    ) : null}

                    {courseId ? (
                      <button
                        type="button"
                        onClick={(e) => handleStudyLecture(cleanTitle, e)}
                        className="hidden sm:inline-flex items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-1 text-[11.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]/50"
                        aria-label={t("Start studying this lecture")}
                      >
                        <Sparkles size={11} className="text-amber-500" />
                        <span>{t("Study Lecture")}</span>
                      </button>
                    ) : null}
                  </div>
                </div>

                {/* Expanded View: Media Bar & 4-tier Unit Hierarchy */}
                {isExpanded &&
                (unit.topics.length > 0 ||
                  videoUrl ||
                  slideUrl ||
                  isVideoUpcoming ||
                  isSlideUpcoming) ? (
                  <div className="border-t border-[var(--border)]/70 bg-[var(--background)]/40 p-2.5 sm:p-3">
                    {/* Direct Lecture Media & Slide Quick-Action Links (Expanded View) */}
                    {videoUrl || slideUrl || isVideoUpcoming || isSlideUpcoming ? (
                      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--border)]/70 bg-[var(--card)] p-2.5 px-3">
                        <div className="flex items-center gap-2 text-[11.5px] font-semibold text-[var(--foreground)]">
                          <BookOpen
                            size={13}
                            className="text-[var(--muted-foreground)]"
                          />
                          <span>{t("Lecture materials & media")}</span>
                        </div>
                        <div className="flex flex-wrap items-center gap-1.5">
                          {videoUrl ? (
                            <a
                              href={videoUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[11.5px] font-medium text-emerald-600 dark:text-emerald-400 transition-colors hover:bg-emerald-500/20 hover:border-emerald-500/50"
                            >
                              <PlayCircle size={13} className="text-emerald-500" />
                              <span>{t("Watch Video")}</span>
                            </a>
                          ) : null}
                          {slideUrl ? (
                            <a
                              href={slideUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1.5 rounded-lg border border-sky-500/30 bg-sky-500/10 px-2.5 py-1 text-[11.5px] font-medium text-sky-600 dark:text-sky-400 transition-colors hover:bg-sky-500/20 hover:border-sky-500/50"
                            >
                              <FileText size={13} className="text-sky-500" />
                              <span>{t("View Slide PDF")}</span>
                            </a>
                          ) : null}
                          {mirrorSlideUrl ? (
                            <a
                              href={mirrorSlideUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-2.5 py-1 text-[11.5px] font-medium text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--secondary)] transition-colors"
                            >
                              <FileText size={13} aria-hidden="true" />
                              <span>{t("Mirror PDF (GitHub)")}</span>
                            </a>
                          ) : null}
                          {readingWorkspaceUrl ? (
                            <Link
                              href={readingWorkspaceUrl}
                              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-2.5 py-1 text-[11.5px] font-medium text-[var(--primary)] hover:bg-[var(--secondary)] transition-colors"
                            >
                              <BookOpen size={13} aria-hidden="true" />
                              <span>{t("Read on DeepTutor")}</span>
                            </Link>
                          ) : null}
                          {isVideoUpcoming ? (
                            <span className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-[11.5px] font-medium text-amber-600 dark:text-amber-400">
                              <Clock size={12} className="text-amber-500" />
                              <span>{t("Video coming soon")}</span>
                            </span>
                          ) : null}
                          {isSlideUpcoming ? (
                            <span className="inline-flex items-center gap-1.5 rounded-lg border border-sky-500/30 bg-sky-500/10 px-2.5 py-1 text-[11.5px] font-medium text-sky-600 dark:text-sky-400">
                              <Clock size={12} className="text-sky-500" />
                              <span>{t("Slide PDF coming soon")}</span>
                            </span>
                          ) : null}
                        </div>
                      </div>
                    ) : null}

                    {/* Sub-Units List Header */}
                    {unit.topics.length > 0 ? (
                      <>
                        <div className="mb-2 flex items-center justify-between px-1">
                          <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
                            {t("Units & Topics")} ({unit.topics.length})
                          </span>
                          {courseId ? (
                            <button
                              type="button"
                              onClick={(e) => handleStudyLecture(cleanTitle, e)}
                              className="sm:hidden inline-flex items-center gap-1 text-[11px] font-medium text-[var(--foreground)] hover:underline"
                            >
                              <Sparkles size={11} className="text-amber-500" />
                              <span>{t("Study all")}</span>
                            </button>
                          ) : null}
                        </div>

                        {/* 4th-tier hierarchy: Units & Concepts */}
                        <ul className="space-y-2">
                          {unit.topics.map((topic, topicIdx) => {
                            const parsed = parseUnitTopic(topic);
                            const hasConcepts = parsed.concepts.length > 0;

                            return (
                              <li
                                key={topicIdx}
                                className="group rounded-xl border border-[var(--border)]/70 bg-[var(--card)] p-2.5 transition-all hover:border-[var(--ring)]/50"
                              >
                                {/* Level 3: Unit Header Row */}
                                <div className="flex items-center justify-between gap-3">
                                  <div className="flex min-w-0 items-center gap-2">
                                    <BookOpen
                                      size={13}
                                      className="shrink-0 text-[var(--muted-foreground)] group-hover:text-[var(--foreground)] transition-colors"
                                    />
                                    <div className="min-w-0 flex flex-wrap items-center gap-1.5">
                                      <span className="text-[12.5px] font-medium text-[var(--foreground)]">
                                        {parsed.unitTitle}
                                      </span>
                                      {hasConcepts ? (
                                        <span className="rounded-md bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
                                          {t("{{count}} concepts", {
                                            count: parsed.concepts.length,
                                          })}
                                        </span>
                                      ) : null}
                                    </div>
                                  </div>

                                  {courseId ? (
                                    <button
                                      type="button"
                                      onClick={() =>
                                        handleStudyTopic(
                                          cleanTitle,
                                          parsed.unitTitle,
                                        )
                                      }
                                      className="inline-flex shrink-0 items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-[11px] font-medium text-[var(--muted-foreground)] transition-all hover:border-[var(--foreground)]/40 hover:bg-[var(--foreground)] hover:text-[var(--background)]"
                                      aria-label={t("Study this entire topic")}
                                    >
                                      <span>{t("Study Unit")}</span>
                                      <ArrowRight size={11} />
                                    </button>
                                  ) : null}
                                </div>

                                {/* Level 4: Concepts / Sub-topics Pills */}
                                {hasConcepts ? (
                                  <div className="mt-2 border-t border-[var(--border)]/50 pt-2">
                                    <div className="flex flex-wrap items-center gap-1.5">
                                      <span className="mr-0.5 text-[10px] font-medium uppercase tracking-wider text-[var(--muted-foreground)]">
                                        {t("Concepts")}:
                                      </span>
                                      {parsed.concepts.map((concept, cIdx) => (
                                        <button
                                          key={cIdx}
                                          type="button"
                                          onClick={(e) =>
                                            handleStudyConcept(
                                              cleanTitle,
                                              parsed.unitTitle,
                                              concept,
                                              e,
                                            )
                                          }
                                          className="group/concept inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/80 bg-[var(--background)] px-2 py-1 text-[11px] text-[var(--foreground)] transition-all hover:border-sky-500/50 hover:bg-sky-500/5 hover:text-sky-600 dark:hover:text-sky-400 active:scale-[0.98]"
                                          aria-label={t(
                                            "Click to study concept '{{concept}}'",
                                            {
                                              concept,
                                            },
                                          )}
                                        >
                                          <span className="font-medium">
                                            {concept}
                                          </span>
                                          <span className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[9.5px] font-medium text-sky-600 dark:text-sky-400 bg-sky-500/10 group-hover/concept:bg-sky-500/20 transition-colors">
                                            <Sparkles
                                              size={9.5}
                                              className="shrink-0"
                                            />
                                            <span>{t("Study concept")}</span>
                                          </span>
                                        </button>
                                      ))}
                                    </div>
                                  </div>
                                ) : null}
                              </li>
                            );
                          })}
                        </ul>
                      </>
                    ) : null}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
