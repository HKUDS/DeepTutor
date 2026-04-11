"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  Laptop,
  Link2,
  Loader2,
  ShieldCheck,
  Unplug,
  X,
} from "lucide-react";
import { parseCodexCredential } from "@/lib/codexCredential";

// ─── Storage key ──────────────────────────────────────────────────────────────
const STORAGE_KEY = "deeptutor:codex:credential";

function loadStoredApiKey(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(STORAGE_KEY) ?? "";
}

function saveApiKey(key: string) {
  if (typeof window === "undefined") return;
  if (key) {
    localStorage.setItem(STORAGE_KEY, key);
  } else {
    localStorage.removeItem(STORAGE_KEY);
  }
}

// ─── Model presets ────────────────────────────────────────────────────────────
const MODEL_PRESETS = [
  "gpt-5.3-codex",
  "gpt-5-codex",
  "gpt-5-codex-mini",
  "gpt-5.4",
  "gpt-5.4-pro",
];
const MODEL_STORAGE_KEY = "deeptutor:codex:model";

function loadStoredModel(): string {
  if (typeof window === "undefined") return MODEL_PRESETS[0];
  return localStorage.getItem(MODEL_STORAGE_KEY) ?? MODEL_PRESETS[0];
}

// ─── Mini toast ───────────────────────────────────────────────────────────────
function useToast() {
  const [msg, setMsg] = useState("");
  const [isError, setIsError] = useState(false);

  const show = useCallback((text: string, error = false) => {
    setMsg(text);
    setIsError(error);
  }, []);

  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(() => setMsg(""), 3500);
    return () => clearTimeout(t);
  }, [msg]);

  return { msg, isError, show };
}

type CodexHealthState =
  | { status: "idle"; message: string }
  | { status: "testing"; message: string }
  | { status: "passed"; message: string; model?: string | null; responseTimeMs?: number | null }
  | { status: "failed"; message: string; error?: string | null };

