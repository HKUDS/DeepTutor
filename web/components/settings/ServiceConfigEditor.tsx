"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  CheckCircle2,
  ChevronDown,
  Eye,
  EyeOff,
  Info,
  Loader2,
  Plus,
  RefreshCw,
  Terminal,
  Trash2,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import Modal from "@/components/common/Modal";
import ProviderIcon from "@/components/common/ProviderIcon";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { apiFetch, apiUrl } from "@/lib/api";
import {
  reasoningEffortOptions,
  reasoningEffortOptionsFromSupportedLevels,
} from "@/lib/reasoning-effort";
import { CodexOAuthCard } from "./CodexOAuthCard";
import { CodeBuddyAuthCard } from "./CodeBuddyAuthCard";
import {
  isBoundManagedCodexProfile,
  isCodexOAuthProfile,
  isManagedCodexProfile,
} from "./codex-profile";
import {
  type CatalogModel,
  type CatalogProfile,
  type LlmContextWindowDetection,
  type ModelCapabilityKey,
  type ProviderOption,
  type ServiceName,
  getActiveModel,
  getActiveProfile,
  useSettings,
} from "@/features/settings/store/SettingsStore";
import { DimensionField } from "./DimensionField";
import { ModelCapabilityFields } from "./ModelCapabilityFields";
import { ModelListPicker } from "./ModelListPicker";
import {
  AddCard,
  CardAction,
  CardGrid,
  ModelCard,
  ProfileCard,
  SectionHead,
  UseRow,
} from "./ModelCards";
import { nextProfileName } from "./profile-naming";
import { searchProviderFields } from "./search-providers";
import {
  activeProfileDetail,
  formatContextWindowSource,
  inputClass,
  selectClass,
  selectOptionClass,
  stringifyExtraHeaders,
} from "./shared";

// The protocol an endpoint speaks. Labels and hints are keyed by the backend
// value so the select never invents a format the registry does not know.
const API_FORMAT_LABELS: Record<string, string> = {
  auto: "Auto (recommended)",
  openai_chat: "OpenAI Chat Completions",
  openai_responses: "OpenAI Responses",
  anthropic: "Anthropic Messages",
};
const API_FORMAT_HINTS: Record<string, string> = {
  auto: "Chat Completions for most endpoints; Responses for OpenAI reasoning models, with fallback.",
  openai_chat: "Send every request to /v1/chat/completions.",
  openai_responses:
    "Send every request to /v1/responses. Endpoint errors are returned without falling back.",
  anthropic: "Send every request as Anthropic Messages (/v1/messages).",
};
const LLM_SHAPED = new Set<ServiceName>(["llm", "task"]);

const SERVICE_LABEL: Record<ServiceName, string> = {
  llm: "LLM",
  task: "Task model",
  embedding: "Embedding",
  search: "Search",
  tts: "Text-to-Speech",
  stt: "Speech-to-Text",
  imagegen: "Image Generation",
  videogen: "Video Generation",
};

