"use client";

import { scrollToSettingsElement } from "@/features/settings/navigation/settings-scroll";
import Tooltip from "@/shared/ui/Tooltip";
import { stageRegistryAction, type RegistryEdit } from "@/lib/provider-registry";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowRight, Cable, Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { formatConfiguredProviderName, formatProviderLabel } from "@/lib/provider-branding";
import ProviderIcon from "@/components/common/ProviderIcon";
import { randomUuid } from "@/lib/random-uuid";
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
  SERVICE_TITLES,
  PROVIDER_SERVICES,
  providerServiceSupport,
} from "@/lib/provider-registry";
import {
  EditableRegistryName,
  RegistryField,
  RegistryProbe,
  registryButton,
  registryDanger,
  registryPrimary,
} from "./RegistryControls";
import { ProviderServices } from "./ProviderServices";
import { AddProviderPanel, ProviderProtocol, type CustomProviderInput } from "./AddProviderPanel";
import { CodexOAuthCard } from "./CodexOAuthCard";
import { CodeBuddyAuthCard } from "./CodeBuddyAuthCard";
import { stringifyExtraHeaders, subPanelClass } from "./shared";
import {
  WorkspaceDetailEmpty,
  WorkspaceRail,
  WorkspaceSplit,
  workspaceCardClass,
} from "./WorkspaceShell";

