"use client";

import { stageRegistryAction, type RegistryEdit } from "@/lib/provider-registry";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowRight, Cable, Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import ProviderIcon from "@/components/common/ProviderIcon";
import {
  useSettings,
  type CatalogConnection,
  type ServiceName,
} from "@/features/settings/store/SettingsStore";
import {
  providerRegistry,
  providerUsage,
  providerProbeInput,
  updateProvider,
  REGISTRY_SERVICES,
} from "@/lib/provider-registry";
import {
  EditableRegistryName,
  RegistryField,
  RegistryProbe,
  registryButton,
  registryDanger,
  registryPrimary,
} from "./RegistryControls";
import { CodexOAuthCard } from "./CodexOAuthCard";
import { CodeBuddyAuthCard } from "./CodeBuddyAuthCard";
import { selectClass, stringifyExtraHeaders, subPanelClass } from "./shared";
import {
  WorkspaceDetailEmpty,
  WorkspaceRail,
  WorkspaceSplit,
  workspaceCardClass,
} from "./WorkspaceShell";

export function ProvidersWorkspace() {
  const { t } = useTranslation();
  const {
    catalog,
    draft,
    providers,
    connectionTargets,
    catalogEditable,
    mutateCatalog,
    applying,
  } = useSettings();
  const stageRegistry = async (edit: RegistryEdit) => {
    mutateCatalog((next) => stageRegistryAction(next, edit));
    return true;
  };
  const sources = providerRegistry(draft);
  const editorRef = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<string | null>(null);
  // Below xl the detail pane sits under the rail, so anything that changes what
  // it shows has to bring it into view.
  const revealDetail = () => {
    if (window.matchMedia("(max-width: 1279px)").matches)
      requestAnimationFrame(() =>
        editorRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        }),
      );
  };
  useEffect(() => {
    if (selected) revealDetail();
  }, [selected]);
  const [adding, setAdding] = useState(false);
  const [vendor, setVendor] = useState("");
  const [query, setQuery] = useState("");
  const [auth, setAuth] = useState("");
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("provider");
    if (id && sources.some((p) => p.id === id))
      setSelected((current) => current || id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sources.length]);
  const options = [
    ...new Map(
      REGISTRY_SERVICES.flatMap((service) =>
        (providers[service] ?? [])
          .filter((p) => p.value !== "none" && p.status !== "deprecated")
          .map((option) => [option.value, { ...option, service }] as const),
      ).reverse(),
    ).values(),
  ].sort((a, b) => a.label.localeCompare(b.label));
  const source = sources.find((p) => p.id === selected);
  const option = options.find((p) => p.value === source?.provider);
  const managed = source?.provider === "openai_codex";
  const connection = source?.source;
  const change = (field: string, value: unknown) => {
    if (source)
      mutateCatalog((next) => {
        updateProvider(next, source.ref, field, value);
        if (field === "name" && managed)
          updateProvider(next, source.ref, "user_name", value);
      });
  };
  const create = () => {
    const option = options.find((o) => o.value === vendor);
    if (!option) return;
    if (option.value === "openai_codex") {
      setAuth("openai_codex");
      setAdding(false);
      return;
    }
    const id = `conn-${crypto.randomUUID()}`;
    const entry: CatalogConnection = {
      id,
      name: option.label,
      provider: option.value,
      source_service: option.service,
      api_key: "",
      base_url: "",
      api_version: "",
      api_format:
        (option.default_api_format as CatalogConnection["api_format"]) ||
        "auto",
    };
    mutateCatalog((next) => {
      (next.connections ??= []).push(entry);
    });
    setSelected(`connection:${id}`);
    setAdding(false);
    setAuth("");
  };
  if (!catalogEditable)
    return (
      <p className="text-sm text-[var(--muted-foreground)]">
        {t("Only administrators can manage providers.")}
      </p>
    );
  const savedIds = new Set(providerRegistry(catalog).map((p) => p.id));
  const saved = Boolean(source && savedIds.has(source.id));
  const filtered = sources.filter((p) =>
    `${p.name} ${p.provider}`.toLowerCase().includes(query.toLowerCase()),
  );
  const hints = source
    ? Object.keys(
        connectionTargets.find((target) => target.provider === source.provider)
          ?.services ?? {},
      ).map((service) =>
        ["tts", "stt"].includes(service)
          ? "voice"
          : ["imagegen", "videogen"].includes(service)
            ? "generation"
            : service,
      )
    : [];
  if (
    source &&
    (providers.search ?? []).some(
      (p) => p.value === source.provider && p.status !== "deprecated",
    )
  )
    hints.push("search");
  if (source && ["tts", "stt"].some(service => providers[service as "tts" | "stt"]?.some(p => p.value === source.provider))) hints.push("voice");
  return (
    <div className="space-y-5">
      <WorkspaceSplit
        rail={
          <WorkspaceRail
            // The add action sits with the list it appends to. It used to head a
            // row above the split that only repeated the page description.
            action={
              <button
                type="button"
                onClick={() => {
                  setAdding(true);
                  revealDetail();
                }}
                className={`${registryButton} w-full py-2`}
              >
                <Plus size={14} />
                {t("Add provider")}
              </button>
            }
            search={{
              label: t("Find provider"),
              value: query,
              onChange: setQuery,
              placeholder: t("Search by name"),
            }}
            empty={
              filtered.length
                ? undefined
                : sources.length
                  ? t("No providers match your search.")
                  : t("Add your first provider to start configuring models.")
            }
          >
            {filtered.map((p) => {
              const editing = !adding && !auth && p.id === selected;
              return (
                <button
                  key={p.id}
                  type="button"
                  aria-pressed={editing}
                  onClick={() => {
                    setSelected(p.id);
                    setAdding(false);
                    setAuth("");
                  }}
                  className={workspaceCardClass(editing)}
                >
                  <span className="flex items-center gap-2">
                    <ProviderIcon provider={p.provider} size={16} />
                    <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium">
                      {p.name}
                    </span>
                  </span>
                  <span className="mt-1 block pl-[24px] text-[11px] text-[var(--muted-foreground)]">
                    {t("{{count}} configured models", {
                      count: providerUsage(draft, p),
                    })}
                    {!savedIds.has(p.id) && ` · ${t("Not saved")}`}
                  </span>
                </button>
              );
            })}
          </WorkspaceRail>
        }
        detail={
          <div ref={editorRef} className="min-w-0 scroll-mt-4">
            {/* One configuring surface at a time. The add form used to open as a
                band above the split while a provider's editor kept rendering
                below it, so two things claimed to be "currently configuring". */}
            {adding ? (
              <AddProviderPanel
                options={options}
                vendor={vendor}
                onVendor={setVendor}
                onCreate={create}
                onCancel={() => setAdding(false)}
              />
            ) : auth === "openai_codex" ? (
              <CodexOAuthCard />
            ) : source && connection ? (
              <section
                aria-label={t("Provider settings")}
                // `border-[var(--primary)]/35` compiled to no rule at all, so
                // this pane was drawing preflight's default grey border.
                className="min-w-0 overflow-hidden rounded-2xl border border-[color-mix(in_srgb,var(--primary)_35%,var(--border))]"
              >
                <header className="border-b border-[var(--border)] bg-[color-mix(in_srgb,var(--primary)_4%,var(--background))] px-5 py-4">
                  <p className="mb-1 text-[11px] font-medium text-[var(--primary)]">
                    {t("Configuring provider")}
                  </p>
                  <EditableRegistryName
                    key={source.id}
                    name={connection.name}
                    label={t("Rename provider")}
                    onChange={(name) => change("name", name)}
                  />
                  <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                    {option?.label || source.provider}
                    {!saved && ` · ${t("Not saved")}`}
                  </p>
                </header>
                <div className="space-y-5 p-5">
                  {managed ? (
                    <CodexOAuthCard />
                  ) : (
                    <>
                      {source.provider === "codebuddy" && <CodeBuddyAuthCard />}
                      {/* Address and credential belong on one line: they are the
                          two halves of one connection, and stacking them full
                          width was most of what made this pane feel cramped. */}
                      <div className="grid gap-x-5 gap-y-4 lg:grid-cols-2">
                        <div className="space-y-2">
                          <RegistryField
                            label={t("Provider URL")}
                            value={connection.base_url}
                            onChange={(v) => change("base_url", v)}
                            placeholder={
                              option?.base_url || "https://api.example.com/v1"
                            }
                          />
                          <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
                            {t(
                              "Leave blank to use the provider default. Enter a custom URL for a gateway or private deployment.",
                            )}
                          </p>
                        </div>
                        {option?.requires_api_key !== false && (
                          <div className="space-y-4">
                            {Array.isArray(connection.api_key) ? (
                              connection.api_key.map(
                                (key: string, index: number) => (
                                  <RegistryField
                                    key={index}
                                    label={t("API key {{number}}", {
                                      number: index + 1,
                                    })}
                                    value={key}
                                    type="password"
                                    onChange={(value) => {
                                      const keys = [...connection.api_key];
                                      keys[index] = value;
                                      change("api_key", keys);
                                    }}
                                  />
                                ),
                              )
                            ) : (
                              <RegistryField
                                label={t(source.provider === "volcengine_speech" && connection.app_id ? "Speech access token" : "API key")}
                                value={connection.api_key}
                                type="password"
                                onChange={(value) => change("api_key", value)}
                              />
                            )}
                          </div>
                        )}
                      </div>
                      {source.provider === "volcengine_speech" && (
                        <div className="space-y-2">
                          <RegistryField label={t("Speech App ID (legacy console only)")}
                            value={connection.app_id ?? ""} onChange={v => change("app_id", v)} />
                          <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
                            {t("Use the Speech console API key. For the legacy console, enter App ID and put the access token in the key field. Ark keys are separate.")}
                          </p>
                        </div>
                      )}
                      <details className={`p-3.5 ${subPanelClass}`}>
                        <summary className="cursor-pointer select-none rounded text-xs font-medium marker:text-[var(--muted-foreground)]">
                          {t("Advanced connection settings")}
                        </summary>
                        <div className="mt-4 grid gap-4 sm:grid-cols-2">
                          {source.provider !== "volcengine_speech" && <>
                          <label className="block space-y-1.5 text-xs font-medium">
                            <span className="block">{t("API format")}</span>
                            <select
                              className={selectClass}
                              value={connection.api_format || "auto"}
                              onChange={(e) =>
                                change("api_format", e.target.value)
                              }
                            >
                              <option value="auto">{t("Auto")}</option>
                              <option value="openai_chat">
                                {t("OpenAI Chat Completions")}
                              </option>
                              <option value="openai_responses">
                                {t("OpenAI Responses")}
                              </option>
                              <option value="anthropic">
                                {t("Anthropic Messages")}
                              </option>
                            </select>
                          </label>
                          <RegistryField
                            label={t("API version")}
                            value={connection.api_version || ""}
                            onChange={(v) => change("api_version", v)}
                          />
                          </>}
                          <div className="sm:col-span-2">
                            <RegistryField
                              label={t("Extra headers (JSON)")}
                              value={stringifyExtraHeaders(
                                connection.extra_headers,
                              )}
                              onChange={(v) => change("extra_headers", v)}
                            />
                          </div>
                          {source.service === "search" && (
                            <RegistryField
                              label={t("Proxy")}
                              value={connection.proxy || ""}
                              onChange={(v) => change("proxy", v)}
                            />
                          )}
                        </div>
                      </details>
                      <RegistryProbe
                        input={providerProbeInput(source, option?.base_url)}
                        discovery={connection.discovery}
                        hints={hints}
                        onResult={(result) => change("discovery", result)}
                      />
                    </>
                  )}
                  <div className="flex flex-wrap items-center gap-2 border-t border-[var(--border)] pt-4">

                    <button
                      type="button"
                      disabled={
                        applying || providerUsage(draft, source) > 0 || managed
                      }
                      title={
                        providerUsage(draft, source)
                          ? t(
                              "Change or remove the models using this provider first.",
                            )
                          : undefined
                      }
                      onClick={async () => {
                        await stageRegistry({ kind: "provider", ref: source.ref, delete: true });
                        setSelected(null);
                      }}
                      className={`${registryDanger} ml-auto`}
                    >
                      <Trash2 size={13} />
                      {t("Remove provider")}
                    </button>
                  </div>
                  {source && (
                    <div className="flex flex-wrap gap-2 border-t border-[var(--border)] pt-4">
                      {[
                        ["llm", "Language models"],
                        ["embedding", "Embedding models"],
                        ["search", "Search"],
                        ["voice", "Voice"],
                        ["multimodal", "Multimodal generation"],
                      ].map(([path, label]) => (
                        <Link
                          key={path}
                          href={`/settings/${path}?provider=${encodeURIComponent(source.id)}`}
                          className="inline-flex items-center gap-1 rounded-lg border border-[color-mix(in_srgb,var(--border)_80%,transparent)] px-2.5 py-1.5 text-xs text-[var(--muted-foreground)] transition-[background-color,border-color,color] duration-150 hover:border-[color-mix(in_srgb,var(--foreground)_20%,var(--border))] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
                        >
                          {t(label)}
                          <ArrowRight size={12} />
                        </Link>
                      ))}
                    </div>
                  )}
                </div>
              </section>
            ) : (
              <WorkspaceDetailEmpty
                icon={<Cable size={17} />}
                title={t("Nothing selected")}
                hint={t(
                  "Select a provider to edit its connection. Models are managed on their own pages.",
                )}
              />
            )}
          </div>
        }
      />
    </div>
  );
}

