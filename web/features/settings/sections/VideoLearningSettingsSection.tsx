"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, Save, Server, Youtube } from "lucide-react";
import { useTranslation } from "react-i18next";

import { SettingsPageHeader } from "@/components/settings/shared";
import {
  getVideoLearningSettings,
  saveVideoLearningSettings,
  testInvidious,
  type VideoLearningSettings,
} from "@/lib/video-learning-api";

const DEFAULTS: VideoLearningSettings = {
  version: 1,
  default_provider: "youtube",
  youtube: { transcript_provider: "youtube_transcript_api" },
  invidious: { api_base_url: "", public_base_url: "" },
};

export default function VideoLearningSettingsPage() {
  const { t } = useTranslation();
  const [settings, setSettings] = useState(DEFAULTS);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    void getVideoLearningSettings()
      .then(setSettings)
      .catch((error) =>
        setMessage(
          error instanceof Error
            ? error.message
            : t("Settings could not be loaded."),
        ),
      )
      .finally(() => setLoading(false));
  }, [t]);

  const save = async () => {
    setSaving(true);
    setMessage("");
    try {
      setSettings(await saveVideoLearningSettings(settings));
      setMessage(
        t("Saved. New and reopened videos use this provider immediately."),
      );
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : t("Settings could not be saved."),
      );
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setMessage(t("Testing Invidious…"));
    try {
      const result = await testInvidious(settings);
      setMessage(
        result.ok
          ? t("Invidious connected ({{message}}).", result)
          : t("Invidious unavailable: {{message}}", result),
      );
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : t("Connection test failed."),
      );
    }
  };

  return (
    <div className="space-y-6">
      <SettingsPageHeader
        title={t("Video Learning")}
        description={t(
          "Choose native YouTube or a self-hosted Invidious instance. Provider changes do not rebuild learning materials or reset progress.",
        )}
      />
      {loading ? (
        <Loader2 className="h-5 w-5 animate-spin" />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            {(
              [
                [
                  "youtube",
                  Youtube,
                  t(
                    "Official privacy-enhanced IFrame Player. No media is proxied or stored.",
                  ),
                ],
                [
                  "invidious",
                  Server,
                  t(
                    "HTML5 playback through your configured Invidious instance.",
                  ),
                ],
              ] as const
            ).map(([provider, Icon, description]) => (
              <button
                key={provider}
                type="button"
                onClick={() =>
                  setSettings((current) => ({
                    ...current,
                    default_provider: provider,
                  }))
                }
                className={`rounded-xl border p-4 text-left ${settings.default_provider === provider ? "border-[var(--primary)] ring-1 ring-[var(--primary)]" : "border-[var(--border)]"}`}
              >
                <div className="flex items-center gap-2 font-medium">
                  <Icon className="h-5 w-5" />
                  {provider === "youtube"
                    ? t("Native YouTube")
                    : t("Self-hosted Invidious")}
                </div>
                <p className="mt-2 text-sm text-[var(--muted-foreground)]">
                  {description}
                </p>
              </button>
            ))}
          </div>

          <div className="space-y-4 rounded-xl border border-[var(--border)] p-5">
            <h3 className="font-medium">{t("Invidious connection")}</h3>
            <label className="block text-sm">
              <span className="mb-1 block">{t("Backend API origin")}</span>
              <input
                value={settings.invidious.api_base_url}
                onChange={(event) =>
                  setSettings((current) => ({
                    ...current,
                    invidious: {
                      ...current.invidious,
                      api_base_url: event.target.value,
                    },
                  }))
                }
                placeholder={t("Invidious API URL")}
                className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 font-mono"
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block">
                {t("Browser-facing origin (optional)")}
              </span>
              <input
                value={settings.invidious.public_base_url}
                onChange={(event) =>
                  setSettings((current) => ({
                    ...current,
                    invidious: {
                      ...current.invidious,
                      public_base_url: event.target.value,
                    },
                  }))
                }
                placeholder={t("Defaults to the API origin")}
                className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 font-mono"
              />
            </label>
            <button
              type="button"
              onClick={() => void test()}
              className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm"
            >
              {t("Test connection")}
            </button>
          </div>

          <label className="flex items-center justify-between gap-4 rounded-xl border border-[var(--border)] p-4 text-sm">
            <span>
              <strong>{t("YouTube transcript adapter")}</strong>
              <br />
              <span className="text-[var(--muted-foreground)]">
                {t(
                  "Optional captions; playback remains available when the package or captions are unavailable.",
                )}
              </span>
            </span>
            <select
              value={settings.youtube.transcript_provider}
              onChange={(event) =>
                setSettings((current) => ({
                  ...current,
                  youtube: {
                    transcript_provider: event.target.value as
                      | "youtube_transcript_api"
                      | "none",
                  },
                }))
              }
              className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
            >
              <option value="youtube_transcript_api">
                {t("youtube-transcript-api")}
              </option>
              <option value="none">{t("Disabled")}</option>
            </select>
          </label>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => void save()}
              disabled={saving}
              className="inline-flex items-center gap-2 rounded-lg bg-[var(--foreground)] px-4 py-2 text-sm text-[var(--background)] disabled:opacity-50"
            >
              {saving ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}{" "}
              {t("Save")}
            </button>
            {message && (
              <p className="inline-flex items-center gap-1 text-sm text-[var(--muted-foreground)]">
                <CheckCircle2 className="h-4 w-4" />
                {message}
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