export function ServiceConfigEditor({ service }: { service: ServiceName }) {
  const { t } = useTranslation();
  const {
    catalog,
    draft,
    catalogEditable,
    settingsError,
    providers,
    language,
    embeddingCapabilities,
    embeddingDefaultDim,
    logs,
    testRunning,
    applying,
    mutateCatalog,
    addProfile,
    removeActiveProfile,
    addModel,
    removeActiveModel,
    updateProfileField: setProfileField,
    updateModelField: setModelField,
    updateModelBoolField: setModelBoolField,
    updateContextWindowField: setContextWindowField,
    updateReasoningEffort: setReasoningEffort,
    updateModelCapability: setModelCapability,
    llmContextDetection,
    applyDetectedContextWindow,
    runDetailedTest,
    applyService,
    setToast,
  } = useSettings();

  const profiles = draft.services[service].profiles;
  const inUseProfileId = draft.services[service].active_profile_id;
  const inUseModelId = draft.services[service].active_model_id;

  // ── Browsing vs using ───────────────────────────────────────────────────
  //
  // The page always shows its providers. Opening one pops a dialog with its
  // connection fields and its models; nothing in that dialog adopts it — "in
  // use" is a separate, deliberate act, which is what lets you look at a
  // provider you are not currently running on without switching to it.
  const [openProfileId, setOpenProfileId] = useState<string | null>(null);
  const [expandedModelId, setExpandedModelId] = useState<string | null>(null);

  const openedProfile =
    profiles.find((item) => item.id === openProfileId) ?? null;

  // Whatever the field editors below are pointed at. Falling back to the
  // profile in use keeps every reference working before anything is opened.
  const activeProfile = openedProfile ?? getActiveProfile(draft, service);
  const activeModel = openedProfile
    ? ((expandedModelId
        ? openedProfile.models.find((item) => item.id === expandedModelId)
        : null) ?? null)
    : getActiveModel(draft, service);

  // The context's mutators write to whatever is in use unless told otherwise.
  // Binding them to what is on screen here means the ~300 lines of field
  // editors below need no knowledge of any of this.
  const updateProfileField = useCallback(
    (svc: ServiceName, field: keyof CatalogProfile, value: string) =>
      setProfileField(svc, field, value, activeProfile?.id),
    [setProfileField, activeProfile?.id],
  );
  const updateModelField = useCallback(
    (svc: ServiceName, field: keyof CatalogModel, value: string) =>
      setModelField(svc, field, value, activeProfile?.id, activeModel?.id),
    [setModelField, activeProfile?.id, activeModel?.id],
  );
  const updateModelBoolField = useCallback(
    (svc: ServiceName, field: keyof CatalogModel, value: boolean) =>
      setModelBoolField(svc, field, value, activeProfile?.id, activeModel?.id),
    [setModelBoolField, activeProfile?.id, activeModel?.id],
  );
  const updateContextWindowField = useCallback(
    (value: string) =>
      setContextWindowField(value, activeProfile?.id, activeModel?.id),
    [setContextWindowField, activeProfile?.id, activeModel?.id],
  );
  const updateReasoningEffort = useCallback(
    (value: string) =>
      setReasoningEffort(value, activeProfile?.id, activeModel?.id),
    [setReasoningEffort, activeProfile?.id, activeModel?.id],
  );
  const updateModelCapability = useCallback(
    (key: ModelCapabilityKey, value: boolean | null) =>
      setModelCapability(
        service,
        key,
        value,
        activeProfile?.id,
        activeModel?.id,
      ),
    [setModelCapability, service, activeProfile?.id, activeModel?.id],
  );

  const activeProviderValue =
    service === "search"
      ? activeProfile?.provider || ""
      : activeProfile?.binding || "";
  const activeProviderOption = (providers[service] || []).find(
    (option) => option.value === activeProviderValue,
  );
  const isManagedCodex = isManagedCodexProfile(activeProfile);
  const isBoundManagedCodex = isBoundManagedCodexProfile(activeProfile);
  const isCodexOAuth = isCodexOAuthProfile(
    service,
    activeProviderValue,
    activeProviderOption,
    activeProfile,
  );

  // Arriving from Settings > Connections with ?profile=<id>: open that
  // provider's dialog directly. It used to have to *adopt* the profile to
  // show it, because selecting and using were the same act — with the two
  // separated, following the link costs nothing and needs no warning.
  //
  // The query is read from `window.location` rather than `useSearchParams()`
  // so no settings page needs a Suspense boundary for something that only
  // exists after hydration.
  const deepLinkHandled = useRef(false);
  useEffect(() => {
    if (deepLinkHandled.current) return;
    const requested = new URLSearchParams(window.location.search).get(
      "profile",
    );
    if (!requested) {
      deepLinkHandled.current = true;
      return;
    }
    // The catalog may still be loading; leave the flag down and retry.
    if (!profiles.some((item) => item.id === requested)) return;
    deepLinkHandled.current = true;
    // Drop the query so a refresh does not re-open something already closed.
    window.history.replaceState(null, "", window.location.pathname);
    setOpenProfileId(requested);
  }, [profiles]);

  const [showApiKey, setShowApiKey] = useState(false);
  const [deletingProfile, setDeletingProfile] = useState<CatalogProfile | null>(
    null,
  );
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [editingModelId, setEditingModelId] = useState<string | null>(null);
  const [editingModelName, setEditingModelName] = useState("");
  const [editingProfileId, setEditingProfileId] = useState<string | null>(null);
  const [editingProfileName, setEditingProfileName] = useState("");
  const [modelsSyncing, setModelsSyncing] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);

  const closeProviderEditor = useCallback(() => {
    setOpenProfileId(null);
    setExpandedModelId(null);
  }, []);

  const finishProviderEditing = useCallback(async () => {
    const serviceChanged =
      JSON.stringify(catalog.services[service]) !==
      JSON.stringify(draft.services[service]);
    if (serviceChanged && !(await applyService(service))) return;
    closeProviderEditor();
  }, [
    applyService,
    catalog.services,
    closeProviderEditor,
    draft.services,
    service,
  ]);

  // Reset API-key visibility whenever we land on a different profile or
  // switch services — same effect the old code had, but using React's
  // documented "store previous prop in state" pattern so it happens during
  // render rather than in a useEffect (which the linter forbids).
  const profileKey = `${service}:${activeProfile?.id ?? "none"}`;
  const [lastProfileKey, setLastProfileKey] = useState(profileKey);
  if (lastProfileKey !== profileKey) {
    setLastProfileKey(profileKey);
    if (showApiKey) setShowApiKey(false);
  }

  const searchProviderRaw =
    service === "search"
      ? (activeProfile?.provider || "").trim().toLowerCase()
      : "";
  const showSearchProviderWarning =
    service === "search" && Boolean(searchProviderRaw);
  // Every judgement below reads the backend's own provider list, so the web app
  // never keeps a second (and drifting) copy of what is supported.
  const searchProviderOption = (providers.search || []).find(
    (option) => option.value === searchProviderRaw,
  );
  const isDeprecatedSearchProvider =
    searchProviderOption?.status === "deprecated";
  const isSupportedSearchProvider =
    Boolean(searchProviderOption) && !isDeprecatedSearchProvider;
  const supportedSearchProviderNames = (providers.search || [])
    .filter(
      (option) => option.status !== "deprecated" && option.value !== "none",
    )
    .map((option) => option.value)
    .join("/");
  // Providers that fail hard rather than falling back need their key before the
  // first query — say so while the user is still on this screen.
  const searchProviderMissingKey =
    service === "search" &&
    isSupportedSearchProvider &&
    searchProviderOption?.requires_api_key === true &&
    searchProviderOption?.soft_fallback === false &&
    !String(activeProfile?.api_key || "").trim();
  const activeLlmDetection =
    service === "llm" &&
    llmContextDetection?.profileId === draft.services.llm.active_profile_id &&
    llmContextDetection?.modelId === draft.services.llm.active_model_id
      ? llmContextDetection
      : null;
  const reasoningOptions =
    service === "llm" && activeModel
      ? isManagedCodex
        ? isBoundManagedCodex
          ? reasoningEffortOptionsFromSupportedLevels(
              activeModel.codex_supported_reasoning_levels ?? [],
            )
          : []
        : reasoningEffortOptions(
            activeProfile?.binding,
            activeModel.model,
            activeModel.reasoning_effort,
            activeModel.capabilities?.reasoning,
          )
      : [];

  const syncProviderModels = async (
    connection?: Pick<CatalogProfile, "binding" | "base_url" | "api_key">,
  ) => {
    if (!LLM_SHAPED.has(service) || !activeProfile || modelsSyncing) return;
    const binding = connection?.binding ?? activeProfile.binding ?? "";
    const baseUrl = connection?.base_url ?? activeProfile.base_url ?? "";
    const apiKey = connection?.api_key ?? activeProfile.api_key ?? "";
    if (!binding || (binding !== "codebuddy" && !baseUrl.trim())) return;

    const profileId = activeProfile.id;
    setModelsSyncing(true);
    try {
      const response = await apiFetch(apiUrl("/api/settings/fetch-models"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          binding,
          base_url: baseUrl,
          api_key: apiKey || null,
          profile_id: profileId,
          service,
          api_format: activeProfile.api_format ?? "auto",
        }),
      });
      if (!response.ok) {
        const payload = (await response.json().catch(() => ({}))) as {
          detail?: string;
        };
        throw new Error(payload.detail || `HTTP ${response.status}`);
      }
      const payload = (await response.json()) as {
        models?: Array<{ id: string; name?: string }>;
      };
      const fetched = payload.models || [];
      if (fetched.length === 0) throw new Error(t("No models returned"));

      mutateCatalog((next) => {
        const target = next.services[service];
        const profile = target.profiles.find((item) => item.id === profileId);
        if (!profile || profile.binding !== binding) return;
        const existing = new Map(
          profile.models.map((model) => [model.model, model]),
        );
        profile.models = fetched.map((item, index) => {
          const previous = existing.get(item.id);
          return previous
            ? { ...previous, name: item.name || previous.name, model: item.id }
            : {
                id: `${service}-model-${Date.now()}-${index}`,
                name: item.name || item.id,
                model: item.id,
              };
        });
        if (
          !profile.models.some((model) => model.id === target.active_model_id)
        ) {
          target.active_model_id = profile.models[0]?.id ?? null;
        }
      });
      setToast(t("Synced {{count}} models", { count: fetched.length }));
    } catch (error) {
      setToast(error instanceof Error ? error.message : String(error));
    } finally {
      setModelsSyncing(false);
    }
  };

  const startModelRename = (model: CatalogModel) => {
    setEditingModelId(model.id);
    setEditingModelName(model.name || model.model || "");
  };

  const commitModelRename = (modelId: string) => {
    const fallbackIndex =
      activeProfile?.models.findIndex((model) => model.id === modelId) ?? -1;
    const fallbackName = defaultModelLabel(language, fallbackIndex + 1);
    const nextName = editingModelName.trim() || fallbackName;
    mutateCatalog((next) => {
      const profile = getActiveProfile(next, service);
      const model = profile?.models.find((item) => item.id === modelId);
      if (model) model.name = nextName;
    });
    setEditingModelId(null);
    setEditingModelName("");
  };

  const cancelModelRename = () => {
    setEditingModelId(null);
    setEditingModelName("");
  };

  const startProfileRename = (profile: CatalogProfile) => {
    setEditingProfileId(profile.id);
    setEditingProfileName(profile.name || "");
  };

  const commitProfileRename = (profileId: string) => {
    const nextName = editingProfileName.trim();
    if (nextName) {
      mutateCatalog((next) => {
        const profile = next.services[service].profiles.find(
          (item) => item.id === profileId,
        );
        if (profile) profile.name = nextName;
      });
    }
    setEditingProfileId(null);
    setEditingProfileName("");
  };

  const cancelProfileRename = () => {
    setEditingProfileId(null);
    setEditingProfileName("");
  };

  if (!catalogEditable) {
    // catalogEditable=false covers two unrelated cases: settings fetch failed,
    // or multi-user grant denied. Split them so a Docker user without the
    // 8001 port mapped does not see an "assigned by administrator" hint.
    if (settingsError) {
      return (
        <div className="rounded-xl border border-dashed border-[var(--border)] px-5 py-10 text-center text-[13px] text-[var(--muted-foreground)]">
          {t(
            "Backend unreachable — model endpoints will appear once the connection is restored. See the banner above for details.",
          )}
        </div>
      );
    }
    return (
      <div className="space-y-4">
        <div className="rounded-xl border border-dashed border-[var(--border)] px-5 py-10 text-center text-[13px] text-[var(--muted-foreground)]">
          {t(
            "Model endpoints are assigned by your administrator. You can still personalize theme and language here.",
          )}
        </div>
        {/* One thing an ordinary user CAN configure for themselves: an
            owner-bound Codex login. It authenticates their own ChatGPT plan,
            so it is never something an administrator can grant them — the
            account has to sign in for itself (#781). The card talks only to
            the per-user OAuth endpoints and exposes no catalog. */}
        {service === "llm" && <CodexOAuthCard />}
      </div>
    );
  }

  return (
    <div data-tour={`tour-${service}`} className="space-y-5">
      {activeProfile ? (
        <div>
          {/* ── The providers configured for this service ──────────────────
                 A card is a place, not a switch: opening one pops a dialog
                 with its connection fields and its models, and nothing in
                 there changes which provider the app is running on. That
                 is what "In use" is for. */}
          <SectionHead
            title={t("Providers")}
            action={
              <CardAction onClick={() => addProfile(service)}>
                <Plus className="h-3 w-3" />
                {t("Add provider")}
              </CardAction>
            }
          />
          <CardGrid>
            {profiles.map((profile) => (
              <ProfileCard
                key={profile.id}
                profile={profile}
                service={service}
                inUse={profile.id === inUseProfileId}
                open={profile.id === openProfileId}
                renaming={editingProfileId === profile.id}
                renameValue={editingProfileName}
                onRenameChange={setEditingProfileName}
                onRenameCommit={() => commitProfileRename(profile.id)}
                onRenameCancel={cancelProfileRename}
                onRenameStart={() => startProfileRename(profile)}
                onOpen={() => {
                  setOpenProfileId(profile.id);
                  setExpandedModelId(
                    profile.id === inUseProfileId
                      ? (inUseModelId ?? null)
                      : (profile.models[0]?.id ?? null),
                  );
                }}
                onUse={() =>
                  mutateCatalog((next) => {
                    next.services[service].active_profile_id = profile.id;
                    if (service !== "search") {
                      next.services[service].active_model_id =
                        profile.models[0]?.id ?? null;
                    }
                  })
                }
              />
            ))}
            <AddCard
              label={t("Add provider")}
              onClick={() => addProfile(service)}
            />
          </CardGrid>

          {/* ── One provider, in a dialog: its connection, then its models ── */}
          {openedProfile && (
            <Modal
              isOpen
              onClose={closeProviderEditor}
              title={openedProfile.name}
              titleIcon={
                <ProviderIcon
                  provider={
                    service === "search"
                      ? openedProfile.provider || ""
                      : openedProfile.binding || ""
                  }
                  size={15}
                />
              }
              width="lg"
              footer={
                <div className="flex items-center justify-between gap-3">
                  <button
                    type="button"
                    onClick={() => setDeletingProfile(openedProfile)}
                    className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12.5px] text-red-500/80 transition-colors hover:bg-red-500/10 hover:text-red-500"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    {t("Delete provider")}
                  </button>
                  <button
                    type="button"
                    onClick={() => void finishProviderEditing()}
                    disabled={applying}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12.5px] font-medium text-[var(--foreground)] transition-colors hover:border-[var(--foreground)]/40 disabled:opacity-40"
                  >
                    {applying && <Loader2 className="h-3 w-3 animate-spin" />}
                    {t("Done")}
                  </button>
                </div>
              }
            >
              <div className="space-y-6 p-5">
                <UseRow
                  inUse={openedProfile.id === inUseProfileId}
                  onUse={() =>
                    mutateCatalog((next) => {
                      next.services[service].active_profile_id =
                        openedProfile.id;
                      if (service !== "search") {
                        next.services[service].active_model_id =
                          openedProfile.models[0]?.id ?? null;
                      }
                    })
                  }
                />

                <ProfileFields
                  service={service}
                  profile={activeProfile}
                  showApiKey={showApiKey}
                  setShowApiKey={setShowApiKey}
                  showSearchProviderWarning={showSearchProviderWarning}
                  isSupportedSearchProvider={isSupportedSearchProvider}
                  isDeprecatedSearchProvider={isDeprecatedSearchProvider}
                  searchProviderMissingKey={searchProviderMissingKey}
                  supportedSearchProviderNames={supportedSearchProviderNames}
                  onProviderChanged={(provider, previousProvider) => {
                    if (service !== "llm" || !activeProfile) return;
                    const crossesCodeBuddyBoundary =
                      provider.value === "codebuddy" ||
                      previousProvider === "codebuddy";
                    if (crossesCodeBuddyBoundary) {
                      const profileId = activeProfile.id;
                      mutateCatalog((next) => {
                        const target = next.services.llm;
                        const profile = target.profiles.find(
                          (item) => item.id === profileId,
                        );
                        if (!profile || profile.binding !== provider.value)
                          return;
                        if (provider.value === "codebuddy") {
                          profile.models = [];
                          target.active_model_id = null;
                          return;
                        }
                        const modelId = `llm-model-${Date.now()}`;
                        profile.models = [
                          {
                            id: modelId,
                            name: defaultModelLabel(language, 1),
                            model: "",
                          },
                        ];
                        target.active_model_id = modelId;
                      });
                    }
                    if (provider.value === "codebuddy") {
                      void syncProviderModels({
                        binding: provider.value,
                        base_url: provider.base_url || "",
                        api_key: "",
                      });
                    }
                  }}
                />

                {service !== "search" && (
                  <div>
                    <SectionHead
                      title={t("Models")}
                      action={
                        <span className="flex items-center gap-2">
                          {service === "llm" &&
                            openedProfile.binding === "codebuddy" && (
                              <CardAction
                                onClick={() => void syncProviderModels()}
                                disabled={modelsSyncing}
                              >
                                <RefreshCw
                                  className={`h-3 w-3 ${modelsSyncing ? "animate-spin" : ""}`}
                                />
                                {t("Sync models")}
                              </CardAction>
                            )}
                          {LLM_SHAPED.has(service) &&
                            !isCodexOAuth &&
                            openedProfile.binding !== "codebuddy" &&
                            Boolean(
                              String(openedProfile.base_url || "").trim(),
                            ) && (
                              <CardAction onClick={() => setPickerOpen(true)}>
                                <RefreshCw className="h-3 w-3" />
                                {t("List models")}
                              </CardAction>
                            )}
                          <CardAction
                            onClick={() => addModel(service, openedProfile.id)}
                          >
                            <Plus className="h-3 w-3" />
                            {t("Add model")}
                          </CardAction>
                        </span>
                      }
                    />
                    {/* Capped at 2 columns rather than the page grid's
                        `xl:grid-cols-3` — that breakpoint reads the browser
                        viewport, not this dialog's fixed width, and would
                        force 3 columns into a 600px box on a large screen. */}
                    <div className="grid gap-2.5 sm:grid-cols-2">
                      {openedProfile.models.map((model, index) => (
                        <ModelCard
                          key={model.id}
                          model={model}
                          service={service}
                          language={language}
                          index={index}
                          inUse={
                            openedProfile.id === inUseProfileId &&
                            model.id === inUseModelId
                          }
                          expanded={model.id === expandedModelId}
                          renaming={editingModelId === model.id}
                          renameValue={editingModelName}
                          onRenameChange={setEditingModelName}
                          onRenameCommit={() => commitModelRename(model.id)}
                          onRenameCancel={cancelModelRename}
                          onRenameStart={() => startModelRename(model)}
                          onToggleExpand={() =>
                            setExpandedModelId(
                              model.id === expandedModelId ? null : model.id,
                            )
                          }
                          onUse={() =>
                            mutateCatalog((next) => {
                              next.services[service].active_profile_id =
                                openedProfile.id;
                              next.services[service].active_model_id = model.id;
                            })
                          }
                          onDelete={() =>
                            removeActiveModel(
                              service,
                              openedProfile.id,
                              model.id,
                            )
                          }
                        />
                      ))}
                      <AddCard
                        label={t("Add model")}
                        onClick={() => addModel(service, openedProfile.id)}
                      />
                    </div>
                  </div>
                )}

                {service !== "search" && (
                  <div>
                    {activeModel && (!isCodexOAuth || isBoundManagedCodex) && (
                      <div className="mb-2.5 flex items-center justify-between gap-2 border-b border-[var(--border)]/60 pb-2">
                        <div className="min-w-0 truncate text-[13px] font-medium text-[var(--foreground)]">
                          {(activeModel.name || "").trim() || t("Model")}
                        </div>
                        <button
                          type="button"
                          onClick={() => setExpandedModelId(null)}
                          className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)]/50 px-2.5 py-1 text-[12px] text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)]"
                        >
                          <X className="h-3 w-3" />
                          {t("Close")}
                        </button>
                      </div>
                    )}
                    {activeModel && (!isCodexOAuth || isBoundManagedCodex) && (
                      <div className="grid gap-4 sm:grid-cols-2">
                        {!isCodexOAuth && (
                          <div>
                            <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
                              {t("Model ID")}
                            </div>
                            <input
                              className={inputClass}
                              value={activeModel.model}
                              onChange={(e) =>
                                updateModelField(
                                  service,
                                  "model",
                                  e.target.value,
                                )
                              }
                              placeholder="gpt-4o"
                            />
                          </div>
                        )}
                        {service === "llm" && (
                          <>
                            {!isCodexOAuth && (
                              <>
                                <div>
                                  <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
                                    {t("Context Window")}
                                  </div>
                                  <input
                                    className={inputClass}
                                    inputMode="numeric"
                                    value={activeModel.context_window || ""}
                                    onChange={(e) =>
                                      updateContextWindowField(e.target.value)
                                    }
                                    placeholder="65536"
                                  />
                                  <ContextWindowMeta model={activeModel} />
                                </div>
                                <ContextWindowDetectionBanner
                                  model={activeModel}
                                  detection={activeLlmDetection}
                                  onApply={applyDetectedContextWindow}
                                />
                              </>
                            )}
                            {reasoningOptions.length > 0 && (
                              <div>
                                <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
                                  {t("Reasoning effort")}
                                </div>
                                <div className="relative">
                                  <select
                                    className={selectClass}
                                    value={activeModel.reasoning_effort || ""}
                                    onChange={(event) =>
                                      updateReasoningEffort(event.target.value)
                                    }
                                  >
                                    {reasoningOptions.map((option) => (
                                      <option
                                        className={selectOptionClass}
                                        key={option.value || "auto"}
                                        value={option.value}
                                      >
                                        {t(option.label)}
                                      </option>
                                    ))}
                                  </select>
                                  <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted-foreground)]" />
                                </div>
                                <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
                                  {t(
                                    "Sets this model's default reasoning depth. Auto leaves the choice to the provider.",
                                  )}
                                </p>
                              </div>
                            )}
                          </>
                        )}
                        {LLM_SHAPED.has(service) && !isCodexOAuth && (
                          <ModelCapabilityFields
                            binding={activeProfile?.binding}
                            model={activeModel}
                            reasoningKnown={reasoningOptions.length > 0}
                            onChange={updateModelCapability}
                          />
                        )}
                        {service === "embedding" && (
                          <div>
                            <div className="mb-1.5 flex items-center justify-between gap-2">
                              <span className="text-[12px] text-[var(--muted-foreground)]">
                                {t("Dimension")}
                              </span>
                              <label className="inline-flex cursor-pointer items-center gap-1.5 text-[11px] text-[var(--muted-foreground)] select-none">
                                <input
                                  type="checkbox"
                                  className="h-3 w-3 cursor-pointer accent-[var(--foreground)]"
                                  checked={
                                    activeModel.send_dimensions !== false
                                  }
                                  onChange={(e) =>
                                    updateModelBoolField(
                                      service,
                                      "send_dimensions",
                                      e.target.checked,
                                    )
                                  }
                                />
                                <span>{t("Send dimensions")}</span>
                                <span
                                  tabIndex={0}
                                  className="group/info relative inline-flex cursor-help focus:outline-none"
                                >
                                  <Info className="h-3 w-3 opacity-50 transition-opacity group-hover/info:opacity-100 group-focus/info:opacity-100" />
                                  <span
                                    role="tooltip"
                                    className="pointer-events-none absolute top-full left-1/2 z-20 mt-1.5 w-64 -translate-x-1/2 rounded-lg border border-[var(--border)] bg-[var(--card)] p-2.5 text-[11px] leading-relaxed text-[var(--foreground)] opacity-0 shadow-lg transition-opacity duration-75 group-hover/info:opacity-100 group-focus/info:opacity-100"
                                  >
                                    {t(
                                      "Some embedding models (e.g. Qwen text-embedding-v4) reject the `dimensions` request param. Turn this off if your provider returns HTTP 400.",
                                    )}
                                  </span>
                                </span>
                              </label>
                            </div>
                            <DimensionField
                              activeModel={activeModel}
                              activeBinding={activeProfile?.binding}
                              capabilities={embeddingCapabilities}
                              embeddingDefaultDim={embeddingDefaultDim}
                              inputClass={inputClass}
                              onChangeDimension={(value) =>
                                updateModelField(service, "dimension", value)
                              }
                            />
                          </div>
                        )}
                        {service === "tts" && (
                          <>
                            <div>
                              <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
                                {t("Voice")}
                              </div>
                              <input
                                className={inputClass}
                                value={activeModel.voice || ""}
                                onChange={(e) =>
                                  updateModelField(
                                    service,
                                    "voice",
                                    e.target.value,
                                  )
                                }
                                placeholder="alloy"
                              />
                              <p className="mt-1.5 text-[11px] text-[var(--muted-foreground)]">
                                {t(
                                  "Provider-specific voice name, e.g. alloy (OpenAI) or model:voice (SiliconFlow).",
                                )}
                              </p>
                            </div>
                            <div>
                              <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
                                {t("Output format")}
                              </div>
                              <div className="relative">
                                <select
                                  className={selectClass}
                                  value={activeModel.response_format || "mp3"}
                                  onChange={(e) =>
                                    updateModelField(
                                      service,
                                      "response_format",
                                      e.target.value,
                                    )
                                  }
                                >
                                  {[
                                    "mp3",
                                    "wav",
                                    "opus",
                                    "aac",
                                    "flac",
                                    "pcm",
                                  ].map((fmt) => (
                                    <option
                                      className={selectOptionClass}
                                      key={fmt}
                                      value={fmt}
                                    >
                                      {fmt}
                                    </option>
                                  ))}
                                </select>
                                <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted-foreground)]" />
                              </div>
                            </div>
                          </>
                        )}
                        {service === "imagegen" && (
                          <>
                            <div>
                              <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
                                {t("Image size")}
                              </div>
                              <input
                                className={inputClass}
                                value={activeModel.size || ""}
                                onChange={(e) =>
                                  updateModelField(
                                    service,
                                    "size",
                                    e.target.value,
                                  )
                                }
                                placeholder="1024x1024"
                              />
                              <p className="mt-1.5 text-[11px] text-[var(--muted-foreground)]">
                                {t(
                                  "Default pixel size sent with each request. Leave empty for the provider default.",
                                )}
                              </p>
                            </div>
                            <div>
                              <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
                                {t("Quality / Style")}
                              </div>
                              <div className="grid grid-cols-2 gap-2">
                                <input
                                  className={inputClass}
                                  value={activeModel.quality || ""}
                                  onChange={(e) =>
                                    updateModelField(
                                      service,
                                      "quality",
                                      e.target.value,
                                    )
                                  }
                                  placeholder={t("quality (e.g. hd)")}
                                />
                                <input
                                  className={inputClass}
                                  value={activeModel.style || ""}
                                  onChange={(e) =>
                                    updateModelField(
                                      service,
                                      "style",
                                      e.target.value,
                                    )
                                  }
                                  placeholder={t("style (e.g. vivid)")}
                                />
                              </div>
                            </div>
                          </>
                        )}
                        {service === "videogen" && (
                          <>
                            <div>
                              <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
                                {t("Aspect ratio")}
                              </div>
                              <input
                                className={inputClass}
                                value={activeModel.aspect_ratio || ""}
                                onChange={(e) =>
                                  updateModelField(
                                    service,
                                    "aspect_ratio",
                                    e.target.value,
                                  )
                                }
                                placeholder="16:9"
                              />
                              <p className="mt-1.5 text-[11px] text-[var(--muted-foreground)]">
                                {t(
                                  "Defaults sent with each request. Leave empty for the provider default.",
                                )}
                              </p>
                            </div>
                            <div>
                              <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
                                {t("Duration / Resolution")}
                              </div>
                              <div className="grid grid-cols-2 gap-2">
                                <input
                                  className={inputClass}
                                  inputMode="numeric"
                                  value={activeModel.duration || ""}
                                  onChange={(e) =>
                                    updateModelField(
                                      service,
                                      "duration",
                                      e.target.value,
                                    )
                                  }
                                  placeholder={t("seconds")}
                                />
                                <input
                                  className={inputClass}
                                  value={activeModel.resolution || ""}
                                  onChange={(e) =>
                                    updateModelField(
                                      service,
                                      "resolution",
                                      e.target.value,
                                    )
                                  }
                                  placeholder="720p"
                                />
                              </div>
                            </div>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </Modal>
          )}

          {pickerOpen &&
            openedProfile &&
            (service === "llm" || service === "task") && (
              <ModelListPicker
                service={service}
                profile={openedProfile}
                existing={openedProfile.models.map((model) => model.model)}
                onClose={() => setPickerOpen(false)}
                onAdd={(ids) => {
                  const profileId = openedProfile.id;
                  mutateCatalog((next) => {
                    const target = next.services[service];
                    const profile = target.profiles.find(
                      (item) => item.id === profileId,
                    );
                    if (!profile) return;
                    const present = new Set(
                      profile.models.map((model) => model.model),
                    );
                    ids
                      .filter((id) => !present.has(id))
                      .forEach((id, index) => {
                        profile.models.push({
                          id: `${service}-model-${Date.now()}-${index}`,
                          name: id,
                          model: id,
                        });
                      });
                    if (
                      profile.id === target.active_profile_id &&
                      !profile.models.some(
                        (model) => model.id === target.active_model_id,
                      )
                    ) {
                      target.active_model_id = profile.models[0]?.id ?? null;
                    }
                  });
                  setPickerOpen(false);
                  setToast(t("Added {{count}} models.", { count: ids.length }));
                }}
              />
            )}

          <div className="mt-7 min-w-0">
            {/* ── Diagnostics — per-service, inline ── */}
            <div className="border-t border-[var(--border)]/60">
              <div className="flex items-center justify-between py-2.5">
                <button
                  type="button"
                  onClick={() => setDiagnosticsOpen((v) => !v)}
                  className="flex min-w-0 flex-1 items-center gap-2 text-left"
                  aria-expanded={diagnosticsOpen}
                >
                  <Terminal className="h-3.5 w-3.5 text-[var(--muted-foreground)]" />
                  <span className="text-[13px] font-medium text-[var(--foreground)]">
                    {t("Diagnostics")}
                  </span>
                  {testRunning === service && (
                    <Loader2 className="h-3 w-3 animate-spin text-[var(--primary)]" />
                  )}
                </button>
                <div className="ml-3 flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => {
                      if (!diagnosticsOpen) setDiagnosticsOpen(true);
                      runDetailedTest(service);
                    }}
                    disabled={testRunning !== null}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-2.5 py-1 text-[12px] text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:opacity-40"
                  >
                    {t("Run test")}
                  </button>
                  <button
                    type="button"
                    onClick={() => setDiagnosticsOpen((v) => !v)}
                    className="text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
                    aria-label={
                      diagnosticsOpen
                        ? t("Collapse diagnostics")
                        : t("Expand diagnostics")
                    }
                    aria-expanded={diagnosticsOpen}
                  >
                    <ChevronDown
                      className={`h-4 w-4 transition-transform ${diagnosticsOpen ? "rotate-180" : ""}`}
                    />
                  </button>
                </div>
              </div>
              {diagnosticsOpen && (
                <div className="border-t border-[var(--border)] px-5 py-4">
                  <p className="mb-3 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                    {t(
                      "Streams config snapshot, request target, response summary, and service-specific validation for the active {{service}} profile.",
                      { service: t(SERVICE_LABEL[service]) },
                    )}
                  </p>
                  <pre className="max-h-[360px] overflow-auto rounded-lg bg-[#0f0f0f] p-4 font-mono text-[12px] leading-6 text-[#777] whitespace-pre-wrap break-words dark:bg-[#0a0a0a]">
                    {testRunning === service || logs
                      ? logs
                      : t("Waiting for test run...")}
                  </pre>
                </div>
              )}
            </div>
          </div>
        </div>
      ) : (
        // Zero state in the same language as the populated one: the grid with
        // only its add card in it, so starting out looks like what comes next.
        <div>
          <SectionHead title={t("Providers")} />
          <CardGrid>
            <AddCard
              label={t("Add provider")}
              onClick={() => addProfile(service)}
            />
          </CardGrid>
        </div>
      )}

      {deletingProfile && (
        <ConfirmDialog
          open
          title={t("Delete this provider?")}
          tone="danger"
          confirmLabel={t("Delete")}
          onConfirm={() => {
            removeActiveProfile(service, deletingProfile.id);
            setDeletingProfile(null);
            setOpenProfileId(null);
            setExpandedModelId(null);
          }}
          onCancel={() => setDeletingProfile(null)}
        >
          {deletingProfile.id === inUseProfileId
            ? t(
                "This is your active {{service}} provider — deleting it switches to {{next}}.",
                {
                  service: t(SERVICE_LABEL[service]),
                  next:
                    profiles.find((item) => item.id !== deletingProfile.id)
                      ?.name ?? t("nothing configured"),
                },
              )
            : t(
                "This removes {{count}} model(s) and its saved credentials. This can't be undone.",
                { count: deletingProfile.models.length },
              )}
        </ConfirmDialog>
      )}
    </div>
  );
}