/**
 * The add flow. It lives in the detail pane, opposite the list, because that is
 * the one place on the page that means "what you are configuring right now" —
 * and only one thing can be there at a time.
 */
function AddProviderPanel({
  options,
  vendor,
  onVendor,
  onCreate,
  onCancel,
}: {
  options: { value: string; label: string }[];
  vendor: string;
  onVendor: (value: string) => void;
  onCreate: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  return (
    <section
      aria-label={t("Add provider")}
      className={`min-w-0 p-5 ${subPanelClass}`}
    >
      <h3 className="mb-4 text-base font-semibold">{t("Add provider")}</h3>
      <label className="block space-y-1.5 text-xs font-medium sm:max-w-sm">
        <span className="block">{t("Provider type")}</span>
        <select
          aria-label={t("Provider type")}
          className={selectClass}
          value={vendor}
          onChange={(e) => onVendor(e.target.value)}
        >
          <option value="">{t("Choose a provider")}</option>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      <p className="mt-3 text-xs leading-relaxed text-[var(--muted-foreground)]">
        {t("Connect once. Reuse the provider across your models.")}
      </p>
      <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-[color-mix(in_srgb,var(--border)_70%,transparent)] pt-4">
        <button
          type="button"
          disabled={!vendor}
          onClick={onCreate}
          className={registryPrimary}
        >
          {t("Continue")}
        </button>
        <button type="button" onClick={onCancel} className={registryButton}>
          {t("Cancel")}
        </button>
      </div>
    </section>
  );
}