// ─── Main component ───────────────────────────────────────────────────────────
export function CodexSection() {
  const { msg: toastMsg, isError: toastIsError, show: showToast } = useToast();

  const [open, setOpen] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(MODEL_PRESETS[0]);
  const [modelDraft, setModelDraft] = useState(MODEL_PRESETS[0]);
  const [callbackUrl, setCallbackUrl] = useState("");
  const [startedLogin, setStartedLogin] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [isCompleting, setIsCompleting] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const [health, setHealth] = useState<CodexHealthState>({
    status: "idle",
    message: "Credential present locally. Test to verify the backend chat path.",
  });

  // Hydrate from localStorage on mount
  useEffect(() => {
    const stored = loadStoredApiKey();
    if (stored) setApiKey(stored);
    const storedModel = loadStoredModel();
    setModel(storedModel);
    setModelDraft(storedModel);
  }, []);

  const isConnected = !!parseCodexCredential(apiKey);
  const hasModelChange = modelDraft.trim() && modelDraft.trim() !== model;

  const runConnectionTest = useCallback(async () => {
    if (!isConnected) {
      setHealth({ status: "failed", message: "Connect a Codex session first." });
      showToast("Connect a Codex session first.", true);
      return false;
    }

    setHealth({ status: "testing", message: "Testing backend and model..." });
    try {
      const res = await fetch("/api/codex/test", { method: "POST" });
      const payload = (await res.json()) as {
        ok?: boolean;
        message?: string;
        error?: string | null;
        model?: string | null;
        responseTimeMs?: number | null;
      };

      if (!res.ok || !payload.ok) {
        const message = payload.message ?? payload.error ?? "Codex test failed";
        setHealth({ status: "failed", message, error: payload.error });
        showToast(message, true);
        return false;
      }

      const message = payload.responseTimeMs
        ? `${payload.message} (${payload.responseTimeMs.toFixed(0)} ms)`
        : (payload.message ?? "Codex test passed");
      setHealth({
        status: "passed",
        message,
        model: payload.model,
        responseTimeMs: payload.responseTimeMs,
      });
      showToast(message);
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : "Codex test failed";
      setHealth({ status: "failed", message });
      showToast(message, true);
      return false;
    }
  }, [isConnected, showToast]);

  // ── Backend bridge ──────────────────────────────────────────────────────────

  const applyToBackend = async (key: string, mdl: string) => {
    setIsApplying(true);
    try {
      const res = await fetch("/api/codex/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ apiKey: key, model: mdl }),
      });
      const data = (await res.json()) as { ok?: boolean; error?: string };
      if (!res.ok) {
        showToast(data.error ?? "Could not apply to backend", true);
        return false;
      }
      return true;
    } catch {
      showToast("Could not apply Codex config to backend", true);
      return false;
    } finally {
      setIsApplying(false);
    }
  };

  const removeFromBackend = async () => {
    try {
      await fetch("/api/codex/apply", { method: "DELETE" });
    } catch {
      // best-effort
    }
  };

  const handleStartLogin = async () => {
    setIsStarting(true);
    try {
      const res = await fetch("/api/codex/auth/start", { method: "POST" });
      const data = (await res.json()) as { authUrl?: string; error?: string };
      if (!res.ok) throw new Error(data.error ?? "Could not start auth");
      window.open(data.authUrl!, "_blank", "noopener,noreferrer");
      setStartedLogin(true);
      showToast("Opened OpenAI login — paste callback URL below when done.");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Could not start auth", true);
    } finally {
      setIsStarting(false);
    }
  };

  const handleCompleteLogin = async () => {
    if (!callbackUrl.trim()) {
      showToast("Paste the full callback URL first", true);
      return;
    }
    if (!startedLogin) {
      showToast("Start the login flow first", true);
      return;
    }
    setIsCompleting(true);
    try {
      const res = await fetch("/api/codex/auth/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ callbackUrl: callbackUrl.trim() }),
      });
      const data = (await res.json()) as { apiKey?: string; error?: string };
      if (!res.ok) throw new Error(data.error ?? "Could not complete auth");
      const newKey = data.apiKey!;
      setApiKey(newKey);
      saveApiKey(newKey);
      setCallbackUrl("");
      setStartedLogin(false);
      const applied = await applyToBackend(newKey, model);
      setHealth({
        status: "idle",
        message: applied
          ? "Credential applied. Run a test to verify replies."
          : "Credential saved, but backend apply failed.",
      });
      if (applied) {
        await runConnectionTest();
      } else {
        showToast("Connected but failed to apply", true);
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Could not complete auth", true);
    } finally {
      setIsCompleting(false);
    }
  };

  const handleImportLocal = async () => {
    setIsImporting(true);
    try {
      const res = await fetch("/api/codex/auth/import-local", { method: "POST" });
      const data = (await res.json()) as { apiKey?: string; error?: string };
      if (!res.ok) throw new Error(data.error ?? "Could not import local session");
      const newKey = data.apiKey!;
      setApiKey(newKey);
      saveApiKey(newKey);
      const applied = await applyToBackend(newKey, model);
      setHealth({
        status: "idle",
        message: applied
          ? "Credential applied. Run a test to verify replies."
          : "Credential imported, but backend apply failed.",
      });
      if (applied) {
        await runConnectionTest();
      } else {
        showToast("Imported but failed to apply", true);
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Could not import", true);
    } finally {
      setIsImporting(false);
    }
  };

  const handleDisconnect = async () => {
    setApiKey("");
    saveApiKey("");
    setHealth({ status: "idle", message: "Credential removed." });
    await removeFromBackend();
    showToast("Codex disconnected");
  };

  const handleSaveModel = async () => {
    const m = modelDraft.trim();
    if (!m) { showToast("Model ID cannot be empty", true); return; }
    setModel(m);
    localStorage.setItem(MODEL_STORAGE_KEY, m);
    if (isConnected) {
      const applied = await applyToBackend(apiKey, m);
      setHealth({
        status: "idle",
        message: applied
          ? `Model saved as ${m}. Run a test to verify replies.`
          : "Model saved locally, but backend apply failed.",
      });
      if (applied) {
        await runConnectionTest();
      } else {
        showToast(`Saved locally but backend apply failed`, true);
      }
    } else {
      setHealth({ status: "idle", message: `Model saved as ${m}. Connect a session to test it.` });
      showToast(`Codex model set to ${m}`);
    }
  };

  const badgeClass =
    health.status === "passed"
      ? "border-emerald-500/30 bg-emerald-500/8 text-emerald-600 dark:text-emerald-400"
      : health.status === "failed"
        ? "border-red-500/30 bg-red-500/8 text-red-500"
        : isConnected
          ? "border-amber-500/30 bg-amber-500/8 text-amber-500"
          : "border-[var(--border)]/60 text-[var(--muted-foreground)]/50";

  const badgeLabel =
    health.status === "testing"
      ? "Testing"
      : health.status === "passed"
        ? "Ready"
        : health.status === "failed"
          ? "Issue detected"
          : isConnected
            ? "Credential saved"
            : "Not connected";

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="mb-6 rounded-xl border border-[var(--border)]">
      {/* ── Header row ── */}
      <div className="flex items-center justify-between px-5 py-3.5">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
          aria-expanded={open}
        >
          <ShieldCheck className="h-3.5 w-3.5 text-[var(--muted-foreground)]" />
          <span className="text-[13px] font-medium text-[var(--foreground)]">
            OpenAI Codex Session
          </span>
          {/* Status badge */}
          <span
            className={`ml-1 inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${badgeClass}`}
          >
            {health.status === "testing" ? (
              <><Loader2 className="h-3 w-3 animate-spin" /> {badgeLabel}</>
            ) : health.status === "passed" ? (
              <><CheckCircle2 className="h-3 w-3" /> {badgeLabel}</>
            ) : (
              badgeLabel
            )}
          </span>
        </button>

        <div className="ml-3 flex items-center gap-3">
          {toastMsg && (
            <span
              className={`text-[11px] ${toastIsError ? "text-red-500" : "text-[var(--primary)]"}`}
            >
              {toastMsg}
            </span>
          )}
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
            aria-label={open ? "Collapse Codex section" : "Expand Codex section"}
          >
            <ChevronDown
              className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`}
            />
          </button>
        </div>
      </div>

      {/* ── Expanded body ── */}
      {open && (
        <div className="border-t border-[var(--border)] px-5 py-5 space-y-5">

          {/* Description */}
          <p className="text-[12px] leading-relaxed text-[var(--muted-foreground)]">
            Connect your ChatGPT account using the same OAuth flow as the{" "}
            <code className="rounded bg-[var(--muted)] px-1 py-0.5 text-[11px]">openai/codex</code>{" "}
            CLI — no API key needed. Or use a local session if you&apos;ve already run{" "}
            <code className="rounded bg-[var(--muted)] px-1 py-0.5 text-[11px]">codex auth</code>.
          </p>

          {/* ── Step box ── */}
          <div className="rounded-lg border border-[var(--border)]/60 bg-[var(--muted)]/30 px-4 py-3">
            <p className="text-[12px] leading-relaxed text-[var(--muted-foreground)]">
              <strong className="text-[var(--foreground)]">OAuth flow:</strong>{" "}
              Click <em>Start OpenAI Login</em> → complete login in the new tab
              → your browser redirects to{" "}
              <code className="text-[11px]">localhost:1455/auth/callback?…</code> (page won&apos;t
              load) → copy the full URL → paste it below → click{" "}
              <em>Complete Login</em>.
            </p>
          </div>

          {/* ── Auth buttons row ── */}
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={handleStartLogin}
              disabled={isStarting}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-[12px] font-medium text-white transition-opacity hover:opacity-85 disabled:opacity-40"
            >
              {isStarting ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Link2 className="h-3.5 w-3.5" />
              )}
              Start OpenAI Login
            </button>

            <button
              onClick={handleImportLocal}
              disabled={isImporting}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/60 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:opacity-40"
            >
              {isImporting ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Laptop className="h-3.5 w-3.5" />
              )}
              Use Local Session
            </button>

            <button
              onClick={() => void runConnectionTest()}
              disabled={!isConnected || health.status === "testing" || isApplying}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/60 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:opacity-40"
            >
              {health.status === "testing" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <CheckCircle2 className="h-3.5 w-3.5" />
              )}
              Test Connection
            </button>

            {isConnected && (
              <button
                onClick={handleDisconnect}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/60 px-3 py-1.5 text-[12px] font-medium text-red-500/70 transition-colors hover:border-red-500/30 hover:text-red-500 disabled:opacity-40"
              >
                <Unplug className="h-3.5 w-3.5" />
                Disconnect
              </button>
            )}
          </div>

          <div className="rounded-lg border border-[var(--border)]/60 bg-[var(--muted)]/20 px-4 py-3 text-[12px] text-[var(--muted-foreground)]">
            <div className="font-medium text-[var(--foreground)]">Status</div>
            <p className="mt-1 leading-relaxed">{health.message}</p>
            {health.status === "passed" && health.model ? (
              <p className="mt-1 text-[11px]">
                Active backend model: <code className="rounded bg-[var(--muted)] px-1 py-0.5">{health.model}</code>
              </p>
            ) : null}
            {isApplying ? (
              <p className="mt-1 text-[11px]">Applying credential to backend...</p>
            ) : null}
          </div>

          {/* ── Callback URL input ── */}
          <div>
            <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
              Callback URL
              {startedLogin && (
                <span className="ml-2 text-emerald-500 text-[11px]">← paste here</span>
              )}
            </div>
            <div className="flex gap-2">
              <textarea
                value={callbackUrl}
                onChange={(e) => setCallbackUrl(e.target.value)}
                rows={2}
                placeholder="http://localhost:1455/auth/callback?code=...&state=..."
                className="flex-1 resize-y rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--ring)] placeholder:text-[var(--muted-foreground)]/30"
              />
              {callbackUrl.trim() && (
                <button
                  onClick={() => setCallbackUrl("")}
                  className="self-start p-1 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            <button
              onClick={handleCompleteLogin}
              disabled={!startedLogin || isCompleting || !callbackUrl.trim()}
              className="mt-2 inline-flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-[12px] font-medium text-[var(--background)] transition-opacity hover:opacity-80 disabled:opacity-30"
            >
              {isCompleting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Complete Login
            </button>
          </div>

          {/* ── Model picker ── */}
          <div className="rounded-xl border border-[var(--border)] p-4">
            <div className="mb-3 text-[12px] font-medium text-[var(--foreground)]">
              Codex Model
              <span className="ml-2 font-normal text-[var(--muted-foreground)]/60">
                active: <code className="text-[11px]">{model}</code>
              </span>
            </div>
            <div className="mb-3 flex flex-wrap gap-1.5">
              {MODEL_PRESETS.map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setModelDraft(m)}
                  className={`rounded-full border px-2.5 py-1 text-[11px] transition-colors ${
                    modelDraft === m
                      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                      : "border-[var(--border)]/60 text-[var(--muted-foreground)] hover:border-[var(--border)]"
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <input
                value={modelDraft}
                onChange={(e) => setModelDraft(e.target.value)}
                placeholder="Custom model ID"
                className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--ring)] placeholder:text-[var(--muted-foreground)]/30"
              />
              <button
                onClick={handleSaveModel}
                disabled={!hasModelChange}
                className="shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3 py-2 text-[12px] font-medium text-[var(--background)] transition-opacity hover:opacity-80 disabled:opacity-30"
              >
                Save
              </button>
            </div>
          </div>

          {/* ── Raw credential display (dev helper) ── */}
          {isConnected && (
            <details className="text-[11px] text-[var(--muted-foreground)]/40">
              <summary className="cursor-pointer hover:text-[var(--muted-foreground)]">
                Show raw credential (dev)
              </summary>
              <pre className="mt-2 max-h-[100px] overflow-auto rounded-lg bg-[#0f0f0f] p-3 font-mono text-[10px] leading-5 text-[#666]">
                {apiKey}
              </pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
