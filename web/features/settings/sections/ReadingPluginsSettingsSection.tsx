"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch, apiUrl } from "@/lib/api";

type PluginState = {
  mode: "builtin" | "managed" | "disabled" | "pip";
  version?: string;
  disabled: string[];
};
type Catalog = {
  package: string;
  desired: PluginState;
  active: PluginState;
  restart_required: boolean;
  extensions: string[];
};

export default function ReadingPluginsSettingsSection() {
  const { t } = useTranslation();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const base = apiUrl("/api/reading/plugins");

  async function request(path = "", init?: RequestInit) {
    setBusy(true);
    setError("");
    try {
      const response = await apiFetch(base + path, init);
      const data = await response.json();
      if (!response.ok)
        throw new Error(String(data.detail || response.statusText));
      setCatalog(data);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    let active = true;
    void apiFetch(base)
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok)
          throw new Error(String(data.detail || response.statusText));
        if (active) setCatalog(data);
      })
      .catch((cause) => {
        if (active)
          setError(String(cause instanceof Error ? cause.message : cause));
      });
    return () => {
      active = false;
    };
  }, [base]);

  const labels: Record<string, string> = {
    read_aloud: t("Read aloud"),
    vocabulary: t("Look up word"),
    quiz: t("Quiz me"),
  };

  return (
    <section className="space-y-4 rounded-xl border border-[var(--border)] bg-[var(--card)] p-5">
      <h2 className="text-lg font-semibold">{t("Reading extensions")}</h2>
      <p className="text-sm text-[var(--muted-foreground)]">
        {t("Install the reading bundle once; control each action separately.")}
      </p>
      {error ? (
        <div role="alert">
          {error}{" "}
          <button type="button" onClick={() => void request()} disabled={busy}>
            {t("Retry")}
          </button>
        </div>
      ) : null}
      {!catalog && !error ? (
        <p role="status">{t("Loading reading actions…")}</p>
      ) : null}
      {catalog ? (
        <>
          <p>
            {t("Active reading version")}:{" "}
            {catalog.active.version ||
              (catalog.active.mode === "disabled"
                ? t("Disabled")
                : t("Bundled"))}
          </p>
          <p>
            {t("Selected reading version")}:{" "}
            {catalog.desired.version ||
              (catalog.desired.mode === "disabled"
                ? t("Disabled")
                : t("Bundled"))}
          </p>
          {catalog.restart_required ? (
            <p role="status" className="rounded-lg bg-[var(--muted)] p-3">
              {t(
                "Restart all DeepTutor backend workers to apply these changes.",
              )}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-4">
            {catalog.extensions.map((id) => (
              <label key={id} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  disabled={busy || catalog.desired.mode === "disabled"}
                  checked={
                    catalog.desired.mode !== "disabled" &&
                    !catalog.desired.disabled.includes(id)
                  }
                  onChange={(event) =>
                    void request("/" + id + "/enabled", {
                      method: "PUT",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ enabled: event.target.checked }),
                    })
                  }
                />
                {labels[id] || id}
              </label>
            ))}
          </div>
          <p className="text-sm text-[var(--muted-foreground)]">
            {t(
              "Learner access still follows each account's reading permissions.",
            )}
          </p>
        </>
      ) : null}
      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        {t(
          "I trust this package publisher. Installed Python extensions run on the backend with its permissions.",
        )}
      </label>
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={busy || !confirmed}
          onClick={() => void request("/download", { method: "POST" })}
          className="rounded-lg bg-[var(--primary)] px-3 py-2 text-[var(--primary-foreground)] disabled:opacity-50"
        >
          {t("Download or update reading bundle")}
        </button>
        <label className="text-sm">
          {t("Install reading wheel")}
          <input
            aria-label={t("Install reading wheel")}
            type="file"
            accept=".whl"
            disabled={busy || !confirmed}
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (!file) return;
              if (file.size > 10 * 1024 * 1024) {
                setError(t("Reading wheel must not exceed 10 MB."));
                return;
              }
              const data = new FormData();
              data.append("file", file);
              void request("/install", { method: "POST", body: data });
            }}
          />
        </label>
        {catalog?.desired.mode !== "disabled" ? (
          <button
            type="button"
            disabled={busy || !catalog}
            onClick={() => void request("", { method: "DELETE" })}
          >
            {t("Uninstall reading bundle")}
          </button>
        ) : null}
        <button
          type="button"
          disabled={busy || !catalog}
          onClick={() => void request("/restore", { method: "POST" })}
        >
          {t("Restore bundled reading actions")}
        </button>
      </div>
      {busy ? <p role="status">{t("Updating reading extensions…")}</p> : null}
    </section>
  );
}
