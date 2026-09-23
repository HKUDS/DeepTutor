"use client";

import { stageRegistryAction, type RegistryEdit } from "@/lib/provider-registry";
import { useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import { Check, Plus, SlidersHorizontal, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import ProviderIcon from "@/components/common/ProviderIcon";
import {
  useSettings,
  type CatalogModel,
  type CatalogProfile,
  type ServiceName,
} from "@/features/settings/store/SettingsStore";
import {
  flattenModels,
  modelProvider,
  providerAdapter,
  providerIdentity,
  providerProbeInput,
  providerRegistry,
  SERVICE_TITLES,
  type ProviderSource,
} from "@/lib/provider-registry";
import { voiceModelOptions } from "@/lib/voice-settings";
import { VoiceModelFields } from "./VoiceModelFields";
import { VoicePreviewPanel } from "./VoicePreviewPanel";
import { ModelTestPanel } from "./ModelTestPanel";
import EmbeddingModelUsage from "./EmbeddingModelUsage";
import {
  EditableRegistryName,
  RegistryField,
  RegistryModelIdField,
  RegistryProbe,
  registryButton,
  registryDanger,
  registryPrimary,
} from "./RegistryControls";
import { inputClass, selectClass, subPanelClass } from "./shared";
import {
  WorkspaceDetailEmpty,
  WorkspaceRail,
  WorkspaceSplit,
  workspaceCardClass,
} from "./WorkspaceShell";

import { randomUuid } from "@/lib/random-uuid";
type ModelPage = "llm" | "embedding" | "search" | "voice" | "multimodal";
const PAGE_SERVICES: Record<ModelPage, ServiceName[]> = {
  llm: ["llm", "task"],
  embedding: ["embedding"],
  search: ["search"],
  voice: ["tts", "stt"],
  multimodal: ["imagegen", "videogen"],
};
export function ModelsWorkspace({
  page,
  initialService,
}: {
  page: ModelPage;
  initialService?: ServiceName;
}) {
  const { t } = useTranslation();
  const {
    draft,
    providers,
    connectionTargets,
    catalogEditable,
    mutateCatalog,
  } = useSettings();
  const services = PAGE_SERVICES[page];
  const rows = flattenModels(draft, services);
  const editorRef = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [newService, setNewService] = useState<ServiceName>(
    initialService && services.includes(initialService) ? initialService : services[0],
  );
  const [newProvider, setNewProvider] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const profileId = params.get("profile");
    if (profileId)
      setSelected(
        (current) =>
          current || rows.find((r) => r.profile.id === profileId)?.key || null,
      );
    // Resolve old profile links after the settings payload arrives.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows.length]);
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
  const selectModel = (key: string) => {
    setSelected(key);
    setAdding(false);
    revealDetail();
  };
  const selectedRow = rows.find((r) => r.key === selected);
  // Providers and models can be created together in the same draft.
  const sources = providerRegistry(draft);
  /** Whether a built-in adapter is on record for this vendor and service. */
  const declared = (source: ProviderSource, service: ServiceName) => {
    const adapterService = service === "task" ? "llm" : service;
    const exact = providers[adapterService]?.some(
      (option) =>
        option.value === source.provider &&
        option.value !== "none" &&
        option.status !== "deprecated",
    );
    const mapped = connectionTargets.find(
      (target) => target.provider === source.provider,
    )?.services[adapterService];
    return Boolean(
      exact ||
      mapped ||
      (service !== "search" && source.service === service) ||
      (service === "task" && source.service === "llm") ||
      (service !== "search" && source.provider === "custom"),
    );
  };
  // Not being on record is not a veto for any service. Whether a vendor serves
  // a given model type is not knowable from its registry entry — plenty of
  // OpenAI-compatible endpoints serve embeddings or speech without appearing in
  // that service's table — so every provider is selectable, the ones with no
  // adapter on record are only grouped apart, and a wrong pick is reported by
  // the model test rather than pre-empted here. Managed credentials stay out:
  // that is not a capability judgement, their models arrive with them.
  const selectable = sources.filter(
    (source) => !("managed_by" in source.source && source.source.managed_by),
  );
  const start = () => {
    setAdding(true);
    revealDetail();
    const preferred = new URLSearchParams(window.location.search).get(
      "provider",
    );
    if (preferred && selectable.some((p) => p.id === preferred))
      setNewProvider(preferred);
  };
  const create = () => {
    const source = selectable.find((p) => p.id === newProvider);
    if (!source) return;
    const profileId = `${newService}-profile-${randomUuid()}`;
    const modelId = `${newService}-model-${randomUuid()}`;
    const ref = providerAdapter(
      source,
      newService,
      connectionTargets,
      providers,
    );
    const target = providers[newService]?.find((p) => p.value === ref.binding);
    const model = target?.default_model || "";
    mutateCatalog((next) => {
      const profile: CatalogProfile = {
        id: profileId,
        name: source.name,
        binding: ref.binding,
        provider: newService === "search" ? ref.binding : undefined,
        provider_ref: ref,
        api_key: "",
        base_url: "",
        api_version: "",
        models:
          newService === "search"
            ? []
            : [
                {
                  id: modelId,
                  model,
                  name: model,
                  provider_ref: ref,
                  ...(newService === "tts"
                    ? {
                        voice: target?.default_voice || "",
                        response_format: voiceModelOptions(target?.voice_options, target?.default_model || "")?.formats[0] || "mp3",
                      }
                    : {}),
                },
              ],
      };
      if (newService === "search") profile.display_name = source.name;
      next.services[newService].profiles.push(profile);
    });
    setSelected(
      newService === "search"
        ? `${newService}:${profileId}`
        : `${newService}:${profileId}:${modelId}`,
    );
    setAdding(false);
    setQuery("");
    setFilter("all");
  };
  if (!catalogEditable)
    return (
      <p className="text-sm text-[var(--muted-foreground)]">
        {t("Only administrators can manage models.")}
      </p>
    );
  const filtered = rows.filter(
    (row) =>
      (filter === "all" || row.service === filter) &&
      `${row.model?.name || row.profile.display_name || row.profile.name} ${row.model?.model || ""} ${modelProvider(draft, row.service, row.profile, row.model)?.name || ""}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const addLabel = t(
    page === "search" ? "Add search configuration" : "Add model",
  );
  return (
    <div className="space-y-5">
      {!sources.length && (
        <div className="rounded-xl border border-[var(--border)] p-5 text-sm">
          <p>{t("Add a provider before adding models.")}</p>
          <Link
            href="/settings/connections"
            className="mt-3 inline-block underline underline-offset-4"
          >
            {t("Go to providers")}
          </Link>
        </div>
      )}
      <WorkspaceSplit
        rail={
          <WorkspaceRail
            // The add action sits with the list it appends to. It used to head a
            // description row above the split that only repeated the page
            // description, costing a band of height and telling nobody anything.
            action={
              <button
                type="button"
                onClick={start}
                className={`${registryButton} w-full py-2`}
              >
                <Plus size={14} />
                {addLabel}
              </button>
            }
            search={{
              label: t("Find model"),
              value: query,
              onChange: setQuery,
              placeholder: t("Search by model or provider"),
            }}
            filter={
              page === "voice" || page === "multimodal" ? (
                <select
                  aria-label={t("Filter model type")}
                  className={`${selectClass} py-1.5 text-[13px]`}
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                >
                  <option value="all">{t("All model types")}</option>
                  {PAGE_SERVICES[page].map((s) => (
                    <option key={s} value={s}>
                      {t(SERVICE_TITLES[s])}
                    </option>
                  ))}
                </select>
              ) : undefined
            }
            empty={
              filtered.length
                ? undefined
                : rows.length
                  ? t("No models match your search.")
                  : t("No models configured yet.")
            }
          >
            {filtered.map((row) => {
              const provider = modelProvider(
                draft,
                row.service,
                row.profile,
                row.model,
              );
              const bucket = draft.services[row.service];
              const isDefault =
                bucket.active_profile_id === row.profile.id &&
                (!row.model || bucket.active_model_id === row.model.id) &&
                (row.service !== "task" ||
                  (bucket.mode !== "inherit" && bucket.mode !== "reference"));
              const label =
                row.model?.name ||
                row.model?.model ||
                row.profile.display_name ||
                (row.model ? t("New model") : row.profile.name);
              const providerName = provider?.name || t("Provider unavailable");
              const editing = !adding && row.key === selected;
              return (
                <button
                  key={row.key}
                  type="button"
                  aria-pressed={editing}
                  // The card leads with the model, because that is what you are
                  // looking for, but the accessible name keeps the provider
                  // first so the row still reads as "provider, model".
                  aria-label={`${providerName} ${label}${row.model?.model ? ` ${row.model.model}` : ""}`}
                  onClick={() => selectModel(row.key)}
                  className={workspaceCardClass(editing)}
                >
                  <span className="flex items-center gap-2">
                    <ProviderIcon
                      provider={provider?.provider || "custom"}
                      size={15}
                    />
                    <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium">
                      {label}
                    </span>
                    {isDefault && (
                      <span
                        title={t("Default model")}
                        className="shrink-0 text-[var(--primary)]"
                      >
                        <Check size={13} />
                      </span>
                    )}
                  </span>
                  <span className="mt-1 flex items-center gap-1.5 pl-[23px] text-[11px] text-[var(--muted-foreground)]">
                    <span className="max-w-[45%] truncate">{providerName}</span>
                    {row.model?.model && (
                      <>
                        <span aria-hidden>·</span>
                        <span className="truncate">{row.model.model}</span>
                      </>
                    )}
                  </span>
                  {(page === "voice" || page === "multimodal" || row.service === "task") && (
                    <span className="mt-1.5 ml-[23px] inline-flex rounded-md bg-[color-mix(in_srgb,var(--muted)_70%,transparent)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]">
                      {t(SERVICE_TITLES[row.service])}
                    </span>
                  )}
                </button>
              );
            })}
          </WorkspaceRail>
        }
        detail={
          <div ref={editorRef} className="min-w-0 scroll-mt-4">
            {/* One configuring surface at a time. The add form used to open as a
                band above the split while an existing model's editor kept
                rendering below it, so two things claimed to be "currently
                configuring". Cancel returns to whatever was open before. */}
            {adding ? (
              <AddModelPanel
                page={page}
                service={newService}
                onService={(value) => {
                  setNewService(value);
                  setNewProvider("");
                }}
                provider={newProvider}
                onProvider={setNewProvider}
                sources={selectable}
                declared={(source) => declared(source, newService)}
                onCreate={create}
                onCancel={() => setAdding(false)}
              />
            ) : selectedRow ? (
              <ModelEditor
                key={selectedRow.key}
                row={selectedRow}
                sources={selectable}
                declared={(source) => declared(source, selectedRow.service)}
                onRemoved={() => setSelected(null)}
              />
            ) : (
              <WorkspaceDetailEmpty
                icon={<SlidersHorizontal size={17} />}
                title={t("Nothing selected")}
                hint={t(
                  "Select a model to view its settings and connection test.",
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
 * Provider options for one service. Vendors with no adapter on record are
 * offered rather than hidden — they are only separated out, so the list still
 * says which ones are a known quantity without deciding for you.
 */
function ProviderOptions({
  sources,
  declared,
}: {
  sources: ProviderSource[];
  declared: (source: ProviderSource) => boolean;
}) {
  const { t } = useTranslation();
  const option = (p: ProviderSource) => (
    <option key={p.id} value={p.id}>
      {p.name}
    </option>
  );
  const unverified = sources.filter((source) => !declared(source));
  if (!unverified.length) return <>{sources.map(option)}</>;
  const known = sources.filter(declared);
  return (
    <>
      {known.length > 0 && (
        <optgroup label={t("Supported for this model type")}>
          {known.map(option)}
        </optgroup>
      )}
      <optgroup label={t("Not on record — verify with the model test")}>
        {unverified.map(option)}
      </optgroup>
    </>
  );
}

/**
 * The add flow. It lives in the detail pane, opposite the list, because that is
 * the one place on the page that means "what you are configuring right now" —
 * and only one thing can be there at a time.
 */
function AddModelPanel({
  page,
  service,
  onService,
  provider,
  onProvider,
  sources,
  declared,
  onCreate,
  onCancel,
}: {
  page: ModelPage;
  service: ServiceName;
  onService: (value: ServiceName) => void;
  provider: string;
  onProvider: (value: string) => void;
  sources: ProviderSource[];
  declared: (source: ProviderSource) => boolean;
  onCreate: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const title = t(
    page === "search" ? "Add search configuration" : "Add model",
  );
  return (
    <section aria-label={title} className={`min-w-0 p-5 ${subPanelClass}`}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-base font-semibold">{title}</h3>
        <Link
          href="/settings/connections"
          className="shrink-0 text-xs text-[var(--muted-foreground)] underline underline-offset-4 transition-colors hover:text-[var(--foreground)]"
        >
          {t("Manage providers")}
        </Link>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {(page === "voice" || page === "multimodal") && (
          <label className="space-y-1.5 text-xs font-medium">
            <span className="block">{t("Model type")}</span>
            <select
              className={selectClass}
              value={service}
              onChange={(e) => onService(e.target.value as ServiceName)}
            >
              {PAGE_SERVICES[page].map((s) => (
                <option key={s} value={s}>
                  {t(SERVICE_TITLES[s])}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="space-y-1.5 text-xs font-medium">
          <span className="block">{t("Configured provider")}</span>
          <select
            aria-label={t("Configured provider")}
            className={selectClass}
            value={provider}
            onChange={(e) => onProvider(e.target.value)}
          >
            <option value="">{t("Choose a provider")}</option>
            <ProviderOptions sources={sources} declared={declared} />
          </select>
        </label>
      </div>
      <p className="mt-3 text-xs leading-relaxed text-[var(--muted-foreground)]">
        {t(
          service === "search"
            ? "Every provider is selectable. Search has no generic adapter, so a provider without a search API of its own is rejected by the search test — that is where a wrong pick shows up."
            : "Every provider is selectable. One with no adapter on record for this model type is called as an OpenAI-compatible endpoint derived from its provider URL — add the model, then run the model test to see whether it answers.",
        )}
      </p>
      <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-[color-mix(in_srgb,var(--border)_70%,transparent)] pt-4">
        <button
          type="button"
          disabled={!provider}
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

type ModelRow = ReturnType<typeof flattenModels>[number];
function ModelEditor({
  row,
  sources,
  declared,
  onRemoved,
}: {
  row: ModelRow;
  sources: ProviderSource[];
  declared: (source: ProviderSource) => boolean;
  onRemoved: () => void;
}) {
  const { t } = useTranslation();
  const {
    draft,
    providers,
    connectionTargets,
    mutateCatalog,
    applying,
  } = useSettings();
  const stageRegistry = async (edit: RegistryEdit) => {
    mutateCatalog((next) => stageRegistryAction(next, edit));
    return true;
  };
  const { service, profile, model } = row;
  const provider = modelProvider(draft, service, profile, model);
  const speechProvider = model?.provider_ref?.binding || profile.provider_ref?.binding || provider?.provider || profile.binding || "custom";
  const speechOptions = providers[service]?.find(p => p.value === speechProvider)?.voice_options;
  const speechPreset = voiceModelOptions(speechOptions, model?.model ?? "");
  const [listed, setListed] = useState<{
    provider: string;
    models: { id: string }[];
  } | null>(null);
  const name = model
    ? model.name || model.model || t("New model")
    : profile.display_name || profile.name;
  const managed = Boolean(
    model?.managed_by || profile.read_only || profile.managed_by,
  );
  const saved = draft.services[service].profiles.find(
    (p) => p.id === profile.id,
  );
  const savedModel =
    service === "search"
      ? Boolean(saved && !saved.provider_only)
      : saved?.models.some((m) => m.id === model?.id);
  const active =
    savedModel &&
    draft.services[service].active_profile_id === profile.id &&
    (!model || draft.services[service].active_model_id === model.id);
  const task = draft.services.task;
  const assignedToTask = Boolean(model && [task, ...Object.values(task.overrides ?? {})].some((choice) =>
    (service === "llm" && choice.mode === "reference" && choice.selection?.profile_id === profile.id && choice.selection?.model_id === model.id) ||
    (service === "task" && choice.mode === "profiles" && choice.active_profile_id === profile.id && choice.active_model_id === model.id)
  ));
  const update = (field: keyof CatalogModel, value: unknown) =>
    mutateCatalog((next) => {
      const target = next.services[service].profiles
        .find((p) => p.id === profile.id)
        ?.models.find((m) => m.id === model?.id);
      if (!target) return;
      if (field === "model" && (!target.name || target.name === target.model))
        target.name = String(value);
      if (field === "model" && (service === "tts" || service === "stt")) {
        const before = voiceModelOptions(speechOptions, target.model);
        const after = voiceModelOptions(speechOptions, String(value));
        if (after && after !== speechOptions?.fallback) {
          if (before?.voices.some(v => v.id === target.voice) && !after.voices.some(v => v.id === target.voice))
            target.voice = after.voices[0]?.id ?? "";
          if (before?.formats.includes(target.response_format ?? "") && !after.formats.includes(target.response_format ?? ""))
            target.response_format = after.formats[0] ?? "";
          if (before?.languages.some(l => l.id === target.language) && !after.languages.some(l => l.id === target.language))
            target.language = "";
          if (!after.instructions) delete target.instructions;
          if (!after.speed) delete target.speed;
        }
      }
      Object.assign(target, { [field]: value });
      if (field === "name" && managed) target.user_name = String(value);
      if (field === "context_window") {
        target.context_window_source = value ? "manual" : "default";
        delete target.context_window_tokens;
        delete target.context_window_detected_at;
      }
    });
  const updateSearch = (field: string, value: unknown) =>
    mutateCatalog((next) => {
      const target = next.services.search.profiles.find(
        (p) => p.id === profile.id,
      );
      if (target) Object.assign(target, { [field]: value });
    });
  const chooseProvider = (id: string) => {
    const source = sources.find((p) => p.id === id);
    if (!source) return;
    const ref = providerAdapter(source, service, connectionTargets, providers);
    if (model) update("provider_ref", ref);
    else updateSearch("provider_ref", ref);
    setListed(null);
  };
  const list =
    listed && listed.provider === provider?.id
      ? listed.models
      : provider?.source.discovery?.models || [];
  const remove = async () => {
    await stageRegistry({ kind: "model", service, profile_id: profile.id, model_id: model?.id, delete: true });
    onRemoved();
  };

  return (
    <section
      aria-label={t("Model settings")}
      // `border-[var(--primary)]/35` compiled to no rule at all, so this pane
      // was drawing preflight's default grey border and read as unstyled.
      className="min-w-0 overflow-clip rounded-2xl border border-[color-mix(in_srgb,var(--primary)_35%,var(--border))]"
    >
      {/* Opaque on purpose: it stays put over the scrolling body. */}
      <header className="sticky top-14 z-10 border-b border-[var(--border)] bg-[color-mix(in_srgb,var(--primary)_4%,var(--background))] px-5 py-4 lg:top-0">
        <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px]">
          <span className="font-medium text-[var(--primary)]">
            {t("Currently configuring")}
          </span>
          <span className="text-[var(--muted-foreground)]">
            {t(SERVICE_TITLES[service])}
          </span>
          {!savedModel && (
            <span className="text-[var(--muted-foreground)]">
              · {t("Not saved")}
            </span>
          )}
        </div>
        <EditableRegistryName
          name={name}
          label={t("Rename model")}
          onChange={(value) =>
            model ? update("name", value) : updateSearch("display_name", value)
          }
        />
        <div className="mt-2 flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
          <ProviderIcon provider={provider?.provider || "custom"} size={16} />
          <span className="break-all">
            {provider?.name || t("Provider unavailable")}
          </span>
        </div>
        {model?.model && (
          <p className="mt-2 break-all font-mono text-[11px] text-[var(--muted-foreground)]">
            {model.model}
          </p>
        )}
      </header>
      <div className="space-y-5 p-5">
        {service === "embedding" && model && <EmbeddingModelUsage key={JSON.stringify([profile.id, model.id])} profileId={profile.id} modelId={model.id} />}
        <div className="grid gap-x-5 gap-y-4 lg:grid-cols-2">
          <div className="space-y-2">
            <label className="block space-y-1.5 text-xs font-medium">
              <span className="block">{t("Configured provider")}</span>
              <select
                aria-label={t("Configured provider")}
                className={selectClass}
                disabled={managed}
                value={provider?.id || ""}
                onChange={(e) => chooseProvider(e.target.value)}
              >
                <option value="" disabled>
                  {t("Choose a provider")}
                </option>
                {provider && !sources.some((p) => p.id === provider.id) && (
                  <option value={provider.id}>{provider.name}</option>
                )}
                <ProviderOptions sources={sources} declared={declared} />
              </select>
            </label>
            {/* Why the test below matters more here: nothing vouches for this
                pairing yet, so say what request it will actually make. */}
            {provider && !declared(provider) && (
              <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
                {t(
                  service === "search"
                    ? "No search adapter is on record for this provider, and search has no OpenAI-compatible fallback. Run the test below — it will say so rather than search with the wrong engine."
                    : "No adapter for this model type is on record for this provider. DeepTutor calls it as an OpenAI-compatible endpoint derived from the provider URL; run the model test below to confirm it answers.",
                )}
              </p>
            )}
            <Link
              href={`/settings/connections${provider ? `?provider=${encodeURIComponent(provider.id)}` : ""}`}
              className="inline-block text-xs text-[var(--muted-foreground)] underline underline-offset-4 transition-colors hover:text-[var(--foreground)]"
            >
              {t("Manage provider connection")}
            </Link>
          </div>
          {model && (
            <div className="space-y-2">
              <RegistryModelIdField
                label={t(speechProvider === "volcengine_speech" && service === "tts" ? "Model / resource ID" : "Model ID")}
                value={model.model}
                options={[...new Set([...(speechOptions?.models.map(m => m.id) ?? []), ...list.map((item) => item.id)])]}
                disabled={managed}
                onChange={(value) => update("model", value)}
                placeholder={t("Choose a listed model or enter a model ID")}
              />
              <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
                {t(
                  "The display name is used in chat. Double-click the name above or use the edit button to rename it.",
                )}
              </p>
            </div>
          )}
          {service === "search" && (
            <div className="space-y-2">
              <RegistryField
                label={t("Maximum results")}
                type="number"
                value={String(profile.max_results ?? 5)}
                onChange={(value) =>
                  updateSearch(
                    "max_results",
                    Math.max(1, Math.min(10, Number(value) || 5)),
                  )
                }
              />
              <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
                {t(
                  "Search APIs use an engine configuration rather than a model ID or context window.",
                )}
              </p>
            </div>
          )}
        </div>
        {model && provider && !managed && service !== "search" && (
          <RegistryProbe
            input={providerProbeInput(
              provider,
              providers[provider.service || "llm"]?.find(
                (p) => p.value === provider.provider,
              )?.base_url ||
                providers[service]?.find((p) => p.value === provider.provider)
                  ?.base_url,
            )}
            discovery={provider.source.discovery}
            listing
            onResult={(result) =>
              setListed({ provider: provider.id, models: result.models })
            }
          />
        )}
        {model && (service === "tts" || service === "stt") ? (
          <VoiceModelFields service={service} provider={speechProvider} model={model}
            options={speechOptions} preset={speechPreset} update={update} disabled={managed} />
        ) : model && <ModelParameters service={service} model={model} update={update} managed={managed} />}
        {service === "tts" && model ? <VoicePreviewPanel profileId={profile.id} modelId={model.id} maxChars={Math.min(500, speechPreset?.max_input_chars ?? 500)} /> : <ModelTestPanel service={service} profile={profile} model={model} />}
        <div className="flex flex-wrap items-center gap-2 border-t border-[var(--border)] pt-4">

          <button
            type="button"
            disabled={applying || !savedModel || Boolean(active)}
            onClick={() =>
              void stageRegistry({
                kind: "default",
                service,
                profile_id: profile.id,
                model_id: model?.id,
              })
            }
            className={registryButton}
          >
            {active && <Check size={13} />}{" "}
            {t(active ? "Default model" : "Set as default")}
          </button>
          <button
            type="button"
            aria-label={t("Remove model")}
            disabled={applying || managed || assignedToTask}
            title={assignedToTask ? t("Choose another background task model before removing this model.") : undefined}
            onClick={() => void remove()}
            className={`${registryDanger} ml-auto`}
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>
    </section>
  );
}

function ModelParameters({
  service,
  model,
  update,
  managed,
}: {
  service: ServiceName;
  model: CatalogModel;
  update: (field: keyof CatalogModel, value: unknown) => void;
  managed: boolean;
}) {
  const { t } = useTranslation();
  const contextId = useId();
  const language = service === "llm" || service === "task";
  const fields: [keyof CatalogModel, string][] =
    service === "embedding"
      ? [
          ["dimension", "Dimensions"],
          ["supported_dimensions", "Supported dimensions"],
        ]
      : service === "tts"
        ? [
            ["voice", "Voice"],
            ["response_format", "Response format"],
          ]
        : service === "stt"
          ? [["language", "Language"]]
          : service === "imagegen"
            ? [
                ["size", "Image size"],
                ["quality", "Quality"],
                ["style", "Style"],
                ["response_format", "Response format"],
              ]
            : service === "videogen"
              ? [
                  ["aspect_ratio", "Aspect ratio"],
                  ["duration", "Duration (seconds)"],
                  ["resolution", "Resolution"],
                ]
              : [];
  return (
    <div className="space-y-4">
      {language && (
        <div className="space-y-4">
          {/* Two knobs of the same kind, so they sit side by side instead of
              stacking into one more column of full-width inputs. */}
          <div className="grid gap-x-5 gap-y-4 lg:grid-cols-2">
            <div className="space-y-2">
              {/* The heading *is* this field's label. It used to sit above a
                  second one that said the same thing, which read as a repeat
                  and — the visible part — pushed this input a whole label row
                  below the select beside it, so the pair never lined up. */}
              <div className="space-y-1.5">
                <div className="flex min-h-5 flex-wrap items-center justify-between gap-2">
                  <label htmlFor={contextId} className="text-xs font-medium">
                    {t("Context length (tokens)")}
                  </label>
                  <button
                    type="button"
                    onClick={() => update("context_window", "")}
                    disabled={
                      managed ||
                      !(model.context_window || model.context_window_tokens)
                    }
                    className="rounded text-xs text-[var(--muted-foreground)] underline underline-offset-4 transition-colors hover:text-[var(--foreground)] disabled:opacity-40 disabled:hover:text-[var(--muted-foreground)]"
                  >
                    {t("Use default")}
                  </button>
                </div>
                <input
                  id={contextId}
                  type="number"
                  className={inputClass}
                  value={
                    model.context_window ??
                    String(model.context_window_tokens || "")
                  }
                  disabled={managed}
                  onChange={(e) => update("context_window", e.target.value)}
                  placeholder={t("Default")}
                />
              </div>
              <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
                {t(
                  "Keep the default, enter a custom value, or use the detected value after testing. Testing does not overwrite your choice.",
                )}
              </p>
            </div>
            <div className="space-y-1.5">
              <p className="flex min-h-5 items-center text-xs font-medium">
                {t("Reasoning effort")}
              </p>
              <select
                aria-label={t("Reasoning effort")}
                className={selectClass}
                value={model.reasoning_effort || ""}
                onChange={(e) => update("reasoning_effort", e.target.value)}
              >
                <option value="">{t("Default")}</option>
                {[
                  ...new Set([
                    ...(model.codex_supported_reasoning_levels || [
                      "none",
                      "minimal",
                      "low",
                      "medium",
                      "high",
                      "xhigh",
                      "max",
                    ]),
                    ...(model.reasoning_effort ? [model.reasoning_effort] : []),
                  ]),
                ].map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <details className={`p-3.5 ${subPanelClass}`}>
            <summary className="cursor-pointer select-none rounded text-xs font-medium marker:text-[var(--muted-foreground)]">
              {t("Model capabilities")}
            </summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {(["tools", "vision", "json_output", "reasoning"] as const).map(
                (key) => (
                  <label key={key} className="space-y-1.5 text-xs">
                    <span className="block">
                      {t(
                        {
                          tools: "Tool calling",
                          vision: "Vision",
                          json_output: "JSON output",
                          reasoning: "Reasoning",
                        }[key],
                      )}
                    </span>
                    <select
                      className={selectClass}
                      disabled={managed}
                      value={
                        model.capabilities?.[key] === undefined
                          ? "auto"
                          : String(model.capabilities[key])
                      }
                      onChange={(e) => {
                        const capabilities = { ...model.capabilities };
                        if (e.target.value === "auto") delete capabilities[key];
                        else capabilities[key] = e.target.value === "true";
                        update("capabilities", capabilities);
                      }}
                    >
                      <option value="auto">{t("Auto")}</option>
                      <option value="true">{t("Supported")}</option>
                      <option value="false">{t("Not supported")}</option>
                    </select>
                  </label>
                ),
              )}
            </div>
          </details>
        </div>
      )}
      {!!fields.length && (
        <div className="grid gap-4 sm:grid-cols-2">
          {fields.map(([field, label]) => (
            <RegistryField
              key={field}
              label={t(label)}
              value={String(model[field] ?? "")}
              onChange={(v) => update(field, v)}
              placeholder={t("Default")}
            />
          ))}
        </div>
      )}
      {service === "embedding" && (
        <label className="block space-y-1.5 text-xs font-medium">
          <span className="block">{t("Send dimensions in embedding requests")}</span>
          <select
            className={selectClass}
            value={
              typeof model.send_dimensions === "boolean"
                ? String(model.send_dimensions)
                : "auto"
            }
            onChange={(e) =>
              update(
                "send_dimensions",
                e.target.value === "auto" ? null : e.target.value === "true",
              )
            }
          >
            <option value="auto">{t("Auto")}</option>
            <option value="true">{t("Enabled")}</option>
            <option value="false">{t("Disabled")}</option>
          </select>
        </label>
      )}
      {managed && (
        <p className="text-xs text-[var(--muted-foreground)]">
          {t(
            "This signed-in provider manages model IDs, context, and capabilities. You can rename the model and choose its reasoning effort.",
          )}
        </p>
      )}
    </div>
  );
}
