"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Download, Loader2, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  SettingRow,
  SettingSection,
  SettingsPageHeader,
  nativeSelectClass,
  selectOptionClass,
} from "@/components/settings/shared";
import { MinerUEngineSettings } from "@/components/settings/MinerUEngineSettings";
import { Toggle } from "@/components/settings/Toggle";
import { apiFetch, apiUrl } from "@/lib/api";

type EngineMeta = {
  id: string;
  name: string;
  description: string;
  needs_local_models: boolean;
  available: boolean;
};

type Readiness = { ready: boolean; reason: string; message: string };

type DocumentParsingPayload = {
  engine: string;
  engines: Record<string, Record<string, unknown>>;
  available_engines: EngineMeta[];
  readiness: Record<string, Readiness>;
  installable: string[];
  mineru: { api_token_set: boolean; local_cli?: unknown };
};

const PIP_HINT: Record<string, string> = {
  docling: "pip install deeptutor[parse-docling]",
  markitdown: "pip install deeptutor[parse-markitdown]",
  pymupdf4llm: "pip install deeptutor[parse-pymupdf4llm]",
};

export default function DocumentParsingSettingsPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<DocumentParsingPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const response = await apiFetch(
        apiUrl("/api/v1/settings/document-parsing"),
      );
      const payload = (await response.json().catch(() => ({}))) as
        | DocumentParsingPayload
        | { detail?: string };
      if (!response.ok) {
        throw new Error(
          "detail" in payload && payload.detail
            ? payload.detail
            : t("Failed to load document parsing settings."),
        );
      }
      setData(payload as DocumentParsingPayload);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const putDocumentParsing = useCallback(
    async (body: Record<string, unknown>) => {
      setBusy(true);
      setError(null);
      try {
        const response = await apiFetch(
          apiUrl("/api/v1/settings/document-parsing"),
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          },
        );
        const payload = (await response.json().catch(() => ({}))) as
          | DocumentParsingPayload
          | { detail?: string };
        if (!response.ok) {
          throw new Error(
            "detail" in payload && payload.detail
              ? payload.detail
              : t("Failed to save document parsing settings."),
          );
        }
        setData(payload as DocumentParsingPayload);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [t],
  );

  return (
    <div>
      <SettingsPageHeader
        title={t("Document Parsing")}
        description={t(
          "How uploaded documents are converted into text for knowledge bases and question generation. Pick an engine and its options. Local model downloads are off by default — they only happen when you explicitly allow them.",
        )}
      />

      {loading && (
        <div className="flex items-center gap-2 text-[13px] text-[var(--muted-foreground)]">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("Loading...")}
        </div>
      )}

      {!loading && error && (
        <div className="mb-5 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-[13px] text-red-600 dark:text-red-300">
          {error}
        </div>
      )}

      {!loading && data && (
        <>
          <section className="mb-10">
            <header className="mb-3">
              <h2 className="text-[15px] font-semibold tracking-tight text-[var(--foreground)]">
                {t("Engine")}
              </h2>
              <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
                {t(
                  "The active engine handles all parsing. Text-only is built in and extracts plain text; markitdown is lightweight and optional; MinerU and Docling produce richer structure but may need local models or a hosted API.",
                )}
              </p>
            </header>
            <div className="flex flex-col gap-2">
              {data.available_engines.map((engine) => {
                const active = engine.id === data.engine;
                return (
                  <button
                    key={engine.id}
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      !active && putDocumentParsing({ engine: engine.id })
                    }
                    className={`flex items-start justify-between gap-4 rounded-xl border px-4 py-3 text-left transition-colors disabled:opacity-60 ${
                      active
                        ? "border-[var(--foreground)] bg-[var(--card)]"
                        : "border-[var(--border)] hover:border-[var(--foreground)]/40"
                    }`}
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-[13px] font-medium text-[var(--foreground)]">
                          {engine.name}
                        </span>
                        {active && (
                          <span className="rounded-full bg-[var(--foreground)] px-2 py-0.5 text-[10px] font-medium text-[var(--background)]">
                            {t("Active")}
                          </span>
                        )}
                        {!engine.available && (
                          <span className="rounded-full border border-[var(--border)] px-2 py-0.5 text-[10px] text-[var(--muted-foreground)]">
                            {t("Not installed")}
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-[12px] text-[var(--muted-foreground)]">
                        {engine.description}
                      </p>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>

          {data.engine === "text_only" && <TextOnlyPanel />}

          {data.engine === "mineru" && <MinerUEngineSettings />}

          {data.engine === "docling" && (
            <DoclingPanel
              slice={data.engines.docling || {}}
              readiness={data.readiness.docling}
              available={
                data.available_engines.find((e) => e.id === "docling")
                  ?.available ?? false
              }
              busy={busy}
              onInstalled={load}
              onSave={(patch) =>
                putDocumentParsing({ engines: { docling: patch } })
              }
            />
          )}

          {data.engine === "markitdown" && (
            <MarkItDownPanel
              slice={data.engines.markitdown || {}}
              available={
                data.available_engines.find((e) => e.id === "markitdown")
                  ?.available ?? false
              }
              busy={busy}
              onInstalled={load}
              onSave={(patch) =>
                putDocumentParsing({ engines: { markitdown: patch } })
              }
            />
          )}

          {data.engine === "pymupdf4llm" && (
            <PyMuPDF4LLMPanel
              slice={data.engines.pymupdf4llm || {}}
              available={
                data.available_engines.find((e) => e.id === "pymupdf4llm")
                  ?.available ?? false
              }
              busy={busy}
              onInstalled={load}
              onSave={(patch) =>
                putDocumentParsing({ engines: { pymupdf4llm: patch } })
              }
            />
          )}
        </>
      )}
    </div>
  );
}

function TextOnlyPanel() {
  const { t } = useTranslation();
  return (
    <SettingSection
      title={t("Text-only")}
      description={t(
        "Built-in plain text extraction for PDF, Office, and text files. No optional parser package, model download, OCR, or layout reconstruction.",
      )}
    >
      <SettingRow
        title={t("Model status")}
        control={
          <ReadinessBadge
            readiness={{ ready: true, reason: "ready", message: "" }}
          />
        }
      />
    </SettingSection>
  );
}

function ReadinessBadge({ readiness }: { readiness?: Readiness }) {
  const { t } = useTranslation();
  if (!readiness) return null;
  return (
    <span
      className={`inline-flex items-center gap-1 text-[12px] ${
        readiness.ready
          ? "text-emerald-600 dark:text-emerald-400"
          : "text-amber-600 dark:text-amber-400"
      }`}
    >
      {readiness.ready ? (
        <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
      ) : (
        <XCircle className="h-3.5 w-3.5 shrink-0" />
      )}
      {readiness.ready ? t("Ready to parse.") : readiness.message}
    </span>
  );
}

// Full-width readiness line for engines whose "not ready" guidance is a
// multi-sentence message (e.g. Docling's "models not downloaded" hint). A long
// message must wrap full-width — it doesn't fit a SettingRow's compact,
// non-shrinking control slot (which overflows and squeezes the title).
function ReadinessNotice({ readiness }: { readiness?: Readiness }) {
  const { t } = useTranslation();
  if (!readiness) return null;
  if (readiness.ready) {
    return (
      <div className="flex items-center gap-1.5 px-1 py-4 text-[12px] text-emerald-600 dark:text-emerald-400">
        <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
        {t("Ready to parse.")}
      </div>
    );
  }
  return (
    <div className="px-1 py-4">
      <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-[12px] leading-relaxed text-amber-700 dark:text-amber-300">
        <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span className="min-w-0">{readiness.message}</span>
      </div>
    </div>
  );
}

function DoclingPanel({
  slice,
  readiness,
  available,
  busy,
  onInstalled,
  onSave,
}: {
  slice: Record<string, unknown>;
  readiness?: Readiness;
  available: boolean;
  busy: boolean;
  onInstalled: () => void;
  onSave: (patch: Record<string, unknown>) => void;
}) {
  const { t } = useTranslation();
  const doOcr = Boolean(slice.do_ocr);
  const doTables = slice.do_table_structure !== false;
  const allowDownload = Boolean(slice.allow_local_model_download);

  if (!available) {
    return (
      <NotInstalledSection
        engineId="docling"
        title={t("Docling")}
        onInstalled={onInstalled}
      />
    );
  }

  return (
    <SettingSection
      title={t("Docling")}
      description={t(
        "Structured conversion of PDF/Office/HTML/images. Downloads layout/table models on first run.",
      )}
    >
      <ReadinessNotice readiness={readiness} />
      {readiness && !readiness.ready && (
        <ModelDownloadRow
          engineId="docling"
          title={t("Docling")}
          onDownloaded={onInstalled}
        />
      )}
      <SettingRow
        title={t("Allow automatic model download")}
        description={t(
          "Off by default. When off, parsing fails with guidance instead of silently downloading models. Or pre-fetch with `docling-tools models download`.",
        )}
        control={
          <Toggle
            checked={allowDownload}
            disabled={busy}
            onChange={(v) => onSave({ allow_local_model_download: v })}
          />
        }
      />
      <SettingRow
        title={t("Recognize tables")}
        control={
          <Toggle
            checked={doTables}
            disabled={busy}
            onChange={(v) => onSave({ do_table_structure: v })}
          />
        }
      />
      <SettingRow
        title={t("OCR scanned pages")}
        description={t("Slower; enable for image-only PDFs.")}
        control={
          <Toggle
            checked={doOcr}
            disabled={busy}
            onChange={(v) => onSave({ do_ocr: v })}
          />
        }
      />
    </SettingSection>
  );
}

function MarkItDownPanel({
  slice,
  available,
  busy,
  onInstalled,
  onSave,
}: {
  slice: Record<string, unknown>;
  available: boolean;
  busy: boolean;
  onInstalled: () => void;
  onSave: (patch: Record<string, unknown>) => void;
}) {
  const { t } = useTranslation();
  const llmImages = Boolean(slice.enable_llm_image_description);

  if (!available) {
    return (
      <NotInstalledSection
        engineId="markitdown"
        title={t("markitdown")}
        onInstalled={onInstalled}
      />
    );
  }

  return (
    <SettingSection
      title={t("markitdown")}
      description={t(
        "Lightweight Markdown conversion with broad format support. No model downloads.",
      )}
    >
      <SettingRow
        title={t("Describe images with the vision model")}
        description={t(
          "Reserved — uses DeepTutor's vision model to caption images during conversion.",
        )}
        control={
          <Toggle
            checked={llmImages}
            disabled={busy}
            onChange={(v) => onSave({ enable_llm_image_description: v })}
          />
        }
      />
    </SettingSection>
  );
}

const PYMUPDF4LLM_IMAGE_FORMATS = ["png", "jpg", "jpeg", "webp"];

function PyMuPDF4LLMPanel({
  slice,
  available,
  busy,
  onInstalled,
  onSave,
}: {
  slice: Record<string, unknown>;
  available: boolean;
  busy: boolean;
  onInstalled: () => void;
  onSave: (patch: Record<string, unknown>) => void;
}) {
  const { t } = useTranslation();
  const writeImages = slice.write_images !== false;
  const imageFormat =
    typeof slice.image_format === "string" ? slice.image_format : "png";
  const imageDpi = typeof slice.image_dpi === "number" ? slice.image_dpi : 150;

  if (!available) {
    return (
      <NotInstalledSection
        engineId="pymupdf4llm"
        title={t("PyMuPDF4LLM")}
        onInstalled={onInstalled}
      />
    );
  }

  return (
    <SettingSection
      title={t("PyMuPDF4LLM")}
      description={t(
        "Lightweight PDF/e-book → Markdown built on PyMuPDF. No model downloads or CUDA, so it runs on low-end machines.",
      )}
    >
      <SettingRow
        title={t("Extract images")}
        description={t(
          "Save embedded images and rendered vector graphics into the parse, referenced from the Markdown.",
        )}
        control={
          <Toggle
            checked={writeImages}
            disabled={busy}
            onChange={(v) => onSave({ write_images: v })}
          />
        }
      />
      {writeImages && (
        <>
          <SettingRow
            title={t("Image format")}
            control={
              <select
                className={`${nativeSelectClass} w-28`}
                value={imageFormat}
                disabled={busy}
                onChange={(e) => onSave({ image_format: e.target.value })}
              >
                {PYMUPDF4LLM_IMAGE_FORMATS.map((f) => (
                  <option key={f} className={selectOptionClass} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            }
          />
          <SettingRow
            title={t("Image resolution (DPI)")}
            description={t("Higher is sharper but larger. 72–600.")}
            control={
              <input
                type="number"
                min={72}
                max={600}
                step={1}
                value={imageDpi}
                disabled={busy}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  if (Number.isFinite(v)) onSave({ image_dpi: v });
                }}
                className="w-24 rounded-lg border border-[var(--border)] bg-transparent px-2 py-1 text-[12px] text-[var(--foreground)]"
              />
            }
          />
        </>
      )}
    </SettingSection>
  );
}

type JobKind = "install" | "models";

type JobStatus = {
  state: "running" | "done" | "failed" | "cancelled" | string;
  kind: JobKind;
  lines: string[];
  message: string;
};

// Shared driver for the page's one-click background jobs (pip install / model
// download). Mirrors the MinerU model-download UI: POST to start → poll a shared
// cursor-based log filtered by `kind` → call onDone once on success. Only one
// job runs server-side at a time, so the kind filter keeps each card's view to
// its own job.
function useBackgroundJob(
  kind: JobKind,
  startUrl: string,
  engineId: string,
  onDone: () => void,
) {
  const { t } = useTranslation();
  const [job, setJob] = useState<JobStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const cursor = useRef(0);
  const notifiedDone = useRef(false);

  useEffect(() => {
    if (job?.state !== "running") return;
    const timer = setInterval(async () => {
      try {
        const response = await apiFetch(
          apiUrl(
            `/api/v1/settings/document-parsing/job/status?cursor=${cursor.current}`,
          ),
        );
        if (!response.ok) return;
        const data = (await response.json()) as {
          state?: string;
          kind?: string;
          lines?: string[];
          next_cursor?: number;
          message?: string;
        };
        // A different kind of job is running — leave our view alone.
        if (data.kind && data.kind !== kind) return;
        cursor.current = data.next_cursor ?? cursor.current;
        setJob((current) =>
          current
            ? {
                state: data.state || current.state,
                kind,
                lines: [...current.lines, ...(data.lines || [])].slice(-100),
                message: data.message || "",
              }
            : current,
        );
        if (data.state === "done" && !notifiedDone.current) {
          notifiedDone.current = true;
          onDone();
        }
      } catch {
        // transient network error — keep polling
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [job?.state, kind, onDone]);

  async function start() {
    setStarting(true);
    notifiedDone.current = false;
    try {
      const response = await apiFetch(apiUrl(startUrl), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ engine: engineId }),
      });
      const data = (await response.json().catch(() => ({}))) as {
        ok?: boolean;
        message?: string;
        detail?: string;
      };
      if (!response.ok || !data.ok) {
        setJob({
          state: "failed",
          kind,
          lines: [],
          message: data.message || data.detail || t("Failed."),
        });
        return;
      }
      cursor.current = 0;
      setJob({ state: "running", kind, lines: [], message: "" });
    } finally {
      setStarting(false);
    }
  }

  async function cancel() {
    try {
      await apiFetch(apiUrl("/api/v1/settings/document-parsing/job/cancel"), {
        method: "POST",
      });
    } catch {
      // status polling surfaces the final state either way
    }
  }

  return { job, starting, start, cancel };
}

// Status line + streamed log for a background job, shared by install / download.
function JobLog({
  job,
  runningLabel,
  doneLabel,
}: {
  job: JobStatus | null;
  runningLabel: string;
  doneLabel: string;
}) {
  if (!job) return null;
  return (
    <div className="px-1 pb-1">
      <div
        className={`mb-2 inline-flex items-center gap-1.5 text-[12px] ${
          job.state === "done"
            ? "text-emerald-600 dark:text-emerald-400"
            : job.state === "running"
              ? "text-[var(--muted-foreground)]"
              : "text-red-600 dark:text-red-400"
        }`}
      >
        {job.state === "running" ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : job.state === "done" ? (
          <CheckCircle2 className="h-3.5 w-3.5" />
        ) : (
          <XCircle className="h-3.5 w-3.5" />
        )}
        {job.state === "running"
          ? runningLabel
          : job.state === "done"
            ? doneLabel
            : job.message || job.state}
      </div>
      {job.lines.length > 0 && (
        <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap rounded-lg border border-[var(--border)]/60 bg-[var(--card)] px-3 py-2 font-mono text-[11px] leading-relaxed text-[var(--muted-foreground)]">
          {job.lines.join("\n")}
        </pre>
      )}
    </div>
  );
}

function JobButton({
  running,
  starting,
  label,
  onStart,
  onCancel,
}: {
  running: boolean;
  starting: boolean;
  label: string;
  onStart: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  if (running) {
    return (
      <button
        type="button"
        onClick={onCancel}
        className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12px] font-medium text-[var(--foreground)] transition-opacity hover:opacity-80"
      >
        {t("Cancel")}
      </button>
    );
  }
  return (
    <button
      type="button"
      onClick={onStart}
      disabled={starting}
      className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-[12px] font-medium text-[var(--background)] transition-opacity hover:opacity-80 disabled:opacity-40"
    >
      {starting ? (
        <Loader2 className="h-3 w-3 animate-spin" />
      ) : (
        <Download className="h-3 w-3" />
      )}
      {label}
    </button>
  );
}

// The active engine's panel when its optional package isn't installed: a clean
// section with the pip hint and a one-click installer. Keeps install in ONE
// place per engine; reloads on success so the engine flips to available.
function NotInstalledSection({
  engineId,
  title,
  onInstalled,
}: {
  engineId: string;
  title: string;
  onInstalled: () => void;
}) {
  const { t } = useTranslation();
  const { job, starting, start, cancel } = useBackgroundJob(
    "install",
    "/api/v1/settings/document-parsing/install",
    engineId,
    onInstalled,
  );

  return (
    <SettingSection
      title={title}
      description={t(
        "Not installed yet. Install the package to use this engine — runs on the server, no terminal needed.",
      )}
    >
      <SettingRow
        title={t("Install package")}
        description={PIP_HINT[engineId]}
        control={
          <JobButton
            running={job?.state === "running"}
            starting={starting}
            label={t("Download & install")}
            onStart={start}
            onCancel={cancel}
          />
        }
      />
      <JobLog
        job={job}
        runningLabel={t("Installing {{name}}…", { name: title })}
        doneLabel={t("Installed. Reloading…")}
      />
    </SettingSection>
  );
}

// One-click model-weight download for an installed engine that still needs its
// models (e.g. Docling). Mirrors MinerU's "Download models"; reloads readiness
// on success so the gate clears.
function ModelDownloadRow({
  engineId,
  title,
  onDownloaded,
}: {
  engineId: string;
  title: string;
  onDownloaded: () => void;
}) {
  const { t } = useTranslation();
  const { job, starting, start, cancel } = useBackgroundJob(
    "models",
    "/api/v1/settings/document-parsing/models/download",
    engineId,
    onDownloaded,
  );

  return (
    <>
      <SettingRow
        title={t("Download models")}
        description={t(
          "Fetch the model weights onto the server now — no terminal needed.",
        )}
        control={
          <JobButton
            running={job?.state === "running"}
            starting={starting}
            label={t("Download models")}
            onStart={start}
            onCancel={cancel}
          />
        }
      />
      <JobLog
        job={job}
        runningLabel={t("Downloading {{name}} models…", { name: title })}
        doneLabel={t("Downloaded. Reloading…")}
      />
    </>
  );
}
