"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  Check,
  ChevronDown,
  Eye,
  EyeOff,
  Loader2,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import ProviderIcon from "@/components/common/ProviderIcon";
import { apiFetch, apiUrl } from "@/lib/api";
import {
  CONNECTABLE_SERVICES,
  type CatalogConnection,
  type ConnectionTarget,
  type ServiceName,
  useSettings,
} from "@/features/settings/store/SettingsStore";
import { inputClass, selectClass, selectOptionClass } from "./shared";

/**
 * Connections — the credential layer.
 *
 * Every model service in DeepTutor stores its own profile with its own key,
 * which is right when the keys differ and absurd when they do not: one
 * OpenRouter key had to be pasted into five pages. A connection is that key,
 * typed once, with one linked profile created per service that can use it.
 *
 * It is additive on purpose. Linking mirrors the credential down into ordinary
 * profiles (the backend does it on save), so a linked profile resolves exactly
 * like a hand-typed one and every service page keeps working unchanged. Users
 * who want a different key per service simply never make a connection.
 */

const SERVICE_LABEL: Record<ServiceName, { en: string; zh: string }> = {
  llm: { en: "LLM", zh: "LLM" },
  task: { en: "Task model", zh: "任务模型" },
  embedding: { en: "Embedding", zh: "嵌入模型" },
  search: { en: "Search", zh: "搜索" },
  tts: { en: "Text-to-Speech", zh: "语音合成" },
  stt: { en: "Speech-to-Text", zh: "语音识别" },
  imagegen: { en: "Image", zh: "文生图" },
  videogen: { en: "Video", zh: "文生视频" },
};

const SERVICE_HREF: Record<ServiceName, string> = {
  llm: "/settings#llm",
  task: "/settings#task-models",
  embedding: "/settings#embedding",
  search: "/settings#search",
  tts: "/settings#tts",
  stt: "/settings#stt",
  imagegen: "/settings#imagegen",
  videogen: "/settings#videogen",
};

type ServiceLink = { service: ServiceName; profileId: string };

/** Where a connection's service chip points: that service's page, opened on
 *  the profile this connection feeds. */
function serviceHref(link: ServiceLink): string {
  return `${SERVICE_HREF[link.service]}?profile=${encodeURIComponent(link.profileId)}`;
}

function maskedKey(value: string): string {
  const key = (value || "").trim();
  if (!key) return "";
  // The stored value comes back from the server already masked as "***";
  // anything else is a key the user typed in this session.
  if (key === "***") return "••••••••";
  if (key.length <= 10) return `${key.slice(0, 2)}••••`;
  return `${key.slice(0, 5)}••••${key.slice(-4)}`;
}

