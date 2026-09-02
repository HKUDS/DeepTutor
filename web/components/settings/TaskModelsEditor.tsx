"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, ChevronDown, Download } from "lucide-react";
import { useTranslation } from "react-i18next";

import ProviderIcon from "@/components/common/ProviderIcon";
import { ServiceConfigEditor } from "./ServiceConfigEditor";
import {
  getActiveModel,
  getActiveProfile,
  useSettings,
} from "@/features/settings/store/SettingsStore";
import { selectClass, selectOptionClass } from "./shared";

/**
 * Task models — what DeepTutor runs on when nobody asked it to run.
 *
 * Naming a conversation and writing the three starting points are the two
 * calls the product makes on its own. They were briefly two separate pins, one
 * per call, which asked the user to make a distinction they have no reason to
 * care about: both are short, frequent, and want the same kind of small fast
 * model. So it is one setting.
 *
 * And it is configured exactly like the LLM, because it is the same kind of
 * thing — a provider, then a model under it. The catalog gives it its own
 * service so the whole model editor applies unchanged, and a provider already
 * set up for chat can be brought over rather than typed again.
 *
 * Empty is the default and the common case: with nothing here, both calls
 * resolve the LLM exactly as they did before this page existed.
 */
export function TaskModelsEditor() {
  const { t, i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const { draft, catalogEditable, settingsError, mutateCatalog } =
    useSettings();

  const [importing, setImporting] = useState(false);
  const [importFrom, setImportFrom] = useState("");

  const llmProfiles = draft.services.llm.profiles;
  const configured = draft.services.task.profiles.length > 0;

  const inherited = useMemo(
    () => ({
      binding: getActiveProfile(draft, "llm")?.binding ?? "",
      model: getActiveModel(draft, "llm")?.model ?? "",
    }),
    [draft],
  );

  if (catalogEditable !== true) {
    return (
      <div className="rounded-xl border border-dashed border-[var(--border)] px-5 py-10 text-center text-[13px] text-[var(--muted-foreground)]">
        {settingsError
          ? t(
              "Backend unreachable — model endpoints will appear once the connection is restored. See the banner above for details.",
            )
          : t(
              "Model endpoints are assigned by your administrator. You can still personalize theme and language here.",
            )}
      </div>
    );
  }

  /** Copy a provider over from the LLM service, credentials and all. */
  const importProfile = (profileId: string) => {
    const source = llmProfiles.find((item) => item.id === profileId);
    if (!source) return;
    const stamp = `${Date.now().toString(36)}${Math.random()
      .toString(36)
      .slice(2, 6)}`;
    const profileId2 = `task-profile-${stamp}`;
    const modelId = `task-model-${stamp}`;
    mutateCatalog((next) => {
      const bucket = next.services.task;
      // Only the model in use comes across; the rest are chat's business.
      const sourceModel =
        source.models.find(
          (item) => item.id === next.services.llm.active_model_id,
        ) ?? source.models[0];
      const cloned = JSON.parse(JSON.stringify(source));
      // The server never sends a real secret back — "***" is a display
      // placeholder for "unchanged", which only means something when the
      // profile it came from is the one being saved. A copy under a new id
      // has nothing for the backend to restore it from, so carrying the
      // placeholder over would silently persist and use the literal string
      // "***" as the API key. A connection-linked source is unaffected: its
      // credentials mirror in by connection_id regardless of profile id.
      if (!cloned.connection_id) {
        if (cloned.api_key === "***") cloned.api_key = "";
        if (cloned.api_version === "***") cloned.api_version = "";
        if (cloned.extra_headers && typeof cloned.extra_headers === "object") {
          for (const key of Object.keys(cloned.extra_headers)) {
            if (cloned.extra_headers[key] === "***") {
              cloned.extra_headers[key] = "";
            }
          }
        } else if (cloned.extra_headers === "***") {
          cloned.extra_headers = {};
        }
      }
      bucket.profiles.push({
        ...cloned,
        id: profileId2,
        models: [
          {
            ...(sourceModel
              ? JSON.parse(JSON.stringify(sourceModel))
              : { name: "", model: "" }),
            id: modelId,
          },
        ],
      });
      bucket.active_profile_id = profileId2;
      bucket.active_model_id = modelId;
    });
    setImporting(false);
    setImportFrom("");
  };

  return (
    <div>
      {!configured && (
        <div className="mb-6 rounded-xl border border-[var(--border)] bg-[var(--accent)]/30 px-4 py-3">
          <p className="text-[12.5px] leading-relaxed text-[var(--foreground)]">
            {t(
              "Nothing configured here, so both calls use the language model.",
            )}
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] text-[var(--muted-foreground)]">
            {inherited.model ? (
              <>
                <ProviderIcon provider={inherited.binding} size={12} />
                <span className="font-mono">{inherited.model}</span>
              </>
            ) : (
              <span>{t("No language model is configured yet.")}</span>
            )}
            <Link
              href="/settings#llm"
              className="inline-flex items-center gap-0.5 underline-offset-2 hover:text-[var(--foreground)] hover:underline"
            >
              {t("LLM")}
              <ArrowUpRight className="h-3 w-3" />
            </Link>
          </div>
        </div>
      )}

      {llmProfiles.length > 0 && (
        <div className="mb-5">
          {importing ? (
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative min-w-0 flex-1 sm:max-w-xs">
                <select
                  className={`${selectClass} h-8 py-0 pr-9 text-[12.5px]`}
                  value={importFrom}
                  onChange={(event) => setImportFrom(event.target.value)}
                >
                  <option className={selectOptionClass} value="">
                    {t("Choose a provider to copy...")}
                  </option>
                  {llmProfiles.map((profile) => (
                    <option
                      className={selectOptionClass}
                      key={profile.id}
                      value={profile.id}
                    >
                      {profile.name}
                    </option>
                  ))}
                </select>
                <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted-foreground)]" />
              </div>
              <button
                type="button"
                disabled={!importFrom}
                onClick={() => importProfile(importFrom)}
                className="inline-flex h-8 items-center rounded-lg bg-[var(--foreground)] px-3 text-[12px] font-medium text-[var(--background)] transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                {t("Copy over")}
              </button>
              <button
                type="button"
                onClick={() => {
                  setImporting(false);
                  setImportFrom("");
                }}
                className="h-8 rounded-lg px-2 text-[12px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
              >
                {t("Cancel")}
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setImporting(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-2.5 py-1 text-[12px] text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)]"
            >
              <Download className="h-3 w-3" />
              {t("Bring a provider over from the LLM")}
            </button>
          )}
        </div>
      )}

      <ServiceConfigEditor service="task" />

      <p className="mt-6 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
        {zh
          ? "会话标题和主页起始建议都用这里的模型。两处调用都短小且频繁，指向一个更小更快的模型通常更划算。"
          : "Conversation titles and the home screen's starting points both run on this. Both calls are short and frequent, so a smaller, faster model is usually the better trade."}
      </p>
    </div>
  );
}

export default TaskModelsEditor;
