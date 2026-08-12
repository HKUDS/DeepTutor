"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle2, Loader2, Save, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  SettingRow,
  SettingSection,
  inputClass,
  nativeSelectClass,
  selectOptionClass,
} from "@/components/settings/shared";
import { Toggle } from "@/components/settings/Toggle";
import { apiFetch, apiUrl } from "@/lib/api";

type MinerUMode = "local" | "cloud";
type MinerUModelVersion = "pipeline" | "vlm";
type MinerUDownloadSource = "huggingface" | "modelscope";
type MinerUDownloadType = "pipeline" | "vlm" | "all";

const DEFAULT_BASE_URL = "https://mineru.net";
const DEFAULT_HF_ENDPOINT = "https://huggingface.co";
const LANGUAGE_AUTO = "auto";
const TOKEN_MASK = "••••••••••••";
const MODEL_VERSIONS: MinerUModelVersion[] = ["pipeline", "vlm"];
const DOWNLOAD_SOURCES: MinerUDownloadSource[] = ["huggingface", "modelscope"];
const DOWNLOAD_SOURCE_LABELS: Record<MinerUDownloadSource, string> = {
  huggingface: "HuggingFace",
  modelscope: "ModelScope",
};
const DOWNLOAD_TYPES: MinerUDownloadType[] = ["pipeline", "vlm", "all"];

type MinerUSettings = {
  mode: MinerUMode;
  api_base_url: string;
  local_cli_path: string;
  model_download_source: MinerUDownloadSource;
  model_download_endpoint: string;
  model_version: MinerUModelVersion;
  language: string;
  enable_formula: boolean;
  enable_table: boolean;
  is_ocr: boolean;
  allow_local_model_download: boolean;
};

type DownloadStatus = {
  state: "running" | "done" | "failed" | "cancelled" | string;
  lines: string[];
  message: string;
};

type MinerUPayload = {
  settings: MinerUSettings & { version?: number };
  api_token_set: boolean;
  local_cli?: {
    found: boolean;
    command: string;
    path: string;
    source?: "configured" | "path";
  };
};

function normalizeDraft(payload: MinerUPayload): MinerUSettings {
  const s = payload.settings;
  return {
    mode: s.mode === "cloud" ? "cloud" : "local",
    api_base_url: s.api_base_url || "https://mineru.net",
    local_cli_path: s.local_cli_path || "",
    model_download_source:
      s.model_download_source === "modelscope" ? "modelscope" : "huggingface",
    model_download_endpoint: s.model_download_endpoint || "",
    model_version: s.model_version === "vlm" ? "vlm" : "pipeline",
    language: s.language || "auto",
    enable_formula: Boolean(s.enable_formula),
    enable_table: Boolean(s.enable_table),
    is_ocr: Boolean(s.is_ocr),
    allow_local_model_download: Boolean(s.allow_local_model_download),
  };
}