function defaultModelLabel(language: "en" | "zh", index: number): string {
  const safeIndex = index > 0 ? index : 1;
  return language === "zh" ? `模型${safeIndex}` : `Model ${safeIndex}`;
}

function formatCompactTokens(value: string | number | undefined): string {
  if (value === undefined || value === "") return "";
  const parsed =
    typeof value === "number"
      ? value
      : Number.parseInt(String(value).replace(/[^\d]/g, ""), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return "";
  if (parsed >= 1_000_000) {
    const m = parsed / 1_000_000;
    return `${m >= 10 ? m.toFixed(0) : m.toFixed(1).replace(/\.0$/, "")}M`;
  }
  if (parsed >= 1_000) {
    const k = parsed / 1_000;
    return `${k >= 10 ? k.toFixed(0) : k.toFixed(1).replace(/\.0$/, "")}K`;
  }
  return String(parsed);
}

function formatVoiceBadge(value: string | undefined): string {
  const voice = (value || "").trim();
  if (!voice) return "";
  // "model:voice" → show just the voice segment to keep the chip compact.
  const tail = voice.includes(":")
    ? voice.slice(voice.lastIndexOf(":") + 1)
    : voice;
  return tail.length > 14 ? `${tail.slice(0, 13)}…` : tail;
}

function formatDimensionBadge(value: string | number | undefined): string {
  if (value === undefined || value === "") return "";
  const parsed =
    typeof value === "number"
      ? value
      : Number.parseInt(String(value).replace(/[^\d]/g, ""), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return "";
  return `${parsed}d`;
}

function formatIsoLocal(value: string | undefined): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ` +
    `${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`
  );
}

function ContextWindowMeta({ model }: { model: CatalogModel }) {
  const { t } = useTranslation();
  if (!model.context_window) return null;
  const source = formatContextWindowSource(model.context_window_source, t);
  const updatedAt = formatIsoLocal(model.context_window_detected_at);
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11px] text-[var(--muted-foreground)]">
      <span>{t("Source")}:</span>
      <span className="text-[var(--foreground)]/80">{source}</span>
      {updatedAt && (
        <>
          <span className="text-[var(--muted-foreground)]/40">·</span>
          <span title={model.context_window_detected_at}>{updatedAt}</span>
        </>
      )}
    </div>
  );
}

function ContextWindowDetectionBanner({
  model,
  detection,
  onApply,
}: {
  model: CatalogModel;
  detection: LlmContextWindowDetection | null;
  onApply: () => void;
}) {
  const { t } = useTranslation();
  if (!detection) return null;
  const currentRaw = Number.parseInt(
    String(model.context_window || "").replace(/[^\d]/g, ""),
    10,
  );
  const matches =
    Number.isFinite(currentRaw) && currentRaw === detection.contextWindow;
  const detectedFormatted = detection.contextWindow.toLocaleString("en-US");
  const detectedAt = formatIsoLocal(detection.detectedAt);
  const source = formatContextWindowSource(detection.source, t);

  if (matches) {
    return (
      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-[12px] text-[var(--muted-foreground)] sm:col-span-2">
        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
        <span className="text-[var(--foreground)]/80">
          {t("Detected value matches your current setting")}
        </span>
        <span className="text-[var(--muted-foreground)]/70">
          ({detectedFormatted} · {source})
        </span>
      </div>
    );
  }

  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-[var(--border)] bg-[var(--muted)]/30 px-3 py-2 sm:col-span-2">
      <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[12px]">
        <span className="text-[var(--muted-foreground)]">{t("Detected")}:</span>
        <span className="font-mono text-[13px] font-medium text-[var(--foreground)] tabular-nums">
          {detectedFormatted}
        </span>
        <span className="text-[var(--muted-foreground)]/80">· {source}</span>
        {detectedAt && (
          <span className="text-[var(--muted-foreground)]/60">
            · {detectedAt}
          </span>
        )}
      </div>
      <button
        type="button"
        onClick={onApply}
        className="shrink-0 rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1 text-[11.5px] font-medium text-[var(--foreground)] transition-colors hover:border-[var(--foreground)]"
      >
        {t("Apply")}
      </button>
    </div>
  );
}

function ProfileFields({
  service,
  profile,
  showApiKey,
  setShowApiKey,
  showSearchProviderWarning,
  isSupportedSearchProvider,
  isDeprecatedSearchProvider,
  searchProviderMissingKey,
  supportedSearchProviderNames,
  onProviderChanged,
}: {
  service: ServiceName;
  profile: CatalogProfile;
  showApiKey: boolean;
  setShowApiKey: (next: boolean | ((prev: boolean) => boolean)) => void;
  showSearchProviderWarning: boolean;
  isSupportedSearchProvider: boolean;
  isDeprecatedSearchProvider: boolean;
  searchProviderMissingKey: boolean;
  supportedSearchProviderNames: string;
  onProviderChanged: (
    provider: ProviderOption,
    previousProvider: string,
  ) => void;
}) {
  const { t } = useTranslation();
  const {
    draft,
    providers,
    updateProfileField: setProfileField,
    updateModelField: setModelField,
    unlinkProfile,
  } = useSettings();
  // Bound to the profile on screen. The context mutators fall back to whatever
  // is *in use* when no id is given, so editing an opened-but-inactive
  // provider here used to rewrite the active one's fields instead.
  const updateProfileField = useCallback(
    (svc: ServiceName, field: keyof CatalogProfile, value: string) =>
      setProfileField(svc, field, value, profile.id),
    [setProfileField, profile.id],
  );
  const updateModelField = useCallback(
    (svc: ServiceName, field: keyof CatalogModel, value: string) =>
      setModelField(svc, field, value, profile.id),
    [setModelField, profile.id],
  );
  const [extraOpen, setExtraOpen] = useState(false);

  // A profile fed by a connection shows its credentials but does not let them
  // be edited here: the next save would mirror the connection's values back
  // over anything typed, and a field that silently reverts is worse than one
  // that says where it comes from.
  const linkedConnection =
    (draft.connections ?? []).find(
      (item) => item.id === profile.connection_id,
    ) ?? null;

  const providerValue =
    service === "search" ? profile.provider || "" : profile.binding || "";
  const providerOption = (providers[service] || []).find(
    (option) => option.value === providerValue,
  );
  const isManagedCodex = isManagedCodexProfile(profile);
  const isCodexOAuth = isCodexOAuthProfile(
    service,
    providerValue,
    providerOption,
    profile,
  );
  const isCodeBuddyAuth = service === "llm" && providerValue === "codebuddy";
  const apiFormats = LLM_SHAPED.has(service)
    ? (providerOption?.api_formats ?? [])
    : [];
  const supportsApiFormatSelection = apiFormats.length > 1;
  const apiFormat =
    profile.api_format || providerOption?.default_api_format || "auto";
  const changeApiFormat = (next: string) => {
    updateProfileField(service, "api_format", next);
    // A vendor may serve the new format at a different endpoint (MiniMax:
    // /v1 vs /anthropic). Follow it only while the field still holds the old
    // format's default — a hand-typed URL is the user's and stays.
    const baseUrls = providerOption?.base_urls ?? {};
    const previousDefault = baseUrls[apiFormat] ?? providerOption?.base_url ?? "";
    const nextDefault = baseUrls[next] ?? providerOption?.base_url ?? "";
    const current = String(profile.base_url || "").trim();
    if (
      !linkedConnection &&
      nextDefault &&
      nextDefault !== current &&
      (!current || current === previousDefault)
    ) {
      updateProfileField(service, "base_url", nextDefault);
    }
  };

  const fields =
    isCodexOAuth || isCodeBuddyAuth
      ? { apiKey: false, baseUrl: false, baseUrlRequired: false }
      : service === "search"
        ? searchProviderFields(profile.provider, providerOption)
        : { apiKey: true, baseUrl: true, baseUrlRequired: false };
  const missingRequiredBaseUrl =
    fields.baseUrlRequired && !String(profile.base_url || "").trim();

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="sm:col-span-2">
        <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
          {t("Provider")}
        </div>
        <div className="relative">
          {providerValue && (
            <ProviderIcon
              provider={providerValue}
              size={15}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2"
            />
          )}
          <select
            className={`${selectClass} ${providerValue ? "pl-9" : ""}`}
            value={providerValue}
            disabled={isManagedCodex}
            onChange={(e) => {
              const val = e.target.value;
              const field = service === "search" ? "provider" : "binding";
              const options = providers[service] || [];
              const previousLabel =
                options.find((p) => p.value === providerValue)?.label ?? "";
              const match = options.find((p) => p.value === val);
              updateProfileField(service, field, val);
              // The new vendor may not speak the format the old one did.
              if (
                match &&
                LLM_SHAPED.has(service) &&
                !(match.api_formats ?? []).includes(profile.api_format ?? "auto")
              ) {
                updateProfileField(
                  service,
                  "api_format",
                  match.default_api_format ?? "auto",
                );
              }
              // Keep an un-customized profile name tracking its provider.
              const renamed = nextProfileName(
                profile.name,
                previousLabel,
                match?.label ?? "",
              );
              if (renamed !== profile.name) {
                updateProfileField(service, "name", renamed);
              }
              if (val === "codebuddy") {
                updateProfileField(service, "base_url", "");
                updateProfileField(service, "api_key", "");
              } else if (match?.base_url) {
                updateProfileField(service, "base_url", match.base_url);
              }
              if (match) {
                onProviderChanged(match, providerValue);
              }
              if (service === "embedding" && match?.default_dim) {
                updateModelField(service, "dimension", match.default_dim);
              }
              if (
                (service === "tts" ||
                  service === "stt" ||
                  service === "imagegen" ||
                  service === "videogen") &&
                match?.default_model
              ) {
                updateModelField(service, "model", match.default_model);
              }
              if (service === "tts" && match?.default_voice) {
                updateModelField(service, "voice", match.default_voice);
              }
            }}
          >
            <option className={selectOptionClass} value="">
              {t("Select provider...")}
            </option>
            {(providers[service] || [])
              .filter(
                (p) =>
                  p.status !== "deprecated" &&
                  (p.status !== "legacy" || p.value === providerValue),
              )
              .map((p) => (
                <option
                  className={selectOptionClass}
                  key={p.value}
                  value={p.value}
                >
                  {p.status === "legacy"
                    ? t("{{label}} (legacy)", { label: p.label })
                    : p.label}
                </option>
              ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted-foreground)]" />
        </div>
        {showSearchProviderWarning && (
          <p
            className={`mt-1.5 text-[11px] ${
              isSupportedSearchProvider
                ? "text-emerald-600 dark:text-emerald-400"
                : isDeprecatedSearchProvider
                  ? "text-amber-600 dark:text-amber-400"
                  : "text-red-500"
            }`}
          >
            {isSupportedSearchProvider
              ? searchProviderMissingKey
                ? t(
                    "{{provider}} requires an API key. It will fail hard without credentials.",
                    { provider: providerOption?.label ?? providerValue },
                  )
                : t("Supported provider.")
              : isDeprecatedSearchProvider
                ? t("Deprecated provider. Switch to one of: {{providers}}.", {
                    providers: supportedSearchProviderNames,
                  })
                : t("Unsupported provider. Use one of: {{providers}}.", {
                    providers: supportedSearchProviderNames,
                  })}
          </p>
        )}
      </div>
      {isCodexOAuth && (
        <div className="sm:col-span-2">
          <CodexOAuthCard />
        </div>
      )}
      {isCodeBuddyAuth && (
        <div className="sm:col-span-2">
          <CodeBuddyAuthCard />
        </div>
      )}
      {linkedConnection && (
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-lg border border-[var(--border)] bg-[var(--muted)]/25 px-3 py-2.5 sm:col-span-2">
          <span className="text-[11.5px] text-[var(--muted-foreground)]">
            {t("Credentials come from the {{name}} connection.", {
              name: linkedConnection.name,
            })}
          </span>
          <span className="flex items-center gap-3">
            <Link
              href="/settings#connections"
              className="inline-flex items-center gap-1 text-[11.5px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
            >
              {t("Edit connection")}
              <ArrowUpRight className="h-3 w-3" />
            </Link>
            <button
              type="button"
              onClick={() => unlinkProfile(service, profile.id)}
              className="text-[11.5px] text-[var(--muted-foreground)] underline-offset-2 transition-colors hover:text-[var(--foreground)] hover:underline"
            >
              {t("Use its own key")}
            </button>
          </span>
        </div>
      )}
      {fields.baseUrl && (
        <div className="sm:col-span-2">
          <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
            {service === "embedding" ? t("Endpoint URL") : t("Base URL")}
          </div>
          <input
            className={`${inputClass} disabled:opacity-60`}
            value={profile.base_url}
            disabled={Boolean(linkedConnection)}
            onChange={(e) =>
              updateProfileField(service, "base_url", e.target.value)
            }
            placeholder={
              service === "embedding"
                ? "https://api.openai.com/v1/embeddings"
                : service === "search"
                  ? "http://localhost:8888"
                  : "https://api.openai.com/v1"
            }
          />
          {service === "embedding" && (
            <p className="mt-1.5 text-[11px] text-[var(--muted-foreground)]">
              {t(
                "Embedding requests are sent to this URL exactly; DeepTutor does not append /embeddings or /api/embed at request time.",
              )}
            </p>
          )}
          {missingRequiredBaseUrl && (
            <p className="mt-1.5 text-[11px] text-amber-600 dark:text-amber-400">
              {t("Required — without it, search falls back to DuckDuckGo.")}
            </p>
          )}
        </div>
      )}
      {fields.apiKey && (
        <div className="sm:col-span-2">
          <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
            {t("API Key")}
          </div>
          <div className="relative">
            <input
              type={showApiKey ? "text" : "password"}
              autoComplete="new-password"
              spellCheck={false}
              className={`${inputClass} pr-10 font-mono disabled:opacity-60`}
              value={profile.api_key}
              disabled={Boolean(linkedConnection)}
              onChange={(e) =>
                updateProfileField(service, "api_key", e.target.value)
              }
              placeholder="sk-..."
            />
            <button
              type="button"
              onClick={() => setShowApiKey((prev) => !prev)}
              className="absolute right-1 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
              aria-label={showApiKey ? t("Hide API key") : t("Show API key")}
              title={showApiKey ? t("Hide API key") : t("Show API key")}
            >
              {showApiKey ? (
                <EyeOff className="h-4 w-4" />
              ) : (
                <Eye className="h-4 w-4" />
              )}
            </button>
          </div>
        </div>
      )}
      {supportsApiFormatSelection && (
        <div className="sm:col-span-2">
          <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
            {t("API format")}
          </div>
          <div className="relative">
            <select
              className={selectClass}
              value={apiFormats.includes(apiFormat) ? apiFormat : apiFormats[0]}
              onChange={(event) => changeApiFormat(event.target.value)}
            >
              {apiFormats.map((format) => (
                <option
                  className={selectOptionClass}
                  key={format}
                  value={format}
                >
                  {t(API_FORMAT_LABELS[format] ?? format)}
                </option>
              ))}
            </select>
            <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted-foreground)]" />
          </div>
          {API_FORMAT_HINTS[apiFormat] && (
            <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
              {t(API_FORMAT_HINTS[apiFormat])}
            </p>
          )}
        </div>
      )}
      {!isCodexOAuth && !isCodeBuddyAuth && (
        <div className="sm:col-span-2 rounded-xl border border-[var(--border)]/60 bg-[var(--muted)]/20">
          <button
            type="button"
            onClick={() => setExtraOpen((value) => !value)}
            className="flex w-full items-center justify-between gap-3 px-3.5 py-3 text-left"
            aria-expanded={extraOpen}
          >
            <span>
              <span className="block text-[12px] font-medium text-[var(--foreground)]">
                {t("Extra (optional)")}
              </span>
              <span className="mt-0.5 block text-[11px] text-[var(--muted-foreground)]">
                {service === "search"
                  ? t("API version and proxy")
                  : t("API version and extra request headers")}
              </span>
            </span>
            <ChevronDown
              className={`h-4 w-4 text-[var(--muted-foreground)] transition-transform ${
                extraOpen ? "rotate-180" : ""
              }`}
            />
          </button>
          {extraOpen && (
            <div className="grid gap-4 border-t border-[var(--border)]/60 px-3.5 py-4 sm:grid-cols-2">
              <div>
                <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
                  {t("API Version")}
                </div>
                <input
                  className={inputClass}
                  value={profile.api_version}
                  onChange={(e) =>
                    updateProfileField(service, "api_version", e.target.value)
                  }
                  placeholder={t("Optional")}
                />
              </div>
              {service === "search" ? (
                <div>
                  <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
                    {t("Proxy")}
                  </div>
                  <input
                    className={inputClass}
                    value={profile.proxy || ""}
                    onChange={(e) =>
                      updateProfileField(service, "proxy", e.target.value)
                    }
                    placeholder={t("http://127.0.0.1:7890 (optional)")}
                  />
                </div>
              ) : (
                <div className="sm:col-span-2">
                  <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
                    {t("Extra Headers (JSON)")}
                  </div>
                  <textarea
                    className={`${inputClass} min-h-[84px] resize-y`}
                    value={stringifyExtraHeaders(profile.extra_headers)}
                    onChange={(e) =>
                      updateProfileField(
                        service,
                        "extra_headers",
                        e.target.value,
                      )
                    }
                    placeholder='{"APP-Code":"your-app-code"}'
                  />
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
