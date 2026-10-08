"use client";

import { useMemo } from "react";
import Link from "next/link";
import {
  BookOpen,
  Compass,
  ExternalLink,
  FileText,
  Github,
  Play,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { StudyCourse } from "@/lib/courses-api";

/**
 * Slide deck item in the course materials directory.
 */
export interface LectureSlideItem {
  id: string;
  lectureNumber: number;
  title: string;
  filename: string;
  url: string;
  mirrorUrl?: string;
  readingWorkspaceUrl?: string;
  description?: string;
}

/**
 * Video lecture item with recording and timed media transcript info.
 */
export interface VideoLectureItem {
  id: string;
  lectureNumber: number;
  title: string;
  youtubeId: string;
  youtubeUrl: string;
  transcriptUrl: string;
  description?: string;
}

/**
 * Official course materials data structure.
 */
export interface CourseMaterialsData {
  syllabusUrl: string;
  syllabusTitle: string;
  syllabusDescription: string;
  slides: LectureSlideItem[];
  videos: VideoLectureItem[];
  cheatsheetUrl: string;
  cheatsheetPdfUrl?: string;
  cheatsheetTitle: string;
  cheatsheetDescription: string;
  textbookUrl: string;
  textbookTitle: string;
  textbookDescription: string;
}

export interface CourseMaterialsProps {
  course?: StudyCourse | null;
  courseId?: string;
  className?: string;
  materials?: Partial<CourseMaterialsData>;
}

/**
 * Default official materials for Stanford CME 295: Transformers & LLMs.
 */
const DEFAULT_CME295_MATERIALS: CourseMaterialsData = {
  syllabusUrl: "https://cme295.stanford.edu/syllabus/",
  syllabusTitle: "Official Syllabus Website",
  syllabusDescription:
    "Course schedule, grading policies, lecture calendar, and prerequisites at Stanford CME 295.",
  slides: [
    {
      id: "lecture-1-slide",
      lectureNumber: 1,
      title: "Lecture 1: Transformers & Self-Attention",
      filename: "fall26-cme295-lecture1.pdf",
      url: "https://cme295.stanford.edu/slides/fall26-cme295-lecture1.pdf",
      mirrorUrl:
        "https://raw.githubusercontent.com/afshinea/stanford-cme-295-transformers-large-language-models/main/en/cheatsheet-transformers-large-language-models.pdf",
      readingWorkspaceUrl:
        "/learning/reading/rw_3f8b01ffbee24ecf9ad3f21e1d2f11ae",
      description: "Architecture breakdown, multi-head attention, and layer normalization.",
    },
    {
      id: "lecture-2-slide",
      lectureNumber: 2,
      title: "Lecture 2: Large Language Models & Scaling",
      filename: "fall26-cme295-lecture2.pdf",
      url: "https://cme295.stanford.edu/slides/fall26-cme295-lecture2.pdf",
      mirrorUrl:
        "https://raw.githubusercontent.com/afshinea/stanford-cme-295-transformers-large-language-models/main/en/cheatsheet-transformers-large-language-models.pdf",
      description: "Compute scaling laws, tokenization strategies, and autoregressive training.",
    },
  ],
  videos: [
    {
      id: "lecture-1-video",
      lectureNumber: 1,
      title: "Lecture 1: Transformers",
      youtubeId: "114i2Kz-LZA",
      youtubeUrl: "https://www.youtube.com/watch?v=114i2Kz-LZA",
      transcriptUrl:
        "/learning/watching?video=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3D114i2Kz-LZA",
      description:
        "Full 1h 44m lecture recording with interactive synchronized transcript.",
    },
  ],
  cheatsheetUrl:
    "https://github.com/afshinea/stanford-cme-295-transformers-large-language-models",
  cheatsheetPdfUrl:
    "https://raw.githubusercontent.com/afshinea/stanford-cme-295-transformers-large-language-models/main/en/cheatsheet-transformers-large-language-models.pdf",
  cheatsheetTitle: "VIP Cheatsheet & Code",
  cheatsheetDescription:
    "Official GitHub repository with transformer cheatsheets, PyTorch implementations, and lab exercises.",
  textbookUrl: "https://superstudy.guide",
  textbookTitle: "Super Study Guide",
  textbookDescription:
    "Interactive companion textbook and deep study guide for transformer foundations.",
};

export default function CourseMaterials({
  course,
  courseId,
  className = "",
  materials: customMaterials,
}: CourseMaterialsProps) {
  const { t } = useTranslation();

  const data: CourseMaterialsData = useMemo(() => {
    return {
      ...DEFAULT_CME295_MATERIALS,
      ...customMaterials,
    };
  }, [customMaterials]);

  const courseDisplayName =
    course?.name ||
    (courseId ? `Course ${courseId}` : "Stanford CME 295");

  return (
    <section
      aria-labelledby="course-materials-title"
      className={`rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 text-[var(--foreground)] transition-shadow ${className}`}
    >
      {/* Header */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-[var(--border)] pb-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h2
              id="course-materials-title"
              className="font-serif text-[17px] font-semibold text-[var(--foreground)]"
            >
              {t("Official course materials & resources")}
            </h2>
            <span className="rounded-full border border-[var(--border)] bg-[var(--muted)]/50 px-2 py-0.5 text-[11px] font-medium text-[var(--muted-foreground)]">
              {t("Verified syllabus")}
            </span>
          </div>
          <p className="mt-1 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "Primary textbooks, lecture slide decks, YouTube video recordings, timed transcripts, and code repositories for {{courseName}}.",
              { courseName: courseDisplayName },
            )}
          </p>
        </div>
      </div>

      {/* Materials Cards Grid */}
      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {/* 1. Official Syllabus Website */}
        <div className="flex flex-col justify-between rounded-xl border border-[var(--border)] bg-[var(--background)] p-4 transition-colors hover:border-[var(--ring)]/40 hover:bg-[var(--secondary)]/20">
          <div>
            <div className="flex items-start justify-between gap-2">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--secondary)] text-[var(--foreground)]">
                <Compass size={18} strokeWidth={2} aria-hidden="true" />
              </div>
              <span className="rounded-md border border-[var(--border)] bg-[var(--card)] px-1.5 py-0.5 font-mono text-[10.5px] text-[var(--muted-foreground)]">
                {t("Stanford")}
              </span>
            </div>
            <h3 className="mt-3 text-[14px] font-medium text-[var(--foreground)]">
              {data.syllabusTitle}
            </h3>
            <p className="mt-1 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
              {data.syllabusDescription}
            </p>
          </div>
          <div className="mt-4 pt-3 border-t border-[var(--border)]/60">
            <a
              href={data.syllabusUrl}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={t("Visit official syllabus website (opens in new tab)")}
              className="group inline-flex items-center gap-1.5 text-[12px] font-medium text-[var(--primary)] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] rounded"
            >
              <span>{t("Open syllabus website")}</span>
              <ExternalLink
                size={12}
                className="transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
                aria-hidden="true"
              />
            </a>
          </div>
        </div>

        {/* 2. Lecture Slides (PDF) Directory */}
        <div className="flex flex-col justify-between rounded-xl border border-[var(--border)] bg-[var(--background)] p-4 transition-colors hover:border-[var(--ring)]/40 hover:bg-[var(--secondary)]/20 sm:col-span-2 lg:col-span-1">
          <div>
            <div className="flex items-start justify-between gap-2">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--secondary)] text-[var(--foreground)]">
                <FileText size={18} strokeWidth={2} aria-hidden="true" />
              </div>
              <span className="rounded-md border border-[var(--border)] bg-[var(--card)] px-1.5 py-0.5 font-mono text-[10.5px] text-[var(--muted-foreground)]">
                {t("PDF Directory")}
              </span>
            </div>
            <h3 className="mt-3 text-[14px] font-medium text-[var(--foreground)]">
              {t("Lecture slides (PDF)")}
            </h3>
            <p className="mt-1 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
              {t("Official slide decks and technical handouts for lectures.")}
            </p>

            <ul className="mt-3 space-y-2" role="list">
              {data.slides.map((slide) => (
                <li
                  key={slide.id}
                  className="rounded-lg border border-[var(--border)]/80 bg-[var(--card)] p-2.5 transition-colors hover:bg-[var(--secondary)]/30"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 text-[12px] font-medium text-[var(--foreground)]">
                        <FileText size={13} className="shrink-0 text-[var(--muted-foreground)]" aria-hidden="true" />
                        <span className="truncate">{slide.title}</span>
                      </div>
                      <code className="mt-0.5 block truncate text-[10.5px] text-[var(--muted-foreground)]">
                        {slide.filename}
                      </code>
                    </div>
                    <div className="flex flex-wrap items-center justify-end gap-1.5 shrink-0">
                      <a
                        href={slide.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label={`${t("Download or view")} ${slide.filename} (opens in new tab)`}
                        className="inline-flex shrink-0 items-center gap-1 rounded bg-[var(--secondary)] px-2 py-1 text-[11px] font-medium text-[var(--foreground)] hover:bg-[var(--muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                      >
                        <span>{t("PDF")}</span>
                        <ExternalLink size={10} aria-hidden="true" />
                      </a>
                      {slide.mirrorUrl ? (
                        <a
                          href={slide.mirrorUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          aria-label={`${t("GitHub mirror")} ${slide.filename} (opens in new tab)`}
                          className="inline-flex shrink-0 items-center gap-1 rounded border border-[var(--border)] bg-[var(--card)] px-1.5 py-1 text-[11px] font-medium text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                        >
                          <Github size={10} aria-hidden="true" />
                          <span>{t("GitHub mirror")}</span>
                        </a>
                      ) : null}
                      {slide.readingWorkspaceUrl ? (
                        <Link
                          href={slide.readingWorkspaceUrl}
                          aria-label={`${t("Read on DeepTutor")} ${slide.filename}`}
                          className="inline-flex shrink-0 items-center gap-1 rounded border border-[var(--border)] bg-[var(--card)] px-1.5 py-1 text-[11px] font-medium text-[var(--primary)] hover:bg-[var(--secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                        >
                          <BookOpen size={10} aria-hidden="true" />
                          <span>{t("Read on DeepTutor")}</span>
                        </Link>
                      ) : null}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-[11px] leading-relaxed text-[var(--muted-foreground)] border-t border-[var(--border)]/40 pt-2">
              {t("If Stanford server times out, use GitHub mirror or DeepTutor reading workspace.")}
            </p>
          </div>
        </div>

        {/* 3. Video & Lectures */}
        <div className="flex flex-col justify-between rounded-xl border border-[var(--border)] bg-[var(--background)] p-4 transition-colors hover:border-[var(--ring)]/40 hover:bg-[var(--secondary)]/20">
          <div>
            <div className="flex items-start justify-between gap-2">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--secondary)] text-[var(--foreground)]">
                <Play size={18} strokeWidth={2} aria-hidden="true" />
              </div>
              <span className="rounded-md border border-[var(--border)] bg-[var(--card)] px-1.5 py-0.5 font-mono text-[10.5px] text-[var(--muted-foreground)]">
                {t("Video & Media")}
              </span>
            </div>
            <h3 className="mt-3 text-[14px] font-medium text-[var(--foreground)]">
              {t("Video & lectures")}
            </h3>
            <p className="mt-1 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
              {t("Full-length lecture recordings with timed media transcripts.")}
            </p>

            <div className="mt-3 space-y-2">
              {data.videos.map((video) => (
                <div
                  key={video.id}
                  className="rounded-lg border border-[var(--border)]/80 bg-[var(--card)] p-2.5"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[12px] font-medium text-[var(--foreground)]">
                      {video.title}
                    </span>
                    <span className="rounded bg-[var(--muted)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--muted-foreground)]">
                      {t("YouTube")}: {video.youtubeId}
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
                    {video.description}
                  </p>
                  <div className="mt-2.5 flex flex-wrap items-center gap-2">
                    <a
                      href={video.youtubeUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={`${t("Watch")} ${video.title} ${t("on YouTube (opens in new tab)")}`}
                      className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--secondary)] px-2.5 py-1 text-[11.5px] font-medium text-[var(--foreground)] hover:bg-[var(--muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                    >
                      <Play size={11} className="fill-current" aria-hidden="true" />
                      <span>{t("YouTube")}</span>
                      <ExternalLink size={10} aria-hidden="true" />
                    </a>
                    <Link
                      href={video.transcriptUrl}
                      aria-label={`${t("Open timed media transcript for")} ${video.title}`}
                      className="inline-flex items-center gap-1 rounded-md bg-[var(--foreground)] px-2.5 py-1 text-[11.5px] font-medium text-[var(--background)] hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                    >
                      <Play size={11} aria-hidden="true" />
                      <span>{t("Timed media transcript")}</span>
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* 4. VIP Cheatsheet & Code */}
        <div className="flex flex-col justify-between rounded-xl border border-[var(--border)] bg-[var(--background)] p-4 transition-colors hover:border-[var(--ring)]/40 hover:bg-[var(--secondary)]/20">
          <div>
            <div className="flex items-start justify-between gap-2">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--secondary)] text-[var(--foreground)]">
                <Github size={18} strokeWidth={2} aria-hidden="true" />
              </div>
              <span className="rounded-md border border-[var(--border)] bg-[var(--card)] px-1.5 py-0.5 font-mono text-[10.5px] text-[var(--muted-foreground)]">
                {t("GitHub Repo")}
              </span>
            </div>
            <h3 className="mt-3 text-[14px] font-medium text-[var(--foreground)]">
              {data.cheatsheetTitle}
            </h3>
            <p className="mt-1 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
              {data.cheatsheetDescription}
            </p>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2 pt-3 border-t border-[var(--border)]/60">
            {data.cheatsheetPdfUrl ? (
              <a
                href={data.cheatsheetPdfUrl}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={t("Download VIP Cheatsheet PDF (opens in new tab)")}
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--secondary)] px-2.5 py-1 text-[11.5px] font-medium text-[var(--foreground)] hover:bg-[var(--muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
              >
                <FileText size={12} aria-hidden="true" />
                <span>{t("VIP Cheatsheet PDF")}</span>
                <ExternalLink size={10} aria-hidden="true" />
              </a>
            ) : null}
            <a
              href={data.cheatsheetUrl}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={t("Open VIP cheatsheet and code repository on GitHub (opens in new tab)")}
              className="group inline-flex items-center gap-1.5 text-[12px] font-medium text-[var(--primary)] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] rounded"
            >
              <Github size={13} aria-hidden="true" />
              <span>{t("Open GitHub repository")}</span>
              <ExternalLink
                size={12}
                className="transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
                aria-hidden="true"
              />
            </a>
          </div>
        </div>

        {/* 5. Super Study Guide Textbook */}
        <div className="flex flex-col justify-between rounded-xl border border-[var(--border)] bg-[var(--background)] p-4 transition-colors hover:border-[var(--ring)]/40 hover:bg-[var(--secondary)]/20">
          <div>
            <div className="flex items-start justify-between gap-2">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--secondary)] text-[var(--foreground)]">
                <BookOpen size={18} strokeWidth={2} aria-hidden="true" />
              </div>
              <span className="rounded-md border border-[var(--border)] bg-[var(--card)] px-1.5 py-0.5 font-mono text-[10.5px] text-[var(--muted-foreground)]">
                {t("Textbook")}
              </span>
            </div>
            <h3 className="mt-3 text-[14px] font-medium text-[var(--foreground)]">
              {data.textbookTitle}
            </h3>
            <p className="mt-1 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
              {data.textbookDescription}
            </p>
          </div>
          <div className="mt-4 pt-3 border-t border-[var(--border)]/60">
            <a
              href={data.textbookUrl}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={t("Visit Super Study Guide website (opens in new tab)")}
              className="group inline-flex items-center gap-1.5 text-[12px] font-medium text-[var(--primary)] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] rounded"
            >
              <BookOpen size={13} aria-hidden="true" />
              <span>{t("Open superstudy.guide")}</span>
              <ExternalLink
                size={12}
                className="transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
                aria-hidden="true"
              />
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