export function MinerUEngineSettings() {
  const { t } = useTranslation();
  const [payload, setPayload] = useState<MinerUPayload | null>(null);
  const [draft, setDraft] = useState<MinerUSettings | null>(null);
  // Token is write-only: blank field + "set/not set" hint. Only sent on save
  // when the user actually edits it (tokenTouched).
  const [tokenDraft, setTokenDraft] = useState("");
  const [tokenTouched, setTokenTouched] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    ok: boolean;
    message: string;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [download, setDownload] = useState<DownloadStatus | null>(null);
  const [downloadType, setDownloadType] =
    useState<MinerUDownloadType>("pipeline");
  const [startingDownload, setStartingDownload] = useState(false);
  const downloadCursor = useRef(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const response = await apiFetch(apiUrl("/api/v1/settings/mineru"));
        const data = (await response.json().catch(() => ({}))) as
          | MinerUPayload
          | { detail?: string };
        if (!response.ok) {
          throw new Error(
            "detail" in data && data.detail
              ? data.detail
              : t("Failed to load MinerU settings."),
          );
        }
        if (cancelled) return;
        const next = data as MinerUPayload;
        setPayload(next);
        setDraft(normalizeDraft(next));
        setTokenDraft("");
        setTokenTouched(false);
      } catch (err) {
        if (!cancelled)
          setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [t]);

  const dirty = useMemo(() => {
    if (!payload || !draft) return false;
    const current = normalizeDraft(payload);
    return (
      tokenTouched ||
      current.mode !== draft.mode ||
      current.api_base_url !== draft.api_base_url ||
      current.local_cli_path !== draft.local_cli_path ||
      current.model_download_source !== draft.model_download_source ||
      current.model_download_endpoint !== draft.model_download_endpoint ||
      current.model_version !== draft.model_version ||
      current.language !== draft.language ||
      current.enable_formula !== draft.enable_formula ||
      current.enable_table !== draft.enable_table ||
      current.is_ocr !== draft.is_ocr ||
      current.allow_local_model_download !== draft.allow_local_model_download
    );
  }, [draft, payload, tokenTouched]);

  function patch(next: Partial<MinerUSettings>) {
    setDraft((current) => (current ? { ...current, ...next } : current));
  }

  async function save() {
    if (!draft) return;
    setSaving(true);
    setError(null);
    setMessage("");
    setTestResult(null);
    try {
      const body: Record<string, unknown> = {
        ...draft,
        api_token: tokenTouched ? tokenDraft : null,
      };
      const response = await apiFetch(apiUrl("/api/v1/settings/mineru"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = (await response.json().catch(() => ({}))) as
        | MinerUPayload
        | { detail?: string };
      if (!response.ok) {
        throw new Error(
          "detail" in data && data.detail
            ? data.detail
            : t("Failed to save MinerU settings."),
        );
      }
      const next = data as MinerUPayload;
      setPayload(next);
      setDraft(normalizeDraft(next));
      setTokenDraft("");
      setTokenTouched(false);
      setMessage(t("MinerU settings saved."));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function testConnection() {
    if (!draft) return;
    setTesting(true);
    setTestResult(null);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        ...draft,
        api_token: tokenTouched ? tokenDraft : null,
      };
      const response = await apiFetch(apiUrl("/api/v1/settings/mineru/test"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = (await response.json().catch(() => ({}))) as {
        ok?: boolean;
        message?: string;
        detail?: string;
      };
      if (!response.ok) {
        throw new Error(data.detail || t("Connection test failed."));
      }
      setTestResult({
        ok: Boolean(data.ok),
        message:
          data.message || (data.ok ? t("OK") : t("Connection test failed.")),
      });
    } catch (err) {
      setTestResult({
        ok: false,
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setTesting(false);
    }
  }

  // Poll the download job while it runs; the cursor protocol fetches only
  // new log lines each tick.
  useEffect(() => {
    if (download?.state !== "running") return;
    const timer = setInterval(async () => {
      try {
        const response = await apiFetch(
          apiUrl(
            `/api/v1/settings/mineru/models/download/status?cursor=${downloadCursor.current}`,
          ),
        );
        if (!response.ok) return;
        const data = (await response.json()) as {
          state?: string;
          lines?: string[];
          next_cursor?: number;
          message?: string;
        };
        downloadCursor.current = data.next_cursor ?? downloadCursor.current;
        setDownload((current) =>
          current
            ? {
                state: data.state || current.state,
                lines: [...current.lines, ...(data.lines || [])].slice(-100),
                message: data.message || "",
              }
            : current,
        );
      } catch {
        // transient network error — keep polling
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [download?.state]);

  async function startDownload() {
    if (!draft) return;
    setStartingDownload(true);
    try {
      const response = await apiFetch(
        apiUrl("/api/v1/settings/mineru/models/download"),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            model_type: downloadType,
            source: draft.model_download_source,
            endpoint: draft.model_download_endpoint,
            local_cli_path: draft.local_cli_path,
          }),
        },
      );
      const data = (await response.json().catch(() => ({}))) as {
        ok?: boolean;
        message?: string;
        detail?: string;
      };
      if (!response.ok || !data.ok) {
        setDownload({
          state: "failed",
          lines: [],
          message: data.message || data.detail || t("Download failed."),
        });
        return;
      }
      downloadCursor.current = 0;
      setDownload({ state: "running", lines: [], message: "" });
    } finally {
      setStartingDownload(false);
    }
  }

  async function cancelDownload() {
    try {
      await apiFetch(apiUrl("/api/v1/settings/mineru/models/download/cancel"), {
        method: "POST",
      });
    } catch {
      // status polling will surface the final state either way
    }
  }

  const tokenSet = payload?.api_token_set ?? false;
  const isCloud = draft?.mode === "cloud";
  const localCli = payload?.local_cli;

  function renderTestControl(label: string) {
    return (
      <div className="flex items-center gap-3">
        {testResult && (
          <span
            className={`inline-flex max-w-[40vw] items-center gap-1 text-[12px] ${
              testResult.ok
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-red-600 dark:text-red-400"
            }`}
          >
            {testResult.ok ? (
              <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
            ) : (
              <XCircle className="h-3.5 w-3.5 shrink-0" />
            )}
            {testResult.message}
          </span>
        )}
        <button
          type="button"
          onClick={testConnection}
          disabled={testing}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12px] font-medium text-[var(--foreground)] transition-opacity hover:opacity-80 disabled:opacity-40"
        >
          {testing && <Loader2 className="h-3 w-3 animate-spin" />}
          {label}
        </button>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-[13px] text-[var(--muted-foreground)]">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("Loading MinerU settings...")}
      </div>
    );
  }

  if (error && !draft) {
    return (
      <div className="mb-5 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-[13px] text-red-600 dark:text-red-300">
        {error}
      </div>
    );
  }

  if (!draft) return null;

  return (
    <>
      {error && (
        <div className="mb-5 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-[13px] text-red-600 dark:text-red-300">
          {error}
        </div>
      )}

      <SettingSection
        title={t("Parsing backend")}
        description={t("Choose where PDF parsing runs.")}
      >
        <SettingRow
          title={t("Mode")}
          description={
            isCloud
              ? t("Documents are uploaded to mineru.net for parsing.")
              : t(
                  "Parsing runs on this machine using the local MinerU install.",
                )
          }
          control={
            <div className="inline-flex rounded-lg border border-[var(--border)] p-0.5">
              {(["local", "cloud"] as MinerUMode[]).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => {
                    patch({ mode: m });
                    setTestResult(null);
                  }}
                  className={`rounded-md px-3 py-1 text-[12px] font-medium transition-colors ${
                    draft.mode === m
                      ? "bg-[var(--foreground)] text-[var(--background)]"
                      : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                  }`}
                >
                  {m === "local" ? t("Local") : t("Cloud API")}
                </button>
              ))}
            </div>
          }
        />
      </SettingSection>

      {!isCloud && (
        <SettingSection
          title={t("Local install")}
          description={t(
            "The MinerU CLI must be reachable by the DeepTutor server process. Reserve >=20 GB of free disk (official guidance): ~2-4 GB install, ~1-2 GB models lazily downloaded on first parse, plus parsing cache.",
          )}
        >
          <SettingRow
            title={
              localCli?.found
                ? t("MinerU CLI detected.")
                : localCli?.source === "configured"
                  ? t("Configured CLI path is not executable.")
                  : t("MinerU CLI not found on PATH.")
            }
            description={
              localCli?.found
                ? localCli.path
                : t(
                    'Install into any Python environment: uv pip install -U "mineru[core]" — then set the CLI path below, or install into the server environment for PATH auto-detection.',
                  )
            }
            control={renderTestControl(t("Check"))}
          />
          <SettingRow
            title={t("CLI path")}
            description={t(
              "Optional. Point to a mineru executable in an isolated environment (uv tool, pipx, conda) to avoid dependency conflicts. Leave blank to auto-detect from PATH.",
            )}
            control={
              <input
                className={`${inputClass} w-[320px] max-w-[48vw] font-mono text-[12px]`}
                placeholder={t("Auto-detect from PATH")}
                value={draft.local_cli_path}
                onChange={(e) => patch({ local_cli_path: e.target.value })}
              />
            }
          />
        </SettingSection>
      )}

      {!isCloud && (
        <SettingSection
          title={t("Model weights")}
          description={t(
            "Local parsing needs ~1-2 GB of model weights. By default they are NOT downloaded automatically — download them explicitly below, or allow automatic download on first parse.",
          )}
        >
          <SettingRow
            title={t("Allow automatic model download")}
            description={t(
              "Off by default. When off, a local parse fails with guidance instead of silently downloading multi-GB weights on first run. Turn on to let the first parse fetch models, or use the explicit download below.",
            )}
            control={
              <Toggle
                checked={draft.allow_local_model_download}
                onChange={(v) => patch({ allow_local_model_download: v })}
              />
            }
          />
          <SettingRow
            title={t("Download source")}
            description={t("ModelScope is usually faster in mainland China.")}
            control={
              <select
                className={`${nativeSelectClass} w-44`}
                value={draft.model_download_source}
                onChange={(e) =>
                  patch({
                    model_download_source: e.target
                      .value as MinerUDownloadSource,
                  })
                }
              >
                {DOWNLOAD_SOURCES.map((s) => (
                  <option key={s} className={selectOptionClass} value={s}>
                    {DOWNLOAD_SOURCE_LABELS[s]}
                  </option>
                ))}
              </select>
            }
          />
          {draft.model_download_source === "huggingface" && (
            <SettingRow
              title={t("Download address")}
              description={t(
                "Custom HuggingFace endpoint or mirror (e.g. a regional mirror). Leave blank for the official address.",
              )}
              control={
                <input
                  className={`${inputClass} w-[320px] max-w-[48vw] font-mono text-[12px]`}
                  placeholder={DEFAULT_HF_ENDPOINT}
                  value={draft.model_download_endpoint}
                  onChange={(e) =>
                    patch({ model_download_endpoint: e.target.value })
                  }
                />
              }
            />
          )}
          <SettingRow
            title={t("Download models")}
            description={t(
              "Runs mineru-models-download on the server using the source and address above.",
            )}
            control={
              <div className="flex items-center gap-2">
                <select
                  className={`${nativeSelectClass} w-28`}
                  value={downloadType}
                  onChange={(e) =>
                    setDownloadType(e.target.value as MinerUDownloadType)
                  }
                  disabled={download?.state === "running"}
                >
                  {DOWNLOAD_TYPES.map((v) => (
                    <option key={v} className={selectOptionClass} value={v}>
                      {v}
                    </option>
                  ))}
                </select>
                {download?.state === "running" ? (
                  <button
                    type="button"
                    onClick={cancelDownload}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12px] font-medium text-[var(--foreground)] transition-opacity hover:opacity-80"
                  >
                    {t("Cancel")}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={startDownload}
                    disabled={startingDownload}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-[12px] font-medium text-[var(--background)] transition-opacity hover:opacity-80 disabled:opacity-40"
                  >
                    {startingDownload && (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    )}
                    {t("Download")}
                  </button>
                )}
              </div>
            }
          />
          {download && (
            <div className="px-1 pb-4">
              <div
                className={`mb-2 inline-flex items-center gap-1.5 text-[12px] ${
                  download.state === "done"
                    ? "text-emerald-600 dark:text-emerald-400"
                    : download.state === "running"
                      ? "text-[var(--muted-foreground)]"
                      : "text-red-600 dark:text-red-400"
                }`}
              >
                {download.state === "running" ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : download.state === "done" ? (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                ) : (
                  <XCircle className="h-3.5 w-3.5" />
                )}
                {download.state === "running"
                  ? t("Downloading models...")
                  : download.message || download.state}
              </div>
              {download.lines.length > 0 && (
                <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap rounded-lg border border-[var(--border)]/60 bg-[var(--card)] px-3 py-2 font-mono text-[11px] leading-relaxed text-[var(--muted-foreground)]">
                  {download.lines.join("\n")}
                </pre>
              )}
            </div>
          )}
        </SettingSection>
      )}

      {isCloud && (
        <SettingSection
          title={t("Cloud API")}
          description={t("Get an API token from mineru.net → API management.")}
        >
          <SettingRow
            title={t("API base URL")}
            description={t(
              "Override only if you use a self-hosted MinerU endpoint.",
            )}
            control={
              <input
                className={`${inputClass} w-[320px] max-w-[48vw]`}
                placeholder={DEFAULT_BASE_URL}
                value={draft.api_base_url}
                onChange={(e) => patch({ api_base_url: e.target.value })}
              />
            }
          />
          <SettingRow
            title={t("API token")}
            description={
              tokenSet
                ? t(
                    "A token is saved. Type to replace it; leave blank to keep it.",
                  )
                : t("No token saved yet.")
            }
            control={
              <input
                type="password"
                className={`${inputClass} w-[320px] max-w-[48vw]`}
                placeholder={tokenSet ? TOKEN_MASK : t("Paste API token")}
                value={tokenDraft}
                onChange={(e) => {
                  setTokenDraft(e.target.value);
                  setTokenTouched(true);
                }}
              />
            }
          />
          <SettingRow
            title={t("Test connection")}
            description={t(
              "Verifies the token against the MinerU API (no quota used).",
            )}
            control={renderTestControl(t("Test"))}
          />
        </SettingSection>
      )}

      <SettingSection
        title={t("Parsing options")}
        description={t("Forwarded to MinerU for each document.")}
      >
        <SettingRow
          title={t("Model version")}
          description={t(
            "pipeline is faster; vlm is the vision-language model.",
          )}
          control={
            <select
              className={`${nativeSelectClass} w-40`}
              value={draft.model_version}
              onChange={(e) =>
                patch({ model_version: e.target.value as MinerUModelVersion })
              }
            >
              {MODEL_VERSIONS.map((v) => (
                <option key={v} className={selectOptionClass} value={v}>
                  {v}
                </option>
              ))}
            </select>
          }
        />
        <SettingRow
          title={t("Language")}
          description={t(
            'Document language hint. Use "auto" to let MinerU detect it.',
          )}
          control={
            <input
              className={`${inputClass} w-40`}
              placeholder={LANGUAGE_AUTO}
              value={draft.language}
              onChange={(e) => patch({ language: e.target.value })}
            />
          }
        />
        <SettingRow
          title={t("Extract formulas")}
          control={
            <Toggle
              checked={draft.enable_formula}
              onChange={(v) => patch({ enable_formula: v })}
            />
          }
        />
        <SettingRow
          title={t("Extract tables")}
          control={
            <Toggle
              checked={draft.enable_table}
              onChange={(v) => patch({ enable_table: v })}
            />
          }
        />
        <SettingRow
          title={t("Force OCR")}
          description={t(
            "Treat the PDF as scanned images. Slower; only for non-text PDFs.",
          )}
          control={
            <Toggle
              checked={draft.is_ocr}
              onChange={(v) => patch({ is_ocr: v })}
            />
          }
        />
      </SettingSection>

      <div className="flex items-center justify-between gap-3">
        <p className="text-[12px] text-[var(--muted-foreground)]">
          {message ||
            t(
              "MinerU settings are written to data/user/settings/document_parsing.json.",
            )}
        </p>
        <button
          onClick={save}
          disabled={saving || !dirty}
          className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-[12px] font-medium text-[var(--background)] transition-opacity hover:opacity-80 disabled:opacity-40"
        >
          {saving ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Save className="h-3 w-3" />
          )}
          {t("Save MinerU")}
        </button>
      </div>
    </>
  );
}