export function ProvidersWorkspace() {
  const { t, i18n } = useTranslation();
  const uiLanguage = i18n?.resolvedLanguage ?? i18n?.language ?? "en";
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
        scrollToSettingsElement(editorRef.current),
      );
  };
  const [adding, setAdding] = useState(false);
  useEffect(() => {
    if (adding)
      requestAnimationFrame(() => scrollToSettingsElement(editorRef.current));
    else if (selected) revealDetail();
  }, [adding, selected]);
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
      REGISTRY_SERVICES.flatMap((service) => (providers[service] ?? [])
        .filter(p => p.value !== "none" && p.status !== "deprecated")
        .map(option => [option.value, { ...option, service }] as const)).reverse(),
    ).values(),
  ].map(option => ({ ...option, services: PROVIDER_SERVICES.filter(service =>
    providers[service]?.some(p => p.value === option.value && p.status !== "deprecated") ||
    Boolean(connectionTargets.find(target => target.provider === option.value)?.services[service]))
  })).sort((a, b) => a.label.localeCompare(b.label));
  // Protocol-specific aliases still resolve saved accounts, but new accounts
  // use the vendor once and select their protocol in the connection editor.
  const addableOptions = options.filter((p) => p.status !== "legacy");
  const optionLabel = (provider: string) => formatProviderLabel(provider, options.find(p => p.value === provider)?.label ?? provider, uiLanguage);
  const source = sources.find((p) => p.id === selected);
  const option = options.find((p) => p.value === source?.provider);
  const managed = source?.provider === "openai_codex";
  const connection = source?.source;
  const apiFormat = connection?.api_format ||
    (option?.default_api_format as CatalogConnection["api_format"]) || "auto";
  const defaultBaseUrl = option?.base_urls?.[apiFormat] || option?.base_url || "";
  const change = (field: string, value: unknown) => {
    if (source)
      mutateCatalog((next) => {
        updateProvider(next, source.ref, field, value);
        if (field === "name" && managed)
          updateProvider(next, source.ref, "user_name", value);
      });
  };
  const create = (custom?: CustomProviderInput) => {
    const option = addableOptions.find((o) => o.value === vendor);
    if (!option) return;
    if (option.value === "openai_codex") {
      setAuth("openai_codex");
      setAdding(false);
      return;
    }
    const id = `conn-${randomUuid()}`;
    const entry: CatalogConnection = {
      id,
      name: custom?.name || option.label,
      provider: option.value,
      source_service: option.service,
      api_key: "",
      base_url: custom?.base_url || "",
      api_version: "",
      ...(custom ? { service_overrides: { llm: { enabled: true, binding: "custom" } } } : {}),
      api_format:
        custom?.api_format ||
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
    `${formatConfiguredProviderName(p.provider, p.name, uiLanguage)} ${optionLabel(p.provider)} ${p.provider}`.toLowerCase().includes(query.toLowerCase()),
  );
  const hints = source ? PROVIDER_SERVICES.filter(service => providerServiceSupport(source, service, connectionTargets, providers).enabled)
    .map(service => ["tts", "stt"].includes(service) ? "voice" : ["imagegen", "videogen"].includes(service) ? "generation" : service) : [];
  if (adding)
    return (
      <div ref={editorRef} className="min-w-0 scroll-mt-4">
        <AddProviderPanel
          options={addableOptions}
          vendor={vendor}
          onVendor={setVendor}
          onCreate={create}
          onCancel={() => setAdding(false)}
        />
      </div>
    );
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
                    <span className="min-w-0 flex-1 truncate text-[14px] font-medium">
                      {formatConfiguredProviderName(p.provider, p.name, uiLanguage)}
                    </span>
                  </span>
                  <span className="mt-1 block pl-[24px] text-[12px] text-[var(--muted-foreground)]">
                    {t("{{count}} configured models", {
                      count: providerUsage(draft, p),
                    })}
                    {!savedIds.has(p.id) && ` · ${t("Not saved")}`}
                  </span>
                  <span className="mt-2 flex flex-wrap gap-1 pl-6">
                    {PROVIDER_SERVICES.filter(service => providerServiceSupport(p, service, connectionTargets, providers).enabled).map(service => <span key={service} className="rounded bg-[var(--muted)] px-1.5 py-0.5 text-[11px] text-[var(--muted-foreground)]">{t(SERVICE_TITLES[service])}</span>)}
                  </span>
                </button>
              );
            })}
          </WorkspaceRail>
        }
        detail={
          <div ref={editorRef} className="min-w-0 scroll-mt-4">
            {auth === "openai_codex" ? (
              <CodexOAuthCard />
            ) : source && connection ? (
              <section
                aria-label={t("Provider settings")}
                // `border-[var(--primary)]/35` compiled to no rule at all, so
                // this pane was drawing preflight's default grey border.
                className="min-w-0 overflow-hidden rounded-2xl border border-[color-mix(in_srgb,var(--primary)_35%,var(--border))]"
              >
                <header className="border-b border-[var(--border)] bg-[color-mix(in_srgb,var(--primary)_4%,var(--background))] px-4 py-5 sm:px-6">
                  <p className="mb-1 text-[12px] font-medium text-[var(--primary)]">
                    {t("Configuring provider")}
                  </p>
                  <EditableRegistryName
                    key={source.id}
                    name={connection.name}
                    label={t("Rename provider")}
                    onChange={(name) => change("name", name)}
                  />
                  <p className="mt-1 text-[13px] text-[var(--muted-foreground)]">
                    {optionLabel(source.provider)}
                    {!saved && ` · ${t("Not saved")}`}
                  </p>
                </header>
                <div className="space-y-6 p-4 sm:p-6">
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
                              defaultBaseUrl || "https://api.example.com/v1"
                            }
                          />
                          <p className="text-[13px] leading-relaxed text-[var(--muted-foreground)]">
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
                          <p className="text-[13px] leading-relaxed text-[var(--muted-foreground)]">
                            {t("Use the Speech console API key. For the legacy console, enter App ID and put the access token in the key field. Ark keys are separate.")}
                          </p>
                        </div>
                      )}
                      {providerServiceSupport(source, "llm", connectionTargets, providers).enabled && option?.api_formats?.length !== 0 && (
                        <ProviderProtocol value={apiFormat} formats={option?.api_formats} onChange={value => change("api_format", value)} />
                      )}
                      <ProviderServices key={source.id} source={source} onChange={value => change("service_overrides", value)} />
                      <details className={`p-3.5 ${subPanelClass}`}>
                        <summary className="cursor-pointer select-none rounded text-[13px] font-medium marker:text-[var(--muted-foreground)]">
                          {t("Advanced connection settings")}
                        </summary>
                        <div className="mt-4 grid gap-4 sm:grid-cols-2">
                          {source.provider !== "volcengine_speech" && <>
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
                        input={{ ...providerProbeInput(source, defaultBaseUrl), api_format: apiFormat }}
                        discovery={connection.discovery}
                        hints={hints}
                        showCapabilities={false}
                        onResult={(result) => change("discovery", result)}
                      />
                    </>
                  )}
                  <div className="flex flex-wrap items-center gap-2 border-t border-[var(--border)] pt-4">

                      <Tooltip label={
                        providerUsage(draft, source)
                          ? t("Change or remove the models using this provider first.")
                          : t("Remove provider")
                      } side="top">
                      <button
                        type="button"
                        disabled={
                          applying || providerUsage(draft, source) > 0 || managed
                        }
                        aria-label={t("Remove provider")}
                        onClick={async () => {
                          await stageRegistry({ kind: "provider", ref: source.ref, delete: true });
                          setSelected(null);
                        }}
                        className={`${registryDanger} ml-auto`}
                      >
                        <Trash2 size={13} />
                        {t("Remove provider")}
                      </button>
                    </Tooltip>
                  </div>
                  {source && (
                    <div className="flex flex-wrap gap-2 border-t border-[var(--border)] pt-4">
                      {[
                        ["llm", "Language models"],
                        ["embedding", "Embedding models"],
                        ["search", "Search"],
                        ["voice", "Voice"],
                        ["multimodal", "Multimodal generation"],
                      ].filter(([path]) => PROVIDER_SERVICES.some(service =>
                        (path === "voice" ? service === "tts" || service === "stt" : path === "multimodal" ? service === "imagegen" || service === "videogen" : service === path) &&
                        providerServiceSupport(source, service, connectionTargets, providers).enabled
                      )).map(([path, label]) => (
                        <Link
                          key={path}
                          href={`/settings/${path}?provider=${encodeURIComponent(source.id)}`}
                          className="inline-flex items-center gap-1 rounded-lg border border-[color-mix(in_srgb,var(--border)_80%,transparent)] px-2.5 py-1.5 text-[13px] text-[var(--muted-foreground)] transition-[background-color,border-color,color] duration-150 hover:border-[color-mix(in_srgb,var(--foreground)_20%,var(--border))] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
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