export function ConnectionsEditor() {
  const { t, i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const {
    draft,
    catalogEditable,
    settingsError,
    connectionTargets,
    connectionTarget,
    addConnection,
    updateConnectionField,
    removeConnection,
    linkConnectionToServices,
    setToast,
  } = useSettings();

  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const connections = draft.connections ?? [];

  // Which profiles each connection currently feeds. The profile id rides
  // along so a service link can land on that exact profile — a service with
  // several providers configured would otherwise open on whichever one
  // happens to be selected, which is not where the click was aimed.
  const linkage = useMemo(() => {
    const map = new Map<string, ServiceLink[]>();
    for (const service of CONNECTABLE_SERVICES) {
      for (const profile of draft.services[service].profiles) {
        if (!profile.connection_id) continue;
        const list = map.get(profile.connection_id) ?? [];
        if (!list.some((item) => item.service === service)) {
          list.push({ service, profileId: profile.id });
        }
        map.set(profile.connection_id, list);
      }
    }
    return map;
  }, [draft]);

  // Services configured the old way — a profile with its own credentials and
  // no connection behind it. This is the motivation for the page, so it is
  // shown as a fact rather than left implicit.
  const standaloneServices = useMemo(
    () =>
      CONNECTABLE_SERVICES.filter((service) =>
        draft.services[service].profiles.some(
          (profile) => !profile.connection_id,
        ),
      ),
    [draft],
  );

  if (catalogEditable !== true) {
    // Same shape the service editors use: an ordinary user reaches this page
    // from the Models grid, and an empty panel would read as a broken page
    // rather than a permission boundary.
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

  const label = (service: ServiceName) =>
    zh ? SERVICE_LABEL[service].zh : SERVICE_LABEL[service].en;

  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-3">
        <p className="text-[12px] text-[var(--muted-foreground)]">
          {connections.length > 0
            ? t("{{count}} connection", { count: connections.length })
            : t("No connections yet.")}
        </p>
        {!adding && (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]"
          >
            <Plus className="h-3.5 w-3.5" />
            {t("Add connection")}
          </button>
        )}
      </div>

      {adding && (
        <AddConnectionPanel
          targets={connectionTargets}
          onCancel={() => setAdding(false)}
          onCreate={(input, services) => {
            const connection = addConnection(input);
            const { created, activated } = linkConnectionToServices(
              connection,
              services,
            );
            setAdding(false);
            // The row already lists which services it feeds, so the toast
            // says the one thing that cannot be seen there: which existing
            // selections were left alone.
            const kept = created.filter(
              (service) => !activated.includes(service),
            );
            setToast(
              created.length === 0
                ? t("Connection added.")
                : kept.length === 0
                  ? t("Configured {{count}} services and made them active.", {
                      count: created.length,
                    })
                  : t(
                      "Configured {{count}} services — {{kept}} kept your existing choice.",
                      {
                        count: created.length,
                        kept: kept.map(label).join(zh ? "、" : ", "),
                      },
                    ),
            );
          }}
        />
      )}

      {connections.length === 0 && !adding && (
        <div className="rounded-xl border border-dashed border-[var(--border)] px-4 py-5">
          <p className="text-[13px] text-[var(--foreground)]">
            {t(
              "A connection holds one vendor credential and supplies every model service that can use it.",
            )}
          </p>
          {standaloneServices.length > 0 && (
            <p className="mt-2 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
              {t(
                "Credentials are currently entered separately for {{services}}.",
                {
                  services: standaloneServices
                    .map(label)
                    .join(zh ? "、" : ", "),
                },
              )}
            </p>
          )}
        </div>
      )}

      {connections.length > 0 && (
        <div className="border-t border-[var(--border)]/60">
          {connections.map((connection, index) => (
            <ConnectionRow
              key={connection.id}
              connection={connection}
              target={connectionTarget(connection.provider)}
              linked={linkage.get(connection.id) ?? []}
              first={index === 0}
              editing={editingId === connection.id}
              confirmingDelete={confirmDeleteId === connection.id}
              label={label}
              onEdit={() =>
                setEditingId(editingId === connection.id ? null : connection.id)
              }
              onField={(field, value) =>
                updateConnectionField(connection.id, field, value)
              }
              onLink={(service, model) => {
                const { activated } = linkConnectionToServices(connection, [
                  { service, model },
                ]);
                setToast(
                  activated.includes(service)
                    ? t("{{service}} now uses {{name}}.", {
                        service: label(service),
                        name: connection.name,
                      })
                    : t(
                        "Added a {{service}} profile — switch to it on its own page.",
                        { service: label(service) },
                      ),
                );
              }}
              onAskDelete={() =>
                setConfirmDeleteId(
                  confirmDeleteId === connection.id ? null : connection.id,
                )
              }
              onDelete={() => {
                removeConnection(connection.id);
                setConfirmDeleteId(null);
                setEditingId(null);
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ConnectionRow({
  connection,
  target,
  linked,
  first,
  editing,
  confirmingDelete,
  label,
  onEdit,
  onField,
  onLink,
  onAskDelete,
  onDelete,
}: {
  connection: CatalogConnection;
  target: ConnectionTarget | null;
  linked: ServiceLink[];
  first: boolean;
  editing: boolean;
  confirmingDelete: boolean;
  label: (service: ServiceName) => string;
  onEdit: () => void;
  onField: (field: keyof CatalogConnection, value: string) => void;
  onLink: (service: ServiceName, model: string) => void;
  onAskDelete: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const [showKey, setShowKey] = useState(false);

  const available = CONNECTABLE_SERVICES.filter(
    (service) =>
      target?.services[service] &&
      !linked.some((item) => item.service === service),
  );

  return (
    <div className={first ? "" : "border-t border-[var(--border)]/50"}>
      <div className="flex items-start gap-3 py-3.5">
        <ProviderIcon
          provider={connection.provider}
          size={18}
          className="mt-0.5 shrink-0"
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="text-[13px] font-medium text-[var(--foreground)]">
              {connection.name}
            </span>
            <span className="font-mono text-[11px] text-[var(--muted-foreground)]">
              {maskedKey(connection.api_key) || t("No key")}
            </span>
          </div>
          {/* Each service it supplies is a way in, not just a label: the link
              opens that service on this connection's own profile. */}
          <div className="mt-1 flex flex-wrap items-center text-[11px] leading-relaxed text-[var(--muted-foreground)]">
            {linked.length > 0
              ? linked.map((link, index) => (
                  <span key={link.service} className="inline-flex items-center">
                    {index > 0 && <span className="px-1.5 opacity-50">·</span>}
                    <Link
                      href={serviceHref(link)}
                      className="inline-flex items-center gap-0.5 underline-offset-2 transition-colors hover:text-[var(--foreground)] hover:underline"
                    >
                      {label(link.service)}
                      <ArrowUpRight className="h-2.5 w-2.5" />
                    </Link>
                  </span>
                ))
              : t("Not supplying any service yet")}
          </div>
          {available.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {available.map((service) => (
                <button
                  key={service}
                  type="button"
                  onClick={() =>
                    onLink(
                      service,
                      target?.services[service]?.default_model ?? "",
                    )
                  }
                  className="inline-flex h-6 items-center gap-1 rounded-md border border-[var(--border)] px-2 text-[11px] text-[var(--muted-foreground)] transition-colors hover:border-[var(--ring)] hover:text-[var(--foreground)]"
                >
                  <Plus className="h-3 w-3" />
                  {label(service)}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={onEdit}
            className="rounded-md px-2 py-1 text-[11px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          >
            {editing ? t("Done") : t("Edit")}
          </button>
          <button
            type="button"
            onClick={onAskDelete}
            aria-label={t("Delete")}
            className="rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-red-500"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {confirmingDelete && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--border)] bg-[var(--muted)]/25 px-4 py-3">
          <p className="text-[11px] leading-relaxed text-[var(--muted-foreground)]">
            {linked.length > 0
              ? t(
                  "Profiles it supplies keep their current credentials but stop following this connection.",
                )
              : t("Nothing is using this connection.")}
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onAskDelete}
              className="h-7 rounded-md px-2.5 text-[11px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            >
              {t("Cancel")}
            </button>
            <button
              type="button"
              onClick={onDelete}
              className="h-7 rounded-md bg-red-500/10 px-2.5 text-[11px] font-medium text-red-600 transition-colors hover:bg-red-500/15 dark:text-red-400"
            >
              {t("Delete")}
            </button>
          </div>
        </div>
      )}

      {editing && (
        <div className="grid gap-3 border-t border-[var(--border)] bg-[var(--muted)]/15 px-4 py-4 sm:grid-cols-2">
          <div>
            <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
              {t("Name")}
            </div>
            <input
              className={inputClass}
              value={connection.name}
              onChange={(event) => onField("name", event.target.value)}
            />
          </div>
          <div>
            <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
              {t("Base URL")}
            </div>
            <input
              className={inputClass}
              value={connection.base_url}
              placeholder={target?.default_base_url || "https://…/v1"}
              onChange={(event) => onField("base_url", event.target.value)}
            />
          </div>
          <div className="sm:col-span-2">
            <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
              {t("API Key")}
            </div>
            <div className="relative">
              <input
                type={showKey ? "text" : "password"}
                autoComplete="new-password"
                spellCheck={false}
                className={`${inputClass} pr-10 font-mono`}
                value={connection.api_key}
                onChange={(event) => onField("api_key", event.target.value)}
                placeholder="sk-..."
              />
              <button
                type="button"
                onClick={() => setShowKey((value) => !value)}
                aria-label={showKey ? t("Hide API key") : t("Show API key")}
                className="absolute right-1 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
              >
                {showKey ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </button>
            </div>
            <p className="mt-1.5 text-[11px] text-[var(--muted-foreground)]">
              {t(
                "Saving pushes these values into every profile this connection supplies.",
              )}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function AddConnectionPanel({
  targets,
  onCancel,
  onCreate,
}: {
  targets: ConnectionTarget[];
  onCancel: () => void;
  onCreate: (
    input: {
      provider: string;
      name: string;
      api_key: string;
      base_url: string;
    },
    services: { service: ServiceName; model: string }[],
  ) => void;
}) {
  const { t, i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const [provider, setProvider] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [selected, setSelected] = useState<Set<ServiceName>>(new Set());
  const [llmModel, setLlmModel] = useState("");
  const [fetchedModels, setFetchedModels] = useState<string[]>([]);
  const [fetching, setFetching] = useState(false);
  const [fetchError, setFetchError] = useState("");

  const target = targets.find((item) => item.provider === provider) ?? null;
  const supported = CONNECTABLE_SERVICES.filter(
    (service) => target?.services[service],
  );

  const label = (service: ServiceName) =>
    zh ? SERVICE_LABEL[service].zh : SERVICE_LABEL[service].en;

  const choose = (next: string) => {
    setProvider(next);
    setFetchedModels([]);
    setFetchError("");
    setLlmModel("");
    const spec = targets.find((item) => item.provider === next);
    // Everything the vendor can serve starts checked: the whole point is that
    // one key configures the lot, and unchecking is cheaper than hunting.
    setSelected(
      new Set(
        CONNECTABLE_SERVICES.filter((service) => spec?.services[service]),
      ),
    );
  };

  const fetchModels = async () => {
    if (!target) return;
    setFetching(true);
    setFetchError("");
    try {
      const response = await apiFetch(apiUrl("/api/settings/fetch-models"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          binding: target.services.llm?.provider || provider,
          base_url: baseUrl.trim() || target.services.llm?.base_url || "",
          api_key: apiKey || null,
        }),
      });
      const payload = (await response.json()) as {
        models?: { id: string }[];
        detail?: string;
      };
      if (!response.ok) throw new Error(payload.detail || "request failed");
      const ids = (payload.models ?? []).map((item) => item.id);
      setFetchedModels(ids);
      if (ids.length === 0)
        setFetchError(t("The provider returned no models."));
    } catch (error) {
      setFetchError(
        error instanceof Error ? error.message : t("Could not reach provider."),
      );
    } finally {
      setFetching(false);
    }
  };

  const toggle = (service: ServiceName) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(service)) next.delete(service);
      else next.add(service);
      return next;
    });
  };

  const canSubmit = Boolean(provider) && selected.size > 0;

  return (
    <div className="mb-4 rounded-xl border border-[var(--border)] bg-[var(--muted)]/15 px-4 py-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
            {t("Provider")}
          </div>
          <div className="relative">
            {provider && (
              <ProviderIcon
                provider={provider}
                size={15}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2"
              />
            )}
            <select
              className={`${selectClass} ${provider ? "pl-9" : ""}`}
              value={provider}
              onChange={(event) => choose(event.target.value)}
            >
              <option className={selectOptionClass} value="">
                {t("Select provider...")}
              </option>
              {targets.map((item) => (
                <option
                  className={selectOptionClass}
                  key={item.provider}
                  value={item.provider}
                >
                  {item.label}
                </option>
              ))}
            </select>
            <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted-foreground)]" />
          </div>
        </div>
        <div>
          <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
            {t("Base URL")}
          </div>
          <input
            className={inputClass}
            value={baseUrl}
            placeholder={target?.default_base_url || "https://…/v1"}
            onChange={(event) => setBaseUrl(event.target.value)}
          />
          <p className="mt-1.5 text-[11px] text-[var(--muted-foreground)]">
            {t("Leave blank to use each service's official endpoint.")}
          </p>
        </div>
        <div className="sm:col-span-2">
          <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
            {t("API Key")}
          </div>
          <div className="relative">
            <input
              type={showKey ? "text" : "password"}
              autoComplete="new-password"
              spellCheck={false}
              className={`${inputClass} pr-10 font-mono`}
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="sk-..."
            />
            <button
              type="button"
              onClick={() => setShowKey((value) => !value)}
              aria-label={showKey ? t("Hide API key") : t("Show API key")}
              className="absolute right-1 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              {showKey ? (
                <EyeOff className="h-4 w-4" />
              ) : (
                <Eye className="h-4 w-4" />
              )}
            </button>
          </div>
        </div>
      </div>

      {target && (
        <div className="mt-4">
          <div className="mb-2 text-[12px] text-[var(--muted-foreground)]">
            {t("Configure these services")}
          </div>
          <div className="overflow-hidden rounded-lg border border-[var(--border)]">
            {supported.map((service, index) => {
              const spec = target.services[service]!;
              const checked = selected.has(service);
              return (
                <div
                  key={service}
                  className={`flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2.5 ${
                    index === 0 ? "" : "border-t border-[var(--border)]"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => toggle(service)}
                    aria-pressed={checked}
                    className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors ${
                      checked
                        ? "border-[var(--foreground)] bg-[var(--foreground)] text-[var(--background)]"
                        : "border-[var(--border)]"
                    }`}
                  >
                    {checked && <Check className="h-3 w-3" />}
                  </button>
                  <span className="w-24 shrink-0 text-[12.5px] text-[var(--foreground)]">
                    {label(service)}
                  </span>
                  {service === "llm" ? (
                    <div className="flex min-w-0 flex-1 items-center gap-2">
                      {fetchedModels.length > 0 ? (
                        <div className="relative min-w-0 flex-1">
                          <select
                            className={`${selectClass} h-8 py-0 text-[12px]`}
                            value={llmModel}
                            onChange={(event) =>
                              setLlmModel(event.target.value)
                            }
                          >
                            <option className={selectOptionClass} value="">
                              {t("Select a model...")}
                            </option>
                            {fetchedModels.map((id) => (
                              <option
                                className={selectOptionClass}
                                key={id}
                                value={id}
                              >
                                {id}
                              </option>
                            ))}
                          </select>
                          <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted-foreground)]" />
                        </div>
                      ) : (
                        <input
                          className={`${inputClass} h-8 min-w-0 flex-1 py-0 font-mono text-[12px]`}
                          value={llmModel}
                          placeholder={t("Model ID")}
                          onChange={(event) => setLlmModel(event.target.value)}
                        />
                      )}
                      <button
                        type="button"
                        onClick={fetchModels}
                        disabled={fetching || !apiKey.trim()}
                        className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 text-[11px] text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:opacity-40"
                      >
                        {fetching && (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        )}
                        {t("List models")}
                      </button>
                    </div>
                  ) : (
                    <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-[var(--muted-foreground)]">
                      {spec.default_model || t("Set on its own page")}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
          {fetchError && (
            <p className="mt-1.5 text-[11px] text-amber-600 dark:text-amber-400">
              {fetchError}
            </p>
          )}
          {selected.has("llm") && !llmModel.trim() && (
            <p className="mt-1.5 text-[11px] text-[var(--muted-foreground)]">
              {t(
                "No chat model picked yet — the profile is still created, pick one on the LLM page.",
              )}
            </p>
          )}
        </div>
      )}

      <div className="mt-4 flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-[12px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
        >
          <X className="h-3.5 w-3.5" />
          {t("Cancel")}
        </button>
        <button
          type="button"
          disabled={!canSubmit}
          onClick={() =>
            onCreate(
              {
                provider,
                name: target?.label ?? provider,
                api_key: apiKey,
                base_url: baseUrl,
              },
              [...selected].map((service) => ({
                service,
                model:
                  service === "llm"
                    ? llmModel.trim()
                    : (target?.services[service]?.default_model ?? ""),
              })),
            )
          }
          className="inline-flex h-8 items-center rounded-lg bg-[var(--foreground)] px-3.5 text-[12px] font-medium text-[var(--background)] transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {t("Add connection")}
        </button>
      </div>
    </div>
  );
}

export default ConnectionsEditor;
